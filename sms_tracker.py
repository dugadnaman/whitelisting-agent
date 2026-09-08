"""
Tracker for SMS submissions, Delivery Reports (DLR), and Click Tracking.

Maintains JSONL log files with process-safe file locking (fcntl):
- sms_submission_log.jsonl: Record of sent SMS batches and individual messages
- sms_dlr_log.jsonl: Record of webhook callbacks received from Karix
- sms_click_log.jsonl: Record of link clicks reported by Karix
"""

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sms_models import SmsClickReport, SmsDlrReport, SmsSubmissionResult

logger = logging.getLogger(__name__)

try:
    import fcntl

    def _lock(f):
        fcntl.flock(f, fcntl.LOCK_EX)

    def _unlock(f):
        fcntl.flock(f, fcntl.LOCK_UN)
except ImportError:  # pragma: no cover — Windows fallback

    def _lock(f):
        pass

    def _unlock(f):
        pass


def _read_jsonl(log_path: str) -> list[dict[str, Any]]:
    """Read all valid JSON lines from a JSONL file, ignoring corrupt lines."""
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
            logger.warning("Skipping corrupt JSON line in %s", log_path)
    return entries


def log_sms_submission(
    result: SmsSubmissionResult,
    log_path: str = "sms_submission_log.jsonl",
) -> None:
    """Append one SMS submission outcome as a JSON line."""
    record = asdict(result)
    with open(log_path, "a", encoding="utf-8") as f:
        _lock(f)
        try:
            f.write(json.dumps(record) + "\n")
            f.flush()
        finally:
            _unlock(f)


def load_sms_submissions(
    log_path: str = "sms_submission_log.jsonl",
    client: str | None = None,
) -> list[dict[str, Any]]:
    """Load logged SMS submissions, optionally filtered by client."""
    entries = _read_jsonl(log_path)
    if client and client.lower() != "all":
        c_lower = client.lower()
        return [e for e in entries if str(e.get("client", "")).lower() == c_lower]
    return entries


def log_sms_dlr(
    report: SmsDlrReport,
    log_path: str = "sms_dlr_log.jsonl",
) -> None:
    """Append one SMS DLR callback report as a JSON line."""
    record = asdict(report)
    with open(log_path, "a", encoding="utf-8") as f:
        _lock(f)
        try:
            f.write(json.dumps(record) + "\n")
            f.flush()
        finally:
            _unlock(f)


def load_sms_dlrs(
    log_path: str = "sms_dlr_log.jsonl",
    client: str | None = None,
    ackid: str | None = None,
) -> list[dict[str, Any]]:
    """Load logged SMS DLR reports, optionally filtered by client or ackid."""
    entries = _read_jsonl(log_path)
    if client and client.lower() != "all":
        c_lower = client.lower()
        entries = [e for e in entries if str(e.get("client", "")).lower() == c_lower]
    if ackid:
        ack_str = str(ackid).strip()
        entries = [e for e in entries if str(e.get("ackid", "")).strip() == ack_str]
    return entries


def log_sms_click(
    report: SmsClickReport,
    log_path: str = "sms_click_log.jsonl",
) -> None:
    """Append one SMS click report as a JSON line."""
    record = asdict(report)
    with open(log_path, "a", encoding="utf-8") as f:
        _lock(f)
        try:
            f.write(json.dumps(record) + "\n")
            f.flush()
        finally:
            _unlock(f)


def load_sms_clicks(
    log_path: str = "sms_click_log.jsonl",
    client: str | None = None,
) -> list[dict[str, Any]]:
    """Load logged SMS click reports, optionally filtered by client."""
    entries = _read_jsonl(log_path)
    if client and client.lower() != "all":
        c_lower = client.lower()
        return [e for e in entries if str(e.get("client", "")).lower() == c_lower]
    return entries


def get_sms_stats(
    client: str | None = None,
    submission_log_path: str = "sms_submission_log.jsonl",
    dlr_log_path: str = "sms_dlr_log.jsonl",
    click_log_path: str = "sms_click_log.jsonl",
) -> dict[str, Any]:
    """
    Calculate consolidated statistics for SMS operations:
    - Total submissions and recipients
    - Delivery outcomes (Delivered, Failed, Rejected, Pending)
    - Click events
    - Delivery rate percentage
    """
    submissions = load_sms_submissions(submission_log_path, client=client)
    dlrs = load_sms_dlrs(dlr_log_path, client=client)
    clicks = load_sms_clicks(click_log_path, client=client)

    total_submissions = len(submissions)
    total_recipients = sum(int(s.get("dest_count", 0)) for s in submissions)
    accepted_submissions = sum(1 for s in submissions if s.get("status_code") == "200")
    failed_submissions = total_submissions - accepted_submissions

    delivered = 0
    failed = 0
    rejected = 0
    other_dlr = 0

    for d in dlrs:
        flag = str(d.get("status_flag") or "").strip().lower()
        reason = str(d.get("reason") or "").strip().lower()
        if flag == "success" or reason == "delivered":
            delivered += 1
        elif flag == "failed" or "fail" in reason:
            failed += 1
        elif flag == "rejected" or "reject" in reason:
            rejected += 1
        else:
            other_dlr += 1

    total_dlrs = len(dlrs)
    pending = max(0, total_recipients - (delivered + failed + rejected))
    delivery_rate = round((delivered / total_recipients * 100), 2) if total_recipients > 0 else 0.0

    return {
        "client": client or "all",
        "channel": "sms",
        "total_submissions": total_submissions,
        "total_recipients": total_recipients,
        "accepted_submissions": accepted_submissions,
        "failed_submissions": failed_submissions,
        "dlr_count": total_dlrs,
        "delivered": delivered,
        "failed": failed,
        "rejected": rejected,
        "pending": pending,
        "clicks": len(clicks),
        "delivery_rate": delivery_rate,
    }
