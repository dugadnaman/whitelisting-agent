"""Tata VILPOWER DLT drafts and durable whitelisting outcomes, never SMS delivery."""

from __future__ import annotations

import json
import csv
import threading
from concurrent.futures import Future
from datetime import date, datetime, timedelta
from os.path import commonprefix
from pathlib import Path

from db import get_db
from db_queue import (
    create_job_with_tasks, get_job, get_job_tasks, reconcile_sms_task, sms_reconciliation_payload,
)
from tracker import _row_to_entry_dict

DRAFT_FIELDS = (
    "template_name", "text", "template_type", "category_id", "header_id", "header",
    "brand_id", "message_type", "sample_message", "service_type",
)

_inventory_flights: dict[tuple[str, str, date | None], Future] = {}
_inventory_lock = threading.Lock()


def _inventory(account: str, search: str = "", from_date: date | None = None) -> list[dict]:
    """Share concurrent catalog reads, without caching stale approvals or failures."""
    from vilpower_client import fetch_sms_templates
    require_tata(account)
    key = (account, search, from_date)
    with _inventory_lock:
        flight = _inventory_flights.get(key)
        leader = flight is None
        if leader:
            flight = Future()
            _inventory_flights[key] = flight
    if not leader:
        return flight.result()
    try:
        kwargs = {"client": account, "search": search}
        if from_date is not None:
            kwargs["from_date"] = from_date
        rows = fetch_sms_templates(**kwargs)
        return rows
    except BaseException as exc:
        flight.set_exception(exc)
        raise
    finally:
        with _inventory_lock:
            _inventory_flights.pop(key, None)


def require_tata(account: str) -> None:
    if account != "tata":
        raise ValueError("VILPOWER SMS whitelisting is configured only for Tata Capital. Select Tata Capital · SMS.")


def draft_from_row(row: dict, account: str = "tata") -> dict:
    from vilpower_client import TATA_ENTITY_ID

    require_tata(account)
    if not isinstance(row, dict):
        raise ValueError("Each SMS template must be an object.")
    for field in ("account", "client", "tenant_id"):
        if field in row and str(row[field]).strip().lower() != account:
            raise ValueError("SMS template account does not match Tata Capital.")
    if row.get("channel") and row["channel"] != "sms":
        raise ValueError("SMS template channel does not match the selected destination.")
    if row.get("entity_id", TATA_ENTITY_ID) != TATA_ENTITY_ID:
        raise ValueError("SMS template principal entity does not match Tata Capital.")
    if row.get("provider", "vilpower") != "vilpower":
        raise ValueError("SMS template provider does not match VILPOWER.")
    draft = {key: str(row[key]) if row.get(key) is not None else "" for key in DRAFT_FIELDS}
    draft["text"] = str(next((row[key] for key in ("text", "body", "message", "template_message")
                              if row.get(key) is not None), ""))
    for field in ("source_ref", "source_file"):
        if field in row:
            if not isinstance(row[field], str):
                raise ValueError(f"{field} must be text.")
            draft[field] = row[field]
    if "brief" in row:
        draft["brief"] = row["brief"]
    draft["template_name"] = draft["template_name"].strip()
    draft["template_type"] = draft["template_type"] or "1"
    draft["message_type"] = draft["message_type"] or ("1" if draft["text"].isascii() else "2")
    for key in ("template_type", "message_type"):
        if draft[key] in {"1.0", "2.0", "3.0"}:
            draft[key] = draft[key][0]
    return draft


def load_drafts(path: str, account: str = "tata") -> list[dict]:
    require_tata(account)
    suffix = Path(path).suffix.lower()
    if suffix == ".xlsx":
        import openpyxl
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            rows = workbook.active.iter_rows(values_only=True)
            headers = [str(value or "").strip().lower().replace(" ", "_") for value in next(rows, ())]
            raw = [dict(zip(headers, values, strict=False)) for values in rows if any(value is not None for value in values)]
        finally:
            workbook.close()
    elif suffix == ".xls":
        import xlrd
        workbook = xlrd.open_workbook(path)
        sheet = workbook.sheet_by_index(0)
        headers = [str(value).strip().lower().replace(" ", "_") for value in sheet.row_values(0)] if sheet.nrows else []
        raw = [dict(zip(headers, sheet.row_values(index), strict=False)) for index in range(1, sheet.nrows)]
    elif suffix == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            raw = [{str(key).strip().lower().replace(" ", "_"): value for key, value in row.items() if key}
                   for row in reader if any(value for value in row.values())]
    else:
        raise ValueError("SMS DLT imports accept CSV, XLSX, or XLS files.")
    if not raw:
        raise ValueError("No SMS DLT templates found. Include template_name and text columns; recipients are not required.")
    return [draft_from_row(row, account) for row in raw]


