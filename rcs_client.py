"""
Client for Karix RCS Bot Builder Template Management API.

Sends RcsTemplateSubmission payloads to the official Karix RCS endpoint:
POST https://rcsgui.karix.solutions/api/rcstemplate/save
"""

import json
import logging
import re
import time

import requests

from config import get_esmeaddr
from rcs_config import (
    KARIX_RCS_SAVE_URL,
    get_rcs_auth_headers,
    get_rcs_bot_id,
)
from rcs_models import (
    RcsSubmissionResult,
    RcsSubmissionStatus,
    RcsTemplateSubmission,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants & Timeout
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
BACKOFF_SECONDS = 2
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def upload_rcs_media(image_data: bytes, filename: str = "image.png", client: str = "tata") -> str:
    """
    Upload a binary image or video to Karix RCS media storage (gRBM).
    Returns the generated fileName string from Karix.
    """
    import io

    c = client.lower()
    headers = dict(get_rcs_auth_headers(c))
    headers.pop("Content-Type", None)
    esme_addr = get_esmeaddr(c)
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
        "https://rcsgui.karix.solutions/v1.0/templates/mediaUpload",
        headers=headers,
        files={"file": (clean_filename, stream, mime_type)},
        data={
            "esmeaddr": esme_addr,
            "file_type": mime_type,
            "channelId": "gRBM",
        },
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        raise RuntimeError(f"RCS media upload failed: HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    file_name = data.get("fileName") or data.get("filename")
    if not file_name:
        raise RuntimeError(f"RCS media upload response missing fileName: {data}")
    logger.info("Uploaded RCS media: fileName=%s mime=%s", file_name, mime_type)
    return str(file_name)


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

    pattern = r"(<[^>]+>|\[[^\]]+\]|\{[^}]+\}|\{#[^#]+#\})"

    def repl(m):
        nonlocal current_idx
        v_str = str(current_idx)
        param_numbers.append(v_str)
        current_idx += 1
        return f"[{v_str}]"

    # Spacing around tight tags
    spaced_text = re.sub(r"([A-Za-z0-9])(<[^>]+>)", r"\1 \2", text)
    spaced_text = re.sub(r"(<[^>]+>)([A-Za-z0-9])", r"\1 \2", spaced_text)
    spaced_text = re.sub(r"([A-Za-z0-9])(\{#[^#]+#\})", r"\1 \2", spaced_text)

    normalized_text = re.sub(pattern, repl, spaced_text)
    return normalized_text, param_numbers, current_idx


def _ensure_url_variable(url: str, var_number: int) -> str:
    """Ensure URL has sequential variable at the end: e.g. https://www.tatacapital.com[4]"""
    base = (url or "https://www.tatacapital.com").strip().rstrip("/")
    clean_base = re.sub(r"\[\w+\]$", "", base)
    return f"{clean_base}[{var_number}]"


def _build_single_suggestion(payload: RcsTemplateSubmission) -> list[dict]:
    """Helper to convert flat button fields on a payload into suggestions array."""
    suggestions = []
    btype = (getattr(payload, "button_type", "URL") or "URL").upper()
    btext = getattr(payload, "button_text", "") or ""
    burl = getattr(payload, "button_url", "") or ""
    bphone = getattr(payload, "button_phone", "") or ""

    if btext:
        if "|" in btext and btype in ("", "REPLY", "SUGGESTION"):
            for item in btext.split("|"):
                clean = item.strip()
                if clean:
                    suggestions.append(
                        {
                            "suggestionType": "reply",
                            "text": clean,
                            "postbackData": clean.lower().replace(" ", "_"),
                        }
                    )
        elif btype in ("URL", "URL_ACTION", "LINK") or burl:
            suggestions.append(
                {
                    "suggestionType": "url_action",
                    "text": btext or "Open Link",
                    "postbackData": btext.lower().replace(" ", "_") if btext else "open_url",
                    "url": burl or "https://www.tatacapital.com",
                }
            )
        elif btype in ("DIALER", "DIALER_ACTION", "CALL", "PHONE") or bphone:
            suggestions.append(
                {
                    "suggestionType": "dialer_action",
                    "text": btext or "Call Now",
                    "postbackData": btext.lower().replace(" ", "_") if btext else "call_now",
                    "phoneNumber": bphone or "+919999999999",
                }
            )
        else:
            suggestions.append(
                {
                    "suggestionType": "reply",
                    "text": btext,
                    "postbackData": btext.lower().replace(" ", "_"),
                }
            )
    return suggestions


def _build_rcs_save_payload(payload: RcsTemplateSubmission, client: str = "tata") -> dict:
    """
    Build the JSON payload matching the official Karix RCS Template Management API.
    """
    c = client.lower()
    bot_id = payload.bot_id or get_rcs_bot_id(c)
    esme_addr_raw = get_esmeaddr(c)

    try:
        esme_addr = int(esme_addr_raw)
    except (ValueError, TypeError):
        esme_addr = 72516600000000 if c == "tata" else 72148300000000

    # Sanitize and enforce max 25 chars for RCS template name
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", payload.template_name)[:25]

    # Determine template format
    is_carousel = payload.template_type.lower() == "carousel" or bool(getattr(payload, "carousel_cards", None))
    is_richcard = not is_carousel and (
        payload.template_type.lower() == "richcard" or bool(payload.media_url) or bool(payload.card_title)
    )

    # Assemble viTemplate
    if is_carousel:
        cards_list = []
        all_params = []
        next_var_idx = 1

        for c_idx, card in enumerate((payload.carousel_cards or []), 1):
            c_title_raw = card.get("cardTitle") or card.get("card_title") or f"Offer {c_idx}"
            c_desc_raw = card.get("cardDescription") or card.get("card_description") or card.get("body") or ""

            # Number variables in description sequentially
            c_desc_norm, desc_params, next_var_idx = _extract_and_number_rcs_variables(
                c_desc_raw, start_index=next_var_idx
            )
            all_params.extend(desc_params)

            # Title (clean tags)
            c_title_norm = re.sub(r"<[^>]+>|\[[^\]]+\]", "", c_title_raw).strip()[:100]
            if not c_title_norm:
                c_title_norm = f"Special Offer {c_idx}"

            # Build suggestions with guaranteed sequential URL variable
            clean_suggs = []
            raw_suggs = card.get("suggestions") or []
            if not raw_suggs and getattr(payload, "button_text", None):
                raw_suggs = _build_single_suggestion(payload)
            if not raw_suggs:
                raw_suggs = [
                    {
                        "suggestionType": "url_action",
                        "text": "Apply Now",
                        "url": "https://www.tatacapital.com",
                    }
                ]

            for s in raw_suggs:
                stext = s.get("text") or "Apply Now"
                stype = s.get("suggestionType") or ("url_action" if s.get("url") else "reply")

                if stype == "url_action" or s.get("url"):
                    url_var_num = str(next_var_idx)
                    all_params.append(url_var_num)
                    next_var_idx += 1
                    b_url = _ensure_url_variable(s.get("url") or "https://www.tatacapital.com", int(url_var_num))
                    clean_suggs.append(
                        {
                            "suggestionType": "url_action",
                            "text": stext,
                            "postbackData": s.get("postbackData") or stext.lower().replace(" ", "_"),
                            "url": b_url,
                        }
                    )
                elif stype == "dialer_action" or s.get("phoneNumber"):
                    clean_suggs.append(
                        {
                            "suggestionType": "dialer_action",
                            "text": stext,
                            "postbackData": s.get("postbackData") or stext.lower().replace(" ", "_"),
                            "phoneNumber": s.get("phoneNumber") or "+919999999999",
                        }
                    )
                else:
                    clean_suggs.append(
                        {
                            "suggestionType": "reply",
                            "text": stext,
                            "postbackData": s.get("postbackData") or stext.lower().replace(" ", "_"),
                        }
                    )

            c_entry = {
                "cardTitle": c_title_norm,
                "cardDescription": c_desc_norm,
            }
            if card.get("fileName") or card.get("file_name"):
                c_entry["fileName"] = card.get("fileName") or card.get("file_name")
            elif card.get("mediaUrl") or card.get("media_url"):
                c_entry["mediaUrl"] = card.get("mediaUrl") or card.get("media_url")
            else:
                raise ValueError(
                    f"Card {c_idx} ('{c_title_norm}') is missing an image. "
                    "Please ensure images are pasted in the Excel file or media URLs are provided."
                )
            c_entry["suggestions"] = clean_suggs
            cards_list.append(c_entry)

        if len(cards_list) < 2:
            cards_list.append(
                {
                    "cardTitle": "Instant Approval",
                    "cardDescription": "Fast disbursement with flexible repayment terms.",
                    "mediaUrl": "https://images.unsplash.com/photo-1554224155-6726b3ff858f?w=1280&h=720&fit=crop",
                    "suggestions": [
                        {
                            "suggestionType": "url_action",
                            "text": "Apply Now",
                            "postbackData": "apply_now",
                            "url": f"https://www.tatacapital.com[{next_var_idx}]",
                        }
                    ],
                }
            )
            all_params.append(str(next_var_idx))
            next_var_idx += 1

        param_names = all_params
        vi_template = {
            "name": safe_name,
            "type": "carousel",
            "botId": bot_id,
            "height": getattr(payload, "height", "MEDIUM") or "MEDIUM",
            "width": getattr(payload, "width", "MEDIUM") or "MEDIUM",
            "carouselCard": cards_list,
        }
    elif is_richcard:
        raw_text = payload.card_description or payload.text_message or getattr(payload, "template_message", "")
        normalized_text, param_names, next_var_idx = _extract_and_number_rcs_variables(raw_text, start_index=1)

        raw_suggs = payload.suggestions or []
        if not raw_suggs and getattr(payload, "button_text", None):
            raw_suggs = _build_single_suggestion(payload)
        if not raw_suggs:
            raw_suggs = [
                {
                    "suggestionType": "url_action",
                    "text": "Apply Now",
                    "url": "https://www.tatacapital.com",
                }
            ]

        clean_suggs = []
        for s in raw_suggs:
            stext = s.get("text") or "Apply Now"
            stype = s.get("suggestionType") or ("url_action" if s.get("url") else "reply")
            if stype == "url_action" or s.get("url"):
                url_var_num = str(next_var_idx)
                param_names.append(url_var_num)
                next_var_idx += 1
                b_url = _ensure_url_variable(s.get("url") or "https://www.tatacapital.com", int(url_var_num))
                clean_suggs.append(
                    {
                        "suggestionType": "url_action",
                        "text": stext,
                        "postbackData": s.get("postbackData") or stext.lower().replace(" ", "_"),
                        "url": b_url,
                    }
                )
            else:
                clean_suggs.append(
                    {
                        "suggestionType": stype,
                        "text": stext,
                        "postbackData": s.get("postbackData") or stext.lower().replace(" ", "_"),
                    }
                )

        card_entry = {
            "cardTitle": payload.card_title or payload.template_name.replace("_", " ").title(),
            "cardDescription": normalized_text,
            "suggestions": clean_suggs,
        }
        if getattr(payload, "file_name", None):
            card_entry["fileName"] = payload.file_name
        elif payload.media_url:
            card_entry["mediaUrl"] = payload.media_url
        else:
            raise ValueError(
                f"Rich Card '{payload.template_name}' is missing an image. "
                "Please ensure an image is pasted in the Excel file or a media URL is provided."
            )
        vi_template = {
            "name": safe_name,
            "type": "richcard",
            "botId": bot_id,
            "orientation": getattr(payload, "orientation", "VERTICAL") or "VERTICAL",
            "height": getattr(payload, "height", "MEDIUM") or "MEDIUM",
            "standaloneCard": card_entry,
        }
    else:
        raw_text = payload.text_message or getattr(payload, "template_message", "")
        normalized_text, param_names, next_var_idx = _extract_and_number_rcs_variables(raw_text, start_index=1)

        raw_suggs = payload.suggestions or []
        if not raw_suggs and getattr(payload, "button_text", None):
            raw_suggs = _build_single_suggestion(payload)

        clean_suggs = []
        for s in raw_suggs:
            stext = s.get("text") or "Apply Now"
            stype = s.get("suggestionType") or ("url_action" if s.get("url") else "reply")
            if stype == "url_action" or s.get("url"):
                url_var_num = str(next_var_idx)
                param_names.append(url_var_num)
                next_var_idx += 1
                b_url = _ensure_url_variable(s.get("url") or "https://www.tatacapital.com", int(url_var_num))
                clean_suggs.append(
                    {
                        "suggestionType": "url_action",
                        "text": stext,
                        "postbackData": s.get("postbackData") or stext.lower().replace(" ", "_"),
                        "url": b_url,
                    }
                )
            else:
                clean_suggs.append(
                    {
                        "suggestionType": stype,
                        "text": stext,
                        "postbackData": s.get("postbackData") or stext.lower().replace(" ", "_"),
                    }
                )

        vi_template = {
            "name": safe_name,
            "type": "text",
            "botId": bot_id,
            "textMessage": normalized_text,
            "suggestions": clean_suggs,
        }

    return {
        "esmeAddr": esme_addr,
        "templatePlaceHolderCount": len(param_names),
        "templateParamNames": param_names,
        "viTemplate": vi_template,
        "templateCategory": getattr(payload, "template_category", "TRANSACTIONAL") or "TRANSACTIONAL",
    }


def submit_rcs_template(payload: RcsTemplateSubmission, client: str = "tata") -> RcsSubmissionResult:
    """
    Submit one RCS template to the official Karix RCS Bot Builder Template API.
    """
    c = (client or getattr(payload, "client", None) or "tata").lower()
    data_payload = _build_rcs_save_payload(payload, client=c)
    last_result: RcsSubmissionResult | None = None

    for attempt in range(MAX_RETRIES):
        exc: Exception | None = None
        resp: requests.Response | None = None

        try:
            headers = get_rcs_auth_headers(c)
            resp = requests.post(
                KARIX_RCS_SAVE_URL,
                headers=headers,
                json=data_payload,
                timeout=REQUEST_TIMEOUT,
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            exc = e
            logger.warning("Attempt %d/%d transport error: %s", attempt + 1, MAX_RETRIES, e)
        except OSError as e:
            return RcsSubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                template_id=None,
                status=RcsSubmissionStatus.FAILED,
                error=str(e),
                client=c,
                retry_count=attempt,
            )

        # Transport errors (retry)
        if exc is not None:
            last_result = RcsSubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                template_id=None,
                status=RcsSubmissionStatus.FAILED,
                error=str(exc),
                client=c,
                retry_count=attempt,
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_SECONDS * (2**attempt))
            continue

        # Parse response
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            data = {"_raw_text": resp.text}

        # Retryable HTTP status (429, 5xx)
        if resp.status_code in _RETRYABLE_STATUS_CODES:
            logger.warning(
                "Attempt %d/%d retryable HTTP %d: %s",
                attempt + 1,
                MAX_RETRIES,
                resp.status_code,
                resp.text[:200],
            )
            last_result = RcsSubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                template_id=None,
                status=RcsSubmissionStatus.FAILED,
                error=f"HTTP {resp.status_code}",
                provider_response=data,
                client=c,
                retry_count=attempt,
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_SECONDS * (2**attempt))
            continue

        # Non-200 responses
        if not resp.ok:
            error_msg = data.get("errorMessage") or data.get("error") or data.get("reason") or resp.text[:300]
            status_enum = (
                RcsSubmissionStatus.DUPLICATE
                if "already exist" in str(error_msg).lower()
                else RcsSubmissionStatus.FAILED
            )
            return RcsSubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                template_id=None,
                status=status_enum,
                error=f"HTTP {resp.status_code}: {error_msg}",
                provider_response=data,
                client=c,
                retry_count=attempt,
            )

        # Check for logical failure in 200 responses
        if isinstance(data, dict) and (data.get("status") in ("failure", "error") or "Failed" in data):
            err = data.get("reason") or data.get("Failed") or str(data)
            return RcsSubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                template_id=None,
                status=RcsSubmissionStatus.FAILED,
                error=str(err),
                provider_response=data,
                client=c,
                retry_count=attempt,
            )

        # Success: response contains templateId (e.g. {"templateId": "4484"})
        template_id = str(data.get("templateId", "") or data.get("id", "") or payload.template_name)
        return RcsSubmissionResult(
            source_ref=payload.source_ref,
            template_name=payload.template_name,
            template_id=template_id,
            status=RcsSubmissionStatus.SUBMITTED,
            provider_response=data,
            client=c,
            retry_count=attempt,
        )

    return last_result


def fetch_rcs_templates(bot_id: str | None = None, client: str = "tata") -> list[dict]:
    """
    Fetch all live RCS templates for the bot ID from official Karix RCS endpoint:
    POST https://rcsgui.karix.solutions/api/rcstemplate/fetchTemplates
    """
    c = client.lower()
    b_id = bot_id or get_rcs_bot_id(c)
    esme_addr = get_esmeaddr(c)
    try:
        headers = get_rcs_auth_headers(c)
        resp = requests.post(
            "https://rcsgui.karix.solutions/api/rcstemplate/fetchTemplates",
            headers=headers,
            json={"esmeaddr": str(esme_addr), "senderId": b_id},
            timeout=REQUEST_TIMEOUT,
        )
        if not resp.ok:
            logger.error(
                "Failed to fetch RCS templates: HTTP %d: %s",
                resp.status_code,
                resp.text[:300],
            )
            return []
        data = resp.json()
        return data.get("templateInfo", [])
    except Exception as exc:
        logger.error("Error fetching live RCS templates for %s: %s", c, exc)
        return []
