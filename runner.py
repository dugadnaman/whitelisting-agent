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

from datetime import datetime, timezone
from pathlib import Path

from loader import load_from_list
from models import ApprovalStatus
from submission_client import _STATUS_MAP, _match_template, fetch_template_list, submit_template
from tracker import log_result, pending_entries, update_results

# Approval outcomes worth persisting. Anything else (transport errors,
# not-yet-listed templates, unknown provider states) keeps the entry pending.
_TERMINAL_STATUSES = {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}


def run(templates_raw: list[dict], log_path: str = "submission_log.jsonl", client: str = "bajaj", user: str = "Anonymous Operator", source_file: str | None = None, fix_aspect_ratio: bool = True, fix_grammar: bool = True) -> None:
    """Phase 2, step 1: submit each template, log the attempt."""
    submissions = load_from_list(templates_raw)
    print(f"Submitting {len(submissions)} template(s) for {client} (by {user})...")

    for submission in submissions:
        submission.client = client
        result = submit_template(submission, client=client, fix_aspect_ratio=fix_aspect_ratio, fix_grammar=fix_grammar)
        result.client = client
        result.channel = "whatsapp"
        result.submitted_by = user
        result.source_file = source_file or result.source_file
        log_result(result, log_path)
        note = f" ({result.retry_count} retries)" if result.retry_count else ""
        print(f"  {result.template_name}: {result.status.value}{note}")

    print(f"Done. Results appended to {log_path}")


def poll_pending(log_path: str = "submission_log.jsonl", client: str = "bajaj") -> None:
    """
    Phase 2, step 2: check approval status for everything still pending.

    ONE remote fetch + ONE batch write, regardless of how many entries are
    pending. Transient failures leave entries pollable for the next run.
    """
    c = client.lower()
    to_check = [
        e for e in pending_entries(log_path)
        if (e.get("client", "bajaj") or "bajaj").lower() == c
    ]
    if not to_check:
        print(f"Nothing pending for {client}.")
        return

    print(f"Checking {len(to_check)} pending template(s) for {client}...")

    templates, err = fetch_template_list(c)
    if err is not None:
        # Do NOT write anything: a later poll will retry every entry.
        print(f"  Poll deferred for {client}: {err}")
        return

    now = datetime.now(timezone.utc).isoformat()
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

    if updates:
        updated = update_results(updates, log_path)
        print(f"Applied {updated} status update(s).")


def run_file(file_path: str, log_path: str = "submission_log.jsonl", client: str = "bajaj", user: str = "Anonymous Operator", fix_aspect_ratio: bool = True, fix_grammar: bool = True) -> None:
    """Phase 2, step 1 (from CSV or XLSX): load templates from file, submit each, log attempt."""
    from loader import load_from_csv, load_from_excel

    if file_path.lower().endswith((".xlsx", ".xls")):
        submissions = load_from_excel(file_path, client=client)
    else:
        submissions = load_from_csv(file_path, client=client)

    print(f"Loaded {len(submissions)} template(s) for {client} from {file_path} to submit (by {user}).")

    for submission in submissions:
        submission.client = client
        result = submit_template(submission, client=client, fix_aspect_ratio=fix_aspect_ratio, fix_grammar=fix_grammar)
        result.channel = "whatsapp"
        result.submitted_by = user
        result.source_file = Path(file_path).name
        log_result(result, log_path)
        note = f" ({result.retry_count} retries)" if result.retry_count else ""
        print(f"  {result.template_name}: {result.status.value}{note}")

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
