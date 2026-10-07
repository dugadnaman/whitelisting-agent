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
    buttons: list[dict[str, Any]] = field(default_factory=list)
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
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)
    sample_values: list[str] = field(default_factory=list)
    raw_source: str = ""
    source_origin: str = "jira"
    template_type: str = "richcard"  # "text" | "richcard" | "carousel"
    carousel_cards: list[dict[str, Any]] = field(default_factory=list)

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
    channel_counts: dict[str, int] = field(default_factory=dict)
    campaign_metadata: dict[str, Any] = field(default_factory=dict)

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

    # 1. Clean standalone T&C lines: strip surrounding _/* markdown, and convert any
    # <link>/<url> placeholder on a T&C line into a variable token (<tc_url>) so it becomes {{1}}
    # at the end of T&Cs apply instead of being replaced by DEFAULT_CTA_URL.
    raw_lines = s.split("\n")
    precleaned_lines: list[str] = []
    for rline in raw_lines:
        s_tc = rline.strip().strip("*_ \t").lower()
        if s_tc.startswith(("t&c", "t & c", "terms", "conditions apply", "disclaimer")):
            tc_line = rline.strip().strip("*_ \t")
            tc_line = re.sub(
                r"<\s*(?:link|url|website|લિંક)\s*>|\{\s*(?:link|url|website|લિંક)\s*\}|\[\s*(?:link|url|website|લિંક)\s*\]",
                "<tc_url>",
                tc_line,
                flags=re.IGNORECASE,
            )
            tc_line = re.sub(r"[ \t]+", " ", tc_line).strip("*_ \t")
            if tc_line:
                precleaned_lines.append(tc_line)
        else:
            precleaned_lines.append(rline)
    s = "\n".join(precleaned_lines)

    # 1b. Resolve explicit link placeholders before variable numbering
    s = re.sub(
        r"<\s*(?:https?://[^<>]+|[^<>]*\b(?:link|url|website)\b[^<>]*|લિંક)\s*>",
        DEFAULT_CTA_URL,
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"\{\s*(?:https?://[^{}]+|[^{}]*\b(?:link|url|website)\b[^{}]*|લિંક)\s*\}",
        DEFAULT_CTA_URL,
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"\[\s*(?:https?://[^\[\]]+|[^\[\]]*\b(?:link|url|website)\b[^\[\]]*|લિંક)\s*\]",
        DEFAULT_CTA_URL,
        s,
        flags=re.IGNORECASE,
    )
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
        before_ctx = s[max(0, start - 25) : start]
        after_ctx = s[end : min(len(s), end + 25)]
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
    if any(k in c_low for k in ["gujarati", "gujrati", "guj"]):
        return "gu"
    if any(k in c_low for k in ["punjabi", "pun"]):
        return "pa"
    if any(k in c_low for k in ["hindi", "hin"]):
        return "hi"
    if any(k in c_low for k in ["marathi", "mar"]):
        return "mr"
    if any(k in c_low for k in ["bengali", "bangla", "ben"]):
        return "bn"
    if any(k in c_low for k in ["tamil", "tam"]):
        return "ta"
    if any(k in c_low for k in ["telugu", "tel"]):
        return "te"
    if any(k in c_low for k in ["kannada", "kan"]):
        return "kn"
    if any(k in c_low for k in ["malayalam", "mal"]):
        return "ml"

    for ch in text:
        code = ord(ch)
        if 0x0A80 <= code <= 0x0AFF:
            return "gu"  # Gujarati
        if 0x0A00 <= code <= 0x0A7F:
            return "pa"  # Gurmukhi (Punjabi)
        if 0x0900 <= code <= 0x097F:
            return "hi"  # Devanagari (Hindi)
        if 0x0980 <= code <= 0x09FF:
            return "bn"  # Bengali
        if 0x0B80 <= code <= 0x0BFF:
            return "ta"  # Tamil
        if 0x0C00 <= code <= 0x0C7F:
            return "te"  # Telugu
        if 0x0C80 <= code <= 0x0CFF:
            return "kn"  # Kannada
        if 0x0D00 <= code <= 0x0D7F:
            return "ml"  # Malayalam

    return "en"


