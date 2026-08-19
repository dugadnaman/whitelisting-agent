"""
Configuration for the Karix RCS Bot Builder & DLT template pipeline.

Supports official Karix RCS Template Management API:
- POST https://rcsgui.karix.solutions/api/rcstemplate/save
- GET https://rcsgui.karix.solutions/api/v1.0/rcstemplate/getTemplatesWithFilter?senderId={senderId}
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Official RCS Template Management Endpoints
# ---------------------------------------------------------------------------

KARIX_RCS_BASE_URL = "https://rcsgui.karix.solutions/api/rcstemplate"
KARIX_RCS_SAVE_URL = "https://rcsgui.karix.solutions/api/rcstemplate/save"
KARIX_RCS_UPDATE_URL = "https://rcsgui.karix.solutions/api/rcstemplate/update"
KARIX_RCS_DELETE_URL = "https://rcsgui.karix.solutions/api/rcstemplate/delete"
KARIX_RCS_FETCH_URL = "https://rcsgui.karix.solutions/api/v1.0/rcstemplate/getTemplatesWithFilter"
KARIX_RCS_MEDIA_UPLOAD_URL = "https://rcsgui.karix.solutions/v1.0/templates/mediaUpload"

# Default Bot IDs / Sender IDs
TATA_RCS_BOT_ID = "Uv9tdd0KNADbq3pX"
BAJAJ_RCS_BOT_ID = "af2vdbyFh3RX8eee"

# Legacy Lounge URLs
KARIX_LOUNGE_BASE_URL = "https://karix.solutions/lounge/LoungePage"
KARIX_DLT_ACTION_URL = f"{KARIX_LOUNGE_BASE_URL}/dltRegistrationAction.php"


def _load_env_file() -> None:
    """Load key-value pairs from a local .env file if present."""
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k and v:
                os.environ[k] = v


def _account_prefix(client: str) -> str:
    import re
    return re.sub(r'[^a-zA-Z0-9_]', '_', client).strip('_').upper()

def get_rcs_bot_id(client: str = "tata") -> str:
    """Return the active RCS Bot ID / Sender ID for the given client."""
    _load_env_file()
    c = (client or "tata").lower().strip()
    prefix = _account_prefix(c)
    if c == "tata":
        return os.environ.get("TATA_RCS_BOT_ID") or os.environ.get("TATA_RCS_SENDER_ID") or TATA_RCS_BOT_ID
    elif c == "bajaj":
        return os.environ.get("BAJAJ_RCS_BOT_ID") or os.environ.get("BAJAJ_RCS_SENDER_ID") or BAJAJ_RCS_BOT_ID
    return os.environ.get(f"{prefix}_RCS_BOT_ID") or os.environ.get(f"{prefix}_RCS_SENDER_ID") or os.environ.get("RCS_BOT_ID") or ""


def get_rcs_entity_id(client: str = "tata") -> str:
    """Return the Entity ID for RCS DLT templates."""
    _load_env_file()
    c = (client or "tata").lower().strip()
    prefix = _account_prefix(c)
    if c == "tata":
        return os.environ.get("TATA_ENTITY_ID") or os.environ.get("TATA_RCS_ENTITY_ID") or "1001490234791338781"
    elif c == "bajaj":
        return os.environ.get("BAJAJ_ENTITY_ID") or os.environ.get("ENTITY_ID") or "110100001654"
    return os.environ.get(f"{prefix}_ENTITY_ID") or os.environ.get("ENTITY_ID") or ""


def get_rcs_auth_headers(client: str = "tata") -> dict[str, str]:
    """
    Build the HTTP headers required for official Karix RCS Bot Builder requests.
    Uses Bearer authorization with session fallback.
    """
    _load_env_file()
    c = (client or "tata").lower().strip()
    prefix = _account_prefix(c)

    bearer = (
        os.environ.get(f"{prefix}_RCS_AUTH_TOKEN")
        or os.environ.get(f"{prefix}_KARIX_BEARER_TOKEN")
        or os.environ.get(f"{prefix}_WABA_AUTH_TOKEN")
        or os.environ.get(f"{prefix}_AUTH_TOKEN")
        or (os.environ.get("TATA_WABA_AUTH_TOKEN") if c == "tata" else None)
        or (os.environ.get("BAJAJ_WABA_AUTH_TOKEN") if c == "bajaj" else None)
        or os.environ.get("KARIX_BEARER_TOKEN")
        or os.environ.get("WABA_AUTH_TOKEN")
    )

    if not bearer:
        raise OSError(
            f"Missing required RCS Bearer token for {client}. "
            "Please enter Bearer Token in Settings."
        )
    headers = {
        "Authorization": f"Bearer {bearer.strip()}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Origin": "https://rcmui.instaalerts.zone",
        "Referer": "https://rcmui.instaalerts.zone/",
    }

    # If session header is available, include it
    session = os.environ.get(f"{prefix}KARIX_SESSION") or os.environ.get("KARIX_SESSION")
    user = os.environ.get(f"{prefix}KARIX_USER") or os.environ.get("KARIX_USER")
    if session:
        headers["Session"] = session.strip()
    if user:
        headers["User"] = user.strip()

    return headers
