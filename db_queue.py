"""
Database Queue and State Engine for Karix Template Ingestion.

Manages persistent jobs and tasks in karix_store.db with WAL mode and 5000ms busy_timeout.
Guarantees crash-safe execution, atomic transactions, monotonic approval updates,
and seamless migration from historical JSONL logs.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DB_PATH = Path(os.environ.get("KARIX_DB_PATH", "karix_store.db"))
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


def get_db(timeout_sec: float = 15.0) -> sqlite3.Connection:
    """Return an ACID connection with WAL mode and 5000ms busy timeout."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=timeout_sec)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    return conn


def init_queue_db() -> None:
    """Initialize jobs and tasks tables and run legacy JSONL migration."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_jobs (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'whatsapp',
                filename TEXT NOT NULL,
                total_count INTEGER NOT NULL,
                submitted_count INTEGER NOT NULL DEFAULT 0,
                duplicate_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL CHECK(status IN ('QUEUED', 'RUNNING', 'PAUSED_FOR_AUTH', 'COMPLETED', 'PARTIALLY_COMPLETED', 'FAILED')),
                submitted_by TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_tasks (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'whatsapp',
                source_ref TEXT,
                template_name TEXT NOT NULL,
                category TEXT,
                language TEXT,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('PENDING', 'SUBMITTED', 'DUPLICATE', 'FAILED')),
                approval_status TEXT NOT NULL CHECK(approval_status IN ('pending', 'approved', 'rejected', 'unknown')),
                provider_ref_id TEXT,
                error TEXT,
                approval_reason TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES ingestion_jobs(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_tenant ON ingestion_jobs(tenant_id, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON ingestion_jobs(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_job ON job_tasks(job_id, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_tenant_tpl ON job_tasks(tenant_id, template_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_approval ON job_tasks(tenant_id, approval_status)")

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
    now = datetime.now(UTC).isoformat()
    jid = job_id or f"job_{uuid.uuid4().hex[:12]}"
    total_count = len(tasks_data)

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO ingestion_jobs (
                id, tenant_id, channel, filename, total_count,
                submitted_count, duplicate_count, failed_count,
                status, submitted_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 0, 0, 0, 'QUEUED', ?, ?, ?)
            """,
            (jid, tenant_id, channel, filename, total_count, submitted_by, now, now),
        )

        task_rows = []
        for idx, t in enumerate(tasks_data):
            tid = f"task_{jid}_{idx:04d}"
            tname = str(t.get("template_name", "")).strip()
            sref = str(t.get("source_ref") or tname)
            cat = t.get("category")
            lang = t.get("language")
            payload = json.dumps(t, default=str)
            initial_status = t.get("status", "PENDING").upper()
            if initial_status not in ("PENDING", "SUBMITTED", "DUPLICATE", "FAILED"):
                initial_status = "PENDING"
            approval = (t.get("approval_status") or "pending").lower()
            if approval not in ("pending", "approved", "rejected", "unknown"):
                approval = "pending"
            pref = str(t["provider_ref_id"]) if t.get("provider_ref_id") is not None else None
            err = str(t["error"]) if t.get("error") is not None else None

            task_rows.append((
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
            ))

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
    """Update high-level job lifecycle status (e.g. RUNNING, PAUSED_FOR_AUTH)."""
    now = datetime.now(UTC).isoformat()
    with get_db() as conn:
        conn.execute(
            """
            UPDATE ingestion_jobs
            SET status = ?, error_message = coalesce(?, error_message), updated_at = ?
            WHERE id = ?
            """,
            (status, error_message, now, job_id),
        )


