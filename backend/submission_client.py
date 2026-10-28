"""
Submission client: sends one TemplateSubmission to the Karix WhatsApp
template API and returns a SubmissionResult.

This is the only file that needed a rewrite once the real API shape was
confirmed.  Everything else (loader, tracker, runner) talks to this
module through `submit_template()` / `check_status()` and doesn't care
what's inside it.

Auth model:
    Use the selected account's portal session when available, otherwise its
    official token. Never replay a creation through another transport.
"""

import collections
import copy
import io
import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict
from pathlib import Path

import requests

from config import (
    KARIX_BASE_URL,
    OFFICIAL_TEMPLATE_BASE_URL,
    _account_prefix,
    get_esmeaddr,
    get_official_auth_headers,
    get_portal_auth_headers,
    get_template_namespace_id,
    get_waba_id,
)
from cta import normalize_whatsapp_cta_buttons
from models import (
    ApprovalStatus,
    SubmissionResult,
    SubmissionStatus,
    TemplateSubmission,
)

logger = logging.getLogger(__name__)

BACKOFF_SECONDS = 1  # 1 s → 2 s → 4 s
REQUEST_TIMEOUT = 15  # seconds
MEDIA_UPLOAD_TIMEOUT = 30  # seconds — generous for Render free-tier cold starts

# All Tata Capital sub-accounts share Tata sample content (URLs, company name).
_TATA_GROUP = {"tata", "tcl_promo", "tcl_trans", "tchfl", "wealth", "moneyfy"}


def _is_tata_group(client: str) -> bool:
    """Return True for any Tata Capital sub-account (TCHFL, TCL Promo, etc.)."""
    return (client or "").lower() in _TATA_GROUP


_session: requests.Session | None = None


def get_http_session() -> requests.Session:
    """Return a shared connection-pooled HTTP session for high-throughput Karix/Meta requests."""
    global _session
    if _session is None:
        from requests.adapters import HTTPAdapter

        _session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=25,
            pool_maxsize=100,
            max_retries=0,
        )
        _session.mount("https://", adapter)
        _session.mount("http://", adapter)
    return _session





# Karix portal drops/throttles concurrent media uploads (observed: 4/18 fail at
# 10 workers). Throttle uploads globally and retry transient failures.
_MEDIA_UPLOAD_GATE = threading.Semaphore(2)
_MEDIA_UPLOAD_ATTEMPTS = 3


class KarixHealthGovernor:
    """
    Working Memory: Tracks real-time Karix API response latency and error rates
    to adaptively throttle parallel workers and inject pacing delays.
    """

    def __init__(self, window_size: int = 30):
        self._lock = threading.RLock()
        self._latencies: collections.deque[float] = collections.deque(maxlen=window_size)
        self._errors: collections.deque[int] = collections.deque(maxlen=window_size)
        self._last_429_time: float = 0.0

    def record_request(self, duration_sec: float, status_code: int = 200, is_error: bool = False) -> None:
        with self._lock:
            self._latencies.append(duration_sec)
            self._errors.append(1 if (is_error or status_code in (429, 500, 502, 503, 504)) else 0)
            if status_code == 429:
                self._last_429_time = time.time()

    def get_optimal_concurrency(self, base_workers: int = 8) -> int:
        """
        Dynamically calculate optimal worker pool size:
        - Healthy (< 1.8s avg latency, < 10% errors) -> base_workers (e.g. 8)
        - Degraded (1.8s - 4.5s avg latency or 10-25% errors) -> 4 workers
        - High Latency / Errors (> 4.5s or > 25% errors) -> 2 workers
        - Recent 429 (< 45s ago) -> 1-2 workers
        """
        with self._lock:
            if time.time() - self._last_429_time < 45:
                return max(1, min(2, base_workers))

            if not self._latencies:
                return base_workers

            avg_latency = sum(self._latencies) / len(self._latencies)
            error_rate = sum(self._errors) / len(self._errors) if self._errors else 0.0

            if avg_latency > 5.0 or error_rate >= 0.30:
                return max(1, min(2, base_workers))
            elif avg_latency > 2.5 or error_rate >= 0.15:
                return max(2, min(4, base_workers))
            elif avg_latency > 1.5:
                return max(3, min(6, base_workers))
            return base_workers

    def get_pacing_delay(self) -> float:
        """Return an optional inter-request delay in seconds based on server load."""
        with self._lock:
            if time.time() - self._last_429_time < 45:
                return 1.0  # 1s delay if recently 429 throttled
            if not self._latencies:
                return 0.0
            avg_latency = sum(self._latencies) / len(self._latencies)
            if avg_latency > 4.0:
                return 0.5
            elif avg_latency > 2.0:
                return 0.2
            return 0.0

    def get_health_stats(self) -> dict:
        """Return real-time working memory metrics."""
        with self._lock:
            avg_lat = (sum(self._latencies) / len(self._latencies)) if self._latencies else 0.8
            err_rate = (sum(self._errors) / len(self._errors)) if self._errors else 0.0
            is_throttled = (time.time() - self._last_429_time) < 45

            if is_throttled or err_rate >= 0.25 or avg_lat > 4.5:
                health_status = "throttled" if is_throttled else "degraded"
            elif avg_lat > 2.0 or err_rate > 0.05:
                health_status = "moderate"
            else:
                health_status = "optimal"

            return {
                "status": health_status,
                "avg_latency_sec": round(avg_lat, 2),
                "error_rate": round(err_rate, 2),
                "optimal_workers": self.get_optimal_concurrency(),
                "pacing_delay_sec": self.get_pacing_delay(),
                "sample_count": len(self._latencies),
            }


_GOVERNOR = KarixHealthGovernor()


def upload_media(file_path: str | None = None, file_type: str = "image/png", client: str = "bajaj") -> str:
    """
    Upload media with concurrency throttling and retries.
    See _upload_media_once for the underlying two-path upload logic.
    """
    last_err: RuntimeError | None = None
    for attempt in range(_MEDIA_UPLOAD_ATTEMPTS):
        try:
            with _MEDIA_UPLOAD_GATE:
                return _upload_media_once(file_path, file_type, client)
        except RuntimeError as e:
            last_err = e
            # Auth/config errors (missing token) will never succeed on retry
            if "Missing required" in str(e):
                raise
            if attempt < _MEDIA_UPLOAD_ATTEMPTS - 1:
                wait = BACKOFF_SECONDS * (2**attempt)
                logger.warning(
                    "Media upload attempt %d/%d failed for %s (%s): %s — retrying in %ss",
                    attempt + 1,
                    _MEDIA_UPLOAD_ATTEMPTS,
                    Path(str(file_path or "")).name or "sample",
                    client,
                    str(e)[:200],
                    wait,
                )
                time.sleep(wait)
    raise last_err  # type: ignore[misc]


