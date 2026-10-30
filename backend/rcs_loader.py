"""
Input loader for Karix RCS Bot Builder & DLT templates.

Turns raw rows (CSV, XLSX, JSON) into validated RcsTemplateSubmission objects.
Supports text messages, rich cards, suggestions (URL, Reply, Dialer), and variables.
Structured client briefs use their own header-bearing worksheets, retaining source
sheet/row, explicit routing, numbered cards/actions, and row-local media.
"""

import csv
import json
import logging
import os
import re
from pathlib import Path

from cta import ensure_dynamic_cta_url
from rcs_config import _account_prefix, get_rcs_bot_id, get_rcs_entity_id, get_rcs_esmeaddr
from rcs_models import RcsTemplateSubmission

from client_brief import read_client_brief_rows
logger = logging.getLogger(__name__)


def parse_single_cell_card_block(cell_text: str) -> dict:
    """Preserve supplied copy and parse explicit CTA labels/URLs; never invent a destination."""
    lines = [line.strip() for line in cell_text.splitlines() if line.strip()]
    button_text = ""
    button_url = ""
    clean_lines = []
    for line in lines:
        match = re.fullmatch(r"CTA\s*(?:Button)?\s*[:<\[-]\s*([^>\]\n]+?)[>\]]?\s*(https?://\S+)?", line, re.IGNORECASE)
        link_match = re.fullmatch(r"(?:CTA\s*)?(?:Link|URL)\s*:\s*(https?://\S+)", line, re.IGNORECASE)
        if link_match:
            button_url = link_match.group(1)
        elif match:
            button_text = match.group(1).strip()
            if match.group(2):
                button_url = match.group(2)
        else:
            clean_lines.append(line)
    return {
        "card_title": clean_lines[0] if clean_lines else "",
        "card_description": "\n\n".join(clean_lines),
        "button_text": button_text,
        "button_url": ensure_dynamic_cta_url(button_url),
    }


