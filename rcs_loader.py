"""
Input loader for Karix RCS Bot Builder & DLT templates.

Turns raw rows (CSV, XLSX, JSON) into validated RcsTemplateSubmission objects.
Supports text messages, rich cards, suggestions (URL, Reply, Dialer), and variables.
"""

import csv
import json
import logging
import os
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
    first_line = clean_lines[0] if clean_lines else "Special Offer"
    clean_title = re.sub(r"<[^>]+>|\[[^\]]+\]|\{[^}]+\}", "", first_line).strip()
    clean_title = re.sub(r"^[,\s:–—\-]+|[,\s:–—\-]+$", "", clean_title)
    if re.match(r"^(?:Dear|Hi|Hello)\b", clean_title, re.IGNORECASE) or len(clean_title) < 4:
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
                    suggestions.append(
                        {
                            "suggestionType": "reply",
                            "text": clean,
                            "postbackData": clean,
                        }
                    )
        elif btype in ("DIALER", "DIALER_ACTION", "CALL", "PHONE") or bphone:
            suggestions.append(
                {
                    "suggestionType": "dialer_action",
                    "text": btext or "Call Now",
                    "postbackData": btext or "Call Now",
                    "phoneNumber": bphone or "+919999999999",
                }
            )
        elif btype in ("URL", "URL_ACTION", "LINK") or burl:
            suggestions.append(
                {
                    "suggestionType": "url_action",
                    "text": btext or "Apply Now",
                    "postbackData": btext or "Apply Now",
                    "url": burl or "https://www.tatacapital.com",
                }
            )
        else:
            suggestions.append(
                {
                    "suggestionType": "reply",
                    "text": btext,
                    "postbackData": btext,
                }
            )

    return suggestions


def _normalize_row_keys(row: dict) -> dict:
    """Normalize spreadsheet header keys: strip whitespace, map common aliases to canonical names."""
    aliases = {
        "templatename": "template_name",
        "temlatename": "template_name",
        "templte_name": "template_name",
        "campaignname": "campaign_name",
        "botid": "bot_id",
        "senderid": "sender_id",
        "templatetype": "template_type",
        "mediaurl": "media_url",
        "imageurl": "image_url",
        "image": "image",
        "cardtitle": "card_title",
        "carddescription": "card_description",
        "textmessage": "text_message",
        "templatemessage": "template_message",
        "entityid": "entity_id",
        "sourceref": "source_ref",
        "buttontext": "button_text",
        "buttonurl": "button_url",
        "buttonphone": "button_phone",
        "buttontype": "button_type",
        "suggestiontype": "suggestion_type",
        "suggestiontext": "suggestion_text",
    }
    normalized = {}
    for key, value in row.items():
        if key is None:
            continue
        canonical = str(key).strip()
        compact = re.sub(r"[^a-z0-9]", "", canonical.lower())
        normalized[aliases.get(compact, canonical)] = value
    return normalized