def preview_drafts(rows: list[dict], account: str = "tata") -> list[dict]:
    from vilpower_client import validate_sms_template

    require_tata(account)
    drafts = [draft_from_row(row, account) for row in rows]
    inventory = _inventory(account, commonprefix([draft["template_name"].casefold() for draft in drafts]))
    by_name = {}
    for item in inventory:
        by_name.setdefault(item["template_name"].casefold(), []).append(item)
    previews = []
    seen = {}
    for draft in drafts:
        key = draft["template_name"].casefold()
        existing = by_name.get(key, [])
        errors = validate_sms_template(draft)
        fields = tuple(draft[field] for field in DRAFT_FIELDS)
        if key in seen and seen[key] != fields:
            errors.append("Duplicate name has different SMS DLT fields. Use a distinct name.")
        seen[key] = fields
        previews.append({
            "template_name": draft["template_name"], "client": account, "channel": "sms",
            "category": {"1": "PROMOTIONAL", "2": "TRANSACTIONAL", "3": "SERVICE"}.get(draft["template_type"], "UNKNOWN"),
            "language": "en" if draft["message_type"] == "1" else "regional",
            "components": [{"type": "BODY", "text": draft["text"]}],
            "sms_dlt": draft, "provider": "vilpower", "status": "INVALID" if errors else "VALID",
            "already_exists_on_waba": bool(existing), "exists_on_waba": False,
            "existing_templates": existing,
            "compliance_warnings": [{"severity": "error", "issue": error, "recommendation": "Correct the DLT draft before submitting."} for error in errors],
            "aspect_ratio_warnings": [], "grammar_warnings": [],
        })
    return previews


def stage_batch(rows: list[dict], account: str, user: str, filename: str, skip_duplicates: bool = True) -> dict:
    from vilpower_client import TATA_ENTITY_ID, matches_sms_identity, validate_sms_template

    require_tata(account)
    if not rows:
        raise ValueError("Select at least one SMS DLT template.")
    drafts = [draft_from_row(row, account) for row in rows]
    for index, draft in enumerate(drafts, 1):
        errors = validate_sms_template(draft)
        if errors:
            raise ValueError(f"Row {index} ({draft['template_name']}): {'; '.join(errors)}")
    # A failed provider read must not turn every existing template into a new registration.
    inventory = _inventory(account, commonprefix([draft["template_name"].casefold() for draft in drafts]))
    by_name = {}
    for item in inventory:
        by_name.setdefault(item["template_name"].casefold(), []).append(item)
    _reconcile_tasks(_history_tasks(account), account, inventory)
    previous_tasks = _history_tasks(account)
    tasks = []
    seen = {}
    for index, draft in enumerate(drafts, 1):
        key = draft["template_name"].casefold()
        candidates = by_name.get(key, [])
        exact = [item for item in candidates if matches_sms_identity(draft, item)]
        if len(exact) > 1:
            raise ValueError(f"Row {index}: multiple VILPOWER IDs match '{draft['template_name']}'. Reconcile the inventory before a new review.")
        live = exact[0] if exact else None
        for previous in previous_tasks:
            if previous["template_name"].casefold() != key:
                continue
            if previous["status"] in {"PENDING", "PROCESSING"}:
                raise ValueError(f"Row {index}: '{draft['template_name']}' already has an active SMS queue task. Refresh its job status; do not submit it again.")
            if not live and previous["status"] == "FAILED" and sms_reconciliation_payload(previous) is not None:
                raise ValueError(f"Row {index}: '{draft['template_name']}' has registration outcome unknown. Refresh its job status to reconcile VILPOWER inventory; do not resubmit it.")
        payload = {**draft, "client": account, "channel": "sms", "provider": "vilpower", "entity_id": TATA_ENTITY_ID,
                   "source_ref": draft.get("source_ref") or draft["template_name"], "submitted_by": user,
                   "source_file": draft.get("source_file") or filename,
                   "category": {"1": "PROMOTIONAL", "2": "TRANSACTIONAL", "3": "SERVICE"}[draft["template_type"]],
                   "language": "en" if draft["message_type"] == "1" else "regional"}
        if candidates and not live:
            raise ValueError(f"Row {index}: '{draft['template_name']}' already exists with different DLT content or a different header. Use a distinct name; registered copy is never overwritten.")
        fields = tuple(draft[field] for field in DRAFT_FIELDS)
        if key in seen and seen[key] != fields:
            raise ValueError(f"Row {index}: duplicate name has different SMS DLT fields. Use a distinct name.")
        if live or key in seen:
            payload.update(status="DUPLICATE", approval_status=live.get("status", "unknown") if live else "unknown",
                           provider_ref_id=live.get("template_id") if live else None,
                           error="Already registered on VILPOWER." if live else "Duplicate name within this batch.")
        seen[key] = fields
        tasks.append(payload)
    return create_job_with_tasks(account, "sms", filename, user, tasks)


