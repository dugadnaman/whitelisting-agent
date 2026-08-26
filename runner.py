"""
Runner: wires loader -> client -> tracker together for WhatsApp templates.

Phase 2, step 1: submit each template and log the attempt.
Phase 2, step 2: poll approval status for everything still pending.

Efficiency notes (post-audit):
  * poll_pending fetches the WABA template list ONCE per poll and resolves
    every pending entry in memory — previously it fetched the full list per
    entry (N+1 remote calls).
  * All status updates are applied with a single locked batch write via
    tracker.update_results — previously each entry triggered a whole-file
    read-modify-write.
  * Transient transport failures never write "unknown" into the log; entries
    stay "pending" so a later poll retries them.
"""

import collections
from datetime import UTC, datetime
from pathlib import Path

from config import get_waba_id
from loader import load_from_list
from models import ApprovalStatus
from submission_client import (
    _STATUS_MAP,
    _match_template,
    fetch_template_list,
    submit_template,
)
from tracker import log_result, pending_entries, update_results

# Approval outcomes worth persisting. Anything else (transport errors,
# not-yet-listed templates, unknown provider states) keeps the entry pending.
_TERMINAL_STATUSES = {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}

CATEGORY_APPROVAL_SLAS = {
    "AUTHENTICATION": {"initial_delay_sec": 60, "poll_interval_sec": 60, "avg_approval_sec": 120, "label": "Authentication (Auto)"},
    "UTILITY": {"initial_delay_sec": 120, "poll_interval_sec": 120, "avg_approval_sec": 240, "label": "Utility (Fast ~3m)"},
    "MARKETING_TEXT": {"initial_delay_sec": 600, "poll_interval_sec": 300, "avg_approval_sec": 1200, "label": "Marketing Text (~15m)"},
    "MARKETING_MEDIA": {"initial_delay_sec": 1200, "poll_interval_sec": 600, "avg_approval_sec": 2400, "label": "Marketing Media (~35m)"},
    "DEFAULT": {"initial_delay_sec": 300, "poll_interval_sec": 300, "avg_approval_sec": 900, "label": "Standard (~10m)"},
}


def classify_template_category_sla(entry: dict) -> tuple[str, dict]:
    """Classify a pending template into its SLA tier based on category and media header."""
    pr = entry.get("provider_response") if isinstance(entry.get("provider_response"), dict) else {}
    cat = str(entry.get("category") or pr.get("category", "MARKETING")).upper()
    has_media = False

    comps = entry.get("components") or pr.get("components", []) or []
    for c in comps:
        comp_d = c if isinstance(c, dict) else getattr(c, "__dict__", {})
        if comp_d.get("type") == "HEADER" and str(comp_d.get("format", "")).upper() in ("IMAGE", "VIDEO", "DOCUMENT"):
            has_media = True
            break

    if "AUTH" in cat:
        tier = "AUTHENTICATION"
    elif "UTIL" in cat:
        tier = "UTILITY"
    elif has_media or "MEDIA" in cat:
        tier = "MARKETING_MEDIA"
    elif "MARKET" in cat:
        tier = "MARKETING_TEXT"
    else:
        tier = "DEFAULT"

    return tier, CATEGORY_APPROVAL_SLAS[tier]