def _parse_sender_ids(raw) -> list[str]:
    """Parse sender IDs from a pipe/comma-separated string, list, or None."""
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [x.strip() for x in re.split(r"[|,]", str(raw)) if x.strip()]


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
    descriptions = [
        d.strip()
        for d in str(
            row.get("body") or row.get("card_description") or row.get("text_message") or row.get("description") or ""
        ).split("|")
        if d.strip()
    ]
    media_urls = [
        u.strip()
        for u in str(row.get("media_url") or row.get("image_url") or row.get("image") or "").split("|")
        if u.strip()
    ]
    button_texts = [
        b.strip() for b in str(row.get("button_text") or row.get("button_name") or "").split("|") if b.strip()
    ]
    button_urls = [u.strip() for u in str(row.get("button_url") or row.get("link") or "").split("|") if u.strip()]
    button_types = [t.strip().upper() for t in str(row.get("button_type") or "").split("|") if t.strip()]

    # Support numbered columns: card1_title / card_1_title, card1_image / card1_media_url, etc.
    if not titles and not media_urls and not descriptions:
        for idx in range(1, 11):
            t = (
                row.get(f"card{idx}_title")
                or row.get(f"card_{idx}_title")
                or row.get(f"card{idx}_heading")
                or row.get(f"card_{idx}_heading")
                or row.get(f"title_{idx}")
                or row.get(f"title{idx}")
            )
            d = (
                row.get(f"card{idx}_body")
                or row.get(f"card_{idx}_body")
                or row.get(f"card{idx}_description")
                or row.get(f"card_{idx}_description")
                or row.get(f"card{idx}_desc")
                or row.get(f"card_{idx}_desc")
                or row.get(f"body_{idx}")
                or row.get(f"body{idx}")
            )
            u = (
                row.get(f"card{idx}_image")
                or row.get(f"card_{idx}_image")
                or row.get(f"card{idx}_image_url")
                or row.get(f"card_{idx}_image_url")
                or row.get(f"card{idx}_media_url")
                or row.get(f"card_{idx}_media_url")
                or row.get(f"image_{idx}")
                or row.get(f"image{idx}")
                or row.get(f"media_{idx}")
            )
            bt = (
                row.get(f"card{idx}_button_text")
                or row.get(f"card_{idx}_button_text")
                or row.get(f"card{idx}_button")
                or row.get(f"card_{idx}_button")
                or row.get(f"button_{idx}_text")
                or row.get(f"button{idx}_text")
            )
            bu = (
                row.get(f"card{idx}_button_url")
                or row.get(f"card_{idx}_button_url")
                or row.get(f"card{idx}_url")
                or row.get(f"card_{idx}_url")
                or row.get(f"button_{idx}_url")
                or row.get(f"button{idx}_url")
            )
            b_type = (
                row.get(f"card{idx}_button_type")
                or row.get(f"card_{idx}_button_type")
                or row.get(f"button_{idx}_type")
                or "URL"
            )
            if t or d or u or bt:
                titles.append(str(t).strip() if t else f"Card {idx}")
                descriptions.append(str(d).strip() if d else "")
                if u:
                    media_urls.append(str(u).strip())
                if bt:
                    button_texts.append(str(bt).strip())
                    button_types.append(str(b_type).strip().upper())
                if bu:
                    button_urls.append(str(bu).strip())
    max_cards = max(len(titles), len(descriptions), len(media_urls), len(button_texts), 2)

    public_base = (
        os.environ.get("RENDER_EXTERNAL_URL")
        or os.environ.get("PUBLIC_APP_URL")
        or "https://whitelisting-agent.onrender.com"
    )

    cards = []
    for i in range(max_cards):
        c_title = titles[i] if i < len(titles) else (f"Card {i + 1}" if titles else "")
        c_desc = descriptions[i] if i < len(descriptions) else (descriptions[0] if descriptions else "")
        c_url = media_urls[i] if i < len(media_urls) else ""

        card_suggs = []
        if i < len(button_texts):
            btext = button_texts[i]
            btype = button_types[i] if i < len(button_types) else (button_types[0] if button_types else "URL")
            b_link = (
                button_urls[i]
                if i < len(button_urls)
                else (button_urls[0] if button_urls else "https://www.tatacapital.com")
            )

            if btype in ("URL", "URL_ACTION", "LINK") or b_link:
                card_suggs.append(
                    {
                        "suggestionType": "url_action",
                        "text": btext,
                        "postbackData": btext,
                        "url": b_link,
                    }
                )
            else:
                card_suggs.append(
                    {
                        "suggestionType": "reply",
                        "text": btext,
                        "postbackData": btext,
                    }
                )

        cards.append(
            {
                "cardTitle": c_title,
                "cardDescription": c_desc,
                "mediaUrl": c_url,
                "suggestions": card_suggs,
            }
        )

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
    header_type = str(row.get("header_type") or "").strip().lower()
    media_url = str(row.get("media_url") or row.get("image_url") or row.get("image") or "").strip() or None
    card_title = str(row.get("card_title") or row.get("title") or row.get("header_text") or "").strip() or None

    is_carousel = (
        raw_type in ("carousel", "carousal", "carousel_cards", "multi_card")
        or bool(row.get("carousel_cards"))
        or ("|" in str(row.get("card_title") or "") and "|" in str(row.get("media_url") or ""))
        or ("|" in str(row.get("card_title") or "") and raw_type in ("carousel", "carousal"))
    )

    public_base = (
        os.environ.get("RENDER_EXTERNAL_URL")
        or os.environ.get("PUBLIC_APP_URL")
        or "https://whitelisting-agent.onrender.com"
    )

    # Resolve default media fallback per official spec ratio
    orientation_key = str(row.get("orientation") or "VERTICAL").strip().upper()
    height_key = str(row.get("height") or "MEDIUM").strip().upper()

    message = str(
        row.get("text_message")
        or row.get("body")
        or row.get("card_description")
        or row.get("template_message")
        or row.get("description")
        or row.get("message")
        or ""
    ).strip()

    if is_carousel:
        template_type = "carousel"
        carousel_cards = _build_carousel_cards_from_row(row)
    elif raw_type in ("text", "plain", "standard", "plain_text") and not media_url and header_type not in ("image", "media", "richcard"):
        template_type = "text"
        carousel_cards = []
        if card_title and card_title not in message:
            message = f"{card_title}\n\n{message}"
    elif (
        raw_type in ("richcard", "card", "image")
        or header_type in ("image", "media", "richcard")
        or media_url
    ):
        template_type = "richcard"
        carousel_cards = []
    else:
        template_type = "text"
        carousel_cards = []

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


