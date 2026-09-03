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
from urllib.request import urlretrieve

import requests

from config import (
    BAJAJ_WABA_ID,
    KARIX_BASE_URL,
    OFFICIAL_TEMPLATE_BASE_URL,
    _account_prefix,
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

MAX_RETRIES = 3
BACKOFF_SECONDS = 1  # 1 s → 2 s → 4 s
REQUEST_TIMEOUT = 15  # seconds
MEDIA_UPLOAD_TIMEOUT = 30  # seconds — generous for Render free-tier cold starts

# HTTP status codes worth retrying (transport-level, not validation errors)
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
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
        from urllib3.util import Retry

        _session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            pool_connections=25,
            pool_maxsize=100,
            max_retries=retry_strategy,
        )
        _session.mount("https://", adapter)
        _session.mount("http://", adapter)
    return _session


def _is_retryable(exc: Exception | None, response: requests.Response | None) -> bool:
    """Return True only for transport-level failures we should retry."""
    if exc is not None:
        # Connection error, timeout, etc. — always retry
        return True
    return bool(response is not None and response.status_code in _RETRYABLE_STATUS_CODES)


FALLBACK_PLACEHOLDER_IMAGE_HANDLE = "4::aW1hZ2UvcG5n:ARbniR2Mjs3AjmbXj_PT2co-Htm_UrVCspAqcYZ374tOY9ynPsS1fHzg3GhFomqWBiQjj6eUUZ3pNEkRraYDm90jI4H8yj21diMGmjLjCg0_zg:e:1787385539:379138877290302:100066839164237:ARYkaBy8mnS0GiuXUz0"
FALLBACK_PLACEHOLDER_VIDEO_HANDLE = "4::dmlkZW8vbXA0:ARZtyVaCTL6vxhfjdYm26r3hB7nQ5zecCIxRCNIAtbBpeHODRi8Q4OwMLv_BeADs92ugK330J5mHHEBEHZskpiUSKDPonPEFm6fj6__WL_KDFw:e:1787465291:204883164914271:100066839164237:ARYZ_1MJHg5wBQY8JPA"
FALLBACK_PLACEHOLDER_DOCUMENT_HANDLE = "4::YXBwbGljYXRpb24vcGRm:ARagUnYcCe-_Jwa2bxH7KdPu3w9f-CMLaBRiHDj67GJ_71h7lWlu1kP0SujG4rIolI8cKNOzvm0q73cl7iIjykI0VY64qGMHRsWPRW1_QMEHXg:e:1787465292:379138877290302:100066839164237:ARabH-vpch9ACwHceRc"
FALLBACK_PLACEHOLDER_HEADER_HANDLE = FALLBACK_PLACEHOLDER_IMAGE_HANDLE

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


