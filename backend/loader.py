"""
Input loader: turns raw rows (CSV, JSON list, or Excel files) into validated
TemplateSubmission objects for WhatsApp.

Supports standard schemas, arbitrary semantic column labels, and unstructured
single-cell marketing briefs with automatic media extraction.
"""

import csv
import hashlib
import json
import logging
import re
from pathlib import Path

from config import get_waba_id
from models import TemplateComponent, TemplateSubmission
from cta import TATA_CTA_URL, normalize_whatsapp_cta_buttons, separate_inline_cta_instructions
from campaign_names import normalize_campaign_name

logger = logging.getLogger(__name__)
# Mirror of submission_client._TATA_GROUP — kept in sync manually.
_TATA_GROUP = {"tata", "tcl_promo", "tcl_trans", "tchfl", "wealth", "moneyfy"}


def infer_whatsapp_cta(text: str, client: str = "bajaj") -> tuple[str, str, str]:
    """
    If no explicit CTA is provided:
    Infers the appropriate button text, dynamic URL, and Meta sample example.
    """
    t_lower = text.lower()
    is_tata = (client or "").lower() in _TATA_GROUP

    if is_tata:
        base_domain = "https://www.tatacapital.com"
        if any(w in t_lower for w in ("home loan", "housing", "property")):
            return (
                "Check Rates",
                f"{base_domain}/home-loan.html/{{{{1}}}}",
                f"{base_domain}/home-loan.html",
            )
        elif any(w in t_lower for w in ("business loan", "enterprise", "msme")):
            return (
                "Apply Business",
                f"{base_domain}/business-loan.html/{{{{1}}}}",
                f"{base_domain}/business-loan.html",
            )
        elif any(w in t_lower for w in ("vehicle", "car", "2-wheeler", "bike")):
            return (
                "Explore Vehicle",
                f"{base_domain}/vehicle-loan.html/{{{{1}}}}",
                f"{base_domain}/vehicle-loan.html",
            )
        elif any(w in t_lower for w in ("eligibility", "eligible", "check offer")):
            return (
                "Check Eligibility",
                f"{base_domain}/personal-loan.html/{{{{1}}}}",
                f"{base_domain}/personal-loan.html",
            )
        elif any(w in t_lower for w in ("claim", "pre-approved", "pre approved", "exclusive")):
            return (
                "Claim Your Offer",
                f"{base_domain}/personal-loan.html/{{{{1}}}}",
                f"{base_domain}/personal-loan.html",
            )
        else:
            return (
                "Apply Now",
                f"{base_domain}/personal-loan.html/{{{{1}}}}",
                f"{base_domain}/personal-loan.html",
            )
    else:
        base_domain = "https://www.tatacapital.com"
        return "Apply Now", f"{base_domain}/personal-loan.html/{{{{1}}}}", f"{base_domain}/personal-loan.html"


def parse_single_cell_whatsapp_block(cell_text: str, client: str = "bajaj") -> dict:
    """
    Decompose an unstructured marketing card text block (from Excel cells) into WhatsApp components:
    - Clean body (with CTA instruction lines stripped)
    - Normalized variables ({{1}}, {{2}}...)
    - Clean header title
    - Action button with dynamic link
    """
    if not cell_text:
        return {
            "header": None,
            "body": "",
            "button_text": "Apply Now",
            "button_url": f"{TATA_CTA_URL}{{{{1}}}}" if client.lower() in _TATA_GROUP else "https://1kx.in/{{1}}",
            "button_example": "https://www.tatacapital.com",
        }

    lines = [line.strip() for line in separate_inline_cta_instructions(cell_text).splitlines() if line.strip()]

    inferred_btn, inferred_url, inferred_ex = infer_whatsapp_cta(cell_text, client=client)
    button_text = inferred_btn
    button_url = inferred_url
    button_example = inferred_ex
    clean_lines = []

    for line in lines:
        explicit_cta = re.match(r"^CTA\s*(?:Button)?\s*[:\-–]?\s*(.+)$", line, re.IGNORECASE)
        if explicit_cta:
            label = re.sub(
                r"\s*(?:<\s*(?:link|url)\s*>|\{\{?\s*(?:link|url)\s*\}\}?|\[(?:link|url)\])\s*$",
                "", explicit_cta.group(1), flags=re.IGNORECASE,
            ).strip(" {}<>[]")
            if label:
                button_text = label
            continue
        if re.match(r"^T\s*&\s*Cs?\b|^Terms\b", line, re.IGNORECASE):
            line = re.sub(r"<(?:link|url)>|\{\{?(?:link|url)\}\}?", "", line, flags=re.IGNORECASE).strip()
        is_cta = False
        # 1. Match CTA Button <Text> or CTA button<Text> or CTA<Text>
        m_cta = re.search(
            r"CTA\s*(?:Button|button)?\s*[:<\[]\s*([^>\]<]+)\s*[>\]]",
            line,
            re.IGNORECASE,
        )
        if m_cta:
            cand = m_cta.group(1).strip()
            if cand.lower() not in ("link", "url"):
                button_text = cand
            is_cta = True

        # 2. Match [Button Text] <link> or <Button Text> <link>
        m_link = re.search(r"[\[<]([^>\]<]+)[\]>]\s*(?:<link>|\[link\])", line, re.IGNORECASE)
        if m_link and not is_cta:
            cand = m_link.group(1).strip()
            if cand.lower() not in ("link", "url"):
                button_text = cand
            is_cta = True

        # 3. Match prompt lines like "Tap to proceed ⬇️" or "Tap below to check eligibility⬇️"
        if re.search(
            r"^(?:Tap|Click|Press)\s+(?:below|here|to\s+proceed|to\s+check|to\s+apply).*?(?:⬇️|->|:|here)?$",
            line,
            re.IGNORECASE,
        ):
            is_cta = True

        if not is_cta:
            clean_lines.append(line)

    full_desc = "\n\n".join(clean_lines)

    # Normalize body variables: <Name>, <amt>, [var] -> {{1}}, {{2}}
    spaced_body = re.sub(r"([A-Za-z0-9])(<[^>]+>)", r"\1 \2", full_desc)
    spaced_body = re.sub(r"(<[^>]+>)([A-Za-z0-9])", r"\1 \2", spaced_body)
    spaced_body = re.sub(r"([A-Za-z0-9])(\{#[^#]+#\})", r"\1 \2", spaced_body)

    placeholders = []

    def _repl(m):
        idx = len(placeholders) + 1
        placeholders.append(m.group(0))
        return f"{{{{{idx}}}}}"

    pattern = r"(\{\{\d+\}\}|\{\{[a-zA-Z0-9_]+\}\}|<[^>]+>|\{#[^#]+#\}|\[[a-zA-Z0-9_]+\]|\{[a-zA-Z0-9_]+\})"
    normalized_body = re.sub(pattern, _repl, spaced_body)

    # Only set header if an explicit Header: or Title: prefix was given; otherwise leave blank
    clean_title = None
    if clean_lines:
        m_hdr = re.match(r"^(?:Header|Title)\s*[:\-–]\s*(.+)$", clean_lines[0], re.IGNORECASE)
        if m_hdr:
            clean_title = m_hdr.group(1).strip()[:60]

    return {
        "header": clean_title,
        "body": normalized_body,
        "button_text": button_text,
        "button_url": button_url,
        "button_example": button_example,
    }


