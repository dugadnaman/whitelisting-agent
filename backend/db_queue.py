"""
Database Queue and State Engine for Karix Template Ingestion.

Manages persistent jobs and tasks in karix_store.db with WAL mode and 5000ms busy_timeout.
Guarantees crash-safe execution, atomic transactions, monotonic approval updates,
and seamless migration from historical JSONL logs.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from db import get_db, init_database

logger = logging.getLogger(__name__)

SUBMISSION_LOG_PATH = Path("submission_log.jsonl")
RCS_SUBMISSION_LOG_PATH = Path("rcs_submission_log.jsonl")

# Monotonic lifecycle precedence: lower rank cannot overwrite higher rank
# Terminal states (APPROVED, REJECTED) are immutable once reached
APPROVAL_PRECEDENCE: dict[str, int] = {
    "unknown": 0,
    "pending": 1,
    "approved": 2,
    "rejected": 2,
}

TASK_TERMINAL_STATUSES = frozenset({"SUBMITTED", "DUPLICATE", "FAILED", "BLOCKED_ASPECT_RATIO"})
JOB_TERMINAL_STATUSES = frozenset({"COMPLETED", "PARTIALLY_COMPLETED", "FAILED", "CANCELLED"})


def _lock_job(conn: Any, job_id: str) -> None:
    # A write first serializes SQLite writers and takes the PostgreSQL row lock.
    conn.execute("UPDATE ingestion_jobs SET updated_at = updated_at WHERE id = ?", (job_id,))


def _settle_job(conn: Any, job_id: str, now: str) -> None:
    conn.execute(
        """
        UPDATE ingestion_jobs SET status =
            CASE
                WHEN status = 'CANCELLED' THEN status
                WHEN submitted_count + duplicate_count + failed_count < total_count
                    THEN CASE WHEN status = 'PAUSED_FOR_AUTH' THEN status ELSE 'RUNNING' END
                WHEN failed_count = 0 THEN 'COMPLETED'
                WHEN submitted_count + duplicate_count > 0 THEN 'PARTIALLY_COMPLETED'
                ELSE 'FAILED'
            END, updated_at = ?
        WHERE id = ?
        """,
        (now, job_id),
    )


def init_queue_db() -> None:
    """Initialize jobs and tasks tables and run legacy JSONL migration."""
    init_database()

    # Run one-way legacy migration if jobs table is newly created/empty
    migrate_legacy_jsonl_if_needed()


def create_job_with_tasks(
    tenant_id: str,
    channel: str,
    filename: str,
    submitted_by: str,
    tasks_data: list[dict[str, Any]],
    job_id: str | None = None,
) -> dict[str, Any]:
    """
    Atomically creates an ingestion_job and enqueues all template tasks in one transaction.
    Returns the created job dict.
    """
    tenant_id = str(tenant_id or "").lower().strip()
    channel = str(channel or "").lower().strip()
    if not tenant_id or channel not in ("whatsapp", "rcs", "sms"):
        raise ValueError("A tenant and an explicit whatsapp/rcs/sms channel are required.")
    if channel == "sms" and tenant_id != "tata":
        raise ValueError("VILPOWER SMS whitelisting belongs only to Tata Capital.")
    now = datetime.now(UTC).isoformat()
    jid = job_id or f"job_{uuid.uuid4().hex[:12]}"
    total_count = len(tasks_data)

    with get_db() as conn:
        insert_job_sql = (
            "INSERT INTO ingestion_jobs ("
            "id, tenant_id, channel, filename, total_count, "
            "submitted_count, duplicate_count, failed_count, "
            "status, submitted_by, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, 0, 0, 0, 'QUEUED', ?, ?, ?)"
        )
        conn.execute(insert_job_sql, (jid, tenant_id, channel, filename, total_count, submitted_by, now, now))

        task_rows = []
        for idx, t in enumerate(tasks_data):
            tid = f"task_{jid}_{idx:04d}"
            tname = str(t.get("template_name", "")).strip()
            sref = str(t.get("source_ref") or tname)
            cat = t.get("category")
            lang = t.get("language")
            payload = json.dumps(t, default=str)
            initial_status = str(t.get("status") or "PENDING").upper()
            if initial_status not in TASK_TERMINAL_STATUSES | {"PENDING", "PROCESSING"}:
                initial_status = "PENDING"
            approval = str(t.get("approval_status") or "pending").lower()
            if approval == "submitted":
                approval = "pending"
            if approval not in (*APPROVAL_PRECEDENCE, "blocked_aspect_ratio"):
                approval = "unknown"
            pref = str(t["provider_ref_id"]) if t.get("provider_ref_id") is not None else None
            err = str(t["error"]) if t.get("error") is not None else None

            task_rows.append(
                (
                    tid,
                    jid,
                    tenant_id,
                    channel,
                    sref,
                    tname,
                    cat,
                    lang,
                    payload,
                    initial_status,
                    approval,
                    pref,
                    err,
                    0,
                    now,
                    now,
                )
            )

        conn.executemany(
            """
            INSERT INTO job_tasks (
                id, job_id, tenant_id, channel, source_ref, template_name,
                category, language, payload_json, status, approval_status,
                provider_ref_id, error, retry_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            task_rows,
        )
        submitted = sum(row[9] == "SUBMITTED" for row in task_rows)
        duplicate = sum(row[9] == "DUPLICATE" for row in task_rows)
        failed = sum(row[9] in ("FAILED", "BLOCKED_ASPECT_RATIO") for row in task_rows)
        conn.execute(
            "UPDATE ingestion_jobs SET submitted_count = ?, duplicate_count = ?, failed_count = ? WHERE id = ?",
            (submitted, duplicate, failed, jid),
        )
        if total_count == submitted + duplicate + failed or any(row[9] == "PROCESSING" for row in task_rows):
            _settle_job(conn, jid, now)

    return get_job(jid) or {"id": jid, "status": "QUEUED", "total_count": total_count}


