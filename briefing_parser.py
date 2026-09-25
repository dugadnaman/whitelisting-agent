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
    action_url: str = "https://u3.mnge.co/"
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
    email_templates: list[dict[str, Any]] = field(default_factory=list)
    moengage_campaign: dict[str, Any] = field(default_factory=dict)
    attachments_mapped: list[dict[str, Any]] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)
    comment_updates: list[dict[str, Any]] = field(default_factory=list)

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

DEFAULT_CTA_URL = "https://u3.mnge.co/"


def normalize_placeholders(raw_text: str) -> tuple[str, list[str]]:
    """
    Convert informal Jira placeholders (<xxx>, <name>, [Loan Amount], [ROI], [Tenure], etc.)
    to strict Meta-compliant sequential placeholders ({{1}}, {{2}}, ...) without collisions.
    Handles mixed existing {{1}} variables, bracketed parameters, and generates context-aware samples.
    """
    s = raw_text.strip()
    if not s:
        return "", []

    # 1. Resolve explicit link placeholders first
    s = re.sub(r"<\s*(?:link|Link|url|URL|website|લિંક)\s*>", DEFAULT_CTA_URL, s)
    s = re.sub(r"\{\s*(?:link|Link|url|URL|website|લિંક)\s*\}", DEFAULT_CTA_URL, s)
    s = re.sub(r"\[\s*(?:link|Link|url|URL|website|લિંક)\s*\]", DEFAULT_CTA_URL, s)
    # 2. Unified placeholder pattern matching all informal, regional, and existing variables
    placeholder_pat = re.compile(
        r"(?:₹\s*)?(?:"
        r"\{\{\s*\d+\s*\}\}"
        r"|\{\{\s*[^\{\}]+\s*\}\}"
        r"|#?\{#[^#]+#\}#?"
        r"|<[^<>]+>"
        r"|\[[^\[\]]+\]"
        r"|\{[^\{\}]+\}"
        r")"
    )

    var_counter = 1
    samples: list[str] = []

    def infer_sample(tag: str, before_context: str, after_context: str = "") -> str:
        clean = re.sub(r"[^a-zA-Z0-9]", " ", tag).lower().strip()
        ctx = before_context.lower()
        suffix = after_context.lower()

        # 1. Semantic keyword checks on the placeholder label itself
        if any(w in clean for w in ["name", "client", "customer", "first"]):
            return "Rahul"
        if any(w in clean for w in ["tenure", "month", "year", "period", "duration"]):
            return "24 months"
        if any(w in clean for w in ["roi", "rate", "interest", "percentage"]):
            return "8.5%"
        if any(w in clean for w in ["date", "day", "deadline"]):
            return "15th Oct 2026"
        if any(w in clean for w in ["amount", "loan", "sanction", "limit", "price", "fee", "xxx", "x"]) or "₹" in tag:
            return "5,00,000" if "emi" not in clean else "15,000"
        if any(w in clean for w in ["emi"]):
            return "15,000"
        if any(w in clean for w in ["account", "id", "application", "ref", "number"]):
            return "TCL123456"
        if any(w in clean for w in ["city", "location"]):
            return "Mumbai"
        if any(w in clean for w in ["branch"]):
            return "Andheri"

        # 2. Immediate prefix cues (highest context priority right before the tag)
        last_words = " ".join(ctx.split()[-3:]) if ctx.split() else ""
        if any(k in last_words for k in ["dear", "hi", "hello"]):
            return "Rahul"
        if any(k in last_words for k in ["rs.", "rs", "inr", "₹", "loan of", "worth", "upto", "up to", "spends of"]):
            return "5,00,000"
        if any(k in last_words for k in ["at", "roi", "rate", "%"]):
            return "8.5%"
        if any(k in last_words for k in ["for", "tenure"]):
            return "24 months"

        # 3. Tight suffix cues (first 2 words directly after the tag)
        first_suffix_words = " ".join(suffix.split()[:2]) if suffix.split() else ""
        if any(k in first_suffix_words for k in ["interest", "roi", "rate", "p.a.", "%"]):
            return "8.5%"
        if any(k in first_suffix_words for k in ["month", "year", "tenure"]):
            return "24 months"
        if any(k in first_suffix_words for k in ["lakh", "crore", "rupee", "cashback"]):
            return "5,00,000"

        # 4. Broader context cues
        if any(k in ctx for k in ["rs.", "inr", "₹", "loan of", "spends of"]):
            return "5,00,000"
        if any(k in ctx for k in [" at ", "interest"]):
            return "8.5%"
        if any(k in ctx for k in ["for ", "tenure"]):
            return "24 months"
        if any(k in ctx for k in ["dear", "hi ", "hello"]):
            return "Rahul"

        return "Exclusive"

    def repl(match: re.Match) -> str:
        nonlocal var_counter
        full_match = match.group(0)
        has_rupee = full_match.startswith("₹")
        tag = full_match[1:].strip() if has_rupee else full_match

        # CTA keyword exemption: don't convert CTA text in brackets like [Apply Now] or <Click Here>
        tag_clean = tag.lower()
        if any(cta in tag_clean for cta in ["apply", "check", "click", "explore", "now", "here", "download", "visit"]):
            return full_match

        # Markdown link exemption: e.g. [Link Text](https://...)
        end = match.end()
        if end < len(s) and s[end] == "(":
            return full_match

        start = match.start()
        end = match.end()
        before_ctx = s[max(0, start - 25):start]
        after_ctx = s[end:min(len(s), end + 25)]
        sample = infer_sample(tag, before_ctx, after_ctx)
        samples.append(sample)
        prefix = "₹" if has_rupee else ""
        res = f"{prefix}{{{{{var_counter}}}}}"
        var_counter += 1
        return res

    normalized = placeholder_pat.sub(repl, s)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    return normalized, samples

