"""
Input loader for Karix RCS Bot Builder & DLT templates.

Turns raw rows (CSV, XLSX, JSON) into validated RcsTemplateSubmission objects.
Supports text messages, rich cards, suggestions (URL, Reply, Dialer), and variables.
"""

import csv
import json
import logging
import re
from pathlib import Path

from rcs_config import get_rcs_bot_id, get_rcs_entity_id
from rcs_models import RcsTemplateSubmission

logger = logging.getLogger(__name__)


def infer_cta_link_and_button(text: str) -> tuple[str, str]:
    """
    If no explicit CTA button or link is given in the brief:
    Infers the most relevant Tata Capital landing page and button label based on copy keywords.
    """
    t_lower = text.lower()

    if any(w in t_lower for w in ("home loan", "housing", "property", "mortgage")):
        return "Check Rates", "https://www.tatacapital.com/home-loan.html"
    elif any(w in t_lower for w in ("business loan", "enterprise", "msme", "sme", "working capital")):
        return "Apply Business", "https://www.tatacapital.com/business-loan.html"
    elif any(w in t_lower for w in ("vehicle", "car", "2-wheeler", "bike", "auto")):
        return "Explore Vehicle Loan", "https://www.tatacapital.com/vehicle-loan.html"
    elif any(w in t_lower for w in ("eligibility", "eligible", "check offer", "check my offer")):
        return "Check Eligibility", "https://www.tatacapital.com/personal-loan.html"
    elif any(w in t_lower for w in ("claim", "pre-approved", "pre approved", "exclusive")):
        return "Claim Your Offer", "https://www.tatacapital.com/personal-loan.html"
    elif any(w in t_lower for w in ("feedback", "survey", "rating", "experience", "satisfied")):
        return "Rate Experience", "https://www.tatacapital.com"
    else:
        return "Apply Now", "https://www.tatacapital.com/personal-loan.html"


def parse_single_cell_card_block(cell_text: str) -> dict:
    """
    Decompose an unstructured marketing card text block (from Excel cells) into:
    - card_title
    - card_description
    - button_text
    - button_url
    """
    if not cell_text:
        return {
            "card_title": "",
            "card_description": "",
            "button_text": "Apply Now",
            "button_url": "https://www.tatacapital.com/personal-loan.html",
        }

    lines = [line.strip() for line in cell_text.splitlines() if line.strip()]

    inferred_text, inferred_url = infer_cta_link_and_button(cell_text)
    button_text = inferred_text
    button_url = inferred_url
    clean_lines = []

    for line in lines:
        is_cta = False
        # 1. Match CTA Button <Text> or CTA button<Text> or CTA<Text>
        m_cta = re.search(r'CTA\s*(?:Button|button)?\s*[:<\[]\s*([^>\]<]+)\s*[>\]]', line, re.IGNORECASE)
        if m_cta:
            cand = m_cta.group(1).strip()
            if cand.lower() not in ("link", "url"):
                button_text = cand
            is_cta = True

        # 2. Match [Button Text] <link> or <Button Text> <link>
        m_link = re.search(r'[\[<]([^>\]<]+)[\]>]\s*(?:<link>|\[link\])', line, re.IGNORECASE)
        if m_link and not is_cta:
            cand = m_link.group(1).strip()
            if cand.lower() not in ("link", "url"):
                button_text = cand
            is_cta = True

        # 3. Match prompt lines like "Tap to proceed ⬇️" or "Tap below to check eligibility⬇️"
        if re.search(r'^(?:Tap|Click|Press)\s+(?:below|here|to\s+proceed|to\s+check|to\s+apply).*?(?:⬇️|->|:|here)?$', line, re.IGNORECASE):
            is_cta = True

        if not is_cta:
            clean_lines.append(line)

    full_desc = "\n\n".join(clean_lines)
    first_line = clean_lines[0] if clean_lines else "Special Offer"
    clean_title = re.sub(r'<[^>]+>|\[[^\]]+\]|\{[^}]+\}', '', first_line).strip()
    clean_title = re.sub(r'^[,\s:–—\-]+|[,\s:–—\-]+$', '', clean_title)
    if re.match(r'^(?:Dear|Hi|Hello)\b', clean_title, re.IGNORECASE) or len(clean_title) < 4:
        clean_title = "Pre-Approved Loan Offer ✨"

    return {
        "card_title": clean_title[:100],
        "card_description": full_desc,
        "button_text": button_text,
        "button_url": button_url,
    }