def get_pending_templates_sla_insights(log_path: str = "submission_log.jsonl", client: str = "bajaj") -> dict:
    """
    Procedural Memory: Evaluate pending templates against their SLA windows.
    Returns SLA countdowns, due-for-poll items, and recommended next poll time.
    """
    c = client.lower()
    pending = [e for e in pending_entries(log_path) if (e.get("client", "bajaj") or "bajaj").lower() == c]
    if not pending:
        return {
            "pending_count": 0,
            "due_for_poll_count": 0,
            "categories": {},
            "next_recommended_poll_sec": 120,
            "templates_status": [],
        }

    now = datetime.now(UTC)
    due_items = []
    category_counts: dict[str, int] = collections.defaultdict(int)
    details = []

    for entry in pending:
        tier, sla = classify_template_category_sla(entry)
        category_counts[sla["label"]] += 1

        submitted_at_str = entry.get("submitted_at")
        age_sec = 0.0
        if submitted_at_str:
            try:
                sub_time = datetime.fromisoformat(submitted_at_str.replace("Z", "+00:00"))
                age_sec = (now - sub_time).total_seconds()
            except Exception:
                age_sec = 0.0

        est_remaining_sec = max(0, int(sla["avg_approval_sec"] - age_sec))
        is_due = age_sec >= sla["initial_delay_sec"]

        if is_due:
            due_items.append(entry)

        details.append({
            "template_name": entry.get("template_name"),
            "category_tier": tier,
            "category_label": sla["label"],
            "age_sec": int(age_sec),
            "estimated_remaining_sec": est_remaining_sec,
            "is_due_for_poll": is_due,
        })

    remaining_times = [d["estimated_remaining_sec"] for d in details if d["estimated_remaining_sec"] > 0]
    next_poll = min(remaining_times) if remaining_times else 60
    next_poll = max(15, min(300, next_poll))

    return {
        "pending_count": len(pending),
        "due_for_poll_count": len(due_items),
        "categories": dict(category_counts),
        "next_recommended_poll_sec": next_poll,
        "templates_status": details[:10],
    }

def run(
    templates_raw: list[dict],
    log_path: str = "submission_log.jsonl",
    client: str = "bajaj",
    user: str = "Anonymous Operator",
    source_file: str | None = None,
    fix_aspect_ratio: bool = True,
    fix_grammar: bool = True,
) -> None:
    """Phase 2, step 1: submit each template, log the attempt."""
    import concurrent.futures
    import time
    from submission_client import _GOVERNOR

    submissions = load_from_list(templates_raw, client=client)
    optimal_workers = _GOVERNOR.get_optimal_concurrency(base_workers=min(8, max(1, len(submissions))))
    workers = min(optimal_workers, max(1, len(submissions)))
    pacing = _GOVERNOR.get_pacing_delay()

    health = _GOVERNOR.get_health_stats()
    print(
        f"Submitting {len(submissions)} template(s) for {client} (by {user}) "
        f"[Concurrency: {workers} workers, Pacing: {pacing}s, Karix API: {health['status']} ({health['avg_latency_sec']}s)]..."
    )

    def _submit_single(submission):
        submission.client = client
        submission.waba_id = get_waba_id(client)
        if pacing > 0:
            time.sleep(pacing)
        result = submit_template(
            submission,
            client=client,
            fix_aspect_ratio=fix_aspect_ratio,
            fix_grammar=fix_grammar,
        )
        result.client = client
        result.channel = "whatsapp"
        result.submitted_by = user
        result.source_file = source_file or result.source_file
        log_result(result, log_path)
        note = f" ({result.retry_count} retries)" if result.retry_count else ""
        print(f"  {result.template_name}: {result.status.value}{note}")
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(_submit_single, submissions))

    print(f"Done. Results appended to {log_path}")


