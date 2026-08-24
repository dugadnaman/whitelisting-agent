"""
Tracker for RCS template registration results.

Appends each RcsSubmissionResult to a JSONL log file. Mirrors tracker.py:
locked appends, single-pass locked batch updates, corrupt-line tolerance.
"""

import json
import logging
from dataclasses import asdict
from pathlib import Path

from rcs_models import RcsSubmissionResult

logger = logging.getLogger(__name__)

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
            logger.warning("Skipping corrupt JSONL line in %s", log_path)
    return entries


def log_rcs_result(result: RcsSubmissionResult, log_path: str = "rcs_submission_log.jsonl") -> None:
    """Append one RCS submission result as a JSON line."""
    with open(log_path, "a", encoding="utf-8") as f:
        _lock(f)
        try:
            f.write(json.dumps(asdict(result), default=str) + "\n")
        finally:
            _unlock(f)


def load_rcs_log(log_path: str = "rcs_submission_log.jsonl") -> list[dict]:
    """Read back all logged RCS results."""
    return _read_lines(log_path)


def update_rcs_result(source_ref: str, updates: dict, log_path: str = "rcs_submission_log.jsonl") -> bool:
    """Patch one entry (matched by source_ref or template_name). Returns True if found."""
    return update_rcs_results({source_ref: updates}, log_path) == 1


def update_rcs_results(updates_by_ref: dict, log_path: str = "rcs_submission_log.jsonl") -> int:
    """Apply many updates in ONE locked read-modify-write pass. Returns updated count."""
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
        Path(tmp_path).replace(log_path)
    return updated
