"""
Client for Karix RCS Bot Builder Template Management API.

Sends RcsTemplateSubmission payloads to the official Karix RCS endpoint:
POST https://rcsgui.karix.solutions/api/rcstemplate/save
"""

import os
import re
from urllib.parse import urlsplit

import requests

from cta import CTA_VARIABLE_PATTERN, ensure_dynamic_cta_url
from rcs_config import (
    KARIX_RCS_SAVE_URL,
    KARIX_RCS_FETCH_TEMPLATES_URL,
    KARIX_RCS_MEDIA_UPLOAD_URL,
    _account_prefix,
    get_rcs_auth_headers,
    get_rcs_bot_id,
    get_rcs_bot_ids,
    get_rcs_esmeaddr,
)
from rcs_models import (
    RcsSubmissionResult,
    RcsSubmissionStatus,
    RcsTemplateSubmission,
)


# ---------------------------------------------------------------------------
# Constants & Timeout
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = 30  # seconds
_VARIABLE_PATTERN = CTA_VARIABLE_PATTERN


def check_rcs_credentials(
    client: str, *, bearer_token: str, bot_id: str, esmeaddr: str,
    session_id: str | None = None, portal_user: str | None = None,
) -> tuple[bool, str]:
    """Verify this exact RCS snapshot against the configured read-only bot inventory."""
    try:
        headers = get_rcs_auth_headers(
            client, auth_token=bearer_token, session_id=session_id, portal_user=portal_user,
        )
        response = requests.post(
            KARIX_RCS_FETCH_TEMPLATES_URL, headers=headers,
            json={"senderId": bot_id, "esmeaddr": esmeaddr},
            timeout=REQUEST_TIMEOUT, allow_redirects=False,
        )
        if not response.ok or 300 <= response.status_code < 400:
            return False, "Karix RCS refused the captured session."
        data = response.json()
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict) and not _provider_failed(data):
            rows = next((data[key] for key in ("templateInfo", "templates", "data") if isinstance(data.get(key), list)), None)
            if rows is None and isinstance(data.get("response"), dict):
                rows = data["response"].get("templates")
        else:
            return False, "Karix RCS rejected the captured session."
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            return False, "Karix RCS returned an unrecognized inventory."
        for row in rows:
            observed_bot = row.get("senderId") or row.get("botId")
            observed_esme = row.get("esmeaddr")
            if observed_bot is not None and str(observed_bot) != bot_id:
                return False, "Karix RCS returned another bot's inventory."
            if observed_esme is not None and str(observed_esme) != esmeaddr:
                return False, "Karix RCS returned another account's inventory."
        return True, "RCS session verified for the configured bot."
    except (requests.RequestException, OSError, ValueError, TypeError):
        return False, "Karix RCS session verification failed."


def normalize_rcs_template_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("RCS template name is required")
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if len(safe_name) > 25 or not safe_name.strip("_"):
        raise ValueError("RCS template name must contain letters or numbers and fit within 25 characters")
    return safe_name


def _checked_text(value, label: str, maximum: int, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError(f"RCS {label} must be {'non-empty ' if required else ''}text of at most {maximum} characters")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ValueError(f"RCS {label} contains control characters")
    return value


def _checked_url(value, label: str) -> str:
    value = _checked_text(value, label, 2048, required=True)
    parsed = urlsplit(_VARIABLE_PATTERN.sub("variable", value))
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):
        raise ValueError(f"RCS {label} must be an absolute HTTP(S) URL without credentials")
    return value


def _media_fields(file_name, media_url, image_bytes=None, required: bool = False) -> dict:
    if file_name:
        return {"fileName": _checked_text(file_name, "media fileName", 255, required=True)}
    if image_bytes:
        return {}
    if media_url:
        if isinstance(media_url, str) and media_url.startswith("/api/media/"):
            host = (os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("PUBLIC_APP_URL") or os.environ.get("APP_URL") or "").rstrip("/")
            if not host:
                raise ValueError("A public application URL is required for local RCS media without image bytes")
            media_url = host + media_url
        return {"mediaUrl": _checked_url(media_url, "media URL")}
    if required:
        raise ValueError("RCS rich card requires mediaUrl, provider fileName, or image bytes")
    return {}

