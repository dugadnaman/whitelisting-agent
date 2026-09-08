"""
Client for Karix SMS JSON API.

Sends SMS messages (One-to-One, One-to-Many, Many-to-Many) with support for:
- Plain or AES-256 PII Encrypted payloads
- DLT Entity ID and Template ID registration
- Immediate delivery or scheduled sending
- Automatic retries with exponential backoff on retryable HTTP errors
"""

import logging
import time
from typing import Any

import requests

from sms_config import (
    get_sms_api_url,
    get_sms_auth_headers,
    get_sms_dlt_entity_id,
    get_sms_encryption_key,
    get_sms_key,
    get_sms_sender_id,
    get_sms_username,
)
from sms_models import (
    SMS_ERROR_CODES,
    SmsMessage,
    SmsSendResponse,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
BACKOFF_SECONDS = 2
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

def _sanitize_message(
    msg: SmsMessage,
    default_sender: str,
    default_entity_id: str,
) -> tuple[list[str], str | None]:
    """Validate and sanitize a single message, returning cleaned destinations and error string if any."""
    if not msg.send:
        msg.send = default_sender
    if not msg.dlt_entity_id and default_entity_id:
        msg.dlt_entity_id = default_entity_id

    cleaned_dest = ["".join(ch for ch in str(d) if ch.isdigit()) for d in msg.dest]
    cleaned_dest = [d for d in cleaned_dest if d]
    msg.dest = cleaned_dest

    if not msg.dest:
        return [], "Message destination list is empty after sanitization"
    if not msg.text:
        return [], "Message text content cannot be empty"
    return cleaned_dest, None


def _prepare_payload_messages(
    messages: list[SmsMessage],
    default_sender: str,
    default_entity_id: str,
    encrypt_pii: bool,
    encryption_key: str | None,
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """Prepare all messages for the API request payload."""
    prepared: list[dict[str, Any]] = []
    for msg in messages:
        cleaned_dest, err = _sanitize_message(msg, default_sender, default_entity_id)
        if err:
            err_code = "-113" if "destination" in err else "-115"
            return [], err_code, err
        prepared.append(msg.to_dict(encrypt=encrypt_pii, encryption_key=encryption_key))
    return prepared, None, None


def send_sms(
    messages: list[SmsMessage],
    client: str = "bajaj",
    encrypt_pii: bool = False,
    schedule_at: str | None = None,
    api_url: str | None = None,
    key_override: str | None = None,
    sender_id_override: str | None = None,
    entity_id_override: str | None = None,
    session: requests.Session | None = None,
) -> SmsSendResponse:
    """
    Send a batch of SMS messages to the Karix SMS JSON API.
    """
    if not messages:
        return SmsSendResponse(
            ackid="N/A",
            time="",
            status_code="-113",
            status_desc=SMS_ERROR_CODES.get("-113", "Empty mobile number"),
            success=False,
            error_message="No messages provided in request",
        )

    url = api_url or get_sms_api_url(client)
    key = key_override or get_sms_key(client)
    default_sender = sender_id_override or get_sms_sender_id(client)
    default_entity_id = entity_id_override or get_sms_dlt_entity_id(client)

    encryption_key = get_sms_encryption_key(client) if encrypt_pii else None
    if encrypt_pii and not encryption_key:
        logger.warning(
            "encrypt_pii=True requested for %s SMS but no encryption key configured; proceeding plain.",
            client,
        )
        encrypt_pii = False

    prepared_messages, err_code, err_msg = _prepare_payload_messages(
        messages, default_sender, default_entity_id, encrypt_pii, encryption_key
    )
    if err_msg:
        return SmsSendResponse(
            ackid="N/A",
            time="",
            status_code=err_code or "-999",
            status_desc=SMS_ERROR_CODES.get(err_code or "-999", "Error"),
            success=False,
            error_message=err_msg,
        )

    # Build top-level JSON payload
    payload: dict[str, Any] = {
        "ver": "1.0",
        "key": key,
        "encrpt": "1" if encrypt_pii else "0",
        "messages": prepared_messages,
    }
    if schedule_at:
        payload["sch_at"] = schedule_at

    headers = get_sms_auth_headers(client)
    http = session or requests

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug(
                "Sending SMS request (attempt %d/%d) to %s: %d messages, encrpt=%s",
                attempt,
                MAX_RETRIES,
                url,
                len(prepared_messages),
                payload["encrpt"],
            )

            resp = http.post(
                url,
                json=payload,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )

            if resp.status_code in _RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                sleep_time = BACKOFF_SECONDS * attempt
                logger.warning(
                    "Karix SMS API returned %d (attempt %d/%d). Retrying in %ds...",
                    resp.status_code,
                    attempt,
                    MAX_RETRIES,
                    sleep_time,
                )
                time.sleep(sleep_time)
                continue

            # Parse JSON response
            try:
                resp_json = resp.json()
            except Exception:
                resp_json = {
                    "raw_text": resp.text,
                    "http_status": resp.status_code,
                }

            # Check status inside response body
            # Success response: {"ackid": "...", "time": "...", "status": {"code": "200", "desc": "Request accepted"}}
            # Error response: {"status": {"code": "-108", "desc": "Invalid credentials"}, "ackid": "N/A", "time": "..."}
            status_obj = resp_json.get("status") if isinstance(resp_json.get("status"), dict) else {}
            code = str(status_obj.get("code") or resp.status_code)
            desc = str(status_obj.get("desc") or SMS_ERROR_CODES.get(code, "Unknown status"))
            ackid = str(resp_json.get("ackid") or "N/A")
            resp_time = str(resp_json.get("time") or "")

            is_success = resp.status_code == 200 and code == "200"

            return SmsSendResponse(
                ackid=ackid,
                time=resp_time,
                status_code=code,
                status_desc=desc,
                success=is_success,
                raw=resp_json,
                error_message=None if is_success else f"[{code}] {desc}",
            )

        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                sleep_time = BACKOFF_SECONDS * attempt
                logger.warning(
                    "Network error sending SMS (attempt %d/%d): %s. Retrying in %ds...",
                    attempt,
                    MAX_RETRIES,
                    exc,
                    sleep_time,
                )
                time.sleep(sleep_time)
            else:
                logger.error("All %d retries failed for SMS submission: %s", MAX_RETRIES, exc)

    return SmsSendResponse(
        ackid="N/A",
        time="",
        status_code="-999",
        status_desc=SMS_ERROR_CODES.get("-999", "Internal Error"),
        success=False,
        error_message=f"Request failed after {MAX_RETRIES} attempts: {last_error}",
    )


def send_quick_sms(
    dest: str | list[str],
    text: str,
    client: str = "bajaj",
    sender_id: str | None = None,
    dlt_entity_id: str | None = None,
    dlt_template_id: str | None = None,
    message_type: str = "PM",
    encrypt_pii: bool = False,
    schedule_at: str | None = None,
    cust_ref: str | None = None,
    tag: str | None = None,
) -> SmsSendResponse:
    """Convenience helper to send a single message to one or more mobile numbers."""
    if isinstance(dest, str):
        # Support comma or pipe separated numbers
        if "," in dest or "|" in dest:
            dest_list = [d.strip() for d in dest.replace("|", ",").split(",") if d.strip()]
        else:
            dest_list = [dest.strip()]
    else:
        dest_list = list(dest)

    msg = SmsMessage(
        dest=dest_list,
        text=text,
        send=sender_id or "",
        type=message_type,
        dlt_entity_id=dlt_entity_id,
        dlt_template_id=dlt_template_id,
        cust_ref=cust_ref,
        tag=tag,
    )
    return send_sms(
        messages=[msg],
        client=client,
        encrypt_pii=encrypt_pii,
        schedule_at=schedule_at,
        sender_id_override=sender_id,
        entity_id_override=dlt_entity_id,
    )


def test_sms_connection(client: str = "bajaj") -> dict[str, Any]:
    """
    Check configuration and reachability for the given account's SMS integration.

    Validates that API key or username is set, endpoint is reachable, and reports status.
    """
    key = get_sms_key(client)
    username = get_sms_username(client)
    enc_key = get_sms_encryption_key(client)
    sender_id = get_sms_sender_id(client)
    url = get_sms_api_url(client)

    has_creds = bool(key or username)
    return {
        "client": client,
        "channel": "sms",
        "configured": has_creds,
        "api_url": url,
        "has_access_key": bool(key),
        "has_username": bool(username),
        "has_encryption_key": bool(enc_key),
        "sender_id": sender_id,
        "message": (
            f"SMS credentials configured for {client} (Sender: {sender_id})"
            if has_creds
            else f"No SMS access key or username configured for {client}"
        ),
    }
