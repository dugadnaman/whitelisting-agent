"""
Submission client: sends one TemplateSubmission to the Karix WhatsApp
template API and returns a SubmissionResult.

This is the only file that needed a rewrite once the real API shape was
confirmed.  Everything else (loader, tracker, runner) talks to this
module through `submit_template()` / `check_status()` and doesn't care
what's inside it.

Auth model:
    Text-only templates use Karix's official static-token API. Media-header
    templates temporarily retain the portal path because the official collection
    does not document a media-handle upload endpoint, and the portal upload
    endpoint rejects the static official token.
"""

import copy
import json
import logging
import re
import time
from pathlib import Path
from urllib.request import urlretrieve

import requests

from config import (
    BAJAJ_ESMEADDR,
    BAJAJ_TEMPLATE_NAMESPACE_ID,
    BAJAJ_WABA_ID,
    KARIX_BASE_URL,
    OFFICIAL_TEMPLATE_BASE_URL,
    get_esmeaddr,
    get_official_auth_headers,
    get_portal_auth_headers,
    get_template_namespace_id,
    get_waba_id,
)
from models import (
    ApprovalStatus,
    SubmissionResult,
    SubmissionStatus,
    TemplateSubmission,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------
MAX_RETRIES = 3
BACKOFF_SECONDS = 2  # doubles each retry: 2 s → 4 s → 8 s
REQUEST_TIMEOUT = 30  # seconds
MEDIA_UPLOAD_TIMEOUT = 120  # seconds — images can be large

# HTTP status codes worth retrying (transport-level, not validation errors)
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_retryable(exc: Exception | None, response: requests.Response | None) -> bool:
    """Return True only for transport-level failures we should retry."""
    if exc is not None:
        # Connection error, timeout, etc. — always retry
        return True
    return bool(response is not None and response.status_code in _RETRYABLE_STATUS_CODES)


def upload_media(file_path: str, file_type: str = "image/jpeg", client: str = "bajaj") -> str:
    """
    Upload a media file to Karix for use as a template HEADER image.

    This is the first step of the two-step image-header flow:
      1. POST /mediaUpload → returns a header_handle string
      2. POST /create with the handle in components[].example.header_handle
    """
    url = f"{KARIX_BASE_URL}/mediaUpload"
    headers = get_portal_auth_headers(client)
    # Don't set Content-Type — requests sets multipart boundary automatically

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Media file not found: {file_path}")

    with open(path, "rb") as f:
        resp = requests.post(
            url,
            headers=headers,
            files={"file": (path.name, f, file_type)},
            data={
                "esmeaddr": get_esmeaddr(client),
                "waba_id": get_waba_id(client),
                "template_namespace_id": get_template_namespace_id(client),
                "file_type": file_type,
            },
            timeout=MEDIA_UPLOAD_TIMEOUT,
        )

    if not resp.ok:
        raise RuntimeError(f"Media upload failed: HTTP {resp.status_code}: {resp.text[:500]}")

    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError(f"Media upload returned invalid JSON: {resp.text[:500]}")

    handle_str = data.get("Success")
    if not handle_str:
        raise RuntimeError(f"Media upload response missing 'Success' key: {data}")

    # Response contains multiple handles separated by newlines; use the first one
    first_handle = handle_str.strip().split("\n")[0].strip()
    logger.info("Media uploaded: handle=%s...", first_handle[:60])
    return first_handle

def _ensure_default_sample_image() -> str:
    """
    Ensure a default sample PNG image exists locally to use as a placeholder for
    IMAGE headers during template whitelisting/submission.
    """
    default_path = Path("default_sample_header.png")
    if not default_path.exists():
        import struct
        import zlib
        width, height = 200, 200
        r, g, b = 0, 102, 204  # Blue fill
        ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        raw = b""
        for y in range(height):
            raw += b"\x00"
            for x in range(width):
                raw += bytes([r, g, b])
        compressed = zlib.compress(raw)

        def chunk(chunk_type, data):
            c = chunk_type + data
            crc = zlib.crc32(c) & 0xFFFFFFFF
            return struct.pack(">I", len(data)) + c + struct.pack(">I", crc)

        with open(default_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            f.write(chunk(b"IHDR", ihdr_data))
            f.write(chunk(b"IDAT", compressed))
            f.write(chunk(b"IEND", b""))
        logger.info("Created default sample image at %s", default_path.resolve())

    return str(default_path.resolve())


def _resolve_header_media(components: list, client: str = "bajaj") -> list:
    """
    Pre-process components before submission: for any HEADER component with
    format=IMAGE, ensure a valid media handle is attached.
    """
    for comp in components:
        if not isinstance(comp, dict):
            continue
        if comp.get("type") != "HEADER" or comp.get("format") != "IMAGE":
            continue

        # Already has a handle — skip
        example = comp.get("example", {})
        if example.get("header_handle") and example["header_handle"] != []:
            continue

        media_file = comp.pop("media_file", None)
        media_url = comp.pop("media_url", None)
        file_type = comp.pop("file_type", None) or "image/png"
        image_bytes = comp.pop("image_bytes", None)

        # If in-memory image_bytes provided (from .xlsx)
        if image_bytes:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(image_bytes)
                media_file = tmp.name
            file_type = "image/png"

        # Fallback to default sample image if no custom image specified
        if not media_file and not media_url:
            logger.info(
                "HEADER IMAGE has no custom media_file/media_url; using default sample image for whitelisting."
            )
            media_file = _ensure_default_sample_image()
            file_type = "image/png"
        # Download from URL if needed
        if media_url and not media_file:
            import tempfile

            suffix = Path(media_url.split("?")[0]).suffix or ".jpg"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                media_file = tmp.name

            logger.info("Downloading header image from %s", media_url)
            urlretrieve(media_url, media_file)

        # Upload and fill in the handle
        handle = upload_media(media_file, file_type, client=client)
        comp["example"] = {"header_handle": [handle]}
        logger.info("Header image uploaded for template (%s), handle set.", client)

    return components

def normalize_whatsapp_text_variables(text: str, client: str = "bajaj") -> tuple[str, list[str]]:
    """
    Normalize non-standard variable tags into official WhatsApp sequential variables ({{1}}, {{2}}).
    Generates realistic, Meta-approved context-aware sample values.
    """
    if not text:
        return text, []

    # 1. Normalize line endings and collapse 3+ consecutive newlines (Meta Rule: max 2)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+([.,!?:;])', r'\1', text)

    # 2. Add spacing around tight tags (e.g. "Hi<name>" -> "Hi <name>")
    text = re.sub(r'([A-Za-z0-9])(<[^>]+>)', r'\1 \2', text)
    text = re.sub(r'(<[^>]+>)([A-Za-z0-9])', r'\1 \2', text)
    text = re.sub(r'([A-Za-z0-9])(\{#[^#]+#\})', r'\1 \2', text)
    pattern = r'(\{\{\d+\}\}|\{\{[a-zA-Z0-9_]+\}\}|<[^>]+>|\{#[^#]+#\}|\[[a-zA-Z0-9_]+\]|\{[a-zA-Z0-9_]+\})'

    matches = list(re.finditer(pattern, text))
    samples = []
    is_tata = (client or "bajaj").lower() == "tata"
    company_name = "Tata Capital" if is_tata else "Bajaj Markets"

    for idx, match in enumerate(matches, 1):
        raw_tag = match.group(0)
        start, end = match.span()

        before_text = text[max(0, start - 30):start]
        after_text = text[end:min(len(text), end + 30)]

        line_prefix = before_text.split('\n')[-1].lower().strip()
        line_suffix = after_text.split('\n')[0].lower().strip()
        tag_clean = re.sub(r'[^a-zA-Z0-9_]', '', raw_tag).lower()

        # 1. Suffix cues (e.g. {{2}} T&Cs apply)
        if any(w in line_suffix for w in ('t&c', 'terms', 'apply', 'condition', 'disclaimer', 'ltd')):
            samples.append(company_name)
        elif any(w in line_suffix for w in ('days', 'months', 'years', 'hours', 'mins', 'minutes')):
            samples.append("30")
        elif any(w in line_suffix for w in ('%', 'percent', 'p.a.', 'rate')):
            samples.append("9.5%")
        elif any(w in line_suffix for w in ('emi', 'per month', '/month')):
            samples.append("12,500")

        # 2. Prefix cues (e.g. ₹{{1}} or Dear {{1}})
        elif any(w in line_prefix for w in ('₹', 'rs.', 'rs', 'inr', 'amount', 'price', 'worth', 'upto', 'up to', 'loan', 'limit', 'of')):
            samples.append("5,00,000")
        elif any(w in line_prefix for w in ('hi', 'dear', 'hello', 'mr', 'ms', 'user', 'customer', 'hey')) or 'name' in tag_clean:
            samples.append("John")
        elif any(w in line_prefix for w in ('interest', 'rate', 'roi')):
            samples.append("9.5%")

        # 3. Tag content cues
        elif any(w in tag_clean for w in ('otp', 'code', 'pin')):
            samples.append("482910")
        elif any(w in tag_clean for w in ('date', 'day', 'time', 'month', 'year')):
            samples.append("25 August 2026")
        elif any(w in tag_clean for w in ('account', 'acct', 'card', 'id', 'num')):
            samples.append("12345678")
        else:
            samples.append("5,00,000" if idx == 1 else company_name)

    placeholders = []
    def repl(m):
        idx = len(placeholders) + 1
        placeholders.append(m.group(0))
        return f"{{{{{idx}}}}}"

    normalized = re.sub(pattern, repl, text)
    return normalized, samples


def _resolve_body_variables(components: list, client: str = "bajaj") -> list:
    """
    Ensure any BODY or BUTTON component containing variables ({{1}}, {{2}}, <name>, etc.)
    is properly formatted and has example samples populated for Meta whitelisting.
    """
    for comp in components:
        if not isinstance(comp, dict):
            continue

        ctype = comp.get("type")

        # BODY component with variables
        if ctype == "BODY":
            raw_text = comp.get("text", "")
            normalized_text, auto_samples = normalize_whatsapp_text_variables(raw_text, client=client)
            comp["text"] = normalized_text

            if auto_samples:
                example = comp.setdefault("example", {})
                if "body_text" not in example or not example["body_text"]:
                    example["body_text"] = [auto_samples]
                    logger.info("Auto-normalized text and generated %d body variable sample(s)", len(auto_samples))

        # HEADER text component with variables
        elif ctype == "HEADER" and comp.get("format") == "TEXT":
            raw_text = comp.get("text", "")
            normalized_text, auto_samples = normalize_whatsapp_text_variables(raw_text, client=client)
            comp["text"] = normalized_text
            if auto_samples:
                example = comp.setdefault("example", {})
                if "header_text" not in example or not example["header_text"]:
                    example["header_text"] = [auto_samples[0]]

        # BUTTONS component with URL variables
        elif ctype == "BUTTONS":
            btns = comp.get("buttons", [])
            for b in btns:
                if isinstance(b, dict) and b.get("type") == "URL":
                    url = b.get("url", "")
                    if "{{1}}" in url or "{{0}}" in url or "<" in url:
                        if not b.get("example") or not b["example"]:
                            b["example"] = ["https://www.tatacapital.com/personal-loan.html" if client.lower() == "tata" else "https://www.bajajfinservmarkets.in/"]
                            logger.info("Auto-generated URL variable sample for button")
                    else:
                        # Meta Rule: static URL buttons MUST NOT have 'example' parameter
                        b.pop("example", None)

    return components


def _build_portal_create_body(payload: TemplateSubmission, client: str = "bajaj") -> dict:
    """
    Build the legacy portal create body used only for media headers.
    """
    components_raw = []
    for comp in payload.components:
        if isinstance(comp, dict):
            components_raw.append(copy.deepcopy(comp))
        else:
            d: dict = {"type": comp.type}
            if getattr(comp, "format", None) is not None:
                d["format"] = comp.format
            if getattr(comp, "text", None) is not None:
                d["text"] = comp.text
            if getattr(comp, "variables", None) is not None:
                d["variables"] = comp.variables
            if getattr(comp, "buttons", None) is not None:
                d["buttons"] = comp.buttons
            if getattr(comp, "example", None) is not None:
                d["example"] = comp.example
            if getattr(comp, "media_url", None) is not None:
                d["media_url"] = comp.media_url
            if getattr(comp, "media_file", None) is not None:
                d["media_file"] = comp.media_file
            components_raw.append(d)

    return {
        "requestType": "createTemplate",
        "esmeaddr": get_esmeaddr(client),
        "waba_id": get_waba_id(client),
        "allow_category_change": True,
        "allow_marketing_recategorization": True,
        "sessionId": "12345",  # literal hardcoded placeholder from real traffic
        "template_name": payload.template_name,
        "template_namespace_id": get_template_namespace_id(client),
        "language": payload.language,
        "category": payload.category,
        "components": components_raw,
    }

# Status mapping
# ---------------------------------------------------------------------------

_STATUS_MAP = {
    "PENDING": ApprovalStatus.PENDING,
    "APPROVED": ApprovalStatus.APPROVED,
    "REJECTED": ApprovalStatus.REJECTED,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _submit_portal_template(payload: TemplateSubmission, client: str = "bajaj") -> SubmissionResult:
    """
    Submit one template with media headers via the portal API.
    """
    c = (client or getattr(payload, "client", None) or "bajaj").lower()
    url = f"{KARIX_BASE_URL}/create"
    body = _build_portal_create_body(payload, client=c)

    # Pre-process: upload media for HEADER IMAGE components and auto-fill variable samples
    try:
        body["components"] = _resolve_header_media(body["components"], client=c)
        body["components"] = _resolve_body_variables(body["components"])
    except (OSError, RuntimeError, FileNotFoundError) as e:
        logger.error("Media upload failed for %s (%s): %s", payload.template_name, c, e)
        return SubmissionResult(
            source_ref=payload.source_ref,
            template_name=payload.template_name,
            status=SubmissionStatus.FAILED,
            error=f"Media upload failed: {e}",
            approval_status=ApprovalStatus.UNKNOWN,
        )

    last_result: SubmissionResult | None = None

    for attempt in range(MAX_RETRIES):
        exc: Exception | None = None
        resp: requests.Response | None = None

        try:
            headers = get_portal_auth_headers(c)
            # CRITICAL: The /create endpoint expects multipart/form-data with
            # the JSON payload in a field called "request" — NOT a raw JSON
            # body.  Sending application/json returns 400 Bad Request with no
            # useful error message.  Confirmed via browser DevTools traffic.
            # requests auto-sets Content-Type to multipart/form-data when
            # using files=, so we must NOT include Content-Type in headers.
            resp = requests.post(
                url,
                headers=headers,
                files={"request": (None, json.dumps(body), "application/json")},
                timeout=REQUEST_TIMEOUT,
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            exc = e
            logger.warning("Attempt %d/%d transport error: %s", attempt + 1, MAX_RETRIES, e)
        except OSError as e:
            # Missing credentials — no point retrying
            return SubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                status=SubmissionStatus.FAILED,
                error=str(e),
                approval_status=ApprovalStatus.UNKNOWN,
                retry_count=attempt,
            )

        # ---- Handle transport errors (retry) ----
        if exc is not None:
            last_result = SubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                status=SubmissionStatus.FAILED,
                error=str(exc),
                approval_status=ApprovalStatus.UNKNOWN,
                retry_count=attempt,
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_SECONDS * (2 ** attempt))
            continue

        # ---- We got a response — parse it ----
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
            last_result = SubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                status=SubmissionStatus.FAILED,
                error=f"HTTP {resp.status_code}",
                provider_response=data,
                approval_status=ApprovalStatus.UNKNOWN,
                retry_count=attempt,
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_SECONDS * (2 ** attempt))
            continue

        # Non-retryable error (400, 401, 403, etc.)
        if not resp.ok:
            return SubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                status=SubmissionStatus.FAILED,
                error=f"HTTP {resp.status_code}: {resp.text[:500]}",
                provider_response=data,
                approval_status=ApprovalStatus.UNKNOWN,
                retry_count=attempt,
            )

        # 200 but Karix may still signal a logical failure
        # Check for {"Failed": "..."} or {"status": "failure"/"error"}
        if "Failed" in data:
            return SubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                status=SubmissionStatus.FAILED,
                error=data["Failed"],
                provider_response=data,
                approval_status=ApprovalStatus.UNKNOWN,
                client=c,
                channel="whatsapp",
                retry_count=attempt,
            )

        resp_status = str(data.get("status", "")).lower()
        if resp_status in ("failure", "error", "failed"):
            return SubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                status=SubmissionStatus.FAILED,
                error=data.get("reason", str(data)),
                provider_response=data,
                approval_status=ApprovalStatus.UNKNOWN,
                client=c,
                channel="whatsapp",
                retry_count=attempt,
            )

        # Success
        provider_ref = payload.template_name
        return SubmissionResult(
            source_ref=payload.source_ref,
            template_name=payload.template_name,
            status=SubmissionStatus.SUBMITTED,
            provider_ref_id=provider_ref,
            provider_response=data,
            approval_status=ApprovalStatus.PENDING,
            client=c,
            channel="whatsapp",
            retry_count=attempt,
        )
    # All retries exhausted
    return last_result


