"""
RCS Runner: wires rcs_loader -> rcs_client -> rcs_tracker together.

Entry point for submitting RCS DLT templates for configuration on Karix Lounge.
"""

import os
import sys

from rcs_client import submit_rcs_template
from rcs_loader import load_rcs_from_csv, load_rcs_from_excel, load_rcs_from_list
from rcs_tracker import log_rcs_result


def run_rcs(templates_raw: list[dict], log_path: str = "rcs_submission_log.jsonl", client: str = "bajaj", user: str = "Anonymous Operator") -> None:
    """Submit each RCS DLT template, log the attempt."""
    submissions = load_rcs_from_list(templates_raw)
    print(f"Loaded {len(submissions)} RCS template(s) for {client} to submit (by {user}).")

    for submission in submissions:
        result = submit_rcs_template(submission, client=client)
        result.submitted_by = user
        res_dict = result.__dict__ if hasattr(result, "__dict__") else {}
        res_dict["client"] = client
        res_dict["channel"] = "rcs"
        res_dict["submitted_by"] = user
        log_rcs_result(result, log_path)
        note = f" ({result.retry_count} retries)" if result.retry_count else ""
        print(f"  {result.template_name} (ID: {result.template_id}): {result.status.value}{note}")

    print(f"Done. Results appended to {log_path}")


def run_rcs_file(file_path: str, log_path: str = "rcs_submission_log.jsonl", client: str = "bajaj", user: str = "Anonymous Operator") -> None:
    """Load RCS templates from CSV or Excel file, submit each, and log attempt."""
    if file_path.lower().endswith((".xlsx", ".xls")):
        submissions = load_rcs_from_excel(file_path)
    else:
        submissions = load_rcs_from_csv(file_path)

    print(f"Loaded {len(submissions)} RCS template(s) for {client} from {file_path} to submit (by {user}).")

    for submission in submissions:
        result = submit_rcs_template(submission, client=client)
        result.submitted_by = user
        res_dict = result.__dict__ if hasattr(result, "__dict__") else {}
        res_dict["client"] = client
        res_dict["channel"] = "rcs"
        res_dict["submitted_by"] = user
        log_rcs_result(result, log_path)
        note = f" ({result.retry_count} retries)" if result.retry_count else ""
        err_msg = f" - Error: {result.error}" if result.error and result.status.value != "submitted" else ""
        print(f"  {result.template_name} (ID: {result.template_id}): {result.status.value}{note}{err_msg}")
    print(f"Done. Results appended to {log_path}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and not args[0].startswith("-"):
        target_file = " ".join(args)
        if not os.path.exists(target_file) and os.path.exists(args[0]):
            target_file = args[0]
        run_rcs_file(target_file)
    else:
        print("Usage:")
        print("  python3 rcs_runner.py rcs_templates_sample.csv")
        print("  python3 rcs_runner.py rcs_templates.xlsx")