def detect_language(text: str, column_name: str = "") -> str:
    """Detect language code (e.g. 'en', 'gu', 'hi', 'pa', 'mr', 'bn', 'ta', 'te', 'kn', 'ml') from column or script."""
    c_low = column_name.lower().strip()
    if any(k in c_low for k in ["gujarati", "gujrati", "guj"]): return "gu"
    if any(k in c_low for k in ["punjabi", "pun"]): return "pa"
    if any(k in c_low for k in ["hindi", "hin"]): return "hi"
    if any(k in c_low for k in ["marathi", "mar"]): return "mr"
    if any(k in c_low for k in ["bengali", "bangla", "ben"]): return "bn"
    if any(k in c_low for k in ["tamil", "tam"]): return "ta"
    if any(k in c_low for k in ["telugu", "tel"]): return "te"
    if any(k in c_low for k in ["kannada", "kan"]): return "kn"
    if any(k in c_low for k in ["malayalam", "mal"]): return "ml"

    for ch in text:
        code = ord(ch)
        if 0x0A80 <= code <= 0x0AFF: return "gu"  # Gujarati
        if 0x0A00 <= code <= 0x0A7F: return "pa"  # Gurmukhi (Punjabi)
        if 0x0900 <= code <= 0x097F: return "hi"  # Devanagari (Hindi)
        if 0x0980 <= code <= 0x09FF: return "bn"  # Bengali
        if 0x0B80 <= code <= 0x0BFF: return "ta"  # Tamil
        if 0x0C00 <= code <= 0x0C7F: return "te"  # Telugu
        if 0x0C80 <= code <= 0x0CFF: return "kn"  # Kannada
        if 0x0D00 <= code <= 0x0D7F: return "ml"  # Malayalam

    return "en"


def detect_category(summary: str, text: str = "", sheet_name: str = "") -> str:
    """Determine WhatsApp template category (UTILITY, AUTHENTICATION, MARKETING)."""
    combined = f"{summary} {text} {sheet_name}".lower()
    if any(k in combined for k in ["otp", "auth", "authentication", "verification code", "2fa"]):
        return "AUTHENTICATION"
    if any(k in combined for k in ["utility", "reminder", "statement", "receipt", "alert", "account update", "due date", "not banked", "short banked", "status update"]):
        return "UTILITY"
    return "MARKETING"


def extract_and_strip_cta(
    body: str,
    existing_btn_text: str | None = None,
    existing_btn_url: str | None = None,
    existing_footer: str | None = None,
) -> tuple[str, str, str, str | None]:
    """
    Identify and extract the Call-to-Action (CTA) line from a message body,
    removing it from the body text and placing it cleanly into button_text and button_url.
    Also identifies trailing T&C disclaimer lines and extracts them to footer_text.
    If no destination URL is provided, defaults to https://u3.mnge.co/.
    """
    if not body:
        return "", existing_btn_text or "Check Offer", existing_btn_url or DEFAULT_CTA_URL, existing_footer

    text = body.strip()
    extracted_btn_text = existing_btn_text
    extracted_url = existing_btn_url
    extracted_footer = existing_footer

    lines = text.split("\n")
    cleaned_lines: list[str] = []

    # Clean URL regex (excluding surrounding whitespace and brackets)
    url_pat = r"(https?://[^\s()\[\]]+|<link>|\{link\}|\[link\]|<url>|\{url\}|\[url\])"

    cta_inline_pat = re.compile(
        r"(?:[👉🔗▶️📍📲➡️✅]\s*)?"
        r"(?:\*|_)?\s*"
        r"(?:CTA\s*[:\-–]?\s*|check\s+(?:your\s+|my\s+)?offer|apply\s*(?:now|online|here)?|explore\s*(?:more|now|offer)?|tap\s*(?:here|to\s+save\s+more|now)?|click\s*(?:here|to\s+apply)?|visit\s*(?:now|us)?|view\s*offer|avail\s*now|simplify\s*your\s*repayments?\s*(?:today)?)"
        r"\s*[:\-–]?\s*(?:\*|_)?\s*"
        r"(?:" + url_pat + r")",
        re.IGNORECASE,
    )
    for line in lines:
        sline = line.strip()
        if not sline:
            cleaned_lines.append("")
            continue

        lower_line = sline.lower()

        # 1. Standalone T&C disclaimer line (e.g. '_T&Cs apply https://..._' or 'T&Cs apply.')
        clean_tc = sline.strip("*_ \t").lower()
        if clean_tc.startswith(("t&c", "t & c", "terms", "conditions apply", "disclaimer")):
            if not extracted_footer:
                extracted_footer = "T&C apply"
            continue
        # 2. Check if T&C is attached at the tail of the line
        m_tail = re.search(r"\s*(?:[*_])?\s*(?:t&c|t\s*&\s*c|terms\s*(?:and|&)?\s*conditions?)\s*(?:apply|applies)?\.?\s*(?:[*_])?\s*$", sline, re.IGNORECASE)
        if m_tail and m_tail.start() > 10:
            if not extracted_footer:
                extracted_footer = "T&C apply"
            sline = sline[:m_tail.start()].strip()
        # 2. Check for inline or standalone CTA
        has_url = re.search(url_pat, sline)
        inline_m = cta_inline_pat.search(sline)
        is_url_only = bool(re.match(r"^\s*(?:" + url_pat + r")\s*$", sline))
        starts_with_cta = bool(re.match(r"^\s*(?:CTA\s*[:\-–]|CTA\s+)", sline, re.IGNORECASE))
        starts_with_emoji = bool(re.match(r"^\s*(?:[👉🔗▶️📍📲➡️✅])", sline))

        if inline_m:
            before_part = sline[:inline_m.start()].strip()
            cta_part = sline[inline_m.start():].strip()

            m_url = re.search(url_pat, cta_part)
            if m_url:
                c_url = m_url.group(1).rstrip(".,_*_`\"").strip()
                if c_url.lower() in ("<link>", "{link}", "[link]", "<url>", "{url}", "[url]"):
                    extracted_url = DEFAULT_CTA_URL
                elif c_url.startswith("http"):
                    extracted_url = c_url

            btn_raw = re.sub(url_pat, "", cta_part)
            clean_btn = re.sub(r"[👉🔗▶️📍📲➡️✅*_\-:–|]", " ", btn_raw)
            clean_btn = re.sub(r"^(?:CTA\s*|Click\s*here\s*to\s*|Tap\s*to\s*)", "", clean_btn, flags=re.IGNORECASE).strip()
            clean_btn = re.sub(r"\s+", " ", clean_btn).strip()
            if clean_btn and len(clean_btn) <= 25 and len(clean_btn) >= 3:
                extracted_btn_text = clean_btn.title()
            elif not extracted_btn_text or extracted_btn_text == "Check Offer":
                if "apply" in cta_part.lower():
                    extracted_btn_text = "Apply Now"
                elif "explore" in cta_part.lower():
                    extracted_btn_text = "Explore Now"
                elif "offer" in cta_part.lower():
                    extracted_btn_text = "Check Offer"

            if before_part:
                cleaned_lines.append(before_part)
            continue

        elif is_url_only or (has_url and (starts_with_cta or starts_with_emoji or ":" in sline)):
            if has_url:
                c_url = has_url.group(1).rstrip(".,_*_`\"").strip()
                if c_url.lower() in ("<link>", "{link}", "[link]", "<url>", "{url}", "[url]"):
                    extracted_url = DEFAULT_CTA_URL
                elif c_url.startswith("http"):
                    extracted_url = c_url
            continue

        cleaned_lines.append(line)

    clean_body = "\n".join(cleaned_lines)
    clean_body = re.sub(r"\n{3,}", "\n\n", clean_body).strip()

    final_btn_text = extracted_btn_text or "Check Offer"
    final_url = extracted_url or DEFAULT_CTA_URL
    if final_url.rstrip("/") in ("https://www.tatacapital.com", "http://www.tatacapital.com", "https://tatacapital.com", "http://tatacapital.com", ""):
        final_url = DEFAULT_CTA_URL

    return clean_body, final_btn_text, final_url, extracted_footer