def _build_suggestions_from_row(row: dict) -> list[dict]:
    """Parse button columns into Karix RCS suggestion dictionaries."""
    suggestions = []

    # If suggestions array is already provided as JSON
    if row.get("suggestions"):
        if isinstance(row["suggestions"], list):
            return row["suggestions"]
        try:
            return json.loads(row["suggestions"])
        except (json.JSONDecodeError, TypeError):
            pass

    btype = (row.get("button_type") or row.get("suggestion_type") or "").strip().upper()
    btext = (row.get("button_text") or row.get("suggestion_text") or "").strip()
    burl = (row.get("button_url") or row.get("url") or "").strip()
    bphone = (row.get("button_phone") or row.get("phone") or row.get("phone_number") or "").strip()

    if btext:
        if "|" in btext and btype in ("", "REPLY", "SUGGESTION"):
            for item in btext.split("|"):
                clean = item.strip()
                if clean:
                    suggestions.append({
                        "suggestionType": "reply",
                        "text": clean,
                        "postbackData": clean.lower().replace(" ", "_"),
                    })
        elif btype in ("URL", "URL_ACTION", "LINK") or burl or True:
            suggestions.append({
                "suggestionType": "url_action",
                "text": btext or "Apply Now",
                "postbackData": btext.lower().replace(" ", "_") if btext else "apply_now",
                "url": burl or "https://www.tatacapital.com",
            })
        elif btype in ("DIALER", "DIALER_ACTION", "CALL", "PHONE") or bphone:
            suggestions.append({
                "suggestionType": "dialer_action",
                "text": btext or "Call Now",
                "postbackData": btext.lower().replace(" ", "_") if btext else "call_now",
                "phoneNumber": bphone or "+919999999999",
            })
        else:
            suggestions.append({
                "suggestionType": "reply",
                "text": btext,
                "postbackData": btext.lower().replace(" ", "_"),
            })

    return suggestions


def _build_carousel_cards_from_row(row: dict) -> list[dict]:
    """Parse multiple cards for carousel templates from pipe-separated columns or JSON."""
    if row.get("carousel_cards"):
        if isinstance(row["carousel_cards"], list):
            return row["carousel_cards"]
        try:
            return json.loads(row["carousel_cards"])
        except (json.JSONDecodeError, TypeError):
            pass

    titles = [t.strip() for t in str(row.get("card_title") or row.get("title") or "").split("|") if t.strip()]
    descriptions = [d.strip() for d in str(row.get("body") or row.get("card_description") or row.get("text_message") or row.get("description") or "").split("|") if d.strip()]
    media_urls = [u.strip() for u in str(row.get("media_url") or row.get("image_url") or row.get("image") or "").split("|") if u.strip()]
    button_texts = [b.strip() for b in str(row.get("button_text") or row.get("button_name") or "").split("|") if b.strip()]
    button_urls = [u.strip() for u in str(row.get("button_url") or row.get("link") or "").split("|") if u.strip()]
    button_types = [t.strip().upper() for t in str(row.get("button_type") or "").split("|") if t.strip()]

    max_cards = max(len(titles), len(descriptions), len(media_urls), len(button_texts), 2)

    cards = []
    for i in range(max_cards):
        c_title = titles[i] if i < len(titles) else (f"Card {i+1}" if titles else "")
        c_desc = descriptions[i] if i < len(descriptions) else (descriptions[0] if descriptions else "")
        c_url = media_urls[i] if i < len(media_urls) else (media_urls[0] if media_urls else "https://www.tatacapital.com/content/dam/tata-capital/header-logo/tata-capital-logo.png")

        card_suggs = []
        if i < len(button_texts):
            btext = button_texts[i]
            btype = button_types[i] if i < len(button_types) else (button_types[0] if button_types else "URL")
            b_link = button_urls[i] if i < len(button_urls) else (button_urls[0] if button_urls else "https://www.tatacapital.com")

            if btype in ("URL", "URL_ACTION", "LINK") or b_link:
                card_suggs.append({
                    "suggestionType": "url_action",
                    "text": btext,
                    "postbackData": btext.lower().replace(" ", "_"),
                    "url": b_link,
                })
            else:
                card_suggs.append({
                    "suggestionType": "reply",
                    "text": btext,
                    "postbackData": btext.lower().replace(" ", "_"),
                })

        cards.append({
            "cardTitle": c_title,
            "cardDescription": c_desc,
            "mediaUrl": c_url,
            "suggestions": card_suggs,
        })

    return cards