def _try_portal_media_upload(path: Path, mime: str, client: str, errors: list[str]) -> str | None:
    try:
        headers = get_portal_auth_headers(client)
        url = f"{KARIX_BASE_URL}/mediaUpload"
        waba_res = get_waba_id(client)
        esme_res = get_esmeaddr(client)
        logger.info(
            "🔒 CONFIRMATION CHECKPOINT [Media Upload]: client=%s, waba_id=%s, esmeaddr=%s, file_type=%s, credential_source=%s_KARIX_BEARER_TOKEN",
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
            )
        if resp.ok:
            data = resp.json()
            handle_str = data.get("Success") or data.get("handle") or data.get("header_handle")
            if handle_str:
                first_handle = handle_str.strip().split("\n")[0].strip()
                if first_handle.startswith("4::"):
                    logger.info(
                        "Media uploaded via Karix portal for %s: handle=%s...",
                        client,
                        first_handle[:60],
                    )
                    return first_handle
            errors.append(f"Portal API: HTTP {resp.status_code} OK but no valid handle in response: {str(data)[:300]}")
        else:
            errors.append(f"Portal API: HTTP {resp.status_code}: {resp.text[:300]}")
    except OSError as e:
        errors.append(f"Portal API: {e}")
    except Exception as e:
        errors.append(f"Portal API: {type(e).__name__}: {e}")
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
            )
        if resp.ok:
            data = _parse_karix_json(resp)
            h = None
            if isinstance(data, dict):
                if data.get("header_handle"):
                    val = data["header_handle"]
                    h = val[0] if isinstance(val, list) else str(val)
                elif data.get("Success"):
                    h = data["Success"].strip().split("\n")[0].strip()
                elif data.get("handle"):
                    h = data["handle"]
                elif data.get("response") and isinstance(data["response"], dict):
                    resp_obj = data["response"]
                    h = resp_obj.get("header_handle") or resp_obj.get("handle") or resp_obj.get("Success")
                    if isinstance(h, list):
                        h = h[0]
            if h and str(h).startswith("4::"):
                logger.info(
                    "Media uploaded via Karix Official API (%s): handle=%s...",
                    client,
                    str(h)[:60],
                )
                return str(h)
            errors.append(f"Official API: HTTP {resp.status_code} OK but no valid handle in response: {str(data)[:300]}")
        else:
            errors.append(f"Official API: HTTP {resp.status_code}: {resp.text[:300]}")
    except OSError as e:
        errors.append(f"Official API: {e}")
    except Exception as e:
        errors.append(f"Official API: {type(e).__name__}: {e}")
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
    if not path.exists():
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
    raise RuntimeError(
        f"Could not upload media creative to Karix/Meta for {client} (WABA {w_id}). "
        f"Details: {detail}"
    )


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
    default_path = Path("default_sample_header.mp4")
    if not default_path.exists():
        import base64

        # Valid minimal MP4 container
        minimal_mp4_b64 = "AAAAHGZ0eXBpc29tAAAAAGlzb21pc28yYXZjMW1wNDEAAAAIZnJlZQAAAAhtZGF0AAAAIG1vb3YAAABsbXZoZAAAAABAAAAAAAEAAAEAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAA=="
        try:
            default_path.write_bytes(base64.b64decode(minimal_mp4_b64))
        except Exception:
            default_path.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom\x00\x00\x00\x08free")
        logger.info("Created default sample video at %s", default_path.resolve())
    return str(default_path.resolve())


def _ensure_default_sample_pdf() -> str:
    """Ensure a default sample PDF exists for DOCUMENT headers."""
    default_path = Path("default_sample_header.pdf")
    if not default_path.exists():
        pdf_content = (
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 300 144]/Parent 2 0 R/Resources<<>>>>endobj\n"
            b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n0000000101 00000 n \n"
            b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n178\n%%EOF\n"
        )
        default_path.write_bytes(pdf_content)
        logger.info("Created default sample document at %s", default_path.resolve())


def normalize_image_16_9(
    input_path_or_bytes: str | bytes | None,
    target_width: int = 1280,
    target_height: int = 720,
) -> tuple[str, str]:
    """
    Ensure any image conforms to Meta's required 16:9 aspect ratio (1280x720).
    If the image is square (1:1), portrait (9:16), or has non-standard dimensions,
    it is fitted cleanly onto a 16:9 canvas with matching neutral background padding
    so NO text, logo, or critical branding is cropped out by Meta.
    Returns (normalized_file_path, mime_type).
    """
    if not input_path_or_bytes:
        return _ensure_default_sample_image(), "image/png"
    import tempfile

    try:
        from PIL import Image

        if isinstance(input_path_or_bytes, bytes):
            img = Image.open(io.BytesIO(input_path_or_bytes))
        else:
            img = Image.open(str(input_path_or_bytes))
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        w, h = img.size
        current_ratio = w / h
        target_ratio = target_width / target_height

        # Sample corner pixel to blend background naturally
        edge_color = (255, 255, 255)
        try:
            corner = img.getpixel((0, 0))
            if isinstance(corner, tuple) and len(corner) >= 3:
                edge_color = corner[:3]
        except Exception:
            pass

        # If already approximately 16:9 (within 5% tolerance)
        if abs(current_ratio - target_ratio) < 0.05:
            if w > 1920:
                img.thumbnail((1920, 1080), Image.Resampling.LANCZOS)
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                img.save(tmp, format="JPEG", quality=92, optimize=True)
                return tmp.name, "image/jpeg"

        # Fit inside 16:9 canvas (1280x720) without cropping or stretching
        canvas = Image.new("RGB", (target_width, target_height), edge_color)
        img_fit = img.copy()
        img_fit.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)

        offset_x = (target_width - img_fit.width) // 2
        offset_y = (target_height - img_fit.height) // 2
        canvas.paste(img_fit, (offset_x, offset_y))

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            canvas.save(tmp, format="JPEG", quality=92, optimize=True)
            logger.info(
                "Image normalized from %dx%d (ratio %.2f) to 16:9 (1280x720) for Meta compliance.",
                w,
                h,
                current_ratio,
            )
            return tmp.name, "image/jpeg"
    except Exception as exc:
        logger.warning("Image 16:9 normalization skipped: %s", exc)
        if isinstance(input_path_or_bytes, bytes):
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(input_path_or_bytes)
                return tmp.name, "image/png"
        return str(input_path_or_bytes), "image/png"


