"""Untrusted uploaded-template patches; source and destination remain server-owned."""
from collections import Counter
from copy import deepcopy
import json
import re

from fastapi import HTTPException
from models import TemplateComponent

WA_FIELDS = {"template_name", "category", "language", "components"}
RCS_FIELDS = {"template_name", "template_type", "text_message", "card_title", "card_description", "media_url", "orientation", "height", "width", "template_category", "suggestions", "carousel_cards"}
LANGUAGES = {"en", "hi", "mr", "gu", "pa", "bn", "ta", "te", "kn", "ml", "ur", "or", "as"}


def fail(message):
    raise HTTPException(400, detail="template_overrides: " + message)


def text(value, label, maximum=4096, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()) or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        fail(f"{label} must be {'non-empty ' if required else ''}text of at most {maximum} characters")
    return value


def keys(value, allowed, label):
    if not isinstance(value, dict) or value.keys() - allowed:
        fail(f"{label} contains unsupported fields or is not an object")


def url(value):
    from apparel_whatsapp import https_url
    if not https_url(value) or any(c.isspace() for c in value):
        fail("URLs must be public HTTPS URLs without credentials")


def parse_template_overrides(value, channel):
    if value is None:
        return {}
    if not isinstance(value, str) or len(value.encode("utf-8")) > 262144:
        fail("payload exceeds 256 KiB")
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                fail("duplicate JSON key")
            result[key] = item
        return result
    try:
        patches = json.loads(value, object_pairs_hook=unique)
    except (ValueError, TypeError, RecursionError) as exc:
        fail("must be a JSON object")
    if not isinstance(patches, dict) or len(patches) > 500:
        fail("must map at most 500 source_ref values to patches")
    if patches and channel not in {"whatsapp", "rcs"}:
        fail("only WhatsApp and RCS support edits")
    for ref, patch in patches.items():
        text(ref, "source_ref", 1024, True)
        keys(patch, WA_FIELDS if channel == "whatsapp" else RCS_FIELDS, "patch")
    return patches


def buttons(items):
    if not isinstance(items, list) or len(items) > 10:
        fail("buttons must be an array of at most 10 objects")
    for button in items:
        keys(button, {"type", "text", "url", "phone_number", "example"}, "button")
        kind = button.get("type")
        if not isinstance(kind, str) or kind not in {"URL", "PHONE_NUMBER", "QUICK_REPLY"}:
            fail("unsupported button type")
        text(button.get("text"), "button text", 25, True)
        if kind == "URL":
            url(button.get("url"))
        elif "url" in button:
            fail("URL only belongs to URL buttons")
        if kind == "PHONE_NUMBER":
            if not isinstance(button.get("phone_number"), str) or not re.fullmatch(r"\+?[0-9]{3,15}", button["phone_number"]):
                fail("invalid button phone_number")
        elif "phone_number" in button:
            fail("phone_number only belongs to phone buttons")
        if "example" in button:
            examples(button["example"], button=True)


def examples(value, button=False):
    if button:
        if not isinstance(value, list) or len(value) > 20:
            fail("button example must be an array")
        for item in value:
            text(item, "example", 2048)
        return
    keys(value, {"body_text", "header_text"}, "example")
    for field, items in value.items():
        if not isinstance(items, list) or len(items) > 100:
            fail("example must contain arrays")
        for item in items:
            if field == "body_text":
                if not isinstance(item, list) or len(item) > 100:
                    fail("body_text example must contain arrays")
                for sample in item:
                    text(sample, "example", 2048)
            else:
                text(item, "example", 2048)


