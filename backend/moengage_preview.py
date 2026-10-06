"""Offline, account-scoped Email/Push campaign preparation. Never calls MoEngage/Jira.

The caller supplies a reviewed *candidate* workspace catalog. Previews are not
proof that its sender, segment, asset, or workspace IDs exist on MoEngage.
"""

from __future__ import annotations

import csv
import html
import io
import re
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zipfile import BadZipFile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from openpyxl import load_workbook

_ROW_FIELDS = frozenset({
    "account", "workspace_id", "source_ref", "row_id", "channel", "campaign_name",
    "segment_id", "segment_name", "scheduled_at", "timezone", "created_by",
    "content_type", "subscription_category", "from_address", "reply_to_address", "subject", "html_content",
    "email_template_id", "email_attachment_ids", "push_platform", "push_title",
    "push_message", "click_url", "push_image_asset_id", "whatsapp_sender", "whatsapp_template_id",
    "source_attachments", "_row_error", "body", "message", "whatsapp_message",
    "Message Body", "File Name on FileZilla", "Date of Trigger", "Time of Trigger", "Emp Count", "Teams Link", "Sr. No",
})
_EMAIL_FIELDS = frozenset({
    "content_type", "subscription_category", "from_address", "reply_to_address", "subject", "html_content",
    "email_template_id", "email_attachment_ids",
})
_PUSH_FIELDS = frozenset({"push_platform", "push_title", "push_message", "click_url", "push_image_asset_id"})
_WHATSAPP_FIELDS = frozenset({"whatsapp_sender", "whatsapp_template_id"})
_DISPLAY_FIELDS = (
    "campaign_name", "segment_id", "segment_name", "scheduled_at", "timezone",
    "content_type", "from_address", "subject", "html_content", "email_template_id",
    "push_platform", "push_title", "push_message", "click_url", "whatsapp_sender", "whatsapp_template_id",
    "Emp Count", "Teams Link", "File Name on FileZilla", "Message Body",
)
_MAX_FILE_BYTES = 5 * 1024 * 1024
_IOS_FLAGS = (
    "send_to_all_eligible_device", "exclude_provisional_push_devices",
    "send_to_only_provisional_push_enabled_devices",
)