def _requires_portal_media(payload: TemplateSubmission) -> bool:
    """Return whether the template needs an unverified official media handle."""
    for component in payload.components:
        ctype = component.get("type") if isinstance(component, dict) else getattr(component, "type", "")
        cformat = component.get("format") if isinstance(component, dict) else getattr(component, "format", "")
        if str(ctype).upper() == "HEADER" and str(cformat).upper() in {"IMAGE", "DOCUMENT", "VIDEO"}:
            return True
    return False


def _build_official_create_body(payload: TemplateSubmission, client: str = "bajaj") -> dict:
    """
    Build the documented JSON body for POST /api/v1.0/template/{wabaId}.

    Portal-only account fields and the literal sessionId are deliberately absent.
    """
    components = copy.deepcopy(_build_portal_create_body(payload, client=client)["components"])
    components = _resolve_body_variables(components, client=client)

    # For official API: clean up any empty or unsupported header components
    cleaned_components = []
    for comp in components:
        ctype = comp.get("type")
        if ctype == "HEADER":
            cformat = str(comp.get("format", "")).upper()
            if cformat in ("IMAGE", "DOCUMENT", "VIDEO"):
                example = comp.get("example")
                if not example or not isinstance(example, dict) or not example.get("header_handle"):
                    logger.warning(
                        "Omitting media HEADER %s for %s because no media handle was provided",
                        cformat, payload.template_name
                    )
                    continue
        cleaned_components.append(comp)

    return {
        "template_name": payload.template_name,
        "language": payload.language,
        "category": payload.category,
        "components": cleaned_components,
    }