def components(items, original, account):
    if not isinstance(items, list) or len(items) > 4:
        fail("components must be an array of at most four components")
    result, seen = [], set()
    old_header = next((c for c in original if c.type == "HEADER"), None)
    for raw in items:
        keys(raw, {"type", "text", "format", "example", "buttons", "media_url"}, "component")
        kind = raw.get("type")
        if not isinstance(kind, str) or kind not in {"HEADER", "BODY", "FOOTER", "BUTTONS"} or kind in seen:
            fail("component types must be unique HEADER/BODY/FOOTER/BUTTONS")
        seen.add(kind)
        data = deepcopy(raw)
        if "text" in data:
            text(data["text"], "component text", 4096 if kind == "BODY" else 1024)
        if "example" in data:
            examples(data["example"])
        if kind == "BUTTONS":
            if data.keys() - {"type", "buttons"}:
                fail("BUTTONS only accepts buttons")
            buttons(data.get("buttons"))
            from cta import normalize_whatsapp_cta_buttons
            normalize_whatsapp_cta_buttons(data["buttons"], account)
        elif "buttons" in data:
            fail("buttons only belong to BUTTONS")
        if kind == "HEADER":
            fmt = data.get("format", "TEXT")
            if not isinstance(fmt, str) or fmt not in {"TEXT", "IMAGE", "VIDEO", "DOCUMENT"}:
                fail("invalid header format")
            data["format"] = fmt
            media = data.get("media_url")
            if "media_url" in data:
                text(media, "media_url", 2048, True)
            unchanged = old_header and fmt == old_header.format and media == old_header.media_url and data.get("text") == old_header.text
            if media and not unchanged:
                url(media)
            if fmt == "TEXT" and media:
                fail("TEXT header cannot contain media")
            if fmt != "TEXT" and not media and not (unchanged and (old_header.image_bytes or old_header.media_file)):
                fail("media header requires a public URL or the unchanged original creative")
            component = TemplateComponent(**data)
            if unchanged:
                for field in ("media_file", "image_bytes", "file_type"):
                    setattr(component, field, getattr(old_header, field))
            result.append(component)
        else:
            if "format" in data or "media_url" in data:
                fail("format/media_url only belong to HEADER")
            result.append(TemplateComponent(**data))
    if "BODY" not in seen or not next(c.text for c in result if c.type == "BODY"):
        fail("a non-empty BODY is required")
    return result


def suggestions(items):
    if not isinstance(items, list) or len(items) > 11:
        fail("suggestions must be an array of at most 11 objects")
    for item in items:
        keys(item, {"suggestionType", "text", "postbackData", "url", "phoneNumber"}, "suggestion")
        if not isinstance(item.get("suggestionType"), str) or item["suggestionType"] not in {"reply", "url_action", "dialer_action"}:
            fail("invalid suggestionType")
        text(item.get("text"), "suggestion text", 25, True)
        if "postbackData" in item:
            text(item["postbackData"], "postbackData", 2048)
        if item["suggestionType"] == "url_action":
            url(item.get("url"))
        elif "url" in item:
            fail("url only belongs to url_action")
        if item["suggestionType"] == "dialer_action":
            if not isinstance(item.get("phoneNumber"), str) or not re.fullmatch(r"\+?[0-9]{3,15}", item["phoneNumber"]):
                fail("invalid phoneNumber")
        elif "phoneNumber" in item:
            fail("phoneNumber only belongs to dialer_action")


