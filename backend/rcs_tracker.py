"""RCS results persisted once in tenant-scoped job tasks."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import db
from db_queue import create_job_with_tasks, record_task_result
from rcs_models import RcsSubmissionResult


def _value(value):
    return value.value if hasattr(value, "value") else value


def _row_to_entry_dict(row: dict) -> dict:
    payload = json.loads(row.get("payload_json") or "{}")
    entry = dict(payload)
    # Media is durable queue input, not dashboard/SSE response data.
    entry.pop("image_bytes_base64", None)
    for card in entry.get("carousel_cards") or []:
        if isinstance(card, dict):
            card.pop("image_bytes_base64", None)
    for field in ("source_ref", "template_name", "provider_ref_id", "error", "approval_reason", "retry_count", "updated_at"):
        entry[field] = row.get(field)
    entry.update(
        task_id=row["id"], job_id=row["job_id"], client=row["tenant_id"], channel="rcs",
        status=str(row.get("status") or "pending").lower(),
        approval_status=str(row.get("approval_status") or "unknown").lower(),
        submitted_at=payload.get("submitted_at") or row.get("created_at"),
    )
    return entry


def _custom_file(log_path: str) -> bool:
    return Path(log_path).name != "rcs_submission_log.jsonl"


def log_rcs_result(result: RcsSubmissionResult, log_path: str = "rcs_submission_log.jsonl", *, task_id: str | None = None) -> dict:
    """Persist into the owning task, or create an isolated direct-submission job."""
    db.init_database()
    payload = asdict(result)
    payload["status"] = _value(payload["status"])
    payload["approval_status"] = _value(payload.get("approval_status")) or "unknown"
    tenant = str(payload.get("client") or "").lower().strip()
    if not tenant or payload.get("channel") != "rcs":
        raise ValueError("RCS result requires an explicit tenant and RCS channel")
    payload["client"] = tenant
    if task_id is None:
        job_id = f"job_rcs_direct_{uuid.uuid4().hex}"
        create_job_with_tasks(tenant, "rcs", payload.get("source_file") or "direct_submission_rcs",
                              payload.get("submitted_by") or "Anonymous Operator",
                              [{**payload, "status": "PROCESSING"}], job_id=job_id)
        task_id = f"task_{job_id}_0000"
    with db.get_db() as conn:
        row = conn.execute("""SELECT t.*, j.tenant_id AS job_tenant, j.channel AS job_channel
            FROM job_tasks t JOIN ingestion_jobs j ON j.id = t.job_id WHERE t.id = ?""", (task_id,)).fetchone()
    if not row or row["tenant_id"] != tenant or row["channel"] != "rcs" or row["job_tenant"] != tenant or row["job_channel"] != "rcs":
        raise ValueError("RCS result task/job does not belong to the submitted tenant/channel")
    if payload["source_ref"] != row["source_ref"] or payload["template_name"] != row["template_name"]:
        raise ValueError("RCS result does not match its owning task row")
    try:
        original = json.loads(row["payload_json"] or "{}")
    except (TypeError, ValueError):
        if payload["status"] != "failed":
            raise
        original = {}
    if not isinstance(original, dict):
        if payload["status"] != "failed":
            raise ValueError("RCS task payload must be a JSON object")
        original = {}
    if original.get("bot_id") and payload.get("bot_id") != original["bot_id"]:
        raise ValueError("RCS result bot does not match its owning task")
    stored = record_task_result(task_id, payload["status"], payload["approval_status"],
                                provider_ref_id=payload.get("provider_ref_id"), error=payload.get("error"),
                                approval_reason=payload.get("approval_reason"), result_payload=payload,
                                retry_count=payload.get("retry_count", 0))
    if not stored:
        raise RuntimeError("RCS result task disappeared during persistence")
    if _custom_file(log_path):
        # Custom files are an explicit export, never a fallback for failed persistence.
        with open(log_path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, default=str) + "\n")
    return _row_to_entry_dict(stored)


def load_rcs_log(log_path: str = "rcs_submission_log.jsonl", *, client: str | None = None, pending_only: bool = False) -> list[dict]:
    """Read only the requested tenant/lifecycle instead of scanning all accounts."""
    if _custom_file(log_path):
        path = Path(log_path)
        entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
        return [entry for entry in entries if client is None or entry.get("client") == client]
    db.init_database()
    where = "channel = 'rcs'"
    params = []
    if client is not None:
        where += " AND tenant_id = ?"
        params.append(client)
    if pending_only:
        where += " AND status IN ('SUBMITTED', 'DUPLICATE') AND approval_status IN ('pending', 'unknown') AND provider_ref_id IS NOT NULL AND provider_ref_id != ''"
    with db.get_db() as conn:
        rows = conn.execute(f"SELECT * FROM job_tasks WHERE {where} ORDER BY created_at ASC, id ASC", params).fetchall()
    return [_row_to_entry_dict(dict(row)) for row in rows]


def update_rcs_result(source_ref: str, updates: dict, log_path: str = "rcs_submission_log.jsonl", *, client: str | None = None) -> bool:
    return update_rcs_results({source_ref: updates}, log_path, client=client) == 1


def update_rcs_results(updates_by_ref: dict, log_path: str = "rcs_submission_log.jsonl", *, client: str | None = None) -> int:
    """Update exact task IDs; legacy names must resolve to one task, never many."""
    if not updates_by_ref:
        return 0
    if _custom_file(log_path):
        path = Path(log_path)
        if not path.exists():
            return 0
        entries = load_rcs_log(log_path)
        changed = 0
        for ref, updates in updates_by_ref.items():
            matches = [entry for entry in entries if (entry.get("source_ref") or entry.get("template_name")) == ref and (client is None or entry.get("client") == client)]
            if len(matches) == 1:
                matches[0].update(updates)
                changed += 1
        if changed:
            path.write_text("".join(json.dumps(entry, default=str) + "\n" for entry in entries), encoding="utf-8")
        return changed
    db.init_database()
    client = str(client or "").lower().strip()
    if not client:
        raise ValueError("RCS approval updates require an explicit owning tenant")
    changed = 0
    with db.get_db() as conn:
        for ref, updates in updates_by_ref.items():
            if set(updates) - {"approval_status", "approval_reason", "provider_response"}:
                raise ValueError("RCS polling may only update approval metadata")
            scope = " AND tenant_id = ?"
            params = [ref, client]
            rows = conn.execute("SELECT * FROM job_tasks WHERE channel = 'rcs' AND id = ?" + scope, params).fetchall()
            if not rows:
                params = [ref, ref, client]
                rows = conn.execute("SELECT * FROM job_tasks WHERE channel = 'rcs' AND (source_ref = ? OR template_name = ?)" + scope, params).fetchall()
            if len(rows) != 1:
                continue
            row = dict(rows[0])
            if row.get("approval_status") in ("approved", "rejected"):
                continue
            payload = json.loads(row.get("payload_json") or "{}")
            payload.update(updates)
            approval = str(_value(updates.get("approval_status") or row.get("approval_status") or "unknown")).lower()
            reason = updates.get("approval_reason", row.get("approval_reason"))
            if approval not in ("unknown", "pending", "approved", "rejected"):
                continue
            if approval == "unknown" and row.get("approval_status") == "pending":
                continue
            # Guard both ownership and monotonic state in the write itself.
            cur = conn.execute("""UPDATE job_tasks SET approval_status = ?, approval_reason = ?,
                payload_json = ?, updated_at = ?
                WHERE id = ? AND tenant_id = ? AND channel = 'rcs'
                    AND status IN ('SUBMITTED', 'DUPLICATE')
                    AND approval_status NOT IN ('approved', 'rejected')
                    AND (approval_status = 'unknown' OR ? IN ('pending', 'approved', 'rejected'))""",
                (approval, reason, json.dumps(payload, default=str), datetime.now(UTC).isoformat(),
                 row["id"], client, approval))
            changed += cur.rowcount
    return changed