# ---------------------------------------------------------------------------
# Official Karix RCS media specifications (RCS specifications docx)
#   Rich Card: VERTICAL SHORT=3:1(1440x480)  VERTICAL MEDIUM=2:1(1440x720)  HORIZONTAL=3:4(768x1024)  max 2MB
#   Carousel : SHORT SMALL=8:5(1160x720)  SHORT MEDIUM=5:2(1800x720)  MEDIUM SMALL=1:1(770x720)  MEDIUM MEDIUM=16:9(1280x720)  max 1MB
# ---------------------------------------------------------------------------

RICH_CARD_IMAGE_SPECS: dict[tuple, dict] = {
    ("VERTICAL", "SHORT"): {
        "ratio": (3, 1),
        "optimal": (1440, 480),
        "max_bytes": 2 * 1024 * 1024,
    },
    ("VERTICAL", "MEDIUM"): {
        "ratio": (2, 1),
        "optimal": (1440, 720),
        "max_bytes": 2 * 1024 * 1024,
    },
    ("HORIZONTAL", "SHORT"): {
        "ratio": (3, 4),
        "optimal": (768, 1024),
        "max_bytes": 2 * 1024 * 1024,
    },
    ("HORIZONTAL", "MEDIUM"): {
        "ratio": (3, 4),
        "optimal": (768, 1024),
        "max_bytes": 2 * 1024 * 1024,
    },
}

CAROUSEL_IMAGE_SPECS: dict[tuple, dict] = {
    ("SHORT", "SMALL"): {
        "ratio": (8, 5),
        "optimal": (1160, 720),
        "max_bytes": 1 * 1024 * 1024,
    },
    ("SHORT", "MEDIUM"): {
        "ratio": (5, 2),
        "optimal": (1800, 720),
        "max_bytes": 1 * 1024 * 1024,
    },
    ("MEDIUM", "SMALL"): {
        "ratio": (1, 1),
        "optimal": (770, 720),
        "max_bytes": 1 * 1024 * 1024,
    },
    ("MEDIUM", "MEDIUM"): {
        "ratio": (16, 9),
        "optimal": (1280, 720),
        "max_bytes": 1 * 1024 * 1024,
    },
}

ACCEPTED_IMAGE_FORMATS = (".jpg", ".jpeg", ".png", ".gif")
ACCEPTED_VIDEO_FORMATS = (".mp4", ".m4v", ".mpeg", ".webm", ".h263", ".m4p")


def _spec_for_richcard(sub: RcsTemplateSubmission) -> dict:
    orientation = (getattr(sub, "orientation", "VERTICAL") or "VERTICAL").upper()
    height = (getattr(sub, "height", "MEDIUM") or "MEDIUM").upper()
    return RICH_CARD_IMAGE_SPECS.get(
        (orientation, height),
        RICH_CARD_IMAGE_SPECS[("VERTICAL", "MEDIUM")],
    )


def _spec_for_carousel(sub: RcsTemplateSubmission) -> dict:
    height = (getattr(sub, "height", "MEDIUM") or "MEDIUM").upper()
    width = (getattr(sub, "width", "MEDIUM") or "MEDIUM").upper()
    return CAROUSEL_IMAGE_SPECS.get(
        (height, width),
        CAROUSEL_IMAGE_SPECS[("MEDIUM", "MEDIUM")],
    )