def is_cta_cell(val: str) -> bool:
    """Check if a cell contains a CTA link, button text, or redirect instruction."""
    if not val:
        return False
    v = val.strip().lower()
    if v.startswith(("http://", "https://", "<link>", "{link}", "[link]")):
        return True
    if v.startswith(("cta:", "cta -", "cta ", "apply:", "check:", "explore:")):
        return True
    if any(k in v for k in ["http://", "https://", "<link>"]) and any(c in v for c in ["apply", "check", "offer", "tap", "click"]):
        return True
    return False


def decompose_content(
    raw_text: str,
    explicit_header: str | None = None,
    explicit_footer: str | None = None,
    explicit_btn_text: str | None = None,
    explicit_btn_url: str | None = None,
    neighbor_cta: str | None = None,
    summary: str = "",
) -> dict[str, Any]:
    """
    Decompose any raw template content into structured, ready-to-whitelist components.
    Works whether:
    - Everything is in one cell (Header: ... Body: ... CTA: ...)
    - The CTA is in a neighbor cell
    - The copy has a leading headline
    Extracts header, clean body, footer, button type, text, URL, language, category, variables, and samples.
    """
    text = raw_text.strip()
    header_text = explicit_header
    footer_text = explicit_footer
    button_text = explicit_btn_text
    button_url = explicit_btn_url

    # 1. Explicit Title: / Header: / Body: blocks
    if "Title:" in text and "Body:" in text:
        title_m = re.search(r"Title:\s*([^\n]+)", text)
        body_m = re.search(r"Body:?\s*(.*?)(?:CTA:|$)", text, re.DOTALL)
        cta_m = re.search(r"CTA(?:\s*Button)?:\s*([^\n]+)", text)
        if title_m:
            header_text = title_m.group(1).strip()
        if body_m:
            text = body_m.group(1).strip()
        if cta_m:
            button_text = cta_m.group(1).strip()
    elif "Header:" in text and "Body:" in text:
        h_m = re.search(r"Header:\s*([^\n]+)", text)
        b_m = re.search(r"Body:?\s*(.*?)(?:Footer:|CTA:|$)", text, re.DOTALL)
        f_m = re.search(r"Footer:\s*([^\n]+)", text)
        if h_m:
            header_text = h_m.group(1).strip()
        if b_m:
            text = b_m.group(1).strip()
        if f_m:
            footer_text = f_m.group(1).strip()

    # 2. Neighbor cell CTA
    if neighbor_cta:
        m_url = re.search(r"(https?://[^\s()\[\]]+|<link>)", neighbor_cta)
        if m_url:
            button_url = DEFAULT_CTA_URL if m_url.group(1).lower() == "<link>" else m_url.group(1)
        clean_n = re.sub(r"(https?://[^\s()\[\]]+|<link>)", "", neighbor_cta)
        clean_n = re.sub(r"[👉🔗▶️📍📲➡️✅*_\-:–|]", " ", clean_n)
        clean_n = re.sub(r"^(?:CTA\s*|Click\s*here\s*to\s*|Tap\s*to\s*)", "", clean_n, flags=re.IGNORECASE).strip()
        if clean_n and 3 <= len(clean_n) <= 25:
            button_text = clean_n.title()

    # 3. Leading standalone Headline line
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) >= 3 and not header_text:
        first_line = lines[0]
        if len(first_line) < 45 and not any(k in first_line.lower() for k in ["dear", "hi", "hello", "{{", "<", "{#"]):
            if any(k in first_line.lower() for k in ["offer", "festive", "diwali", "save", "special", "congratulations", "upgrade", "alert", "notice", "update"]):
                header_text = first_line.strip("*_# ")
                text = "\n\n".join(lines[1:])

    # 4. Extract CTA & Footer from body
    norm_text, samples = normalize_placeholders(text)
    clean_body, cta_btn, cta_url, cta_foot = extract_and_strip_cta(
        norm_text,
        existing_btn_text=button_text,
        existing_btn_url=button_url,
        existing_footer=footer_text,
    )
    lang = detect_language(clean_body)
    cat = detect_category(summary or header_text or "", clean_body)

    # Constrained Gemini Intelligence: refine classification only. Gemini never supplies text.
    try:
        from gemini_intelligence import analyze_template_semantics
        ai_res = analyze_template_semantics(clean_body, summary=summary)
        if ai_res.get("category"):
            cat = ai_res["category"]
        if ai_res.get("language") and lang == "en":
            lang = ai_res["language"]
    except Exception:
        pass

    var_tags = re.findall(r"\{\{(\d+)\}\}", clean_body)

    return {
        "header_text": header_text,
        "body": clean_body,
        "footer_text": cta_foot or footer_text,
        "button_text": cta_btn,
        "button_url": cta_url,
        "language": lang,
        "category": cat,
        "variables": var_tags,
        "sample_values": samples[:len(var_tags)],
    }

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
MONTH_NAMES = {
    "jan": "jan", "january": "jan",
    "feb": "feb", "february": "feb",
    "mar": "mar", "march": "mar",
    "apr": "apr", "april": "apr",
    "may": "may",
    "jun": "jun", "june": "jun",
    "jul": "jul", "july": "jul",
    "aug": "aug", "august": "aug",
    "sep": "sep", "sept": "sep", "september": "sep",
    "oct": "oct", "october": "oct",
    "nov": "nov", "november": "nov",
    "dec": "dec", "december": "dec",
}