def _detect_media_kind(filename: str, raw_bytes: bytes) -> tuple[str, str]:
    """
    Detect whether raw media bytes are IMAGE, VIDEO, or DOCUMENT, and return (kind, mime_type).
    """
    fn = filename.lower()
    if fn.endswith((".mp4", ".m4v")):
        return "VIDEO", "video/mp4"
    if fn.endswith((".mov", ".qt")):
        return "VIDEO", "video/quicktime"
    if fn.endswith((".avi", ".mkv", ".webm", ".3gp", ".wmv")):
        return "VIDEO", "video/mp4"
    if fn.endswith((".png",)):
        return "IMAGE", "image/png"
    if fn.endswith((".jpg", ".jpeg")):
        return "IMAGE", "image/jpeg"
    if fn.endswith((".webp",)):
        return "IMAGE", "image/webp"
    if fn.endswith((".gif",)):
        return "IMAGE", "image/gif"
    if fn.endswith((".pdf",)):
        return "DOCUMENT", "application/pdf"

    # Check by magic bytes
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "IMAGE", "image/png"
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        return "IMAGE", "image/jpeg"
    if raw_bytes.startswith(b"%PDF"):
        return "DOCUMENT", "application/pdf"
    if len(raw_bytes) > 12 and (b"ftyp" in raw_bytes[:16] or b"moov" in raw_bytes[:32] or b"mdat" in raw_bytes[:32]):
        return "VIDEO", "video/mp4"

    return "IMAGE", "image/png"





def normalize_whatsapp_template_name(name: str) -> str:
    """Canonical new WhatsApp name: att_ plus Meta-safe lowercase characters."""
    clean = re.sub(r"[^a-zA-Z0-9_]+", "_", str(name or "").strip()).lower().strip("_")
    clean = re.sub(r"_+", "_", clean)
    return normalize_campaign_name(clean or "template")



def _normalize_whatsapp_buttons(components: list, client: str) -> list:
    """Apply the same URL CTA policy at import and at final submission."""
    for component in components:
        kind = component.get("type") if isinstance(component, dict) else component.type
        if str(kind or "").upper() == "BUTTONS":
            buttons = component.get("buttons", []) if isinstance(component, dict) else component.buttons
            normalize_whatsapp_cta_buttons(buttons or [], client)
    return components


def _row_to_submission(row: dict, client: str = "bajaj") -> TemplateSubmission:
    _TC_FIELDS = {
        "type",
        "text",
        "format",
        "variables",
        "buttons",
        "example",
        "media_url",
        "media_file",
        "image_bytes",
        "file_type",
    }

    components = []
    for c in row.get("components", []):
        if isinstance(c, dict):
            if c.keys() <= _TC_FIELDS:
                components.append(TemplateComponent(**c))
            else:
                components.append(c)
        else:
            components.append(c)
    c_client = row.get("client") or client
    raw_name = str(row.get("template_name") or row.get("name") or "").strip()
    source_ref = str(row.get("source_ref") or raw_name)
    channel = str(row.get("channel", "whatsapp")).lower().strip()
    template_name = normalize_whatsapp_template_name(raw_name) if channel == "whatsapp" else raw_name
    body = next((
        component.get("text") or "" if isinstance(component, dict) else component.text or ""
        for component in components
        if (component.get("type") if isinstance(component, dict) else component.type) == "BODY"
    ), "")
    return TemplateSubmission(
        client=c_client,
        channel=row.get("channel", "whatsapp"),
        template_name=template_name,
        language=row.get("language") or _template_cell_language(body),
        category=row.get("category", "MARKETING"),
        waba_id=row.get("waba_id") or _resolve_row_waba(c_client, {}),
        components=_normalize_whatsapp_buttons(components, c_client) if channel == "whatsapp" else components,
        source_ref=source_ref,
    )


def _flat_row_to_components(raw_row: dict) -> list[dict]:
    """Convert flat CSV columns into the Karix components array."""
    components = []

    # 1. HEADER
    htype = (raw_row.get("header_type") or raw_row.get("header_format") or "").strip().upper()
    if htype in ("IMAGE", "VIDEO", "DOCUMENT"):
        comp = {"type": "HEADER", "format": htype}
        if raw_row.get("header_media_url") or raw_row.get("media_url"):
            comp["media_url"] = (raw_row.get("header_media_url") or raw_row.get("media_url")).strip()
        elif raw_row.get("header_media_file") or raw_row.get("media_file"):
            comp["media_file"] = (raw_row.get("header_media_file") or raw_row.get("media_file")).strip()
        components.append(comp)
    elif htype == "LOCATION":
        components.append({"type": "HEADER", "format": "LOCATION"})
    elif (htype in ("TEXT", "HEADER") or (not htype and (raw_row.get("header_text") or raw_row.get("header")))) and (
        raw_row.get("header_text") or raw_row.get("header")
    ):
        components.append(
            {
                "type": "HEADER",
                "format": "TEXT",
                "text": (raw_row.get("header_text") or raw_row.get("header")).strip(),
            }
        )
    # 2. BODY
    body_text = (raw_row.get("body") or raw_row.get("body_text") or "").strip()
    if body_text:
        # Normalize line endings and collapse 3+ consecutive newlines (Meta Rule: max 2)
        body_text = body_text.replace("\r\n", "\n").replace("\r", "\n")
        body_text = re.sub(r"[ \t]+\n", "\n", body_text)
        body_text = re.sub(r"\n{3,}", "\n\n", body_text)
        body_text = re.sub(r"[ \t]+([.,!?:;])", r"\1", body_text)
        body_text = re.sub(r"([A-Za-z0-9])(<[^>]+>)", r"\1 \2", body_text)
        body_text = re.sub(r"(<[^>]+>)([A-Za-z0-9])", r"\1 \2", body_text)
        body_text = re.sub(r"([A-Za-z0-9])(\{#[^#]+#\})", r"\1 \2", body_text)
        placeholders = []

        def _repl(m):
            idx = len(placeholders) + 1
            placeholders.append(m.group(0))
            return f"{{{{{idx}}}}}"

        pattern = r"(\{\{\d+\}\}|\{\{[a-zA-Z0-9_]+\}\}|<[^>]+>|\{#[^#]+#\}|\[[a-zA-Z0-9_]+\]|\{[a-zA-Z0-9_]+\})"
        body_text = re.sub(pattern, _repl, body_text)
        # Strictly never emit a FOOTER component — merge any footer/T&C text into BODY
        footer_text = (raw_row.get("footer") or raw_row.get("footer_text") or "").strip()
        if footer_text and footer_text.lower() not in body_text.lower():
            body_text = f"{body_text.strip()}\n\n{footer_text}"
        components.append({"type": "BODY", "text": body_text.strip()})
    # 4. BUTTONS
    btype = (raw_row.get("button_type") or "").strip().upper()
    btext = (raw_row.get("button_text") or "").strip()
    burl = (raw_row.get("button_url") or "").strip()
    bexample = (raw_row.get("button_url_example") or "").strip()

    if btype in ("URL", "") and btext and burl:
        btn_data = {
            "type": "URL",
            "text": btext,
            "url": burl,
        }
        if bexample:
            btn_data["example"] = [bexample]
        components.append(
            {
                "type": "BUTTONS",
                "buttons": [btn_data],
            }
        )
    elif btype in ("QUICK_REPLY", "QUICKREPLY") and btext:
        btn_items = [{"type": "QUICK_REPLY", "text": item.strip()} for item in btext.split("|") if item.strip()]
        if btn_items:
            components.append(
                {
                    "type": "BUTTONS",
                    "buttons": btn_items,
                }
            )

    return components