def poll_pending(log_path: str = "submission_log.jsonl", client: str = "bajaj") -> dict:
    """
    Phase 2, step 2: check approval status for everything still pending.

    ONE remote fetch + ONE batch write, regardless of how many entries are
    pending. Returns a summary dictionary including procedural SLA insights.
    """
    c = client.lower()
    to_check = [e for e in pending_entries(log_path) if (e.get("client", "bajaj") or "bajaj").lower() == c]
    if not to_check:
        print(f"Nothing pending for {client}.")
        return {
            "checked": 0,
            "updated": 0,
            "pending": 0,
            "insights": get_pending_templates_sla_insights(log_path, client=c),
        }

    print(f"Checking {len(to_check)} pending template(s) for {client}...")

    templates, err = fetch_template_list(c)
    if err is not None:
        # Do NOT write anything: a later poll will retry every entry.
        print(f"  Poll deferred for {client}: {err}")
        return {
            "checked": len(to_check),
            "updated": 0,
            "pending": len(to_check),
            "error": str(err),
            "insights": get_pending_templates_sla_insights(log_path, client=c),
        }

    now = datetime.now(UTC).isoformat()
    updates: dict[str, dict] = {}
    for entry in to_check:
        ref = entry["source_ref"]
        matched = _match_template(templates, entry["provider_ref_id"])
        if matched is None:
            print(f"  {entry['template_name']}: not on WABA yet (stays pending)")
            continue

        raw_status = str(matched.get("template_create_status", "")).upper()
        status = _STATUS_MAP.get(raw_status, ApprovalStatus.UNKNOWN)

        if status in _TERMINAL_STATUSES:
            updates[ref] = {
                "approval_status": status.value,
                "approval_reason": matched.get("template_status_reason"),
                "provider_response": matched,
                "updated_at": now,
            }
            print(f"  {entry['template_name']}: {status.value}")
        else:
            # PENDING or unknown provider state — keep pollable.
            print(f"  {entry['template_name']}: {status.value} (kept pending)")

    updated = 0
    if updates:
        updated = update_results(updates, log_path)
        print(f"Applied {updated} status update(s).")

    return {
        "checked": len(to_check),
        "updated": updated,
        "pending": len(to_check) - updated,
        "insights": get_pending_templates_sla_insights(log_path, client=c),
    }

def run_file(
    file_path: str,
    log_path: str = "submission_log.jsonl",
    client: str = "bajaj",
    user: str = "Anonymous Operator",
    fix_aspect_ratio: bool = True,
    fix_grammar: bool = True,
) -> None:
    """Phase 2, step 1 (from CSV or XLSX): load templates from file, submit in parallel pool, log results."""
    import concurrent.futures
    import time
    from loader import load_from_csv, load_from_excel
    from submission_client import _GOVERNOR

    if file_path.lower().endswith((".xlsx", ".xls")):
        submissions = load_from_excel(file_path, client=client)
    else:
        submissions = load_from_csv(file_path, client=client)

    optimal_workers = _GOVERNOR.get_optimal_concurrency(base_workers=min(8, max(1, len(submissions))))
    workers = min(optimal_workers, max(1, len(submissions)))
    pacing = _GOVERNOR.get_pacing_delay()

    print(
        f"Loaded {len(submissions)} template(s) for {client} from {file_path} to submit (by {user}) "
        f"[Concurrency: {workers} workers, Pacing: {pacing}s]..."
    )

    def _submit_single(submission):
        submission.client = client
        if pacing > 0:
            time.sleep(pacing)
        result = submit_template(
            submission,
            client=client,
            fix_aspect_ratio=fix_aspect_ratio,
            fix_grammar=fix_grammar,
        )
        result.client = client
        result.channel = "whatsapp"
        result.submitted_by = user
        result.source_file = Path(file_path).name
        log_result(result, log_path)
        note = f" ({result.retry_count} retries)" if result.retry_count else ""
        print(f"  {result.template_name}: {result.status.value}{note}")
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(_submit_single, submissions))

    print(f"Done. Results appended to {log_path}")

if __name__ == "__main__":
    import os
    import sys

    args = sys.argv[1:]
    if "--poll" in args:
        poll_pending()
    elif args and not args[0].startswith("-"):
        # If the user passed an unquoted filename with spaces (e.g. templates_sample 4.xlsx),
        # join the arguments back into a single path string.
        target_file = " ".join(args)
        if not os.path.exists(target_file) and os.path.exists(args[0]):
            target_file = args[0]
        run_file(target_file)
    else:
        print("Usage:")
        print("  python3 runner.py templates.xlsx          # Submit templates from Excel")
        print("  python3 runner.py templates_sample.csv   # Submit templates from CSV")
        print("  python3 runner.py --poll                 # Poll approval status of pending templates")