SKIP_SHEET_KEYWORDS = [
    "planner", "schedule", "calendar", "base count", "tracking",
    "summary", "exclusion", "report", "metrics", "decile", "overview"
]

def detect_ticket_month(summary: str, desc: str = "") -> str | None:
    """Infer the campaign month from the Jira summary or description."""
    text = f"{summary} {desc}".lower()
    words = re.findall(r"\b[a-z]+\b", text)
    for w in words:
        if w in MONTH_NAMES:
            return MONTH_NAMES[w]
    return None

def detect_sheet_month(sheet_name: str) -> str | None:
    words = re.findall(r"\b[a-z]+\b", sheet_name.lower())
    for w in words:
        if w in MONTH_NAMES:
            return MONTH_NAMES[w]
    return None

def should_skip_sheet(sheet_name: str, target_month: str | None = None) -> bool:
    s_low = sheet_name.lower()
    if any(k in s_low for k in SKIP_SHEET_KEYWORDS):
        return True
    if target_month:
        sheet_month = detect_sheet_month(sheet_name)
        if sheet_month and sheet_month != target_month:
            return True
    return False

def is_pure_cta_cell(s: str) -> bool:
    """Check if a cell is purely a CTA button or link without body copy."""
    if not s:
        return False
    text = s.strip()
    words = text.split()
    if len(words) > 10:
        return False
    url_pat = r"(https?://[^\s()\[\]]+|<link>|\{link\}|\[link\]|<url>|\{url\}|\[url\])"
    if re.match(r"^\s*(?:" + url_pat + r")\s*$", text):
        return True
    if re.match(
        r"^\s*(?:[👉🔗▶️📍📲➡️✅]\s*)?(?:CTA\s*[:\-–]?\s*|check\s+(?:your\s+|my\s+)?offer|apply\s*(?:now|online|here)?|explore\s*(?:more|now|offer)?|tap\s*(?:here|to\s+save\s+more|now)?|click\s*(?:here|to\s+apply)?|visit\s*(?:now|us)?|view\s*offer|avail\s*now)[\s:\-–]*(?:" + url_pat + r")?\s*$",
        text,
        re.IGNORECASE,
    ):
        return True
    return False


def is_valid_template_copy(text: str) -> bool:
    """
    Validate that a spreadsheet cell contains genuine customer-facing template copy,
    rejecting campaign tracking codes, operational notes, counts, and metadata.
    """
    if not text:
        return False
    s = text.strip()
    if len(s) < 25:
        return False

    # 0. Reject pure CTA button cells (they are buttons, not message bodies)
    if is_pure_cta_cell(s):
        return False
    # 1. Reject internal tracking codes / campaign IDs (e.g. TCLMOE_..., PAPL_..., etc.)
    if "\n" not in s and re.match(r"^(?:TCLMOE|TCL|PAPL|PQPL|UCL|TCF|MOE|SEG)_[A-Za-z0-9_\'-]+$", s, re.IGNORECASE):
        return False

    # 2. Reject internal operational notes, file manifests, and count tables
    s_low = s.lower()
    if any(s_low.startswith(p) for p in [
        "short |", "segment count", "grand total", "dob column", "below files",
        "pls release", "please release", "exclusion list", "date & time",
        "campaign execution", "channel name", "content format"
    ]):
        return False

    # 3. Reject pipe-separated database / tracking headers
    if "|" in s and ("created_at" in s_low or "valid_until" in s_low or "grand total" in s_low):
        return False

    # 4. Reject section headers that masquerade as copy
    if "\n" not in s and len(s) < 60:
        if any(h in s_low for h in ["wholebase", "automation", "normal term loan", "utility messages", "planner", "schedule"]):
            return False

    # 5. Must contain at least 4 whitespace-separated words
    words = s.split()
    if len(words) < 4:
        return False

    # 6. Must contain human customer messaging vocabulary or placeholders
    has_placeholder = bool(re.search(r"(\{\{|\<|\[|#\{#[^#]+#\}#|\{#[^#]+#\}|\{[a-zA-Z0-9_\-\s]+\})", s))
    has_greeting = bool(re.search(r"\b(dear|hi|hello|hey|namaste|greeting|welcome|congratulations)\b", s_low))
    has_messaging_keywords = any(k in s_low for k in [
        "loan", "offer", "tata", "capital", "emi", "fund", "funds", "interest", "rate", "roi",
        "apply", "pay", "tap", "click", "₹", "rs.", "rs ", "inr", "lakh", "lacs", "crore",
        "card", "account", "disbursal", "bank", "due", "cashback", "voucher", "disclaimer",
        "t&c", "terms", "journey", "benefit", "saving", "savings", "travel", "trip",
        "holiday", "upgrade", "repayment", "debt", "debts", "eligibility", "pre-approved",
        "pre approved", "approved", "pre-qualified", "instant", "quick", "flexible"
    ])

    return has_placeholder or has_greeting or has_messaging_keywords