def record_task_result(
    task_id: str,
    status: str,
    approval_status: str,
    provider_ref_id: str | None = None,
    error: str | None = None,
    approval_reason: str | None = None,
) -> dict[str, Any] | None:
    """
    Record task outcome, atomically incrementing parent job counters and resolving job settlement.
    """
    now = datetime.now(UTC).isoformat()
    norm_status = str(status or "FAILED").upper()
    if norm_status not in ("PENDING", "SUBMITTED", "DUPLICATE", "FAILED"):
        norm_status = "FAILED"

    norm_approval = str(approval_status or "pending").lower()
    if norm_approval not in ("pending", "approved", "rejected", "unknown"):
        norm_approval = "unknown"

    with get_db() as conn:
        task = conn.execute("SELECT * FROM job_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return None

        job_id = task["job_id"]
        conn.execute(
            """
            UPDATE job_tasks
            SET status = ?, approval_status = ?, provider_ref_id = coalesce(?, provider_ref_id),
                error = ?, approval_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (norm_status, norm_approval, provider_ref_id, error, approval_reason, now, task_id),
        )

        # Recalculate job summary counts atomically
        stats = conn.execute(
            """
            SELECT
                count(*) as total,
                sum(case when status = 'SUBMITTED' then 1 else 0 end) as submitted,
                sum(case when status = 'DUPLICATE' then 1 else 0 end) as duplicate,
                sum(case when status = 'FAILED' then 1 else 0 end) as failed,
                sum(case when status = 'PENDING' then 1 else 0 end) as pending
            FROM job_tasks WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()

        _ = stats["total"] or 0
        submitted = stats["submitted"] or 0
        duplicate = stats["duplicate"] or 0
        failed = stats["failed"] or 0
        pending = stats["pending"] or 0

        # Determine job settlement status
        job_status = "RUNNING"
        if pending == 0:
            if failed == 0:
                job_status = "COMPLETED"
            elif submitted + duplicate > 0:
                job_status = "PARTIALLY_COMPLETED"
            else:
                job_status = "FAILED"

        conn.execute(
            """
            UPDATE ingestion_jobs
            SET submitted_count = ?, duplicate_count = ?, failed_count = ?,
                status = case when status = 'PAUSED_FOR_AUTH' and ? != 'COMPLETED' then status else ? end,
                updated_at = ?
            WHERE id = ?
            """,
            (submitted, duplicate, failed, job_status, job_status, now, job_id),
        )

        updated_task = conn.execute("SELECT * FROM job_tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(updated_task) if updated_task else None


def update_template_approval_monotonic(
    tenant_id: str,
    template_name: str,
    new_approval_status: str,
    provider_ref_id: str | None = None,
    approval_reason: str | None = None,
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

    new_rank = APPROVAL_PRECEDENCE[norm_new]
    updated_count = 0

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, approval_status, provider_ref_id
            FROM job_tasks
            WHERE lower(tenant_id) = ? AND lower(template_name) = ?
            """,
            (clean_tenant, clean_name.lower()),
        ).fetchall()

        for r in rows:
            curr_status = r["approval_status"].lower()
            curr_rank = APPROVAL_PRECEDENCE.get(curr_status, 0)

            # Terminal states (APPROVED, REJECTED) are immutable
            if curr_status in ("approved", "rejected") and norm_new != curr_status:
                logger.debug(
                    "Monotonic guard: rejected downgrade for %s from %s to %s",
                    clean_name,
                    curr_status,
                    norm_new,
                )
                continue

            # Check rank monotonicity
            if new_rank >= curr_rank:
                conn.execute(
                    """
                    UPDATE job_tasks
                    SET approval_status = ?, provider_ref_id = coalesce(?, provider_ref_id),
                        approval_reason = coalesce(?, approval_reason), updated_at = ?
                    WHERE id = ?
                    """,
                    (norm_new, provider_ref_id, approval_reason, now, r["id"]),
                )
                updated_count += 1

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


def migrate_legacy_jsonl_if_needed() -> None:
    """
    Automatic one-way migration: imports historical entries from submission_log.jsonl
    and rcs_submission_log.jsonl into ingestion_jobs and job_tasks.
    """
    # 1. WhatsApp JSONL
    if SUBMISSION_LOG_PATH.exists():
        with get_db() as conn:
            has_wa = conn.execute("SELECT count(*) as c FROM ingestion_jobs WHERE id = 'job_legacy_whatsapp'").fetchone()["c"]
        if has_wa == 0:
            try:
                lines = [json.loads(line) for line in SUBMISSION_LOG_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
                if lines:
                    tasks = []
                    for entry in lines:
                        tname = entry.get("template_name", "unknown")
                        tasks.append({
                            "template_name": tname,
                            "source_ref": entry.get("source_ref", tname),
                            "status": entry.get("status", "submitted"),
                            "approval_status": entry.get("approval_status", "pending"),
                            "provider_ref_id": entry.get("provider_ref_id"),
                            "error": entry.get("error"),
                            "client": entry.get("client", "bajaj"),
                            "channel": "whatsapp",
                        })
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

    # 2. RCS JSONL
    if RCS_SUBMISSION_LOG_PATH.exists():
        with get_db() as conn:
            has_rcs = conn.execute("SELECT count(*) as c FROM ingestion_jobs WHERE id = 'job_legacy_rcs'").fetchone()["c"]
        if has_rcs == 0:
            try:
                lines = [json.loads(line) for line in RCS_SUBMISSION_LOG_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
                if lines:
                    tasks = []
                    for entry in lines:
                        tname = entry.get("template_name", "unknown")
                        tasks.append({
                            "template_name": tname,
                            "source_ref": entry.get("source_ref", tname),
                            "status": entry.get("status", "submitted"),
                            "approval_status": entry.get("approval_status", "approved"),
                            "provider_ref_id": entry.get("provider_ref_id") or entry.get("template_id"),
                            "error": entry.get("error"),
                            "client": entry.get("client", "bajaj"),
                            "channel": "rcs",
                        })
                    create_job_with_tasks(
                        tenant_id="legacy_import",
                        channel="rcs",
                        filename="rcs_submission_log.jsonl",
                        submitted_by="Legacy Importer",
                        tasks_data=tasks,
                        job_id="job_legacy_rcs",
                    )
                    with get_db() as conn:
                        conn.execute("UPDATE ingestion_jobs SET status = 'COMPLETED' WHERE id = 'job_legacy_rcs'")
                    logger.info("Migrated %d legacy RCS entries into job_legacy_rcs", len(tasks))
            except Exception as exc:
                logger.warning("RCS legacy JSONL migration warning: %s", exc)