_DYNAMIC_FIELD_ALIASES = {
    "name": "template_name",
    "campaign": "template_name",
    "campaign_name": "template_name",
    "campaign_title": "template_name",
    "copy_id": "template_name",
    "copy_name": "template_name",
    "template": "template_name",
    "template_id": "template_name",
    "template_title": "template_name",
    "message": "body",
    "message_body": "body",
    "message_copy": "body",
    "message_text": "body",
    "copy": "body",
    "copy_text": "body",
    "content": "body",
    "content_copy": "body",
    "text": "body",
    "template_text": "body",
    "whatsapp_copy": "body",
    "whatsapp_message": "body",
    "action": "button_text",
    "action_label": "button_text",
    "button_label": "button_text",
    "call_to_action": "button_text",
    "cta": "button_text",
    "cta_label": "button_text",
    "action_link": "button_url",
    "button_link": "button_url",
    "cta_link": "button_url",
    "cta_url": "button_url",
    "link": "button_url",
    "url": "button_url",
    "heading": "header_text",
    "headline": "header_text",
    "header": "header_text",
    "header_copy": "header_text",
    "disclaimer": "footer_text",
    "terms": "footer_text",
    "terms_conditions": "footer_text",
    "language_code": "language",
    "lang": "language",
    "locale": "language",
    "message_category": "category",
    "purpose": "category",
    "template_category": "category",
}
_DYNAMIC_METADATA_FIELDS = {
    "template_name",
    "body",
    "button_text",
    "button_url",
    "header_text",
    "footer_text",
    "language",
    "category",
    "client",
    "channel",
    "waba_id",
    "source_ref",
    "header_type",
    "header_format",
    "button_type",
    "button_url_example",
    "components",
    "address",
    "date",
    "email",
    "id",
    "phone",
    "status",
}


def _dynamic_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _canonicalize_dynamic_row(raw_row: dict) -> dict[str, str]:
    """Map human column labels to a small semantic vocabulary without requiring a schema."""
    canonical: dict[str, str] = {}
    for raw_key, raw_value in raw_row.items():
        value = str(raw_value or "").strip()
        if not value:
            continue
        key = _dynamic_key(raw_key)
        target = _DYNAMIC_FIELD_ALIASES.get(key, key)
        canonical.setdefault(target, value)
    return canonical


def _dynamic_body_value(row: dict[str, str]) -> str:
    body = row.get("body", "").strip()
    if body:
        return body

    try:
        from briefing_parser import is_valid_template_copy
    except Exception:

        def is_valid_template_copy(value: str) -> bool:
            return len(value.split()) >= 6

    candidates = []
    for key, value in row.items():
        if key in _DYNAMIC_METADATA_FIELDS or not value.strip():
            continue
        clean = value.strip()
        if clean.startswith(("http://", "https://")) or clean.isdigit():
            continue
        if len(clean) < 8:
            continue
        lower = clean.lower()
        has_message_signal = any(
            token in lower
            for token in (
                "dear",
                "hello",
                "offer",
                "loan",
                "apply",
                "otp",
                "code",
                "payment",
                "account",
                "approved",
                "due",
                "click",
                "visit",
            )
        )
        if is_valid_template_copy(clean) or (len(clean.split()) >= 6 and has_message_signal):
            candidates.append(clean)
    return max(candidates, key=len, default="")


def _dynamic_template_name(row: dict[str, str], source_name: str, row_number: int) -> str:
    raw_name = row.get("template_name", "").strip()
    if raw_name:
        candidate = raw_name
    else:
        stem = Path(source_name).stem
        candidate = f"{stem}_{row_number}"
    clean = re.sub(r"[^a-zA-Z0-9]+", "_", candidate).strip("_").lower()
    prefix = normalize_campaign_name(clean or f"template_{row_number}")
    if raw_name:
        return prefix[:60]
    digest = hashlib.sha256(f"{source_name}\0{row_number}\0{_dynamic_body_value(row)}".encode()).hexdigest()[:12]
    return f"{prefix[:47].rstrip('_')}_{digest}"