def _submit_official_template(payload: TemplateSubmission, client: str = "bajaj") -> SubmissionResult:
    """Submit a text-only template through the verified official Karix API."""
    c = (client or getattr(payload, "client", None) or "bajaj").lower()
    try:
        waba_id = (payload.waba_id if getattr(payload, "waba_id", None) and payload.waba_id not in ("", BAJAJ_WABA_ID) and c == "tata" else None) or get_waba_id(c)
        headers = get_official_auth_headers(c)
    except OSError as exc:
        return SubmissionResult(
            source_ref=payload.source_ref,
            template_name=payload.template_name,
            status=SubmissionStatus.FAILED,
            error=str(exc),
            approval_status=ApprovalStatus.UNKNOWN,
            client=c,
            channel="whatsapp",
            retry_count=0,
        )

    url = f"{OFFICIAL_TEMPLATE_BASE_URL}/{waba_id}"
    body = _build_official_create_body(payload, client=c)
    last_result: SubmissionResult | None = None

    for attempt in range(MAX_RETRIES):
        try:
            headers = get_official_auth_headers(c)
            headers["Content-Type"] = "application/json"
            response = requests.post(url, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_result = SubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                status=SubmissionStatus.FAILED,
                error=f"Transport error: {exc}",
                approval_status=ApprovalStatus.UNKNOWN,
                client=c,
                channel="whatsapp",
                retry_count=attempt,
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_SECONDS * (2 ** attempt))
            continue
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            data = {"_raw_text": response.text}

        if response.status_code in _RETRYABLE_STATUS_CODES:
            err_detail = f"HTTP {response.status_code}"
            if response.text and response.text.strip():
                err_detail = f"HTTP {response.status_code}: {response.text[:300].strip()}"
            last_result = SubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                status=SubmissionStatus.FAILED,
                error=err_detail,
                provider_response=data,
                approval_status=ApprovalStatus.UNKNOWN,
                client=c,
                channel="whatsapp",
                retry_count=attempt,
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_SECONDS * (2 ** attempt))
            continue

        if response.status_code != 201:
            return SubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                status=SubmissionStatus.FAILED,
                error=f"HTTP {response.status_code}: {response.text[:500]}",
                provider_response=data,
                approval_status=ApprovalStatus.UNKNOWN,
                client=c,
                channel="whatsapp",
                retry_count=attempt,
            )

        template_id = str(data.get("templateId", "")).strip()
        if not template_id:
            return SubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                status=SubmissionStatus.FAILED,
                error="Official create response missing templateId",
                provider_response=data,
                approval_status=ApprovalStatus.UNKNOWN,
                client=c,
                channel="whatsapp",
                retry_count=attempt,
            )

        return SubmissionResult(
            source_ref=payload.source_ref,
            template_name=payload.template_name,
            status=SubmissionStatus.SUBMITTED,
            provider_ref_id=template_id,
            provider_response=data,
            approval_status=ApprovalStatus.PENDING,
            client=c,
            channel="whatsapp",
            retry_count=attempt,
        )

    return last_result