def _history_tasks(account: str, job_id: str | None = None) -> list[dict]:
    require_tata(account)
    with get_db() as conn:
        sql = "SELECT * FROM job_tasks WHERE tenant_id = ? AND channel = 'sms'"
        params = [account]
        if job_id is not None:
            sql += " AND job_id = ?"
            params.append(job_id)
        rows = conn.execute(sql + " ORDER BY created_at DESC", params).fetchall()
    return [dict(row) for row in rows]


def load_history(account: str = "tata") -> list[dict]:
    return [_row_to_entry_dict(row) for row in _history_tasks(account)]


def sms_task_registration_outcome(task: dict) -> str | None:
    """Expose only the safe registration scalar, never the stored draft payload."""
    try:
        payload = json.loads(task.get("payload_json") or "{}")
        response = payload.get("provider_response") if isinstance(payload, dict) else None
        outcome = response.get("outcome") if isinstance(response, dict) else None
        return outcome if isinstance(outcome, str) and outcome in {"unknown", "verified", "failed"} else None
    except (TypeError, ValueError):
        return None


def merged_inventory(account: str = "tata") -> list[dict]:
    require_tata(account)
    live = _inventory(account)
    _reconcile_tasks(_history_tasks(account), account, live)
    history = load_history(account)
    by_id = {}
    live_ids = {str(item["template_id"]) for item in live}
    merged = []
    for item in history:
        identifier = str(item.get("provider_ref_id") or "")
        if identifier:
            by_id.setdefault(identifier, item)
        if identifier not in live_ids:
            merged.append({
                **item, "template_id": item.get("provider_ref_id"), "template_message": item.get("text", ""),
                "template_type": "SMS DLT", "live": False, "exists_on_waba": False, "provider": "vilpower",
            })
    for item in live:
        previous = by_id.get(str(item["template_id"]), {})
        merged.append({**previous, **item, "status": "submitted", "approval_status": item.get("status", "unknown"),
                       "client": account, "channel": "sms", "provider": "vilpower", "live": True,
                       "template_type": "SMS DLT", "exists_on_waba": False,
                       "source_ref": previous.get("source_ref") or item["template_name"],
                       "submitted_at": previous.get("submitted_at") or item.get("requested_at", ""),
                       "sender_ids": [item["header"]] if item.get("header") else []})
    return merged


def _reconcile_tasks(tasks: list[dict], account: str, inventory: list[dict] | None = None) -> dict:
    from vilpower_client import matches_sms_identity

    candidates = [(task, payload) for task in tasks if (payload := sms_reconciliation_payload(task)) is not None]
    if not candidates:
        return {"checked": 0, "updated": 0}
    # Read the complete authoritative catalog, not a potentially delayed name search.
    live = _inventory(account) if inventory is None else inventory
    by_name = {}
    for item in live:
        by_name.setdefault(item["template_name"], []).append(item)
    updated = 0
    for task, payload in candidates:
        matches = [item for item in by_name.get(task["template_name"], []) if matches_sms_identity(payload, item)
                   and (not task.get("provider_ref_id") or str(item["template_id"]) == str(task["provider_ref_id"]))]
        if len(matches) == 1:
            updated += int(reconcile_sms_task(task["id"], matches[0]))
    return {"checked": len(candidates), "updated": updated}