def _media_handle(value: object) -> str | None:
    """Accept provider handles, not truthy objects or the string 'None'."""
    if isinstance(value, list):
        value = value[0] if len(value) == 1 else None
    if not isinstance(value, str):
        return None
    value = value.strip().split("\n")[0].strip()
    return value if re.fullmatch(r"4::[^\s]+", value) else None


def _provider_failure(data: object) -> bool:
    if not isinstance(data, dict):
        return True
    for obj in (data, data.get("response"), data.get("Success")):
        if not isinstance(obj, dict):
            continue
        if any(obj.get(key) for key in ("Failed", "error", "errors", "errorCode")):
            return True
        if obj.get("success") is False or obj.get("Success") is False or str(obj.get("status", "")).lower() in {
            "failure", "failed", "error", "false", "rejected", "unauthorized", "unauthorised", "denied",
        }:
            return True
    return False


def normalize_whatsapp_template_name(name: str) -> str:
    """Normalize template name to Meta guidelines: lowercase letters, numbers, underscores only."""
    clean = re.sub(r"[^a-zA-Z0-9_]+", "_", str(name or "").strip()).lower().strip("_")
    clean = re.sub(r"_+", "_", clean)
    return clean or "template"


def _extract_provider_error(data: object) -> str:
    """Extract human-readable error from Karix / Meta response payloads."""
    if not isinstance(data, dict):
        return "Karix rejected the template or returned an unrecognized response format."
    reason = data.get("reason")
    if isinstance(reason, dict):
        err = reason.get("error")
        if isinstance(err, dict):
            user_msg = err.get("error_user_msg")
            title = err.get("error_user_title")
            if user_msg and title:
                return f"{title}: {user_msg}"
            if user_msg:
                return str(user_msg)
            if err.get("message") and "invalid parameter" not in str(err.get("message")).lower():
                return str(err.get("message"))
        if reason.get("message"):
            return str(reason["message"])
    elif isinstance(reason, str) and reason.strip():
        return reason.strip()

    err = data.get("error")
    if isinstance(err, dict):
        user_msg = err.get("error_user_msg")
        title = err.get("error_user_title")
        if user_msg and title:
            return f"{title}: {user_msg}"
        if user_msg:
            return str(user_msg)
        if err.get("message"):
            return str(err["message"])
    elif isinstance(err, str) and err.strip():
        return err.strip()

    if data.get("Failed"):
        return str(data["Failed"])
    if data.get("errorMessage"):
        return str(data["errorMessage"])
    return "Karix rejected the template or returned a malformed response. Review its components and the selected account's template list."


def _provider_template_id(data: object) -> str | None:
    if _provider_failure(data):
        return None
    references = set()
    for obj in (data, data.get("response")):
        if not isinstance(obj, dict):
            continue
        for key in ("templateId", "template_id", "id", "fb_template_id"):
            value = obj.get(key)
            if value is None:
                continue
            if type(value) is int and value > 0:
                references.add(str(value))
            elif isinstance(value, str) and value.strip().lower() not in {
                "", "none", "null", "true", "false", "0",
            } and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value.strip()):
                references.add(value.strip())
            else:
                return None
    return references.pop() if len(references) == 1 else None


def _try_portal_media_upload(path: Path, mime: str, client: str, errors: list[str]) -> str | None:
    try:
        headers = get_portal_auth_headers(client)
        url = f"{KARIX_BASE_URL}/mediaUpload"
        waba_res = get_waba_id(client)
        esme_res = get_esmeaddr(client)
        logger.info(
            "🔒 CONFIRMATION CHECKPOINT [Media Upload]: client=%s, waba_id=%s, esmeaddr=%s, file_type=%s, auth_env_prefix=%s",
            client,
            waba_res,
            esme_res,
            mime,
            _account_prefix(client),
        )
        with open(path, "rb") as f:
            resp = get_http_session().post(
                url,
                headers=headers,
                files={"file": (path.name, f, mime)},
                data={
                    "esmeaddr": str(get_esmeaddr(client)),
                    "waba_id": str(get_waba_id(client)),
                    "file_type": mime,
                },
                timeout=MEDIA_UPLOAD_TIMEOUT,
                allow_redirects=False,
            )
        if resp.status_code in (200, 201):
            data = _parse_karix_json(resp)
            if isinstance(data, dict) and not _provider_failure(data):
                for key in ("Success", "handle", "header_handle", "fileHandle", "file_handle"):
                    handle = _media_handle(data.get(key))
                    if handle:
                        return handle
            errors.append("Portal media API returned no valid media handle")
        else:
            errors.append(f"Portal media API: HTTP {resp.status_code}")
    except OSError:
        errors.append("Portal media API credentials or local file unavailable")
    except requests.RequestException:
        errors.append("Portal media API transport failed")
    except (ValueError, TypeError):
        errors.append("Portal media API returned a malformed response")
    return None


def _try_official_media_upload(path: Path, mime: str, client: str, errors: list[str]) -> str | None:
    try:
        waba_id = get_waba_id(client)
        headers = get_official_auth_headers(client)
        url = f"{OFFICIAL_TEMPLATE_BASE_URL}/{waba_id}/media"

        with open(path, "rb") as f:
            resp = get_http_session().post(
                url,
                headers=headers,
                files={"file": (path.name, f, mime)},
                data={"file_type": mime},
                timeout=MEDIA_UPLOAD_TIMEOUT,
                allow_redirects=False,
            )
        if resp.status_code in (200, 201):
            data = _parse_karix_json(resp)
            if isinstance(data, dict) and not _provider_failure(data):
                for obj in (data, data.get("response")):
                    if not isinstance(obj, dict):
                        continue
                    for key in ("fileHandle", "file_handle", "header_handle", "handle", "Success"):
                        handle = _media_handle(obj.get(key))
                        if handle:
                            return handle
            errors.append("Official media API returned no valid media handle")
        else:
            errors.append(f"Official media API: HTTP {resp.status_code}")
    except OSError:
        errors.append("Official media API credentials or local file unavailable")
    except requests.RequestException:
        errors.append("Official media API transport failed")
    except (ValueError, TypeError):
        errors.append("Official media API returned a malformed response")
    return None