def _normalize_channel_tag(tag: str) -> str | None:
    """Normalize any string (e.g. 'WhatsApp', 'WA', 'RCS', 'SMS Promotional') to canonical channel."""
    if not tag:
        return None
    t = re.sub(r"[^a-zA-Z0-9]", " ", str(tag)).upper()
    words = t.split()
    if "WHATSAPP" in words or "WA" in words or "WHATSAPP" in t:
        return "WA"
    if "RCS" in words or "RCS" in t:
        return "RCS"
    if "SMS" in words or "SMS" in t:
        return "SMS"
    if "PN" in words or "PUSH" in words:
        return "PN"
    if "EMAIL" in words or "MAILER" in words:
        return "EMAIL"
    return None

def _match_sheet_channel(sname: str) -> str | None:
    norm = re.sub(r"[^A-Za-z0-9]", " ", sname).strip().upper()
    words = norm.split()
    if "WHATSAPP" in norm or "WA" in words:
        return "WA"
    if "RCS" in words or "RCS" in norm:
        return "RCS"
    if "SMS" in words or "SMS" in norm:
        return "SMS"
    return None

def _load_spreadsheet_sheets(filepath: Path) -> dict[str, list[list[str]]]:
    """
    Universally load any spreadsheet file (.xlsx, .csv, .xls) into a dictionary of
    sheet_name -> 2D string matrix (raw_rows). Handles CSV encodings and Excel formats.
    """
    sheets: dict[str, list[list[str]]] = {}
    lower_path = str(filepath).lower()

    # 1. Handle CSV files with encoding fallback
    if lower_path.endswith(".csv"):
        import csv
        for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
            try:
                with open(filepath, "r", encoding=enc, errors="replace") as f:
                    reader = csv.reader(f)
                    rows = [[str(cell or "").strip() for cell in r] for r in reader if any(r)]
                    if rows:
                        sheets["Sheet1"] = rows
                        return sheets
            except Exception:
                continue
        return sheets

    # 2. Handle older binary .xls files directly via xlrd
    if lower_path.endswith(".xls") and not lower_path.endswith(".xlsx"):
        try:
            import xlrd
            xwb = xlrd.open_workbook(filepath)
            for sname in xwb.sheet_names():
                xsh = xwb.sheet_by_name(sname)
                rows: list[list[str]] = []
                for r in range(xsh.nrows):
                    vals = [str(xsh.cell_value(r, c) or "").strip() for c in range(xsh.ncols)]
                    if any(vals):
                        rows.append(vals)
                if rows:
                    sheets[sname] = rows
            return sheets
        except Exception as exc:
            logger.warning("xlrd could not load %s: %s", filepath, exc)

    # 3. Handle Excel files (.xlsx, .xlsm)
    try:
        wb = openpyxl.load_workbook(filepath, data_only=True)
        for sname in wb.sheetnames:
            ws = wb[sname]
            rows: list[list[str]] = []
            for r in range(1, ws.max_row + 1):
                vals = [str(ws.cell(row=r, column=c).value or "").strip() for c in range(1, ws.max_column + 1)]
                if any(vals):
                    rows.append(vals)
            if rows:
                sheets[sname] = rows
        return sheets
    except Exception as exc:
        logger.warning("openpyxl could not load %s: %s", filepath, exc)

    # 3. Fallback: try pandas for .xls or complex formats
    try:
        import pandas as pd
        excel_file = pd.ExcelFile(filepath)
        for sname in excel_file.sheet_names:
            df = pd.read_excel(excel_file, sheet_name=sname, header=None)
            df = df.fillna("")
            rows = [[str(val).strip() for val in row] for row in df.values.tolist()]
            rows = [r for r in rows if any(r)]
            if rows:
                sheets[sname] = rows
        return sheets
    except Exception as exc:
        logger.warning("pandas fallback could not load %s: %s", filepath, exc)

    return sheets
