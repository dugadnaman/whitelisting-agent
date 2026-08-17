"""
Input loader: turns raw rows (CSV, JSON list, or a list of dicts you already
have in memory) into validated TemplateSubmission objects.

This layer doesn't change when the real Karix API shows up tomorrow — only
submission_client.py does.
"""
import csv
import json
import re
from pathlib import Path

from models import TemplateComponent, TemplateSubmission


def _row_to_submission(row: dict) -> TemplateSubmission:
    # TemplateComponent only knows about type/text/variables/buttons.
    # Complex components (HEADER with format/example, BUTTONS with
    # buttons_type/buttons_attributes) have extra keys.  Keep those as
    # raw dicts — submission_client._build_create_body handles both.
    _TC_FIELDS = {"type", "text", "variables", "buttons"}

    components = []
    for c in row["components"]:
        if isinstance(c, dict):
            if c.keys() <= _TC_FIELDS:
                # Simple component — fits the dataclass
                components.append(TemplateComponent(**c))
            else:
                # Complex component — pass through as raw dict
                components.append(c)
        else:
            components.append(c)

    return TemplateSubmission(
        client=row.get("client", "bajaj"),
        channel=row.get("channel", "whatsapp"),
        template_name=row["template_name"],
        language=row["language"],
        category=row["category"],
        waba_id=row["waba_id"],
        components=components,
        source_ref=row.get("source_ref", row["template_name"]),
    )


def load_from_json(path: str) -> list[TemplateSubmission]:
    """Load a JSON file containing a list of template objects."""
    data = json.loads(Path(path).read_text())
    return [_row_to_submission(row) for row in data]


def _flat_row_to_components(raw_row: dict) -> list[dict]:
    """Convert flat CSV columns into the Karix components array."""
    components = []

    # 1. HEADER
    htype = (raw_row.get("header_type") or "").strip().upper()
    if htype == "IMAGE":
        comp = {"type": "HEADER", "format": "IMAGE"}
        if raw_row.get("header_media_url"):
            comp["media_url"] = raw_row["header_media_url"].strip()
        elif raw_row.get("header_media_file"):
            comp["media_file"] = raw_row["header_media_file"].strip()
        components.append(comp)
    elif htype in ("TEXT", "HEADER") and raw_row.get("header_text"):
        components.append({
            "type": "HEADER",
            "format": "TEXT",
            "text": raw_row["header_text"].strip()
        })

    # 2. BODY
    body_text = (raw_row.get("body") or raw_row.get("body_text") or "").strip()
    if body_text:
        # Normalize non-standard tags like <name>, {#var#}, [name] to {{1}}, {{2}}
        body_text = re.sub(r'([A-Za-z0-9])(<[^>]+>)', r'\1 \2', body_text)
        body_text = re.sub(r'(<[^>]+>)([A-Za-z0-9])', r'\1 \2', body_text)
        body_text = re.sub(r'([A-Za-z0-9])(\{#[^#]+#\})', r'\1 \2', body_text)
        placeholders = []
        def _repl(m):
            idx = len(placeholders) + 1
            placeholders.append(m.group(0))
            return f"{{{{{idx}}}}}"
        pattern = r'(\{\{\d+\}\}|\{\{[a-zA-Z0-9_]+\}\}|<[^>]+>|\{#[^#]+#\}|\[[a-zA-Z0-9_]+\]|\{[a-zA-Z0-9_]+\})'
        body_text = re.sub(pattern, _repl, body_text)
        components.append({"type": "BODY", "text": body_text})
    # 3. FOOTER
    footer_text = (raw_row.get("footer") or raw_row.get("footer_text") or "").strip()
    if footer_text:
        components.append({"type": "FOOTER", "text": footer_text})

    # 4. BUTTONS
    btype = (raw_row.get("button_type") or "").strip().upper()
    btext = (raw_row.get("button_text") or "").strip()
    burl = (raw_row.get("button_url") or "").strip()
    bexample = (raw_row.get("button_url_example") or "").strip() or "https://www.bajajfinservmarkets.in/"

    if btype == "URL" and btext and burl:
        components.append({
            "type": "BUTTONS",
            "buttons": [{
                "type": "URL",
                "text": btext,
                "url": burl,
                "example": [bexample]
            }]
        })
    elif btype in ("QUICK_REPLY", "QUICKREPLY") and btext:
        # Allows pipe-separated quick replies: e.g. "Yes | No"
        btn_items = [
            {"type": "QUICK_REPLY", "text": item.strip()}
            for item in btext.split("|") if item.strip()
        ]
        if btn_items:
            components.append({
                "type": "BUTTONS",
                "buttons": btn_items
            })

    return components


def load_from_csv(path: str, client: str = "bajaj") -> list[TemplateSubmission]:
    """
    Load templates from a CSV file for the specified client.
    """
    from config import get_waba_id

    default_waba = get_waba_id(client) if client.lower() == "bajaj" else (get_waba_id(client) or "")
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for raw_row in csv.DictReader(f):
            clean_row = {k.strip(): (v.strip() if v else "") for k, v in raw_row.items() if k}

            if clean_row.get("components"):
                try:
                    clean_row["components"] = json.loads(clean_row["components"])
                except json.JSONDecodeError:
                    clean_row["components"] = _flat_row_to_components(clean_row)
            else:
                clean_row["components"] = _flat_row_to_components(clean_row)

            clean_row["client"] = clean_row.get("client") or client
            if not clean_row.get("waba_id"):
                clean_row["waba_id"] = default_waba
            if not clean_row.get("language"):
                clean_row["language"] = "en"
            if not clean_row.get("category"):
                clean_row["category"] = "MARKETING"

            rows.append(clean_row)

    return [_row_to_submission(row) for row in rows]

def load_from_excel(path: str, client: str = "bajaj") -> list[TemplateSubmission]:
    """
    Load templates directly from an Excel (.xlsx) file for the specified client.
    """
    import openpyxl
    from config import get_waba_id

    default_waba = get_waba_id(client) if client.lower() == "bajaj" else (get_waba_id(client) or "")
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

        if not raw_row.get("template_name"):
            continue

        if raw_row.get("components"):
            try:
                raw_row["components"] = json.loads(raw_row["components"])
            except json.JSONDecodeError:
                raw_row["components"] = _flat_row_to_components(raw_row)
        else:
            raw_row["components"] = _flat_row_to_components(raw_row)

        raw_row["client"] = raw_row.get("client") or client
        if not raw_row.get("waba_id"):
            raw_row["waba_id"] = default_waba
        if not raw_row.get("language"):
            raw_row["language"] = "en"
        if not raw_row.get("category"):
            raw_row["category"] = "MARKETING"

        rows.append(raw_row)

    return [_row_to_submission(row) for row in rows]

def load_from_list(rows: list[dict]) -> list[TemplateSubmission]:
    """Load from a list of dicts already in memory (e.g. from a mock)."""
    return [_row_to_submission(row) for row in rows]
