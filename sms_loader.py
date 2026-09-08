"""
Input loader for Karix SMS messages.

Loads SMS messages from CSV, Excel (.xlsx, .xls), or Python dictionaries into
validated SmsMessage objects, with flexible column header aliasing and data sanitization.
"""

import csv
import logging
import re
from pathlib import Path
from typing import Any

from sms_config import get_sms_dlt_entity_id, get_sms_sender_id
from sms_models import SmsMessage, SmsMessageType

logger = logging.getLogger(__name__)

# Column aliases for robust CSV / Excel header matching
_KEY_ALIASES: dict[str, str] = {
    # Destination mobile numbers
    "dest": "dest",
    "destination": "dest",
    "destinations": "dest",
    "mobile": "dest",
    "mobiles": "dest",
    "mobile_number": "dest",
    "mobile_numbers": "dest",
    "mobile_no": "dest",
    "phone": "dest",
    "phones": "dest",
    "phone_number": "dest",
    "phone_no": "dest",
    "recipient": "dest",
    "recipients": "dest",
    "to": "dest",
    # Message content
    "text": "text",
    "message": "text",
    "msg": "text",
    "content": "text",
    "body": "text",
    "sms_text": "text",
    "message_text": "text",
    "send": "send",
    "sender": "send",
    "sender_id": "send",
    "senderid": "send",
    "header": "send",
    "from": "send",
    # Message Type
    "type": "type",
    "msg_type": "type",
    "message_type": "type",
    # DLT Identifiers
    "dlt_entity_id": "dlt_entity_id",
    "entity_id": "dlt_entity_id",
    "pe_id": "dlt_entity_id",
    "principal_entity_id": "dlt_entity_id",
    "dlt_template_id": "dlt_template_id",
    "template_id": "dlt_template_id",
    "dlt_id": "dlt_template_id",
    "content_template_id": "dlt_template_id",
    # References & Tags
    "cust_ref": "cust_ref",
    "customer_ref": "cust_ref",
    "ref_id": "cust_ref",
    "reference": "cust_ref",
    "tag": "tag",
    "tag1": "tag1",
    "tag2": "tag2",
    "tag3": "tag3",
    "tag4": "tag4",
    "tag5": "tag5",
    # Template dynamic parameters
    "template_values": "template_values",
    "dynamic_values": "template_values",
    "variables": "template_values",
}


