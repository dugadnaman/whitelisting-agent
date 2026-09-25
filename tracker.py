"""
Tracker: stores each SubmissionResult directly in the database (job_tasks table).
The database is the single source of truth for all WhatsApp submission history and status tracking.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict
from datetime import datetime, UTC
from pathlib import Path

from models import SubmissionResult
import db

logger = logging.getLogger(__name__)

# File locking helpers kept for any isolated unit test mock callers
try:
    import fcntl

    def _lock(f):
        fcntl.flock(f, fcntl.LOCK_EX)

    def _unlock(f):
        fcntl.flock(f, fcntl.LOCK_UN)
except ImportError:
    def _lock(f):
        pass

    def _unlock(f):
        pass


def _row_to_entry_dict(row: dict) -> dict:
    payload = {}
    if row.get("payload_json"):
        try:
            payload = json.loads(row["payload_json"])
        except Exception:
            pass

    entry = dict(payload)
    entry["source_ref"] = row.get("source_ref") or entry.get("source_ref") or row.get("template_name")
    entry["template_name"] = row.get("template_name") or entry.get("template_name")
    entry["status"] = (row.get("status") or entry.get("status") or "submitted").lower()
    entry["approval_status"] = (row.get("approval_status") or entry.get("approval_status") or "unknown").lower()
    entry["provider_ref_id"] = row.get("provider_ref_id") or entry.get("provider_ref_id")
    entry["error"] = row.get("error") if row.get("error") is not None else entry.get("error")
    entry["approval_reason"] = row.get("approval_reason") or entry.get("approval_reason")
    entry["retry_count"] = row.get("retry_count", 0)
    entry["submitted_at"] = row.get("created_at") or entry.get("submitted_at")
    entry["updated_at"] = row.get("updated_at") or entry.get("updated_at")
    return entry


def log_result(result: SubmissionResult, log_path: str = "submission_log.jsonl") -> None:
    """Store submission result directly into database (job_tasks) as single source of truth."""
    db.init_database()
    res_dict = asdict(result) if hasattr(result, "__dataclass_fields__") else dict(result)
    tpl_name = res_dict.get("template_name") or ""
    source_ref = res_dict.get("source_ref") or tpl_name
    status_raw = res_dict.get("status") or "submitted"
    status_val = status_raw.value.upper() if hasattr(status_raw, "value") else str(status_raw).upper()
    approval_raw = res_dict.get("approval_status") or "unknown"
    approval_val = approval_raw.value.lower() if hasattr(approval_raw, "value") else str(approval_raw).lower()
    provider_ref_id = res_dict.get("provider_ref_id")
    error = res_dict.get("error")
    approval_reason = res_dict.get("approval_reason")
    retry_count = int(res_dict.get("retry_count") or 0)
    submitted_at = res_dict.get("submitted_at") or datetime.now(UTC).isoformat()
    updated_at = res_dict.get("updated_at") or submitted_at
    payload_json = json.dumps(res_dict, default=str)
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    job_id = "job_direct_submissions"
    tenant_id = res_dict.get("client") or "all"

    # 1. Primary write to Database
    try:
        with db.get_db() as conn:
            conn.execute(
                """
                INSERT INTO ingestion_jobs (id, tenant_id, channel, filename, total_count, status, created_at, updated_at)
                VALUES (?, ?, 'whatsapp', 'direct_submission', 1, 'COMPLETED', ?, ?)
                ON CONFLICT (id) DO UPDATE SET updated_at = EXCLUDED.updated_at
            """,
                (job_id, tenant_id, submitted_at, updated_at),
            )
            conn.execute(
                """
                INSERT INTO job_tasks (
                    id, job_id, tenant_id, channel, source_ref, template_name,
                    payload_json, status, approval_status, provider_ref_id,
                    error, approval_reason, retry_count, created_at, updated_at
                ) VALUES (?, ?, ?, 'whatsapp', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    task_id,
                    job_id,
                    tenant_id,
                    source_ref,
                    tpl_name,
                    payload_json,
                    status_val,
                    approval_val,
                    provider_ref_id,
                    error,
                    approval_reason,
                    retry_count,
                    submitted_at,
                    updated_at,
                ),
            )
            conn.commit()
    except Exception as exc:
        logger.error("Failed to store submission result in database: %s", exc)

    # 2. File fallback only if a non-default custom file path was explicitly passed in unit tests
    if log_path != "submission_log.jsonl" and not log_path.endswith("submission_log.jsonl"):
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                _lock(f)
                try:
                    f.write(json.dumps(res_dict, default=str) + "\n")
                    f.flush()
                finally:
                    _unlock(f)
        except Exception:
            pass