def detect_category(summary: str, text: str = "", sheet_name: str = "") -> str:
    """Determine WhatsApp template category (UTILITY, AUTHENTICATION, MARKETING)."""
    combined = f"{summary} {text} {sheet_name}".lower()
    if any(k in combined for k in ["otp", "auth", "authentication", "verification code", "2fa"]):
        return "AUTHENTICATION"
    if any(
        k in combined
        for k in [
            "utility",
            "reminder",
            "statement",
            "receipt",
            "alert",
            "account update",
            "due date",
            "not banked",
            "short banked",
            "status update",
            "ltv",
            "regularise",
            "regulatory",
            "rbi",
            "revision in ltv",
            "facility is above",
        ]
    ):
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
    T&Cs apply and disclaimers remain inside the message body — we never emit a FOOTER component.
    If no destination URL is provided, defaults to https://u3.mnge.co/.
    """
    if not body:
        fallback_body = existing_footer.strip() if existing_footer and existing_footer.strip() else ""
        return fallback_body, existing_btn_text or "Check Offer", existing_btn_url or DEFAULT_CTA_URL, None

    text = body.strip()
    extracted_btn_text = existing_btn_text
    extracted_url = existing_btn_url

    lines = text.split("\n")
    cleaned_lines: list[str] = []

    # Clean URL regex (excluding surrounding whitespace and brackets)
    url_pat = r"(https?://[^\s()\[\]]+|<link>|\{link\}|\[link\]|<url>|\{url\}|\[url\])"

    btn_bracket_pat = re.compile(
        r"^\s*(?:[👉🔗▶️📍📲➡️✅]\s*)?(?:CTA\s*(?:Button)?\s*[:\-–]?\s*)?(?:\[|<|\()(?:\s*CTA\s*[:\-–]?\s*)?\s*([^\s>\]\)][^>\]\)]*?)\s*(?:\]|>|\))\s*(?:->|=>|–|—|\||:)?\s*(?:"
        + url_pat
        + r")\s*$",
        re.IGNORECASE,
    )
    btn_only_pat = re.compile(
        r"^\s*(?:[👉🔗▶️📍📲➡️✅]\s*)?(?:CTA\s*(?:Button)?\s*[:\-–]?\s*)?(?:\[|<|\()(?:\s*CTA\s*[:\-–]?\s*)?\s*([A-Za-z0-9\s]{3,25})\s*(?:\]|>|\))\s*$",
        re.IGNORECASE,
    )

    directive_pat = re.compile(
        r"^\s*(?:[👉🔗▶️📍📲➡️✅]\s*)?(?:tap|click|press)\s+(?:here|below|down)?\s*(?:to|on)?\s*(.+?)(?:\s*[⬇️👇📲👉🔗▶️\s])*$",
        re.IGNORECASE,
    )

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

        # 1. Standalone bracket/angle CTA button tag (e.g. CTA Button <Check Eligibility> <url> or [Know more] <url>)
        m_btn = btn_bracket_pat.match(sline)
        if m_btn:
            lbl = m_btn.group(1).strip("*_~ ")
            u_val = m_btn.group(2).strip()
            if lbl and len(lbl) <= 25:
                extracted_btn_text = lbl.title()
            if u_val.startswith("http"):
                extracted_url = u_val
            elif not extracted_url or extracted_url == DEFAULT_CTA_URL:
                extracted_url = DEFAULT_CTA_URL
            continue
        # 1b. Standalone bracket/angle button tag without URL (e.g. <CHECK YOUR OFFER> or [Apply Now])
        m_btn_only = btn_only_pat.match(sline)
        if m_btn_only:
            lbl = m_btn_only.group(1).strip("*_~ ")
            if lbl and len(lbl) <= 25:
                extracted_btn_text = lbl.title()
            continue


        # 2. Standalone T&C disclaimer line
        clean_tc = sline.strip("*_ \t").lower()
        if clean_tc.startswith(("t&c", "t & c", "terms", "conditions apply", "disclaimer")):
            tc_clean = sline.strip("*_ \t")
            m_u = re.search(url_pat, tc_clean)
            if m_u:
                c_url = m_u.group(1).rstrip('.,_*_`"').strip()
                if c_url.startswith("http"):
                    extracted_url = c_url
            tc_clean = re.sub(url_pat, "", tc_clean)
            tc_clean = re.sub(r"https?://[^\s()\[\]_]+", "", tc_clean)
            tc_clean = re.sub(r"[ \t]+", " ", tc_clean).strip("*_ \t:-–")
            if tc_clean:
                cleaned_lines.append(tc_clean)
            continue

        # 2b. Line containing 'T&Cs apply <url>' with leading directive or customer copy like:
        # '👉 Apply below & double the joy. T&Cs apply https://u3.mnge.co/'
        # 'More orders are calling... Apply now: <url> T&Cs apply'
        m_tc_inline = re.search(
            r"(?:T\s*&\s*Cs?\s+apply\.?|Terms\s*(?:and|&)\s*Conditions\s+apply\.?)\s*(?:" + url_pat + r")?",
            sline,
            re.IGNORECASE,
        )
        if m_tc_inline and any(k in lower_line for k in ("apply below", "click below", "tap below", "apply now", "view your offer", "check your offer")):
            m_u = re.search(url_pat, sline)
            if m_u and m_u.group(1).startswith("http"):
                extracted_url = m_u.group(1)
            if not extracted_btn_text or extracted_btn_text in ("Check Offer", "Proceed"):
                if "apply" in lower_line:
                    extracted_btn_text = "Apply Now"
                elif "view" in lower_line:
                    extracted_btn_text = "View Your Offer"
                elif "check" in lower_line:
                    extracted_btn_text = "Check Offer"
                elif "explore" in lower_line:
                    extracted_btn_text = "Explore Now"

            m_dir_start = re.match(r"^\s*(?:[👉🔗▶️📍📲➡️✅]\s*)?(?:apply|click|tap)\s+below.*?(?:T\s*&\s*Cs?\s+apply|Terms)", sline, re.IGNORECASE)
            if m_dir_start:
                cleaned_lines.append("T&Cs apply")
            else:
                clean_l = re.sub(r"(?:[👉🔗▶️📍📲➡️✅]\s*)?(?:apply|click|tap|check|view|explore)\s+(?:now|online|here|below)?\s*[:\-–]?\s*https?://\S+", "", sline, flags=re.IGNORECASE)
                clean_l = re.sub(url_pat, "", clean_l)
                clean_l = re.sub(r"\s+", " ", clean_l).strip()
                if clean_l:
                    cleaned_lines.append(clean_l)
                else:
                    cleaned_lines.append("T&Cs apply")
            continue

        # 2c. Standalone tap/click directive (e.g. 'Tap below to check eligibility⬇️' or 'Tap to proceed ⬇️')
        m_dir = directive_pat.match(sline)
        if m_dir:
            action_raw = m_dir.group(1).strip()
            clean_act = re.sub(r"[⬇️👇📲👉🔗▶️\s]+$", "", action_raw).strip()
            m_u = re.search(url_pat, clean_act)
            if m_u:
                extracted_url = m_u.group(1)
                clean_act = re.sub(url_pat, "", clean_act).strip()
            if not extracted_btn_text or extracted_btn_text in ("Check Offer", "Proceed"):
                if clean_act.lower() in ("proceed", "continue"):
                    extracted_btn_text = "Proceed"
                elif "eligibility" in clean_act.lower():
                    extracted_btn_text = "Check Eligibility"
                elif "apply" in clean_act.lower():
                    extracted_btn_text = "Apply Now"
                elif "explore" in clean_act.lower():
                    extracted_btn_text = "Explore Now"
                elif "know more" in clean_act.lower():
                    extracted_btn_text = "Know More"
                elif len(clean_act) <= 25 and len(clean_act) >= 3:
                    extracted_btn_text = clean_act.title()
            if not extracted_url:
                extracted_url = DEFAULT_CTA_URL
            continue

        m_cta_var = re.match(
            r"^\s*(?:[👉🔗▶️📍📲➡️✅]\s*)?(?:CTA\s*Button|CTA|Button|Link|Apply)\s*[:\-–]?\s*(\{\{[^{}]+\}\}|\{#[^#]+#\}|\[[^\[\]]+\])\s*$",
            sline,
            re.IGNORECASE,
        )
        if m_cta_var:
            var_token = m_cta_var.group(1).strip()
            if not extracted_url or extracted_url == DEFAULT_CTA_URL:
                extracted_url = f"https://u3.mnge.co/{var_token}"
            if not extracted_btn_text or extracted_btn_text == "Check Offer":
                extracted_btn_text = "Apply Now"
            continue
        # 3. 'Tap to proceed ⬇' or 'Click to proceed' or 'Tap to apply 📲' or 'Tap to know more'
        m_tap = re.match(
            r"^\s*(?:[👉🔗▶️📍📲➡️✅]\s*)?(?:tap|click|press)\s+(?:here\s+)?(?:to\s+|on\s+)?(?:proceed|apply|continue|check|explore|avail|know\s+more|view|visit|register)\b(?:\s*[:\-–]?\s*(.*?))?(?:\s*[⬇️👇📲👉🔗▶️])?\s*$",
            sline,
            re.IGNORECASE,
        )
        if m_tap:
            tail = (m_tap.group(1) or "").strip("*_~ ")
            m_u = re.search(url_pat, tail)
            if m_u:
                extracted_url = m_u.group(1)
            elif not extracted_url or extracted_url == DEFAULT_CTA_URL:
                extracted_url = DEFAULT_CTA_URL

            if "proceed" in lower_line:
                extracted_btn_text = "Proceed"
            elif "apply" in lower_line:
                extracted_btn_text = "Apply Now"
            elif "explore" in lower_line:
                extracted_btn_text = "Explore Now"
            elif "know more" in lower_line:
                extracted_btn_text = "Know More"
            else:
                extracted_btn_text = "Apply Now"
            continue

        # 3b. Standalone emoji CTA (e.g. '👉 Apply Now' or '👉 Proceed ⬇')
        m_emoji_cta = re.match(
            r"^\s*(?:[👉🔗▶️📍📲➡️✅]\s*)+\s*(apply\s*now|proceed|check\s*offer|explore\s*now|know\s*more)\s*(?:[⬇️👇📲👉🔗▶️\s])*$",
            sline,
            re.IGNORECASE,
        )
        if m_emoji_cta:
            extracted_btn_text = m_emoji_cta.group(1).title()
            if not extracted_url or extracted_url == DEFAULT_CTA_URL:
                extracted_url = DEFAULT_CTA_URL
            continue

        # 4. Check for CTA with label and URL/variable (e.g. 'CTA: Apply Now -> https://...' or 'CTA: Apply Now (https://...)')
        m_cta_arrow = re.match(
            r"^\s*(?:[👉🔗▶️📍📲➡️✅]\s*)?(?:CTA\s*Button|CTA|Button)\s*[:\-–]?\s*(.*?)\s*(?:->|=>|–|—|\||\()\s*(https?://[^\s()]+|<link>|\{\{[^{}]+\}\}|\{#[^#]+#\})(?:\))?\s*$",
            sline,
            re.IGNORECASE,
        )
        if m_cta_arrow:
            lbl = m_cta_arrow.group(1).strip("*_~ ")
            target_val = m_cta_arrow.group(2).strip()
            if lbl and len(lbl) <= 25:
                extracted_btn_text = lbl.title()
            if target_val.startswith("http"):
                extracted_url = target_val
            elif target_val.startswith(("{", "<", "[")):
                extracted_url = f"https://u3.mnge.co/{target_val}"
            continue

        # 4. Check for CTA label only (e.g. 'CTA: Apply Now', 'CTA Button: Check Eligibility', 'Button: Explore Offers')
        m_cta_lbl = re.match(
            r"^\s*(?:[👉🔗▶️📍📲➡️✅]\s*)?(?:CTA\s*Button|CTA|Button)\s*[:\-–]\s*(.+)$",
            sline,
            re.IGNORECASE,
        )
        if m_cta_lbl:
            raw_val = m_cta_lbl.group(1).strip("*_~ ")
            m_u = re.search(url_pat, raw_val)
            if m_u:
                extracted_url = m_u.group(1)
                lbl = re.sub(url_pat, "", raw_val).strip("*_~ :-–")
                if lbl and len(lbl) <= 25:
                    extracted_btn_text = lbl.title()
            elif len(raw_val) <= 25 and not any(k in raw_val.lower() for k in ("none", "n/a", "no cta")):
                extracted_btn_text = raw_val.title()
            continue

        # 5. Check for standalone empty CTA tag
        if re.match(r"^\s*CTA\s*[:\-–]?\s*$", sline, re.IGNORECASE):
            continue

        # 6. Check for inline or standalone CTA with URL
        has_url = re.search(url_pat, sline)
        inline_m = cta_inline_pat.search(sline)
        is_url_only = bool(re.match(r"^\s*(?:" + url_pat + r")\s*$", sline))
        starts_with_cta = bool(re.match(r"^\s*(?:CTA\s*[:\-–]|CTA\s+)", sline, re.IGNORECASE))
        starts_with_emoji = bool(re.match(r"^\s*(?:[👉🔗▶️📍📲➡️✅])", sline))

        if inline_m:
            before_part = sline[: inline_m.start()].strip()
            cta_part = sline[inline_m.start() :].strip()

            if not existing_btn_url or existing_btn_url == DEFAULT_CTA_URL:
                m_url = re.search(url_pat, cta_part)
                if m_url:
                    c_url = m_url.group(1).rstrip('.,_*_`"').strip()
                    if c_url.lower() in ("<link>", "{link}", "[link]", "<url>", "{url}", "[url]"):
                        extracted_url = DEFAULT_CTA_URL
                    elif c_url.startswith("http"):
                        extracted_url = c_url

            if not existing_btn_text:
                btn_raw = re.sub(url_pat, "", cta_part)
                clean_btn = re.sub(r"[👉🔗▶️📍📲➡️✅*_\-:–|]", " ", btn_raw)
                clean_btn = re.sub(
                    r"^(?:CTA\s*|Click\s*here\s*to\s*|Tap\s*to\s*)", "", clean_btn, flags=re.IGNORECASE
                ).strip()
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

        is_standalone_cta_line = bool(
            re.match(
                r"^\s*(?:[👉🔗▶️📍📲➡️✅]\s*)?(?:\*|_)?\s*(?:CTA(?:\s*Button)?|Link|URL|Website|Portal|Apply(?:\s*Now|\s*Online)?|(?:Check|View|Claim|Explore|Avail|Get|Grab)\s*(?:Your\s+|My\s+)?Offer|Explore(?:\s*Now)?|(?:Continue|Complete|Apply|Register|Proceed)\s+(?:Here|Now|Online|Below|Ahead))\s*[:\-–]?\s*(?:\*|_)?\s*(?:"
                + url_pat
                + r")\s*$",
                sline,
                re.IGNORECASE,
            )
            or (re.match(r"^\s*(?:[👉🔗▶️📍📲➡️✅])\s*(?:" + url_pat + r")\s*$", sline) and len(sline) <= 80)
        )

        if is_url_only or is_standalone_cta_line:
            if has_url:
                c_url = has_url.group(1).rstrip('.,_*_`"').strip()
                if c_url.lower() in ("<link>", "{link}", "[link]", "<url>", "{url}", "[url]"):
                    extracted_url = DEFAULT_CTA_URL
                elif c_url.startswith("http"):
                    extracted_url = c_url
            if not existing_btn_text:
                lbl = re.sub(url_pat, "", sline)
                lbl = re.sub(r"[👉🔗▶️📍📲➡️✅*_\-:–|]", " ", lbl)
                lbl = re.sub(r"^\s*CTA(?:\s*Button)?\s*", "", lbl, flags=re.IGNORECASE).strip()
                lbl = re.sub(r"\s+", " ", lbl).strip()
                if lbl and len(lbl) <= 25 and len(lbl) >= 3:
                    extracted_btn_text = lbl.title()
            continue
        else:
            if has_url and (not extracted_url or extracted_url == DEFAULT_CTA_URL):
                c_url = has_url.group(1).rstrip('.,_*_`"').strip()
                if c_url.startswith("http"):
                    extracted_url = c_url
            cleaned_lines.append(line)

    clean_body = "\n".join(cleaned_lines)
    clean_body = re.sub(
        r"[*_]+\s*(T\s*&\s*Cs?\s+apply\.?|Terms\s*(?:and|&)\s*Conditions\s+apply\.?)\s*[*_]+",
        r"\1",
        clean_body,
        flags=re.IGNORECASE,
    )
    clean_body = re.sub(r"\n{3,}", "\n\n", clean_body).strip()
    if not clean_body and text:
        clean_body = text

    if existing_footer and existing_footer.strip():
        ef = existing_footer.strip()
        if ef.lower() not in clean_body.lower():
            clean_body = f"{clean_body}\n\n{ef}".strip()

    final_btn_text = extracted_btn_text or "Check Offer"
    final_url = extracted_url or DEFAULT_CTA_URL
    if final_url.rstrip("/") in (
        "https://www.tatacapital.com",
        "http://www.tatacapital.com",
        "https://tatacapital.com",
        "http://tatacapital.com",
        "",
    ):
        final_url = DEFAULT_CTA_URL

    return clean_body, final_btn_text, final_url, None


def is_cta_cell(val: str) -> bool:
    """Check if a cell contains a CTA link, button text, or redirect instruction."""
    if not val:
        return False
    v = val.strip().lower()
    if v.startswith(("http://", "https://", "<link>", "{link}", "[link]")):
        return True
    if v.startswith(("cta:", "cta -", "cta ", "apply:", "check:", "explore:")):
        return True
    if any(k in v for k in ["http://", "https://", "<link>"]) and any(
        c in v for c in ["apply", "check", "offer", "tap", "click"]
    ):
        return True
    return False


def split_multi_campaign_cell(text: str) -> list[str]:
    """
    Split a single spreadsheet cell into multiple separate campaign template copies
    when a copywriter placed numbered variants (e.g. 1. ... 2. ...) in one cell.
    Strips leading option numbers (e.g. '1. Hello' -> 'Hello') so templates begin
    cleanly with customer greetings.
    """
    clean = text.strip()
    if not clean:
        return []

    split_pattern = r"(?:^|\n+)(?:(?:Option|Variant|Campaign|Draft)\s*)?([1-9]\d*)[.)\-:]\s*"
    matches = list(re.finditer(split_pattern, clean, re.IGNORECASE))
    if len(matches) >= 2:
        numbers = [int(m.group(1)) for m in matches]
        if numbers == list(range(1, len(numbers) + 1)):
            parts = []
            for i, m in enumerate(matches):
                start = m.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(clean)
                segment = clean[start:end].strip()
                if len(segment) > 25:
                    parts.append(segment)
            if len(parts) >= 2:
                return parts

    m_single = re.match(
        r"^\s*(?:(?:Option|Variant|Campaign|Draft)\s*)?[1-9]\d*[.)\-:]\s*(.+)$",
        clean,
        re.DOTALL | re.IGNORECASE,
    )
    if m_single:
        return [m_single.group(1).strip()]

    return [clean]


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
            if any(
                k in first_line.lower()
                for k in [
                    "offer",
                    "festive",
                    "diwali",
                    "save",
                    "special",
                    "congratulations",
                    "upgrade",
                    "alert",
                    "notice",
                    "update",
                ]
            ):
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

    # Supreme Gemini Intelligence & Semantic Adjudication on Identified Components
    is_complete = True
    completeness_score = 1.0
    missing_components: list[str] = []
    try:
        from gemini_intelligence import analyze_template_semantics, is_internal_identifier

        if header_text and is_internal_identifier(header_text, summary=summary):
            header_text = None

        ai_res = analyze_template_semantics(
            clean_body,
            summary=summary,
            candidate_header=header_text,
            candidate_cta_text=cta_btn,
            candidate_cta_url=cta_url,
            timeout=2,
        )
        if ai_res.get("category"):
            cat = ai_res["category"]
        if ai_res.get("language") and lang == "en":
            lang = ai_res["language"]
        if (ai_res.get("is_candidate_header_genuine") is False or ai_res.get("is_internal_name") is True) and is_internal_identifier(header_text, summary=summary):
            header_text = None
        is_complete = bool(ai_res.get("is_complete", True))
        completeness_score = float(ai_res.get("completeness_score", 1.0))
        missing_components = list(ai_res.get("missing_components") or [])
    except Exception:
        pass
    var_tags = re.findall(r"\{\{(\d+)\}\}", clean_body)

    return {
        "header_text": header_text,
        "body": clean_body,
        "footer_text": None,
        "button_text": cta_btn,
        "button_url": cta_url,
        "language": lang,
        "category": cat,
        "variables": var_tags,
        "sample_values": samples[: len(var_tags)],
        "is_complete": is_complete,
        "completeness_score": completeness_score,
        "missing_components": missing_components,
    }


def _clean_template_name(base: str, channel: str, idx: int) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", base.lower()).strip("_")
    clean = re.sub(r"_+", "_", clean)
    short = clean[:26].strip("_")
    return f"{short}_{channel.lower()}_{idx}"


def derive_clean_card_title(body_text: str, account: str | None = None) -> str:
    """
    Derive card title / header title directly from the first line of the content body,
    without artificial fallback strings like 'Special Personal Loan Offer'.
    """
    if not body_text or not body_text.strip():
        return ""

    lines = [line.strip().strip("*_#~ ") for line in body_text.strip().splitlines() if line.strip()]
    if not lines:
        return ""

    first_line = lines[0]
    # Trim to 60 chars maximum (RCS card title / WhatsApp header limit)
    if len(first_line) > 60:
        first_line = first_line[:57].rstrip() + "..."

    return first_line

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
        for m in node.get("marks") or []:
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
        first_cell_lower = raw_rows[0][0].strip().lower() if raw_rows and raw_rows[0] else ""
        if "campaign execution format" in first_cell_lower:
            continue

        # Check Key-Value Campaign Metadata Tables (e.g. SWCM-61 where column 0 has metadata labels)
        first_col_keys = [r[0].lower().strip() for r in raw_rows if r and len(r) >= 1]
        is_kv_metadata = any(
            k.startswith(("campaign name", "date & time", "testing email", "testing mobile", "sftp", "database"))
            or k in ("sms text", "email text", "email html code", "wa text", "whatsapp text")
            for k in first_col_keys
        )
        if is_kv_metadata:
            kv_dict = {r[0].lower().strip(): r[1].strip() for r in raw_rows if len(r) >= 2}
            for k_prefix, chan_tag in [
                ("wa text", "WA"),
                ("whatsapp text", "WA"),
                ("wa content", "WA"),
                ("sms text", "SMS"),
                ("sms content", "SMS"),
                ("rcs text", "RCS"),
                ("rcs content", "RCS"),
                ("email text", "EMAIL"),
                ("email content", "EMAIL"),
                ("email html code", "EMAIL"),
                ("mailer copy", "EMAIL"),
            ]:
                val = kv_dict.get(k_prefix, "")
                if (
                    val
                    and val.upper() not in ("N/A", "NA", "--", "-", "ATTACHED", "NONE")
                    and is_valid_template_copy(val)
                ):
                    extracted_items.append(
                        {
                            "channel": chan_tag,
                            "text": val,
                            "variant": "General",
                            "source": "jira_adf_kv",
                        }
                    )
            continue

        # Check Pattern B (Row-based channel tags)
        start_idx = 0
        first_row = raw_rows[0]
        first_col_0 = first_row[0].strip().upper() if first_row else ""
        if first_col_0 in ("CHANNEL", "CHANNELS", "PLATFORM", "TYPE", "MEDIUM") and len(raw_rows) > 1:
            start_idx = 1
            first_col_val = raw_rows[1][0].strip().upper() if raw_rows[1] else ""
        else:
            first_col_val = first_col_0

        is_row_based = (
            first_col_val in ("SMS", "WA", "RCS", "WHATSAPP", "EMAIL", "MAIL", "MAILER", "PUSH", "APN")
            and len(raw_rows[start_idx]) >= 2
        )

        if is_row_based:
            for r in raw_rows[start_idx:]:
                if len(r) >= 2:
                    chan_raw = r[0].strip().upper()
                    if chan_raw in ("WA", "WHATSAPP"):
                        chan_tag = "WA"
                    elif chan_raw in ("EMAIL", "MAIL", "MAILER"):
                        chan_tag = "EMAIL"
                    elif chan_raw in ("PUSH", "APN"):
                        chan_tag = "PUSH"
                    else:
                        chan_tag = chan_raw
                    body_content = r[1].strip()
                    if body_content and len(body_content) > 10 and is_valid_template_copy(body_content):
                        extracted_items.append(
                            {
                                "channel": chan_tag,
                                "text": body_content,
                                "variant": "General",
                                "source": "jira_adf",
                            }
                        )
            continue
        # Pattern A (Columnar headers in row 0)
        if len(raw_rows) >= 2:
            header_cells = raw_rows[0]
            for r in raw_rows[1:]:
                for col_idx, cell_val in enumerate(r):
                    if col_idx < len(header_cells):
                        header_name = header_cells[col_idx]
                        if header_name and cell_val and len(cell_val) > 10 and not cell_val.isdigit():
                            header_lower = header_name.lower().strip()
                            # Word boundary match to avoid substrings like 'awarness' matching 'wa'
                            if re.search(r"\b(wa|whatsapp)\b", header_lower):
                                chan_type = "WA"
                            elif re.search(r"\b(rcs)\b", header_lower):
                                chan_type = "RCS"
                            elif re.search(r"\b(sms)\b", header_lower):
                                chan_type = "SMS"
                            elif re.search(r"\b(email|mailer|mail)\b", header_lower):
                                chan_type = "EMAIL"
                            elif re.search(r"\b(push|apn)\b", header_lower):
                                chan_type = "PUSH"
                            else:
                                continue

                            # Every extracted template body must pass strict template validation
                            if not is_valid_template_copy(cell_val):
                                continue

                            variant_label = (
                                "Retargeting"
                                if "retarget" in header_lower
                                else ("Non clicker" if "non" in header_lower else "General")
                            )
                            extracted_items.append(
                                {
                                    "channel": chan_type,
                                    "text": cell_val,
                                    "variant": variant_label,
                                    "source": "jira_adf",
                                }
                            )

    return extracted_items


def _extract_kv_metadata_from_adf_or_text(
    adf_doc: dict[str, Any] | None, desc_text: str
) -> dict[str, Any]:
    """Extract structured campaign metadata table (e.g. SWCM-105 / SWCM-61 key-value tables)."""
    meta: dict[str, Any] = {}
    raw_pairs: list[tuple[str, str]] = []

    if adf_doc:
        for tbl in _find_adf_tables(adf_doc):
            rows = tbl.get("content", [])
            for r in rows:
                cells = [_extract_text_from_adf_node(c).strip() for c in r.get("content", [])]
                if len(cells) >= 2 and cells[0] and cells[1]:
                    raw_pairs.append((cells[0], cells[1]))

    if not raw_pairs and desc_text:
        for line in desc_text.splitlines():
            if "|" in line:
                parts = [p.strip() for p in line.split("|", 1)]
                if len(parts) == 2 and parts[0] and parts[1]:
                    raw_pairs.append((parts[0], parts[1]))

    for key_raw, val_raw in raw_pairs:
        k = key_raw.lower().strip()
        v = val_raw.strip()
        if not v or v.upper() in ("N/A", "NA", "--", "-", "NONE"):
            continue

        if k == "campaign name":
            meta["campaign_name"] = v
        elif k in ("date & time of execution", "date & time", "date and time of execution", "date and time"):
            meta["execution_date_raw"] = v
            from moengage_preview import parse_jira_execution_datetime

            parsed_dt = parse_jira_execution_datetime(v)
            if parsed_dt:
                meta["scheduled_at"] = parsed_dt
                meta["timezone"] = "Asia/Kolkata"
        elif k in ("email text", "email content", "mailer text"):
            subj_m = re.search(r"subject\s*:\s*(.+)", v, re.IGNORECASE)
            if subj_m:
                meta["email_subject"] = subj_m.group(1).splitlines()[0].strip()
            preheader_m = re.search(r"pre-?header\s*:\s*(.+)", v, re.IGNORECASE)
            if preheader_m:
                meta["email_preheader"] = preheader_m.group(1).splitlines()[0].strip()
        elif k in ("subject", "email subject", "mail subject"):
            meta["email_subject"] = v
        elif k in ("database", "database path", "sftp path", "base path"):
            meta["database_source"] = v
        elif k in ("testing email id :", "testing email", "testing email id", "test email"):
            meta["testing_email"] = v
        elif k in ("campaign tag", "campaign type", "tag"):
            meta["campaign_tag"] = v
        elif k == "product":
            meta["product"] = v
        elif k == "sub product":
            meta["sub_product"] = v
        elif k in ("from email", "from address", "sender email"):
            meta["from_address"] = v

    return meta


# ---------------------------------------------------------------------------
# Excel Spreadsheet Extraction Engine
# ---------------------------------------------------------------------------
MONTH_NAMES = {
    "jan": "jan",
    "january": "jan",
    "feb": "feb",
    "february": "feb",
    "mar": "mar",
    "march": "mar",
    "apr": "apr",
    "april": "apr",
    "may": "may",
    "jun": "jun",
    "june": "jun",
    "jul": "jul",
    "july": "jul",
    "aug": "aug",
    "august": "aug",
    "sep": "sep",
    "sept": "sep",
    "september": "sep",
    "oct": "oct",
    "october": "oct",
    "nov": "nov",
    "november": "nov",
    "dec": "dec",
    "december": "dec",
}

SKIP_SHEET_KEYWORDS = [
    "planner",
    "schedule",
    "calendar",
    "base count",
    "tracking",
    "summary",
    "exclusion",
    "report",
    "metrics",
    "decile",
    "overview",
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
        r"^\s*(?:[👉🔗▶️📍📲➡️✅]\s*)?(?:CTA\s*[:\-–]?\s*|check\s+(?:your\s+|my\s+)?offer|apply\s*(?:now|online|here)?|explore\s*(?:more|now|offer)?|tap\s*(?:here|to\s+save\s+more|now)?|click\s*(?:here|to\s+apply)?|visit\s*(?:now|us)?|view\s*offer|avail\s*now)[\s:\-–]*(?:"
        + url_pat
        + r")?\s*$",
        text,
        re.IGNORECASE,
    ):
        return True
    return False


def is_valid_template_copy(text: str) -> bool:
    """
    Validate that a spreadsheet cell contains genuine customer-facing template copy,
    rejecting audience targeting criteria, cohort descriptions, tracking codes,
    operational notes, counts, and metadata.
    """
    if not text:
        return False
    s = text.strip()
    if len(s) < 25:
        return False

    # 0. Reject pure CTA button cells (they are buttons, not message bodies)
    if is_pure_cta_cell(s):
        return False

    s_low = s.lower()

    # 1. Reject internal tracking codes / campaign IDs (e.g. TCLMOE_..., PAPL_..., etc.)
    if "\n" not in s and re.match(r"^(?:TCLMOE|TCL|PAPL|PQPL|UCL|TCF|MOE|SEG)_[A-Za-z0-9_\'-]+$", s, re.IGNORECASE):
        return False

    # 2. Reject audience targeting criteria, cohort names, exclusion lists, and caps
    targeting_markers = (
        "non clicker", "non-clicker", "non clickers", "non-clickers", "non click", "non-click",
        "non opener", "non-opener", "non openers", "non-openers", "openers", "opener",
        "regional dnd", "utility regional", "non dnd", "dnd &", "dnd +",
        "app users", "web users", "app user", "web user",
        "previous rounds", "previous round", "past 60 days", "past 30 days", "past 90 days",
        "last 60 days", "last 30 days", "last 90 days",
        "capping", "exclusion list", "suppression", "target base", "base seg",
        "segment count", "segment name", "cohort", "dnd & non clicker", "dnd + non clicker",
        "tourism day users", "non clickers of", "non-clickers of", "openers of",
    )
    if any(m in s_low for m in targeting_markers):
        return False

    # Reject parenthetical exclusion syntax e.g. "( exclude ... )" or "( remove ... )"
    if re.search(r"\(\s*(?:exclude|remove|capping)\b", s_low):
        return False

    # 3. Reject internal operational notes, file manifests, and count tables
    if any(
        p in s_low
        for p in [
            "campaign name |",
            "sftp path",
            "date & time of execution",
            "testing email",
            "testing mobile",
            "short |",
            "segment count",
            "grand total",
            "dob column",
            "below files",
            "pls release",
            "please release",
            "exclusion list",
            "date & time",
            "campaign execution",
            "channel name",
            "content format",
        ]
    ):
        return False

    # 4. Reject pipe-separated database / tracking headers
    if "|" in s and ("created_at" in s_low or "valid_until" in s_low or "grand total" in s_low):
        return False

    # 5. Reject section headers that masquerade as copy
    if "\n" not in s and len(s) < 60:
        if any(
            h in s_low
            for h in ["wholebase", "automation", "normal term loan", "utility messages", "planner", "schedule"]
        ):
            return False

    # 6. Word count validation:
    # Candidate templates under 25 words are rejected UNLESS they start with an explicit
    # customer greeting ("Dear ...", "Hi ...", "Hey ...") AND contain genuine banking/loan offers.
    words = s.split()
    has_greeting = bool(re.search(r"\b(dear|hi|hello|hey|namaste|congratulations)\b", s_low))
    has_placeholder = bool(re.search(r"(\{\{|\<|\[|#\{#[^#]+#\}#|\{#[^#]+#\}|\{[a-zA-Z0-9_\-\s]+\})", s))
    has_link = bool(re.search(r"(?:https?://|www\.|<link>|u3\.mnge\.co)", s_low))
    has_structured = ("body:" in s_low) or ("title:" in s_low)
    has_brand = ("tata capital" in s_low) or ("tatacapital" in s_low) or ("bajaj" in s_low)
    has_action_offer = bool(re.search(r"\b(apply|get|enjoy|switch|transfer|repay|check)\b", s_low)) and bool(
        re.search(r"\b(loan|loans|emi|emis|fund|funds|interest|offer|offers)\b", s_low)
    )

    has_customer_offer = bool(
        re.search(
            r"\b(loan|loans|emi|emis|offer|offers|interest|apply|pay|disburs|pre-approved|approved|card|account|tenure|roi|funds?)\b|"
            r"(?:₹|rs\.?\s*\d+|inr\s*\d+)",
            s_low,
        )
    )
    if len(words) < 25:
        valid_feature = (
            has_greeting
            or has_placeholder
            or has_link
            or has_structured
            or (has_brand and has_customer_offer)
            or has_action_offer
        )
        if not valid_feature:
            return False
        if not has_customer_offer:
            return False

    # Must contain at least 4 whitespace-separated words in any case
    if len(words) < 4:
        return False

    # 7. Must contain human customer messaging vocabulary or placeholders
    has_placeholder = bool(re.search(r"(\{\{|\<|\[|#\{#[^#]+#\}#|\{#[^#]+#\}|\{[a-zA-Z0-9_\-\s]+\})", s))
    has_messaging_keywords = bool(
        re.search(
            r"\b(loan|loans|offer|offers|tata|capital|emi|emis|interest|rate|roi|apply|pay|"
            r"lakh|lakhs|lacs|crore|card|cards|account|disbursal|bank|due|cashback|voucher|"
            r"disclaimer|t&c|terms|benefit|benefits|saving|savings|travel|trip|holiday|"
            r"upgrade|repayment|debt|debts|eligibility|pre-approved|approved|instant|quick|flexible)\b|"
            r"(?:₹|rs\.?\s*\d+|inr\s*\d+)",
            s_low,
        )
    )

    return has_placeholder or has_greeting or has_messaging_keywords


def _normalize_channel_tag(tag: str) -> str | None:
    """Normalize any string (e.g. 'WhatsApp', 'WA', 'RCS', 'SMS Promotional') to canonical channel."""
    if not tag:
        return None
    s_str = str(tag).strip()
    # Channel tags are concise labels (e.g. 'WA', 'RCS', 'WhatsApp Content').
    # Reject full cohort sentences like 'WA Utility Regional DND + Non Clickers...'.
    if len(s_str.split()) > 4 or len(s_str) > 30:
        return None
    t = re.sub(r"[^a-zA-Z0-9]", " ", s_str).upper()
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
                with open(filepath, encoding=enc, errors="replace") as f:
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
                row_vals: list[str] = []
                for c in range(1, ws.max_column + 1):
                    cell = ws.cell(row=r, column=c)
                    val = str(cell.value or "").strip()
                    if cell.hyperlink and cell.hyperlink.target:
                        target = str(cell.hyperlink.target).strip()
                        if target and target.startswith("http") and not val.startswith("http"):
                            val = f"{val} ({target})" if val else target
                    row_vals.append(val)
                if any(row_vals):
                    rows.append(row_vals)
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


def _is_targeting_or_planner_row(row: list[str]) -> bool:
    """Detect if a row is describing audience targeting cohorts rather than creative copy."""
    row_text = " ".join(row).lower()
    targeting_markers = (
        "non clicker", "non-clicker", "non clickers", "non-clickers", "non click", "non-click",
        "non opener", "non-opener", "non openers", "non-openers", "openers", "opener",
        "regional dnd", "utility regional", "non dnd", "app users", "web users",
        "previous rounds", "previous round", "past 60 days", "past 30 days", "past 90 days",
        "last 60 days", "last 30 days", "last 90 days",
        "capping", "exclusion list", "suppression", "target base", "base seg",
        "segment name", "cohort", "dnd & non clicker", "dnd + non clicker",
        "tourism day users", "non clickers of", "non-clickers of", "openers of",
    )
    return any(marker in row_text for marker in targeting_markers)
def _identify_sheet_columns(header_row: list[str]) -> dict[str, Any]:
    """
    Robustly identify column indexes for any client spreadsheet header row.
    Handles space-separated, underscore-separated, and uppercase/lowercase variations.
    """
    headers = [re.sub(r"[\s_]+", " ", str(h or "").lower()).strip() for h in header_row]
    mapping: dict[str, Any] = {}

    for idx, h in enumerate(headers):
        if not h:
            continue

        # 1. URL / Link column (checked first to prevent collisions with button text)
        if any(k in h for k in ["button url", "cta url", "cta link", "destination url", "landing page", "target url", "btn url", "button link"]):
            mapping.setdefault("button_url", idx)
        elif h in ("url", "link", "website") or (("url" in h or "link" in h) and not any(k in h for k in ["text", "type", "name", "header", "media", "image", "creative"])):
            mapping.setdefault("button_url", idx)

        # 2. Button Type
        if any(k in h for k in ["button type", "btn type", "action type", "cta type"]):
            mapping.setdefault("button_type", idx)

        # 3. Button Text / CTA Label
        if any(k in h for k in ["button text", "cta text", "cta button", "button label", "btn text", "action label", "cta label", "button name"]):
            mapping.setdefault("button_text", idx)
        elif h in ("cta", "button", "action") or (("cta" in h or "button" in h) and not any(k in h for k in ["url", "link", "type"])):
            mapping.setdefault("button_text", idx)

        # 4. Header Type
        if any(k in h for k in ["header type", "media type"]):
            mapping.setdefault("header_type", idx)

        # 5. Header Text / Title
        if any(k in h for k in ["header text", "card title", "headline", "heading"]):
            mapping.setdefault("header", idx)
        elif h in ("header", "title") or (("header" in h or "title" in h) and "type" not in h and "url" not in h and "link" not in h):
            mapping.setdefault("header", idx)

        # 6. Footer Text
        if any(k in h for k in ["footer", "footer text", "disclaimer"]):
            mapping.setdefault("footer", idx)

        # 7. Category
        if any(k in h for k in ["category", "template category", "waba category"]):
            mapping.setdefault("category", idx)

        # 8. Media / Creative URL
        if any(k in h for k in ["media url", "image url", "creative url", "image link", "media link"]):
            mapping.setdefault("media_url", idx)
        elif h in ("media", "image", "creative"):
            mapping.setdefault("media_url", idx)

        # 9. Language
        if h in ("language", "lang"):
            mapping.setdefault("language", idx)

        # 10. Channel
        if h in ("channel", "channel name", "platform", "medium", "mode"):
            mapping.setdefault("channel", idx)

        # 11. Template Name / ID
        if any(k in h for k in ["template name", "template id", "waba name", "waba template", "template code", "template title"]):
            mapping.setdefault("template_name", idx)
        elif h in ("template", "name") and "channel" not in h:
            mapping.setdefault("template_name", idx)

    # 12. Content / Copy columns (can be multiple, e.g. multi-channel or multilingual)
    content_cols: list[int] = []
    claimed_indices = set(mapping.values())
    for idx, h in enumerate(headers):
        if idx in claimed_indices:
            continue
        if any(k in h for k in ["body", "content", "copy", "message", "text", "communication", "whatsapp", "sms", "rcs", "english", "hindi"]):
            if not any(k in h for k in ["header", "footer", "button", "cta", "url", "link", "type", "channel", "name", "id"]):
                content_cols.append(idx)
        elif not mapping and ("copy" in h or "content" in h or "message" in h or "text" in h):
            content_cols.append(idx)

    mapping["content_cols"] = content_cols
    return mapping
def _parse_raw_sheet_rows(raw_rows: list[list[str]], sname: str, sheet_images: list[str] | None = None) -> list[dict[str, Any]]:
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

    # 1. Detect candidate header row index
    def _is_real_header_row(row: list[str]) -> bool:
        if not row:
            return False
        if any(len(str(c or "").strip()) > 60 for c in row):
            return False
        header_keywords = ("channel", "content", "body", "copy", "template", "message", "text", "header", "button", "cta", "url", "category", "footer", "status", "date")
        row_low = " ".join(str(c or "").lower() for c in row)
        return any(k in row_low for k in header_keywords)

    header_row_idx = None
    for r_idx, row in enumerate(raw_rows[:5]):
        if _is_real_header_row(row):
            header_row_idx = r_idx
            break

    if header_row_idx is None:
        chan_tags_in_col0 = sum(1 for row in raw_rows if row and _normalize_channel_tag(row[0]) is not None)
        if chan_tags_in_col0 >= 1:
            chan_col_idx = 0
            has_columnar_structure = True
            start_idx = 0 if _normalize_channel_tag(raw_rows[0][0]) is not None else 1
            content_cols = [
                c_idx
                for c_idx in range(1, max(len(r) for r in raw_rows))
                if any(len(str(r[c_idx] or "")) > 25 for r in raw_rows if c_idx < len(r))
            ]
            header_row = []
            col_map = {"channel": 0, "content_cols": content_cols}
            template_name_col_idx = None
            header_col_idx = None
            header_type_col_idx = None
            footer_col_idx = None
            btn_text_col_idx = None
            btn_url_col_idx = None
            btn_type_col_idx = None
            category_col_idx = None
            media_url_col_idx = None
            language_col_idx = None
        else:
            header_row = []
            col_map = {}
            chan_col_idx = None
            template_name_col_idx = None
            header_col_idx = None
            header_type_col_idx = None
            footer_col_idx = None
            btn_text_col_idx = None
            btn_url_col_idx = None
            btn_type_col_idx = None
            category_col_idx = None
            media_url_col_idx = None
            language_col_idx = None
            content_cols = []
            has_columnar_structure = False
            start_idx = len(raw_rows)
    else:
        header_row = [str(c or "").strip() for c in raw_rows[header_row_idx]]
        col_map = _identify_sheet_columns(header_row) if header_row else {}
        chan_col_idx = col_map.get("channel")
        template_name_col_idx = col_map.get("template_name")
        header_col_idx = col_map.get("header")
        header_type_col_idx = col_map.get("header_type")
        footer_col_idx = col_map.get("footer")
        btn_text_col_idx = col_map.get("button_text")
        btn_url_col_idx = col_map.get("button_url")
        btn_type_col_idx = col_map.get("button_type")
        category_col_idx = col_map.get("category")
        media_url_col_idx = col_map.get("media_url")
        language_col_idx = col_map.get("language")
        content_cols = col_map.get("content_cols", [])
        has_columnar_structure = bool(any(col_map.values()) or chan_col_idx is not None)
        start_idx = (header_row_idx + 1) if has_columnar_structure else len(raw_rows)
    current_channel = sheet_chan

    targeting_header_keywords = (
        "segment", "targeting", "cohort", "audience", "volume", "capping", "dnd",
        "exclusion", "criteria", "sftp", "remarks", "comments", "planner", "schedule", "execution",
    )
    targeting_col_indices = {
        idx for idx, h in enumerate(header_row) if any(th in str(h).lower() for th in targeting_header_keywords)
    }
    for r_num, row in enumerate(raw_rows[start_idx:], start=start_idx + 1):
        # Skip rows describing audience targeting cohorts rather than creative copy
        if _is_targeting_or_planner_row(row):
            continue

        # 1. Section header (only when ALL cells are short and no long copy exists)
        has_long_copy = any(len(c) > 25 for c in row)
        if not has_long_copy:
            for cell in row:
                c_norm = _normalize_channel_tag(cell)
                if c_norm and any(
                    k in cell.lower()
                    for k in ["promotional", "retargeting", "utility", "content", "whatsapp", "sms", "rcs", "email"]
                ):
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

        # Skip header rows repeated mid-sheet
        row_joined = " ".join(row).lower()
        if any(h in row_joined for h in ["created_at", "valid_until", "tracking_id"]):
            if not any(len(cell) > 40 for cell in row):
                continue

        # 3. Extract content columns
        target_cols = content_cols if content_cols else [c_idx for c_idx in range(len(row))]
        skip_indices = {chan_col_idx, template_name_col_idx, header_col_idx, header_type_col_idx, footer_col_idx, btn_text_col_idx, btn_url_col_idx, btn_type_col_idx, category_col_idx, media_url_col_idx, language_col_idx}
        skip_indices.discard(None)
        skip_indices.update(targeting_col_indices)

        for c_idx in target_cols:
            if c_idx in skip_indices and content_cols:
                continue
            if c_idx >= len(row):
                continue
            body_val = row[c_idx].strip()
            if not is_valid_template_copy(body_val):
                continue

            # Determine specific channel for this column if applicable
            col_hdr = header_row[c_idx] if c_idx < len(header_row) else ""
            item_chan = _normalize_channel_tag(col_hdr) or active_chan or ("WA" if _normalize_channel_tag(sname) is None else _normalize_channel_tag(sname))

            base_variant = "General"
            if row and row[0] and row[0].lower().startswith("c") and len(row[0]) < 10:
                base_variant = row[0].upper()
            elif col_hdr and col_hdr not in ("content", "message", "copy", "text", "body"):
                base_variant = col_hdr.title()

            copies = split_multi_campaign_cell(body_val)
            for copy_idx, copy_text in enumerate(copies):
                variant = base_variant if len(copies) == 1 else f"{base_variant} (Option {copy_idx + 1})"
                item_dict: dict[str, Any] = {
                    "channel": item_chan,
                    "text": copy_text,
                    "raw_text": copy_text,
                    "variant": variant,
                    "source": f"excel_{sname}_r{r_num}_c{c_idx + 1}" + (f"_opt_{copy_idx + 1}" if len(copies) > 1 else ""),
                }
                if sheet_images:
                    img_path = sheet_images[copy_idx % len(sheet_images)]
                    item_dict["media_file"] = img_path
                    item_dict["media_filename"] = Path(img_path).name
                if template_name_col_idx is not None and template_name_col_idx < len(row) and row[template_name_col_idx]:
                    item_dict["template_name"] = row[template_name_col_idx].strip()
                if header_col_idx is not None and header_col_idx < len(row) and row[header_col_idx]:
                    item_dict["header"] = row[header_col_idx].strip()
                if header_type_col_idx is not None and header_type_col_idx < len(row) and row[header_type_col_idx]:
                    item_dict["header_type"] = row[header_type_col_idx].strip().upper()
                if footer_col_idx is not None and footer_col_idx < len(row) and row[footer_col_idx]:
                    item_dict["footer"] = row[footer_col_idx].strip()
                if btn_text_col_idx is not None and btn_text_col_idx < len(row) and row[btn_text_col_idx]:
                    item_dict["button_text"] = row[btn_text_col_idx].strip()
                if btn_url_col_idx is not None and btn_url_col_idx < len(row) and row[btn_url_col_idx]:
                    item_dict["button_url"] = row[btn_url_col_idx].strip()
                if btn_type_col_idx is not None and btn_type_col_idx < len(row) and row[btn_type_col_idx]:
                    item_dict["button_type"] = row[btn_type_col_idx].strip().upper()
                if category_col_idx is not None and category_col_idx < len(row) and row[category_col_idx]:
                    item_dict["category"] = row[category_col_idx].strip().upper()
                if media_url_col_idx is not None and media_url_col_idx < len(row) and row[media_url_col_idx]:
                    item_dict["media_url"] = row[media_url_col_idx].strip()
                if language_col_idx is not None and language_col_idx < len(row) and row[language_col_idx]:
                    item_dict["language"] = row[language_col_idx].strip()

                if "Title:" in copy_text and "Body:" in copy_text:
                    title_m = re.search(r"Title:\s*([^\n]+)", copy_text)
                    body_m = re.search(r"Body:?\s*(.*?)(?:CTA:|$)", copy_text, re.DOTALL)
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
                elif (
                    r_idx + 1 < len(raw_rows)
                    and c_idx < len(raw_rows[r_idx + 1])
                    and is_pure_cta_cell(raw_rows[r_idx + 1][c_idx])
                ):
                    neighbor_cta = raw_rows[r_idx + 1][c_idx]
                    consumed_coords.add((r_idx + 1, c_idx))

                # Look up for neighbor header
                if r_idx > 0 and c_idx < len(raw_rows[r_idx - 1]):
                    top_c = raw_rows[r_idx - 1][c_idx].strip()
                    from gemini_intelligence import is_internal_identifier

                    if (
                        3 < len(top_c) < 45
                        and not is_cta_cell(top_c)
                        and not is_valid_template_copy(top_c)
                        and not is_internal_identifier(top_c, sheet_name=sname)
                    ):
                        neighbor_header = top_c
                copies = split_multi_campaign_cell(clean_cell)
                for copy_idx, copy_text in enumerate(copies):
                    decomp = decompose_content(
                        copy_text,
                        explicit_header=neighbor_header,
                        neighbor_cta=neighbor_cta,
                    )

                    row_chan = _normalize_channel_tag(row[0]) if (row and row[0]) else None
                    item_dict = {
                        "channel": sheet_chan or row_chan or ("RCS" if decomp.get("header_text") else "WA"),
                        "text": decomp["body"],
                        "header": decomp["header_text"],
                        "footer": decomp["footer_text"],
                        "button_text": decomp["button_text"],
                        "button_url": decomp["button_url"],
                        "variant": f"Cell_{r_idx + 1}_{c_idx + 1}" + (f"_opt_{copy_idx + 1}" if len(copies) > 1 else ""),
                        "source": f"excel_spatial_{sname}_r{r_idx + 1}_c{c_idx + 1}",
                    }
                    if sheet_images:
                        img_path = sheet_images[copy_idx % len(sheet_images)]
                        item_dict["media_file"] = img_path
                        item_dict["media_filename"] = Path(img_path).name
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
                    items.append(
                        {
                            "channel": channel,
                            "text": combined,
                            "variant": variant_label,
                            "source": f"excel_grid_{sheet_name}",
                        }
                    )
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
                    items.append(
                        {
                            "channel": "RCS",
                            "text": body,
                            "title": title,
                            "variant": "App Downloads",
                            "source": f"excel_block_{sname}",
                        }
                    )

    return items


def _is_dlt_sms_sheet(raw_rows: list[list[str]], filename: str = "") -> bool:
    """Detect if an Excel spreadsheet is an official DLT SMS template export."""
    if not raw_rows or len(raw_rows) < 2:
        return False
    header_row = [str(c or "").strip().upper() for c in raw_rows[0]]
    if "TEMPLATE ID" in header_row and ("TEMPLATE MESSAGE" in header_row or "REGISTERED DLT" in header_row):
        return True
    if "sms" in filename.lower() and "TEMPLATE MESSAGE" in header_row:
        return True
    return False


def _parse_dlt_sms_sheet(raw_rows: list[list[str]], sname: str, filename: str = "") -> list[dict[str, str]]:
    """Parse official DLT SMS template spreadsheet rows into canonical SMS template dicts."""
    header_row = [str(c or "").strip().upper() for c in raw_rows[0]]
    msg_idx = header_row.index("TEMPLATE MESSAGE") if "TEMPLATE MESSAGE" in header_row else None
    name_idx = header_row.index("TEMPLATE NAME") if "TEMPLATE NAME" in header_row else None
    id_idx = header_row.index("TEMPLATE ID") if "TEMPLATE ID" in header_row else None
    header_idx = header_row.index("HEADER") if "HEADER" in header_row else None
    cat_idx = header_row.index("CATEGORY") if "CATEGORY" in header_row else None

    items = []
    for r in raw_rows[1:]:
        if msg_idx is not None and msg_idx < len(r) and r[msg_idx]:
            msg = str(r[msg_idx]).strip()
            if not msg or not is_valid_template_copy(msg):
                continue
            tname = str(r[name_idx]).strip() if name_idx is not None and name_idx < len(r) and r[name_idx] else ""
            tid = str(r[id_idx]).strip().strip("'") if id_idx is not None and id_idx < len(r) and r[id_idx] else ""
            h_val = (
                str(r[header_idx]).strip() if header_idx is not None and header_idx < len(r) and r[header_idx] else ""
            )
            cat_val = str(r[cat_idx]).strip() if cat_idx is not None and cat_idx < len(r) and r[cat_idx] else "General"
            items.append(
                {
                    "channel": "SMS",
                    "text": msg,
                    "header": h_val or None,
                    "template_name": tname,
                    "dlt_template_id": tid,
                    "variant": cat_val,
                    "source": f"dlt_sms_{sname}",
                }
            )
    return items


def extract_templates_from_docx_file(docx_path: str | Path) -> list[dict[str, Any]]:
    """
    Extract multi-channel customer communications (WhatsApp, SMS, Email) from Word documents (.docx).
    Handles client communication briefs segmented by customer tiers (e.g. '1. Customers at or below 50% LTV...').
    Identifies genuine customer-facing headlines for WhatsApp templates.
    """
    paras: list[str] = []

    # 1. Try python-docx if installed
    try:
        import docx

        doc = docx.Document(docx_path)
        paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    except Exception:
        paras = []

    # 2. Robust zero-dependency fallback using built-in zipfile + XML
    if not paras:
        try:
            import xml.etree.ElementTree as ET  # nosec B405  # nosemgrep
            import zipfile

            with zipfile.ZipFile(docx_path) as z:
                xml_content = z.read("word/document.xml")
            tree = ET.fromstring(xml_content)  # nosec B314  # nosemgrep
            for p in tree.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                texts = [
                    node.text
                    for node in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
                    if node.text
                ]
                if texts:
                    clean_p = "".join(texts).strip()
                    if clean_p:
                        paras.append(clean_p)
        except Exception as exc:
            logger.warning("Failed to parse docx %s with stdlib XML parser: %s", docx_path, exc)
            return []
    items: list[dict[str, Any]] = []
    channel_blocks: list[dict[str, Any]] = []
    curr_block: dict[str, Any] = {"channel": None, "tier": "General", "lines": []}
    chan_names = {
        "whatsapp": "WA", "wa": "WA", "sms": "SMS", "email": "EMAIL", "rcs": "RCS",
        "pn": "PN", "push": "PN", "push notification": "PN"
    }

    for p in paras:
        clean_p = p.strip()
        low = clean_p.lower()
        norm_chan = re.sub(r"[\s\-–—:]+$", "", low).strip()

        # Check tier header (e.g. 1. Customers at or below 50% LTV...)
        if re.match(r"^\d+\.\s+Customers?", p, re.IGNORECASE):
            if curr_block["channel"] and curr_block["lines"]:
                channel_blocks.append(curr_block)
            curr_block = {"channel": None, "tier": p, "lines": []}
            continue

        if norm_chan in chan_names:
            if curr_block["channel"] and curr_block["lines"]:
                channel_blocks.append(curr_block)
            curr_block = {"channel": chan_names[norm_chan], "tier": curr_block.get("tier", "General"), "lines": []}
            continue

        # Handle section headers like 'Content to Referrer–', 'Not Contactable –'
        if clean_p.endswith(("-", "–", "—", ":")) and len(clean_p) < 40 and not any(k in low for k in ("t&c", "link", "tatacapital", "dear", "hello", "hi")):
            curr_block["tier"] = clean_p.rstrip("-–—: ").strip()
            continue

        if curr_block["channel"]:
            curr_block["lines"].append(clean_p)

    if curr_block["channel"] and curr_block["lines"]:
        channel_blocks.append(curr_block)

    for b in channel_blocks:
        chan = b["channel"]
        lines = b["lines"]
        tier = b["tier"]
        if not lines:
            continue
        header = None
        if chan == "WA":
            current_wa: list[str] = []
            for line in lines:
                is_new_wa = bool(
                    re.match(r"^(?:dear|hi|hello|hey|namaste)\b", line.lower())
                    and current_wa and len("\n".join(current_wa)) > 60
                )
                if is_new_wa and current_wa:
                    combined = "\n".join(current_wa).strip()
                    if is_valid_template_copy(combined):
                        decomp = decompose_content(combined)
                        items.append({
                            "channel": "WA",
                            "header": decomp["header_text"],
                            "text": decomp["body"],
                            "button_text": decomp["button_text"],
                            "button_url": decomp["button_url"],
                            "variant": tier,
                            "source": f"docx_{Path(docx_path).stem}",
                        })
                    current_wa = [line]
                else:
                    current_wa.append(line)
            if current_wa:
                combined = "\n".join(current_wa).strip()
                if is_valid_template_copy(combined):
                    decomp = decompose_content(combined)
                    items.append({
                        "channel": "WA",
                        "header": decomp["header_text"],
                        "text": decomp["body"],
                        "button_text": decomp["button_text"],
                        "button_url": decomp["button_url"],
                        "variant": tier,
                        "source": f"docx_{Path(docx_path).stem}",
                    })
        elif chan == "SMS":
            current_sms: list[str] = []
            for line in lines:
                is_new_message = bool(
                    re.match(r"^(?:dear|hi|hello|hey|know someone|you have been|up to|unexpected|more orders|urgent)\b", line.lower())
                    or (current_sms and len("\n".join(current_sms)) > 150)
                )
                if is_new_message and current_sms:
                    combined = "\n".join(current_sms).strip()
                    if is_valid_template_copy(combined):
                        items.append({
                            "channel": "SMS",
                            "header": None,
                            "text": combined,
                            "variant": tier,
                            "source": f"docx_{Path(docx_path).stem}",
                        })
                    current_sms = [line]
                else:
                    current_sms.append(line)
            if current_sms:
                combined = "\n".join(current_sms).strip()
                if is_valid_template_copy(combined):
                    items.append({
                        "channel": "SMS",
                        "header": None,
                        "text": combined,
                        "variant": tier,
                        "source": f"docx_{Path(docx_path).stem}",
                    })
        elif chan in ("PN", "PUSH"):
            for line in lines:
                if len(line) >= 15:
                    items.append({
                        "channel": "PN",
                        "header": line,
                        "text": line,
                        "variant": tier,
                        "source": f"docx_{Path(docx_path).stem}",
                    })
        elif chan == "EMAIL":
            subject = None
            body_lines = []
            for l in lines:
                if l.lower().startswith("subject:"):
                    subject = l.split(":", 1)[1].strip()
                else:
                    body_lines.append(l)
            items.append({
                "channel": "EMAIL",
                "header": subject,
                "text": "\n".join(body_lines),
                "variant": tier,
                "source": f"docx_{Path(docx_path).stem}",
            })

    return items


def extract_templates_from_excel_file(
    filepath: Path,
    target_month: str | None = None,
    sheet_images_map: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """
    Inspect and extract template items from any client spreadsheet (.xlsx, .csv, .xls) across all sheets.
    Combines channel-tagged tables, section headers, grid messages, and key-value blocks.
    Filters out historical past-month sheets and administrative planner sheets.
    Deduplicates identical templates so multi-sheet workbooks don't produce duplicate cards.
    """
    sheets = _load_spreadsheet_sheets(filepath)
    if not sheets:
        return []

    if sheet_images_map is None and filepath.suffix.lower() == ".xlsx":
        sheet_images_map = _extract_images_from_xlsx(filepath)

    all_items: list[dict[str, Any]] = []
    seen_texts: set[str] = set()

    for sname, raw_rows in sheets.items():
        if should_skip_sheet(sname, target_month=target_month):
            continue
        sheet_imgs = (sheet_images_map or {}).get(sname, [])
        if _is_dlt_sms_sheet(raw_rows, filename=filepath.name):
            sheet_items = _parse_dlt_sms_sheet(raw_rows, sname, filename=filepath.name)
        else:
            sheet_items = _parse_raw_sheet_rows(raw_rows, sname, sheet_images=sheet_imgs)
        is_carousel_sheet = "carousal" in sname.lower() or "carousel" in sname.lower()
        if is_carousel_sheet and len(sheet_items) >= 2:
            c_cards = []
            for c_idx, card in enumerate(sheet_items, 1):
                raw_desc = card.get("text") or card.get("body") or ""
                c_title = card.get("card_title") or card.get("header") or derive_clean_card_title(raw_desc) or f"Card {c_idx}"
                lines = raw_desc.strip().splitlines()
                c_desc = raw_desc
                if len(lines) > 1 and lines[0].strip().strip("*_#~ ").lower() == c_title.lower():
                    c_desc = "\n".join(lines[1:]).strip()
                c_btn = card.get("button_text") or "Explore Now"
                c_url = card.get("button_url") or "https://u3.mnge.co/"
                if sheet_imgs and (c_idx - 1) < len(sheet_imgs):
                    c_media = sheet_imgs[c_idx - 1]
                    c_media_fn = Path(c_media).name
                elif sheet_imgs:
                    c_media = sheet_imgs[(c_idx - 1) % len(sheet_imgs)]
                    c_media_fn = Path(c_media).name
                else:
                    c_media = card.get("media_file")
                    c_media_fn = card.get("media_filename")
                c_cards.append({
                    "card_title": c_title,
                    "card_description": c_desc,
                    "media_url": c_media,
                    "media_filename": c_media_fn,
                    "button_text": c_btn,
                    "button_url": c_url,
                    "suggestions": [
                        {
                            "suggestionType": "url_action",
                            "text": c_btn,
                            "postbackData": c_btn,
                            "url": c_url,
                        }
                    ],
                })
            carousel_item = {
                "channel": "RCS",
                "template_type": "carousel",
                "variant": "Carousel",
                "card_title": c_cards[0]["card_title"],
                "text": c_cards[0]["card_description"],
                "raw_text": "\n---\n".join(c["card_description"] for c in c_cards),
                "button_text": c_cards[0]["button_text"],
                "button_url": c_cards[0]["button_url"],
                "media_file": c_cards[0]["media_url"],
                "media_filename": c_cards[0]["media_filename"],
                "carousel_cards": c_cards,
                "source": f"excel_carousel_{sname}",
            }
            all_items.append(carousel_item)
        else:
            for item in sheet_items:
                raw_t = item.get("raw_text") or item.get("text", "")
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

def _extract_images_from_xlsx(xlsx_path: Path) -> dict[str, list[str]]:
    """
    Extract embedded drawing images from an Excel (.xlsx) file sheet-by-sheet,
    saving raw image bytes to MEDIA_CACHE_DIR and returning a map of
    {sheet_name: [saved_image_paths]}.
    """
    image_map: dict[str, list[str]] = {}
    if not xlsx_path.exists():
        return image_map

    try:
        import openpyxl

        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
        for sname in wb.sheetnames:
            ws = wb[sname]
            imgs = getattr(ws, "_images", [])
            if imgs:
                clean_sname = re.sub(r"[^\w\-.]", "_", sname)

                def _img_sort_key(im):
                    af = getattr(im.anchor, "_from", None)
                    return (af.col, af.row) if af else (0, 0)

                sorted_imgs = sorted(imgs, key=_img_sort_key)
                for idx, img in enumerate(sorted_imgs):
                    try:
                        data = img._data()
                        fmt = getattr(img, "format", "jpeg") or "jpeg"
                        out_path = MEDIA_CACHE_DIR / f"jira_xlsx_{xlsx_path.stem}_{clean_sname}_{idx + 1}.{fmt}"
                        out_path.write_bytes(data)
                        image_map.setdefault(sname, []).append(str(out_path))
                    except Exception as e:
                        logger.debug("Could not extract image %d from sheet %s: %s", idx, sname, e)
        wb.close()
    except Exception as exc:
        logger.debug("Could not extract embedded images from xlsx %s: %s", xlsx_path, exc)

    return image_map


def _parse_swcm_campaign_tables(adf_doc: dict[str, Any] | None, summary: str = "") -> list[dict[str, Any]]:
    """
    Parse SWCM campaign execution format tables (WhatsApp, RCS, SMS) into campaign items.
    Handles single-cell header tables (e.g. SWCM-85, SWCM-84, SWCM-79, SWCM-78) as well as
    multi-cell execution format tables (SWCM-59).
    Preserves bold markdown (*bold*), variable placeholders, and extracts real destination URLs.
    """
    if not adf_doc:
        return []

    tables = _find_adf_tables(adf_doc)
    campaigns: list[dict[str, Any]] = []

    for tbl in tables:
        rows = tbl.get("content", [])
        if not rows:
            continue

        raw_rows = []
        for r in rows:
            cells = [_extract_text_from_adf_node(c, preserve_formatting=True).strip() for c in r.get("content", [])]
            raw_rows.append(cells)

        if not raw_rows:
            continue

        header_c0 = raw_rows[0][0].lower().strip() if raw_rows and raw_rows[0] else ""
        header_c1 = raw_rows[0][1].strip() if len(raw_rows[0]) > 1 else ""
        is_swcm_table = "campaign execution format" in header_c0 or any(
            "campaign execution format" in (r[0].lower() if r else "") for r in raw_rows
        )
        if not is_swcm_table:
            continue

        chan = None
        if header_c1.upper().startswith("WA"):
            chan = "WA"
        elif header_c1.upper().startswith("RCS"):
            chan = "RCS"
        elif header_c1.upper().startswith("SMS"):
            chan = "SMS"
        elif "whatsapp" in header_c0 or "wa " in header_c0 or header_c0.startswith("wa"):
            chan = "WA"
        elif "rcs" in header_c0:
            chan = "RCS"
        elif "sms" in header_c0:
            chan = "SMS"
        elif "email" in header_c0:
            chan = "EMAIL"

        fields: dict[str, str] = {}
        fields_links: dict[str, list[str]] = {}
        start_r = 1 if ("campaign execution format" in header_c0 or len(raw_rows) > 1) else 0
        for r_node in rows[start_r:]:
            cells_node = r_node.get("content", [])
            if len(cells_node) >= 2:
                raw_k = _extract_text_from_adf_node(cells_node[0], preserve_formatting=False).strip().replace("*", "").strip(":")
                val_text = _extract_text_from_adf_node(cells_node[1], preserve_formatting=True).strip()
                val_links = _extract_links_from_adf_node(cells_node[1])
                k_norm = raw_k.lower().strip()
                fields[k_norm] = val_text
                fields_links[k_norm] = val_links

        body_val = None
        candidate_keys = [
            "whatsapp text", "wa text", "whatsapp content", "wa content",
            "rcs text", "rcs content",
            "sms text", "sms content",
            "content", "message", "copy", "text",
            "template id (if available)", "template id",
        ]
        for k in candidate_keys:
            if k in fields:
                val = fields[k]
                if is_valid_template_copy(val):
                    body_val = val
                    if not chan:
                        if "whatsapp" in k or "wa " in k:
                            chan = "WA"
                        elif "rcs" in k:
                            chan = "RCS"
                        elif "sms" in k:
                            chan = "SMS"
                    break

        if not body_val:
            continue

        if not chan:
            s_low = summary.lower()
            if "whatsapp" in s_low or "wa " in s_low:
                chan = "WA"
            elif "rcs" in s_low:
                chan = "RCS"
            elif "sms" in s_low:
                chan = "SMS"
            else:
                chan = "WA"

        camp_name = (
            fields.get("campaign name")
            or fields.get("campaign name 1")
            or fields.get("campaign name 2")
            or summary
        )
        cta_text = fields.get("cta / link") or fields.get("cta") or fields.get("link") or ""
        cta_links = fields_links.get("cta / link") or fields_links.get("cta") or []
        sched = fields.get("date & time of execution") or fields.get("date & time") or ""

        campaigns.append(
            {
                "channel": chan,
                "wa_label": header_c1 or chan,
                "campaign_name": camp_name,
                "body": body_val,
                "cta_text": cta_text,
                "cta_links": cta_links,
                "schedule": sched,
            }
        )

    return campaigns

def _clean_cta_label(label: str) -> str:
    """Clean internal targeting tags like '(for both EC & PC)', '(only for PC)' from CTA button label."""
    clean = re.sub(r"\s*\([^)]*(?:ec|pc|rcs|wa|whatsapp|sms)[^)]*\)", "", label, flags=re.IGNORECASE).strip()
    clean = clean.strip("*_~:- ")
    return clean or "Explore Now"


def _parse_swcm_cta(cta_raw: str, cta_links: list[str] | None = None) -> tuple[str, str, list[dict[str, str]]]:
    """
    Parse CTA label and real destination URL from cell text and extracted hyperlink marks.
    Returns: (primary_button_text, primary_button_url, all_ctas_list)
    """
    all_ctas: list[dict[str, str]] = []
    cta_raw_clean = (cta_raw or "").strip()
    if not cta_raw_clean and not cta_links:
        return "", "", []
    # 1. Check for multi-CTA patterns like 'CTA 1:', 'CTA 2:', 'Button 1:', etc.
    cta_marker_pat = re.compile(
        r"(?:^|\n)\s*(?:CTA\s*(\d*)|Button\s*(\d*)|Action\s*(\d*))\s*[:\-–]\s*([^\n\r]+)",
        re.IGNORECASE,
    )
    matches = list(cta_marker_pat.finditer(cta_raw_clean))

    if len(matches) >= 2 or (len(matches) == 1 and ("cta 1" in cta_raw_clean.lower() or "cta 2" in cta_raw_clean.lower())):
        for idx, m in enumerate(matches):
            raw_label = m.group(4).strip()
            clean_lbl = _clean_cta_label(raw_label)

            start_pos = m.end()
            end_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(cta_raw_clean)
            block_text = cta_raw_clean[start_pos:end_pos]

            url_match = re.search(r"https?://[^\s]+", block_text)
            url_val = url_match.group(0).rstrip(".,)") if url_match else None

            if not url_val and cta_links and idx < len(cta_links):
                url_val = cta_links[idx]

            all_ctas.append({
                "type": "URL",
                "label": clean_lbl,
                "url": url_val or DEFAULT_CTA_URL,
            })
    else:
        lines = [l.strip() for l in cta_raw_clean.split("\n") if l.strip()]
        button_text = "Explore Now"
        button_url = DEFAULT_CTA_URL

        for line in lines:
            if re.match(r"^cta\s*\d*\s*[:\-–]", line, re.IGNORECASE):
                candidate = re.split(r"[:\-–]", line, 1)[1].strip()
                if candidate:
                    button_text = _clean_cta_label(candidate)
                    break
            elif "->" in line or "|" in line:
                parts = re.split(r"\s*(?:->|\|)\s*", line)
                if len(parts) >= 2:
                    button_text = _clean_cta_label(parts[0])
                    break

        raw_urls = re.findall(r"https?://[^\s]+", cta_raw_clean)
        valid_links = [l.rstrip(".,)") for l in (cta_links or []) if l.startswith("http")] + [u.rstrip(".,)") for u in raw_urls]
        if valid_links:
            button_url = valid_links[0]

        all_ctas.append({
            "type": "URL",
            "label": button_text,
            "url": button_url,
        })

        if len(valid_links) > 1 and len(all_ctas) == 1:
            for extra_url in valid_links[1:]:
                all_ctas.append({
                    "type": "URL",
                    "label": "Learn More",
                    "url": extra_url,
                })

    primary_text = all_ctas[0]["label"] if all_ctas else "Explore Now"
    primary_url = all_ctas[0]["url"] if all_ctas else DEFAULT_CTA_URL
    return primary_text, primary_url, all_ctas


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
    target_keywords = {v for k, v in _LOCATION_KEYWORDS.items() if k in cname_lower}
    if not target_keywords:
        return None

    wa_named = [i for i in images if "whatsapp" in Path(i).name.lower() or "whatsap" in Path(i).name.lower()]
    other = [i for i in images if i not in wa_named]

    for img in wa_named + other:
        img_lower = Path(img).name.lower()
        if any(kw in img_lower for kw in target_keywords):
            return img
    return None


def parse_ticket_intent(desc: str) -> dict[str, Any]:
    """
    Parse explicit operator and copy instructions from the Jira issue description:
    - WhatsApp Category (e.g. Utility, Marketing, Authentication)
    - CTA intent (e.g. 'No CTA', 'Without CTA' -> prevents adding default CTA buttons)
    - WhatsApp Sender / WABA identifier (e.g. 'TATACAPTRANS')
    - SMS Sender Header (e.g. 'Tatacl')
    """
    info: dict[str, Any] = {
        "wa_category": None,
        "no_cta": False,
        "wa_sender": None,
        "sms_header": None,
    }
    if not desc:
        return info

    low = desc.lower()
    if any(k in low for k in ("no cta", "without cta", "cta: none", "cta: na", "cta: n/a", "no button")):
        info["no_cta"] = True

    lines = [l.strip() for l in desc.split("\n") if l.strip()]
    in_wa = False
    in_sms = False

    for line in lines:
        l_low = line.lower()
        if l_low.startswith(("whatsapp", "wa:")) or l_low == "wa":
            in_wa = True
            in_sms = False
            continue
        elif l_low.startswith("sms"):
            in_sms = True
            in_wa = False
            continue

        if in_wa:
            if line.upper() in ("UTILITY", "MARKETING", "AUTHENTICATION"):
                info["wa_category"] = line.upper()
            elif any(k in l_low for k in ("no cta", "without cta", "cta: none", "cta: na", "cta: n/a")):
                info["no_cta"] = True
            elif len(line) >= 4 and not info["wa_sender"] and not line.endswith(":"):
                info["wa_sender"] = line
        elif in_sms:
            if "header:" in l_low:
                info["sms_header"] = line.split(":", 1)[1].strip()

    if not info["wa_category"]:
        if "utility" in low and "marketing" not in low:
            info["wa_category"] = "UTILITY"
        elif "marketing" in low and "utility" not in low:
            info["wa_category"] = "MARKETING"
        elif "authentication" in low or "otp" in low:
            info["wa_category"] = "AUTHENTICATION"

    return info


def parse_jira_brief(issue_data: dict[str, Any], download_creatives: bool = True) -> ParsedJiraBrief:
    """
    Parse a complete Jira ticket dictionary:
    - Extracts from Excel attachments if present (.xlsx, .csv).
    - Extracts multi-channel copy from Word attachments (.docx).
    - Falls back to Jira ADF tables / text.
    - Classifies email mailers (.zip + .docx).
    """
    key = str(issue_data.get("key", "TCN_001"))
    summary = str(issue_data.get("summary", ""))
    desc_text = str(issue_data.get("description_text", ""))
    desc_raw = issue_data.get("description_raw")
    sub_account = infer_sub_account_from_text(summary + " " + desc_text)
    ticket_intent = parse_ticket_intent(desc_text)

    # Detect Email Mailer tickets (e.g. TCN-528 TCL Mailers Sept, SWCM-61)
    raw_attachments = issue_data.get("attachments", [])
    has_mailers_zip = any(
        ("mailer" in a.get("filename", "").lower() or a.get("filename", "").endswith(".zip")) for a in raw_attachments
    )
    has_subject_lines = any(
        "subject" in a.get("filename", "").lower() or a.get("filename", "").endswith((".docx", ".doc"))
        for a in raw_attachments
    )
    has_excel = any(a.get("filename", "").lower().endswith((".xlsx", ".xls", ".csv")) for a in raw_attachments)
    has_docx = any(a.get("filename", "").lower().endswith((".docx", ".doc")) for a in raw_attachments)
    is_email_campaign = (
        (
            "mailer" in summary.lower()
            or "mailers" in summary.lower()
            or "email" in summary.lower()
            or "email" in desc_text.lower()
        )
        and (has_mailers_zip or has_subject_lines or "email text" in desc_text.lower())
    ) or (has_mailers_zip and not has_excel and not has_docx)
    mapped_attachments: list[dict[str, Any]] = []
    excel_attachment_paths: list[Path] = []
    docx_attachment_paths: list[Path] = []
    zip_creative_paths: list[str] = []

    for att in raw_attachments:
        fn = att.get("filename", "")
        att_id = att.get("id")
        mime = att.get("mimeType", "")
        local_path: str | None = None
        if att.get("local_path") and Path(att["local_path"]).exists():
            local_path = str(att["local_path"])
            p = Path(local_path)
            if fn.lower().endswith((".xlsx", ".xls", ".csv")):
                excel_attachment_paths.append(p)
                if fn.lower().endswith(".xlsx"):
                    xlsx_imgs = _extract_images_from_xlsx(p)
                    for s_name, img_paths in xlsx_imgs.items():
                        zip_creative_paths.extend(img_paths)
                        for ip in img_paths:
                            mapped_attachments.append({
                                "id": Path(ip).stem,
                                "filename": Path(ip).name,
                                "local_path": ip,
                                "mime": "image/jpeg",
                                "target_channel": "WHATSAPP" if "wa" in s_name.lower() else ("RCS" if "rcs" in s_name.lower() else "GENERAL"),
                            })
            elif fn.lower().endswith((".docx", ".doc")):
                docx_attachment_paths.append(p)
            elif fn.lower().endswith(".zip"):
                zip_creative_paths.extend(_extract_images_from_zip(p))
        elif download_creatives and att_id:
            try:
                p = download_jira_attachment(att_id, fn)
                local_path = str(p)
                if fn.lower().endswith((".xlsx", ".xls", ".csv")):
                    excel_attachment_paths.append(p)
                    if fn.lower().endswith(".xlsx"):
                        xlsx_imgs = _extract_images_from_xlsx(p)
                        for s_name, img_paths in xlsx_imgs.items():
                            zip_creative_paths.extend(img_paths)
                            for ip in img_paths:
                                mapped_attachments.append({
                                    "id": Path(ip).stem,
                                    "filename": Path(ip).name,
                                    "local_path": ip,
                                    "mime": "image/jpeg",
                                    "target_channel": "WHATSAPP" if "wa" in s_name.lower() else ("RCS" if "rcs" in s_name.lower() else "GENERAL"),
                                })
                elif fn.lower().endswith((".docx", ".doc")):
                    docx_attachment_paths.append(p)
                elif fn.lower().endswith(".zip"):
                    zip_creative_paths.extend(_extract_images_from_zip(p))
            except Exception as e:
                logger.warning("Could not download attachment %s for %s: %s", att_id, key, e)
        fn_lower = fn.lower()
        if fn_lower.endswith((".xlsx", ".xls", ".csv")):
            target_chan = "SPREADSHEET_BRIEF"
        elif fn_lower.endswith((".docx", ".doc")):
            target_chan = "DOCUMENT_BRIEF"
        elif fn_lower.endswith(".zip"):
            target_chan = "EMAIL_CREATIVE"
        elif "wa" in fn_lower or "whatsapp" in fn_lower:
            target_chan = "WHATSAPP"
        elif "rcs" in fn_lower:
            target_chan = "RCS"
        elif "sms" in fn_lower:
            target_chan = "SMS"
        else:
            target_chan = "GENERAL"
        mapped_attachments.append(
            {
                "id": att_id,
                "filename": fn,
                "local_path": local_path,
                "mime": mime,
                "target_channel": target_chan,
            }
        )

    IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
    wa_creatives = [
        a
        for a in mapped_attachments
        if a.get("filename", "").lower().endswith(IMAGE_EXTS)
        and a.get("local_path")
        and (
            a["target_channel"] == "WHATSAPP"
            or "wa" in a.get("filename", "").lower()
            or "whatsapp" in a.get("filename", "").lower()
        )
    ]
    if not wa_creatives:
        wa_creatives = [
            a for a in mapped_attachments if a.get("filename", "").lower().endswith(IMAGE_EXTS) and a.get("local_path")
        ]

    rcs_creatives = [
        a
        for a in mapped_attachments
        if a.get("filename", "").lower().endswith(IMAGE_EXTS)
        and a.get("local_path")
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
        is_email_doc = (
            lower_fn.endswith(".zip")
            or lower_fn.endswith(".html")
            or (
                lower_fn.endswith((".docx", ".doc"))
                and (
                    is_email_campaign
                    or has_mailers_zip
                    or any(k in lower_fn for k in ("subject", "mailer", "preheader", "email"))
                )
            )
        )
        if is_email_doc:
            f_type = (
                "HTML Mailer Package"
                if lower_fn.endswith(".zip")
                else ("Subject Lines & Preheaders" if lower_fn.endswith((".docx", ".doc")) else "HTML Template")
            )
            html_code: str | None = None
            lpath = att.get("local_path")
            if lower_fn.endswith(".zip") and lpath and Path(lpath).exists():
                try:
                    import zipfile

                    with zipfile.ZipFile(lpath, "r") as zf:
                        for zname in zf.namelist():
                            if zname.lower().endswith((".html", ".htm")) and not zname.startswith("__MACOSX"):
                                html_code = zf.read(zname).decode("utf-8", errors="ignore")
                                break
                except Exception as exc:
                    logger.warning("Could not read HTML from mailer zip %s: %s", fn, exc)
            elif lower_fn.endswith((".html", ".htm")) and lpath and Path(lpath).exists():
                try:
                    html_code = Path(lpath).read_text(encoding="utf-8", errors="ignore")
                except Exception as exc:
                    logger.warning("Could not read HTML file %s: %s", fn, exc)

            email_item: dict[str, Any] = {
                "template_name": Path(fn).stem,
                "filename": fn,
                "file_type": f_type,
                "local_path": lpath,
                "target_channel": "EMAIL",
            }
            if html_code:
                email_item["html_content"] = html_code
            email_drafts.append(email_item)
    base_name = f"{key.lower().replace('-', '_')}_{re.sub(r'[^a-z0-9]', '_', summary.lower())[:16]}".strip("_")

    # 2. Extract templates from attached Word (.docx) and Excel (.xlsx) files
    target_month = detect_ticket_month(summary, desc_text)
    extracted_items: list[dict[str, str]] = []

    for docx_path in docx_attachment_paths:
        docx_items = extract_templates_from_docx_file(docx_path)
        if docx_items:
            extracted_items.extend(docx_items)

    for excel_path in excel_attachment_paths:
        items = extract_templates_from_excel_file(excel_path, target_month=target_month)
        if items:
            extracted_items.extend(items)
    adf_items = _parse_tables_from_adf(desc_raw)
    if adf_items:
        extracted_items.extend(adf_items)

    if not extracted_items:
        # Pipe blocks fallback (e.g. SMS | ... or WA | ...)
        pipe_blocks = re.findall(r"^(SMS|WA|RCS)\s*\|\s*(.+)$", desc_text, re.IGNORECASE | re.MULTILINE)
        for chan_tag, text_val in pipe_blocks:
            extracted_items.append(
                {
                    "channel": chan_tag.upper(),
                    "text": text_val.strip(),
                    "variant": "General",
                    "source": "jira_pipe",
                }
            )

    # 3c. Check ticket comments for revisions / copy updates
    raw_comments = issue_data.get("comments", [])
    comment_updates: list[dict[str, Any]] = []
    for c in raw_comments:
        c_body = c.get("body_text", "")
        author = c.get("author", "Commenter")
        pipe_m = re.findall(r"^(SMS|WA|RCS|WHATSAPP)\s*\|\s*(.+)$", c_body, re.IGNORECASE | re.MULTILINE)
        for c_tag, t_val in pipe_m:
            comment_updates.append(
                {
                    "channel": "WA" if c_tag.upper() in ("WA", "WHATSAPP") else c_tag.upper(),
                    "text": t_val.strip(),
                    "variant": f"Revision by {author}",
                    "source": f"comment_{c.get('id', '')}",
                }
            )
        rev_m = re.findall(
            r"(?:updated|revised|new|approved)\s+(wa|whatsapp|sms|rcs)\s*[:\-–]\s*(.+?)(?=\n\s*(?:updated|revised|new|sms|wa|rcs|$)|\Z)",
            c_body,
            re.IGNORECASE | re.DOTALL,
        )
        for c_tag, t_val in rev_m:
            if len(t_val.strip()) > 20:
                comment_updates.append(
                    {
                        "channel": "WA" if c_tag.upper() in ("WA", "WHATSAPP") else c_tag.upper(),
                        "text": t_val.strip(),
                        "variant": f"Revision by {author}",
                        "source": f"comment_rev_{c.get('id', '')}",
                    }
                )

    if comment_updates:
        extracted_items.extend(comment_updates)
    wa_counter = 1
    rcs_counter = 1
    sms_counter = 1
    # 3b. SWCM campaign tables (WhatsApp, RCS, SMS)
    swcm_campaigns = _parse_swcm_campaign_tables(desc_raw, summary=summary)
    for idx, campaign in enumerate(swcm_campaigns, start=1):
        c_chan = campaign.get("channel", "WA").upper()
        cta_text, cta_url, all_ctas = _parse_swcm_cta(campaign.get("cta_text", ""), campaign.get("cta_links", []))
        norm_text, samples = normalize_placeholders(campaign["body"])
        clean_body, swcm_btn_text, swcm_btn_url, swcm_footer = extract_and_strip_cta(
            norm_text,
            existing_btn_text=cta_text,
            existing_btn_url=cta_url,
        )
        if not all_ctas and (swcm_btn_text or (swcm_btn_url and swcm_btn_url != DEFAULT_CTA_URL)):
            all_ctas = [{"type": "URL", "label": swcm_btn_text or "Explore Now", "url": swcm_btn_url or DEFAULT_CTA_URL}]
        var_tags = re.findall(r"\{\{(\d+)\}\}", clean_body)
        if len(samples) > len(var_tags):
            samples = samples[: len(var_tags)]
        lang = detect_language(clean_body)
        cat = detect_category(summary, clean_body)

        if c_chan in ("WA", "WHATSAPP"):
            media = _match_creative_to_campaign(campaign["campaign_name"], zip_creative_paths)
            if media is None and zip_creative_paths:
                media = zip_creative_paths[(idx - 1) % len(zip_creative_paths)]
            tname = _clean_template_name(base_name, f"wa_{lang}" if lang != "en" else "wa", wa_counter)
            wa_drafts.append(
                WhatsAppTemplateDraft(
                    template_name=tname,
                    category=cat,
                    language=lang,
                    body=clean_body,
                    header_type="IMAGE" if media else "TEXT",
                    header_text=None,
                    footer_text=None,
                    media_file=media,
                    media_filename=Path(media).name if media else None,
                    button_type="URL",
                    button_text=all_ctas[0]["label"] if all_ctas else swcm_btn_text,
                    button_url=all_ctas[0]["url"] if all_ctas else swcm_btn_url,
                    buttons=all_ctas,
                    variables=var_tags,
                    source_origin=f"swcm_{campaign['wa_label'].replace(' ', '_').lower()}",
                )
            )
            wa_counter += 1

        elif c_chan == "RCS":
            media = _match_creative_to_campaign(campaign["campaign_name"], zip_creative_paths)
            if media is None and zip_creative_paths:
                media = zip_creative_paths[(idx - 1) % len(zip_creative_paths)]
            tname = _clean_template_name(base_name, "rcs", rcs_counter)
            rcs_card_title = derive_clean_card_title(clean_body, account=issue_data.get("account"))
            if rcs_card_title and clean_body:
                lines = clean_body.strip().splitlines()
                if len(lines) > 1:
                    first_clean = lines[0].strip().strip("*_#~ ")
                    if first_clean.lower() == rcs_card_title.lower() or rcs_card_title.lower().startswith(first_clean.lower()[:30]):
                        clean_body = "\n".join(lines[1:]).strip()
            rcs_drafts.append(
                RcsTemplateDraft(
                    template_name=tname,
                    card_title=rcs_card_title,
                    body=clean_body,
                    media_file=media,
                    media_filename=Path(media).name if media else None,
                    action_type="URL",
                    action_label=all_ctas[0]["label"] if all_ctas else swcm_btn_text,
                    action_url=all_ctas[0]["url"] if all_ctas else swcm_btn_url,
                    suggestions=all_ctas,
                    variables=var_tags,
                    sample_values=samples,
                    raw_source=campaign["body"],
                    source_origin=f"swcm_{campaign['wa_label'].replace(' ', '_').lower()}",
                )
            )

        elif c_chan == "SMS":
            tname = _clean_template_name(base_name, "sms", sms_counter)
            sms_drafts.append(
                SmsTemplateDraft(
                    template_name=tname,
                    text=clean_body,
                    char_count=len(clean_body),
                    variant=f"SWCM {campaign['wa_label']}",
                    variables=var_tags,
                    raw_source=campaign["body"],
                )
            )
            sms_counter += 1
    # 3c. TypeSafe AI Semantic Extraction fallback for free-form Jira descriptions
    desc_low = desc_text.lower()
    is_metadata_brief = any(k in desc_low for k in ("campaign name |", "sftp path", "date & time of execution"))
    if not extracted_items and not swcm_campaigns and desc_text.strip() and not is_metadata_brief:
        try:
            from jira_extractor import extract_template_from_jira_text

            semantic_res = extract_template_from_jira_text(desc_text, summary=summary, allow_ai=True)
            t_comp = semantic_res.template
            if t_comp.body_text and is_valid_template_copy(t_comp.body_text):
                chan_decision = semantic_res.routing.target_channel
                channels_to_emit = (
                    ["WA", "RCS", "SMS"]
                    if chan_decision == "MULTI_CHANNEL"
                    else (["WA"] if chan_decision == "WHATSAPP" else [chan_decision])
                )
                for c_tag in channels_to_emit:
                    extracted_items.append(
                        {
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
                        }
                    )
        except Exception as ex:
            logger.warning("TypeSafe semantic Jira extraction skipped: %s", ex)

    # 4. Assemble template drafts
    seen_sms_texts: dict[str, int] = {}
    for item in extracted_items:
        chan = item["channel"].upper()
        clean_content = item["text"]
        from gemini_intelligence import is_internal_identifier

        variant = item.get("variant", "General")
        title = item.get("title") or item.get("header") or ""
        if title and is_internal_identifier(title, summary=summary):
            title = ""
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

            # Strict 25-word validation for WhatsApp campaign drafts:
            # Unwanted cohort descriptions, audience criteria, and notes (< 25 words)
            # must not be counted or emitted unless starting with an explicit customer greeting.
            words = clean_body.split()
            has_greeting = bool(re.search(r"^(?:dear|hi|hello|hey|namaste)\b", clean_body.lower()))
            has_placeholder = bool(re.search(r"(\{\{|\<|\[|#\{#[^#]+#\}#|\{#[^#]+#\})", clean_body))
            has_link = bool(re.search(r"(?:https?://|www\.|<link>|u3\.mnge\.co)", clean_body.lower()))
            has_brand_offer = (
                ("tata capital" in clean_body.lower() or "tatacapital" in clean_body.lower() or "bajaj" in clean_body.lower())
                and bool(re.search(r"\b(loan|emi|offer|interest|apply|disburs|pre-approved)\b", clean_body.lower()))
            )
            has_action_offer = bool(re.search(r"\b(apply|get|enjoy|switch|transfer|repay|check)\b", clean_body.lower())) and bool(
                re.search(r"\b(loan|loans|emi|emis|fund|funds|interest|offer|offers)\b", clean_body.lower())
            )
            if len(words) < 25 and not (has_greeting or has_placeholder or has_link or has_brand_offer or has_action_offer):
                continue
            # Apply ticket intent instructions (e.g. No CTA, Utility category)
            if ticket_intent.get("no_cta"):
                b_type = "NONE"
                b_text = None
                b_url = None
            else:
                b_type = item.get("button_type") or ("URL" if cta_btn_url else "NONE")
                b_text = cta_btn_text
                b_url = cta_btn_url

            lang = item.get("language") or detect_language(clean_body, variant)
            cat = item.get("category") or ticket_intent.get("wa_category") or detect_category(summary, clean_body, item.get("source", ""))
            tname = item.get("template_name") or _clean_template_name(base_name, f"wa_{lang}" if lang != "en" else "wa", wa_counter)
            var_tags = re.findall(r"\{\{(\d+)\}\}", clean_body)
            resolved_vars = var_tags
            if len(resolved_samples) > len(var_tags):
                resolved_samples = resolved_samples[: len(var_tags)]
            wa_header = item.get("header")
            if wa_header and is_internal_identifier(wa_header, summary=summary):
                wa_header = None

            # Strip the explicit header from clean_body if repeated on the first line
            if wa_header and clean_body:
                lines = clean_body.strip().splitlines()
                if len(lines) > 1:
                    first_clean = lines[0].strip().strip("*_#~ ")
                    if first_clean.lower() == wa_header.lower():
                        clean_body = "\n".join(lines[1:]).strip()
            wa_drafts.append(
                WhatsAppTemplateDraft(
                    template_name=tname,
                    category=cat,
                    language=lang,
                    body=clean_body,
                    header_type=item.get("header_type") or ("IMAGE" if (item.get("media_file") or img) else ("TEXT" if wa_header else "NONE")),
                    header_text=None if (item.get("media_file") or img) else wa_header,
                    footer_text=None,
                    media_file=item.get("media_file") or (img.get("local_path") if img else None),
                    media_filename=item.get("media_filename") or (img.get("filename") if img else None),
                    button_type=b_type,
                    button_text=b_text,
                    button_url=b_url,
                    variables=resolved_vars,
                    sample_values=resolved_samples,
                    raw_source=clean_content,
                    source_origin=source_origin,
                )
            )
            wa_counter += 1

        elif chan == "RCS":
            img = rcs_creatives[(rcs_counter - 1) % len(rcs_creatives)] if rcs_creatives else None
            is_car = item.get("template_type") == "carousel" or bool(item.get("carousel_cards"))
            t_suffix = "rcs_carousel" if is_car else "rcs"
            tname = item.get("template_name") or _clean_template_name(base_name, t_suffix, rcs_counter)
            clean_body, cta_btn_text, cta_btn_url, _ = extract_and_strip_cta(
                norm_text,
                existing_btn_text=item.get("button_text"),
                existing_btn_url=item.get("button_url"),
            )

            # Strict 25-word validation for RCS campaign drafts
            words = clean_body.split()
            has_greeting = bool(re.search(r"^(?:dear|hi|hello|hey|namaste)\b", clean_body.lower()))
            has_placeholder = bool(re.search(r"(\{\{|\<|\[|#\{#[^#]+#\}#|\{#[^#]+#\})", clean_body))
            has_link = bool(re.search(r"(?:https?://|www\.|<link>|u3\.mnge\.co)", clean_body.lower()))
            has_structured = ("body:" in clean_body.lower()) or ("title:" in clean_body.lower())
            has_brand_offer = (
                ("tata capital" in clean_body.lower() or "tatacapital" in clean_body.lower() or "bajaj" in clean_body.lower())
                and bool(re.search(r"\b(loan|emi|offer|interest|apply|disburs|pre-approved)\b", clean_body.lower()))
            )
            has_action_offer = bool(re.search(r"\b(apply|get|enjoy|switch|transfer|repay|check)\b", clean_body.lower())) and bool(
                re.search(r"\b(loan|loans|emi|emis|fund|funds|interest|offer|offers)\b", clean_body.lower())
            )
            if len(words) < 25 and not (has_greeting or has_placeholder or has_link or has_structured or has_brand_offer or has_action_offer):
                continue
            raw_rcs_title = item.get("title") or item.get("header") or ""
            if raw_rcs_title and not is_internal_identifier(raw_rcs_title, summary=summary):
                rcs_card_title = raw_rcs_title
            else:
                rcs_card_title = derive_clean_card_title(clean_body, account=issue_data.get("account"))

            # Strip the extracted card title from clean_body so it is never repeated in both title and body
            if rcs_card_title and clean_body:
                lines = clean_body.strip().splitlines()
                if len(lines) > 1:
                    first_clean = lines[0].strip().strip("*_#~ ")
                    if first_clean.lower() == rcs_card_title.lower():
                        clean_body = "\n".join(lines[1:]).strip()
            rcs_drafts.append(
                RcsTemplateDraft(
                    template_name=tname,
                    card_title=rcs_card_title,
                    body=clean_body,
                    media_file=item.get("media_file") or (img.get("local_path") if img else None),
                    media_filename=item.get("media_filename") or (img.get("filename") if img else None),
                    action_type=item.get("button_type") or "URL",
                    action_label=cta_btn_text,
                    action_url=cta_btn_url,
                    template_type="carousel" if is_car else ("richcard" if (item.get("media_file") or img) else "text"),
                    carousel_cards=item.get("carousel_cards", []),
                    variables=item.get("variables") or var_tags,
                    sample_values=item.get("sample_values") or resolved_samples[: len(var_tags)],
                    raw_source=clean_content,
                    source_origin=source_origin,
                )
            )
            rcs_counter += 1

        elif chan == "SMS":
            norm_key = re.sub(r"[^a-z0-9]", "", norm_text.lower())[:150]
            if norm_key in seen_sms_texts:
                prev_idx = seen_sms_texts[norm_key]
                if item.get("template_name") and not item["template_name"].startswith("swcm_"):
                    sms_drafts[prev_idx].template_name = item["template_name"]
                continue
            tname = item.get("template_name") or _clean_template_name(base_name, "sms", sms_counter)
            seen_sms_texts[norm_key] = len(sms_drafts)
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
            email_drafts.append(
                {
                    "template_name": _clean_template_name(base_name, "email", len(email_drafts) + 1),
                    "filename": f"Email Copy {len(email_drafts) + 1}",
                    "file_type": "Email Body Copy",
                    "body": norm_text,
                    "variant": variant,
                    "source_origin": source_origin,
                }
            )
    from jira_client import is_explicit_push

    has_push = bool(
        any(item.get("channel") == "PUSH" for item in extracted_items)
        or is_explicit_push(summary)
        or is_explicit_push(desc_text)
    )

    is_email = bool(
        len(email_drafts) > 0
        or has_mailers_zip
        or "mailer" in summary.lower()
        or "mailers" in summary.lower()
        or ("email" in summary.lower() and not wa_drafts)
        or "email text" in desc_text.lower()
    )
    is_email_campaign = is_email and not wa_drafts and not rcs_drafts and not sms_drafts

    email_count = len(email_drafts) if email_drafts else (1 if is_email else 0)
    push_count = 1 if has_push else 0

    # 5. Build MoEngage Campaign Staging payload
    campaign_metadata = _extract_kv_metadata_from_adf_or_text(desc_raw, desc_text)
    approved_cname = campaign_metadata.get("campaign_name") if campaign_metadata else None
    approved_sched = campaign_metadata.get("scheduled_at") if campaign_metadata else None
    approved_subj = campaign_metadata.get("email_subject") if campaign_metadata else None
    moengage_campaign = {
        "campaign_name": approved_cname or f"{key} - {summary}",
        "target_account": sub_account,
        "scheduled_date": approved_sched or issue_data.get("duedate"),
        "whatsapp_template": wa_drafts[0].template_name if wa_drafts else None,
        "sms_content": sms_drafts[0].text if sms_drafts else None,
        "email_subject": approved_subj,
        "database_source": campaign_metadata.get("database_source") if campaign_metadata else None,
        "push_title": f"Tata Capital: {summary[:30]}" if has_push else None,
        "push_body": (sms_drafts[0].text if sms_drafts else (wa_drafts[0].body if wa_drafts else summary))[:120] if has_push else None,
        "status": "DRAFT",
    }

    if is_email_campaign:
        campaign_type_label = "Email Mailer Campaign"
    elif wa_drafts and is_email:
        campaign_type_label = "Multi-Channel (WhatsApp & Email)"
    elif wa_drafts and rcs_drafts:
        campaign_type_label = "Multi-Channel (WhatsApp & RCS)"
    else:
        campaign_type_label = "Multi-Channel Whitelisting Brief"

    ch_counts = {
        "total": len(wa_drafts) + len(rcs_drafts) + len(sms_drafts) + email_count + push_count,
        "whatsapp": len(wa_drafts),
        "rcs": len(rcs_drafts),
        "sms": len(sms_drafts),
        "email": email_count,
        "push": push_count,
    }

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
        channel_counts=ch_counts,
        campaign_metadata=campaign_metadata,
    )
