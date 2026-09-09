"""
Centralized Error Logging and Diagnostic Engine.

Records all system, API, network, validation, and platform errors into
a structured JSONL log (error_log.jsonl) with process-safe file locking.

Accessible directly to the operator and the autonomous AI agent to diagnose
issues, inspect stack traces, and guide automated remediation.
"""
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import sys
import traceback
from typing import Any
import uuid

ERROR_LOG_PATH = "error_log.jsonl"
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


@dataclass
class SystemErrorRecord:
    """Detailed record of an error event."""

    id: str = field(default_factory=lambda: f"err_{uuid.uuid4().hex[:10]}")
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    severity: str = "ERROR"  # "WARNING" | "ERROR" | "CRITICAL"
    category: str = "SYSTEM"  # "API_ERROR" | "NETWORK_TIMEOUT" | "VALIDATION" | "AUTH" | "DEPENDENCY" | "PARSER"
    channel: str = "system"  # "rcs" | "whatsapp" | "sms" | "system"
    account: str = "all"  # "tcl_promo" | "tchfl" | "wealth" | "moneyfy" | "tcl_trans" | "all"
    error_type: str = ""
    error_message: str = ""
    module: str = ""
    function: str = ""
    stack_trace: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    remediation_hint: str | None = None
    resolved: bool = False
    resolved_by: str | None = None


def log_error(
    message: str,
    exc: BaseException | None = None,
    account: str = "all",
    channel: str = "system",
    severity: str = "ERROR",
    category: str = "SYSTEM",
    module: str = "",
    function: str = "",
    context: dict[str, Any] | None = None,
    remediation_hint: str | None = None,
    log_path: str = ERROR_LOG_PATH,
) -> SystemErrorRecord:
    """
    Record an error to the central error log.

    Automatically extracts exception type and traceback if exc or sys.exc_info() is available.
    """
    err_type = type(exc).__name__ if exc else ""
    st_text = None

    if exc:
        st_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    elif sys.exc_info()[0]:
        st_text = traceback.format_exc()
        if not err_type and sys.exc_info()[0]:
            err_type = sys.exc_info()[0].__name__

    if not module and sys.exc_info()[2]:
        tb = sys.exc_info()[2]
        while tb.tb_next:
            tb = tb.tb_next
        module = Path(tb.tb_frame.f_code.co_filename).name
        function = tb.tb_frame.f_code.co_name

    rec = SystemErrorRecord(
        severity=severity.upper(),
        category=category.upper(),
        channel=channel.lower(),
        account=account.lower(),
        error_type=err_type or "Error",
        error_message=str(message).strip(),
        module=module or "unknown",
        function=function or "unknown",
        stack_trace=st_text,
        context=context or {},
        remediation_hint=remediation_hint,
    )

    # Append to JSONL with process lock
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            _lock(f)
            try:
                f.write(json.dumps(asdict(rec)) + "\n")
                f.flush()
            finally:
                _unlock(f)
    except Exception as io_err:
        logger.error("Failed to write to error_log.jsonl: %s", io_err)

    logger.error(
        "[%s] [%s:%s] %s: %s (ID: %s)",
        rec.severity,
        rec.channel.upper(),
        rec.account,
        rec.error_type,
        rec.error_message,
        rec.id,
    )
    return rec


def load_errors(
    log_path: str = ERROR_LOG_PATH,
    account: str | None = None,
    channel: str | None = None,
    category: str | None = None,
    severity: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Load logged errors in reverse-chronological order (newest first) with optional filtering."""
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
            continue

    # Filter
    if account and account.lower() != "all":
        acc_lower = account.lower().strip()
        entries = [e for e in entries if e.get("account") in (acc_lower, "all")]
    if channel and channel.lower() != "all":
        chan_lower = channel.lower().strip()
        entries = [e for e in entries if e.get("channel") in (chan_lower, "system")]
    if category and category.lower() != "all":
        cat_lower = category.lower().strip()
        entries = [e for e in entries if str(e.get("category", "")).lower() == cat_lower]
    if severity and severity.lower() != "all":
        sev_lower = severity.lower().strip()
        entries = [e for e in entries if str(e.get("severity", "")).lower() == sev_lower]

    # Return newest first
    entries.reverse()
    return entries[:limit]


def get_error_summary(log_path: str = ERROR_LOG_PATH) -> dict[str, Any]:
    """Return summary statistics of all logged errors."""
    all_errs = load_errors(log_path, limit=10000)
    by_category: dict[str, int] = {}
    by_channel: dict[str, int] = {}
    by_severity: dict[str, int] = {}

    for e in all_errs:
        cat = e.get("category", "SYSTEM")
        by_category[cat] = by_category.get(cat, 0) + 1

        chan = e.get("channel", "system")
        by_channel[chan] = by_channel.get(chan, 0) + 1

        sev = e.get("severity", "ERROR")
        by_severity[sev] = by_severity.get(sev, 0) + 1

    return {
        "total_errors": len(all_errs),
        "by_category": by_category,
        "by_channel": by_channel,
        "by_severity": by_severity,
        "latest_error": all_errs[0] if all_errs else None,
    }