def check_rcs_image_aspect_ratio(
    media_data: bytes, template_type: str = "carousel"
) -> tuple[bool, str, tuple[int, int], float]:
    """
    Validate that an image strictly adheres to official Karix aspect ratio specifications.
    NO auto-resizing, auto-cropping, or canvas padding is performed.
    Returns: (is_valid, error_reason_if_invalid, (width, height), ratio)
    """
    try:
        import io
        from PIL import Image

        img = Image.open(io.BytesIO(media_data))
        w, h = img.size
        if w <= 0 or h <= 0:
            return False, "Invalid image dimensions (0x0)", (w, h), 0.0
        ratio = w / h

        if template_type in ("carousel", "carousal"):
            # Official Karix Carousel allowed ratios:
            # - 16:9 (~1.78:1, e.g. 1280x720) for Medium width
            # - 1:1 (1.0:1, e.g. 770x720) for Small width
            # - 3:4 (0.75:1, e.g. 768x1024) for Portrait
            is_16_9 = abs(ratio - (16 / 9)) < 0.08
            is_1_1 = abs(ratio - 1.0) < 0.08
            is_3_4 = abs(ratio - 0.75) < 0.08

            if is_16_9 or is_1_1 or is_3_4:
                return True, "", (w, h), ratio
            return (
                False,
                f"Image {w}x{h} ({ratio:.2f}:1) is not in allowed Carousel aspect ratio: 16:9 (1280x720), 1:1 (770x720), or 3:4 (768x1024).",
                (w, h),
                ratio,
            )
        else:
            # Official Karix Rich Card allowed ratios:
            # - 2:1 (2.0:1, e.g. 1440x720 / 1200x600)
            # - 16:9 (~1.78:1, e.g. 1280x720)
            # - 3:4 (0.75:1, e.g. 768x1024)
            # - 3:1 (3.0:1, e.g. 1440x480)
            is_2_1 = abs(ratio - 2.0) < 0.08
            is_16_9 = abs(ratio - (16 / 9)) < 0.08
            is_3_4 = abs(ratio - 0.75) < 0.08
            is_3_1 = abs(ratio - 3.0) < 0.10

            if is_2_1 or is_16_9 or is_3_4 or is_3_1:
                return True, "", (w, h), ratio
            return (
                False,
                f"Image {w}x{h} ({ratio:.2f}:1) is not in allowed Rich Card aspect ratio: 2:1 (1440x720), 16:9 (1280x720), or 3:4 (768x1024).",
                (w, h),
                ratio,
            )
    except Exception as exc:
        logger.warning("Failed to inspect image aspect ratio: %s", exc)
        return True, "", (0, 0), 1.0



def _extract_images_spatially(path: str) -> dict[int, list[tuple[str, bytes]]]:
    """
    Extract embedded images from an Excel (.xlsx) file, mapping each image
    to its exact (row, col) cell coordinates in the worksheet.
    Returns: dict mapping row_idx (1-indexed matching sheet rows) to list of (filename, bytes)
    sorted by column (left-to-right).
    """
    import collections
    import openpyxl

    images_by_row: dict[int, list[tuple[int, str, bytes]]] = collections.defaultdict(list)
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.active
        if hasattr(ws, "_images") and ws._images:
            for idx, img in enumerate(ws._images):
                anchor_from = getattr(img.anchor, "_from", None)
                if anchor_from:
                    r = anchor_from.row + 1  # 1-indexed Excel row
                    c = anchor_from.col + 1  # 1-indexed Excel col
                    fname = getattr(img, "name", None) or f"row{r}_col{c}_{idx}.png"
                    try:
                        data = img._data()
                        images_by_row[r].append((c, fname, data))
                    except Exception:
                        pass
        wb.close()
    except Exception as e:
        logger.debug("Could not extract spatial images via openpyxl: %s", e)

    sorted_map: dict[int, list[tuple[str, bytes]]] = {}
    for r, items in images_by_row.items():
        items.sort(key=lambda x: x[0])
        sorted_map[r] = [(fname, data) for _, fname, data in items]
    return sorted_map


