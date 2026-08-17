"""
Runner: wires loader -> submission_client -> tracker together.

This is the entry point. It doesn't change tomorrow either — only
submission_client.py does.
"""

from datetime import datetime, timezone

from loader import load_from_list
from submission_client import check_status, submit_template
from tracker import log_result, pending_entries, update_result


def run(templates_raw: list[dict], log_path: str = "submission_log.jsonl", client: str = "bajaj") -> None:
    """Phase 2, step 1: submit each template, log the attempt."""
    submissions = load_from_list(templates_raw)
    for s in submissions:
        s.client = client
    print(f"Loaded {len(submissions)} template(s) for {client} to submit.")

    for submission in submissions:
        result = submit_template(submission, client=client)
        res_dict = result.__dict__ if hasattr(result, "__dict__") else {}
        res_dict["client"] = client
        res_dict["channel"] = "whatsapp"
        log_result(result, log_path)
        note = f" ({result.retry_count} retries)" if result.retry_count else ""
        print(f"  {result.template_name}: {result.status.value}{note}")

    print(f"Done. Results appended to {log_path}")


def poll_pending(log_path: str = "submission_log.jsonl", client: str = "bajaj") -> None:
    """
    Phase 2, step 2: check approval status for everything still pending for the client.
    """
    c = client.lower()
    all_pending = pending_entries(log_path)
    to_check = [
        e for e in all_pending
        if (e.get("client", "bajaj") or "bajaj").lower() == c
    ]
    if not to_check:
        print(f"Nothing pending for {client}.")
        return

    print(f"Checking {len(to_check)} pending template(s) for {client}...")
    for entry in to_check:
        approval_status, reason, raw = check_status(entry["provider_ref_id"], client=client)
        update_result(
            entry["source_ref"],
            {
                "approval_status": approval_status.value,
                "approval_reason": reason,
                "provider_response": raw,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            log_path,
        )
        print(f"  {entry['template_name']}: {approval_status.value}")

def run_file(file_path: str, log_path: str = "submission_log.jsonl", client: str = "bajaj") -> None:
    """Phase 2, step 1 (from CSV or XLSX): load templates from file, submit each, log attempt."""
    from loader import load_from_csv, load_from_excel

    if file_path.lower().endswith((".xlsx", ".xls")):
        submissions = load_from_excel(file_path)
    else:
        submissions = load_from_csv(file_path)

    for s in submissions:
        s.client = client

    print(f"Loaded {len(submissions)} template(s) for {client} from {file_path} to submit.")

    for submission in submissions:
        result = submit_template(submission, client=client)
        res_dict = result.__dict__ if hasattr(result, "__dict__") else {}
        res_dict["client"] = client
        res_dict["channel"] = "whatsapp"
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