def _parse_raw_sheet_rows(raw_rows: list[list[str]], sname: str) -> list[dict[str, str]]:
    """
    Universally parse template content from 2D raw string rows of any sheet.
    Supports:
    1. Dedicated channel sheets (e.g. 'WA', 'WhatsApp Content', 'SMS_1', 'RCS')
    2. Columnar channel tables (e.g. Column 0 has 'Channel', Column 1 has 'Content')
    3. Section header rows (e.g. ['Content', 'SMS Promotional'], ['Content', 'WhatsApp'])
    4. Multilingual columns (e.g. ['Channel', 'English', 'Gujarati', 'Hindi'])
    5. Standard template tables (template_name | body | header | button...)
    """
    items: list[dict[str, str]] = []
    sheet_chan = _normalize_channel_tag(sname)
    if not raw_rows:
        return items

    # Detect channel column or header row
    chan_col_idx = None
    header_row_idx = None

    for r_idx, row in enumerate(raw_rows[:5]):
        for c_idx, val in enumerate(row):
            v_low = val.lower()
            if v_low in ("channel", "channel name", "platform", "medium", "mode"):
                chan_col_idx = c_idx
                header_row_idx = r_idx
                break
        if chan_col_idx is not None:
            break

    # If no explicit 'Channel' header, check if column 0 contains channel tags
    if chan_col_idx is None:
        chan_tags_in_col0 = sum(1 for row in raw_rows if row and _normalize_channel_tag(row[0]) is not None)
        if chan_tags_in_col0 >= 1:
            chan_col_idx = 0
            header_row_idx = 0 if _normalize_channel_tag(raw_rows[0][0]) is None else -1

    current_channel = sheet_chan
    start_idx = (header_row_idx + 1) if header_row_idx is not None and header_row_idx >= 0 else 0
    header_row = [c.lower() for c in raw_rows[header_row_idx]] if header_row_idx is not None and header_row_idx >= 0 and header_row_idx < len(raw_rows) else []

    # Check for columnar headers (e.g. template_name | body | header | button...)
    body_col_idx = None
    if header_row:
        for idx, h in enumerate(header_row):
            if "header" in h or "title" in h or "type" in h or "name" in h:
                continue
            if any(k in h for k in ["body", "content", "copy", "message", "text"]):
                body_col_idx = idx
                break

    header_col_idx = next((i for i, h in enumerate(header_row) if "header" in h and "type" not in h), None)
    footer_col_idx = next((i for i, h in enumerate(header_row) if "footer" in h), None)
    btn_text_col_idx = next((i for i, h in enumerate(header_row) if "button_text" in h or "cta" in h), None)
    btn_url_col_idx = next((i for i, h in enumerate(header_row) if "button_url" in h or "url" in h or "link" in h), None)
    btn_type_col_idx = next((i for i, h in enumerate(header_row) if "button_type" in h), None)

    for r_num, row in enumerate(raw_rows[start_idx:], start=start_idx + 1):
        # 1. Section header (only when ALL cells are short and no long copy exists)
        has_long_copy = any(len(c) > 25 for c in row)
        if not has_long_copy:
            for cell in row:
                c_norm = _normalize_channel_tag(cell)
                if c_norm and any(k in cell.lower() for k in ["promotional", "retargeting", "utility", "content", "whatsapp", "sms", "rcs"]):
                    current_channel = c_norm
                    break
            continue

        # 2. Check channel column
        if chan_col_idx is not None and chan_col_idx < len(row):
            row_chan = _normalize_channel_tag(row[chan_col_idx])
            if row_chan:
                current_channel = row_chan

        active_chan = current_channel or sheet_chan
        if not active_chan:
            for cell in row[:2]:
                c_norm = _normalize_channel_tag(cell)
                if c_norm:
                    active_chan = c_norm
                    current_channel = c_norm
                    break

        if not active_chan:
            continue

        # Skip header rows
        row_joined = " ".join(row).lower()
        if any(h in row_joined for h in ["channel", "gujarati", "punjabi", "created_at", "valid_until"]):
            if not any(len(cell) > 40 for cell in row):
                continue

        # 3. If explicit body column was detected, extract from that column
        if body_col_idx is not None and body_col_idx < len(row) and len(row[body_col_idx]) > 15:
            body_val = row[body_col_idx]
            if is_valid_template_copy(body_val):
                item_dict: dict[str, str] = {
                    "channel": active_chan,
                    "text": body_val,
                    "variant": f"Variant {r_num}",
                    "source": f"excel_{sname}_r{r_num}",
                }
                if header_col_idx is not None and header_col_idx < len(row) and row[header_col_idx]:
                    item_dict["header"] = row[header_col_idx]
                if footer_col_idx is not None and footer_col_idx < len(row) and row[footer_col_idx]:
                    item_dict["footer"] = row[footer_col_idx]
                if btn_text_col_idx is not None and btn_text_col_idx < len(row) and row[btn_text_col_idx]:
                    item_dict["button_text"] = row[btn_text_col_idx]
                if btn_url_col_idx is not None and btn_url_col_idx < len(row) and row[btn_url_col_idx]:
                    item_dict["button_url"] = row[btn_url_col_idx]
                if btn_type_col_idx is not None and btn_type_col_idx < len(row) and row[btn_type_col_idx]:
                    item_dict["button_type"] = row[btn_type_col_idx]

                if "Title:" in body_val and "Body:" in body_val:
                    title_m = re.search(r"Title:\s*([^\n]+)", body_val)
                    body_m = re.search(r"Body:?\s*(.*?)(?:CTA:|$)", body_val, re.DOTALL)
                    if title_m:
                        item_dict["title"] = title_m.group(1).strip()
                    if body_m:
                        item_dict["text"] = body_m.group(1).strip()

                items.append(item_dict)
                continue

        # 4. Otherwise scan non-channel columns for copy (multilingual, multi-column, or row lists)
        skip_indices = {chan_col_idx} if chan_col_idx is not None else set()
        for c_idx, cell in enumerate(row):
            if c_idx in skip_indices:
                continue
            clean_cell = cell.strip()
            if is_valid_template_copy(clean_cell):
                variant = "General"
                if row and row[0] and row[0].lower().startswith("c") and len(row[0]) < 10:
                    variant = row[0].upper()
                elif header_row and c_idx < len(header_row):
                    col_hdr = header_row[c_idx]
                    if col_hdr and col_hdr not in ("content", "message", "copy", "text", "body"):
                        variant = col_hdr.title()

                item_dict = {
                    "channel": active_chan,
                    "text": clean_cell,
                    "variant": variant,
                    "source": f"excel_{sname}_r{r_num}",
                }
                if "Title:" in clean_cell and "Body:" in clean_cell:
                    title_m = re.search(r"Title:\s*([^\n]+)", clean_cell)
                    body_m = re.search(r"Body:?\s*(.*?)(?:CTA:|$)", clean_cell, re.DOTALL)
                    if title_m:
                        item_dict["title"] = title_m.group(1).strip()
                    if body_m:
                        item_dict["text"] = body_m.group(1).strip()

                items.append(item_dict)

    # 3. Pass 3: Universal Spatial Matrix Scanner (The "Arrive Anyhow" Engine)
    # If no templates were extracted from Pass 1 or Pass 2 (e.g. unformatted A1/A2/B1/B2 layouts)
    if not items:
        consumed_coords: set[tuple[int, int]] = set()
        for r_idx, row in enumerate(raw_rows):
            for c_idx, cell in enumerate(row):
                if (r_idx, c_idx) in consumed_coords:
                    continue
                clean_cell = cell.strip()
                if not is_valid_template_copy(clean_cell):
                    continue

                neighbor_cta = None
                neighbor_header = None

                # Look right for neighbor CTA
                if c_idx + 1 < len(row) and is_pure_cta_cell(row[c_idx + 1]):
                    neighbor_cta = row[c_idx + 1]
                    consumed_coords.add((r_idx, c_idx + 1))
                # Look down for neighbor CTA
                elif r_idx + 1 < len(raw_rows) and c_idx < len(raw_rows[r_idx + 1]) and is_pure_cta_cell(raw_rows[r_idx + 1][c_idx]):
                    neighbor_cta = raw_rows[r_idx + 1][c_idx]
                    consumed_coords.add((r_idx + 1, c_idx))

                # Look up for neighbor header
                if r_idx > 0 and c_idx < len(raw_rows[r_idx - 1]):
                    top_c = raw_rows[r_idx - 1][c_idx].strip()
                    if 3 < len(top_c) < 45 and not is_cta_cell(top_c) and not is_valid_template_copy(top_c):
                        neighbor_header = top_c

                decomp = decompose_content(
                    clean_cell,
                    explicit_header=neighbor_header,
                    neighbor_cta=neighbor_cta,
                )

                item_dict = {
                    "channel": sheet_chan or ("RCS" if decomp.get("header_text") else "WA"),
                    "text": decomp["body"],
                    "header": decomp["header_text"],
                    "footer": decomp["footer_text"],
                    "button_text": decomp["button_text"],
                    "button_url": decomp["button_url"],
                    "variant": f"Cell_{r_idx + 1}_{c_idx + 1}",
                    "source": f"excel_spatial_{sname}_r{r_idx + 1}_c{c_idx + 1}",
                }
                items.append(item_dict)

    return items


