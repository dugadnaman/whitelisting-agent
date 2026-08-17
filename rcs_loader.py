"""
Input loader for RCS / DLT templates.

Turns raw rows (CSV, Excel, JSON list, or list of dicts) into validated
RcsTemplateSubmission objects.
"""

import csv
import json
from pathlib import Path

from rcs_config import BAJAJ_ENTITY_ID
from rcs_models import RcsTemplateSubmission

# Valid DLT template types allowed on Karix Lounge
VALID_TEMPLATE_TYPES = {
    "promotional": "Promotional",
    "transactional": "Transactional",
    "service - implicit": "Service - Implicit",
    "service implicit": "Service - Implicit",
    "service-implicit": "Service - Implicit",
    "service - explicit": "Service - Explicit",
    "service explicit": "Service - Explicit",
    "service-explicit": "Service - Explicit",
}

VALID_MESSAGE_TYPES = {
    "text": "Text",
    "unicode": "Unicode",
}


def _normalize_template_type(val: str | None) -> str:
    """Normalize template type to Karix Lounge display format."""
    if not val:
        return "Transactional"
    cleaned = val.strip().lower()
    return VALID_TEMPLATE_TYPES.get(cleaned, val.strip())


def _normalize_message_type(val: str | None) -> str:
    """Normalize template message type to Text or Unicode."""
    if not val:
        return "Text"
    cleaned = val.strip().lower()
    return VALID_MESSAGE_TYPES.get(cleaned, "Text")


def _parse_sender_ids(val: str | list | None) -> list[str]:
    """Parse comma/pipe separated sender IDs or list, enforcing max 5."""
    if not val:
        return []
    if isinstance(val, list):
        items = [str(x).strip() for x in val if str(x).strip()]
    else:
        # Split on comma or pipe
        raw_str = str(val).replace("|", ",")
        items = [x.strip() for x in raw_str.split(",") if x.strip()]

    # Limit to maximum 5 sender IDs as enforced by Karix DLT portal
    return items[:5]


def _clean_template_id(val: str | int | float | None) -> str:
    """Clean DLT template ID, handling scientific notation or float conversions."""
    if val is None:
        return ""
    if isinstance(val, float):
        return f"{int(val)}"
    val_str = str(val).strip()
    if val_str.endswith(".0"):
        val_str = val_str[:-2]
    return val_str


def _row_to_rcs_submission(row: dict) -> RcsTemplateSubmission:
    """Convert a normalized dict to an RcsTemplateSubmission."""
    # Find matching keys regardless of minor casing or naming variations
    normalized_row = {k.strip().lower(): v for k, v in row.items() if k}

    template_name = str(
        normalized_row.get("template_name")
        or normalized_row.get("name")
        or normalized_row.get("template name")
        or ""
    ).strip()

    template_id = _clean_template_id(
        normalized_row.get("template_id")
        or normalized_row.get("dlt_template_id")
        or normalized_row.get("template id")
    )

    template_message = str(
        normalized_row.get("template_message")
        or normalized_row.get("template_content")
        or normalized_row.get("message")
        or normalized_row.get("body")
        or normalized_row.get("template message")
        or ""
    ).strip()

    if not template_name:
        raise ValueError(f"Missing required 'template_name' in row: {row}")
    if not template_id:
        raise ValueError(f"Missing required 'template_id' for template '{template_name}'")
    if not template_message:
        raise ValueError(f"Missing required 'template_message' for template '{template_name}'")

    raw_sender = (
        normalized_row.get("sender_id")
        or normalized_row.get("sender_ids")
        or normalized_row.get("sender id")
        or normalized_row.get("senderid")
    )
    sender_ids = _parse_sender_ids(raw_sender)

    raw_type = (
        normalized_row.get("template_type")
        or normalized_row.get("type")
        or normalized_row.get("template type")
    )
    template_type = _normalize_template_type(raw_type)

    raw_msg_type = (
        normalized_row.get("template_message_type")
        or normalized_row.get("textmsg_type")
        or normalized_row.get("message_type")
        or normalized_row.get("template message type")
    )
    template_message_type = _normalize_message_type(raw_msg_type)

    entity_id = str(
        normalized_row.get("entity_id")
        or normalized_row.get("entity id")
        or normalized_row.get("pe_id")
        or BAJAJ_ENTITY_ID
    ).strip() or BAJAJ_ENTITY_ID

    source_ref = str(
        normalized_row.get("source_ref")
        or template_name
    ).strip()

    return RcsTemplateSubmission(
        template_name=template_name,
        template_id=template_id,
        template_type=template_type,
        sender_ids=sender_ids,
        template_message_type=template_message_type,
        template_message=template_message,
        entity_id=entity_id,
        source_ref=source_ref,
    )


def load_rcs_from_csv(path: str) -> list[RcsTemplateSubmission]:
    """Load RCS DLT templates from a CSV file."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for raw_row in csv.DictReader(f):
            clean_row = {k.strip(): (v.strip() if v else "") for k, v in raw_row.items() if k}
            if not any(clean_row.values()):
                continue
            rows.append(clean_row)

    return [_row_to_rcs_submission(row) for row in rows]


def load_rcs_from_excel(path: str) -> list[RcsTemplateSubmission]:
    """Load RCS DLT templates from an Excel (.xlsx) file."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as e:
        import zipfile
        if zipfile.is_zipfile(path):
            try:
                with zipfile.ZipFile(path, "r") as z:
                    if any("Index/Document.iwa" in name for name in z.namelist()):
                        raise ValueError(
                            f"File '{path}' is saved as an Apple Numbers document (.numbers).\n"
                            "To fix: Open in Apple Numbers and go to: File -> Export To -> Excel..."
                        ) from e
            except zipfile.BadZipFile:
                pass
        raise ValueError(f"Unable to read Excel file '{path}': {e}") from e

    sheet = wb.active
    headers = [str(cell.value or "").strip() for cell in sheet[1]]

    rows = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if not any(row):
            continue  # Skip blank rows

        raw_row = {}
        for h, val in zip(headers, row):
            if h:
                raw_row[h] = str(val).strip() if val is not None else ""

        if not raw_row.get("template_name") and not raw_row.get("Template Name"):
            continue

        rows.append(raw_row)

    return [_row_to_rcs_submission(row) for row in rows]


def load_rcs_from_json(path: str) -> list[RcsTemplateSubmission]:
    """Load RCS DLT templates from a JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [_row_to_rcs_submission(row) for row in data]


def load_rcs_from_list(rows: list[dict]) -> list[RcsTemplateSubmission]:
    """Load from a list of dicts already in memory."""
    return [_row_to_rcs_submission(row) for row in rows]