def _upload_media_once(file_path: str | None = None, file_type: str = "image/png", client: str = "bajaj") -> str:
    """
    Upload a media file to Karix/Meta using Karix's Official Template Media API:
    POST https://rcsgui.karix.solutions/api/v1.0/template/{wabaId}/media
    Uses official WABA API Token (Authentication: Bearer {token}) with multipart form upload.
    """
    if not file_path or not str(file_path).strip():
        file_path = _ensure_default_sample_image()
    path = Path(file_path)
    if not path.is_file() or path.stat().st_size == 0:
        path = Path(_ensure_default_sample_image())

    errors: list[str] = []
    mime = (
        "image/jpeg"
        if ("jpeg" in file_type or "jpg" in file_type)
        else ("video/mp4" if "video" in file_type else ("application/pdf" if "pdf" in file_type else "image/png"))
    )

    handle = _try_portal_media_upload(path, mime, client, errors)
    if handle:
        return handle

    handle = _try_official_media_upload(path, mime, client, errors)
    if handle:
        return handle

    w_id = get_waba_id(client)
    detail = "; ".join(errors) if errors else "No diagnostic info"
    logger.error("Media upload failed for %s (WABA %s): %s", client, w_id, detail)
    raise RuntimeError(f"Could not upload media creative to Karix/Meta for {client} (WABA {w_id}). Details: {detail}")


def _resolve_default_media_path(filename: str) -> Path:
    mc = Path("media_cache")
    if (mc / filename).exists():
        return mc / filename
    if Path(filename).exists():
        return Path(filename)
    if mc.is_dir():
        return mc / filename
    return Path(filename)


def _ensure_default_sample_image() -> str:
    """
    Ensure a default sample PNG image exists locally to use as a placeholder for
    IMAGE headers during template whitelisting/submission.
    """
    default_path = _resolve_default_media_path("default_sample_header.png")
    if not default_path.exists():
        import struct
        import zlib

        width, height = 200, 200
        r, g, b = 0, 102, 204  # Blue fill
        ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        raw = b""
        for _y in range(height):
            raw += b"\x00"
            for _x in range(width):
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


def _ensure_default_sample_video() -> str:
    """Ensure a default sample MP4 video exists for VIDEO headers."""
    default_path = _resolve_default_media_path("default_sample_header.mp4")
    if not default_path.exists():
        default_path.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom\x00\x00\x00\x08free")
        logger.info("Created default sample video at %s", default_path.resolve())
    return str(default_path.resolve())


def _ensure_default_sample_pdf() -> str:
    """Ensure a default sample PDF exists for DOCUMENT headers."""
    default_path = _resolve_default_media_path("default_sample_header.pdf")
    if not default_path.exists():
        pdf_content = (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 300 144]/Parent 2 0 R/Resources<<>>>>endobj\n"
            b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n0000000101 00000 n \n"
            b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n178\n%%EOF\n"
        )
        default_path.write_bytes(pdf_content)
        logger.info("Created default sample document at %s", default_path.resolve())
    return str(default_path.resolve())




def _prepare_local_media_bytes(
    cformat: str, image_bytes: bytes | None, media_file: str | None, media_url: str | None
) -> tuple[str | None, str]:
    import mimetypes
    import tempfile

    mime = {"IMAGE": "image/png", "VIDEO": "video/mp4", "DOCUMENT": "application/pdf"}[cformat]
    if image_bytes is not None:
        if not isinstance(image_bytes, bytes) or not image_bytes:
            raise ValueError("Media creative is empty or invalid. Reattach the intended file.")
        if cformat == "IMAGE" and image_bytes.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        suffix = mimetypes.guess_extension(mime) or ".bin"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(image_bytes)
            return tmp.name, mime
    if media_file:
        if not Path(media_file).is_file() or Path(media_file).stat().st_size == 0:
            raise ValueError("Media creative is missing or empty. Reattach the intended file.")
        if cformat == "IMAGE":
            with open(media_file, "rb") as stream:
                if stream.read(3) == b"\xff\xd8\xff":
                    mime = "image/jpeg"
        return media_file, mime
    if not media_url:
        if cformat == "VIDEO":
            return _ensure_default_sample_video(), mime
        if cformat == "DOCUMENT":
            return _ensure_default_sample_pdf(), mime
        return _ensure_default_sample_image(), mime
    return None, mime


def _download_remote_media(cformat: str, media_url: str) -> tuple[str, str]:
    import tempfile

    clean_url = (media_url or "").strip()
    if not clean_url.lower().startswith(("http://", "https://")):
        raise ValueError("Invalid media URL: only http:// and https:// are permitted.")
    suffix = ".mp4" if cformat == "VIDEO" else (".pdf" if cformat == "DOCUMENT" else ".png")
    media_file = None
    try:
        with requests.get(clean_url, stream=True, timeout=20) as resp:
            resp.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                media_file = tmp.name
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        tmp.write(chunk)
        return _prepare_local_media_bytes(cformat, None, media_file, None)
    except (requests.RequestException, OSError, ValueError) as exc:
        if media_file:
            Path(media_file).unlink(missing_ok=True)
        raise ValueError("Could not download media creative. Check access to the media URL or attach the file directly.") from exc


def _resolve_header_media(components: list, client: str = "bajaj") -> list:
    """
    Pre-process components before submission: for any HEADER component with
    format in (IMAGE, VIDEO, DOCUMENT), ensure a valid media handle is attached.
    """
    for comp in components:
        if not isinstance(comp, dict):
            continue
        ctype = str(comp.get("type", "")).upper()
        if ctype == "CAROUSEL":
            raise ValueError("WhatsApp carousel submission is not supported by the verified Karix contract.")
        cformat = str(comp.get("format", "")).upper()
        if ctype != "HEADER" or cformat not in ("IMAGE", "VIDEO", "DOCUMENT"):
            continue

        media_file = comp.pop("media_file", None)
        media_url = comp.pop("media_url", None)
        comp.pop("file_type", None)
        image_bytes = comp.pop("image_bytes", None)
        example = comp.get("example") or {}
        if not isinstance(example, dict):
            raise ValueError("Media header example must contain a valid uploaded media handle.")
        if example.get("header_handle"):
            handle = _media_handle(example["header_handle"])
            if not handle:
                raise ValueError("Media header has an invalid uploaded media handle. Reattach the intended creative.")
            comp["example"] = {**example, "header_handle": [handle]}
            continue

        temporary = image_bytes is not None or bool(media_url and not media_file)
        resolved_file = None
        try:
            resolved_file, file_type = _prepare_local_media_bytes(
                cformat, image_bytes, media_file, media_url
            )
            if media_url and not resolved_file:
                resolved_file, file_type = _download_remote_media(cformat, media_url)
            handle = upload_media(resolved_file, file_type, client=client)
            if not _media_handle(handle):
                raise ValueError("Media upload returned no valid handle. Reattach the intended creative.")
            comp["example"] = {**example, "header_handle": [handle]}
        finally:
            if temporary and resolved_file:
                Path(resolved_file).unlink(missing_ok=True)
    return components