def _parse_excel_channel_sheets(wb: openpyxl.Workbook, target_month: str | None = None) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for sname in wb.sheetnames:
        if should_skip_sheet(sname, target_month):
            continue
        ws = wb[sname]
        raw_rows = []
        for r in range(1, ws.max_row + 1):
            vals = [str(ws.cell(row=r, column=c).value or "").strip() for c in range(1, ws.max_column + 1)]
            if any(vals):
                raw_rows.append(vals)
        items.extend(_parse_raw_sheet_rows(raw_rows, sname))
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


def extract_templates_from_excel_file(filepath: Path, target_month: str | None = None) -> list[dict[str, str]]:
    """
    Inspect and extract template items from any client spreadsheet (.xlsx, .csv, .xls) across all sheets.
    Combines channel-tagged tables, section headers, grid messages, and key-value blocks.
    Filters out historical past-month sheets and administrative planner sheets.
    Deduplicates identical templates so multi-sheet workbooks don't produce duplicate cards.
    """
    sheets = _load_spreadsheet_sheets(filepath)
    if not sheets:
        return []

    all_items: list[dict[str, str]] = []
    seen_texts: set[str] = set()

    for sname, raw_rows in sheets.items():
        if should_skip_sheet(sname, target_month=target_month):
            continue
        sheet_items = _parse_raw_sheet_rows(raw_rows, sname)
        for item in sheet_items:
            raw_t = item.get("text", "")
            if not is_valid_template_copy(raw_t):
                continue
            norm_key = re.sub(r"\s+", " ", raw_t).strip().lower()
            if norm_key and norm_key not in seen_texts:
                seen_texts.add(norm_key)
                all_items.append(item)

    return all_items

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
    button_url = DEFAULT_CTA_URL

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

        fn_lower = fn.lower()
        if fn_lower.endswith((".xlsx", ".xls", ".csv")):
            target_chan = "SPREADSHEET_BRIEF"
        elif fn_lower.endswith((".zip", ".docx", ".doc")):
            target_chan = "EMAIL_CREATIVE"
        elif "wa" in fn_lower or "whatsapp" in fn_lower:
            target_chan = "WHATSAPP"
        elif "rcs" in fn_lower:
            target_chan = "RCS"
        elif "sms" in fn_lower:
            target_chan = "SMS"
        else:
            target_chan = "GENERAL"
        mapped_attachments.append({
            "id": att_id,
            "filename": fn,
            "local_path": local_path,
            "mime": mime,
            "target_channel": target_chan,
        })

    IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
    wa_creatives = [
        a for a in mapped_attachments
        if a.get("filename", "").lower().endswith(IMAGE_EXTS) and a.get("local_path")
        and (a["target_channel"] == "WHATSAPP" or "wa" in a.get("filename", "").lower() or "whatsapp" in a.get("filename", "").lower())
    ]
    if not wa_creatives:
        wa_creatives = [
            a for a in mapped_attachments
            if a.get("filename", "").lower().endswith(IMAGE_EXTS) and a.get("local_path")
        ]

    rcs_creatives = [
        a for a in mapped_attachments
        if a.get("filename", "").lower().endswith(IMAGE_EXTS) and a.get("local_path")
        and (a["target_channel"] == "RCS" or "rcs" in a.get("filename", "").lower())
    ] or wa_creatives

    wa_drafts: list[WhatsAppTemplateDraft] = []
    rcs_drafts: list[RcsTemplateDraft] = []
    sms_drafts: list[SmsTemplateDraft] = []
    email_drafts: list[dict[str, Any]] = []

    # Collect email mailer packages and subject line files from attachments
    for att in mapped_attachments:
        fn = att.get("filename", "")
        lower_fn = fn.lower()
        if lower_fn.endswith((".zip", ".docx", ".doc", ".html")):
            f_type = (
                "HTML Mailer Package"
                if lower_fn.endswith(".zip")
                else ("Subject Lines & Preheaders" if lower_fn.endswith((".docx", ".doc")) else "HTML Template")
            )
            email_drafts.append({
                "template_name": Path(fn).stem,
                "filename": fn,
                "file_type": f_type,
                "local_path": att.get("local_path"),
                "target_channel": "EMAIL",
            })
    base_name = f"{key.lower().replace('-', '_')}_{re.sub(r'[^a-z0-9]', '_', summary.lower())[:16]}".strip("_")

    # 2. Extract templates from attached Excel files first
    target_month = detect_ticket_month(summary, desc_text)
    extracted_items: list[dict[str, str]] = []
    for excel_path in excel_attachment_paths:
        items = extract_templates_from_excel_file(excel_path, target_month=target_month)
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

    # 3c. Check ticket comments for revisions / copy updates
    raw_comments = issue_data.get("comments", [])
    comment_updates: list[dict[str, Any]] = []
    for c in raw_comments:
        c_body = c.get("body_text", "")
        author = c.get("author", "Commenter")
        pipe_m = re.findall(r"^(SMS|WA|RCS|WHATSAPP)\s*\|\s*(.+)$", c_body, re.IGNORECASE | re.MULTILINE)
        for c_tag, t_val in pipe_m:
            comment_updates.append({
                "channel": "WA" if c_tag.upper() in ("WA", "WHATSAPP") else c_tag.upper(),
                "text": t_val.strip(),
                "variant": f"Revision by {author}",
                "source": f"comment_{c.get('id', '')}",
            })
        rev_m = re.findall(r"(?:updated|revised|new|approved)\s+(wa|whatsapp|sms|rcs)\s*[:\-–]\s*(.+?)(?=\n\s*(?:updated|revised|new|sms|wa|rcs|$)|\Z)", c_body, re.IGNORECASE | re.DOTALL)
        for c_tag, t_val in rev_m:
            if len(t_val.strip()) > 20:
                comment_updates.append({
                    "channel": "WA" if c_tag.upper() in ("WA", "WHATSAPP") else c_tag.upper(),
                    "text": t_val.strip(),
                    "variant": f"Revision by {author}",
                    "source": f"comment_rev_{c.get('id', '')}",
                })

    if comment_updates:
        extracted_items.extend(comment_updates)
    # 3b. SWCM WhatsApp campaign tables ("Campaign execution format N | WA N")
    swcm_campaigns = _parse_swcm_campaign_tables(desc_raw)
    for idx, campaign in enumerate(swcm_campaigns, start=1):
        cta_text, cta_url = _parse_swcm_cta(campaign.get("cta_text", ""), campaign.get("cta_links", []))
        norm_text, samples = normalize_placeholders(campaign["body"])
        clean_body, swcm_btn_text, swcm_btn_url, swcm_footer = extract_and_strip_cta(
            norm_text,
            existing_btn_text=cta_text,
            existing_btn_url=cta_url,
        )
        var_tags = re.findall(r"\{\{(\d+)\}\}", clean_body)
        if len(samples) > len(var_tags):
            samples = samples[:len(var_tags)]
        media = _match_creative_to_campaign(campaign["campaign_name"], zip_creative_paths)
        if media is None and zip_creative_paths:
            media = zip_creative_paths[(idx - 1) % len(zip_creative_paths)]
        tname = _clean_template_name(base_name, "wa", idx)
        lang = detect_language(clean_body)
        cat = detect_category(summary, clean_body)
        tname = _clean_template_name(base_name, f"wa_{lang}" if lang != "en" else "wa", idx)
        wa_drafts.append(
            WhatsAppTemplateDraft(
                template_name=tname,
                category=cat,
                language=lang,
                body=clean_body,
                header_type="IMAGE" if media else "TEXT",
                media_file=media,
                media_filename=Path(media).name if media else None,
                button_type="URL",
                button_text=swcm_btn_text,
                button_url=swcm_btn_url,
                footer_text=swcm_footer,
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
            clean_body, cta_btn_text, cta_btn_url, cta_footer = extract_and_strip_cta(
                norm_text,
                existing_btn_text=item.get("button_text"),
                existing_btn_url=item.get("button_url"),
                existing_footer=item.get("footer"),
            )
            lang = detect_language(clean_body, variant)
            cat = detect_category(summary, clean_body, item.get("source", ""))
            tname = _clean_template_name(base_name, f"wa_{lang}" if lang != "en" else "wa", wa_counter)

            var_tags = re.findall(r"\{\{(\d+)\}\}", clean_body)
            resolved_vars = var_tags
            if len(resolved_samples) > len(var_tags):
                resolved_samples = resolved_samples[:len(var_tags)]

            wa_drafts.append(
                WhatsAppTemplateDraft(
                    template_name=tname,
                    category=cat,
                    language=lang,
                    body=clean_body,
                    header_type="IMAGE" if img else ("TEXT" if item.get("header") else "TEXT"),
                    header_text=item.get("header"),
                    footer_text=cta_footer or item.get("footer"),
                    media_file=img.get("local_path") if img else None,
                    media_filename=img.get("filename") if img else None,
                    button_type=item.get("button_type") or "URL",
                    button_text=cta_btn_text,
                    button_url=cta_btn_url,
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
            clean_body, cta_btn_text, cta_btn_url, _ = extract_and_strip_cta(
                norm_text,
                existing_btn_text=item.get("button_text"),
                existing_btn_url=item.get("button_url"),
            )
            var_tags = re.findall(r"\{\{(\d+)\}\}", clean_body)

            rcs_drafts.append(
                RcsTemplateDraft(
                    template_name=tname,
                    card_title=title,
                    body=clean_body,
                    media_file=img.get("local_path") if img else None,
                    media_filename=img.get("filename") if img else None,
                    action_type=item.get("button_type") or "URL",
                    action_label=cta_btn_text,
                    action_url=cta_btn_url,
                    variables=item.get("variables") or var_tags,
                    sample_values=item.get("sample_values") or resolved_samples[:len(var_tags)],
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
                    variables=resolved_vars,
                    sample_values=resolved_samples,
                    raw_source=clean_content,
                    source_origin=source_origin,
                )
            )
            sms_counter += 1

        elif chan in ("EMAIL", "MAILER", "MAIL"):
            email_drafts.append({
                "template_name": _clean_template_name(base_name, "email", len(email_drafts) + 1),
                "filename": f"Email Copy {len(email_drafts) + 1}",
                "file_type": "Email Body Copy",
                "body": norm_text,
                "variant": variant,
                "source_origin": source_origin,
            })
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
        email_templates=email_drafts,
        moengage_campaign=moengage_campaign,
        attachments_mapped=mapped_attachments,
        comments=raw_comments,
        comment_updates=comment_updates,
    )