def _prepare_local_media_bytes(
    cformat: str, image_bytes: bytes | None, media_file: str | None, media_url: str | None, fix_aspect_ratio: bool
) -> tuple[str | None, str]:
    import tempfile

    if cformat == "IMAGE":
        if fix_aspect_ratio:
            if image_bytes:
                return normalize_image_16_9(image_bytes)
            elif media_file:
                return normalize_image_16_9(media_file)
            elif not media_url:
                return _ensure_default_sample_image(), "image/png"
        else:
            if image_bytes:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp.write(image_bytes)
                    return tmp.name, "image/png"
            elif not media_file and not media_url:
                return _ensure_default_sample_image(), "image/png"
        return media_file, "image/png"
    elif cformat == "VIDEO":
        if image_bytes:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                tmp.write(image_bytes)
                return tmp.name, "video/mp4"
        if not media_file and not media_url:
            return _ensure_default_sample_video(), "video/mp4"
        return media_file, "video/mp4"
    elif cformat == "DOCUMENT":
        if image_bytes:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(image_bytes)
                return tmp.name, "application/pdf"
        if not media_file and not media_url:
            return _ensure_default_sample_pdf(), "application/pdf"
        return media_file, "application/pdf"
    return media_file, "application/octet-stream"


def _download_remote_media(cformat: str, media_url: str) -> tuple[str, str]:
    import tempfile

    suffix = Path(media_url.split("?")[0]).suffix if media_url else ""
    if not suffix:
        suffix = ".mp4" if cformat == "VIDEO" else (".pdf" if cformat == "DOCUMENT" else ".png")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        media_file = tmp.name
    file_type = "video/mp4" if cformat == "VIDEO" else ("application/pdf" if cformat == "DOCUMENT" else "image/png")

    logger.info("Downloading header %s from %s", cformat.lower(), media_url)
    try:
        urlretrieve(media_url, media_file)
        if cformat == "IMAGE":
            media_file, file_type = normalize_image_16_9(media_file)
    except Exception as e:
        logger.warning("Could not download media_url %s: %s; using default sample", media_url, e)
        if cformat == "VIDEO":
            media_file = _ensure_default_sample_video()
        elif cformat == "DOCUMENT":
            media_file = _ensure_default_sample_pdf()
        else:
            media_file = _ensure_default_sample_image()
    return media_file, file_type