def normalize_whatsapp_text_variables(text: str, client: str = "bajaj") -> tuple[str, list[str]]:
    """
    Normalize non-standard variable tags into official WhatsApp sequential variables ({{1}}, {{2}}).
    Generates realistic, Meta-approved context-aware sample values.
    """
    if not text:
        return text, []

    # 1. Normalize line endings and collapse 3+ consecutive newlines (Meta Rule: max 2)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+([.,!?:;])", r"\1", text)

    # 2. Add spacing around tight tags (e.g. "Hi<name>" -> "Hi <name>")
    text = re.sub(r"([A-Za-z0-9])(<[^>]+>)", r"\1 \2", text)
    text = re.sub(r"(<[^>]+>)([A-Za-z0-9])", r"\1 \2", text)
    text = re.sub(r"([A-Za-z0-9])(\{#[^#]+#\})", r"\1 \2", text)
    pattern = r"(\{\{\d+\}\}|\{\{[a-zA-Z0-9_]+\}\}|<[^>]+>|\{#[^#]+#\}|\[[a-zA-Z0-9_]+\]|\{[a-zA-Z0-9_]+\})"

    matches = list(re.finditer(pattern, text))
    samples = []
    company_name = "Tata Capital" if _is_tata_group(client) else "Bajaj Finance"

    last_end = 0
    seen_tags = set()
    for idx, match in enumerate(matches, 1):
        raw_tag = match.group(0)
        if raw_tag in seen_tags:
            continue
        seen_tags.add(raw_tag)
        start, end = match.span()

        next_start = matches[idx].start() if idx < len(matches) else len(text)
        before_text = text[max(last_end, start - 30) : start]
        after_text = text[end : min(next_start, end + 30)]

        line_prefix = before_text.split("\n")[-1].lower().strip()
        line_suffix = after_text.split("\n")[0].lower().strip()
        tag_clean = re.sub(r"[^a-zA-Z0-9_]", "", raw_tag).lower()
        last_end = end

        # 1. Suffix cues (e.g. {{2}} T&Cs apply). NOTE: bare "apply" is too
        #    common ("Apply now" CTA text) — require explicit T&C phrasing.
        if any(
            w in line_suffix
            for w in (
                "t&c",
                "t & c",
                "terms",
                "terms and conditions",
                "conditions apply",
                "disclaimer",
                "ltd.",
                "ltd",
            )
        ):
            samples.append(company_name)
        elif any(w in line_suffix for w in ("days", "months", "years", "hours", "mins", "minutes")):
            samples.append("30")
        elif any(w in line_suffix for w in ("%", "percent", "p.a.", "rate", "roi")):
            samples.append("9.5%")
        elif any(w in line_suffix for w in ("emi", "per month", "/month")):
            samples.append("12,500")

        # 2. Prefix cues (e.g. ₹{{1}} or Dear {{1}})
        elif any(
            w in line_prefix
            for w in (
                "₹",
                "rs.",
                "rs",
                "inr",
                "amount",
                "price",
                "worth",
                "upto",
                "up to",
                "limit",
                "loan",
                "disbursal",
                "disbursed",
                "balance",
            )
        ):
            samples.append("5,00,000")
        elif (
            any(w in line_prefix for w in ("hi", "dear", "hello", "mr", "ms", "user", "customer", "hey"))
            or "name" in tag_clean
        ):
            samples.append("John")
        elif any(w in line_prefix for w in ("from", "with", "at", "by", "team", "regards", "experience with")) or any(
            w in tag_clean for w in ("company", "brand", "org")
        ):
            samples.append(company_name)
        elif any(w in line_prefix for w in ("interest", "rate", "roi")):
            samples.append("9.5%")

        # 3. Tag content cues
        elif any(w in tag_clean for w in ("otp", "code", "pin")):
            samples.append("482910")
        elif any(w in tag_clean for w in ("date", "day", "time", "month", "year")):
            samples.append("25 August 2026")
        elif any(w in tag_clean for w in ("account", "acct", "card", "id", "num")):
            samples.append("12345678")
        else:
            samples.append("5,00,000" if idx == 1 else company_name)

    placeholders = {}

    def repl(m):
        raw_tag = m.group(0)
        if raw_tag not in placeholders:
            placeholders[raw_tag] = len(placeholders) + 1
        return f"{{{{{placeholders[raw_tag]}}}}}"

    normalized = re.sub(pattern, repl, text)
    return normalized, samples


def _resolve_body_variables(components: list, client: str = "bajaj", fix_grammar: bool = True) -> list:
    """
    Ensure BODY/HEADER variables and every URL button are properly formatted
    with example samples, optionally grammar-fixing text for Meta whitelisting.
    """
    from grammar_checker import lint_and_fix_body

    for comp in components:
        if not isinstance(comp, dict):
            continue

        ctype = str(comp.get("type") or "").upper()

        # BODY component with variables
        if ctype == "BODY":
            raw_text = comp.get("text", "")
            if fix_grammar:
                raw_text, _ = lint_and_fix_body(raw_text)
            normalized_text, auto_samples = normalize_whatsapp_text_variables(raw_text, client=client)
            comp["text"] = normalized_text

            if auto_samples:
                if not isinstance(comp.get("example"), dict):
                    comp["example"] = {}
                example = comp["example"]
                if "body_text" not in example or not example.get("body_text"):
                    example["body_text"] = [auto_samples]
                    logger.info(
                        "Auto-normalized text and generated %d body variable sample(s)",
                        len(auto_samples),
                    )

        # HEADER text component with variables
        elif ctype == "HEADER" and comp.get("format") == "TEXT":
            raw_text = comp.get("text", "")
            if fix_grammar:
                raw_text, _ = lint_and_fix_body(raw_text)
            normalized_text, auto_samples = normalize_whatsapp_text_variables(raw_text, client=client)
            comp["text"] = normalized_text
            if auto_samples:
                if not isinstance(comp.get("example"), dict):
                    comp["example"] = {}
                example = comp["example"]
                if "header_text" not in example or not example.get("header_text"):
                    example["header_text"] = [auto_samples[0]]
        elif ctype == "BUTTONS":
            normalize_whatsapp_cta_buttons(comp.get("buttons", []))

    return components