def submit_template(payload: TemplateSubmission, client: str | None = None) -> SubmissionResult:
    """
    Submit a template for whitelisting.

    All Tata Capital submissions and text-only Bajaj templates use the official
    API. Legacy Bajaj portal media templates use the portal session endpoint.
    """
    c = (client or getattr(payload, "client", None) or "bajaj").lower()
    if c == "bajaj" and _requires_portal_media(payload):
        return _submit_portal_template(payload, client=c)
    return _submit_official_template(payload, client=c)

def check_status(provider_ref_id: str, client: str = "bajaj") -> tuple[ApprovalStatus, str | None, dict]:
    """
    Read the latest approval status from the official Karix template list for the given client.

    Official create returns `templateId`, which is exposed as `fb_template_id`
    by the list endpoint. Existing portal entries remain pollable because the
    same list also exposes their serial number and template name.
    """
    try:
        waba_id = get_waba_id(client)
        url = f"{OFFICIAL_TEMPLATE_BASE_URL}/{waba_id}"
        response = requests.get(
            url,
            headers=get_official_auth_headers(client),
            timeout=REQUEST_TIMEOUT,
        )
    except OSError as exc:
        # Missing WABA ID / token or transport error — never propagate to the caller.
        logger.error("check_status credential/transport error: %s", exc)
        return ApprovalStatus.UNKNOWN, str(exc), {}
    except (requests.ConnectionError, requests.Timeout) as exc:
        logger.error("Transport error in check_status: %s", exc)
        return ApprovalStatus.UNKNOWN, f"Transport error: {exc}", {}

    if not response.ok:
        logger.error("Official check_status HTTP %d: %s", response.status_code, response.text[:300])
        return ApprovalStatus.UNKNOWN, f"HTTP {response.status_code}", {"_raw_text": response.text}

    try:
        data = response.json()
    except (json.JSONDecodeError, ValueError):
        return ApprovalStatus.UNKNOWN, "Invalid JSON response", {"_raw_text": response.text}

    templates = data.get("response", {}).get("templates", [])
    matched = next(
        (
            template
            for template in templates
            if str(template.get("fb_template_id", "")) == provider_ref_id
            or str(template.get("sno", "")) == provider_ref_id
            or template.get("template_name") == provider_ref_id
        ),
        None,
    )
    if matched is None:
        logger.warning(
            "Official check_status: no template found matching provider_ref_id=%r (%d templates)",
            provider_ref_id,
            len(templates),
        )
        return ApprovalStatus.UNKNOWN, f"Template {provider_ref_id} not found in response", data

    raw_status = str(matched.get("template_create_status", "")).upper()
    return _STATUS_MAP.get(raw_status, ApprovalStatus.UNKNOWN), matched.get("template_status_reason"), matched