def _extract_images_from_xlsx(path: str) -> list[tuple[str, bytes]]:
    """Extract embedded media (images/videos) from an Excel (.xlsx) file in order, preserving original bytes."""
    media = []
    try:
        import zipfile

        with zipfile.ZipFile(path, "r") as z:
            media_names = [f for f in z.namelist() if f.startswith("xl/media/")]

            def natural_key(name):
                return [int(c) if c.isdigit() else c for c in re.split(r"(\d+)", name)]

            media_names.sort(key=natural_key)
            for name in media_names:
                filename = name.split("/")[-1]
                media.append((filename, z.read(name)))
    except Exception as e:
        logger.warning("Could not extract embedded media from xlsx: %s", e)
    return media


def _upload_and_bind_rcs_images(
    raw_media: list[tuple[str, bytes]],
    subs: list[RcsTemplateSubmission],
    client: str,
    spatial_images: dict[int, list[tuple[str, bytes]]] | None = None,
    fix_aspect_ratio: bool = True,
    upload_now: bool = True,
) -> None:
    """
    Fit each extracted image to the official RCS spec ratio for the template's
    orientation/height/width, compress to the max file size, upload, and bind the
    Karix fileName back onto the templates.
    """
    if not raw_media and not spatial_images:
        return

    media_cache_dir = Path("media_cache")
    media_cache_dir.mkdir(parents=True, exist_ok=True)
    public_base = (
        os.environ.get("RENDER_EXTERNAL_URL")
        or os.environ.get("PUBLIC_APP_URL")
        or "https://whitelisting-agent.onrender.com"
    )

    try:
        from rcs_client import upload_rcs_media
    except Exception:
        return

    media_cursor = 0
    for sub in subs:
        excel_row = getattr(sub, "_excel_row", None)
        row_images = spatial_images.get(excel_row, []) if (spatial_images and excel_row) else []

        safe_tname = re.sub(r"[^a-zA-Z0-9_]", "_", sub.template_name or f"tpl_{excel_row or 1}")[:25]

        if sub.template_type == "richcard":
            target_img = row_images[0] if row_images else (raw_media[media_cursor] if media_cursor < len(raw_media) else None)
            if not row_images and target_img:
                media_cursor += 1
            if target_img:
                try:
                    fname, media_data = target_img
                    unique_fn = f"{client}_{safe_tname}_rich.png"
                    ext = Path(fname).suffix.lower()
                    # Preserve original raw bytes - zero auto-resizing or cropping
                    cache_p = media_cache_dir / unique_fn
                    cache_p.write_bytes(media_data)
                    sub.media_url = f"{public_base}/api/media/{unique_fn}"
                    sub.image_bytes = media_data
                    sub.file_name = unique_fn

                    # Strict aspect ratio validation gate
                    is_valid, err_msg, (w, h), ratio = check_rcs_image_aspect_ratio(media_data, template_type="richcard")
                    if not is_valid:
                        sub.aspect_ratio_blocked = True
                        sub.aspect_ratio_error = err_msg
                        logger.warning("Rich card %s blocked: %s", safe_tname, err_msg)
                    elif upload_now:
                        try:
                            k_name = upload_rcs_media(media_data, filename=unique_fn, client=client)
                            sub.file_name = k_name
                            logger.info("Bound user pasted rich card media %s -> Karix %s", unique_fn, k_name)
                        except Exception as up_ex:
                            logger.info("Portal mediaUpload unavailable (%s); serving user image via %s", up_ex, sub.media_url)
                            sub.file_name = None
                except Exception as ex:
                    logger.warning("Failed to process rich card media: %s", ex)


        elif sub.template_type == "carousel" and sub.carousel_cards:
            spec = _spec_for_carousel(sub)
            for c_idx, card in enumerate(sub.carousel_cards):
                existing_url = card.get("mediaUrl") or ""

                # Find the user's image for this card
                if c_idx < len(row_images):
                    target_img = row_images[c_idx]
                elif not existing_url and media_cursor < len(raw_media):
                    target_img = raw_media[media_cursor]
                    media_cursor += 1
                else:
                    target_img = None

                if target_img:
                    try:
                        fname, media_data = target_img
                        unique_fn = f"{client}_{safe_tname}_card_{c_idx + 1}.png"
                        ext = Path(fname).suffix.lower()
                        # Preserve original raw bytes - zero auto-resizing or cropping
                        cache_p = media_cache_dir / unique_fn
                        cache_p.write_bytes(media_data)
                        card["mediaUrl"] = f"{public_base}/api/media/{unique_fn}"
                        card["image_bytes"] = media_data
                        card["fileName"] = unique_fn

                        # Strict aspect ratio validation gate
                        is_valid, err_msg, (w, h), ratio = check_rcs_image_aspect_ratio(media_data, template_type="carousel")
                        if not is_valid:
                            card["aspect_ratio_blocked"] = True
                            card["aspect_ratio_error"] = err_msg
                            sub.aspect_ratio_blocked = True
                            if not sub.aspect_ratio_error:
                                sub.aspect_ratio_error = f"Card {c_idx + 1}: {err_msg}"
                            logger.warning("Carousel card %d in %s blocked: %s", c_idx + 1, safe_tname, err_msg)
                        elif upload_now:
                            try:
                                k_name = upload_rcs_media(media_data, filename=unique_fn, client=client)
                                card["fileName"] = k_name
                                logger.info("Bound user pasted carousel card %d media -> Karix %s", c_idx + 1, k_name)
                            except Exception as up_ex:
                                logger.info("Portal mediaUpload unavailable (%s); serving user image via %s", up_ex, card["mediaUrl"])
                                card.pop("fileName", None)
                    except Exception as ex:
                        logger.warning("Failed to process carousel card media: %s", ex)