def _provider_failed(data: dict) -> bool:
    status = str(data.get("status", "")).strip().lower()
    code = data.get("errorCode")
    return (
        status in ("failure", "failed", "error", "rejected", "false", "unauthorized", "forbidden")
        or data.get("success") is False
        or str(data.get("success", "")).strip().lower() in ("false", "0")
        or data.get("status") is False
        or (status.isdecimal() and int(status) >= 400)
        or bool(data.get("Failed") or data.get("error") or data.get("errorMessage"))
        or code not in (None, "", 0, "0", "000")
        or (isinstance(data.get("data"), dict) and _provider_failed(data["data"]))
    )


def _provider_reference(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    reference = str(value).strip()
    if not reference or reference.lower() in ("none", "null", "undefined", "false", "0") or any(ord(c) < 32 for c in reference):
        return None
    if isinstance(value, int) and value <= 0:
        return None
    return reference


class RcsInventoryUnavailable(RuntimeError):
    """Inventory could not be obtained; it must not be treated as an empty bot."""


class RcsAuthenticationRefused(RuntimeError):
    """Provider explicitly refused authentication before template save."""


def upload_rcs_media(image_data: bytes, filename: str = "image.png", client: str = "tata") -> str:
    """
    Upload a binary image or video to Karix RCS media storage (gRBM).
    Returns the generated fileName string from Karix.
    """
    import io

    c = client.lower()
    headers = dict(get_rcs_auth_headers(c))
    headers.pop("Content-Type", None)
    esme_addr = get_rcs_esmeaddr(c)
    stream = io.BytesIO(image_data)
    stream.seek(0)

    clean_filename = filename.split("/")[-1].split("\\")[-1] or "image.png"
    lower_name = clean_filename.lower()

    VIDEO_MIMES = {
        ".mp4": "video/mp4",
        ".m4v": "video/m4v",
        ".m4p": "video/m4p",
        ".mpeg": "video/mpeg",
        ".webm": "video/webm",
        ".h263": "video/h263",
    }

    if lower_name.endswith((".jpg", ".jpeg")):
        mime_type = "image/jpeg"
    elif lower_name.endswith(".gif"):
        mime_type = "image/gif"
    elif lower_name.endswith(".png"):
        mime_type = "image/png"
    elif any(lower_name.endswith(ext) for ext in VIDEO_MIMES):
        ext = next(e for e in VIDEO_MIMES if lower_name.endswith(e))
        mime_type = VIDEO_MIMES[ext]
    else:
        mime_type = "image/png"
        clean_filename += ".png"

    resp = requests.post(
        KARIX_RCS_MEDIA_UPLOAD_URL,
        headers=headers,
        files={"file": (clean_filename, stream, mime_type)},
        data={
            "esmeaddr": esme_addr,
            "file_type": mime_type,
            "channelId": "gRBM",
        },
        timeout=REQUEST_TIMEOUT,
        allow_redirects=False,
    )
    if resp.status_code in (401, 403):
        raise RcsAuthenticationRefused(f"RCS media upload authentication failed: HTTP {resp.status_code}")
    if not 200 <= resp.status_code < 300:
        raise RuntimeError(f"RCS media upload failed: HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError("RCS media upload returned invalid JSON") from exc
    if not isinstance(data, dict) or _provider_failed(data):
        raise RuntimeError("RCS media upload was not accepted")
    raw_file_name = data.get("fileName") or data.get("filename")
    file_name = _provider_reference(raw_file_name) if isinstance(raw_file_name, str) else None
    if file_name is None:
        raise RuntimeError("RCS media upload response missing fileName")
    return file_name


def _extract_and_number_rcs_variables(text: str, start_index: int = 1) -> tuple[str, list[str], int]:
    """
    Extract and sequentially number any bracket placeholder:
    <...>, [...], {...}, {#...#} -> [1], [2], [3]...
    Returns (normalized_text, list_of_param_numbers, next_start_index).
    """
    if not text:
        return text, [], start_index

    current_idx = start_index
    param_numbers = []

    pattern = _VARIABLE_PATTERN

    def repl(m):
        nonlocal current_idx
        v_str = str(current_idx)
        param_numbers.append(v_str)
        current_idx += 1
        return f"[{v_str}]"

    normalized_text = re.sub(pattern, repl, text)
    return normalized_text, param_numbers, current_idx


def _ensure_url_variable(url: str, var_number: int) -> str:
    """Karix expects a variable suffix for otherwise static action URLs."""
    return ensure_dynamic_cta_url(url).replace("{{1}}", f"[{var_number}]")


def _build_single_suggestion(payload: RcsTemplateSubmission) -> list[dict]:
    """Use the same explicit CTA parsing for rows and flat payload fields."""
    from rcs_loader import _build_suggestions_from_row

    return _build_suggestions_from_row({
        field: getattr(payload, field, "") or ""
        for field in ("button_type", "button_text", "button_url", "button_phone")
    })


def _build_rcs_clean_suggestions(raw_suggs: list, next_var_idx: int, param_names: list[str]) -> tuple[list[dict], int]:
    if not isinstance(raw_suggs, list):
        raise ValueError("RCS suggestions must be an array")
    clean_suggs = []
    for s in raw_suggs:
        if not isinstance(s, dict):
            raise ValueError("Each RCS suggestion must be an object")
        stext = _checked_text(s.get("text"), "suggestion text", 25, required=True)
        stype = s.get("suggestionType") or ("url_action" if s.get("url") else "dialer_action" if s.get("phoneNumber") else "reply")
        if stype not in ("reply", "url_action", "dialer_action"):
            raise ValueError(f"Unsupported RCS suggestion type: {stype}")
        suggestion = {
            "suggestionType": stype,
            "text": stext,
            "postbackData": _checked_text(s.get("postbackData") or stext, "postbackData", 2048),
        }
        if stype == "url_action":
            raw_url = _checked_url(s.get("url"), "action URL")
            b_url, url_params, following_idx = _extract_and_number_rcs_variables(raw_url, next_var_idx)
            if not url_params:
                b_url = _ensure_url_variable(raw_url, next_var_idx)
                url_params = [str(next_var_idx)]
                following_idx = next_var_idx + 1
            param_names.extend(url_params)
            next_var_idx = following_idx
            suggestion["url"] = b_url
        elif stype == "dialer_action":
            phone = s.get("phoneNumber")
            if not isinstance(phone, str) or not re.fullmatch(r"\+?[0-9]{3,15}", phone):
                raise ValueError("RCS dialer action requires a valid phoneNumber")
            suggestion["phoneNumber"] = phone
        clean_suggs.append(suggestion)
    return clean_suggs, next_var_idx


def _build_rcs_carousel_vi_template(
    payload: RcsTemplateSubmission, safe_name: str, bot_id: str
) -> tuple[dict, list[str]]:
    cards_list = []
    all_params: list[str] = []
    next_var_idx = 1

    for c_idx, card in enumerate((payload.carousel_cards or []), 1):
        c_title_raw = _checked_text(card.get("cardTitle") or card.get("card_title") or "", "card title", 200)
        c_title_norm, title_params, next_var_idx = _extract_and_number_rcs_variables(
            c_title_raw, start_index=next_var_idx
        )
        all_params.extend(title_params)

        c_desc_raw = _checked_text(card.get("cardDescription") or card.get("card_description") or card.get("body") or "", "card description", 2000)
        c_desc_norm, desc_params, next_var_idx = _extract_and_number_rcs_variables(c_desc_raw, start_index=next_var_idx)
        all_params.extend(desc_params)

        if "suggestions" in card:
            raw_suggs = card["suggestions"]
        elif card.get("button_text"):
            from rcs_loader import _build_suggestions_from_row
            raw_suggs = _build_suggestions_from_row(card)
        else:
            raw_suggs = []
        if not isinstance(raw_suggs, list) or len(raw_suggs) > 4:
            raise ValueError("RCS cards allow at most 4 suggestions in an array")
        clean_suggs, next_var_idx = _build_rcs_clean_suggestions(raw_suggs, next_var_idx, all_params)

        c_entry: dict = {"cardTitle": c_title_norm, "cardDescription": c_desc_norm, "suggestions": clean_suggs}
        c_entry.update(_media_fields(card.get("fileName") or card.get("file_name"), card.get("mediaUrl") or card.get("media_url"), card.get("image_bytes")))
        cards_list.append(c_entry)
    vi_template = {
        "name": safe_name,
        "type": "carousel",
        "botId": bot_id,
        "height": getattr(payload, "height", "MEDIUM") or "MEDIUM",
        "width": getattr(payload, "width", "MEDIUM") or "MEDIUM",
        "carouselCard": cards_list,
    }
    return vi_template, all_params


def _build_rcs_richcard_vi_template(
    payload: RcsTemplateSubmission, safe_name: str, bot_id: str
) -> tuple[dict, list[str]]:
    raw_title = _checked_text(payload.card_title or "", "card title", 200)
    c_title_norm, title_params, next_var_idx = _extract_and_number_rcs_variables(raw_title, start_index=1)

    raw_text = _checked_text(payload.card_description or payload.text_message or "", "card description", 2000)
    normalized_text, param_names, next_var_idx = _extract_and_number_rcs_variables(raw_text, start_index=next_var_idx)
    all_params = title_params + param_names

    raw_suggs = payload.suggestions
    if not raw_suggs and getattr(payload, "button_text", None):
        raw_suggs = _build_single_suggestion(payload)
    if not isinstance(raw_suggs, list) or len(raw_suggs) > 4:
        raise ValueError("RCS cards allow at most 4 suggestions in an array")
    clean_suggs, _ = _build_rcs_clean_suggestions(raw_suggs, next_var_idx, all_params)

    card_entry: dict = {
        "cardTitle": c_title_norm,
        "cardDescription": normalized_text,
        "suggestions": clean_suggs,
    }
    card_entry.update(_media_fields(payload.file_name, payload.media_url, payload.image_bytes))
    vi_template = {
        "name": safe_name,
        "type": "richcard",
        "botId": bot_id,
        "orientation": getattr(payload, "orientation", "VERTICAL") or "VERTICAL",
        "height": getattr(payload, "height", "MEDIUM") or "MEDIUM",
        "standaloneCard": card_entry,
    }
    return vi_template, all_params


def _build_rcs_text_vi_template(payload: RcsTemplateSubmission, safe_name: str, bot_id: str) -> tuple[dict, list[str]]:
    raw_text = payload.text_message or getattr(payload, "template_message", "") or ""
    if payload.card_title and payload.card_title.strip() and payload.card_title.strip() not in raw_text:
        raw_text = f"{payload.card_title.strip()}\n\n{raw_text}"
    raw_text = _checked_text(raw_text, "text message", 3072, required=True)
    normalized_text, param_names, next_var_idx = _extract_and_number_rcs_variables(raw_text, start_index=1)
    raw_suggs = payload.suggestions or (
        _build_single_suggestion(payload) if getattr(payload, "button_text", None) else []
    )
    if not isinstance(raw_suggs, list) or len(raw_suggs) > 11:
        raise ValueError("RCS text allows at most 11 suggestions in an array")
    clean_suggs, _ = _build_rcs_clean_suggestions(raw_suggs, next_var_idx, param_names)

    vi_template = {
        "name": safe_name,
        "type": "text",
        "botId": bot_id,
        "textMessage": normalized_text,
        "suggestions": clean_suggs,
    }
    return vi_template, param_names


def _build_rcs_save_payload(payload: RcsTemplateSubmission, client: str = "tata") -> dict:
    """
    Build the JSON payload matching the official Karix RCS Template Management API.
    """
    c = client.strip().lower()
    _account_prefix(c)
    if payload.client.strip().lower() != c:
        raise ValueError("RCS payload account does not match the selected account")
    configured_bot = get_rcs_bot_id(c)
    configured_esme = get_rcs_esmeaddr(c)
    if payload.bot_id and payload.bot_id != configured_bot:
        raise ValueError("RCS bot ID does not match the selected account")
    if payload.esme_addr and str(payload.esme_addr) != configured_esme:
        raise ValueError("RCS ESME address does not match the selected account")
    bot_id = _checked_text(configured_bot, "bot ID", 255, required=True)
    esme_addr_raw = configured_esme
    if not re.fullmatch(r"[0-9]+", str(esme_addr_raw)):
        raise ValueError("RCS ESME address must be a positive decimal identifier")
    esme_addr = int(esme_addr_raw)
    if esme_addr <= 0 or str(esme_addr) != str(esme_addr_raw):
        raise ValueError("RCS ESME address must be a positive decimal identifier without leading zeros")
    safe_name = normalize_rcs_template_name(payload.template_name)
    t_type = str(payload.template_type).strip().lower()
    if t_type in ("carousel", "carousal", "carousel_cards", "multi_card"):
        if not isinstance(payload.carousel_cards, list) or not 2 <= len(payload.carousel_cards) <= 10 or not all(isinstance(card, dict) for card in payload.carousel_cards):
            raise ValueError("RCS carousel must contain 2 to 10 card objects")
        if payload.height not in ("SHORT", "MEDIUM") or payload.width not in ("SMALL", "MEDIUM"):
            raise ValueError("Invalid RCS carousel height or width")
        vi_template, param_names = _build_rcs_carousel_vi_template(payload, safe_name, bot_id)
    elif t_type in ("richcard", "card", "standalone", "rich_card", "image"):
        if payload.orientation not in ("VERTICAL", "HORIZONTAL") or payload.height not in ("SHORT", "MEDIUM", "TALL"):
            raise ValueError("Invalid RCS rich card orientation or height")
        vi_template, param_names = _build_rcs_richcard_vi_template(payload, safe_name, bot_id)
    elif t_type in ("text", "plain", "standard", "plain_text", "transactional", "promotional"):
        if payload.carousel_cards:
            raise ValueError("Carousel cards require carousel template type")
        vi_template, param_names = _build_rcs_text_vi_template(payload, safe_name, bot_id)
    else:
        raise ValueError(f"Unsupported RCS template type: {payload.template_type}")
    if payload.template_category not in ("TRANSACTIONAL", "PROMOTIONAL"):
        raise ValueError("RCS category must be TRANSACTIONAL or PROMOTIONAL")

    return {
        "esmeAddr": esme_addr,
        "templatePlaceHolderCount": len(param_names),
        "templateParamNames": param_names,
        "viTemplate": vi_template,
        "templateCategory": getattr(payload, "template_category", "TRANSACTIONAL") or "TRANSACTIONAL",
    }


def submit_rcs_template(payload: RcsTemplateSubmission, client: str | None = None) -> RcsSubmissionResult:
    """Submit once: save is not idempotent, so uncertain outcomes require reconciliation."""
    selected_client = client if client is not None else payload.client
    c = selected_client.strip().lower() if isinstance(selected_client, str) else ""
    result = RcsSubmissionResult(
        source_ref=payload.source_ref,
        template_name=payload.template_name,
        status=RcsSubmissionStatus.FAILED,
        approval_status="unknown",
        client=c,
        channel=payload.channel,
        bot_id=payload.bot_id,
    )
    if payload.aspect_ratio_blocked:
        result.status = RcsSubmissionStatus.BLOCKED_ASPECT_RATIO
        result.approval_status = "blocked_aspect_ratio"
        result.error = payload.aspect_ratio_error or "Invalid RCS image aspect ratio"
        return result
    try:
        data_payload = _build_rcs_save_payload(payload, client=c)
        result.bot_id = data_payload["viTemplate"]["botId"]
        headers = get_rcs_auth_headers(c)
        from rcs_loader import check_rcs_image_aspect_ratio
        images = [(payload.image_bytes, payload.file_name, data_payload["viTemplate"].get("standaloneCard"), payload)] if payload.image_bytes else []
        if data_payload["viTemplate"]["type"] == "carousel":
            images = [(card.get("image_bytes"), card.get("fileName"), entry, card) for card, entry in zip(payload.carousel_cards, data_payload["viTemplate"]["carouselCard"], strict=True) if card.get("image_bytes")]
        for image, _, entry, _ in images:
            if entry is None:
                raise ValueError("Embedded RCS media requires a rich card or carousel")
            valid, reason, _, _ = check_rcs_image_aspect_ratio(image, payload.template_type)
            maximum = 1024 * 1024 if data_payload["viTemplate"]["type"] == "carousel" else 2 * 1024 * 1024
            if not valid or len(image) > maximum:
                result.status = RcsSubmissionStatus.BLOCKED_ASPECT_RATIO
                result.approval_status = "blocked_aspect_ratio"
                result.error = reason or f"RCS media exceeds {maximum} bytes"
                return result
        uploaded = {}
        for image, existing, entry, original in images:
            if not existing:
                source_name = (original.get("image_filename") if isinstance(original, dict) else original.image_filename) or "image.png"
                if image not in uploaded:
                    uploaded[image] = upload_rcs_media(image, filename=source_name, client=c)
                file_name = uploaded[image]
                entry.pop("mediaUrl", None)
                entry["fileName"] = file_name
                if isinstance(original, dict):
                    original["fileName"] = file_name
                else:
                    original.file_name = file_name
    except (OSError, ValueError, TypeError, RuntimeError, requests.RequestException) as exc:
        result.auth_refused = isinstance(exc, RcsAuthenticationRefused)
        result.error = f"RCS submission not sent: {exc}"
        return result
    try:
        resp = requests.post(KARIX_RCS_SAVE_URL, headers=headers, json=data_payload, timeout=REQUEST_TIMEOUT, allow_redirects=False)
    except requests.RequestException as exc:
        result.outcome_uncertain = True
        result.error = f"RCS save outcome unknown ({type(exc).__name__}); reconcile this template with Karix before retrying."
        return result
    try:
        response_data = resp.json()
    except ValueError:
        response_data = None
    data = response_data if isinstance(response_data, dict) else {"_raw_text": resp.text[:1000]}
    result.provider_response = data
    raw_error = str(data.get("errorMessage") or data.get("error") or data.get("reason") or data.get("Failed") or data.get("message") or "")
    auth_failure = str(data.get("status", "")).lower() in ("unauthorized", "forbidden") or str(data.get("errorCode", "")) in ("401", "403")
    auth_failure = auth_failure or bool(re.search(r"\b(?:unauthorized|forbidden|authentication failed|invalid token|expired token|session expired|invalid session)\b", raw_error, re.IGNORECASE))
    if resp.status_code in (401, 403) or auth_failure:
        result.auth_refused = True
        result.error = f"RCS save authentication failed: HTTP {resp.status_code}"
        return result
    rejected = not 200 <= resp.status_code < 300 or _provider_failed(data)
    duplicate = re.search(r"\b(?:already\s+exists?|duplicate)\b", raw_error, re.IGNORECASE)
    if duplicate and not re.search(r"\b(?:not|no)\s+(?:a\s+)?duplicate\b", raw_error, re.IGNORECASE) and rejected and (200 <= resp.status_code < 300 or resp.status_code == 409):
        result.status = RcsSubmissionStatus.DUPLICATE
        result.error = raw_error
        return result
    if rejected:
        result.outcome_uncertain = resp.status_code >= 500 or resp.status_code == 429
        result.error = f"RCS save HTTP {resp.status_code}: {raw_error or 'provider rejected submission'}"
        if result.outcome_uncertain:
            result.error += "; reconcile with Karix before retrying."
        return result
    data_inner = data.get("data") if isinstance(data.get("data"), dict) else {}
    valid_envelope = all(
        ("status" not in container or isinstance(container["status"], (str, int, bool)))
        and ("success" not in container or str(container["success"]).strip().lower() in ("true", "false", "0", "1"))
        for container in (data, data_inner)
    ) and ("data" not in data or isinstance(data["data"], dict))
    references = [_provider_reference(container[key]) for container in (data, data_inner) for key in ("templateId", "id") if key in container]
    template_id = references[0] if valid_envelope and references and all(reference == references[0] for reference in references) else None
    if not template_id or str(template_id).lower() in ("none", "null"):
        result.outcome_uncertain = True
        result.error = "RCS save returned an invalid or ambiguous response without a valid template ID; reconcile with Karix before retrying."
        return result
    result.template_id = result.provider_ref_id = str(template_id)
    result.status = RcsSubmissionStatus.SUBMITTED
    result.approval_status = "submitted"
    return result


def fetch_rcs_templates(
    bot_id: str | None = None, client: str = "tata", *, auth_token: str | None = None,
) -> list[dict]:
    """Return a valid inventory, including []; raise when provider inventory is unavailable."""
    try:
        c = client.strip().lower()
        configured_bots = get_rcs_bot_ids(c)
        if bot_id and bot_id not in configured_bots:
            raise ValueError("RCS inventory bot ID does not match the selected account")

        headers = get_rcs_auth_headers(c, auth_token=auth_token)
        esme = get_rcs_esmeaddr(c)

        if c == "apparel" and not bot_id and len(configured_bots) > 1:
            from concurrent.futures import ThreadPoolExecutor

            def _fetch_one_bot(sid: str) -> list[dict]:
                try:
                    resp = requests.post(
                        KARIX_RCS_FETCH_TEMPLATES_URL,
                        headers=headers,
                        json={"esmeaddr": esme, "senderId": sid},
                        timeout=REQUEST_TIMEOUT,
                        allow_redirects=False,
                    )
                    if 200 <= resp.status_code < 300:
                        data = resp.json()
                        t_list = data.get("templateInfo") if isinstance(data, dict) and not _provider_failed(data) else []
                        if isinstance(t_list, list):
                            for t in t_list:
                                if isinstance(t, dict) and not t.get("botId"):
                                    t["botId"] = sid
                            return t_list
                except Exception as ex:
                    logger.warning("Error fetching templates for bot %s on %s: %s", sid, c, ex)
                return []

            with ThreadPoolExecutor(max_workers=min(len(configured_bots), 10)) as pool:
                bot_results = list(pool.map(_fetch_one_bot, configured_bots))

            all_templates = []
            seen_keys = set()
            for items in bot_results:
                for item in items:
                    key = (item.get("templateId"), item.get("botId"))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        all_templates.append(item)
            return all_templates

        target_bot = bot_id or (configured_bots[0] if configured_bots else get_rcs_bot_id(c))
        resp = requests.post(
            KARIX_RCS_FETCH_TEMPLATES_URL,
            headers=headers,
            json={"esmeaddr": esme, "senderId": target_bot},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )
        if not 200 <= resp.status_code < 300:
            raise RcsInventoryUnavailable(f"RCS inventory HTTP {resp.status_code}")
        data = resp.json()
        templates = data.get("templateInfo") if isinstance(data, dict) and not _provider_failed(data) else None
        if not isinstance(templates, list) or not all(isinstance(template, dict) for template in templates):
            raise RcsInventoryUnavailable("Invalid RCS template inventory response")
        return templates
    except (OSError, ValueError, TypeError, requests.RequestException) as exc:
        raise RcsInventoryUnavailable(f"RCS inventory unavailable for {client}: {type(exc).__name__}") from exc