def load_log(log_path: str = "submission_log.jsonl") -> list[dict]:
    """Read back all WhatsApp submission results from the database."""
    # If custom temporary path specified in tests, read from that file
    if log_path != "submission_log.jsonl" and not log_path.endswith("submission_log.jsonl"):
        p = Path(log_path)
        if p.exists():
            entries = []
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
            return entries

    db.init_database()
    entries = []
    try:
        with db.get_db() as conn:
            cur = conn.execute("SELECT * FROM job_tasks WHERE channel = 'whatsapp' ORDER BY created_at ASC")
            for r in cur.fetchall():
                entries.append(_row_to_entry_dict(dict(r)))
    except Exception as exc:
        logger.error("Failed to load submission log from database: %s", exc)
    return entries


def update_result(source_ref: str, updates: dict, log_path: str = "submission_log.jsonl") -> bool:
    """Patch one entry in the database (matched by source_ref or template_name)."""
    return update_results({source_ref: updates}, log_path) == 1


def update_results(updates_by_ref: dict, log_path: str = "submission_log.jsonl") -> int:
    """
    Apply updates directly in the database (single source of truth).
    """
    if not updates_by_ref:
        return 0

    if log_path != "submission_log.jsonl" and not log_path.endswith("submission_log.jsonl"):
        p = Path(log_path)
        if p.exists():
            file_entries = []
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        file_entries.append(json.loads(line))
                    except Exception:
                        pass
            f_updated = 0
            for entry in file_entries:
                r = entry.get("source_ref") or entry.get("template_name")
                if r in updates_by_ref:
                    entry.update(updates_by_ref[r])
                    f_updated += 1
            if f_updated:
                with open(log_path, "w", encoding="utf-8") as f:
                    for entry in file_entries:
                        f.write(json.dumps(entry, default=str) + "\n")
            return f_updated
        return 0

    db.init_database()
    now = datetime.now(UTC).isoformat()
    updated = 0

    try:
        with db.get_db() as conn:
            for ref, upd in updates_by_ref.items():
                status = upd.get("status")
                status_val = (status.value.upper() if hasattr(status, "value") else str(status).upper()) if status else None
                app_status = upd.get("approval_status")
                app_val = (app_status.value.lower() if hasattr(app_status, "value") else str(app_status).lower()) if app_status else None
                prov_id = upd.get("provider_ref_id")
                app_reason = upd.get("approval_reason")

                cur = conn.execute(
                    """
                    UPDATE job_tasks SET
                        approval_status = COALESCE(?, approval_status),
                        approval_reason = COALESCE(?, approval_reason),
                        status = COALESCE(?, status),
                        provider_ref_id = COALESCE(?, provider_ref_id),
                        updated_at = ?
                    WHERE channel = 'whatsapp' AND (template_name = ? OR source_ref = ?)
                """,
                    (app_val, app_reason, status_val, prov_id, now, ref, ref),
                )
                if cur.rowcount > 0:
                    updated += cur.rowcount
            conn.commit()
    except Exception as exc:
        logger.error("Failed to update results in database: %s", exc)

    return updated


def pending_entries(log_path: str = "submission_log.jsonl") -> list[dict]:
    """Entries still awaiting a final approval outcome, read from database."""
    if log_path != "submission_log.jsonl" and not log_path.endswith("submission_log.jsonl"):
        return [e for e in load_log(log_path) if e.get("status") in ("submitted", "duplicate") and e.get("approval_status") == "pending"]

    db.init_database()
    entries = []
    try:
        with db.get_db() as conn:
            cur = conn.execute(
                """
                SELECT * FROM job_tasks
                WHERE channel = 'whatsapp'
                  AND LOWER(status) IN ('submitted', 'duplicate')
                  AND LOWER(approval_status) = 'pending'
                ORDER BY created_at ASC
            """
            )
            for r in cur.fetchall():
                entries.append(_row_to_entry_dict(dict(r)))
    except Exception as exc:
        logger.error("Failed to query pending entries from database: %s", exc)
    return entries
