"""
Tracker for RCS DLT template registration results.

Appends each RcsSubmissionResult to a JSONL log file.
"""

import json
from dataclasses import asdict
from pathlib import Path

from rcs_models import RcsSubmissionResult


def log_rcs_result(result: RcsSubmissionResult, log_path: str = "rcs_submission_log.jsonl") -> None:
    """Append one RCS submission result as a JSON line."""
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(result), default=str) + "\n")


def load_rcs_log(log_path: str = "rcs_submission_log.jsonl") -> list[dict]:
    """Read back all logged RCS results."""
    path = Path(log_path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def update_rcs_result(source_ref: str, updates: dict, log_path: str = "rcs_submission_log.jsonl") -> bool:
    """
    Update the log entry matching source_ref with new fields.
    Returns True if found and updated.
    """
    entries = load_rcs_log(log_path)
    found = False
    for entry in entries:
        if entry.get("source_ref") == source_ref or entry.get("template_name") == source_ref:
            entry.update(updates)
            found = True
    if found:
        with open(log_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, default=str) + "\n")
    return found
