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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import openpyxl
from jira_client import download_jira_attachment

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
    variables: list[str] = field(default_factory=list)
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
    raw_source: str = ""
    source_origin: str = "jira"


@dataclass
class SmsTemplateDraft:
    template_name: str
    text: str
    char_count: int
    variant: str = "General"
    variables: list[str] = field(default_factory=list)
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


def _extract_text_from_adf_node(node: dict[str, Any] | None) -> str:
    if not node or not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return node.get("text", "")
    if node.get("type") == "hardBreak":
        return "\n"
    if "content" in node and isinstance(node["content"], list):
        sep = "\n" if node.get("type") == "paragraph" else ""
        return "".join(_extract_text_from_adf_node(c) for c in node["content"]) + sep
    return ""


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


def _parse_excel_channel_sheets(wb: openpyxl.Workbook) -> list[dict[str, str]]:
    """
    Check if the workbook has dedicated channel sheets: 'WA', 'SMS', 'RCS', 'PN'.
    e.g. PQ UCL.xlsx in TCN-527.
    """
    items: list[dict[str, str]] = []
    sheet_map = {
        "WA": "WA",
        "WHATSAPP": "WA",
        "SMS": "SMS",
        "RCS": "RCS",
    }

    for sname in wb.sheetnames:
        norm_sname = sname.strip().upper()
        target_chan = sheet_map.get(norm_sname)
        if not target_chan:
            continue

        ws = wb[sname]
        # Look for rows containing copy
        for r in range(1, ws.max_row + 1):
            row_vals = [str(ws.cell(row=r, column=c).value or "").strip() for c in range(1, ws.max_column + 1)]
            label = row_vals[0].lower() if row_vals else ""

            # Check if this row has message copy (e.g. labeled "SMS Text" or "Body" or long content)
            if any(k in label for k in ["text", "body", "message", "copy", "content"]) or len(row_vals) > 1:
                candidates = row_vals[1:] if any(k in label for k in ["text", "body", "copy", "sms", "name", "cta"]) else row_vals
                for col_idx, cell in enumerate(candidates, start=1):
                    if len(cell) > 25 and not cell.lower().startswith(("http", "as per", "ucl_", "tclmoe_", "clicker")):
                        variant_label = "Retargeting" if col_idx > 1 or "retarget" in cell.lower() else "General"
                        items.append({
                            "channel": target_chan,
                            "text": cell,
                            "variant": variant_label,
                            "source": f"excel_sheet_{sname}",
                        })

    return items


def _parse_excel_grid_messages(wb: openpyxl.Workbook) -> list[dict[str, str]]:
    """
    Parse Excel sheets where copy spans multiple contiguous rows
    and Column 0 indicates channel sections like 'SMS' and 'RCS'.
    e.g. LAP Content.xlsx in TCN-525.
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
                combined = "\n".join([line for line in lines if line and not line.lower().startswith("t&cs apply")])
                if len(combined) > 25:
                    variant_label = f"Variant {c_idx}" if c_idx > 1 else "General"
                    items.append({
                        "channel": channel,
                        "text": combined,
                        "variant": variant_label,
                        "source": f"excel_grid_{sheet_name}",
                    })
            current_block = {c: [] for c in range(1, cols)}

        for row in raw_rows:
            first_val = row[0].strip().upper()
            if first_val in ("SMS", "RCS", "WA", "WHATSAPP"):
                _flush_block(current_channel, num_cols, sname)
                current_channel = "WA" if first_val in ("WA", "WHATSAPP") else first_val

            has_text = any(len(row[c]) > 0 for c in range(1, num_cols))
            is_empty_row = not has_text or all(row[c] == "" for c in range(1, num_cols))

            if is_empty_row:
                _flush_block(current_channel, num_cols, sname)
            else:
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
        norm_text, variables = normalize_placeholders(clean_content)

        if chan in ("WA", "WHATSAPP"):
            img = wa_creatives[(wa_counter - 1) % len(wa_creatives)] if wa_creatives else None
            tname = _clean_template_name(base_name, "wa", wa_counter)
            wa_drafts.append(
                WhatsAppTemplateDraft(
                    template_name=tname,
                    category="MARKETING",
                    body=norm_text,
                    header_type="IMAGE" if img else "TEXT",
                    media_file=img.get("local_path") if img else None,
                    media_filename=img.get("filename") if img else None,
                    button_type="URL",
                    button_text="Check Offer",
                    button_url="https://www.tatacapital.com",
                    variables=variables,
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
                    action_type="URL",
                    action_label="Explore Now",
                    action_url="https://www.tatacapital.com",
                    variables=variables,
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