def _row_to_rcs_submission(row: dict, client: str = "tata", fallback_idx: int = 1) -> RcsTemplateSubmission:
    """Convert a normalized dict to an RcsTemplateSubmission."""
    row = _normalize_row_keys(row)
    c = (row.get("client") or client).lower()

    template_name = str(
        row.get("template_name")
        or row.get("templatename")
        or row.get("name")
        or row.get("template")
        or row.get("campaign_name")
        or row.get("campaign")
        or f"rcs_template_{fallback_idx}"
    ).strip()

    bot_id = str(row.get("bot_id") or row.get("sender_id") or get_rcs_bot_id(c)).strip()

    raw_type = str(row.get("template_type") or row.get("type") or "").strip().lower()
    media_url = str(row.get("media_url") or row.get("image_url") or row.get("image") or "").strip() or None
    card_title = str(row.get("card_title") or row.get("title") or "").strip() or None

    is_carousel = (
        raw_type in ("carousel", "carousal", "carousel_cards", "multi_card")
        or bool(row.get("carousel_cards"))
        or ("|" in str(row.get("card_title") or "") and "|" in str(row.get("media_url") or ""))
        or ("|" in str(row.get("card_title") or "") and raw_type in ("carousel", "carousal"))
    )

    if is_carousel:
        template_type = "carousel"
        carousel_cards = _build_carousel_cards_from_row(row)
    elif raw_type in ("richcard", "card", "image") or media_url or card_title:
        template_type = "richcard"
        carousel_cards = []
    else:
        template_type = "text"
        carousel_cards = []

    message = (
        row.get("text_message")
        or row.get("body")
        or row.get("card_description")
        or row.get("template_message")
        or row.get("description")
        or row.get("message")
        or ""
    ).strip()

    suggestions = _build_suggestions_from_row(row)
    category = str(row.get("category") or row.get("template_category") or "TRANSACTIONAL").strip().upper()

    return RcsTemplateSubmission(
        template_name=template_name,
        bot_id=bot_id,
        template_type=template_type,
        text_message=message,
        card_title=card_title,
        card_description=message if template_type == "richcard" else None,
        media_url=media_url,
        orientation=str(row.get("orientation") or "VERTICAL").strip().upper(),
        height=str(row.get("height") or "MEDIUM").strip().upper(),
        width=str(row.get("width") or "MEDIUM").strip().upper(),
        suggestions=suggestions,
        carousel_cards=carousel_cards,
        template_category=category,
        entity_id=str(row.get("entity_id") or get_rcs_entity_id(c)).strip(),
        client=c,
        channel="rcs",
        source_ref=row.get("source_ref") or template_name,
    )


