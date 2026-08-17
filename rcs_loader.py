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
        # Multiple pipe-separated quick replies e.g. "Yes | No | Call Us"
        if "|" in btext and btype in ("", "REPLY", "SUGGESTION"):
            for item in btext.split("|"):
                clean = item.strip()
                if clean:
                    suggestions.append({
                        "suggestionType": "reply",
                        "text": clean,
                        "postbackData": clean.lower().replace(" ", "_"),
                    })
        elif btype in ("URL", "URL_ACTION", "LINK") or burl:
            suggestions.append({
                "suggestionType": "url_action",
                "text": btext or "Open Link",
                "postbackData": btext.lower().replace(" ", "_") if btext else "open_url",
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

    titles = [t.strip() for t in str(row.get("card_title") or "").split("|") if t.strip()]
    descriptions = [d.strip() for d in str(row.get("body") or row.get("card_description") or row.get("text_message") or "").split("|") if d.strip()]
    media_urls = [u.strip() for u in str(row.get("media_url") or "").split("|") if u.strip()]
    button_texts = [b.strip() for b in str(row.get("button_text") or "").split("|") if b.strip()]
    button_urls = [u.strip() for u in str(row.get("button_url") or "").split("|") if u.strip()]
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


def _row_to_rcs_submission(row: dict, client: str = "tata") -> RcsTemplateSubmission:
    """Convert a normalized dict to an RcsTemplateSubmission."""
    c = (row.get("client") or client).lower()
    template_name = str(row.get("template_name") or row.get("name") or "").strip()
    bot_id = str(row.get("bot_id") or row.get("sender_id") or get_rcs_bot_id(c)).strip()

    raw_type = str(row.get("template_type") or row.get("type") or "").strip().lower()
    media_url = str(row.get("media_url") or row.get("image_url") or "").strip() or None
    card_title = str(row.get("card_title") or "").strip() or None

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
        for raw_row in csv.DictReader(f):
            clean_row = {
                (k.strip() if k else ""): (v.strip() if v else "")
                for k, v in raw_row.items()
                if k
            }
            if not clean_row.get("template_name") and not clean_row.get("name"):
                continue
            rows.append(clean_row)
    return [_row_to_rcs_submission(row, client=client) for row in rows]


def load_rcs_from_excel(path: str, client: str = "tata") -> list[RcsTemplateSubmission]:
    """Load RCS templates from an Excel (.xlsx) file."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    sheet = wb.active
    headers = [str(cell.value or "").strip() for cell in sheet[1]]

    rows = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if not any(row):
            continue

        raw_row = {}
        for h, val in zip(headers, row):
            if h:
                raw_row[h] = str(val).strip() if val is not None else ""

        if not raw_row.get("template_name") and not raw_row.get("name"):
            continue

        rows.append(raw_row)

    return [_row_to_rcs_submission(row, client=client) for row in rows]


def load_rcs_from_list(rows: list[dict], client: str = "tata") -> list[RcsTemplateSubmission]:
    """Load from a list of dicts already in memory."""
    return [_row_to_rcs_submission(row, client=client) for row in rows]