def _resolve_header_media(components: list, client: str = "bajaj", fix_aspect_ratio: bool = True) -> list:
    """
    Pre-process components before submission: for any HEADER component with
    format in (IMAGE, VIDEO, DOCUMENT), ensure a valid media handle is attached.
    """
    for comp in components:
        if not isinstance(comp, dict):
            continue
        ctype = comp.get("type")
        cformat = str(comp.get("format", "")).upper()
        if ctype != "HEADER" or cformat not in ("IMAGE", "VIDEO", "DOCUMENT"):
            continue

        example = comp.get("example", {})
        if example.get("header_handle") and example["header_handle"] != []:
            continue

        media_file = comp.pop("media_file", None)
        media_url = comp.pop("media_url", None)
        file_type = comp.pop("file_type", None)
        image_bytes = comp.pop("image_bytes", None)

        media_file, file_type = _prepare_local_media_bytes(
            cformat, image_bytes, media_file, media_url, fix_aspect_ratio
        )

        if media_url and not media_file:
            media_file, file_type = _download_remote_media(cformat, media_url)

        if not media_file or not os.path.exists(str(media_file)):
            if cformat == "VIDEO":
                media_file, file_type = _ensure_default_sample_video(), "video/mp4"
            elif cformat == "DOCUMENT":
                media_file, file_type = _ensure_default_sample_pdf(), "application/pdf"
            else:
                media_file, file_type = _ensure_default_sample_image(), "image/png"

        # Cache media to persistent public directory and generate public URL
        import hashlib

        MEDIA_CACHE_DIR = Path("media_cache")
        MEDIA_CACHE_DIR.mkdir(exist_ok=True)
        public_url = None
        try:
            raw_bytes = Path(media_file).read_bytes()
            media_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]
            ext = ".jpg" if "jpeg" in file_type else (".png" if "png" in file_type else (".mp4" if cformat == "VIDEO" else ".pdf"))
            cache_file = MEDIA_CACHE_DIR / f"{media_hash}{ext}"
            cache_file.write_bytes(raw_bytes)
            public_base = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("PUBLIC_APP_URL") or "https://whitelisting-agent.onrender.com"
            public_url = f"{public_base}/api/media/{media_hash}{ext}"
        except Exception as e:
            logger.debug("Media caching notice: %s", e)

        handle = upload_media(media_file, file_type, client=client)
        if handle:
            comp["example"] = {"header_handle": [handle]}
        elif public_url:
            comp["example"] = {"header_url": [public_url]}

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
    is_tata = _is_tata_group(client)
    company_name = "Tata Capital" if is_tata else "Bajaj Markets"

    for idx, match in enumerate(matches, 1):
        raw_tag = match.group(0)
        start, end = match.span()

        before_text = text[max(0, start - 30) : start]
        after_text = text[end : min(len(text), end + 30)]

        line_prefix = before_text.split("\n")[-1].lower().strip()
        line_suffix = after_text.split("\n")[0].lower().strip()
        tag_clean = re.sub(r"[^a-zA-Z0-9_]", "", raw_tag).lower()

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
            )
        ):
            samples.append(company_name)
        elif any(w in line_suffix for w in ("days", "months", "years", "hours", "mins", "minutes")):
            samples.append("30")
        elif any(w in line_suffix for w in ("%", "percent", "p.a.", "rate")):
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
                "loan",
                "limit",
                "of",
            )
        ):
            samples.append("5,00,000")
        elif (
            any(w in line_prefix for w in ("hi", "dear", "hello", "mr", "ms", "user", "customer", "hey"))
            or "name" in tag_clean
        ):
            samples.append("John")
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

    placeholders = []

    def repl(m):
        idx = len(placeholders) + 1
        placeholders.append(m.group(0))
        return f"{{{{{idx}}}}}"

    normalized = re.sub(pattern, repl, text)
    return normalized, samples


def _resolve_body_variables(components: list, client: str = "bajaj", fix_grammar: bool = True) -> list:
    """
    Ensure any BODY or BUTTON component containing variables ({{1}}, {{2}}, <name>, etc.)
    is properly formatted, optionally grammar-fixed, and has example samples populated for Meta whitelisting.
    """
    from grammar_checker import lint_and_fix_body

    for comp in components:
        if not isinstance(comp, dict):
            continue

        ctype = comp.get("type")

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
            _resolve_button_cta_variables(comp.get("buttons", []), client)

    return components


def _resolve_button_cta_variables(btns: list, client: str) -> None:
    for b in btns:
        if isinstance(b, dict) and b.get("type") == "URL":
            url = b.get("url", "")
            # Force every CTA to dynamic: append /{{1}} if no variable present
            if "{{1}}" not in url and "{{0}}" not in url and "<" not in url:
                url = url.rstrip("/") + "/{{1}}"
                b["url"] = url
                logger.info("Forced static CTA to dynamic: %s", url)
            # Always ensure a sample example for the dynamic variable
            if not b.get("example") or not b["example"]:
                b["example"] = [
                    "https://www.tatacapital.com/personal-loan.html"
                    if _is_tata_group(client)
                    else "https://www.bajajfinservmarkets.in/"
                ]
                logger.info("Auto-generated URL variable sample for button")



