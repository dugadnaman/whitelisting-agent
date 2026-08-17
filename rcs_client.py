"""
Client for Karix Lounge RCS / DLT template registration.

Sends RcsTemplateSubmission payloads to Karix Lounge DLT registration endpoint
and returns RcsSubmissionResult.
"""

import json
import logging
import time
import requests

from rcs_config import KARIX_DLT_ACTION_URL, get_rcs_auth_headers, get_rcs_entity_id
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


def _build_dlt_payload(payload: RcsTemplateSubmission, client: str = "bajaj") -> dict:
    """
    Build the payload for Karix Lounge DLT registration.
    """
    entity_id = payload.entity_id or get_rcs_entity_id(client)
    return {
        "action": "addTemplate",
        "configurationType": "Individual",
        "entityId": entity_id,
        "templateType": payload.template_type,
        "senderId": payload.sender_ids,
        "templateName": payload.template_name,
        "templateId": payload.template_id,
        "templateMsgType": payload.template_message_type,
        "templateMsg": payload.template_message,
    }


def submit_rcs_template(payload: RcsTemplateSubmission, client: str = "bajaj") -> RcsSubmissionResult:
    """
    Submit one RCS DLT template for configuration/whitelisting on Karix Lounge.

    Retries transport-level failures with exponential backoff.
    Returns an RcsSubmissionResult regardless of outcome.
    """
    data_payload = _build_dlt_payload(payload, client=client)
    last_result: RcsSubmissionResult | None = None

    for attempt in range(MAX_RETRIES):
        exc: Exception | None = None
        resp: requests.Response | None = None

        try:
            headers = get_rcs_auth_headers(client)
            # Most Karix Lounge actions accept form-encoded or JSON POST
            resp = requests.post(
                KARIX_DLT_ACTION_URL,
                headers=headers,
                data=data_payload,
                timeout=REQUEST_TIMEOUT,
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            exc = e
            logger.warning("Attempt %d/%d transport error: %s", attempt + 1, MAX_RETRIES, e)
        except OSError as e:
            # Missing credentials
            return RcsSubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                template_id=payload.template_id,
                status=RcsSubmissionStatus.FAILED,
                error=str(e),
                retry_count=attempt,
            )

        # Transport errors (retry)
        if exc is not None:
            last_result = RcsSubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                template_id=payload.template_id,
                status=RcsSubmissionStatus.FAILED,
                error=str(exc),
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
                template_id=payload.template_id,
                status=RcsSubmissionStatus.FAILED,
                error=f"HTTP {resp.status_code}",
                provider_response=data,
                retry_count=attempt,
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_SECONDS * (2 ** attempt))
            continue

        # Non-retryable HTTP error (400, 401, 403)
        if not resp.ok:
            return RcsSubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                template_id=payload.template_id,
                status=RcsSubmissionStatus.FAILED,
                error=f"HTTP {resp.status_code}: {resp.text[:500]}",
                provider_response=data,
                retry_count=attempt,
            )

        # Check for Karix logical duplicate or failure messages
        raw_text = str(data).lower()
        if "already exists" in raw_text or "duplicate" in raw_text:
            return RcsSubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                template_id=payload.template_id,
                status=RcsSubmissionStatus.DUPLICATE,
                error="Template already exists / duplicate on Karix",
                provider_response=data,
                retry_count=attempt,
            )

        if "failed" in raw_text or "error" in raw_text:
            return RcsSubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                template_id=payload.template_id,
                status=RcsSubmissionStatus.FAILED,
                error=data.get("reason") or data.get("message") or str(data),
                provider_response=data,
                retry_count=attempt,
            )

        # Success
        return RcsSubmissionResult(
            source_ref=payload.source_ref,
            template_name=payload.template_name,
            template_id=payload.template_id,
            status=RcsSubmissionStatus.SUBMITTED,
            provider_response=data,
            retry_count=attempt,
        )

    return last_result