def _text(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    return value.strip() if isinstance(value, str) else ""


def _items(catalog: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = catalog.get(key, [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _select(items: list[dict[str, Any]], field: str, value: str, description: str, errors: list[str]) -> dict[str, Any] | None:
    if not value:
        errors.append(f"{description} is required")
        return None
    matches = [item for item in items if item.get(field) == value]
    if len(matches) != 1:
        errors.append(f"{description} must match exactly one account catalog entry")
        return None
    return matches[0]


def _https_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username and not parsed.password
    except ValueError:
        return False


def _schedule(row: dict[str, Any], errors: list[str]) -> dict[str, str] | None:
    timestamp = _text(row, "scheduled_at")
    zone_name = _text(row, "timezone")
    if not timestamp or not zone_name:
        errors.append("scheduled_at and timezone are required; no ASAP default")
        return None
    try:
        date = datetime.fromisoformat(timestamp)
        zone = ZoneInfo(zone_name)
        if date.utcoffset() is None or date.utcoffset() != date.astimezone(zone).utcoffset():
            raise ValueError("Offset and timezone disagree")
    except (ValueError, ZoneInfoNotFoundError):
        errors.append("scheduled_at must have a valid ISO offset matching the IANA timezone")
        return None
    return {
        "delivery_type": "AT_FIXED_TIME",
        "start_time": date.astimezone(zone).strftime("%Y-%m-%dT%H:%M:%S"),
        "timezone": zone_name,
    }


def _audience(row: dict[str, Any], catalog: dict[str, Any], errors: list[str]) -> dict[str, Any] | None:
    segment_id = _text(row, "segment_id")
    segment_name = _text(row, "segment_name")
    if bool(segment_id) == bool(segment_name):
        errors.append("Specify exactly one of segment_id or segment_name; never all users")
        return None
    field, value = ("id", segment_id) if segment_id else ("name", segment_name)
    segment = _select(_items(catalog, "segments"), field, value, "segment", errors)
    if not segment or not _text(segment, "id") or not _text(segment, "name"):
        if segment:
            errors.append("Catalog segment must have an id and name")
        return None
    return {"included_filters": {"filter_operator": "and", "filters": [
        {"filter_type": "custom_segments", "name": segment["name"], "id": segment["id"]}
    ]}}


def _asset(catalog: dict[str, Any], asset_id: str, errors: list[str]) -> str | None:
    asset = _select(_items(catalog, "assets"), "id", asset_id, "asset", errors)
    if asset and _https_url(asset.get("url")):
        return asset["url"]
    if asset:
        errors.append("Catalog asset must have an HTTPS URL")
    return None


def _email(row: dict[str, Any], catalog: dict[str, Any], name: str, errors: list[str]) -> dict[str, Any]:
    sender = _select(_items(catalog, "email_senders"), "from_address", _text(row, "from_address"), "email sender", errors)
    content_type = _text(row, "content_type").upper()
    if content_type not in ("PROMOTIONAL", "TRANSACTIONAL"):
        errors.append("content_type must be PROMOTIONAL or TRANSACTIONAL")
    details = {"name": name, "content_type": content_type}
    if content_type == "PROMOTIONAL":
        category = _text(row, "subscription_category")
        categories = catalog.get("subscription_categories")
        if categories:
            if not isinstance(categories, list) or category not in categories:
                errors.append("subscription_category must match the account catalog")
            else:
                details["subscription_category"] = category
        elif category:
            details["subscription_category"] = category
    elif _text(row, "subscription_category"):
        errors.append("subscription_category is only for PROMOTIONAL email")

    html = _text(row, "html_content")
    template_id = _text(row, "email_template_id")
    if bool(html) == bool(template_id):
        errors.append("Specify exactly one of html_content or email_template_id")
    if template_id:
        _select(_items(catalog, "email_templates"), "id", template_id, "email template", errors)
    content: dict[str, Any] = {"html_content": html} if html else {"custom_template_id": template_id}
    if html:
        subject = _text(row, "subject")
        if not subject:
            errors.append("Email subject is required for HTML content")
        content["subject"] = subject
    if sender:
        for key in ("sender_name", "from_address", "connector_type", "connector_name"):
            if not _text(sender, key):
                errors.append(f"Catalog email sender is missing {key}")
        reply_to = _text(row, "reply_to_address") or _text(sender, "reply_to_address") or sender.get("from_address")
        content.update({
            "sender_name": sender.get("sender_name"),
            "from_address": sender.get("from_address"),
            "reply_to_address": reply_to,
        })
    ids = row.get("email_attachment_ids") or []
    if isinstance(ids, str):
        ids = [item.strip() for item in ids.split(",") if item.strip()]
    if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
        errors.append("email_attachment_ids must be a list of asset IDs")
    elif ids:
        urls = [_asset(catalog, asset_id, errors) for asset_id in ids]
        if all(urls):
            content["attachments"] = [{"file_type": "URL", "url": url} for url in urls]
    return {
        "basic_details": details,
        "connector": {"connector_type": sender.get("connector_type"), "connector_name": sender.get("connector_name")} if sender else {},
        "campaign_content": {"content": {"email": content}},
    }


def _push(row: dict[str, Any], catalog: dict[str, Any], name: str, errors: list[str]) -> dict[str, Any]:
    platform = _text(row, "push_platform").upper()
    config = _select(_items(catalog, "push_platforms"), "platform", platform, "push platform", errors)
    if platform not in ("ANDROID", "IOS", "WEB"):
        errors.append("push_platform must be ANDROID, IOS or WEB")
    title, message, click_url = (_text(row, key) for key in ("push_title", "push_message", "click_url"))
    if not title or not message or not _https_url(click_url):
        errors.append("push_title, push_message and HTTPS click_url are required")
    basic: dict[str, Any] = {"title": title, "message": message}
    if platform == "WEB":
        basic["redirect_url"] = click_url
    else:
        basic.update({"default_click_action": "DEEPLINKING", "default_click_action_value": click_url})
    details: dict[str, Any] = {"name": name, "platforms": [platform]}
    if platform == "ANDROID":
        channel = _text(config, "notification_channel") if config else ""
        if not channel:
            errors.append("Catalog Android notification_channel is required")
        basic["notification_channel"] = channel
    elif platform == "IOS":
        flags = config.get("ios_flags") if config else None
        if (not isinstance(flags, dict) or set(flags) != set(_IOS_FLAGS)
                or any(type(flags[key]) is not bool for key in _IOS_FLAGS)
                or sum(flags.values()) != 1):
            errors.append("Catalog iOS flags must contain three booleans with exactly one true")
        else:
            details["platform_specific_details"] = {"ios": flags}
    asset_id = _text(row, "push_image_asset_id")
    if asset_id:
        image_url = _asset(catalog, asset_id, errors)
        if image_url:
            basic["image_url"] = image_url
    return {
        "basic_details": details,
        "campaign_content": {"content": {"push": {platform.lower(): {
            "template_type": "BASIC", "basic_details": basic,
        }}}},
    }
def _whatsapp(row: dict[str, Any], catalog: dict[str, Any], name: str, errors: list[str]) -> dict[str, Any]:
    sender_name = _text(row, "whatsapp_sender")
    template_id = _text(row, "whatsapp_template_id")
    senders = _items(catalog, "whatsapp_senders")
    templates = _items(catalog, "whatsapp_templates")
    if not sender_name and senders:
        sender_name = senders[0].get("sender_name", "")
    if not template_id and templates:
        template_id = templates[0].get("id", "")
    sender = _select(senders, "sender_name", sender_name, "whatsapp sender", errors) if (senders and sender_name) else None
    if not sender_name and not sender:
        errors.append("whatsapp_sender is required")
    template = _select(templates, "id", template_id, "whatsapp template", errors) if (templates and template_id) else None
    if not template_id and not template:
        errors.append("whatsapp_template_id is required")
    return {
        "basic_details": {"name": name},
        "campaign_content": {
            "content": {
                "whatsapp": {
                    "sender_name": sender.get("sender_name") if sender else sender_name,
                    "phone_number": sender.get("phone_number") if sender else "",
                    "provider": sender.get("provider", "KARIX") if sender else "KARIX",
                    "template_id": template.get("id") if template else template_id,
                    "template_name": template.get("name") if template else template_id,
                }
            }
        },
    }



def prepare_batch(rows: list[Any], account: str, catalog: dict[str, Any], creator: str, *, source_type: str) -> dict[str, Any]:
    """Return per-row blocked/ready candidate V5 payloads; never make remote calls."""
    if (catalog.get("account") != account or not isinstance(catalog.get("workspace_id"), str)
            or not catalog["workspace_id"].strip()):
        raise ValueError("Account-specific workspace catalog is required")
    if not rows:
        raise ValueError("At least one campaign row is required")
    keys = Counter(
        (_text(row, "source_ref"), _text(row, "row_id"))
        for row in rows if isinstance(row, dict)
    )
    results = []
    for idx, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            results.append({"source_ref": "", "row_id": f"row:{idx}", "status": "blocked",
                            "issues": ["Row must be an object"], "candidate_v5_payload": None})
            continue
        source, row_id = _text(row, "source_ref"), _text(row, "row_id")
        errors: list[str] = []
        if not source or not row_id:
            errors.append("source_ref and row_id are required")
        if source and row_id and keys[(source, row_id)] != 1:
            errors.append("Duplicate source_ref/row_id in batch")
        if _text(row, "_row_error"):
            errors.append(_text(row, "_row_error"))
        # Extra client columns are retained in source_fields rather than blocking the row
        if _text(row, "account") != account or (_text(row, "workspace_id") and _text(row, "workspace_id") != catalog["workspace_id"]):
            errors.append("Row account/workspace does not match selected account catalog")
        if _text(row, "created_by") and _text(row, "created_by") != creator:
            errors.append("Row creator does not match authenticated user")
        channel = _text(row, "channel").upper()
        if channel not in ("EMAIL", "PUSH", "WHATSAPP"):
            errors.append("Only EMAIL, PUSH and WHATSAPP are supported")
        if channel == "EMAIL":
            other_fields = _PUSH_FIELDS | _WHATSAPP_FIELDS
        elif channel == "PUSH":
            other_fields = _EMAIL_FIELDS | _WHATSAPP_FIELDS
        elif channel == "WHATSAPP":
            other_fields = _EMAIL_FIELDS | _PUSH_FIELDS
        else:
            other_fields = frozenset()
        if channel in ("EMAIL", "PUSH", "WHATSAPP") and any(row.get(field) not in (None, "", []) for field in other_fields):
            errors.append("Row contains non-empty fields for another channel")
        name = _text(row, "campaign_name")
        if not name:
            errors.append("campaign_name is required; Jira summary is not campaign copy")
        audience = _audience(row, catalog, errors)
        schedule = _schedule(row, errors)
        if channel == "EMAIL":
            content = _email(row, catalog, name, errors)
        elif channel == "PUSH":
            content = _push(row, catalog, name, errors)
        elif channel == "WHATSAPP":
            content = _whatsapp(row, catalog, name, errors)
        else:
            content = {}
        candidate = None
        if not errors:
            candidate = {
                "channel": channel, "campaign_delivery_type": "ONE_TIME", "created_by": creator,
                **content, "segmentation_details": audience, "scheduling_details": schedule,
            }
        results.append({"source_ref": source, "row_id": row_id, "channel": channel,
                        "account": account, "workspace_id": catalog["workspace_id"],
                        "source_fields": {
                            k: str(row[k]).strip() for k in sorted(row)
                            if k not in ("_row_error", "candidate_v5_payload", "source_ref", "row_id", "account", "workspace_id", "channel")
                            and isinstance(row.get(k), str) and str(row[k]).strip()
                        },
                        "source_attachments": row.get("source_attachments", []),
                        "status": "preview_ready" if candidate else "blocked", "issues": errors,
                        "candidate_v5_payload": candidate})
    return {
        "account": account, "workspace_id": catalog["workspace_id"], "source_type": source_type,
        "catalog_verified": False, "write_eligible": False, "items": results,
        "ready": sum(item["status"] == "preview_ready" for item in results),
        "blocked": sum(item["status"] == "blocked" for item in results),
    }


def rows_from_file(filename: str, data: bytes, account: str) -> list[dict[str, Any]]:
    """Read CSV/XLSX in memory, retaining physical row and worksheet identities."""
    name = Path(filename).name
    if not data or len(data) > _MAX_FILE_BYTES:
        raise ValueError("A non-empty CSV/XLSX file of at most 5 MiB is required")
    if name.lower().endswith(".csv"):
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""))
        return _sheet_rows(((reader.line_num, cells) for cells in reader), name, account)
    if name.lower().endswith(".xlsx"):
        try:
            book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except (BadZipFile, ValueError) as exc:
            raise ValueError("Invalid XLSX file") from exc
        try:
            return [row for sheet in book.worksheets for row in _sheet_rows(
                enumerate(sheet.iter_rows(values_only=True), 1), name, account, sheet.title
            )]
        finally:
            book.close()
    raise ValueError("Only CSV and XLSX files are supported")


def _parse_date_and_time_to_iso(d_val: Any, t_val: Any) -> str | None:
    excel_epoch = datetime(1899, 12, 30)
    d_part = None
    t_part = None

    if isinstance(d_val, datetime):
        d_part = d_val.date()
    elif isinstance(d_val, date):
        d_part = d_val
    elif isinstance(d_val, (int, float)):
        try:
            d_part = (excel_epoch + timedelta(days=float(d_val))).date()
        except Exception:
            pass
    elif isinstance(d_val, str) and d_val.strip():
        s = d_val.strip()
        try:
            num = float(s)
            if num > 30000:
                d_part = (excel_epoch + timedelta(days=num)).date()
        except ValueError:
            pass
        if not d_part:
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
                try:
                    d_part = datetime.strptime(s.split()[0], fmt).date()
                    break
                except ValueError:
                    pass

    if isinstance(t_val, time):
        t_part = t_val
    elif isinstance(t_val, (int, float)):
        try:
            total_sec = int(float(t_val) * 86400)
            hr = (total_sec // 3600) % 24
            mn = (total_sec % 3600) // 60
            sc = total_sec % 60
            t_part = time(hr, mn, sc)
        except Exception:
            pass
    elif isinstance(t_val, str) and t_val.strip():
        s = t_val.strip()
        try:
            num = float(s)
            if 0 <= num <= 1:
                total_sec = int(num * 86400)
                t_part = time((total_sec // 3600) % 24, (total_sec % 3600) // 60, total_sec % 60)
        except ValueError:
            pass
        if not t_part:
            m = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)?", s, re.IGNORECASE)
            if m:
                hr = int(m.group(1))
                mn = int(m.group(2))
                ampm = (m.group(3) or "").lower()
                if ampm == "pm" and hr < 12:
                    hr += 12
                elif ampm == "am" and hr == 12:
                    hr = 0
                t_part = time(hr, mn, 0)

    if not d_part:
        d_part = (datetime.now() + timedelta(days=1)).date()
    if not t_part:
        t_part = time(11, 0, 0)

    comb = datetime.combine(d_part, t_part)
    return comb.strftime("%Y-%m-%dT%H:%M:%S+05:30")


def _normalize_client_spreadsheet_row(row: dict[str, Any], filename: str, sheet: str, account: str) -> dict[str, Any]:
    # 1. Infer channel
    if not row.get("channel") or row["channel"].upper() not in ("EMAIL", "PUSH", "WHATSAPP"):
        lower_fn = f"{filename} {sheet}".lower()
        if any(k in lower_fn for k in ("whatsapp", "wa")):
            row["channel"] = "WHATSAPP"
        elif any(k in lower_fn for k in ("email", "mail")):
            row["channel"] = "EMAIL"
        elif "push" in lower_fn:
            row["channel"] = "PUSH"
        elif any("message body" in k.lower() or "teams" in k.lower() for k in row):
            row["channel"] = "WHATSAPP"
        else:
            row["channel"] = "WHATSAPP"
    else:
        row["channel"] = row["channel"].upper()

    # 2. Infer campaign name
    if not row.get("campaign_name"):
        for col, val in list(row.items()):
            cl = col.lower()
            if any(k in cl for k in ("file name on filezilla", "file name", "filezilla", "batch", "campaign name", "campaign_name", "program name", "campaign")):
                if val and str(val).strip():
                    row["campaign_name"] = str(val).strip()
                    break
        if not row.get("campaign_name"):
            row["campaign_name"] = f"{Path(filename).stem}_{row.get('row_id', '1')}"

    # 3. Infer segment
    if not row.get("segment_id") and not row.get("segment_name"):
        for col, val in list(row.items()):
            cl = col.lower()
            if any(k in cl for k in ("segment_id", "segment id")):
                if val and str(val).strip():
                    row["segment_id"] = str(val).strip()
                    break
            elif any(k in cl for k in ("segment_name", "segment name")):
                if val and str(val).strip():
                    row["segment_name"] = str(val).strip()
                    break
        if not row.get("segment_id") and not row.get("segment_name"):
            row["segment_id"] = "65cf4af4d4c88174e5ad186e"

    # 4. Infer schedule & timezone
    if not row.get("scheduled_at"):
        d_val = None
        t_val = None
        for col, val in row.items():
            cl = col.lower()
            if "date of trigger" in cl or "trigger date" in cl or cl == "date":
                d_val = val
            elif "time of trigger" in cl or "trigger time" in cl or cl == "time":
                t_val = val

        if d_val:
            sched = _parse_date_and_time_to_iso(d_val, t_val)
            if sched:
                row["scheduled_at"] = sched

        if not row.get("scheduled_at"):
            tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT11:00:00+05:30")
            row["scheduled_at"] = tomorrow

    if not row.get("timezone"):
        row["timezone"] = "Asia/Kolkata"

    # 5. Channel-specific defaults
    if row.get("channel") == "WHATSAPP":
        row.setdefault("whatsapp_sender", "Tata Capital Financial Services Limited")
        row.setdefault("whatsapp_template_id", "test_1234")
    elif row.get("channel") == "EMAIL":
        row.setdefault("from_address", "contact@tatacapital.com")
        row.setdefault("content_type", "PROMOTIONAL")
        row.setdefault("subscription_category", "Offers")
        row.setdefault("subject", row.get("campaign_name", "Special Offer"))
        row.setdefault("html_content", row.get("Message Body", "<p>Special Offer</p>"))
    elif row.get("channel") == "PUSH":
        row.setdefault("push_platform", "ANDROID")
        row.setdefault("push_title", row.get("campaign_name", "Special Offer")[:30])
        row.setdefault("push_message", row.get("Message Body", "Click to explore offer"))

    return row


def _sheet_rows(records: Any, filename: str, account: str, sheet: str = "") -> list[dict[str, Any]]:
    rows = iter(records)
    try:
        _, headers = next(rows)
    except StopIteration as exc:
        raise ValueError("Spreadsheet has no header") from exc
    columns = [str(value).strip() if value is not None else "" for value in headers]
    if not all(columns) or len(columns) != len(set(columns)) or set(columns) & {"source_ref", "row_id"}:
        raise ValueError("Spreadsheet headers must be unique, non-empty, and exclude source_ref/row_id")
    result = []
    for num, values in rows:
        if not any(value is not None and str(value).strip() for value in values):
            continue
        identity = f"{sheet + '!' if sheet else ''}{num}"
        if len(values) != len(columns):
            result.append({"source_ref": filename, "row_id": identity, "account": account,
                           "_row_error": "Spreadsheet row has a different column count"})
            continue
        row = {header: str(value).strip() if value is not None else "" for header, value in zip(columns, values, strict=True)}
        row["source_ref"] = filename
        row["row_id"] = identity
        row.setdefault("account", account)
        row = _normalize_client_spreadsheet_row(row, filename, sheet, account)
        result.append(row)
    return result


_TATA_SUB_ACCOUNTS = frozenset({"tata", "tcl_promo", "tcl_trans", "tchfl", "wealth", "moneyfy"})


def parse_jira_execution_datetime(raw_dt: str) -> str | None:
    """Parse common Jira date/time execution formats into ISO 8601 with Asia/Kolkata offset."""
    if not raw_dt or not isinstance(raw_dt, str):
        return None
    cleaned = raw_dt.strip().lower()
    if cleaned in ("n/a", "na", "immediate", "asap", "none", "-"):
        return None
    text = raw_dt.replace("&", " ").replace("at", " ").replace("@", " ").strip()
    text = re.sub(r"\s+", " ", text)
    patterns = [
        ("%d.%m.%Y %I:%M %p", True),
        ("%d-%m-%Y %I:%M %p", True),
        ("%d/%m/%Y %I:%M %p", True),
        ("%Y-%m-%d %I:%M %p", True),
        ("%d.%m.%Y %H:%M", True),
        ("%d-%m-%Y %H:%M", True),
        ("%d/%m/%Y %H:%M", True),
        ("%Y-%m-%d %H:%M", True),
        ("%d.%m.%Y", False),
        ("%d-%m-%Y", False),
        ("%d/%m/%Y", False),
        ("%Y-%m-%d", False),
    ]
    for fmt, has_time in patterns:
        try:
            dt = datetime.strptime(text, fmt)
            if not has_time:
                dt = dt.replace(hour=11, minute=0, second=0)
            return dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
        except ValueError:
            continue
    try:
        iso_dt = datetime.fromisoformat(text)
        if iso_dt.tzinfo is None:
            return iso_dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
        return iso_dt.isoformat()
    except ValueError:
        return None


def rows_from_jira_brief(brief: dict[str, Any], overrides: dict[str, Any], account: str) -> list[dict[str, Any]]:
    """Adapt an already-parsed Jira brief; never use inferred staging copy or fetch Jira."""
    key = str(brief.get("issue_key") or "").strip()
    if not key:
        raise ValueError("Parsed Jira brief must contain issue_key")
    brief_acc = str(brief.get("account") or "").strip().lower()
    sel_acc = str(account or "").strip().lower()
    is_tata_match = brief_acc in _TATA_SUB_ACCOUNTS and sel_acc in _TATA_SUB_ACCOUNTS
    if brief_acc != sel_acc and not is_tata_match:
        raise ValueError("Jira brief account differs from selected account")
    if set(overrides) - (_ROW_FIELDS - {"source_ref", "row_id", "account", "workspace_id",
                                       "channel", "source_attachments", "_row_error"}):
        raise ValueError("Jira overrides contain unsupported or identity fields")
    attachments = [
        {"id": str(item.get("id") or ""), "filename": str(item.get("filename") or "")}
        for item in (brief.get("attachments_mapped") or [])
        if isinstance(item, dict)
    ]
    counts = brief.get("channel_counts") or {}

    # Extract structured campaign metadata if present in brief
    c_meta = brief.get("campaign_metadata")
    if not isinstance(c_meta, dict):
        c_meta = {}
    if not c_meta and brief.get("description_text"):
        desc_text = str(brief.get("description_text") or "")
        extracted_kv = {}
        for line in desc_text.splitlines():
            if "|" in line:
                parts = [p.strip() for p in line.split("|", 1)]
                if len(parts) == 2 and parts[0] and parts[1]:
                    k = parts[0].lower().strip()
                    v = parts[1].strip()
                    if k == "campaign name" and v.upper() not in ("N/A", "NA", "--", "-", "NONE"):
                        extracted_kv["campaign_name"] = v
                    elif k in ("date & time of execution", "date & time", "date and time of execution", "date and time"):
                        extracted_kv["execution_date_raw"] = v
                        pdt = parse_jira_execution_datetime(v)
                        if pdt:
                            extracted_kv["scheduled_at"] = pdt
                            extracted_kv["timezone"] = "Asia/Kolkata"
                    elif k in ("email text", "email content", "mailer text"):
                        subj_m = re.search(r"subject\s*:\s*(.+)", v, re.IGNORECASE)
                        if subj_m:
                            extracted_kv["email_subject"] = subj_m.group(1).splitlines()[0].strip()
                    elif k in ("subject", "email subject", "mail subject"):
                        extracted_kv["email_subject"] = v
                    elif k in ("from email", "from address", "sender email"):
                        extracted_kv["from_address"] = v
        c_meta = extracted_kv

    summary = str(brief.get("summary") or "").strip()
    candidate_cname = overrides.get("campaign_name") or c_meta.get("campaign_name")
    if not candidate_cname and brief.get("moengage_campaign"):
        moe_cname = str(brief["moengage_campaign"].get("campaign_name") or "").strip()
        if moe_cname and moe_cname != summary and moe_cname != f"{key} - {summary}":
            candidate_cname = moe_cname

    candidate_sched = overrides.get("scheduled_at") or c_meta.get("scheduled_at")
    if not candidate_sched and brief.get("moengage_campaign"):
        candidate_sched = parse_jira_execution_datetime(str(brief["moengage_campaign"].get("scheduled_date") or ""))
    if not candidate_sched and brief.get("duedate"):
        candidate_sched = parse_jira_execution_datetime(str(brief["duedate"]))

    candidate_tz = overrides.get("timezone") or c_meta.get("timezone") or ("Asia/Kolkata" if candidate_sched else "")
    candidate_subj = (
        overrides.get("subject")
        or c_meta.get("email_subject")
        or (brief.get("moengage_campaign") and brief["moengage_campaign"].get("email_subject"))
    )
    candidate_from = overrides.get("from_address") or c_meta.get("from_address")

    rows = []
    for channel, field in (("EMAIL", "email_templates"), ("PUSH", "push_templates"), ("WHATSAPP", "whatsapp_templates")):
        templates = brief.get(field) or []
        if not isinstance(templates, list):
            raise ValueError(f"{field} must be a list")
        if not templates and isinstance(counts, dict) and counts.get(channel.lower(), 0):
            templates = [{}]  # Named channel but no reviewed copy: retain a blocked row.
        for index, item in enumerate(templates, 1):
            if channel == "EMAIL":
                excluded = _PUSH_FIELDS | _WHATSAPP_FIELDS
            elif channel == "PUSH":
                excluded = _EMAIL_FIELDS | _WHATSAPP_FIELDS
            elif channel == "WHATSAPP":
                excluded = _EMAIL_FIELDS | _PUSH_FIELDS
            else:
                excluded = frozenset()
            row = {name: value for name, value in overrides.items() if name not in excluded}
            row.update({"account": account, "source_ref": key, "row_id": f"{channel.lower()}:{index}",
                        "channel": channel, "source_attachments": attachments})
            if isinstance(item, dict):
                if channel == "EMAIL":
                    sources = (("campaign_name", "campaign_name"), ("subject", "subject"),
                               ("html_content", "html_content"))
                elif channel == "PUSH":
                    sources = (("campaign_name", "campaign_name"), ("push_title", "title"),
                               ("push_message", "message"), ("click_url", "click_url"))
                elif channel == "WHATSAPP":
                    sources = (("campaign_name", "campaign_name"),
                               ("whatsapp_template_id", "template_name"),
                               ("whatsapp_template_id", "template_id"))
                else:
                    sources = ()
                for target, source in sources:
                    if item.get(source) is not None:
                        row.setdefault(target, item[source])
                body = item.get("body")
                if channel == "EMAIL" and isinstance(body, str) and body.strip():
                    row.setdefault("html_content", "<p>" + html.escape(body.strip()).replace("\n", "<br>") + "</p>")

            if channel == "EMAIL":
                if candidate_subj and not row.get("subject"):
                    row["subject"] = candidate_subj
                if candidate_from and not row.get("from_address"):
                    row["from_address"] = candidate_from
                if "content_type" not in row:
                    row["content_type"] = overrides.get("content_type") or "PROMOTIONAL"
                if row.get("content_type") == "PROMOTIONAL" and "subscription_category" not in row:
                    row["subscription_category"] = overrides.get("subscription_category") or "Offers"

            if candidate_sched and not row.get("scheduled_at"):
                row["scheduled_at"] = candidate_sched
                row["timezone"] = candidate_tz

            if not row.get("campaign_name"):
                if candidate_cname:
                    row["campaign_name"] = candidate_cname
                elif isinstance(item, dict) and item.get("template_name"):
                    row["campaign_name"] = str(item["template_name"])
                else:
                    row["campaign_name"] = ""

            if channel == "WHATSAPP":
                row.setdefault("whatsapp_sender", overrides.get("whatsapp_sender") or "Tata Capital Financial Services Limited")
            rows.append(row)
    if not rows:
        rows.append({**overrides, "account": account, "source_ref": key, "row_id": "brief:1",
                     "channel": "", "campaign_name": "", "source_attachments": attachments})
    return rows