def _dynamic_row_to_submission(
    raw_row: dict,
    source_name: str,
    row_number: int,
    client: str,
    waba_cache: dict[str, str],
) -> TemplateSubmission | None:
    """Build a submission from arbitrary content columns when no standard schema is present."""
    row = _canonicalize_dynamic_row(raw_row)
    body = _dynamic_body_value(row)
    if not body:
        return None

    parsed = parse_single_cell_whatsapp_block(body, client=client)
    header = row.get("header_text") or (parsed.get("header") if "\n" in body else None)
    clean_body = parsed.get("body") or body
    components: list[dict] = []
    if header:
        components.append({"type": "HEADER", "format": "TEXT", "text": header[:60]})
    footer = row.get("footer_text", "").strip()
    if footer and footer.lower() not in clean_body.lower():
        clean_body = f"{clean_body.strip()}\n\n{footer}"
    components.append({"type": "BODY", "text": clean_body.strip()})
    has_cta = bool(
        row.get("button_url")
        or row.get("button_text")
        or re.search(
            r"https?://|(?:apply|check|explore|click|tap|claim).{0,30}(?:now|here|offer|online)",
            body,
            re.IGNORECASE,
        )
    )
    button_url = row.get("button_url") or parsed.get("button_url")
    button_text = row.get("button_text") or parsed.get("button_text")
    if has_cta and (button_text or button_url):
        button = {
            "type": "URL",
            "text": (button_text or "Check Offer")[:25],
            "url": button_url or (TATA_CTA_URL if client.lower() in _TATA_GROUP else "https://u3.mnge.co/"),
        }
        if row.get("button_url_example"):
            button["example"] = [row["button_url_example"]]
        elif not row.get("button_url") and parsed.get("button_example"):
            button["example"] = [parsed["button_example"]]
        components.append({"type": "BUTTONS", "buttons": [button]})

    try:
        from briefing_parser import detect_category

        category = row.get("category", "").strip().upper() or detect_category("", clean_body)
        language = row.get("language", "").strip().lower() or _template_cell_language(clean_body)
    except Exception:
        category = row.get("category", "").strip().upper() or "MARKETING"
        language = row.get("language", "").strip().lower() or ""

    template_name = _dynamic_template_name(row, source_name, row_number)
    return TemplateSubmission(
        client=client,
        channel="whatsapp",
        template_name=template_name,
        language=language,
        category=category,
        waba_id=_resolve_row_waba(client, waba_cache),
        components=[TemplateComponent(**component) for component in _normalize_whatsapp_buttons(components, client)],
        source_ref=template_name,
    )


def _resolve_row_waba(row_client: str, cache: dict[str, str]) -> str:
    """Resolve the WABA ID for a row's client, cached per client per file load."""
    c = (row_client or "bajaj").lower()
    if c not in cache:
        try:
            cache[c] = get_waba_id(c) or ""
        except Exception:
            cache[c] = ""
    return cache[c]


def load_from_csv(
    path: str, client: str = "bajaj", source_name: str | None = None, import_notes: list[str] | None = None,
) -> list[TemplateSubmission]:
    """Load standard or dynamically structured WhatsApp rows from CSV."""
    p = Path(path)
    if not p.exists() and (Path("samples") / path).exists():
        p = Path("samples") / path
    waba_cache: dict[str, str] = {}
    rows = []
    dynamic_submissions: list[TemplateSubmission] = []
    skipped_channels = set()
    source_name = Path(source_name or p.name).name
    with open(p, newline="", encoding="utf-8-sig") as f:
        grid = list(csv.reader(f))
        headers = grid[0] if grid else []
        _reject_other_channel_columns(headers)
        if not _has_whatsapp_table_headers(headers):
            sheet_name = Path(source_name).stem
            loose = _loose_template_cells(grid, sheet_name, _template_channel_context([(sheet_name, grid)]))
            native = _native_template_cells(grid, sheet_name)
            if loose or native:
                from briefing_parser import split_multi_campaign_cell
                from sms_brief import _column

                result = []
                for row, col, text, language, scope in loose or native:
                    source_ref = f"{source_name}:{sheet_name}!{_column(col)}{row}"
                    if loose:
                        result.append(_build_loose_whatsapp_submission(
                            text, client, source_name, source_ref, None, waba_cache, import_notes, language=language,
                        ))
                    else:
                        variants = split_multi_campaign_cell(text)
                        for index, block in enumerate(variants, 1):
                            ref = f"{source_ref}#{index}" if len(variants) > 1 else source_ref
                            result.append(_build_single_cell_card_submission(
                                block, client, source_name, ref, language, scope, None, waba_cache,
                            ))
                return result
            return []
        for row_number, values in enumerate(grid[1:], 2):
            raw_row = dict(zip(headers, values))
            clean_row = {
                k.strip(): (v.strip() if v else "") for k, v in raw_row.items()
                if k and _whatsapp_import_channel(k) not in {"sms", "rcs", "pn", "email"}
            }
            channel_label = _canonicalize_dynamic_row(clean_row).get("channel", "")
            row_channel = _whatsapp_import_channel(channel_label)
            if channel_label and row_channel != "whatsapp":
                skipped_channels.add(channel_label.upper())
                continue
            has_standard_components = bool(clean_row.get("components"))
            has_standard_body = bool(clean_row.get("body") or clean_row.get("body_text"))
            has_standard_name = bool(clean_row.get("template_name") or clean_row.get("name"))

            if not has_standard_components and not (has_standard_name and has_standard_body):
                dynamic = _dynamic_row_to_submission(clean_row, source_name, row_number, client, waba_cache)
                if dynamic:
                    dynamic_submissions.append(dynamic)
                    continue

            if not has_standard_name:
                continue

            if clean_row.get("components"):
                try:
                    clean_row["components"] = json.loads(clean_row["components"])
                except json.JSONDecodeError:
                    clean_row["components"] = _flat_row_to_components(clean_row)
            else:
                clean_row["components"] = _flat_row_to_components(clean_row)

            clean_row["client"] = clean_row.get("client") or client
            if not clean_row.get("waba_id"):
                clean_row["waba_id"] = _resolve_row_waba(clean_row["client"], waba_cache)
            if not clean_row.get("category"):
                clean_row["category"] = "MARKETING"

            rows.append(clean_row)

    submissions = [_row_to_submission(row, client=client) for row in rows]
    result = [s for s in [*submissions, *dynamic_submissions] if s.components]
    if skipped_channels and import_notes is not None:
        import_notes.append(f"Excluded non-WhatsApp/unrecognized channel rows: {', '.join(sorted(skipped_channels))}.")
    if not result and skipped_channels:
        raise ValueError(f"No WhatsApp copy found; this CSV contains {', '.join(sorted(skipped_channels))} rows. Select the matching channel.")
    return result


def _whatsapp_import_channel(value) -> str:
    """Recognize short channel labels, never channel words inside customer copy."""
    label = str(value or "").strip().lower()
    if len(label) > 85 or "\n" in label:
        return ""
    match = re.fullmatch(
        r"(whatsapp|wa|sms|rcs|pn|push notification|email)"
        r"(?:[\s_]+(?:retargeting|retaregting|retargetting|retarget|text|body|content|copy|"
        r"title|desp\.?|description|implicit|explicit|promotional|transactional|utility|service|"
        r"carousel|carousal|card|cards|richcard|c?\d+))*",
        label,
    )
    if not match:
        return ""
    channel = match.group(1)
    return {"wa": "whatsapp", "push notification": "pn"}.get(channel, channel)


