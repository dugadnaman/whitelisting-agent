"""
Tracker: appends each SubmissionResult to a log file.

Since Phase 1 isn't running for Bajaj yet, this log is the only record of
what was submitted and what happened to it — without it, a failed
submission just disappears silently. When Phase 1 comes online for Bajaj
later, it can cross-check this log against Karix's live status export
instead of starting from nothing.
"""

import json
from dataclasses import asdict
from pathlib import Path

from models import SubmissionResult


def log_result(result: SubmissionResult, log_path: str = "submission_log.jsonl") -> None:
    """Append one result as a JSON line."""
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(result), default=str) + "\n")


def load_log(log_path: str = "submission_log.jsonl") -> list[dict]:
    """Read back all logged results (e.g. for a status summary)."""
    path = Path(log_path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
def update_result(source_ref: str, updates: dict, log_path: str = "submission_log.jsonl") -> bool:
    """
    Update the log entry matching source_ref with new fields (e.g. after a
    status poll resolves approval_status from pending to approved/rejected).

    JSONL is append-only, so an update means: read everything, patch the
    matching entry, rewrite the file. Fine at the scale this pipeline runs
    at (hundreds/thousands of rows, not millions); revisit if that changes.

    Returns True if a matching entry was found and updated.
    """
    entries = load_log(log_path)
    found = False
    for entry in entries:
        if entry["source_ref"] == source_ref:
            entry.update(updates)
            found = True
    if found:
        with open(log_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, default=str) + "\n")
    return found


def pending_entries(log_path: str = "submission_log.jsonl") -> list[dict]:
    """Entries still awaiting a final approval outcome."""
    return [
        e for e in load_log(log_path)
        if e.get("status") == "submitted" and e.get("approval_status") == "pending"
    ]
