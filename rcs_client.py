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
    KARIX_RCS_FETCH_URL,
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
# Retry policy
# ---------------------------------------------------------------------------
MAX_RETRIES = 3
BACKOFF_SECONDS = 2  # doubles each retry: 2 s → 4 s → 8 s
REQUEST_TIMEOUT = 30  # seconds

# HTTP status codes worth retrying (transport-level)
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _extract_rcs_variables(text: str) -> tuple[str, list[str]]:
    """
    Extract and normalize variables into RCS bracket syntax [ParamName].
    Returns (normalized_text, list_of_param_names).
    """
    if not text:
        return text, []

    # Normalization map for non-bracket formats:
    # <name> -> [Name], {{1}} -> [Param_1], {#var#} -> [Var_1]
    param_names = []

    def repl(m):
        raw = m.group(0)
        clean = re.sub(r'[^a-zA-Z0-9_]', '', raw)
        if not clean or clean.isdigit():
            name = f"Param_{len(param_names) + 1}"
        else:
            name = clean
        param_names.append(name)
        return f"[{name}]"

    # Match bracket format [Name] or <name> or {{1}} or {#var#}
    pattern = r'(\[[a-zA-Z0-9_]+\]|<[^>]+>|\{\{[^}]+\}\}|\{#[^#]+#\})'
    normalized_text = re.sub(pattern, repl, text)

    # If text already had pure bracket variables, extract them
    if not param_names:
        param_names = re.findall(r'\[([a-zA-Z0-9_]+)\]', text)

    return normalized_text, param_names


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

    # Determine message text and variables
    is_richcard = (
        payload.template_type.lower() == "richcard"
        or bool(payload.media_url)
        or bool(payload.card_title)
    )

    raw_text = (
        payload.card_description
        or payload.text_message
        or getattr(payload, "template_message", "")
    )
    normalized_text, param_names = _extract_rcs_variables(raw_text)

    # Format suggestions
    suggestions = []
    if payload.suggestions:
        suggestions = payload.suggestions
    elif hasattr(payload, "button_text") and payload.button_text:
        btype = getattr(payload, "button_type", "URL") or "URL"
        btext = payload.button_text
        burl = getattr(payload, "button_url", "")
        bphone = getattr(payload, "button_phone", "")

        if btype.upper() in ("URL", "URL_ACTION") and burl:
            suggestions.append({
                "suggestionType": "url_action",
                "text": btext,
                "postbackData": btext.lower().replace(" ", "_"),
                "url": burl,
            })
        elif btype.upper() in ("DIALER", "DIALER_ACTION", "CALL") and bphone:
            suggestions.append({
                "suggestionType": "dialer_action",
                "text": btext,
                "postbackData": btext.lower().replace(" ", "_"),
                "phoneNumber": bphone,
            })
        else:
            suggestions.append({
                "suggestionType": "reply",
                "text": btext,
                "postbackData": btext.lower().replace(" ", "_"),
            })

    # Assemble viTemplate
    if is_richcard:
        vi_template = {
            "name": payload.template_name,
            "type": "richcard",
            "botId": bot_id,
            "orientation": getattr(payload, "orientation", "VERTICAL") or "VERTICAL",
            "height": getattr(payload, "height", "MEDIUM") or "MEDIUM",
            "standaloneCard": {
                "cardTitle": payload.card_title or payload.template_name.replace("_", " ").title(),
                "cardDescription": normalized_text,
                "mediaUrl": payload.media_url or "https://www.tatacapital.com/content/dam/tata-capital/header-logo/tata-capital-logo.png",
                "suggestions": suggestions,
            },
        }
    else:
        vi_template = {
            "name": payload.template_name,
            "type": "text",
            "botId": bot_id,
            "textMessage": normalized_text,
            "suggestions": suggestions,
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
                time.sleep(BACKOFF_SECONDS * (2 ** attempt))
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
                attempt + 1, MAX_RETRIES, resp.status_code, resp.text[:200],
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
                time.sleep(BACKOFF_SECONDS * (2 ** attempt))
            continue

        # Non-200 responses
        if not resp.ok:
            error_msg = data.get("errorMessage") or data.get("error") or data.get("reason") or resp.text[:300]
            status_enum = RcsSubmissionStatus.DUPLICATE if "already exist" in str(error_msg).lower() else RcsSubmissionStatus.FAILED
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
    Fetch all RCS templates for the bot ID from the official Karix RCS endpoint.
    """
    c = client.lower()
    b_id = bot_id or get_rcs_bot_id(c)
    headers = get_rcs_auth_headers(c)
    url = f"{KARIX_RCS_FETCH_URL}?senderId={b_id}"

    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    if not resp.ok:
        logger.error("Failed to fetch RCS templates: HTTP %d: %s", resp.status_code, resp.text[:300])
        return []

    data = resp.json()
    return data.get("templateInfo", [])