def _has_whatsapp_table_headers(headers) -> bool:
    """Flat/semantic tables have a copy field, unlike native Channel/language grids."""
    fields = [_DYNAMIC_FIELD_ALIASES.get(_dynamic_key(header), _dynamic_key(header)) for header in headers]
    if fields and fields[0] == "channel" and not any(field in {"template_name", "components"} for field in fields):
        return False
    return any(
        field in {"body", "body_text", "components"} for field in fields
    )


def _reject_other_channel_columns(headers):
    channels = {_whatsapp_import_channel(header) for header in headers} - {""}
    if channels and "whatsapp" not in channels:
        labels = ", ".join(sorted(channel.upper() for channel in channels))
        raise ValueError(f"This file contains explicitly {labels} columns, not WhatsApp copy. Select the matching channel.")


def _load_template_workbook(path):
    """Keep the existing XLS reader and XLSX media/merged-cell support in one place."""
    import openpyxl

    if Path(path).suffix.lower() != ".xls":
        return openpyxl.load_workbook(path, data_only=False)
    from sms_brief import _read_sheets

    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for title, rows in _read_sheets(path, Path(path).name):
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
    return workbook


def _template_context_label(value):
    """Exact structural labels only: 'Link your account' is customer copy, not metadata."""
    from sms_brief import _norm
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+", str(value or "").strip()):
        return True

    label = _norm(value).rstrip(":").replace("_", " ")
    return label in {
        "channel", "regional", "language", "lang", "template name", "campaign name",
        "name", "address", "phone", "mobile", "email", "id", "date", "status",
        "client", "account", "waba id", "bot id", "entity id", "sender id", "esme addr",
        "cta", "link", "url", "time of", "testing", "test mobile", "database",
        "product", "sub product", "campaign tag", "note", "notes", "instruction",
        "instructions", "character", "characters", "character count", "char count",
        "use case", "remark", "remarks", "base", "mentioned in base", "generic",
        "mentioned in database", "as per planner",
    } or label.replace(" ", "_") in _DYNAMIC_METADATA_FIELDS or _has_whatsapp_table_headers([value])


def _template_cell_copy(value):
    """Accept letters in every script without imposing an English or length heuristic."""
    from sms_brief import _LANGUAGES

    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(
        text and not text.startswith("=") and any(char.isalpha() for char in text)
        and not re.fullmatch(r"(?:(?:https?://|www\.)\S+\s*)+", text, re.IGNORECASE)
        and not _template_context_label(text) and not _whatsapp_import_channel(text)
        and text.lower() not in {*_LANGUAGES, "hinglish", "highlish"}
    )


def _template_channel_context(sheets, selected_channel="whatsapp"):
    """Unlabelled sheets cannot inherit a destination from a mixed-channel workbook."""
    return any(
        (_whatsapp_import_channel(title) not in {"", selected_channel})
        or any(_whatsapp_import_channel(value) not in {"", selected_channel}
               or str(value or "").strip().lower() == "channel"
               for row in rows for value in row)
        for title, rows in sheets
    )


def _loose_template_cells(rows, sheet_name, has_channel_context=False, selected_channel="whatsapp"):
    """Only plain message/language grids inherit the operator's selected destination."""
    from sms_brief import _LANGUAGES, _norm

    if re.search(r"planner|calendar", sheet_name, re.IGNORECASE) or sheet_name.strip().lower() in {
        "overview", "summary", "notes", "instructions", "metadata", "readme", "read me",
    }:
        return []
    if has_channel_context and _whatsapp_import_channel(sheet_name) != selected_channel:
        return []
    first = next((row for row in rows if any(value is not None and str(value).strip() for value in row)), [])
    column_languages = {
        ci: _LANGUAGES[_norm(value)] for ci, value in enumerate(first, 1) if _norm(value) in _LANGUAGES
    }
    if any(_norm(value) not in {*_LANGUAGES, "language", "lang", "regional", "generic", ""}
           for value in first):
        column_languages = {}
    row_languages = not column_languages and any(row and _norm(row[0]) in _LANGUAGES for row in rows)
    language_grid = bool(column_languages or row_languages)
    if any(
        (_template_context_label(value) and not (language_grid and _norm(value) in {"language", "lang", "regional", "generic", "control"}))
        or _whatsapp_import_channel(value)
        for row in rows for value in row if value is not None
    ):
        return []
    cells = []
    for ri, row in enumerate(rows, 1):
        label = _norm(row[0]) if row else ""
        if row_languages and label not in {*_LANGUAGES, "generic", "control"}:
            continue
        for ci, value in enumerate(row, 1):
            if column_languages and ci not in column_languages:
                continue
            if row_languages and ci == 1:
                continue
            if _template_cell_copy(value):
                cells.append((ri, ci, value, column_languages.get(ci, "") or _LANGUAGES.get(label, ""), ""))
    return cells


def _template_cell_language(text, declared="", source_ref="", import_notes=None):
    from briefing_parser import detect_language

    language = detect_language(text, column_name=declared)
    if language == "und":
        if import_notes is not None:
            import_notes.append(f"{source_ref}: Language review required; source script does not identify a unique supported language. Copy is unchanged.")
        return ""
    return language


def _build_loose_whatsapp_submission(text, client, source_name, source_ref, media, waba_cache, import_notes, language=""):
    from briefing_parser import detect_category

    digest = hashlib.sha256(f"{client}\0{source_ref}\0{text}".encode()).hexdigest()[:12]
    prefix = normalize_whatsapp_template_name(f"{client}_{Path(source_name).stem}")
    components = []
    if media:
        components.append(TemplateComponent(
            type="HEADER", format=media["kind"], image_bytes=media["bytes"], file_type=media["mime_type"],
        ))
    components.append(TemplateComponent(type="BODY", text=text))
    return TemplateSubmission(
        client=client.lower(), channel="whatsapp", template_name=f"{prefix[:47].rstrip('_')}_{digest}",
        language=_template_cell_language(text, declared=language, source_ref=source_ref, import_notes=import_notes),
        category=detect_category("", text), waba_id=_resolve_row_waba(client, waba_cache),
        components=components, source_ref=source_ref,
    )