def apply_template_overrides(submissions, patches, channel, account):
    refs = Counter(s.source_ref for s in submissions)
    if patches.keys() - refs.keys():
        fail("unknown source_ref values: " + ", ".join(sorted(patches.keys() - refs.keys())))
    if any(refs[ref] != 1 for ref in patches):
        fail("each edited source_ref must identify exactly one template")
    for submission in submissions:
        patch = patches.get(submission.source_ref)
        if not patch:
            continue
        patch = deepcopy(patch)
        for field, value in patch.items():
            if field not in {"components", "suggestions", "carousel_cards"}:
                if field in {"card_title", "card_description", "media_url"} and value is None:
                    continue
                text(value, field, 4096, field in {"template_name", "category", "language", "template_type"})
        if "template_name" in patch:
            pattern = r"[a-z0-9_]{1,512}" if channel == "whatsapp" else r"[A-Za-z0-9_]{1,25}"
            if not re.fullmatch(pattern, patch["template_name"]):
                fail("invalid template_name")
        if channel == "whatsapp":
            if "language" in patch and patch["language"] not in LANGUAGES:
                fail("unsupported language")
            if "category" in patch and patch["category"] not in {"MARKETING", "UTILITY", "AUTHENTICATION"}:
                fail("unsupported category")
            if "components" in patch:
                old_header = next((c for c in submission.components if c.type == "HEADER"), None)
                patch["components"] = components(patch["components"], submission.components, account)
                new_header = next((c for c in patch["components"] if c.type == "HEADER"), None)
                if new_header != old_header:
                    submission.aspect_ratio_blocked = False
                    submission.aspect_ratio_error = None
        else:
            for field, allowed in (("template_type", {"text", "richcard", "carousel"}), ("template_category", {"TRANSACTIONAL", "PROMOTIONAL"}), ("orientation", {"VERTICAL", "HORIZONTAL"}), ("height", {"SHORT", "MEDIUM", "TALL"}), ("width", {"SMALL", "MEDIUM"})):
                if field in patch and patch[field] not in allowed:
                    fail("unsupported " + field)
            if "suggestions" in patch:
                suggestions(patch["suggestions"])
            if patch.get("media_url") and patch["media_url"] != submission.media_url:
                url(patch["media_url"])
            if "media_url" in patch and (not patch["media_url"] or patch["media_url"] != submission.media_url):
                submission.image_bytes = None
                submission.file_name = None
                submission.aspect_ratio_blocked = False
                submission.aspect_ratio_error = None
            if "carousel_cards" in patch:
                cards = patch["carousel_cards"]
                if not isinstance(cards, list) or not 2 <= len(cards) <= 10:
                    fail("carousel_cards must contain 2 to 10 objects")
                for index, card in enumerate(cards):
                    keys(card, {"cardTitle", "cardDescription", "mediaUrl", "card_title", "card_description", "media_url", "suggestions"}, "card")
                    if "mediaUrl" in card and "media_url" in card:
                        fail("card must use only one media URL spelling")
                    for media_field in ("mediaUrl", "media_url"):
                        if media_field in card:
                            text(card[media_field], media_field, 2048)
                    for field in ("cardTitle", "card_title", "cardDescription", "card_description"):
                        if field in card:
                            text(card[field], field, 200 if field in {"cardTitle", "card_title"} else 2000)
                    if "suggestions" in card:
                        suggestions(card["suggestions"])
                    old = submission.carousel_cards[index] if index < len(submission.carousel_cards) else {}
                    media_supplied = "mediaUrl" in card or "media_url" in card
                    media = card.get("mediaUrl", card.get("media_url"))
                    old_media = old.get("mediaUrl", old.get("media_url"))
                    if media and media != old_media:
                        url(media)
                    if not media_supplied or (media and media == old_media):
                        if not media_supplied and old_media:
                            card["mediaUrl" if "mediaUrl" in old else "media_url"] = old_media
                        for field in ("image_bytes", "fileName", "file_name", "image_filename"):
                            if field in old:
                                card[field] = old[field]
        for field, value in patch.items():
            setattr(submission, field, value)
        if channel == "whatsapp":
            from submission_client import (
                _resolve_body_variables, _template_components, normalize_whatsapp_template_name,
            )

            # Review the same canonical text, samples, footer policy and buttons
            # that both Karix transports will serialize, without creating media.
            submission.template_name = normalize_whatsapp_template_name(submission.template_name)
            submission.components = [
                TemplateComponent(**component)
                for component in _resolve_body_variables(
                    _template_components(submission), client=account, fix_grammar=False,
                )
            ]
        else:
            from campaign_names import normalize_campaign_name, require_campaign_name
            from rcs_client import normalize_rcs_template_name
            from rcs_loader import normalize_rcs_suggestions

            try:
                submission.template_name = normalize_rcs_template_name(
                    require_campaign_name(normalize_campaign_name(submission.template_name)),
                )
            except ValueError as exc:
                fail(str(exc))
            submission.suggestions = normalize_rcs_suggestions(submission.suggestions, account)
            for card in submission.carousel_cards:
                if "suggestions" in card:
                    card["suggestions"] = normalize_rcs_suggestions(card["suggestions"], account)