def _template_components(payload: TemplateSubmission) -> list[dict]:
    """Copy supported components without requiring portal account fields."""
    components_raw = []
    extra_footer_texts: list[str] = []
    for comp in payload.components:
        if isinstance(comp, dict):
            comp_d = copy.deepcopy(comp)
        else:
            comp_d = asdict(comp)

        comp_type = str(comp_d.get("type") or "").upper()
        if comp_type == "CAROUSEL":
            raise ValueError("WhatsApp carousel submission is not supported by the verified Karix contract.")
        # Strictly never emit a FOOTER component — merge any footer text into BODY
        if comp_type == "FOOTER":
            if comp_d.get("text"):
                extra_footer_texts.append(str(comp_d["text"]).strip())
            continue

        d: dict = {"type": comp_d.get("type")}
        if comp_d.get("format"):
            d["format"] = comp_d["format"]
        if comp_d.get("text") is not None:
            d["text"] = comp_d["text"]
        if comp_d.get("buttons"):
            d["buttons"] = comp_d["buttons"]
        if comp_d.get("example"):
            d["example"] = comp_d["example"]
        if comp_d.get("media_file"):
            d["media_file"] = comp_d["media_file"]
        if comp_d.get("media_url"):
            d["media_url"] = comp_d["media_url"]
        if comp_d.get("image_bytes") is not None:
            d["image_bytes"] = comp_d["image_bytes"]
        if comp_d.get("file_type"):
            d["file_type"] = comp_d["file_type"]
        components_raw.append(d)

    if extra_footer_texts:
        for d in components_raw:
            if str(d.get("type") or "").upper() == "BODY":
                body_txt = str(d.get("text") or "").strip()
                for ft in extra_footer_texts:
                    if ft and ft.lower() not in body_txt.lower():
                        body_txt = f"{body_txt}\n\n{ft}".strip()
                d["text"] = body_txt
                break
    return components_raw


def _build_portal_create_body(payload: TemplateSubmission, client: str = "bajaj") -> dict:
    """Build the verified portal multipart request."""
    return {
        "requestType": "createTemplate",
        "esmeaddr": get_esmeaddr(client),
        "waba_id": get_waba_id(client),
        "allow_category_change": True,
        "allow_marketing_recategorization": True,
        "sessionId": "12345",  # literal hardcoded placeholder from real traffic
        "template_name": normalize_whatsapp_template_name(payload.template_name),
        "template_namespace_id": get_template_namespace_id(client),
        "language": payload.language,
        "category": payload.category,
        "components": _template_components(payload),
    }


def _is_duplicate_or_exists_error(err: object) -> bool:
    """Check if an error string/dict from Karix or Meta indicates the template already exists."""
    if not err:
        return False
    s = str(err).lower()
    if "already exist" in s:  # matches "Template Already Exist.", "already exists", "already existed"
        return True
    if "there is already" in s and "content for this template" in s:  # Meta duplicate content
        return True
    if "template with this name" in s and "already exists" in s:
        return True
    if "duplicate template" in s:
        return True
    if "2388042" in s or "2388043" in s:  # Meta API error subcodes for duplicate template
        return True
    return False


def _resolve_existing_template_result(
    payload: TemplateSubmission,
    client: str,
    attempt: int,
    err_msg: object,
    provider_resp: dict,
) -> SubmissionResult:
    """Resolve duplicates only from this account's matching live inventory."""
    reference = None
    approval = ApprovalStatus.UNKNOWN
    try:
        rows, inventory_error = fetch_template_list(client)
        if not inventory_error:
            expected_waba = get_waba_id(client)
            expected_esme = get_esmeaddr(client)
            for row in rows:
                if not isinstance(row, dict) or str(row.get("template_name", "")).lower() != payload.template_name.lower():
                    continue
                if row.get("language") and row["language"] != payload.language:
                    continue
                if any(row.get(key) is not None and str(row[key]) != str(expected_waba) for key in ("wabaId", "waba_id")):
                    continue
                if row.get("esmeaddr") is not None and str(row["esmeaddr"]) not in ("0", str(expected_esme)):
                    continue
                reference = _provider_template_id(row)
                if reference:
                    approval = _STATUS_MAP.get(str(row.get("template_create_status", "")).upper(), ApprovalStatus.UNKNOWN)
                    break
    except (requests.RequestException, OSError, ValueError, TypeError):
        pass
    return SubmissionResult(
        source_ref=payload.source_ref,
        template_name=payload.template_name,
        status=SubmissionStatus.DUPLICATE,
        provider_ref_id=reference,
        error="Template already exists; verified its live provider record." if reference else "Template already exists. Refresh the selected account's template list to inspect its provider ID and approval status.",
        provider_response=provider_resp,
        approval_status=approval,
        client=client,
        channel="whatsapp",
        retry_count=attempt,
    )


def _evaluate_portal_create_response(
    resp: requests.Response, data: object, payload: TemplateSubmission, c: str, attempt: int
) -> SubmissionResult:
    template_id = None
    if resp.status_code in (401, 403):
        error = (
            f"Karix credentials refused (HTTP {resp.status_code}). Open Settings → {c}; "
            "reconnect Karix Auth Sync after mobile OTP login for portal sessions, "
            "or update this account's Official WABA API Token."
        )
    elif resp.status_code in (400, 409) and isinstance(data, dict) and _is_duplicate_or_exists_error(data):
        return _resolve_existing_template_result(payload, c, attempt, data, data)
    elif resp.status_code not in (200, 201):
        error = f"Karix creation returned HTTP {resp.status_code}. Check the template list before trying again."
    elif isinstance(data, dict) and _is_duplicate_or_exists_error(data):
        return _resolve_existing_template_result(payload, c, attempt, data, data)
    elif _provider_failure(data):
        if any(marker in str(data).lower() for marker in ("uploaded media handle is invalid", "check the handle provided", "2494102")):
            error = "Karix rejected the media handle for this account. Reattach the original creative and verify the selected account's Karix session; no replacement media was submitted."
        else:
            error = _extract_provider_error(data)
    else:
        template_id = _provider_template_id(data)
        if not template_id and isinstance(data, dict):
            status_text = str(data.get("status", "")).lower()
            reason_text = str(data.get("reason", "")).lower()
            if status_text == "success" or "successfully" in reason_text or "created" in reason_text:
                try:
                    rows, _ = fetch_template_list(c)
                    target_name = normalize_whatsapp_template_name(payload.template_name)
                    for r in rows:
                        if str(r.get("template_name", "")).lower().strip() == target_name:
                            template_id = str(r.get("fb_template_id") or r.get("sno") or "")
                            break
                except Exception:
                    pass
                if template_id:
                    error = None
                else:
                    error = "No valid provider template ID returned. Check the template list before trying again."
            else:
                error = "No valid provider template ID returned. Check the template list before trying again."
        else:
            error = None if template_id else "No valid provider template ID returned. Check the template list before trying again."
    return SubmissionResult(
        source_ref=payload.source_ref,
        template_name=payload.template_name,
        status=SubmissionStatus.SUBMITTED if template_id else SubmissionStatus.FAILED,
        provider_ref_id=template_id,
        error=error,
        provider_response=data if isinstance(data, dict) else {},
        approval_status=ApprovalStatus.PENDING if template_id else ApprovalStatus.UNKNOWN,
        client=c,
        channel="whatsapp",
        retry_count=attempt,
    )