def _native_template_cells(rows, sheet_name, selected_channel="whatsapp"):
    """Keep explicit channel state local to each label column and retain cell coordinates."""
    from sms_brief import _language, _metadata, _norm

    width = max(map(len, rows), default=0)
    rows = [list(row) + [None] * (width - len(row)) for row in rows]
    if not width:
        return []
    cells = {}

    def add(ri, ci, language="", scope=""):
        if _template_cell_copy(rows[ri][ci]):
            cells[ri, ci] = (ri + 1, ci + 1, rows[ri][ci], language, scope)

    # Language | SMS | WA | PN (also native Template Name | SMS 2 | WA).
    matrix_headers = {
        ri for ri, row in enumerate(rows)
        if (_norm(row[0]) in {"language", "lang", "template name", "template_name"}
            and any(_whatsapp_import_channel(value) for value in row[1:]))
        or (any(row) and all(not value or _whatsapp_import_channel(value) for value in row))
    }
    if matrix_headers:
        columns = {}
        language_matrix = False
        for ri, row in enumerate(rows):
            if ri in matrix_headers:
                columns = {ci: str(value) for ci, value in enumerate(row) if _whatsapp_import_channel(value) == selected_channel}
                language_matrix = _norm(row[0]) in {"language", "lang"}
            elif any(row):
                if language_matrix and not _language(row[0]):
                    columns = {}
                    continue
                for ci, scope in columns.items():
                    add(ri, ci, _language(row[0]), scope)
        return list(cells.values())

    anchors = sorted({
        ci for row in rows for ci, value in enumerate(row)
        if _norm(value) == "channel"
        or (_whatsapp_import_channel(value) and ci + 1 < width and any(_template_cell_copy(r[ci + 1]) for r in rows))
    })
    if not anchors and _whatsapp_import_channel(sheet_name) == selected_channel and any(_language(row[0]) for row in rows):
        for ri, row in enumerate(rows):
            if _language(row[0]) or _norm(row[0]) in {"generic", "control"}:
                for ci in range(1, width):
                    add(ri, ci, _language(row[0]), sheet_name)
        return list(cells.values())
    if not anchors and _whatsapp_import_channel(sheet_name) == selected_channel and any(
        _metadata(row[0]) or _norm(row[0]) in {"campaign name", "campaign_name"} for row in rows
    ):
        anchors = [0]
    if not anchors:
        if _whatsapp_import_channel(sheet_name) == selected_channel:
            for ri, row in enumerate(rows):
                for ci in range(width):
                    add(ri, ci, _language(row[0]), sheet_name)
        return list(cells.values())

    for index, anchor in enumerate(anchors):
        end = anchors[index + 1] if index + 1 < len(anchors) else width
        # Without headers, the channel owns every copy column up to the next channel block.
        columns = {ci: "" for ci in range(anchor + 1, end)}
        scope = sheet_name if _whatsapp_import_channel(sheet_name) == selected_channel else ""
        active = bool(scope)
        for ri, row in enumerate(rows):
            value = row[anchor]
            label = _norm(value)
            channel = _whatsapp_import_channel(value)
            header = label in {"channel", "regional"} or (
                channel and not any(_template_cell_copy(row[ci]) for ci in range(anchor + 1, end))
                and any(
                    _language(row[ci]) or re.fullmatch(r"[a-z]|\d+\s*-\s*\d+|generic", _norm(row[ci]))
                    or _has_whatsapp_table_headers([row[ci]]) or "content" in _norm(row[ci])
                    for ci in range(anchor + 1, end) if row[ci] is not None
                )
            )
            if header:
                columns = {
                    ci: _language(row[ci]) for ci in range(anchor + 1, end)
                    if row[ci] is not None and not _metadata(row[ci])
                    and (_language(row[ci]) or re.fullmatch(r"[a-z]|\d+\s*-\s*\d+|generic", _norm(row[ci]))
                         or _has_whatsapp_table_headers([row[ci]]) or "content" in _norm(row[ci]))
                } or {ci: "" for ci in range(anchor + 1, end)}
                scope = str(value) if channel == selected_channel else ""
                active = bool(scope)
                continue
            if channel:
                scope = str(value) if channel == selected_channel else ""
                active = bool(scope)
            elif label in {"campaign name", "campaign_name"}:
                active = bool(scope)
                continue
            elif _metadata(value):
                active = False
                continue
            elif label and not _language(value) and not re.fullmatch(r"c\d+|[a-z]", label):
                active = False
                continue
            if active:
                for ci, language in columns.items():
                    add(ri, ci, language or _language(value), scope)
    return list(cells.values())


def _sheet_anchored_media(sheet, positions, import_notes=None):
    """Bind only exact-column or sole-copy same-row drawings; ambiguity means no creative."""
    from sms_brief import _column
    result = {}
    by_row = {}
    for row, col in positions:
        by_row.setdefault(row, []).append(col)
    for image in sheet._images:
        anchor = getattr(image.anchor, "_from", None)
        if anchor is None:
            continue
        row, col = anchor.row + 1, anchor.col + 1
        candidates = by_row.get(row, [])
        target = (row, col) if col in candidates else ((row, candidates[0]) if len(candidates) == 1 else None)
        if target:
            result.setdefault(target, []).append(image)
        elif import_notes is not None:
            import_notes.append(f"{sheet.title}!{_column(col)}{row}: embedded creative has no unambiguous copy-cell anchor; not assigned.")
    media = {}
    for target, images in result.items():
        if len(images) == 1:
            image = images[0]
            raw = image._data()
            kind, mime_type = _detect_media_kind(f"creative.{image.format}", raw)
            media[target] = {"kind": kind, "mime_type": mime_type, "bytes": raw}
        elif import_notes is not None:
            row, col = target
            import_notes.append(f"{sheet.title}!{_column(col)}{row}: multiple embedded creatives share this copy-cell anchor; not assigned.")
    return media


def _build_single_cell_card_submission(
    block, client, source_name, source_ref, language, scope, media, waba_cache,
) -> TemplateSubmission:
    from briefing_parser import detect_category

    parsed = parse_single_cell_whatsapp_block(block, client=client)
    digest = hashlib.sha256(f"{client}\0{source_ref}\0{block}".encode()).hexdigest()[:12]
    prefix = normalize_whatsapp_template_name(f"{client}_{Path(source_name).stem}")
    name = f"{prefix[:47].rstrip('_')}_{digest}"
    components = []
    if media:
        components.append({
            "type": "HEADER", "format": media["kind"], "image_bytes": media["bytes"], "file_type": media["mime_type"],
        })
    elif parsed.get("header"):
        components.append({"type": "HEADER", "format": "TEXT", "text": parsed["header"]})
    components.append({"type": "BODY", "text": parsed["body"].strip()})
    components.append({
        "type": "BUTTONS", "buttons": [{
            "type": "URL", "text": parsed["button_text"], "url": parsed["button_url"], "example": [parsed["button_example"]],
        }],
    })
    return TemplateSubmission(
        client=client.lower(), channel="whatsapp", template_name=name,
        language=_template_cell_language(block, declared=language, source_ref=source_ref),
        category=detect_category(scope, block),
        waba_id=_resolve_row_waba(client, waba_cache),
        components=[TemplateComponent(**component) for component in _normalize_whatsapp_buttons(components, client)],
        source_ref=source_ref,
    )


