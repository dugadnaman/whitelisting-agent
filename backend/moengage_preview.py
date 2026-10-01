"""Offline, account-scoped Email/Push campaign preparation. Never calls MoEngage/Jira.

The caller supplies a reviewed *candidate* workspace catalog. Previews are not
proof that its sender, segment, asset, or workspace IDs exist on MoEngage.
"""

from __future__ import annotations

import csv
import html
import io
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zipfile import BadZipFile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from openpyxl import load_workbook

_ROW_FIELDS = frozenset({
    "account", "workspace_id", "source_ref", "row_id", "channel", "campaign_name",
    "segment_id", "segment_name", "scheduled_at", "timezone", "created_by",
    "content_type", "subscription_category", "from_address", "subject", "html_content",
    "email_template_id", "email_attachment_ids", "push_platform", "push_title",
    "push_message", "click_url", "push_image_asset_id", "source_attachments", "_row_error",
})
_EMAIL_FIELDS = frozenset({
    "content_type", "subscription_category", "from_address", "subject", "html_content",
    "email_template_id", "email_attachment_ids",
})
_PUSH_FIELDS = frozenset({"push_platform", "push_title", "push_message", "click_url", "push_image_asset_id"})
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
    return {"delivery_type": "AT_FIXED_TIME", "start_time": date.astimezone(UTC).isoformat()}


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
        if not isinstance(categories, list) or category not in categories:
            errors.append("subscription_category must match the account catalog")
        else:
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
        content.update({"sender_name": sender.get("sender_name"), "from_address": sender.get("from_address")})

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
        extras = set(row) - _ROW_FIELDS
        if extras:
            errors.append("Unsupported fields: " + ", ".join(sorted(extras)))
        if _text(row, "account") != account or (_text(row, "workspace_id") and _text(row, "workspace_id") != catalog["workspace_id"]):
            errors.append("Row account/workspace does not match selected account catalog")
        if _text(row, "created_by") and _text(row, "created_by") != creator:
            errors.append("Row creator does not match authenticated user")
        channel = _text(row, "channel").upper()
        if channel not in ("EMAIL", "PUSH"):
            errors.append("Only EMAIL and PUSH are supported")
        other_fields = _PUSH_FIELDS if channel == "EMAIL" else _EMAIL_FIELDS
        if channel in ("EMAIL", "PUSH") and any(row.get(field) not in (None, "", []) for field in other_fields):
            errors.append("Row contains non-empty fields for another channel")
        name = _text(row, "campaign_name")
        if not name:
            errors.append("campaign_name is required; Jira summary is not campaign copy")
        audience = _audience(row, catalog, errors)
        schedule = _schedule(row, errors)
        content = _email(row, catalog, name, errors) if channel == "EMAIL" else (
            _push(row, catalog, name, errors) if channel == "PUSH" else {}
        )
        candidate = None
        if not errors:
            candidate = {
                "channel": channel, "campaign_delivery_type": "ONE_TIME", "created_by": creator,
                **content, "segmentation_details": audience, "scheduling_details": schedule,
            }
        results.append({"source_ref": source, "row_id": row_id, "channel": channel,
                        "account": account, "workspace_id": catalog["workspace_id"],
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
        result.append(row)
    return result


def rows_from_jira_brief(brief: dict[str, Any], overrides: dict[str, Any], account: str) -> list[dict[str, Any]]:
    """Adapt an already-parsed Jira brief; never use inferred staging copy or fetch Jira."""
    key = str(brief.get("issue_key") or "").strip()
    if not key:
        raise ValueError("Parsed Jira brief must contain issue_key")
    if brief.get("account") != account:
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
    rows = []
    for channel, field in (("EMAIL", "email_templates"), ("PUSH", "push_templates")):
        templates = brief.get(field) or []
        if not isinstance(templates, list):
            raise ValueError(f"{field} must be a list")
        if not templates and isinstance(counts, dict) and counts.get(channel.lower(), 0):
            templates = [{}]  # Named channel but no reviewed copy: retain a blocked row.
        for index, item in enumerate(templates, 1):
            excluded = _PUSH_FIELDS if channel == "EMAIL" else _EMAIL_FIELDS
            row = {name: value for name, value in overrides.items() if name not in excluded}
            row.update({"account": account, "source_ref": key, "row_id": f"{channel.lower()}:{index}",
                        "channel": channel, "source_attachments": attachments})
            if isinstance(item, dict):
                sources = (("campaign_name", "campaign_name"), ("subject", "subject"),
                           ("html_content", "html_content")) if channel == "EMAIL" else (
                           ("campaign_name", "campaign_name"), ("push_title", "title"),
                           ("push_message", "message"), ("click_url", "click_url"))
                for target, source in sources:
                    if item.get(source) is not None:
                        row.setdefault(target, item[source])
                body = item.get("body")
                if channel == "EMAIL" and isinstance(body, str) and body.strip():
                    row.setdefault("html_content", "<p>" + html.escape(body.strip()).replace("\n", "<br>") + "</p>")
            if not row.get("campaign_name"):
                row["campaign_name"] = ""  # Jira summary is not approved campaign content.
            rows.append(row)
    if not rows:
        rows.append({**overrides, "account": account, "source_ref": key, "row_id": "brief:1",
                     "channel": "", "campaign_name": "", "source_attachments": attachments})
    return rows
