"""
Intelligent Campaign Briefing Parser for Jira Tickets.
Extracts multi-channel marketing content (WhatsApp, RCS, SMS, MoEngage)
from Jira issue descriptions and ADF tables, normalizes variables ({{1}}, {{2}}),
pairs creative image attachments, and maps sub-accounts.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

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


@dataclass
class SmsTemplateDraft:
    template_name: str
    text: str
    char_count: int
    variant: str = "General"  # e.g. "Non clicker", "Retargeting"
    variables: list[str] = field(default_factory=list)
    raw_source: str = ""


@dataclass
class ParsedJiraBrief:
    issue_key: str
    summary: str
    account: str  # e.g. "tcl_promo", "tchfl"
    status: str
    assignee: str
    reporter: str
    duedate: str | None
    whatsapp_templates: list[dict[str, Any]] = field(default_factory=list)
    rcs_templates: list[dict[str, Any]] = field(default_factory=list)
    sms_templates: list[dict[str, Any]] = field(default_factory=list)
    moengage_campaign: dict[str, Any] = field(default_factory=dict)
    attachments_mapped: list[dict[str, Any]] = field(default_factory=list)


def infer_sub_account_from_text(text: str, default: str = "tcl_promo") -> str:
    """Infer the correct Tata Capital sub-account from product keywords in summary/copy."""
    t = text.lower()
    if any(k in t for k in ["housing", "home loan", "tchfl", "home_loan"]):
        return "tchfl"
    if any(k in t for k in ["wealth", "securities", "portfolio", "demat"]):
        return "wealth"
    if any(k in t for k in ["moneyfy", "mutual fund", "sip"]):
        return "moneyfy"
    return default


def normalize_placeholders(raw_text: str) -> tuple[str, list[str]]:
    """
    Convert informal Jira placeholders (<xxx>, <name>, {link}, etc.)
    into sequential Meta/Karix standard variables ({{1}}, {{2}}, ...).
    Returns (normalized_text, sample_variables_list).
    """
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
        # Avoid replacing CTA button markers
        if any(cta in val.lower() for cta in ["apply", "check", "click", "explore", "link", "now"]):
            return val
        curr = f"{{{{{var_counter}}}}}"
        var_counter += 1
        samples.append("Exclusive")
        return curr

    # 1. Money/amount placeholders
    s = re.sub(r"₹\s*(?:<[^>]+>|\{[^}]+\})", _replace_money, s)
    s = re.sub(r"(?:<x+>|<X+>|\{x+\}|\{X+\})", _replace_money, s)
    # 2. Name placeholders
    s = re.sub(r"(?:<name>|\{name\}|<customer_name>)", _replace_name, s, flags=re.IGNORECASE)
    # 3. Other bracketed parameters
    s = re.sub(r"<[a-zA-Z\-_]+>", _replace_generic, s)

    # Clean double spaces
    s = re.sub(r"[ \t]+", " ", s)
    # Normalize link markers
    s = re.sub(r"<\s*(?:link|Link)\s*>", "https://www.tatacapital.com", s)
    s = re.sub(r"\{\s*(?:link|Link)\s*\}", "https://www.tatacapital.com", s)

    return s, samples


def _clean_template_name(base: str, channel: str, idx: int) -> str:
    """Generate a clean snake_case template name acceptable by Meta / Karix."""
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", base.lower()).strip("_")
    clean = re.sub(r"_+", "_", clean)
    short = clean[:28].strip("_")
    return f"{short}_{channel.lower()}_{idx}"


def _extract_text_from_adf_node(node: dict[str, Any] | None) -> str:
    """Extract plain text from an ADF node preserving linebreaks."""
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
    """Recursively discover all ADF table nodes."""
    tables = []
    if isinstance(node, dict):
        if node.get("type") == "table":
            tables.append(node)
        for c in node.get("content", []):
            tables.extend(_find_adf_tables(c))
    return tables


def _parse_tables_from_adf(adf_doc: dict[str, Any] | None) -> list[dict[str, str]]:
    """
    Parse ADF table structures supporting both:
    - Pattern A (Columnar): Headers in row 0, content in subsequent rows across columns
    - Pattern B (Row-based): Channel tag in col 0 (e.g. 'SMS', 'WA'), message body in col 1
    Returns a unified list of {'channel': 'WA'|'SMS'|'RCS', 'text': '...', 'variant': '...'}
    """
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

        # Check if this table is Pattern B: Row 0 Col 0 is a known channel name
        # e.g. Row 0: ['SMS', 'Hi <name>...'], Row 1: ['WA', 'Hi <name>...']
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
                        })
            continue

        # Otherwise, Pattern A (Columnar headers in row 0)
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
                            })

    return extracted_items


def _split_pipe_channel_blocks(description: str) -> list[tuple[str, str]]:
    """Extract blocks formatted as 'SMS | Text...' or 'WA | Text...'."""
    results: list[tuple[str, str]] = []
    pattern = re.compile(r"^(SMS|WA|RCS)\s*\|\s*(.+)$", re.IGNORECASE | re.MULTILINE)
    matches = pattern.findall(description)
    for chan, text in matches:
        results.append((chan.upper(), text.strip()))
    return results


def parse_jira_brief(issue_data: dict[str, Any], download_creatives: bool = True) -> ParsedJiraBrief:
    """
    Parse a complete Jira ticket dictionary (from fetch_jira_issue)
    into structured WhatsApp, RCS, and SMS template drafts with media mappings.
    """
    key = str(issue_data.get("key", "TCN_001"))
    summary = str(issue_data.get("summary", ""))
    desc_text = str(issue_data.get("description_text", ""))
    desc_raw = issue_data.get("description_raw")
    sub_account = infer_sub_account_from_text(summary + " " + desc_text)

    # 1. Download and categorize attachments
    raw_attachments = issue_data.get("attachments", [])
    mapped_attachments: list[dict[str, Any]] = []

    for att in raw_attachments:
        fn = att.get("filename", "")
        att_id = att.get("id")
        mime = att.get("mimeType", "")
        local_path: str | None = None
        if download_creatives and att_id:
            try:
                p = download_jira_attachment(att_id, fn)
                local_path = str(p)
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

        mapped_attachments.append({
            "id": att_id,
            "filename": fn,
            "local_path": local_path,
            "mime": mime,
            "target_channel": target_chan,
        })

    # Collect creative images
    wa_creatives = [a for a in mapped_attachments if a["target_channel"] == "WHATSAPP" and a.get("local_path")]
    if not wa_creatives:
        wa_creatives = [a for a in mapped_attachments if "image" in a.get("mime", "") and a.get("local_path")]

    rcs_creatives = [a for a in mapped_attachments if a["target_channel"] == "RCS" and a.get("local_path")] or wa_creatives

    wa_drafts: list[WhatsAppTemplateDraft] = []
    rcs_drafts: list[RcsTemplateDraft] = []
    sms_drafts: list[SmsTemplateDraft] = []

    base_name = f"{key.lower().replace('-', '_')}_{re.sub(r'[^a-z0-9]', '_', summary.lower())[:16]}".strip("_")

    # 2. Extract structured content items
    items = _parse_tables_from_adf(desc_raw)
    if not items:
        # Fallback to plain pipe lines
        pipe_blocks = _split_pipe_channel_blocks(desc_text)
        for chan_tag, text_val in pipe_blocks:
            items.append({
                "channel": chan_tag,
                "text": text_val,
                "variant": "General",
            })

    wa_counter = 1
    rcs_counter = 1
    sms_counter = 1

    for item in items:
        chan = item["channel"]
        clean_content = item["text"]
        variant = item.get("variant", "General")
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
                )
            )
            wa_counter += 1

        elif chan == "RCS":
            img = rcs_creatives[(rcs_counter - 1) % len(rcs_creatives)] if rcs_creatives else None
            tname = _clean_template_name(base_name, "rcs", rcs_counter)
            rcs_drafts.append(
                RcsTemplateDraft(
                    template_name=tname,
                    card_title=summary[:32],
                    body=norm_text,
                    media_file=img.get("local_path") if img else None,
                    media_filename=img.get("filename") if img else None,
                    action_type="URL",
                    action_label="Explore Now",
                    action_url="https://www.tatacapital.com",
                    variables=variables,
                    raw_source=clean_content,
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
                )
            )
            sms_counter += 1

    # 3. Build MoEngage Campaign Staging payload
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

    return ParsedJiraBrief(
        issue_key=key,
        summary=summary,
        account=sub_account,
        status=str(issue_data.get("status", "To Do")),
        assignee=str(issue_data.get("assignee", "Unassigned")),
        reporter=str(issue_data.get("reporter", "Anonymous")),
        duedate=issue_data.get("duedate"),
        whatsapp_templates=[asdict(w) for w in wa_drafts],
        rcs_templates=[asdict(r) for r in rcs_drafts],
        sms_templates=[asdict(s) for s in sms_drafts],
        moengage_campaign=moengage_campaign,
        attachments_mapped=mapped_attachments,
    )