def load_from_excel(
    path: str, client: str = "bajaj", source_name: str | None = None, import_notes: list[str] | None = None,
) -> list[TemplateSubmission]:
    """Read all worksheets; only plain unlabelled grids inherit the selected WhatsApp channel."""
    import openpyxl
    from briefing_parser import split_multi_campaign_cell
    from sms_brief import _copy, _metadata, _norm

    source_name = Path(source_name or path).name
    notes = import_notes if import_notes is not None else []
    notes.append("All worksheets and months are considered; plain message grids use the selected WhatsApp channel, while labelled briefs retain explicit routing.")
    waba_cache = {}
    submissions = []
    workbook = _load_template_workbook(path)
    try:
        sheets = [(sheet, list(sheet.iter_rows(values_only=True))) for sheet in workbook]
        has_channel_context = _template_channel_context([(sheet.title, rows) for sheet, rows in sheets])
        for sheet, rows in sheets:
            if not rows:
                continue
            if re.search(r"planner|calendar", sheet.title, re.IGNORECASE):
                notes.append(f"{sheet.title}: planner/calendar worksheet excluded.")
                continue
            sheet_channel = _whatsapp_import_channel(sheet.title)
            if sheet_channel and sheet_channel != "whatsapp":
                notes.append(f"{sheet.title}: explicitly {sheet_channel.upper()} worksheet excluded, regardless of copied labels.")
                continue
            headers = [str(value or "").strip() for value in rows[0]]
            if _has_whatsapp_table_headers(headers):
                positions = [(ri, ci + 1) for ri, row in enumerate(rows[1:], 2) for ci, value in enumerate(row)
                             if ci < len(headers) and _has_whatsapp_table_headers([headers[ci]]) and value]
                media = _sheet_anchored_media(sheet, positions, notes)
                for ri, row in enumerate(rows[1:], 2):
                    raw = {header: str(value).strip() if value is not None else "" for header, value in zip(headers, row, strict=False) if header}
                    canonical = _canonicalize_dynamic_row(raw)
                    channel_label = canonical.get("channel", "")
                    if channel_label and _whatsapp_import_channel(channel_label) != "whatsapp":
                        notes.append(f"{sheet.title}!A{ri}: non-WhatsApp/unrecognized channel row excluded.")
                        continue
                    standard = bool(raw.get("components") or ((raw.get("template_name") or raw.get("name")) and (raw.get("body") or raw.get("body_text"))))
                    if standard:
                        try:
                            raw["components"] = json.loads(raw["components"]) if raw.get("components") else _flat_row_to_components(raw)
                        except json.JSONDecodeError:
                            raw["components"] = _flat_row_to_components(raw)
                        for component in raw["components"]:
                            if component.get("type") == "HEADER" and component.get("format") in {"IMAGE", "VIDEO", "DOCUMENT"} and not (component.get("media_url") or component.get("media_file")):
                                matches = [item for (row_num, _), item in media.items() if row_num == ri and item["kind"] == component["format"]]
                                if len(matches) == 1:
                                    component.update(image_bytes=matches[0]["bytes"], file_type=matches[0]["mime_type"])
                        raw["client"] = raw.get("client") or client
                        raw["waba_id"] = raw.get("waba_id") or _resolve_row_waba(raw["client"], waba_cache)
                        raw["category"] = raw.get("category") or "MARKETING"
                        submission = _row_to_submission(raw, client)
                    else:
                        submission = _dynamic_row_to_submission(raw, f"{source_name}:{sheet.title}", ri, client, waba_cache)
                    if submission and submission.components:
                        submission.source_ref = canonical.get("source_ref") or f"{source_name}:{sheet.title}!{openpyxl.utils.get_column_letter(next((ci for ci, h in enumerate(headers, 1) if _has_whatsapp_table_headers([h])), 1))}{ri}"
                        submissions.append(submission)
                continue
            loose = _loose_template_cells(rows, sheet.title, has_channel_context)
            cells = loose or _native_template_cells(rows, sheet.title)
            media = _sheet_anchored_media(sheet, [
                (ri, ci) for ri, row in enumerate(rows, 1) for ci, value in enumerate(row, 1) if _template_cell_copy(value)
            ], notes)
            for row, col, text, language, scope in cells:
                source_ref = f"{source_name}:{sheet.title}!{openpyxl.utils.get_column_letter(col)}{row}"
                if loose:
                    submissions.append(_build_loose_whatsapp_submission(
                        text, client, source_name, source_ref, media.get((row, col)), waba_cache, notes, language=language,
                    ))
                    continue
                variants = split_multi_campaign_cell(text)
                for index, block in enumerate(variants, 1):
                    ref = f"{source_ref}#{index}" if len(variants) > 1 else source_ref
                    submissions.append(_build_single_cell_card_submission(
                        block, client, source_name, ref, language, scope, media.get((row, col)), waba_cache,
                    ))
            selected = {(row, col) for row, col, *_ in cells}
            excluded = [
                (ri, ci) for ri, row in enumerate(rows, 1) for ci, value in enumerate(row, 1)
                if _copy(value) and (ri, ci) not in selected
                and not (ci > 1 and (_metadata(row[0]) or _norm(row[0]) in {"campaign name", "campaign_name"}))
            ]
            if excluded:
                refs = ", ".join(f"{sheet.title}!{openpyxl.utils.get_column_letter(col)}{row}" for row, col in excluded)
                note = f"Excluded {len(excluded)} non-WhatsApp/unscoped copy cells (confirm channel before import): {refs}."
                notes.append(note)
                logger.warning(note)
    finally:
        workbook.close()
    if not submissions:
        raise ValueError("No WhatsApp copy found; this workbook contains explicitly SMS/RCS/PN, planner, metadata or ambiguous content. Select the matching channel or label the WhatsApp section.")
    return submissions


def load_from_json(path: str) -> list[TemplateSubmission]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [_row_to_submission(row) for row in data]