def _failed_submission(payload: TemplateSubmission, client: str, error: str) -> SubmissionResult:
    return SubmissionResult(
        source_ref=payload.source_ref,
        template_name=payload.template_name,
        status=SubmissionStatus.FAILED,
        error=error,
        approval_status=ApprovalStatus.UNKNOWN,
        client=client,
        channel="whatsapp",
    )




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


def _submit_portal_template(
    payload: TemplateSubmission, client: str = "bajaj",
    fix_grammar: bool = True,
) -> SubmissionResult:
    """Issue exactly one create; a lost response must never replay a side effect."""
    c = (client or payload.client or "bajaj").lower().strip()
    try:
        headers = get_portal_auth_headers(c)
        body = _build_portal_create_body(payload, client=c)
        body["components"] = _resolve_header_media(body["components"], client=c)
        body["components"] = _resolve_body_variables(body["components"], client=c, fix_grammar=fix_grammar)
    except (OSError, RuntimeError, ValueError) as exc:
        return _failed_submission(payload, c, f"Template/media preparation failed: {exc}")
    try:
        t0 = time.time()
        resp = get_http_session().post(
            f"{KARIX_BASE_URL}/create", headers=headers,
            files={"request": (None, json.dumps(body), "application/json")},
            timeout=REQUEST_TIMEOUT, allow_redirects=False,
        )
        _GOVERNOR.record_request(time.time() - t0, status_code=resp.status_code)
    except requests.RequestException:
        _GOVERNOR.record_request(REQUEST_TIMEOUT, status_code=500, is_error=True)
        return _failed_submission(payload, c, "Karix creation response was not received. Check the template list before trying again; the request was not replayed.")
    return _evaluate_portal_create_response(resp, _parse_karix_json(resp), payload, c, 0)




def _build_official_create_body(
    payload: TemplateSubmission,
    client: str = "bajaj",
    fix_grammar: bool = True,
) -> dict:
    """
    Build the documented JSON body for POST /api/v1.0/template/{wabaId}.

    Portal-only account fields and the literal sessionId are deliberately absent.
    """
    components = _template_components(payload)
    components = _resolve_header_media(components, client=client)
    components = _resolve_body_variables(components, client=client, fix_grammar=fix_grammar)

    return {
        "template_name": normalize_whatsapp_template_name(payload.template_name),
        "language": payload.language,
        "category": payload.category,
        "components": components,
    }


def _submit_official_template(
    payload: TemplateSubmission,
    client: str = "bajaj",
    fix_grammar: bool = True,
) -> SubmissionResult:
    """Submit to the selected account through the official Karix API once."""
    c = (client or payload.client or "bajaj").lower().strip()
    try:
        waba_id = get_waba_id(c)
        headers = get_official_auth_headers(c)
        headers["Content-Type"] = "application/json"
        body = _build_official_create_body(payload, client=c, fix_grammar=fix_grammar)
    except (OSError, RuntimeError, ValueError) as exc:
        return _failed_submission(payload, c, f"Template/media preparation failed: {exc}")
    try:
        t0 = time.time()
        response = get_http_session().post(
            f"{OFFICIAL_TEMPLATE_BASE_URL}/{waba_id}", headers=headers, json=body,
            timeout=REQUEST_TIMEOUT, allow_redirects=False,
        )
        _GOVERNOR.record_request(time.time() - t0, status_code=response.status_code)
    except requests.RequestException:
        _GOVERNOR.record_request(REQUEST_TIMEOUT, status_code=500, is_error=True)
        return _failed_submission(payload, c, "Karix creation response was not received. Check the template list before trying again; the request was not replayed.")
    return _evaluate_portal_create_response(response, _parse_karix_json(response), payload, c, 0)


def submit_template(
    payload: TemplateSubmission,
    client: str = "bajaj",
    fix_grammar: bool = True,
    validate_ai: bool = False,
) -> SubmissionResult:
    """
    Submit one template to Karix and return the result.
    If portal session credentials exist, uses Portal API.
    If official WABA static token exists, uses Official API.
    """
    c = (client or getattr(payload, "client", None) or "bajaj").lower()

    # Optional TypeSafe AI Pre-Flight Gate
    if validate_ai:
        try:
            from template_validator import validate_template_semantic_quality

            body_text = ""
            for comp in payload.components:
                if isinstance(comp, dict) and comp.get("type") == "BODY":
                    body_text = str(comp.get("text", ""))
                    break
                elif getattr(comp, "type", None) == "BODY":
                    body_text = str(getattr(comp, "text", "") or "")
                    break

            if body_text:
                ai_rep = validate_template_semantic_quality(
                    body_text=body_text,
                    declared_category=payload.category,
                    client=c,
                    allow_ai=True,
                )
                if ai_rep.ai_checked and not ai_rep.is_safe_to_submit:
                    critical_errors = [w["issue"] for w in ai_rep.warnings if w.get("severity") == "error"]
                    if critical_errors:
                        logger.warning(
                            "Blocking submission of WhatsApp template '%s' due to TypeSafe AI semantic error: %s",
                            payload.template_name,
                            critical_errors,
                        )
                        return SubmissionResult(
                            source_ref=payload.source_ref,
                            template_name=payload.template_name,
                            status=SubmissionStatus.FAILED,
                            approval_status=ApprovalStatus.REJECTED,
                            error=f"BLOCKED (AI Pre-Submission Compliance): {'; '.join(critical_errors)}",
                            client=c,
                            channel="whatsapp",
                        )
        except Exception as ex:
            logger.debug("AI pre-flight inspection bypassed due to exception: %s", ex)
    # Select a transport before side effects. Never retry/fall back after create.
    try:
        selected_waba = str(get_waba_id(c))
        if payload.client.lower().strip() != c:
            raise ValueError("Template client does not match the selected account.")
        if payload.waba_id and str(payload.waba_id) != selected_waba:
            raise ValueError("Template WABA does not match the selected account.")
        try:
            get_portal_auth_headers(c)
        except OSError:
            return _submit_official_template(
                payload, client=c, fix_grammar=fix_grammar,
            )
        return _submit_portal_template(
            payload, client=c, fix_grammar=fix_grammar,
        )
    except (OSError, ValueError) as exc:
        return _failed_submission(payload, c, str(exc))


def _parse_karix_json(resp) -> dict | list:
    """Parse a Karix response body as JSON. Karix serves JSON with text/plain content-type."""
    try:
        return resp.json()
    except Exception:
        pass
    try:
        import json as _json

        return _json.loads(resp.text)
    except Exception:
        return {}