def _json_objects(value, label: str) -> list[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid RCS {label} JSON") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"RCS {label} must be an array of objects")
    return value


def normalize_rcs_suggestions(suggestions: list[dict]) -> list[dict]:
    """Make URL actions dynamic without changing reply or dialer actions."""
    return [
        {**suggestion, "url": ensure_dynamic_cta_url(suggestion.get("url") or "")}
        if suggestion.get("suggestionType") == "url_action"
        or (not suggestion.get("suggestionType") and suggestion.get("url"))
        else dict(suggestion)
        for suggestion in suggestions
    ]


def _build_suggestions_from_row(row: dict) -> list[dict]:
    """Parse button columns into Karix RCS suggestion dictionaries."""
    suggestions = []

    if row.get("suggestions") not in (None, ""):
        return normalize_rcs_suggestions(_json_objects(row["suggestions"], "suggestions"))

    btype = (row.get("button_type") or row.get("suggestion_type") or "").strip().upper()
    btext = (row.get("button_text") or row.get("suggestion_text") or "").strip()
    burl = (row.get("button_url") or row.get("url") or "").strip()
    bphone = (row.get("button_phone") or row.get("phone") or row.get("phone_number") or "").strip()
    if not btext and (burl or bphone or btype):
        raise ValueError("RCS action requires explicit button text")
    if btype and btype not in ("URL", "URL_ACTION", "LINK", "DIALER", "DIALER_ACTION", "CALL", "PHONE", "REPLY", "SUGGESTION"):
        raise ValueError(f"Unsupported RCS button type: {btype}")

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
        elif btype in ("DIALER", "DIALER_ACTION", "CALL", "PHONE") or (not btype and bphone):
            suggestions.append(
                {
                    "suggestionType": "dialer_action",
                    "text": btext,
                    "postbackData": btext,
                    "phoneNumber": bphone,
                }
            )
        elif btype in ("URL", "URL_ACTION", "LINK") or (not btype and burl):
            suggestions.append(
                {
                    "suggestionType": "url_action",
                    "text": btext,
                    "postbackData": btext,
                    "url": ensure_dynamic_cta_url(burl),
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
        "filename": "file_name",
        "esmeaddr": "esme_addr",
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
    """Keep card column positions, including blanks, without borrowing another card's data."""
    if row.get("carousel_cards") not in (None, ""):
        cards = _json_objects(row["carousel_cards"], "carousel_cards")
        normalized = []
        for card in cards:
            card = dict(card)
            if "suggestions" in card or card.get("button_text"):
                card["suggestions"] = _build_suggestions_from_row(card)
                if card.get("button_url") and any(
                    suggestion.get("suggestionType") == "url_action"
                    for suggestion in card["suggestions"]
                ):
                    card["button_url"] = ensure_dynamic_cta_url(card["button_url"])
            normalized.append(card)
        return normalized

    def parts(*keys):
        value = next((row[key] for key in keys if row.get(key) not in (None, "")), "")
        return [piece.strip() for piece in str(value).split("|")] if value != "" else []

    columns = {
        "card_title": parts("card_title", "title"),
        "body": parts("body", "card_description", "text_message", "description"),
        "media_url": parts("media_url", "image_url", "image"),
        "button_text": parts("button_text", "button_name"),
        "button_url": parts("button_url", "link"),
        "button_type": parts("button_type"),
        "button_phone": parts("button_phone", "phone"),
    }
    card_rows = []
    if any(columns.values()):
        for i in range(max(map(len, columns.values()))):
            card_rows.append({key: values[i] if i < len(values) else "" for key, values in columns.items()})
    else:
        for idx in range(1, 11):
            card_row = {}
            for field, suffixes in {
                "card_title": ("title", "heading"),
                "body": ("body", "description", "desc"),
                "media_url": ("image", "image_url", "media_url"),
                "button_text": ("button_text", "button"),
                "button_url": ("button_url", "url"),
                "button_type": ("button_type",),
                "button_phone": ("button_phone", "phone"),
            }.items():
                keys = [key for suffix in suffixes for key in (f"card{idx}_{suffix}", f"card_{idx}_{suffix}", f"{suffix}_{idx}", f"{suffix}{idx}")]
                card_row[field] = next((row[key] for key in keys if row.get(key) not in (None, "")), "")
            if any(card_row.values()):
                card_rows.append(card_row)
    return [{
        "cardTitle": card["card_title"],
        "cardDescription": card["body"],
        "mediaUrl": card["media_url"],
        "suggestions": _build_suggestions_from_row(card),
    } for card in card_rows]


def _row_to_rcs_submission(row: dict, client: str = "tata", fallback_idx: int = 1) -> RcsTemplateSubmission:
    """Convert a normalized dict to an RcsTemplateSubmission."""
    row = _normalize_row_keys(row)
    c = client.strip().lower()
    _account_prefix(c)
    row_client = row.get("client")
    if row_client and str(row_client).strip().lower() != c:
        raise ValueError("RCS row account does not match the selected account")

    template_name = str(
        row.get("template_name")
        or row.get("templatename")
        or row.get("name")
        or row.get("template")
        or row.get("campaign_name")
        or row.get("campaign")
        or f"rcs_template_{fallback_idx}"
    ).strip()

    configured_bot = get_rcs_bot_id(c)
    bot_id = str(row.get("bot_id") or row.get("sender_id") or configured_bot).strip()
    if bot_id != configured_bot:
        raise ValueError("RCS row bot ID does not match the selected account")
    esme_addr = str(row.get("esme_addr") or row.get("esmeaddr") or "").strip() or None
    if esme_addr and esme_addr != get_rcs_esmeaddr(c):
        raise ValueError("RCS row ESME address does not match the selected account")
    raw_type = str(row.get("template_type") or row.get("type") or "").strip().lower()
    type_aliases = {
        "rich_card": "richcard", "rich_card_standalone": "richcard",
        "richcardstandalone": "richcard", "standalone": "richcard",
        "rich_card_carousel": "carousel", "richcardcarousel": "carousel",
    }
    raw_type = type_aliases.get(raw_type, raw_type)
    if raw_type and raw_type not in {
        "text", "plain", "standard", "plain_text", "richcard", "card", "image",
        "carousel", "carousal", "carousel_cards", "multi_card",
    }:
        raise ValueError(f"Unsupported RCS template type: {raw_type}")
    header_type = str(row.get("header_type") or "").strip().lower()
    media_url = str(row.get("media_url") or row.get("image_url") or row.get("image") or "").strip() or None
    card_title = str(row.get("card_title") or row.get("title") or row.get("header_text") or "").strip() or None

    is_carousel = (
        raw_type in ("carousel", "carousal", "carousel_cards", "multi_card")
        or bool(row.get("carousel_cards"))
        or ("|" in str(row.get("card_title") or "") and "|" in str(row.get("media_url") or ""))
        or ("|" in str(row.get("card_title") or "") and raw_type in ("carousel", "carousal"))
    )


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
    elif (
        raw_type in ("text", "plain", "standard", "plain_text")
        and not media_url
        and header_type not in ("image", "media", "richcard")
    ):
        template_type = "text"
        carousel_cards = []
        if card_title and card_title not in message:
            message = f"{card_title}\n\n{message}"
    elif raw_type in ("richcard", "card", "image") or header_type in ("image", "media", "richcard") or media_url:
        template_type = "richcard"
        carousel_cards = []
    else:
        template_type = "text"
        carousel_cards = []

    # Pipe-delimited carousel actions belong to individual cards, not one global button.
    suggestions = _build_suggestions_from_row(
        {"suggestions": row.get("suggestions")} if is_carousel else row
    )
    category = str(row.get("category") or row.get("template_category") or "TRANSACTIONAL").strip().upper()

    return RcsTemplateSubmission(
        template_name=template_name,
        bot_id=bot_id,
        esme_addr=esme_addr,
        template_type=template_type,
        text_message=message,
        card_title=card_title,
        card_description=message if template_type == "richcard" else None,
        media_url=media_url,
        file_name=str(row.get("file_name") or "").strip() or None,
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
    p = Path(path)
    if not p.exists() and (Path("samples") / path).exists():
        p = Path("samples") / path
    rows = []
    with open(p, newline="", encoding="utf-8") as f:
        for idx, raw_row in enumerate(csv.DictReader(f), 1):
            if not any(raw_row.values()):
                continue
            rows.append(_row_to_rcs_submission(raw_row, client=client, fallback_idx=idx))
    return rows


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

        with Image.open(io.BytesIO(media_data)) as img:
            w, h = img.size
            if img.format not in ("JPEG", "PNG", "GIF"):
                return False, "RCS images must be JPEG, PNG, or GIF", (w, h), 0.0
            img.verify()
        with Image.open(io.BytesIO(media_data)) as img:
            img.load()
        if w <= 0 or h <= 0:
            return False, "Invalid image dimensions (0x0)", (w, h), 0.0
        ratio = w / h

        if template_type in ("carousel", "carousal"):
            # Short-card ratios are documented in docs/vendor/RCS specifications.
            # Preserve legacy portrait acceptance; do not silently tighten provider policy.
            is_16_9 = abs(ratio - (16 / 9)) < 0.08
            is_1_1 = abs(ratio - 1.0) < 0.08
            is_3_4 = abs(ratio - 0.75) < 0.08
            is_8_5 = abs(ratio - (8 / 5)) < 0.08
            is_5_2 = abs(ratio - (5 / 2)) < 0.08

            if is_16_9 or is_1_1 or is_3_4 or is_8_5 or is_5_2:
                return True, "", (w, h), ratio
            return (
                False,
                f"Image {w}x{h} ({ratio:.2f}:1) is not in allowed Carousel aspect ratio: 16:9, 1:1, 3:4, 8:5, or 5:2.",
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
        if not media_data:
            return False, "Empty image data", (0, 0), 0.0
        return False, f"Invalid or unreadable image data ({exc})", (0, 0), 0.0

def _extract_images_spatially(path: str, workbook=None, sheet_name: str | None = None) -> dict[int, list[tuple[str, bytes]]]:
    """
    Extract embedded images from an Excel (.xlsx) file, mapping each image
    to its exact (row, col) cell coordinates in the worksheet.
    Returns: dict mapping row_idx (1-indexed matching sheet rows) to list of (filename, bytes)
    sorted by column (left-to-right).
    """
    import collections

    import openpyxl

    images_by_row: dict[int, list[tuple[int, str, bytes]]] = collections.defaultdict(list)
    wb = workbook if workbook is not None else openpyxl.load_workbook(path, data_only=True)
    try:
        sheet = wb[sheet_name] if sheet_name is not None else wb.active
        for idx, img in enumerate(getattr(sheet, "_images", [])):
            anchor_from = getattr(img.anchor, "_from", None)
            if anchor_from:
                r = anchor_from.row + 1
                c = anchor_from.col + 1
                fname = getattr(img, "name", None) or f"row{r}_col{c}_{idx}.{img.format}"
                images_by_row[r].append((c, fname, img._data()))
    finally:
        if workbook is None:
            wb.close()

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
    upload_now: bool = True,
) -> None:
    """Preserve and validate local media, uploading only when explicitly requested.

    Local preview paths are not provider fileNames. Content-addressed cache names
    avoid overwriting previews; provider uploads stay distinct for every card.
    """
    import hashlib
    from rcs_client import _validate_rcs_carousel_media_names, upload_rcs_media

    c = client.strip().lower()
    _account_prefix(c)
    for sub in subs:
        if sub.client.strip().lower() != c:
            raise ValueError("RCS media account does not match the selected account")
    if not raw_media and not spatial_images:
        if upload_now:
            for sub in subs:
                if sub.template_type == "carousel":
                    _validate_rcs_carousel_media_names(sub.carousel_cards)
        return
    media_cache_dir = Path("media_cache")
    media_cache_dir.mkdir(parents=True, exist_ok=True)
    public_base = (os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("PUBLIC_APP_URL") or "").rstrip("/")
    inspected = {}
    media_cursor = 0
    bindings = []
    for sub in subs:
        row_images = (spatial_images or {}).get(getattr(sub, "_excel_row", None), [])
        targets = [sub] if sub.template_type == "richcard" else sub.carousel_cards if sub.template_type == "carousel" else []
        for index, target in enumerate(targets):
            existing_url = target.get("mediaUrl") or target.get("media_url") if isinstance(target, dict) else target.media_url
            if index < len(row_images):
                image = row_images[index]
            elif not spatial_images and not existing_url and media_cursor < len(raw_media):
                image = raw_media[media_cursor]
                media_cursor += 1
            else:
                continue
            fname, data = image
            key = (data, sub.template_type)
            if key not in inspected:
                inspected[key] = check_rcs_image_aspect_ratio(data, sub.template_type)
            valid, reason, _, _ = inspected[key]
            maximum = 1024 * 1024 if sub.template_type == "carousel" else 2 * 1024 * 1024
            if not valid or len(data) > maximum:
                sub.aspect_ratio_blocked = True
                sub.aspect_ratio_error = reason or f"RCS media exceeds {maximum} bytes"
            extension = ".jpg" if data.startswith(b"\xff\xd8\xff") else ".gif" if data.startswith(b"GIF8") else ".png"
            cache_name = f"{c}_{hashlib.sha256(data).hexdigest()}{extension}"
            cache_path = media_cache_dir / cache_name
            if not cache_path.exists():
                cache_path.write_bytes(data)
            preview_url = f"{public_base}/api/media/{cache_name}"
            if isinstance(target, dict):
                target["image_bytes"] = data
                target["image_filename"] = fname
                target["mediaUrl"] = preview_url
                target.pop("fileName", None)
                target.pop("file_name", None)
            else:
                target.image_bytes = data
                target.image_filename = fname
                target.media_url = preview_url
                target.file_name = None
            bindings.append((sub, target, fname, data))
    for sub, target, fname, data in bindings:
        if upload_now and not sub.aspect_ratio_blocked:
            file_name = upload_rcs_media(data, filename=fname, client=c)
            if isinstance(target, dict):
                target["fileName"] = file_name
            else:
                target.file_name = file_name
    if upload_now:
        for sub in subs:
            if sub.template_type == "carousel" and not sub.aspect_ratio_blocked:
                _validate_rcs_carousel_media_names(sub.carousel_cards)


def _brief_blocks(value: str, label: str) -> dict[int, str] | None:
    """Split explicit headings while preserving inner line breaks."""
    pattern = re.compile(rf"(?im)^[ \t]*{label}[ \t]+(\d+)[ \t]*(?::[ \t]*-?|-[ \t]*:?)?[ \t]*")
    matches = list(pattern.finditer(value or ""))
    if not matches:
        return None
    if value[:matches[0].start()].strip():
        raise ValueError(f"Ambiguous text before {label} 1")
    result = {}
    for index, match in enumerate(matches):
        number = int(match.group(1))
        if number in result:
            raise ValueError(f"Duplicate {label} {number}")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        result[number] = value[match.end():end].strip()
    if sorted(result) != list(range(1, len(result) + 1)):
        raise ValueError(f"{label} numbers must be consecutive starting at 1")
    return result


def _brief_actions(value: str, count: int, label: str) -> dict[int, dict[int, str]]:
    """Legacy Button N maps to card N; Card N / Button M maps nested actions."""
    value = (value or "").strip()
    if not value:
        return {number: {} for number in range(1, count + 1)}
    pattern = re.compile(r"(?im)^[ \t]*Card[ \t]+(\d+)[ \t]*/[ \t]*Button[ \t]+(\d+)[ \t]*(?::[ \t]*-?|-[ \t]*:?)?[ \t]*")
    flat = list(pattern.finditer(value))
    if flat:
        if value[:flat[0].start()].strip():
            raise ValueError(f"Ambiguous {label} before first card/button")
        result = {}
        for index, match in enumerate(flat):
            card, button = map(int, match.groups())
            end = flat[index + 1].start() if index + 1 < len(flat) else len(value)
            buttons = result.setdefault(card, {})
            if button in buttons:
                raise ValueError(f"Duplicate Card {card} / Button {button}")
            buttons[button] = value[match.end():end].strip()
        if sorted(result) != list(range(1, count + 1)) or any(sorted(buttons) != list(range(1, len(buttons) + 1)) for buttons in result.values()):
            raise ValueError(f"{label} card/button counts are contradictory")
        return result
    cards = _brief_blocks(value, "Card")
    if cards is not None:
        if len(cards) != count:
            raise ValueError(f"{label} card count does not match carousel")
        return {number: _brief_blocks(text, "Button") or {1: text} for number, text in cards.items()}
    buttons = _brief_blocks(value, "Button")
    if buttons is not None:
        if count == 1:
            return {1: buttons}
        if len(buttons) != count:
            raise ValueError(f"{label} button count does not match carousel")
        return {number: {1: text} for number, text in buttons.items()}
    if count == 1:
        return {1: {1: value}}
    raise ValueError(f"Ambiguous {label}: use explicit Card N / Button M headings")


def _brief_suggestions(row: dict, count: int) -> dict[int, list[dict]]:
    texts = _brief_actions(row.get("button_text", ""), count, "button text")
    fields = {}
    for key in ("button_type", "button_url"):
        value = row.get(key, "").strip()
        explicit = bool(re.search(r"(?im)^[ \t]*(?:Card|Button)[ \t]+\d+", value))
        fields[key] = (_brief_actions(value, count, key), False) if explicit else (value, True)
    output = {}
    for card, buttons in texts.items():
        suggestions = []
        if not buttons and any(
            scalar and mapping.strip().lower() not in ("", "na", "n/a")
            for mapping, scalar in fields.values()
        ):
            raise ValueError(f"Card {card} action requires explicit button text")
        for key, (mapping, scalar) in fields.items():
            if not scalar and set(mapping[card]) != set(buttons):
                raise ValueError(f"{key} button count does not match button text for Card {card}")
        for button, text in buttons.items():
            action = {"button_text": text}
            for key, (mapping, scalar) in fields.items():
                action[key] = mapping if scalar else mapping[card][button]
            kind = action["button_type"].strip().lower()
            action["button_type"] = {
                "website (rcs)": "URL", "url action (rcs)": "URL",
                "reply (rcs)": "REPLY", "suggested reply (rcs)": "REPLY",
                "na": "", "n/a": "",
            }.get(kind, action["button_type"])
            suggestions.extend(_build_suggestions_from_row(action))
        output[card] = suggestions
    return output


def _brief_rcs_row(row: dict) -> dict:
    import hashlib

    result = dict(row)
    if row.get("account") and row.get("client") and row["account"].strip().lower() != row["client"].strip().lower():
        raise ValueError("Contradictory explicit client and account")
    if row.get("account"):
        result["client"] = row["account"]
    if not any(row.get(key, "").strip() for key in ("template_name", "campaign_name")):
        digest = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]
        sheet = re.sub(r"[^a-z0-9]", "_", row["sheet"].lower()).strip("_")[:6] or "sheet"
        result["template_name"] = f"{sheet}_{row['excel_row']}_{digest}"[:25]
    kind = row.get("header_type", "").strip().lower()
    result["template_type"] = kind if kind in ("carousel", "richcard") else ""
    if kind == "carousel":
        titles = _brief_blocks(row.get("card_title", ""), "Card")
        bodies = _brief_blocks(row.get("body", ""), "Card")
        if not titles or not bodies or titles.keys() != bodies.keys():
            raise ValueError("Carousel title/body card counts must match explicit Card N headings")
        actions = _brief_suggestions(row, len(titles))
        media_text = row.get("image_url", "").strip()
        media = _brief_blocks(media_text, "Card") if media_text else {}
        if media_text and (media is None or media.keys() != titles.keys()):
            raise ValueError("Carousel media must map explicitly to every Card N; a single asset cannot be reused")
        result["carousel_cards"] = [
            {"cardTitle": titles[number], "cardDescription": bodies[number],
             "mediaUrl": media.get(number, ""), "suggestions": actions[number]}
            for number in titles
        ]
    else:
        result["suggestions"] = _brief_suggestions(row, 1)[1]
    return result


def _load_rcs_client_brief(path: str, records: list[dict], client: str, upload_media: bool) -> list[RcsTemplateSubmission]:
    import openpyxl

    submissions = []
    # Validate all routing before media processing can upload anything.
    for row in records:
        if row["channel"].strip().lower() != "rcs":
            continue
        try:
            sub = _row_to_rcs_submission(_brief_rcs_row(row), client=client, fallback_idx=row["excel_row"])
        except ValueError as exc:
            raise ValueError(f"{row['source_ref']}: {exc}") from exc
        sub._excel_row = row["excel_row"]
        sub._excel_sheet = row["sheet"]
        submissions.append(sub)
    workbook = openpyxl.load_workbook(path, data_only=True)
    try:
        for sheet_name in dict.fromkeys(sub._excel_sheet for sub in submissions):
            images = _extract_images_spatially(path, workbook=workbook, sheet_name=sheet_name)
            sheet_subs = [sub for sub in submissions if sub._excel_sheet == sheet_name]
            for sub in sheet_subs:
                row_images = images.get(sub._excel_row, [])
                targets = sub.carousel_cards if sub.template_type == "carousel" else [sub] if sub.template_type == "richcard" else []
                # Partial sets do not identify individual cards unambiguously.
                if row_images and len(row_images) != len(targets):
                    logger.warning(
                        "%s: %d embedded images cannot map unambiguously to %d media targets; leaving media missing",
                        sub.source_ref, len(row_images), len(targets),
                    )
                    images.pop(sub._excel_row, None)
            _upload_and_bind_rcs_images([], sheet_subs, client, spatial_images=images, upload_now=upload_media)
    finally:
        workbook.close()
    return submissions


def load_rcs_from_excel(
    path: str,
    client: str = "tata",
    upload_media: bool = True,
) -> list[RcsTemplateSubmission]:
    """Load RCS templates from an Excel (.xlsx) file with auto-extracted embedded images."""
    import openpyxl

    brief_rows = read_client_brief_rows(path)
    if brief_rows is not None:
        return _load_rcs_client_brief(path, brief_rows, client, upload_media)

    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        spatial_images = _extract_images_spatially(path, workbook=wb)
        all_raw_rows = list(wb.active.iter_rows(values_only=True))
    finally:
        wb.close()
    raw_media = [] if spatial_images else _extract_images_from_xlsx(path)

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

                card_dict["suggestions"] = _build_suggestions_from_row(card_dict)
                c_cards.append(card_dict)

            base_name = Path(path).stem
            clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", base_name).strip("_")
            t_name = f"{client.lower()}_{clean_name}_carousel"[:25].rstrip("_")

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
            sub._excel_row = 1
            _upload_and_bind_rcs_images(
                raw_media,
                [sub],
                client,
                spatial_images={1: [image for images in spatial_images.values() for image in images]} if spatial_images else None,
                upload_now=upload_media,
            )
            return [sub]
    headers = [str(c or "").strip() for c in all_raw_rows[0]] if all_raw_rows else []
    rows = []
    for idx, row in enumerate(all_raw_rows[1:], 2):
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
        upload_now=upload_media,
    )
    return rows


def load_rcs_from_list(rows: list[dict], client: str = "tata") -> list[RcsTemplateSubmission]:
    """Load from a list of dicts already in memory."""
    return [_row_to_rcs_submission(row, client=client, fallback_idx=idx) for idx, row in enumerate(rows, 1)]
