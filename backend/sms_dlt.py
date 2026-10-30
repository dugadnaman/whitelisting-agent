"""Tata VILPOWER DLT drafts and durable whitelisting outcomes, never SMS delivery."""

from __future__ import annotations

import csv
import threading
from concurrent.futures import Future
from datetime import UTC, datetime
from os.path import commonprefix
from pathlib import Path

from db import get_db
from db_queue import create_job_with_tasks
from tracker import _row_to_entry_dict

DRAFT_FIELDS = (
    "template_name", "text", "template_type", "category_id", "header_id", "header",
    "brand_id", "message_type", "sample_message", "service_type",
)

_inventory_flights: dict[tuple[str, str], Future] = {}
_inventory_lock = threading.Lock()


def _inventory(account: str, search: str = "") -> list[dict]:
    """Share concurrent catalog reads, without caching stale approvals or failures."""
    from vilpower_client import fetch_sms_templates
    require_tata(account)
    key = (account, search)
    with _inventory_lock:
        flight = _inventory_flights.get(key)
        leader = flight is None
        if leader:
            flight = Future()
            _inventory_flights[key] = flight
    if not leader:
        return flight.result()
    try:
        rows = fetch_sms_templates(client=account, search=search)
        flight.set_result(rows)
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
    require_tata(account)
    if not isinstance(row, dict):
        raise ValueError("Each SMS template must be an object.")
    for field in ("account", "client", "tenant_id"):
        if field in row and str(row[field]).strip().lower() != account:
            raise ValueError("SMS template account does not match Tata Capital.")
    if row.get("channel") and row["channel"] != "sms":
        raise ValueError("SMS template channel does not match the selected destination.")
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
    seen = set()
    for draft in drafts:
        key = draft["template_name"].casefold()
        existing = by_name.get(key, [])
        errors = validate_sms_template(draft)
        if key in seen:
            errors.append("Duplicate SMS template name in this batch.")
        seen.add(key)
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
    from vilpower_client import validate_sms_template

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
    tasks = []
    seen = {}
    for index, draft in enumerate(drafts, 1):
        key = draft["template_name"].casefold()
        candidates = by_name.get(key, [])
        exact = [item for item in candidates if item.get("template_message") == draft["text"] and item.get("header") == draft["header"]]
        exact.sort(key=lambda item: item.get("status") != "approved")
        live = exact[0] if exact else None
        payload = {**draft, "client": account, "channel": "sms", "provider": "vilpower",
                   "source_ref": draft.get("source_ref") or draft["template_name"], "submitted_by": user,
                   "source_file": draft.get("source_file") or filename,
                   "category": {"1": "PROMOTIONAL", "2": "TRANSACTIONAL", "3": "SERVICE"}[draft["template_type"]],
                   "language": "en" if draft["message_type"] == "1" else "regional"}
        if candidates and not live:
            raise ValueError(f"Row {index}: '{draft['template_name']}' already exists with different DLT content or a different header. Use a distinct name; registered copy is never overwritten.")
        fields = tuple(draft[field] for field in DRAFT_FIELDS)
        if key in seen and seen[key] != fields:
            raise ValueError(f"Row {index}: duplicate name has different SMS DLT fields. Use a distinct name.")
        if (live and skip_duplicates) or key in seen:
            payload.update(status="DUPLICATE", approval_status=live.get("status", "unknown") if live else "unknown",
                           provider_ref_id=live.get("template_id") if live else None,
                           error="Already registered on VILPOWER." if live else "Duplicate name within this batch.")
        seen[key] = fields
        tasks.append(payload)
    return create_job_with_tasks(account, "sms", filename, user, tasks)


def load_history(account: str = "tata") -> list[dict]:
    require_tata(account)
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM job_tasks WHERE tenant_id = ? AND channel = 'sms' ORDER BY created_at DESC", (account,)).fetchall()
    return [_row_to_entry_dict(dict(row)) for row in rows]


def merged_inventory(account: str = "tata") -> list[dict]:
    require_tata(account)
    live = _inventory(account)
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


def poll_approvals(account: str = "tata") -> dict:
    require_tata(account)
    pending = [row for row in load_history(account) if row["status"] in {"submitted", "duplicate"}
               and row["approval_status"] in {"pending", "unknown"} and row.get("provider_ref_id")]
    if not pending:
        return {"checked": 0, "updated": 0}
    inventory = {str(item["template_id"]): item for item in _inventory(account)}
    updated = 0
    with get_db() as conn:
        for entry in pending:
            live = inventory.get(str(entry["provider_ref_id"]))
            if not live or live.get("template_name") != entry["template_name"]:
                continue
            status = live.get("status", "unknown")
            if status not in {"pending", "approved", "rejected"} or status == entry["approval_status"]:
                continue
            cur = conn.execute(
                "UPDATE job_tasks SET approval_status = ?, approval_reason = ?, updated_at = ? "
                "WHERE id = ? AND tenant_id = ? AND channel = 'sms' AND provider_ref_id = ? "
                "AND approval_status IN ('pending', 'unknown')",
                (status, live.get("approval_reason"), datetime.now(UTC).isoformat(), entry["task_id"], account, entry["provider_ref_id"]),
            )
            updated += cur.rowcount
    return {"checked": len(pending), "updated": updated}


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