def load_from_list(rows: list[dict], client: str = "bajaj") -> list[TemplateSubmission]:
    return [_row_to_submission(row, client=client) for row in rows]




def _score_single_row_routing(
    explicit_client: str,
    raw_header_val: str,
    comp_headers: list[str],
    comp_text: str,
    tname: str,
    scores: dict,
    reasons: dict,
) -> None:
    for rule in ACCOUNT_ROUTING_RULES:
        r_id = rule["id"]
        if explicit_client and r_id in explicit_client:
            scores[r_id] += 20
            if f"Explicit account column: '{explicit_client}'" not in reasons[r_id]:
                reasons[r_id].append(f"Explicit account column: '{explicit_client}'")
        for tag in rule["headers"]:
            if tag in raw_header_val or any(tag in ch for ch in comp_headers):
                scores[r_id] += 10
                if f"Header tag '{tag}'" not in reasons[r_id]:
                    reasons[r_id].append(f"Header tag '{tag}'")
        for prefix in rule["name_prefixes"]:
            if tname.startswith(prefix):
                scores[r_id] += 5
                if f"Template prefix '{prefix}'" not in reasons[r_id]:
                    reasons[r_id].append(f"Template prefix '{prefix}'")
        for kw in rule["keywords"]:
            if kw in comp_text or kw in tname:
                scores[r_id] += 2
                if f"Keyword '{kw}'" not in reasons[r_id]:
                    reasons[r_id].append(f"Keyword '{kw}'")


ACCOUNT_ROUTING_RULES = [
    {
        "id": "tchfl",
        "name": "TCHFL — Housing Finance (HLTATA)",
        "headers": ["HLTATA", "TCHFL", "HL_TATA", "HOUSING"],
        "name_prefixes": ["hfl_", "tchfl_", "hl_"],
        "keywords": ["housing finance", "home loan", "tchfl", "hltata", "housing"],
    },
    {
        "id": "tcl_promo",
        "name": "TCL — Promotional (PL, BL, UCL, NCL, LAP)",
        "headers": ["PLTATA", "TATABL", "ALTATA", "TCLLAP", "Tatacl", "TCLPROMO"],
        "name_prefixes": ["pl_", "bl_", "ucl_", "ncl_", "lap_", "promo_"],
        "keywords": [
            "personal loan",
            "business loan",
            "used car loan",
            "two wheeler",
            "promotional",
            "pltata",
            "tatabl",
        ],
    },
    {
        "id": "tcl_trans",
        "name": "TCL — Transactional (LAP, Services & Collections)",
        "headers": ["TCLLAP", "Tatacl", "TCLTRANS"],
        "name_prefixes": ["trans_", "srv_", "coll_", "serv_"],
        "keywords": ["transactional", "emi reminder", "overdue", "collections", "statement"],
    },
    {
        "id": "wealth",
        "name": "Tata Wealth & Securities (TATAWL)",
        "headers": ["TATAWL", "WEALTH", "TATA_WEALTH"],
        "name_prefixes": ["wl_", "wealth_", "sec_"],
        "keywords": ["wealth", "securities", "portfolio", "demat", "trading", "tatawl"],
    },
    {
        "id": "moneyfy",
        "name": "Tata Moneyfy",
        "headers": ["MONEYFY", "TATA_MONEYFY"],
        "name_prefixes": ["mf_", "moneyfy_"],
        "keywords": ["moneyfy", "mutual fund", "sip", "investment"],
    },
    {
        "id": "bajaj",
        "name": "Bajaj Finserv",
        "headers": ["BAJAJ", "BFDL", "BAJAJ_FINSERV"],
        "name_prefixes": ["bajaj_", "bfdl_"],
        "keywords": ["bajaj", "finserv", "bfdl", "emi card", "bfl"],
    },
]


def detect_spreadsheet_account(
    submissions_or_rows: list,
    current_account: str = "bajaj",
) -> dict:
    """
    Inspect spreadsheet rows, template names, header tags, and body text
    to infer the target sub-account with a confidence score and explanation.
    """
    if not submissions_or_rows:
        return {
            "detected_account_id": current_account,
            "detected_account_name": current_account.title(),
            "confidence": 0.0,
            "matched_reasons": ["No rows to inspect"],
            "is_mismatch": False,
            "current_account": current_account,
        }

    scores = {rule["id"]: 0 for rule in ACCOUNT_ROUTING_RULES}
    reasons = {rule["id"]: [] for rule in ACCOUNT_ROUTING_RULES}

    for item in submissions_or_rows:
        row = item if isinstance(item, dict) else (getattr(item, "__dict__", None) or {})
        tname = str(row.get("template_name") or getattr(item, "template_name", "") or "").lower()

        # Check components text
        comp_text = ""
        comp_headers = []
        components = row.get("components") or getattr(item, "components", []) or []
        for comp in components:
            c = comp if isinstance(comp, dict) else (getattr(comp, "__dict__", None) or {})
            if c.get("text"):
                comp_text += " " + str(c.get("text", "")).lower()
            if c.get("type") == "HEADER":
                h_text = str(c.get("text") or "").upper()
                if h_text:
                    comp_headers.append(h_text)

        # Check raw header columns (e.g. sender_id, header, client, sub_product)
        explicit_client = str(row.get("client") or row.get("account") or row.get("sub_product") or "").lower()
        raw_header_val = str(row.get("header") or row.get("sender_id") or row.get("dlt_header") or "").upper()

        _score_single_row_routing(explicit_client, raw_header_val, comp_headers, comp_text, tname, scores, reasons)
    # Pick highest score
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_id, best_score = sorted_scores[0]

    # Calculate confidence (0.0 to 1.0)
    total_score = sum(scores.values())
    confidence = (best_score / total_score) if total_score > 0 else 0.0

    if best_score == 0:
        best_id = current_account
        confidence = 0.0
        reasons[best_id] = ["No distinct brand indicators found; retained current account."]

    rule_meta = next((r for r in ACCOUNT_ROUTING_RULES if r["id"] == best_id), None)
    best_name = rule_meta["name"] if rule_meta else best_id.title()

    curr_norm = (current_account or "bajaj").lower().strip()
    is_mismatch = (best_id != curr_norm) and (confidence >= 0.35)

    return {
        "detected_account_id": best_id,
        "detected_account_name": best_name,
        "confidence": round(confidence, 2),
        "matched_reasons": reasons.get(best_id, [])[:3],
        "is_mismatch": is_mismatch,
        "current_account": current_account,
        "all_scores": {k: v for k, v in scores.items() if v > 0},
    }
