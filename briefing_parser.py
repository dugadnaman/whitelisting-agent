"""
Intelligent Campaign Briefing Parser for Jira Tickets.
Extracts multi-channel marketing content (WhatsApp, RCS, SMS, MoEngage)
from:
1. Attached client spreadsheets (.xlsx, .xls, .csv) with channel sheets (WA, RCS, SMS),
   channel grids (LAP Content), or Title/Body blocks (RCS App Downloads).
2. Jira ticket ADF descriptions (tables and pipe-separated lines).
3. Detects email mailer campaigns (.zip + .docx) to inform operators.
Normalizes placeholders ({{1}}, {{2}}), pairs creative attachments, and maps sub-accounts.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import openpyxl
from jira_client import MEDIA_CACHE_DIR, download_jira_attachment

logger = logging.getLogger(__name__)


def clean_safelink(url: str | None) -> str:
    """Unwrap Outlook Safelink tracking URLs to extract the actual destination URL."""
    if not url:
        return ""
    clean = str(url).strip()
    if "safelinks.protection.outlook.com" in clean and "url=" in clean:
        try:
            parsed = urllib.parse.urlparse(clean)
            params = urllib.parse.parse_qs(parsed.query)
            target = params.get("url", [""])[0]
            if target:
                return urllib.parse.unquote(target)
        except Exception:
            pass
    return clean
logger = logging.getLogger(__name__)


@dataclass
class WhatsAppTemplateDraft:
    template_name: str
    category: str
    body: str
    language: str = "en"
    header_type: str = "TEXT"
    header_text: str | None = None
    media_file: str | None = None
    media_filename: str | None = None
    button_type: str = "NONE"
    button_text: str | None = None
    button_url: str | None = None
    footer_text: str | None = None
    variables: list[str] = field(default_factory=list)
    sample_values: list[str] = field(default_factory=list)
    raw_source: str = ""
    source_origin: str = "jira"  # "jira_adf" | "excel_sheet" | "excel_grid"


@dataclass
class RcsTemplateDraft:
    template_name: str
    card_title: str
    body: str
    media_file: str | None = None
    media_filename: str | None = None
    action_type: str = "URL"
    action_label: str = "Check Offer"
    action_url: str = "https://www.tatacapital.com"
    variables: list[str] = field(default_factory=list)
    sample_values: list[str] = field(default_factory=list)
    raw_source: str = ""
    source_origin: str = "jira"


@dataclass
class SmsTemplateDraft:
    template_name: str
    text: str
    char_count: int
    variant: str = "General"
    variables: list[str] = field(default_factory=list)
    sample_values: list[str] = field(default_factory=list)
    raw_source: str = ""
    source_origin: str = "jira"


@dataclass
class ParsedJiraBrief:
    issue_key: str
    summary: str
    account: str  # e.g. "tcl_promo", "tchfl"
    status: str
    assignee: str
    reporter: str
    duedate: str | None
    is_email_campaign: bool = False
    campaign_type_label: str = "Whitelisting & Messaging"
    whatsapp_templates: list[dict[str, Any]] = field(default_factory=list)
    rcs_templates: list[dict[str, Any]] = field(default_factory=list)
    sms_templates: list[dict[str, Any]] = field(default_factory=list)
    moengage_campaign: dict[str, Any] = field(default_factory=dict)
    attachments_mapped: list[dict[str, Any]] = field(default_factory=list)


def infer_sub_account_from_text(text: str, default: str = "tcl_promo") -> str:
    """Infer the correct Tata Capital sub-account from product keywords."""
    t = text.lower()
    if any(k in t for k in ["housing", "home loan", "tchfl", "home_loan"]):
        return "tchfl"
    if any(k in t for k in ["wealth", "securities", "portfolio", "demat"]):
        return "wealth"
    if any(k in t for k in ["moneyfy", "mutual fund", "sip"]):
        return "moneyfy"
    return default


def normalize_placeholders(raw_text: str) -> tuple[str, list[str]]:
    """Convert informal Jira placeholders (<xxx>, <name>, {link}, etc.) to {{1}}, {{2}}."""
    s = raw_text.strip()
    if not s:
        return "", []

    var_counter = 1
    samples: list[str] = []

    def _replace_money(m: re.Match) -> str:
        nonlocal var_counter
        curr = f"{{{{{var_counter}}}}}"
        var_counter += 1
        samples.append("5,00,000")
        return curr

    def _replace_name(m: re.Match) -> str:
        nonlocal var_counter
        curr = f"{{{{{var_counter}}}}}"
        var_counter += 1
        samples.append("Customer")
        return curr

    def _replace_generic(m: re.Match) -> str:
        nonlocal var_counter
        val = m.group(0)
        if any(cta in val.lower() for cta in ["apply", "check", "click", "explore", "link", "now", "here"]):
            return val
        curr = f"{{{{{var_counter}}}}}"
        var_counter += 1
        samples.append("Exclusive")
        return curr

    s = re.sub(r"₹\s*(?:<[^>]+>|\{[^}]+\})", _replace_money, s)
    s = re.sub(r"(?:<x+>|<X+>|\{x+\}|\{X+\})", _replace_money, s)
    s = re.sub(r"(?:<name>|\{name\}|<customer_name>)", _replace_name, s, flags=re.IGNORECASE)
    # Square-bracket placeholders used by SWCM briefs: [Client Name], [Name], [First Name]
    s = re.sub(r"\[(?:client\s+name|customer\s+name|first\s+name|name)\]", _replace_name, s, flags=re.IGNORECASE)
    s = re.sub(r"<[a-zA-Z\-_]+>", _replace_generic, s)

    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"<\s*(?:link|Link)\s*>", "https://www.tatacapital.com", s)
    s = re.sub(r"\{\s*(?:link|Link)\s*\}", "https://www.tatacapital.com", s)
    s = re.sub(r"\[\s*(?:link|Link)\s*\]", "https://www.tatacapital.com", s)

    return s, samples


def _clean_template_name(base: str, channel: str, idx: int) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", base.lower()).strip("_")
    clean = re.sub(r"_+", "_", clean)
    short = clean[:26].strip("_")
    return f"{short}_{channel.lower()}_{idx}"


def _extract_text_from_adf_node(node: dict[str, Any] | None, preserve_formatting: bool = True) -> str:
    if not node or not isinstance(node, dict):
        return ""
    ntype = node.get("type")
    if ntype == "text":
        t = str(node.get("text", ""))
        if not t or not preserve_formatting:
            return t
        marks = node.get("marks") or []
        m_types = {m.get("type") for m in marks if isinstance(m, dict)}
        if "strong" in m_types and t.strip():
            stripped = t.strip()
            t = t.replace(stripped, f"*{stripped}*")
        elif "em" in m_types and t.strip():
            stripped = t.strip()
            t = t.replace(stripped, f"_{stripped}_")
        return t
    if ntype == "hardBreak":
        return "\n"
    if "content" in node and isinstance(node["content"], list):
        sep = "\n" if ntype == "paragraph" else ""
        return "".join(_extract_text_from_adf_node(c, preserve_formatting) for c in node["content"]) + sep
    return ""


def _extract_links_from_adf_node(node: dict[str, Any] | None) -> list[str]:
    """Recursively discover and extract all destination URLs from link marks."""
    links: list[str] = []
    if not node or not isinstance(node, dict):
        return links
    if node.get("type") == "text":
        for m in (node.get("marks") or []):
            if isinstance(m, dict) and m.get("type") == "link":
                href = m.get("attrs", {}).get("href")
                if href and not href.startswith("mailto:"):
                    clean = clean_safelink(href)
                    if clean and clean not in links:
                        links.append(clean)
    for c in node.get("content", []):
        links.extend(_extract_links_from_adf_node(c))
    return links

def _find_adf_tables(node: Any) -> list[dict[str, Any]]:
    tables = []
    if isinstance(node, dict):
        if node.get("type") == "table":
            tables.append(node)
        for c in node.get("content", []):
            tables.extend(_find_adf_tables(c))
    return tables


def _parse_tables_from_adf(adf_doc: dict[str, Any] | None) -> list[dict[str, str]]:
    if not adf_doc:
        return []

    tables = _find_adf_tables(adf_doc)
    extracted_items: list[dict[str, str]] = []

    for tbl in tables:
        rows = tbl.get("content", [])
        if not rows:
            continue

        raw_rows = []
        for r in rows:
            cells = [_extract_text_from_adf_node(c).strip() for c in r.get("content", [])]
            raw_rows.append(cells)

        if not raw_rows:
            continue

        # Skip SWCM key-value campaign tables (handled by _parse_swcm_campaign_tables)
        first_cell_lower = (raw_rows[0][0].strip().lower() if raw_rows and raw_rows[0] else "")
        if "campaign execution format" in first_cell_lower:
            continue

        # Check Pattern B (Row-based channel tags)
        first_row = raw_rows[0]
        first_col_val = first_row[0].strip().upper() if first_row else ""
        is_row_based = first_col_val in ("SMS", "WA", "RCS", "WHATSAPP", "EMAIL") and len(first_row) >= 2

        if is_row_based:
            for r in raw_rows:
                if len(r) >= 2:
                    chan_tag = r[0].strip().upper()
                    body_content = r[1].strip()
                    if body_content and len(body_content) > 10:
                        extracted_items.append({
                            "channel": chan_tag,
                            "text": body_content,
                            "variant": "General",
                            "source": "jira_adf",
                        })
            continue

        # Pattern A (Columnar headers in row 0)
        if len(raw_rows) >= 2:
            header_cells = raw_rows[0]
            for r in raw_rows[1:]:
                for col_idx, cell_val in enumerate(r):
                    if col_idx < len(header_cells):
                        header_name = header_cells[col_idx]
                        if header_name and cell_val and len(cell_val) > 10 and not cell_val.isdigit():
                            header_lower = header_name.lower()
                            if "wa" in header_lower:
                                chan_type = "WA"
                            elif "rcs" in header_lower:
                                chan_type = "RCS"
                            elif "sms" in header_lower:
                                chan_type = "SMS"
                            else:
                                continue

                            variant_label = (
                                "Retargeting"
                                if "retarget" in header_lower
                                else ("Non clicker" if "non" in header_lower else "General")
                            )
                            extracted_items.append({
                                "channel": chan_type,
                                "text": cell_val,
                                "variant": variant_label,
                                "source": "jira_adf",
                            })

    return extracted_items


# ---------------------------------------------------------------------------
# Excel Spreadsheet Extraction Engine
# ---------------------------------------------------------------------------


def _match_sheet_channel(sname: str) -> str | None:
    """
    Match an Excel sheet name to its intended communication channel.
    Handles exact names ('WA', 'SMS', 'RCS') as well as descriptive variations
    ('WhatsApp Content', 'WA Copies', 'RCS Copies', 'SMS_1', 'SMS Content', etc.).
    """
    norm = re.sub(r"[^A-Za-z0-9]", " ", sname).strip().upper()
    words = norm.split()
    if "WHATSAPP" in norm or "WA" in words:
        return "WA"
    if "RCS" in words or "RCS" in norm:
        return "RCS"
    if "SMS" in words or "SMS" in norm:
        return "SMS"
    return None


def _parse_excel_channel_sheets(wb: openpyxl.Workbook) -> list[dict[str, str]]:
    """
    Check if the workbook has dedicated channel sheets (e.g. 'WA', 'WhatsApp Content',
    'SMS Copies', 'RCS_1') and extract marketing templates.
    Supports both columnar tables (e.g. template_name | body | header) and row-based lists.
    """
    items: list[dict[str, str]] = []

    for sname in wb.sheetnames:
        target_chan = _match_sheet_channel(sname)
        if not target_chan:
            continue

        ws = wb[sname]
        raw_rows = []
        for r in range(1, ws.max_row + 1):
            row_vals = [str(ws.cell(row=r, column=c).value or "").strip() for c in range(1, ws.max_column + 1)]
            if any(row_vals):
                raw_rows.append(row_vals)

        if not raw_rows:
            continue

        # 1. Check for columnar template tables where row 0 contains header names
        header_row = [c.lower() for c in raw_rows[0]]
        body_col_idx = None
        for idx, h in enumerate(header_row):
            if "header" in h or "title" in h or "type" in h or "name" in h:
                continue
            if any(k in h for k in ["body", "content", "copy", "message", "text"]):
                body_col_idx = idx
                break

        if body_col_idx is not None and len(raw_rows) > 1:
            header_col_idx = next((i for i, h in enumerate(header_row) if "header" in h and "type" not in h), None)
            footer_col_idx = next((i for i, h in enumerate(header_row) if "footer" in h), None)
            btn_text_col_idx = next((i for i, h in enumerate(header_row) if "button_text" in h or "cta" in h), None)
            btn_url_col_idx = next((i for i, h in enumerate(header_row) if "button_url" in h or "url" in h or "link" in h), None)
            btn_type_col_idx = next((i for i, h in enumerate(header_row) if "button_type" in h), None)

            for r_idx, r in enumerate(raw_rows[1:], start=1):
                if body_col_idx < len(r) and len(r[body_col_idx]) > 10:
                    body_val = r[body_col_idx]
                    item: dict[str, str] = {
                        "channel": target_chan,
                        "text": body_val,
                        "variant": f"Variant {r_idx}" if r_idx > 1 else "General",
                        "source": f"excel_sheet_{sname}",
                    }
                    if header_col_idx is not None and header_col_idx < len(r) and r[header_col_idx]:
                        item["header"] = r[header_col_idx]
                    if footer_col_idx is not None and footer_col_idx < len(r) and r[footer_col_idx]:
                        item["footer"] = r[footer_col_idx]
                    if btn_text_col_idx is not None and btn_text_col_idx < len(r) and r[btn_text_col_idx]:
                        item["button_text"] = r[btn_text_col_idx]
                    if btn_url_col_idx is not None and btn_url_col_idx < len(r) and r[btn_url_col_idx]:
                        item["button_url"] = r[btn_url_col_idx]
                    if btn_type_col_idx is not None and btn_type_col_idx < len(r) and r[btn_type_col_idx]:
                        item["button_type"] = r[btn_type_col_idx]

                    if "Title:" in body_val and "Body:" in body_val:
                        title_m = re.search(r"Title:\s*([^\n]+)", body_val)
                        body_m = re.search(r"Body:?\s*(.*?)(?:CTA:|$)", body_val, re.DOTALL)
                        if title_m:
                            item["title"] = title_m.group(1).strip()
                        if body_m:
                            item["text"] = body_m.group(1).strip()

                    items.append(item)
            continue

        # 2. Row-based format (e.g. PQ UCL.xlsx where column 0 has labels like 'SMS Text', 'Body')
        for r_vals in raw_rows:
            label = r_vals[0].lower() if r_vals else ""
            if any(k in label for k in ["text", "body", "message", "copy", "content"]) or len(r_vals) > 1:
                candidates = r_vals[1:] if any(k in label for k in ["text", "body", "copy", "sms", "name", "cta"]) else r_vals
                for col_idx, cell in enumerate(candidates, start=1):
                    if len(cell) > 25 and not cell.lower().startswith(("http", "as per", "ucl_", "tclmoe_", "clicker")):
                        variant_label = "Retargeting" if col_idx > 1 or "retarget" in cell.lower() else "General"
                        item_dict = {
                            "channel": target_chan,
                            "text": cell,
                            "variant": variant_label,
                            "source": f"excel_sheet_{sname}",
                        }
                        if "Title:" in cell and "Body:" in cell:
                            title_m = re.search(r"Title:\s*([^\n]+)", cell)
                            body_m = re.search(r"Body:?\s*(.*?)(?:CTA:|$)", cell, re.DOTALL)
                            if title_m:
                                item_dict["title"] = title_m.group(1).strip()
                            if body_m:
                                item_dict["text"] = body_m.group(1).strip()
                        items.append(item_dict)

    return items


def _parse_excel_grid_messages(wb: openpyxl.Workbook) -> list[dict[str, str]]:
    """
    Parse Excel sheets where copy spans multiple contiguous rows
    and Column 0 indicates channel sections like 'SMS' and 'RCS'.
    e.g. LAP Content.xlsx in TCN-525.
    Handles paragraph breaks safely without prematurely splitting templates on a single empty row.
    """
    items: list[dict[str, str]] = []

    for sname in wb.sheetnames:
        ws = wb[sname]
        raw_rows = []
        for r in range(1, ws.max_row + 1):
            vals = [str(ws.cell(row=r, column=c).value or "").strip() for c in range(1, ws.max_column + 1)]
            raw_rows.append(vals)

        if not raw_rows or len(raw_rows[0]) < 2:
            continue

        current_channel = None
        num_cols = len(raw_rows[0])
        current_block: dict[int, list[str]] = {c: [] for c in range(1, num_cols)}

        def _flush_block(channel: str | None, cols: int, sheet_name: str) -> None:
            nonlocal current_block
            if not channel:
                current_block = {c: [] for c in range(1, cols)}
                return
            for c_idx in range(1, cols):
                lines = current_block.get(c_idx, [])
                combined = "\n".join([line for line in lines if not line.lower().startswith("t&cs apply")]).strip()
                if len(combined) > 25:
                    variant_label = f"Variant {c_idx}" if c_idx > 1 else "General"
                    items.append({
                        "channel": channel,
                        "text": combined,
                        "variant": variant_label,
                        "source": f"excel_grid_{sheet_name}",
                    })
            current_block = {c: [] for c in range(1, cols)}

        consecutive_empty_rows = 0

        for row in raw_rows:
            first_val = row[0].strip().upper()
            is_channel_header = first_val in ("SMS", "RCS", "WA", "WHATSAPP", "EMAIL", "PN")
            if is_channel_header:
                _flush_block(current_channel, num_cols, sname)
                current_channel = "WA" if first_val in ("WA", "WHATSAPP") else first_val
                consecutive_empty_rows = 0

            has_text = any(len(row[c]) > 0 for c in range(1, num_cols))
            is_empty_row = not has_text or all(row[c] == "" for c in range(1, num_cols))

            if is_empty_row:
                consecutive_empty_rows += 1
                # A single empty row is paragraph spacing within the message body.
                # Only flush when 2+ consecutive empty rows signal the end of a section.
                if consecutive_empty_rows >= 2:
                    _flush_block(current_channel, num_cols, sname)
                    current_channel = None
                else:
                    # Preserve paragraph separation
                    for c in range(1, num_cols):
                        if current_block[c]:
                            current_block[c].append("")
            else:
                consecutive_empty_rows = 0
                for c in range(1, num_cols):
                    cell_text = row[c].strip()
                    if cell_text and not cell_text.lower().startswith(("group", "channel")):
                        current_block[c].append(cell_text)

        _flush_block(current_channel, num_cols, sname)

    return items


def _parse_excel_key_value_blocks(wb: openpyxl.Workbook) -> list[dict[str, str]]:
    """
    Parse Excel sheets with Title: and Body: message blocks.
    e.g. RCS App Downloads.xlsx in TCN-526.
    """
    items: list[dict[str, str]] = []

    for sname in wb.sheetnames:
        ws = wb[sname]
        for r in range(1, ws.max_row + 1):
            for c in range(1, ws.max_column + 1):
                val = str(ws.cell(row=r, column=c).value or "").strip()
                if "Title:" in val and "Body:" in val:
                    title_m = re.search(r"Title:\s*([^\n]+)", val)
                    body_m = re.search(r"Body:?\s*(.*?)(?:CTA:|$)", val, re.DOTALL)
                    title = title_m.group(1).strip() if title_m else "Tata Capital Offer"
                    body = body_m.group(1).strip() if body_m else val
                    items.append({
                        "channel": "RCS",
                        "text": body,
                        "title": title,
                        "variant": "App Downloads",
                        "source": f"excel_block_{sname}",
                    })

    return items


def extract_templates_from_excel_file(filepath: Path) -> list[dict[str, str]]:
    """Inspect and extract template items from any client Excel file."""
    try:
        wb = openpyxl.load_workbook(filepath, data_only=True)
    except Exception as exc:
        logger.warning("Could not load Excel file %s: %s", filepath, exc)
        return []

    # 1. Try dedicated channel sheets (WA, SMS, RCS)
    sheet_items = _parse_excel_channel_sheets(wb)
    if sheet_items:
        return sheet_items

    # 2. Try Title/Body block structure
    block_items = _parse_excel_key_value_blocks(wb)
    if block_items:
        return block_items

    # 3. Try multi-row grid format
    grid_items = _parse_excel_grid_messages(wb)
    if grid_items:
        return grid_items

    return []


def _extract_images_from_zip(zip_path: Path) -> list[str]:
    """Extract top-level image creatives from a ZIP attachment. Returns local paths.

    Nested ZIPs are emailer packages (HTML + banner/whatsapp icon assets) and are
    intentionally skipped — WhatsApp template creatives live at the ZIP's top level.
    """
    import zipfile

    image_exts = (".jpg", ".jpeg", ".png", ".webp")
    images: list[str] = []
    try:
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                lower = name.lower()
                base = Path(name).name
                if lower.endswith(image_exts) and "/" not in name:
                    out_path = MEDIA_CACHE_DIR / f"jira_{zip_path.stem}_{base}"
                    out_path.write_bytes(z.read(name))
                    images.append(str(out_path))
    except Exception as exc:
        logger.warning("Could not extract ZIP %s: %s", zip_path, exc)
    return images


def _parse_swcm_campaign_tables(adf_doc: dict[str, Any] | None) -> list[dict[str, Any]]:
    """
    Parse SWCM 'Campaign execution format N | WA N' key-value tables into WhatsApp campaigns.
    Preserves bold markdown (*bold*), variable placeholders, and extracts real destination URLs
    from hyperlinked CTA text.
    """
    if not adf_doc:
        return []

    tables = _find_adf_tables(adf_doc)
    campaigns: list[dict[str, Any]] = []

    for tbl in tables:
        rows = tbl.get("content", [])
        if not rows:
            continue

        header = [_extract_text_from_adf_node(c, preserve_formatting=False).strip() for c in rows[0].get("content", [])]
        if len(header) < 2:
            continue
        if "campaign execution format" not in header[0].lower():
            continue
        if not header[1].strip().upper().startswith("WA"):
            continue

        fields: dict[str, dict[str, Any]] = {}
        for r in rows[1:]:
            cells = r.get("content", [])
            if len(cells) >= 2:
                raw_label = _extract_text_from_adf_node(cells[0], preserve_formatting=False).strip().replace("*", "")
                val_text = _extract_text_from_adf_node(cells[1], preserve_formatting=True).strip()
                val_links = _extract_links_from_adf_node(cells[1])
                fields[raw_label] = {"text": val_text, "links": val_links}

        wa_content = fields.get("WA Content", {}).get("text", "")
        if wa_content:
            cta_info = fields.get("CTA / LINK", {})
            campaigns.append({
                "wa_label": header[1].strip(),
                "campaign_name": fields.get("Campaign Name", {}).get("text", ""),
                "body": wa_content,
                "cta_text": cta_info.get("text", ""),
                "cta_links": cta_info.get("links", []),
                "schedule": fields.get("Date & Time of execution", {}).get("text", ""),
            })

    return campaigns


def _parse_swcm_cta(cta_raw: str, cta_links: list[str] | None = None) -> tuple[str, str]:
    """
    Parse CTA label and real destination URL from cell text and extracted hyperlink marks.
    Example: 'CTA: Explore Now!\\nGodrej Majesty-NCR' -> ('Explore Now!', 'https://forms.cloud.microsoft/...')
    """
    button_text = "Explore Now"
    button_url = "https://www.tatacapital.com"

    # 1. Use real decoded destination URL if hyperlink mark exists
    if cta_links and len(cta_links) > 0:
        valid_links = [l for l in cta_links if l.startswith("http")]
        if valid_links:
            button_url = valid_links[0]

    # 2. Extract button text from CTA label
    lines = [l.strip() for l in cta_raw.split("\n") if l.strip()]
    for line in lines:
        if line.lower().startswith("cta:") and ":" in line:
            candidate = line.split(":", 1)[1].strip()
            if candidate:
                button_text = candidate
                break

    # If no hyperlink mark was attached, fallback to URL in text if any
    if not cta_links:
        for line in lines:
            if line.startswith("http://") or line.startswith("https://"):
                button_url = line
                break

    return button_text, button_url

_LOCATION_KEYWORDS = {
    "noida": "noida",
    "greater": "noida",
    "whitefield": "whitefield",
    "bengaluru": "whitefield",
    "bangalore": "whitefield",
    "orbis": "orbis",
    "ghansoli": "orbis",
    "hiranandani": "hiranandani",
    "sands": "hiranandani",
    "alibaug": "hiranandani",
}


def _match_creative_to_campaign(campaign_name: str, images: list[str]) -> str | None:
    """Match a WhatsApp campaign to its creative image by location keyword in filename.

    Prefers filenames containing 'whatsapp'/'whatsap' (the actual WhatsApp creatives),
    falling back to generic images (e.g. emailer banner1.png inside nested ZIPs) only
    when no WhatsApp-named creative matches.
    """
    cname_lower = campaign_name.lower()
    target_keywords = {
        v for k, v in _LOCATION_KEYWORDS.items() if k in cname_lower
    }
    if not target_keywords:
        return None

    wa_named = [
        i for i in images
        if "whatsapp" in Path(i).name.lower() or "whatsap" in Path(i).name.lower()
    ]
    other = [i for i in images if i not in wa_named]

    for img in wa_named + other:
        img_lower = Path(img).name.lower()
        if any(kw in img_lower for kw in target_keywords):
            return img
    return None


def parse_jira_brief(issue_data: dict[str, Any], download_creatives: bool = True) -> ParsedJiraBrief:
    """
    Parse a complete Jira ticket dictionary:
    - Extracts from Excel attachments if present (.xlsx, .csv).
    - Falls back to Jira ADF tables / text.
    - Classifies email mailers (.zip + .docx).
    """
    key = str(issue_data.get("key", "TCN_001"))
    summary = str(issue_data.get("summary", ""))
    desc_text = str(issue_data.get("description_text", ""))
    desc_raw = issue_data.get("description_raw")
    sub_account = infer_sub_account_from_text(summary + " " + desc_text)

    # Detect Email Mailer tickets (e.g. TCN-528 TCL Mailers Sept)
    raw_attachments = issue_data.get("attachments", [])
    has_mailers_zip = any("mailer" in a.get("filename", "").lower() and a.get("filename", "").endswith(".zip") for a in raw_attachments)
    has_subject_lines = any("subject" in a.get("filename", "").lower() or a.get("filename", "").endswith((".docx", ".doc")) for a in raw_attachments)
    is_email_campaign = ("mailer" in summary.lower() or "mailers" in summary.lower() or has_mailers_zip) and (has_mailers_zip or has_subject_lines)

    # 1. Download and categorize attachments
    mapped_attachments: list[dict[str, Any]] = []
    excel_attachment_paths: list[Path] = []
    zip_creative_paths: list[str] = []

    for att in raw_attachments:
        fn = att.get("filename", "")
        att_id = att.get("id")
        mime = att.get("mimeType", "")
        local_path: str | None = None
        if download_creatives and att_id:
            try:
                p = download_jira_attachment(att_id, fn)
                local_path = str(p)
                if fn.lower().endswith((".xlsx", ".xls", ".csv")):
                    excel_attachment_paths.append(p)
                elif fn.lower().endswith(".zip"):
                    zip_creative_paths.extend(_extract_images_from_zip(p))
            except Exception as e:
                logger.warning("Could not download attachment %s for %s: %s", att_id, key, e)

        fn_upper = fn.upper()
        target_chan = "GENERAL"
        if "WA" in fn_upper or "WHATSAPP" in fn_upper:
            target_chan = "WHATSAPP"
        elif "RCS" in fn_upper:
            target_chan = "RCS"
        elif "SMS" in fn_upper:
            target_chan = "SMS"
        elif fn_upper.endswith((".XLSX", ".XLS", ".CSV")):
            target_chan = "SPREADSHEET_BRIEF"
        elif fn_upper.endswith((".ZIP", ".DOCX")):
            target_chan = "EMAIL_CREATIVE"

        mapped_attachments.append({
            "id": att_id,
            "filename": fn,
            "local_path": local_path,
            "mime": mime,
            "target_channel": target_chan,
        })

    wa_creatives = [a for a in mapped_attachments if a["target_channel"] == "WHATSAPP" and a.get("local_path")]
    if not wa_creatives:
        wa_creatives = [a for a in mapped_attachments if "image" in a.get("mime", "") and a.get("local_path")]

    rcs_creatives = [a for a in mapped_attachments if a["target_channel"] == "RCS" and a.get("local_path")] or wa_creatives

    wa_drafts: list[WhatsAppTemplateDraft] = []
    rcs_drafts: list[RcsTemplateDraft] = []
    sms_drafts: list[SmsTemplateDraft] = []

    base_name = f"{key.lower().replace('-', '_')}_{re.sub(r'[^a-z0-9]', '_', summary.lower())[:16]}".strip("_")

    # 2. Extract templates from attached Excel files first
    extracted_items: list[dict[str, str]] = []
    for excel_path in excel_attachment_paths:
        items = extract_templates_from_excel_file(excel_path)
        if items:
            extracted_items.extend(items)

    # 3. If no templates found in Excel, parse ADF tables / description text
    if not extracted_items:
        extracted_items = _parse_tables_from_adf(desc_raw)

    if not extracted_items:
        # Pipe blocks fallback (e.g. SMS | ... or WA | ...)
        pipe_blocks = re.findall(r"^(SMS|WA|RCS)\s*\|\s*(.+)$", desc_text, re.IGNORECASE | re.MULTILINE)
        for chan_tag, text_val in pipe_blocks:
            extracted_items.append({
                "channel": chan_tag.upper(),
                "text": text_val.strip(),
                "variant": "General",
                "source": "jira_pipe",
            })


    # 3b. SWCM WhatsApp campaign tables ("Campaign execution format N | WA N")
    swcm_campaigns = _parse_swcm_campaign_tables(desc_raw)
    for idx, campaign in enumerate(swcm_campaigns, start=1):
        norm_text, samples = normalize_placeholders(campaign["body"])
        var_tags = re.findall(r"\{\{(\d+)\}\}", norm_text)
        cta_text, cta_url = _parse_swcm_cta(campaign.get("cta_text", ""), campaign.get("cta_links", []))
        media = _match_creative_to_campaign(campaign["campaign_name"], zip_creative_paths)
        if media is None and zip_creative_paths:
            media = zip_creative_paths[(idx - 1) % len(zip_creative_paths)]
        tname = _clean_template_name(base_name, "wa", idx)
        wa_drafts.append(
            WhatsAppTemplateDraft(
                template_name=tname,
                category="MARKETING",
                body=norm_text,
                header_type="IMAGE" if media else "TEXT",
                media_file=media,
                media_filename=Path(media).name if media else None,
                button_type="URL",
                button_text=cta_text,
                button_url=cta_url,
                variables=var_tags,
                sample_values=samples,
                raw_source=campaign["body"],
                source_origin=f"swcm_{campaign['wa_label'].replace(' ', '_').lower()}",
            )
        )

    # 3c. TypeSafe AI Semantic Extraction fallback for free-form Jira descriptions
    if not extracted_items and not swcm_campaigns and desc_text.strip():
        try:
            from jira_extractor import extract_template_from_jira_text

            semantic_res = extract_template_from_jira_text(desc_text, summary=summary, allow_ai=True)
            t_comp = semantic_res.template
            if t_comp.body_text:
                chan_decision = semantic_res.routing.target_channel
                channels_to_emit = (
                    ["WA", "RCS", "SMS"]
                    if chan_decision == "MULTI_CHANNEL"
                    else (["WA"] if chan_decision == "WHATSAPP" else [chan_decision])
                )
                for c_tag in channels_to_emit:
                    extracted_items.append({
                        "channel": c_tag,
                        "text": t_comp.body_text,
                        "header": t_comp.header_text,
                        "footer": t_comp.footer_text,
                        "button_text": t_comp.button_text,
                        "button_url": t_comp.button_url,
                        "button_type": t_comp.button_type,
                        "variant": semantic_res.routing.campaign_purpose,
                        "source": "jira_typesafe_extractor",
                        "variables": semantic_res.variables,
                        "sample_values": semantic_res.sample_values,
                    })
        except Exception as ex:
            logger.warning("TypeSafe semantic Jira extraction skipped: %s", ex)

    # 4. Assemble template drafts
    wa_counter = 1
    rcs_counter = 1
    sms_counter = 1

    for item in extracted_items:
        chan = item["channel"].upper()
        clean_content = item["text"]
        variant = item.get("variant", "General")
        title = item.get("title") or summary[:32]
        source_origin = item.get("source", "jira")
        norm_text, norm_samples = normalize_placeholders(clean_content)
        var_tags = re.findall(r"\{\{(\d+)\}\}", norm_text)
        resolved_vars = item.get("variables") or var_tags
        resolved_samples = item.get("sample_values") or norm_samples

        if chan in ("WA", "WHATSAPP"):
            img = wa_creatives[(wa_counter - 1) % len(wa_creatives)] if wa_creatives else None
            tname = _clean_template_name(base_name, "wa", wa_counter)
            wa_drafts.append(
                WhatsAppTemplateDraft(
                    template_name=tname,
                    category="MARKETING",
                    body=norm_text,
                    header_type="IMAGE" if img else ("TEXT" if item.get("header") else "TEXT"),
                    header_text=item.get("header"),
                    footer_text=item.get("footer"),
                    media_file=img.get("local_path") if img else None,
                    media_filename=img.get("filename") if img else None,
                    button_type=item.get("button_type") or ("URL" if item.get("button_url") else "URL"),
                    button_text=item.get("button_text") or "Check Offer",
                    button_url=item.get("button_url") or "https://www.tatacapital.com",
                    variables=resolved_vars,
                    sample_values=resolved_samples,
                    raw_source=clean_content,
                    source_origin=source_origin,
                )
            )
            wa_counter += 1

        elif chan == "RCS":
            img = rcs_creatives[(rcs_counter - 1) % len(rcs_creatives)] if rcs_creatives else None
            tname = _clean_template_name(base_name, "rcs", rcs_counter)
            rcs_drafts.append(
                RcsTemplateDraft(
                    template_name=tname,
                    card_title=title,
                    body=norm_text,
                    media_file=img.get("local_path") if img else None,
                    media_filename=img.get("filename") if img else None,
                    action_type=item.get("button_type") or "URL",
                    action_label=item.get("button_text") or "Explore Now",
                    action_url=item.get("button_url") or "https://www.tatacapital.com",
                    variables=item.get("variables") or variables,
                    sample_values=item.get("sample_values") or [],
                    raw_source=clean_content,
                    source_origin=source_origin,
                )
            )
            rcs_counter += 1

        elif chan == "SMS":
            tname = _clean_template_name(base_name, "sms", sms_counter)
            sms_drafts.append(
                SmsTemplateDraft(
                    template_name=tname,
                    text=norm_text,
                    char_count=len(norm_text),
                    variant=variant,
                    variables=variables,
                    raw_source=clean_content,
                    source_origin=source_origin,
                )
            )
            sms_counter += 1

    # 5. Build MoEngage Campaign Staging payload
    moengage_campaign = {
        "campaign_name": f"{key} - {summary}",
        "target_account": sub_account,
        "scheduled_date": issue_data.get("duedate"),
        "whatsapp_template": wa_drafts[0].template_name if wa_drafts else None,
        "sms_content": sms_drafts[0].text if sms_drafts else None,
        "push_title": f"Tata Capital: {summary[:30]}",
        "push_body": (sms_drafts[0].text if sms_drafts else (wa_drafts[0].body if wa_drafts else summary))[:120],
        "status": "DRAFT",
    }

    campaign_type_label = (
        "Email Mailer Campaign" if is_email_campaign else "Multi-Channel Whitelisting Brief"
    )

    return ParsedJiraBrief(
        issue_key=key,
        summary=summary,
        account=sub_account,
        status=str(issue_data.get("status", "To Do")),
        assignee=str(issue_data.get("assignee", "Unassigned")),
        reporter=str(issue_data.get("reporter", "Anonymous")),
        duedate=issue_data.get("duedate"),
        is_email_campaign=is_email_campaign,
        campaign_type_label=campaign_type_label,
        whatsapp_templates=[asdict(w) for w in wa_drafts],
        rcs_templates=[asdict(r) for r in rcs_drafts],
        sms_templates=[asdict(s) for s in sms_drafts],
        moengage_campaign=moengage_campaign,
        attachments_mapped=mapped_attachments,
    )