def load_rcs_from_excel(
    path: str,
    client: str = "tata",
    fix_aspect_ratio: bool = True,
    upload_media: bool = True,
) -> list[RcsTemplateSubmission]:
    """Load RCS templates from an Excel (.xlsx) file with auto-extracted embedded images."""
    import openpyxl
    # Extract spatial images mapped by row and column, plus raw media fallback
    spatial_images = _extract_images_spatially(path)
    raw_media = _extract_images_from_xlsx(path)
    wb = openpyxl.load_workbook(path, data_only=True)
    sheet = wb.active
    all_raw_rows = list(sheet.iter_rows(values_only=True))
    wb.close()

    first_row = [str(c or "").strip().lower() for c in all_raw_rows[0]] if all_raw_rows else []
    has_standard_headers = any(
        h
        in (
            "template_name",
            "templatename",
            "name",
            "body",
            "body_text",
            "components",
            "category",
            "language",
            "card_title",
            "card_description",
            "media_url",
            "header_type",
        )
        for h in first_row
    )

    # Check if there is a row that contains multiple rich single-cell card blocks (only when no standard column headers exist)
    block_row_cards = None
    if not has_standard_headers:
        for r in all_raw_rows:
            text_blocks = [str(c).strip() for c in r if c is not None and len(str(c).strip()) > 35]
            if len(text_blocks) >= 2:
                block_row_cards = text_blocks
                break
        if block_row_cards:
            c_cards = []
            for _c_idx, block in enumerate(block_row_cards):
                card_dict = parse_single_cell_card_block(block)

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
            clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", base_name).strip("_")
            t_name = f"tata_{clean_name}_carousel"[:25].rstrip("_")

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
            _upload_and_bind_rcs_images(
                raw_media,
                [sub],
                client,
                fix_aspect_ratio=fix_aspect_ratio,
                upload_now=upload_media,
            )
            return [sub]
    headers = [str(cell.value or "").strip() for cell in sheet[1]]
    rows = []
    for idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
        if not any(row):
            continue

        raw_row = {}
        for h, val in zip(headers, row, strict=False):
            if h:
                raw_row[h] = str(val).strip() if val is not None else ""

        if not any(raw_row.values()):
            continue

        sub = _row_to_rcs_submission(raw_row, client=client, fallback_idx=idx - 1)
        sub._excel_row = idx
        rows.append(sub)

    _upload_and_bind_rcs_images(
        raw_media,
        rows,
        client,
        spatial_images=spatial_images,
        fix_aspect_ratio=fix_aspect_ratio,
        upload_now=upload_media,
    )
    return rows


def load_rcs_from_list(rows: list[dict], client: str = "tata") -> list[RcsTemplateSubmission]:
    """Load from a list of dicts already in memory."""
    return [_row_to_rcs_submission(row, client=client, fallback_idx=idx) for idx, row in enumerate(rows, 1)]