def _build_portal_create_body(payload: TemplateSubmission, client: str = "bajaj") -> dict:
    """
    Build the legacy portal create body used only for media headers.
    """
    components_raw = []
    for comp in payload.components:
        if isinstance(comp, dict):
            comp_d = copy.deepcopy(comp)
        else:
            comp_d = asdict(comp)

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
        if comp_d.get("image_bytes"):
            d["image_bytes"] = comp_d["image_bytes"]
        if comp_d.get("file_type"):
            d["file_type"] = comp_d["file_type"]
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
def _evaluate_portal_create_response(
    resp: requests.Response, data: dict, payload: TemplateSubmission, c: str, attempt: int
) -> SubmissionResult:
    if resp.status_code == 401:
        return SubmissionResult(
            source_ref=payload.source_ref,
            template_name=payload.template_name,
            status=SubmissionStatus.FAILED,
            error=(
                "Session expired (401). Open Settings → "
                f"{c} and paste fresh Portal Bearer Token / Session ID from "
                "the Karix portal (DevTools → Network headers)."
            ),
            provider_response=data,
            approval_status=ApprovalStatus.UNKNOWN,
            client=c,
            channel="whatsapp",
            retry_count=attempt,
        )

    if not resp.ok:
        return SubmissionResult(
            source_ref=payload.source_ref,
            template_name=payload.template_name,
            status=SubmissionStatus.FAILED,
            error=f"HTTP {resp.status_code}: {resp.text[:2000]}",
            provider_response=data,
            approval_status=ApprovalStatus.UNKNOWN,
            client=c,
            channel="whatsapp",
            retry_count=attempt,
        )

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
        reason_data = data.get("reason", {})
        reason_str = str(reason_data)
        recovered = _handle_portal_media_auto_recovery(payload, c, reason_str)
        if recovered is not None:
            return recovered
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

    return SubmissionResult(
        source_ref=payload.source_ref,
        template_name=payload.template_name,
        status=SubmissionStatus.SUBMITTED,
        provider_ref_id=payload.template_name,
        provider_response=data,
        approval_status=ApprovalStatus.PENDING,
        client=c,
        channel="whatsapp",
        retry_count=attempt,
    )


def _handle_portal_media_auto_recovery(payload: TemplateSubmission, c: str, reason_str: str) -> SubmissionResult | None:
    is_handle_err = (
        "Uploaded media handle is invalid" in reason_str
        or "Check the handle provided" in reason_str
        or "2494102" in reason_str
    )
    if not is_handle_err or getattr(payload, "_tried_media_reupload", False):
        return None

    logger.warning(
        "Media handle invalid on WABA %s for %s (%s). Re-uploading media with fresh credentials...",
        get_waba_id(c),
        payload.template_name,
        c,
    )
    payload._tried_media_reupload = True

    new_comps = []
    for comp in payload.components:
        comp_d = asdict(comp) if not isinstance(comp, dict) else dict(comp)
        if comp_d.get("type") == "HEADER" and comp_d.get("format", "").upper() in ("IMAGE", "VIDEO", "DOCUMENT"):
            comp_d.pop("example", None)
            if not comp_d.get("media_file") and not comp_d.get("media_url") and not comp_d.get("image_bytes"):
                fmt = comp_d.get("format", "IMAGE").upper()
                if fmt == "VIDEO":
                    comp_d["media_file"] = _ensure_default_sample_video()
                elif fmt == "DOCUMENT":
                    comp_d["media_file"] = _ensure_default_sample_pdf()
                else:
                    comp_d["media_file"] = _ensure_default_sample_image()
        new_comps.append(comp_d)

    payload.components = new_comps
    return _submit_portal_template(payload, client=c)




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

        for comp in body.get("components", []):
            if isinstance(comp, dict):
                comp.pop("media_file", None)
                comp.pop("image_bytes", None)
                comp.pop("file_type", None)
                comp.pop("variables", None)
    except (OSError, RuntimeError, FileNotFoundError) as e:
        logger.error("Media upload failed for %s (%s): %s", payload.template_name, c, e)
        return SubmissionResult(
            source_ref=payload.source_ref,
            template_name=payload.template_name,
            status=SubmissionStatus.FAILED,
            error=f"Media upload failed: {e}",
            approval_status=ApprovalStatus.UNKNOWN,
            client=c,
            channel="whatsapp",
        )
    last_result: SubmissionResult | None = None
    for attempt in range(MAX_RETRIES):
        exc: Exception | None = None
        resp: requests.Response | None = None
        try:
            headers = get_portal_auth_headers(c)
            waba_resolved = get_waba_id(c)
            esme_resolved = get_esmeaddr(c)
            logger.info(
                "🔒 CONFIRMATION CHECKPOINT [Portal Create]: client=%s, waba_id=%s, esmeaddr=%s, template=%s, credential_source=%s_KARIX_BEARER_TOKEN",
                c,
                waba_resolved,
                esme_resolved,
                payload.template_name,
                _account_prefix(c),
            )
            t0 = time.time()
            resp = get_http_session().post(
                url,
                headers=headers,
                files={"request": (None, json.dumps(body), "application/json")},
                timeout=REQUEST_TIMEOUT,
            )
            _GOVERNOR.record_request(time.time() - t0, status_code=resp.status_code if resp else 500)
        except (requests.ConnectionError, requests.Timeout) as e:
            exc = e
            _GOVERNOR.record_request(REQUEST_TIMEOUT, status_code=500, is_error=True)
            logger.warning("Attempt %d/%d transport error: %s", attempt + 1, MAX_RETRIES, e)
        except OSError as e:
            _GOVERNOR.record_request(0.1, status_code=500, is_error=True)
            return SubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                status=SubmissionStatus.FAILED,
                error=str(e),
                approval_status=ApprovalStatus.UNKNOWN,
                client=c,
                channel="whatsapp",
                retry_count=attempt,
            )
        # ---- Handle transport errors (retry) ----
        if exc is not None:
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
                time.sleep(BACKOFF_SECONDS * (2**attempt))
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
                attempt + 1,
                MAX_RETRIES,
                resp.status_code,
                resp.text[:500],
            )
            last_result = SubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                status=SubmissionStatus.FAILED,
                error=f"HTTP {resp.status_code}",
                provider_response=data,
                approval_status=ApprovalStatus.UNKNOWN,
                client=c,
                channel="whatsapp",
                retry_count=attempt,
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_SECONDS * (2**attempt))
            continue

        return _evaluate_portal_create_response(resp, data, payload, c, attempt)
    return last_result