def _normalize_sms_row_keys(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize row keys to standard SmsMessage field names."""
    normalized = {}
    for k, v in row.items():
        if not k:
            continue
        clean_k = re.sub(r"[^a-zA-Z0-9_]", "_", str(k).strip().lower())
        clean_k = re.sub(r"_+", "_", clean_k).strip("_")
        canonical = _KEY_ALIASES.get(clean_k, clean_k)
        normalized[canonical] = v
    return normalized


def _clean_phone_number(val: Any) -> list[str]:
    """Clean and parse one or more phone numbers from string, int, float, or list."""
    if val is None:
        return []

    raw_items: list[str] = []
    if isinstance(val, (list, tuple)):
        raw_items = [str(x) for x in val]
    elif isinstance(val, float):
        # Handle Excel float formatting like 919876543210.0
        raw_items = [str(int(val))]
    elif isinstance(val, int):
        raw_items = [str(val)]
    else:
        s = str(val).strip()
        # Split on comma, semicolon, pipe, or newline
        parts = re.split(r"[,;|\n]+", s)
        raw_items = [p.strip() for p in parts if p.strip()]

    cleaned: list[str] = []
    for item in raw_items:
        # Strip decimal suffix if present e.g. "919876543210.0"
        if "." in item:
            item = item.split(".")[0]
        digits = "".join(c for c in item if c.isdigit())
        if digits:
            cleaned.append(digits)
    return cleaned


def _parse_template_values(val: Any) -> list[str] | None:
    """Parse dynamic template values (up to 10 parameters)."""
    if not val:
        return None
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    parts = re.split(r"[,|]+", str(val))
    cleaned = [p.strip() for p in parts if p.strip()]
    return cleaned if cleaned else None


def load_sms_from_list(
    rows: list[dict[str, Any]],
    client: str = "bajaj",
) -> list[SmsMessage]:
    """
    Parse a list of raw row dictionaries into validated SmsMessage objects.
    """
    default_sender = get_sms_sender_id(client)
    default_entity_id = get_sms_dlt_entity_id(client)

    messages: list[SmsMessage] = []
    for idx, raw_row in enumerate(rows):
        row = _normalize_sms_row_keys(raw_row)

        dest = _clean_phone_number(row.get("dest"))
        text = str(row.get("text") or "").strip()
        send = str(row.get("send") or default_sender).strip()

        # If dest or text is empty, skip or warn
        if not dest or not text:
            logger.warning("Row %d missing dest or text; skipping: %s", idx, raw_row)
            continue

        msg_type = str(row.get("type") or SmsMessageType.PLAIN).strip()
        entity_id = str(row.get("dlt_entity_id") or default_entity_id).strip() or None
        template_id = str(row.get("dlt_template_id") or "").strip() or None

        cust_ref = str(row.get("cust_ref") or "").strip() or None
        template_values = _parse_template_values(row.get("template_values"))

        tag = str(row.get("tag") or "").strip() or None
        tag1 = str(row.get("tag1") or "").strip() or None
        tag2 = str(row.get("tag2") or "").strip() or None
        tag3 = str(row.get("tag3") or "").strip() or None
        tag4 = str(row.get("tag4") or "").strip() or None
        tag5 = str(row.get("tag5") or "").strip() or None

        msg = SmsMessage(
            dest=dest,
            text=text,
            send=send,
            type=msg_type,
            dlt_entity_id=entity_id,
            dlt_template_id=template_id,
            template_values=template_values,
            cust_ref=cust_ref,
            tag=tag,
            tag1=tag1,
            tag2=tag2,
            tag3=tag3,
            tag4=tag4,
            tag5=tag5,
        )
        messages.append(msg)

    return messages


def load_sms_from_csv(
    csv_path: str | Path,
    client: str = "bajaj",
) -> list[SmsMessage]:
    """Read SMS messages from a CSV file."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"SMS CSV file not found: {csv_path}")

    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))

    return load_sms_from_list(rows, client=client)


def load_sms_from_excel(
    excel_path: str | Path,
    client: str = "bajaj",
) -> list[SmsMessage]:
    """Read SMS messages from an Excel file (.xlsx or .xls)."""
    import openpyxl

    path = Path(excel_path)
    if not path.exists():
        raise FileNotFoundError(f"SMS Excel file not found: {excel_path}")

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    if ws is None:
        return []

    raw_rows = list(ws.iter_rows(values_only=True))
    if not raw_rows:
        return []

    headers = [str(h or "").strip() for h in raw_rows[0]]
    rows: list[dict[str, Any]] = []
    for row_vals in raw_rows[1:]:
        if not any(row_vals):
            continue
        row_dict = {}
        for h, v in zip(headers, row_vals, strict=False):
            if h:
                row_dict[h] = v
        rows.append(row_dict)

    return load_sms_from_list(rows, client=client)


def preview_sms_rows(
    messages: list[SmsMessage],
    client: str = "bajaj",
) -> list[dict[str, Any]]:
    """Generate preview summaries for UI preview and validation."""
    previews: list[dict[str, Any]] = []
    for idx, msg in enumerate(messages):
        preview = {
            "index": idx + 1,
            "dest_count": len(msg.dest),
            "destinations": msg.dest[:5] + (["..."] if len(msg.dest) > 5 else []),
            "sender_id": msg.send,
            "message": msg.text,
            "character_count": len(msg.text),
            "type": msg.type,
            "dlt_entity_id": msg.dlt_entity_id,
            "dlt_template_id": msg.dlt_template_id,
            "cust_ref": msg.cust_ref,
            "client": client,
        }
        previews.append(preview)
    return previews
