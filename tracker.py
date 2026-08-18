"""
Tracker: appends each SubmissionResult to a JSONL log file.

The log is the only record of what was submitted and what happened to it.
JSONL is append-only for writes; updates are rare (status polls) and are
performed as a single locked read-modify-write so concurrent pollers can
never interleave and corrupt the file.
"""

import json
import logging
from dataclasses import asdict
from pathlib import Path

from models import SubmissionResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# File locking helpers (POSIX; no-op fallback elsewhere so imports never fail)
# ---------------------------------------------------------------------------

try:
    import fcntl

    def _lock(f):
        fcntl.flock(f, fcntl.LOCK_EX)

    def _unlock(f):
        fcntl.flock(f, fcntl.LOCK_UN)
except ImportError:  # pragma: no cover — Windows
    def _lock(f):
        pass

    def _unlock(f):
        pass


def _read_lines(log_path: str) -> list[dict]:
    """Read all valid JSON records, skipping (not crashing on) corrupt lines."""
    path = Path(log_path)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            # A torn write must not take down the dashboard or the poller.
            logger.warning("Skipping corrupt JSONL line in %s", log_path)
    return entries


def log_result(result: SubmissionResult, log_path: str = "submission_log.jsonl") -> None:
    """Append one result as a JSON line (append-only, locked)."""
    with open(log_path, "a", encoding="utf-8") as f:
        _lock(f)
        try:
            f.write(json.dumps(asdict(result), default=str) + "\n")
        finally:
            _unlock(f)


def load_log(log_path: str = "submission_log.jsonl") -> list[dict]:
    """Read back all logged results (e.g. for a status summary)."""
    return _read_lines(log_path)


def update_result(source_ref: str, updates: dict, log_path: str = "submission_log.jsonl") -> bool:
    """Patch one entry (matched by source_ref or template_name). Returns True if found."""
    return update_results({source_ref: updates}, log_path) == 1


def update_results(updates_by_ref: dict, log_path: str = "submission_log.jsonl") -> int:
    """
    Apply many updates in ONE locked read-modify-write pass.

    Keys of `updates_by_ref` are matched against both `source_ref` and
    `template_name` (historical entries used either). Returns the number of
    entries updated. This replaces the previous per-entry whole-file rewrite,
    which was O(entries x file_size) on every poll.
    """
    if not updates_by_ref:
        return 0

    entries = _read_lines(log_path)
    updated = 0
    for entry in entries:
        ref = entry.get("source_ref") or entry.get("template_name")
        if ref in updates_by_ref:
            entry.update(updates_by_ref[ref])
            updated += 1

    if updated:
        tmp_path = f"{log_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            _lock(f)
            try:
                for entry in entries:
                    f.write(json.dumps(entry, default=str) + "\n")
                f.flush()
            finally:
                _unlock(f)
        Path(tmp_path).replace(log_path)  # atomic on POSIX
    return updated


def pending_entries(log_path: str = "submission_log.jsonl") -> list[dict]:
    """Entries still awaiting a final approval outcome."""
    return [
        e for e in load_log(log_path)
        if e.get("status") == "submitted" and e.get("approval_status") == "pending"
    ]