def load_rcs_from_csv(path: str, client: str = "tata") -> list[RcsTemplateSubmission]:
    """Load RCS templates from a CSV file."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for idx, raw_row in enumerate(csv.DictReader(f), 1):
            if not any(raw_row.values()):
                continue
            rows.append(_row_to_rcs_submission(raw_row, client=client, fallback_idx=idx))
    return rows

def _ensure_aspect_ratio(img_bytes: bytes, target_ratio: tuple = (16, 9)) -> bytes:
    """Auto-fit image bytes to match target aspect ratio (16:9 for Carousel) if needed."""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(img_bytes))
        target_w, target_h = target_ratio
        current_w, current_h = img.size
        target_aspect = target_w / target_h
        current_aspect = current_w / current_h
        if abs(current_aspect - target_aspect) > 0.02:
            if current_aspect > target_aspect:
                new_w = int(current_h * target_aspect)
                left = (current_w - new_w) // 2
                img = img.crop((left, 0, left + new_w, current_h))
            else:
                new_h = int(current_w / target_aspect)
                top = (current_h - new_h) // 2
                img = img.crop((0, top, current_w, top + new_h))
        buf = io.BytesIO()
        fmt = "PNG" if img.format == "PNG" else "JPEG"
        img.save(buf, format=fmt, quality=95)
        return buf.getvalue()
    except Exception:
        return img_bytes


def _extract_images_from_xlsx(path: str) -> list[tuple[str, bytes]]:
    """Extract embedded images from an Excel (.xlsx) file in order."""
    images = []
    try:
        import zipfile
        with zipfile.ZipFile(path, "r") as z:
            media_names = [f for f in z.namelist() if f.startswith("xl/media/")]
            def natural_key(name):
                return [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', name)]
            media_names.sort(key=natural_key)
            for name in media_names:
                filename = name.split("/")[-1]
                raw_data = z.read(name)
                fitted_data = _ensure_aspect_ratio(raw_data, (16, 9))
                images.append((filename, fitted_data))
    except Exception as e:
        logger.warning("Could not extract embedded images from xlsx: %s", e)
    return images

def load_rcs_from_excel(path: str, client: str = "tata") -> list[RcsTemplateSubmission]:
    """Load RCS templates from an Excel (.xlsx) file with auto-extracted embedded images."""
    import openpyxl

    # Auto-extract and upload any images embedded in the Excel spreadsheet
    extracted_images = _extract_images_from_xlsx(path)
    uploaded_file_names = []
    if extracted_images:
        try:
            from rcs_client import upload_rcs_media
            for fname, img_data in extracted_images:
                try:
                    k_name = upload_rcs_media(img_data, filename=fname, client=client)
                    uploaded_file_names.append(k_name)
                    logger.info("Auto-uploaded embedded image %s -> %s", fname, k_name)
                except Exception as ex:
                    logger.warning("Failed to auto-upload embedded image %s: %s", fname, ex)
        except Exception as e:
            logger.warning("Could not upload extracted xlsx images: %s", e)

    wb = openpyxl.load_workbook(path, data_only=True)
    sheet = wb.active
    all_raw_rows = list(sheet.iter_rows(values_only=True))

    # Check if there is a row that contains multiple rich single-cell card blocks (like Book4)
    block_row_cards = None
    for r in all_raw_rows:
        text_blocks = [str(c).strip() for c in r if c is not None and len(str(c).strip()) > 35]
        if len(text_blocks) >= 2:
            block_row_cards = text_blocks
            break

    if block_row_cards:
        c_cards = []
        for c_idx, block in enumerate(block_row_cards):
            card_dict = parse_single_cell_card_block(block)
            if c_idx < len(uploaded_file_names):
                card_dict["fileName"] = uploaded_file_names[c_idx]

            b_text = card_dict.get("button_text") or "Apply Now"
            b_url = card_dict.get("button_url") or "https://www.tatacapital.com"
            card_dict["suggestions"] = [
                {
                    "suggestionType": "url_action",
                    "text": b_text,
                    "postbackData": b_text.lower().replace(" ", "_"),
                    "url": b_url,
                }
            ]
            c_cards.append(card_dict)

        base_name = Path(path).stem
        clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', base_name).strip('_')
        t_name = f"tata_{clean_name}_carousel"[:25].rstrip('_')

        sub = RcsTemplateSubmission(
            template_name=t_name,
            bot_id=get_rcs_bot_id(client),
            template_type="carousel",
            carousel_cards=c_cards,
            template_category="TRANSACTIONAL",
            entity_id=get_rcs_entity_id(client),
            client=client.lower(),
            channel="rcs",
            source_ref=t_name,
        )
        return [sub]
    headers = [str(cell.value or "").strip() for cell in sheet[1]]
    rows = []
    for idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), 1):
        if not any(row):
            continue

        raw_row = {}
        for h, val in zip(headers, row):
            if h:
                raw_row[h] = str(val).strip() if val is not None else ""

        if not any(raw_row.values()):
            continue

        sub = _row_to_rcs_submission(raw_row, client=client, fallback_idx=idx)

        # Auto-bind uploaded image fileNames to carousel cards or richcard if not manually set
        if uploaded_file_names:
            if sub.template_type == "carousel" and sub.carousel_cards:
                for c_idx, card in enumerate(sub.carousel_cards):
                    if c_idx < len(uploaded_file_names):
                        card["fileName"] = uploaded_file_names[c_idx]
            elif sub.template_type == "richcard" and not sub.media_url:
                setattr(sub, "file_name", uploaded_file_names[0])

        rows.append(sub)

    return rows


def load_rcs_from_list(rows: list[dict], client: str = "tata") -> list[RcsTemplateSubmission]:
    """Load from a list of dicts already in memory."""
    return [_row_to_rcs_submission(row, client=client, fallback_idx=idx) for idx, row in enumerate(rows, 1)]