def _requires_portal_media(payload: TemplateSubmission) -> bool:
    """Return whether the template needs an unverified official media handle."""
    for component in payload.components:
        ctype = component.get("type") if isinstance(component, dict) else getattr(component, "type", "")
        cformat = component.get("format") if isinstance(component, dict) else getattr(component, "format", "")
        if str(ctype).upper() == "HEADER" and str(cformat).upper() in {
            "IMAGE",
            "DOCUMENT",
            "VIDEO",
        }:
            return True
    return False


def _build_official_create_body(
    payload: TemplateSubmission,
    client: str = "bajaj",
    fix_aspect_ratio: bool = True,
    fix_grammar: bool = True,
) -> dict:
    """
    Build the documented JSON body for POST /api/v1.0/template/{wabaId}.

    Portal-only account fields and the literal sessionId are deliberately absent.
    """
    components = copy.deepcopy(_build_portal_create_body(payload, client=client)["components"])
    components = _resolve_header_media(components, client=client, fix_aspect_ratio=fix_aspect_ratio)
    components = _resolve_body_variables(components, client=client, fix_grammar=fix_grammar)

    return {
        "template_name": payload.template_name,
        "language": payload.language,
        "category": payload.category,
        "components": components,
    }


def _submit_official_template(
    payload: TemplateSubmission,
    client: str = "bajaj",
    fix_aspect_ratio: bool = True,
    fix_grammar: bool = True,
) -> SubmissionResult:
    """Submit a text-only template through the verified official Karix API."""
    c = (client or getattr(payload, "client", None) or "bajaj").lower()
    try:
        waba_id = (
            payload.waba_id
            if getattr(payload, "waba_id", None) and payload.waba_id not in ("", BAJAJ_WABA_ID) and c != "bajaj"
            else None
        ) or get_waba_id(c)
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
    body = _build_official_create_body(payload, client=c, fix_aspect_ratio=fix_aspect_ratio, fix_grammar=fix_grammar)
    last_result: SubmissionResult | None = None
    for attempt in range(MAX_RETRIES):
        try:
            headers = get_official_auth_headers(c)
            headers["Content-Type"] = "application/json"
            logger.info(
                "🔒 CONFIRMATION CHECKPOINT [Official Create]: client=%s, waba_id=%s, template=%s, credential_source=%s_WABA_AUTH_TOKEN",
                c,
                waba_id,
                payload.template_name,
                _account_prefix(c),
            )
            t0 = time.time()
            response = get_http_session().post(url, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
            _GOVERNOR.record_request(time.time() - t0, status_code=response.status_code if response else 500)
        except (requests.ConnectionError, requests.Timeout) as exc:
            _GOVERNOR.record_request(REQUEST_TIMEOUT, status_code=500, is_error=True)
            last_result = SubmissionResult(
                template_name=payload.template_name,
                status=SubmissionStatus.FAILED,
                error=f"Transport error: {exc}",
                approval_status=ApprovalStatus.UNKNOWN,
                client=c,
                channel="whatsapp",
                retry_count=attempt,
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_SECONDS * (2**attempt))
            continue
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            data = {"_raw_text": response.text}

        if response.status_code in _RETRYABLE_STATUS_CODES:
            err_detail = f"HTTP {response.status_code}"
            if response.text and response.text.strip():
                err_detail = f"HTTP {response.status_code}: {response.text[:2000].strip()}"
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
                time.sleep(BACKOFF_SECONDS * (2**attempt))
            continue
        # 401 Unauthorized = expired/invalid WABA API token. No browser
        # auto-login (Karix portal requires OTP) — surface an actionable error.
        if response.status_code == 401:
            return SubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                status=SubmissionStatus.FAILED,
                error=(
                    "WABA API Token invalid or expired (401). Open Settings → "
                    f"{c} and paste a fresh Official WABA API Token from the "
                    "Karix Lounge."
                ),
                provider_response=data,
                approval_status=ApprovalStatus.UNKNOWN,
                client=c,
                channel="whatsapp",
                retry_count=attempt,
            )

        if response.status_code != 201:
            return SubmissionResult(
                source_ref=payload.source_ref,
                template_name=payload.template_name,
                status=SubmissionStatus.FAILED,
                error=f"HTTP {response.status_code}: {response.text[:2000]}",
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
                error="No templateId returned in official API response",
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


def submit_template(
    payload: TemplateSubmission,
    client: str = "bajaj",
    fix_aspect_ratio: bool = True,
    fix_grammar: bool = True,
) -> SubmissionResult:
    """
    Submit one template to Karix and return the result.
    If portal session credentials exist, uses Portal API.
    If official WABA static token exists, uses Official API.
    """
    c = (client or getattr(payload, "client", None) or "bajaj").lower()

    # 1. Primary for accounts with Portal Session: Portal API
    try:
        get_portal_auth_headers(c)
        portal_res = _submit_portal_template(payload, client=c)
        if portal_res.status == SubmissionStatus.SUBMITTED:
            return portal_res
        if (
            portal_res.error
            and "Unauthorised" not in str(portal_res.error)
            and "Missing required" not in str(portal_res.error)
        ):
            return portal_res
    except OSError:
        pass

    # 2. Try Official WABA API if official token is configured
    try:
        get_official_auth_headers(c)
        official_res = _submit_official_template(
            payload,
            client=c,
            fix_aspect_ratio=fix_aspect_ratio,
            fix_grammar=fix_grammar,
        )
        if official_res.status == SubmissionStatus.SUBMITTED:
            return official_res
    except OSError:
        pass

    # 3. Final fallback
    try:
        return _submit_portal_template(payload, client=c)
    except Exception:
        return _submit_official_template(
            payload,
            client=c,
            fix_aspect_ratio=fix_aspect_ratio,
            fix_grammar=fix_grammar,
        )


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


def fetch_template_list(client: str = "bajaj") -> tuple[list[dict], str | None]:
    """
    Fetch the full template list for a client's WABA (supports Portal API and Official API).
    Returns (templates_list, error_str_if_any).
    """
    c = (client or "bajaj").lower().strip()

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
    except Exception as exc:
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
            if isinstance(data, dict):
                return data.get("response", {}).get("templates", []), None
    except Exception as exc:
        logger.debug("Official fetch_template_list notice for %s: %s", c, exc)

    return [], None


def _match_template(templates: list[dict], provider_ref_id: str) -> dict | None:
    """Match a provider ref against fb_template_id, sno, or template name."""
    return next(
        (
            t
            for t in templates
            if str(t.get("fb_template_id", "")) == provider_ref_id
            or str(t.get("sno", "")) == provider_ref_id
            or t.get("template_name") == provider_ref_id
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