def get_job(job_id: str) -> dict[str, Any] | None:
    """Fetch job summary by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def get_job_tasks(job_id: str) -> list[dict[str, Any]]:
    """Fetch all tasks for a specific job."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM job_tasks WHERE job_id = ? ORDER BY id ASC",
            (job_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_job_task(task_id: str) -> dict[str, Any] | None:
    """Fetch a single task by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM job_tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def update_job_status(job_id: str, status: str, error_message: str | None = None) -> None:
    """Update a live job without reopening an already settled job."""
    now = datetime.now(UTC).isoformat()
    with get_db() as conn:
        conn.execute(
            """
            UPDATE ingestion_jobs
            SET status = ?, error_message = ?, updated_at = ?
            WHERE id = ? AND status NOT IN ('COMPLETED', 'PARTIALLY_COMPLETED', 'FAILED', 'CANCELLED')
            """,
            (status, error_message, now, job_id),
        )


def validate_task_scope(task: dict[str, Any], payload: dict[str, Any], tenant_id: str, channel: str) -> None:
    """Reject persisted or payload ownership mismatches before provider dispatch."""
    if not isinstance(payload, dict):
        raise ValueError("Task payload must be a JSON object.")
    if task.get("tenant_id") != tenant_id or task.get("channel") != channel:
        raise ValueError("Task does not belong to the selected tenant/channel.")
    for field in ("client", "tenant_id", "account"):
        if field in payload and str(payload[field] or "").lower().strip() != tenant_id:
            raise ValueError(f"Task payload {field} does not match its owning tenant.")
    if "channel" in payload and str(payload["channel"] or "").lower().strip() != channel:
        raise ValueError("Task payload channel does not match its owning channel.")
    for field in ("source_ref", "template_name"):
        if field in payload and str(payload[field] or "") != str(task.get(field) or ""):
            raise ValueError(f"Task payload {field} does not match its owning row.")


def claim_task(task_id: str, tenant_id: str, channel: str) -> dict[str, Any] | None:
    """Atomically reserve one pending task before any external side effect."""
    now = datetime.now(UTC).isoformat()
    tenant_id = str(tenant_id or "").lower().strip()
    channel = str(channel or "").lower().strip()
    with get_db() as conn:
        conn.execute(
            "UPDATE ingestion_jobs SET updated_at = updated_at WHERE id = (SELECT job_id FROM job_tasks WHERE id = ?)",
            (task_id,),
        )
        cur = conn.execute(
            """
            UPDATE job_tasks SET status = 'PROCESSING', updated_at = ?
            WHERE id = ? AND tenant_id = ? AND channel = ? AND status = 'PENDING'
                AND job_id IN (
                    SELECT id FROM ingestion_jobs
                    WHERE tenant_id = ? AND channel = ?
                        AND status IN ('QUEUED', 'RUNNING')
                )
            """,
            (now, task_id, tenant_id, channel, tenant_id, channel),
        )
        if cur.rowcount != 1:
            return None
        conn.execute(
            """UPDATE ingestion_jobs SET status = 'RUNNING', updated_at = ?
                WHERE id = (SELECT job_id FROM job_tasks WHERE id = ?) AND status = 'QUEUED'""",
            (now, task_id),
        )
        row = conn.execute("SELECT * FROM job_tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def release_task_for_auth(task_id: str) -> None:
    """Only a definitive authentication refusal may release a claim for retry."""
    with get_db() as conn:
        conn.execute(
            "UPDATE ingestion_jobs SET updated_at = updated_at WHERE id = (SELECT job_id FROM job_tasks WHERE id = ?)",
            (task_id,),
        )
        conn.execute(
            "UPDATE job_tasks SET status = 'PENDING', updated_at = ? WHERE id = ? AND status = 'PROCESSING'",
            (datetime.now(UTC).isoformat(), task_id),
        )


def fail_unfinished_job(job_id: str, error: str) -> None:
    """Fail unclaimed rows after an explicit worker interruption, never another worker's active POST."""
    now = datetime.now(UTC).isoformat()
    with get_db() as conn:
        _lock_job(conn, job_id)
        cur = conn.execute(
            """
            UPDATE job_tasks SET status = 'FAILED', approval_status = 'unknown', error = ?, updated_at = ?
            WHERE job_id = ? AND status = 'PENDING'
                AND NOT EXISTS (SELECT 1 FROM job_tasks active
                                WHERE active.job_id = ? AND active.status = 'PROCESSING')
            """,
            (str(error), now, job_id, job_id),
        )
        if cur.rowcount:
            conn.execute(
                "UPDATE ingestion_jobs SET failed_count = failed_count + ?, error_message = ? WHERE id = ?",
                (cur.rowcount, str(error), job_id),
            )
        # Never expire claims by age or settle an overlapping worker's provider call.
        _settle_job(conn, job_id, now)


def _clean_sql_str(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    return str(val)


def record_task_result(
    task_id: str,
    status: str,
    approval_status: str,
    provider_ref_id: str | None = None,
    error: str | None = None,
    approval_reason: str | None = None,
    result_payload: dict[str, Any] | None = None,
    retry_count: int | None = None,
) -> dict[str, Any] | None:
    """Persist one outcome and its counter delta in a serialized transaction."""
    now = datetime.now(UTC).isoformat()
    norm_status = str(status or "FAILED").upper()
    if norm_status not in TASK_TERMINAL_STATUSES | {"PENDING"}:
        norm_status = "FAILED"
    norm_approval = str(approval_status or "unknown").lower()
    if norm_approval == "submitted":
        norm_approval = "pending"
    if norm_approval not in (*APPROVAL_PRECEDENCE, "blocked_aspect_ratio"):
        norm_approval = "unknown"

    with get_db() as conn:
        # Lock the parent before reading task state: all result writers share it.
        conn.execute(
            "UPDATE ingestion_jobs SET updated_at = updated_at WHERE id = (SELECT job_id FROM job_tasks WHERE id = ?)",
            (task_id,),
        )
        task = conn.execute("SELECT * FROM job_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return None
        old_status = task["status"]
        if old_status in TASK_TERMINAL_STATUSES:
            return dict(task)
        old_approval = str(task["approval_status"] or "unknown").lower()
        if old_approval in ("approved", "rejected"):
            norm_approval = old_approval
            approval_reason = task["approval_reason"]
        payload_json = task["payload_json"]
        if result_payload is not None:
            try:
                payload = json.loads(payload_json)
            except (TypeError, ValueError):
                if norm_status != "FAILED":
                    raise
                payload = {}
            if not isinstance(payload, dict):
                if norm_status != "FAILED":
                    raise ValueError("Task payload must be a JSON object.")
                payload = {}
            payload.update(result_payload)
            payload.update(
                client=task["tenant_id"], channel=task["channel"],
                source_ref=task["source_ref"], template_name=task["template_name"],
            )
            payload_json = json.dumps(payload, default=str)
        conn.execute(
            """
            UPDATE job_tasks
            SET status = ?, approval_status = ?, provider_ref_id = coalesce(?, provider_ref_id),
                error = ?, approval_reason = ?, payload_json = ?, retry_count = coalesce(?, retry_count), updated_at = ?
            WHERE id = ?
            """,
            (norm_status, norm_approval, _clean_sql_str(provider_ref_id), _clean_sql_str(error),
             _clean_sql_str(approval_reason), payload_json, retry_count, now, task_id),
        )
        conn.execute(
            """
            UPDATE ingestion_jobs
            SET submitted_count = submitted_count + ?, duplicate_count = duplicate_count + ?,
                failed_count = failed_count + ?
            WHERE id = ?
            """,
            (int(norm_status == "SUBMITTED") - int(old_status == "SUBMITTED"),
             int(norm_status == "DUPLICATE") - int(old_status == "DUPLICATE"),
             int(norm_status in ("FAILED", "BLOCKED_ASPECT_RATIO")) - int(old_status in ("FAILED", "BLOCKED_ASPECT_RATIO")),
             task["job_id"]),
        )
        _settle_job(conn, task["job_id"], now)
        updated_task = conn.execute("SELECT * FROM job_tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(updated_task) if updated_task else None


def update_template_approval_monotonic(
    tenant_id: str,
    template_name: str,
    new_approval_status: str,
    provider_ref_id: str | None = None,
    approval_reason: str | None = None,
    channel: str = "whatsapp",
) -> int:
    """
    Monotonic approval state machine:
    Only advances state forward. Rejects regressions (e.g. delayed carrier PENDING
    cannot overwrite an existing APPROVED or REJECTED status).
    Returns number of tasks updated.
    """
    now = datetime.now(UTC).isoformat()
    clean_tenant = tenant_id.lower().strip()
    clean_name = template_name.strip()
    norm_new = new_approval_status.lower().strip()

    if norm_new not in APPROVAL_PRECEDENCE:
        return 0

    updated_count = 0

    channel = str(channel).lower().strip()
    # This name-based updater belongs to WhatsApp callbacks. RCS uses exact task IDs.
    if channel != "whatsapp":
        return 0
    with get_db() as conn:
        # Guard in the UPDATE itself, not a stale pre-update snapshot.
        cur = conn.execute(
            """
            UPDATE job_tasks
            SET approval_status = ?, provider_ref_id = coalesce(?, provider_ref_id),
                approval_reason = coalesce(?, approval_reason), updated_at = ?
            WHERE tenant_id = ? AND lower(template_name) = ? AND channel = ?
                AND (approval_status NOT IN ('approved', 'rejected') OR approval_status = ?)
                AND (approval_status = 'unknown' OR approval_status = ?
                     OR (approval_status = 'pending' AND ? IN ('pending', 'approved', 'rejected')))
            """,
            (norm_new, _clean_sql_str(provider_ref_id), _clean_sql_str(approval_reason), now,
             clean_tenant, clean_name.lower(), channel, norm_new, norm_new, norm_new),
        )
        updated_count = cur.rowcount

    return updated_count


def list_paused_jobs(tenant_id: str | None = None) -> list[dict[str, Any]]:
    """Retrieve jobs currently held in PAUSED_FOR_AUTH status."""
    with get_db() as conn:
        if tenant_id:
            rows = conn.execute(
                "SELECT * FROM ingestion_jobs WHERE status = 'PAUSED_FOR_AUTH' AND lower(tenant_id) = ? ORDER BY created_at ASC",
                (tenant_id.lower().strip(),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ingestion_jobs WHERE status = 'PAUSED_FOR_AUTH' ORDER BY created_at ASC"
            ).fetchall()
        return [dict(r) for r in rows]


def resume_paused_jobs_for_tenant(tenant_id: str) -> int:
    """Flip all PAUSED_FOR_AUTH jobs back to RUNNING for a given tenant."""
    now = datetime.now(UTC).isoformat()
    clean_tenant = tenant_id.lower().strip()
    with get_db() as conn:
        cur = conn.execute(
            """
            UPDATE ingestion_jobs
            SET status = 'RUNNING', error_message = NULL, updated_at = ?
            WHERE status = 'PAUSED_FOR_AUTH' AND lower(tenant_id) = ?
            """,
            (now, clean_tenant),
        )
        return cur.rowcount


def _rehome_legacy_rcs_tasks() -> None:
    """Repair the old mixed-account container, preserving IDs and provider outcomes."""
    now = datetime.now(UTC).isoformat()
    with get_db() as conn:
        _lock_job(conn, "job_legacy_rcs")
        legacy = conn.execute(
            "SELECT * FROM ingestion_jobs WHERE id = 'job_legacy_rcs' AND tenant_id = 'legacy_import' AND channel = 'rcs'"
        ).fetchone()
        if not legacy:
            return
        rows = conn.execute("SELECT * FROM job_tasks WHERE job_id = 'job_legacy_rcs' ORDER BY id").fetchall()
        source_by_id = {}
        source_available = RCS_SUBMISSION_LOG_PATH.exists()
        if source_available:
            with RCS_SUBMISSION_LOG_PATH.open(encoding="utf-8") as stream:
                index = 0
                for line in stream:
                    if not line.strip():
                        continue
                    try:
                        source_by_id[f"task_job_legacy_rcs_{index:04d}"] = json.loads(line)
                    except ValueError:
                        source_by_id[f"task_job_legacy_rcs_{index:04d}"] = None
                    index += 1
        groups: dict[str, list[Any]] = {}
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
                stored_tenant = str(payload.get("client") or "").lower().strip()
                source = source_by_id.get(row["id"])
                if source_available:
                    tenant = str(source.get("client") or "").lower().strip() if isinstance(source, dict) else ""
                    valid = (
                        tenant and tenant == stored_tenant
                        and str(source.get("template_name") or "").strip() == row["template_name"]
                        and str(source.get("source_ref") or source.get("template_name") or "") == row["source_ref"]
                        and str(source.get("channel") or "rcs").lower().strip() == "rcs"
                    )
                else:
                    tenant = stored_tenant
                    # The old importer guessed BAJAJ, so that value needs original-source proof.
                    valid = tenant and tenant != "bajaj"
                valid = valid and str(payload.get("channel") or "rcs").lower().strip() == "rcs"
            except (TypeError, ValueError, AttributeError):
                valid = False
            if not valid:
                logger.warning("Quarantining legacy RCS task %s: no explicit owning account/channel.", row["id"])
                continue
            restored_payload = {**(source or {}), **payload, "client": tenant, "channel": "rcs"}
            approval = row["approval_status"]
            if (
                source_available and not source.get("approval_status") and approval == "approved"
                and row["updated_at"] == row["created_at"]
                and not row["approval_reason"] and not payload.get("approval_reason")
                and not payload.get("provider_response") and not source.get("provider_response")
                and not payload.get("updated_at")
            ):
                # Only provably untouched rows can carry the importer's invented approval.
                approval = "unknown"
                restored_payload["approval_status"] = approval
            groups.setdefault(tenant, []).append((row, restored_payload, approval))
        for tenant, tasks in sorted(groups.items()):
            jid = f"job_legacy_rcs_{tenant}"
            conn.execute(
                """INSERT INTO ingestion_jobs (id, tenant_id, channel, filename, total_count,
                    submitted_count, duplicate_count, failed_count, status, submitted_by, created_at, updated_at)
                    VALUES (?, ?, 'rcs', ?, 0, 0, 0, 0, 'QUEUED', ?, ?, ?)
                    ON CONFLICT (id) DO NOTHING""",
                (jid, tenant, legacy["filename"], legacy["submitted_by"], legacy["created_at"], now),
            )
            _lock_job(conn, jid)
            owner = conn.execute("SELECT tenant_id, channel FROM ingestion_jobs WHERE id = ?", (jid,)).fetchone()
            if owner["tenant_id"] != tenant or owner["channel"] != "rcs":
                raise ValueError("Legacy RCS migration job belongs to another account/channel")
            conn.executemany(
                "UPDATE job_tasks SET job_id = ?, tenant_id = ?, channel = 'rcs', payload_json = ?, approval_status = ? WHERE id = ? AND job_id = 'job_legacy_rcs'",
                [(jid, tenant, json.dumps(payload, default=str), approval, row["id"]) for row, payload, approval in tasks],
            )
            _recount_job(conn, jid, now)
        remaining = conn.execute("SELECT count(*) AS c FROM job_tasks WHERE job_id = 'job_legacy_rcs'").fetchone()["c"]
        if remaining:
            _recount_job(conn, "job_legacy_rcs", now)
        else:
            conn.execute("DELETE FROM ingestion_jobs WHERE id = 'job_legacy_rcs' AND tenant_id = 'legacy_import'")


def _recount_job(conn: Any, job_id: str, now: str) -> None:
    counts = conn.execute(
        """SELECT count(*) AS total,
            coalesce(sum(CASE WHEN status = 'SUBMITTED' THEN 1 ELSE 0 END), 0) AS submitted,
            coalesce(sum(CASE WHEN status = 'DUPLICATE' THEN 1 ELSE 0 END), 0) AS duplicate,
            coalesce(sum(CASE WHEN status IN ('FAILED', 'BLOCKED_ASPECT_RATIO') THEN 1 ELSE 0 END), 0) AS failed
            FROM job_tasks WHERE job_id = ?""", (job_id,),
    ).fetchone()
    conn.execute(
        "UPDATE ingestion_jobs SET total_count = ?, submitted_count = ?, duplicate_count = ?, failed_count = ? WHERE id = ?",
        (counts["total"], counts["submitted"], counts["duplicate"], counts["failed"], job_id),
    )
    _settle_job(conn, job_id, now)


def migrate_legacy_jsonl_if_needed() -> None:
    """
    Automatic one-way migration: imports historical entries from submission_log.jsonl
    and rcs_submission_log.jsonl into ingestion_jobs and job_tasks.
    """
    # 1. WhatsApp JSONL
    if SUBMISSION_LOG_PATH.exists():
        with get_db() as conn:
            has_wa = conn.execute(
                "SELECT count(*) as c FROM ingestion_jobs WHERE id = 'job_legacy_whatsapp'"
            ).fetchone()["c"]
        if has_wa == 0:
            try:
                lines = [
                    json.loads(line)
                    for line in SUBMISSION_LOG_PATH.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                if lines:
                    tasks = []
                    for entry in lines:
                        tname = entry.get("template_name", "unknown")
                        tasks.append(
                            {
                                "template_name": tname,
                                "source_ref": entry.get("source_ref", tname),
                                "status": entry.get("status", "submitted"),
                                "approval_status": entry.get("approval_status", "pending"),
                                "provider_ref_id": entry.get("provider_ref_id"),
                                "error": entry.get("error"),
                                "client": entry.get("client", "bajaj"),
                                "channel": "whatsapp",
                            }
                        )
                    create_job_with_tasks(
                        tenant_id="legacy_import",
                        channel="whatsapp",
                        filename="submission_log.jsonl",
                        submitted_by="Legacy Importer",
                        tasks_data=tasks,
                        job_id="job_legacy_whatsapp",
                    )
                    with get_db() as conn:
                        conn.execute("UPDATE ingestion_jobs SET status = 'COMPLETED' WHERE id = 'job_legacy_whatsapp'")
                    logger.info("Migrated %d legacy WhatsApp entries into job_legacy_whatsapp", len(tasks))
            except Exception as exc:
                logger.warning("WhatsApp legacy JSONL migration warning: %s", exc)

    # RCS history is account-owned. Never infer an account, approval, or replayable task.
    _rehome_legacy_rcs_tasks()
    if not RCS_SUBMISSION_LOG_PATH.exists():
        return
    groups: dict[str, list[dict[str, Any]]] = {}
    with RCS_SUBMISSION_LOG_PATH.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                tenant = str(entry.get("client") or "").lower().strip()
                name = str(entry.get("template_name") or "").strip()
                if not tenant or not name or str(entry.get("channel") or "rcs").lower().strip() != "rcs":
                    raise ValueError("missing explicit account/template name or mismatched channel")
            except (TypeError, ValueError, AttributeError) as exc:
                logger.warning("Skipping RCS legacy JSONL row %d: %s", index, exc)
                continue
            status = str(entry.get("status") or "").upper()
            if status not in TASK_TERMINAL_STATUSES:
                status = "FAILED"
                entry["error"] = entry.get("error") or "Legacy submission outcome unknown; reconcile before resubmitting."
            groups.setdefault(tenant, []).append({
                **entry, "client": tenant, "channel": "rcs", "template_name": name,
                "status": status, "approval_status": entry.get("approval_status") or "unknown",
                "provider_ref_id": entry.get("provider_ref_id") or entry.get("template_id"),
            })
    for tenant, tasks in sorted(groups.items()):
        jid = f"job_legacy_rcs_{tenant}"
        existing = get_job(jid)
        if existing:
            if existing["tenant_id"] != tenant or existing["channel"] != "rcs":
                raise ValueError("Legacy RCS migration job belongs to another account/channel")
            continue
        try:
            create_job_with_tasks(
                tenant_id=tenant, channel="rcs", filename=RCS_SUBMISSION_LOG_PATH.name,
                submitted_by="Legacy Importer", tasks_data=tasks, job_id=jid,
            )
            logger.info("Migrated %d legacy RCS entries for %s.", len(tasks), tenant)
        except Exception:
            # Deterministic IDs + one atomic insert transaction prevent concurrent startup duplicates.
            winner = get_job(jid)
            if not winner or winner["tenant_id"] != tenant or winner["channel"] != "rcs":
                raise