def _job_inventory_since(job: dict) -> date | None:
    raw = str(job.get("created_at") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date() - timedelta(days=2)
    except ValueError:
        return None


def _candidate_inventory_scope(candidates: list[dict], fallback_job: dict | None = None) -> tuple[str, date | None]:
    prefix = commonprefix([task["template_name"].casefold() for task in candidates])
    if len(prefix) >= 4:
        return prefix, None
    dates = [d for d in (_job_inventory_since(t) for t in ([fallback_job] if fallback_job else candidates)) if d is not None]
    return "", min(dates) if dates else None


def reconcile_job(job_id: str, account: str = "tata") -> dict:
    """Explicit status refresh: inventory reads only, never registration or replay."""
    require_tata(account)
    job = get_job(job_id)
    if not job or job["tenant_id"] != account or job["channel"] != "sms":
        raise ValueError("Job does not belong to the selected Tata SMS destination.")
    tasks = get_job_tasks(job_id)
    candidates = [task for task in tasks if sms_reconciliation_payload(task) is not None]
    if not candidates:
        return {"checked": 0, "updated": 0}
    search, since = _candidate_inventory_scope(candidates, fallback_job=job)
    return _reconcile_tasks(tasks, account, _inventory(account, search=search, from_date=since))


def poll_approvals(account: str = "tata") -> dict:
    require_tata(account)
    tasks = _history_tasks(account)
    candidates = [task for task in tasks if sms_reconciliation_payload(task) is not None]
    if not candidates:
        return {"checked": 0, "updated": 0}
    search, since = _candidate_inventory_scope(candidates)
    return _reconcile_tasks(tasks, account, _inventory(account, search=search, from_date=since))


def identify_drafts(rows: list[dict], account: str = "tata") -> dict:
    require_tata(account)
    live = _inventory(account)
    by_name = {}
    for item in live:
        by_name.setdefault(item["template_name"].casefold(), []).append(item)
    counts = {"WHITELISTED": 0, "NOT_WHITELISTED": 0, "PENDING": 0, "REJECTED": 0, "CONTENT_DRIFT": 0}
    items, missing = [], []
    for raw in rows:
        draft = draft_from_row(raw, account)
        candidates = by_name.get(draft["template_name"].casefold(), [])
        # DLT delivery matches registered copy, not semantic equivalence or normalized whitespace.
        exact = [item for item in (candidates or live) if item.get("template_message") == draft["text"]
                 and (not draft.get("header") or item.get("header") == draft["header"])]
        exact.sort(key=lambda item: item.get("status") != "approved")
        match = exact[0] if exact else (candidates[0] if candidates else None)
        if match is None:
            status, action = "NOT_WHITELISTED", "SUBMIT"
            missing.append(draft)
        elif match.get("template_message") != draft["text"] or (draft.get("header") and match.get("header") != draft["header"]):
            status, action = "CONTENT_DRIFT", "REMEDIATE"
        else:
            status = {"approved": "WHITELISTED", "pending": "PENDING", "rejected": "REJECTED"}.get(match.get("status"), "PENDING")
            action = {"WHITELISTED": "NONE", "PENDING": "WAIT", "REJECTED": "REMEDIATE"}[status]
        counts[status] += 1
        items.append({"template_name": draft["template_name"], "status": status,
                      "category": draft["template_type"], "language": "en" if draft["message_type"] == "1" else "regional",
                      "master_body": draft["text"], "live_body": match.get("template_message", "") if match else "",
                      "match_confidence": 1.0 if match and match.get("template_message") == draft["text"] else 0.0,
                      "match_method": "EXACT" if match else "NONE", "diff_summary": status.replace("_", " "),
                      "live_fb_id": match.get("template_id") if match else None,
                      "live_status_raw": match.get("status") if match else None, "action_required": action})
    return {"account": account, "total_master": len(items), "whitelisted_count": counts["WHITELISTED"],
            "missing_count": counts["NOT_WHITELISTED"], "pending_count": counts["PENDING"],
            "rejected_count": counts["REJECTED"], "drift_count": counts["CONTENT_DRIFT"],
            "items": items, "missing_templates": missing,
            "summary_notes": "VILPOWER DLT compares exact copy and typed variable syntax; submission is not approval."}