def check_portal_credentials(
    client: str,
    *,
    bearer_token: str | None = None,
    session_id: str | None = None,
    portal_user: str | None = None,
    waba_id: str | None = None,
    esmeaddr: str | None = None,
) -> tuple[bool, str]:
    """Validate the exact portal credentials without saving or falling back to WABA auth."""
    try:
        headers = get_portal_auth_headers(
            client, bearer_token=bearer_token, session_id=session_id, portal_user=portal_user,
        )
        headers["Content-Type"] = "application/json"
        response = get_http_session().post(
            f"{KARIX_BASE_URL}/getAllTemplates",
            headers=headers,
            json={"wabaId": waba_id or get_waba_id(client), "esmeaddr": esmeaddr or get_esmeaddr(client), "start": 0, "limit": 1},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )
        if response.status_code in (401, 403):
            return False, f"Portal session refused (HTTP {response.status_code}). Reconnect this account through Karix Auth Sync after mobile OTP login."
        if response.status_code != 200:
            return False, f"Portal connection returned HTTP {response.status_code}."
        data = _parse_karix_json(response)
        # Provider signatures authorize the request; reject any contradictory returned identity.
        expected_waba = str(waba_id or get_waba_id(client))
        expected_esme = str(esmeaddr or get_esmeaddr(client))
        inventories = []
        identities = []
        if isinstance(data, list):
            inventories.append(data)
        elif isinstance(data, dict):
            identities.append(data)
            failure_data = {key: value for key, value in data.items() if key != "Failed"} if data.get("Failed") == "No Records Found" else data
            if _provider_failure(failure_data):
                return False, "Portal rejected the credentials. Reconnect this account through Karix Auth Sync."
            for envelope in (data, data.get("Success"), data.get("response")):
                if isinstance(envelope, dict):
                    identities.append(envelope)
                    if isinstance(envelope.get("templates"), list):
                        inventories.append(envelope["templates"])
                elif isinstance(envelope, list):
                    inventories.append(envelope)
        for rows in inventories:
            if not all(isinstance(row, dict) for row in rows):
                return False, "Portal validation returned malformed template inventory."
            identities.extend(rows)
        for row in identities:
            observed_waba = row.get("wabaId") if row.get("wabaId") is not None else row.get("waba_id")
            observed_esme = row.get("esmeaddr")
            if observed_waba is not None and str(observed_waba) != expected_waba:
                return False, "Portal returned another configured account's WABA inventory."
            if observed_esme is not None and str(observed_esme) not in ("0", expected_esme):
                return False, "Portal returned another configured account's ESME inventory."
        if inventories or (isinstance(data, dict) and data.get("Failed") == "No Records Found"):
            return True, "Portal credentials valid."
        return False, "Portal validation returned an unrecognized response; credentials could not be verified."
    except requests.RequestException as exc:
        return False, f"Portal connection failed ({type(exc).__name__}). Check network access and try again."
    except OSError as exc:
        return False, str(exc)


def fetch_template_list(client: str = "bajaj") -> tuple[list[dict], str | None]:
    """
    Fetch the full template list for a client's WABA (supports Portal API and Official API).
    Returns (templates_list, error_str_if_any).
    """
    c = (client or "bajaj").lower().strip()
    errors: list[str] = []
    # 1. Primary: Portal API getAllTemplates with pagination
    try:
        waba_id = get_waba_id(c)
        esmeaddr = get_esmeaddr(c)
        headers = get_portal_auth_headers(c)
        headers["Content-Type"] = "application/json"
        url = f"{KARIX_BASE_URL}/getAllTemplates"
        body = {"wabaId": str(waba_id), "esmeaddr": str(esmeaddr), "start": 0, "limit": 2500}
        resp = get_http_session().post(url, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
        if resp.ok:
            data = _parse_karix_json(resp)
            if isinstance(data, list):
                return data, None
            if isinstance(data, dict):
                if data.get("Failed") == "No Records Found":
                    return [], None
                templates = (
                    data.get("Success", {}).get("templates")
                    or data.get("response", {}).get("templates")
                    or data.get("templates")
                    or []
                )
                if templates or "Success" in data or "response" in data:
                    return templates, None
            errors.append("Portal API returned an unrecognized response")
        else:
            errors.append(f"Portal API returned HTTP {resp.status_code}")
    except Exception as exc:
        errors.append(f"Portal API: {exc}")
        logger.debug("Portal fetch_template_list notice for %s: %s", c, exc)

    # 2. Official API Fallback
    try:
        waba_id = get_waba_id(c)
        url = f"{OFFICIAL_TEMPLATE_BASE_URL}/{waba_id}"
        response = get_http_session().get(
            url,
            headers=get_official_auth_headers(c),
            timeout=REQUEST_TIMEOUT,
        )
        if response.ok:
            data = _parse_karix_json(response)
            if isinstance(data, list):
                return data, None
            if isinstance(data, dict):
                templates = data.get("response", {}).get("templates") or data.get("templates") or []
                return templates, None
            errors.append("Official API returned an unrecognized response")
        else:
            errors.append(f"Official API returned HTTP {response.status_code}")
    except Exception as exc:
        errors.append(f"Official API: {exc}")
        logger.debug("Official fetch_template_list notice for %s: %s", c, exc)

    return [], "; ".join(errors) if errors else None


def _match_template(templates: list[dict], provider_ref_id: str) -> dict | None:
    """Match a provider ref against fb_template_id, sno, or template name (case-insensitive)."""
    if not provider_ref_id:
        return None
    pref = str(provider_ref_id).strip().lower()
    return next(
        (
            t
            for t in templates
            if str(t.get("fb_template_id", "")).strip().lower() == pref
            or str(t.get("sno", "")).strip().lower() == pref
            or str(t.get("template_name", "")).strip().lower() == pref
        ),
        None,
    )


def check_status(provider_ref_id: str, client: str = "bajaj") -> tuple[ApprovalStatus, str | None, dict]:
    """
    Read the latest approval status from the official Karix template list.

    Transient failures return (UNKNOWN, reason, {"_transport_error": True}) so
    the poller can leave the entry pollable instead of permanently marking it
    unknown (the old behavior silently locked templates out of future polls).
    """
    templates, err = fetch_template_list(client)
    if err is not None:
        return ApprovalStatus.UNKNOWN, err, {"_transport_error": True}

    matched = _match_template(templates, provider_ref_id)
    if matched is None:
        logger.warning(
            "check_status: no template found matching provider_ref_id=%r (%d templates on WABA)",
            provider_ref_id,
            len(templates),
        )
        return (
            ApprovalStatus.UNKNOWN,
            f"Template {provider_ref_id} not found in response",
            {"_not_found": True},
        )

    raw_status = str(matched.get("template_create_status", "")).upper()
    return (
        _STATUS_MAP.get(raw_status, ApprovalStatus.UNKNOWN),
        matched.get("template_status_reason"),
        matched,
    )


# ---------------------------------------------------------------------------
# Template Deletion
# ---------------------------------------------------------------------------


def delete_template(template_name: str, client: str = "bajaj") -> dict:
    """
    Delete a single WhatsApp template by name.

    Per Karix docs: DELETE /api/v1.0/template/{wabaId}/{templateId}
    with Authentication: Bearer {token}.

    Looks up the template by name in the live list to get fb_template_id,
    then issues the DELETE. Falls back to portal API POST /v1.0/templates/delete.

    Returns {"ok": True/False, "template_name": ..., "detail": ...}.
    """
    c = (client or "bajaj").lower().strip()
    name = template_name.strip()

    # Step 1: Look up template ID from live list
    templates, fetch_err = fetch_template_list(c)
    template_id = None
    if not fetch_err and templates:
        for t in templates:
            if t.get("template_name") == name:
                template_id = str(t.get("fb_template_id") or t.get("sno", "")).strip()
                break

    # Step 2: Official API — DELETE /api/v1.0/template/{wabaId}/{templateId}
    if template_id:
        try:
            waba_id = get_waba_id(c)
            headers = get_official_auth_headers(c)
            url = f"{OFFICIAL_TEMPLATE_BASE_URL}/{waba_id}/{template_id}"
            resp = get_http_session().delete(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.ok:
                logger.info("Deleted template '%s' (id=%s) via official API (client=%s)", name, template_id, c)
                return {
                    "ok": True,
                    "template_name": name,
                    "template_id": template_id,
                    "detail": "Deleted via official API",
                }
            if resp.status_code == 400:
                body = _parse_karix_json(resp)
                detail = str(body) if body else resp.text[:500]
                if "not exist" in detail.lower() or "not found" in detail.lower():
                    return {"ok": True, "template_name": name, "detail": "Template not found (already deleted)"}
            logger.debug(
                "Official DELETE returned %d for '%s' (id=%s): %s", resp.status_code, name, template_id, resp.text[:300]
            )
        except Exception as exc:
            logger.debug("Official DELETE failed for '%s' (id=%s): %s", name, template_id, exc)
    elif not fetch_err:
        # Template name not found in live list — already deleted or never existed
        return {"ok": True, "template_name": name, "detail": "Template not found on WABA (already deleted)"}

    # Step 3: Portal API fallback — POST /v1.0/templates/delete
    try:
        waba_id = get_waba_id(c)
        esmeaddr = get_esmeaddr(c)
        headers = get_portal_auth_headers(c)
        headers["Content-Type"] = "application/json"
        url = f"{KARIX_BASE_URL}/delete"
        body = {
            "waba_id": str(waba_id),
            "esmeaddr": str(esmeaddr),
            "template_name": name,
        }
        resp = get_http_session().post(url, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
        if resp.ok:
            logger.info("Deleted template '%s' via portal API (client=%s)", name, c)
            return {"ok": True, "template_name": name, "detail": "Deleted via portal API"}
        detail = resp.text[:500]
        if "not exist" in detail.lower() or "not found" in detail.lower():
            return {"ok": True, "template_name": name, "detail": "Template not found (already deleted)"}
        logger.warning("Portal DELETE returned %d for '%s': %s", resp.status_code, name, detail)
        return {"ok": False, "template_name": name, "detail": f"Portal API HTTP {resp.status_code}: {detail}"}
    except Exception as exc:
        logger.warning("Portal DELETE failed for '%s': %s", name, exc)
        return {"ok": False, "template_name": name, "detail": str(exc)}


def delete_templates_bulk(
    template_names: list[str] | None = None,
    client: str = "bajaj",
    delete_all: bool = False,
) -> dict:
    """
    Bulk-delete templates by name list, or all templates on the WABA.

    Fetches the live template list once, resolves fb_template_id for each name,
    then issues DELETE /api/v1.0/template/{wabaId}/{templateId} per template.

    If delete_all=True, deletes every template on the WABA.
    Returns {"deleted": [...], "failed": [...], "total": N}.
    """
    c = (client or "bajaj").lower().strip()

    # Fetch template list once for ID resolution
    templates, fetch_err = fetch_template_list(c)
    if fetch_err:
        return {"deleted": [], "failed": [], "total": 0, "error": fetch_err}

    # Build name→id lookup
    name_to_id: dict[str, str] = {}
    for t in templates:
        tname = t.get("template_name", "")
        tid = str(t.get("fb_template_id") or t.get("sno", "")).strip()
        if tname and tid:
            name_to_id[tname] = tid

    if delete_all:
        template_names = list(name_to_id.keys())
        logger.info("Bulk delete ALL: found %d templates on WABA for client=%s", len(template_names), c)
    elif not template_names:
        return {"deleted": [], "failed": [], "total": 0, "error": "No template names provided"}

    waba_id = get_waba_id(c)
    headers = get_official_auth_headers(c)
    deleted = []
    failed = []

    for name in template_names:
        tid = name_to_id.get(name)
        if not tid:
            deleted.append({"ok": True, "template_name": name, "detail": "Not found on WABA (already deleted)"})
            continue

        try:
            url = f"{OFFICIAL_TEMPLATE_BASE_URL}/{waba_id}/{tid}"
            resp = get_http_session().delete(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.ok:
                logger.info("Deleted '%s' (id=%s) client=%s", name, tid, c)
                deleted.append({"ok": True, "template_name": name, "template_id": tid, "detail": "Deleted"})
            else:
                detail = resp.text[:500]
                if "not exist" in detail.lower() or "not found" in detail.lower():
                    deleted.append({"ok": True, "template_name": name, "detail": "Already deleted"})
                else:
                    failed.append(
                        {
                            "ok": False,
                            "template_name": name,
                            "template_id": tid,
                            "detail": f"HTTP {resp.status_code}: {detail}",
                        }
                    )
                    logger.warning("DELETE failed for '%s' (id=%s): HTTP %d", name, tid, resp.status_code)
        except Exception as exc:
            failed.append({"ok": False, "template_name": name, "template_id": tid, "detail": str(exc)})
            logger.warning("DELETE exception for '%s' (id=%s): %s", name, tid, exc)

        time.sleep(0.3)  # rate-limit guard

    logger.info(
        "Bulk delete complete for client=%s: %d deleted, %d failed out of %d",
        c,
        len(deleted),
        len(failed),
        len(template_names),
    )
    return {"deleted": deleted, "failed": failed, "total": len(template_names)}
