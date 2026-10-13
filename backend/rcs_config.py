"""
Configuration for the Karix RCS Bot Builder & DLT template pipeline.

Supports official Karix RCS Template Management API:
- POST https://rcsgui.karix.solutions/api/rcstemplate/save
- GET https://rcsgui.karix.solutions/api/v1.0/rcstemplate/getTemplatesWithFilter?senderId={senderId}
"""

import os
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Official RCS Template Management Endpoints
# ---------------------------------------------------------------------------

KARIX_RCS_BASE_URL = "https://rcsgui.karix.solutions/api/rcstemplate"
KARIX_RCS_SAVE_URL = "https://rcsgui.karix.solutions/api/rcstemplate/save"
KARIX_RCS_UPDATE_URL = "https://rcsgui.karix.solutions/api/rcstemplate/update"
KARIX_RCS_DELETE_URL = "https://rcsgui.karix.solutions/api/rcstemplate/delete"
KARIX_RCS_FETCH_URL = "https://rcsgui.karix.solutions/api/v1.0/rcstemplate/getTemplatesWithFilter"
KARIX_RCS_FETCH_TEMPLATES_URL = "https://rcsgui.karix.solutions/api/rcstemplate/fetchTemplates"
KARIX_RCS_MEDIA_UPLOAD_URL = "https://rcsgui.karix.solutions/v1.0/templates/mediaUpload"

# Default Bot IDs / Sender IDs
DEFAULT_RCS_BOT_IDS: dict[str, str] = {
    "bajaj": "af2vdbyFh3RX8eee",
    "tcl_promo": "Uv9tdd0KNADbq3pX",
    "tcl_trans": "Uv9tdd0KNADbq3pX",
    "tchfl": "G0OedCS9mbsMYBq1",
    "wealth": "Wk22bU8IZqDRyIwQ",
    "moneyfy": "ouwJCTgIe0QDBPPI",
    "tata": "Uv9tdd0KNADbq3pX",
    "apparel": "P7hzkqCcW3x96I6T",
}

DEFAULT_RCS_BOT_NAMES: dict[str, str] = {
    "tcl_promo": "Tata Capital Limited",
    "tcl_trans": "Tata Capital Limited",
    "tchfl": "TCHFL",
    "wealth": "Tata Capital Wealth",
    "moneyfy": "Moneyfy by Tata Capital",
    "tata": "Tata Capital Limited",
    "apparel": "Apparel Brand",
}
DEFAULT_RCS_ESMEADDRS: dict[str, str] = {
    "bajaj": "72148300000000",
    "tcl_promo": "72434700000000",
    "tcl_trans": "72434700000000",
    "tchfl": "72389800000000",
    "wealth": "72516600000000",
    "moneyfy": "72516600000000",
    "apparel": "71189600000000",
}

DEFAULT_RCS_AUTH_TOKENS: dict[str, str] = {}
TATA_RCS_BOT_ID = "Uv9tdd0KNADbq3pX"
BAJAJ_RCS_BOT_ID = "af2vdbyFh3RX8eee"
# Legacy Lounge URLs
KARIX_LOUNGE_BASE_URL = "https://karix.solutions/lounge/LoungePage"
KARIX_DLT_ACTION_URL = f"{KARIX_LOUNGE_BASE_URL}/dltRegistrationAction.php"


def _load_env_file() -> None:
    """Load key-value pairs from credentials.json and local .env file if present."""
    import json

    cred_path = Path("credentials.json")
    if cred_path.exists():
        try:
            creds = json.loads(cred_path.read_text(encoding="utf-8"))
            for k, v in creds.items():
                if k and v and k not in os.environ:
                    os.environ[k] = str(v).strip()
        except Exception:
            pass

    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k and v and k not in os.environ:
                os.environ[k] = v


def _account_prefix(client: str) -> str:
    import re

    if not isinstance(client, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*", client.strip()):
        raise ValueError("RCS account must be an explicit account key")
    return client.strip().upper()


def get_rcs_bot_id(client: str = "tata") -> str:
    """Return the active RCS Bot ID / Sender ID for the given client."""
    _load_env_file()
    c = client.strip().lower() if isinstance(client, str) else client
    prefix = _account_prefix(c)
    bot = (
        os.environ.get(f"{prefix}_RCS_BOT_ID")
        or os.environ.get(f"{prefix}_RCS_SENDER_ID")
        or DEFAULT_RCS_BOT_IDS.get(c)
    )
    if not bot:
        raise OSError(
            f"Missing RCS Bot ID for {client} ({prefix}_RCS_BOT_ID). "
            f"Configure it in Settings under {client} — never fall back to another account's Bot ID."
        )
    return bot


def get_rcs_bot_name(client: str = "tcl_promo") -> str:
    """Return the active RCS Bot Name for the given client."""
    _load_env_file()
    c = client.strip().lower() if isinstance(client, str) else client
    prefix = _account_prefix(c)
    return os.environ.get(f"{prefix}_RCS_BOT_NAME") or DEFAULT_RCS_BOT_NAMES.get(c, "")


def get_rcs_entity_id(client: str = "tata") -> str:
    """Return the Entity ID for RCS DLT templates."""
    _load_env_file()
    c = client.strip().lower() if isinstance(client, str) else client
    prefix = _account_prefix(c)
    if c == "bajaj":
        return os.environ.get("BAJAJ_ENTITY_ID") or "110100001654"
    elif c in ("tata", "tcl_promo", "tcl_trans", "tchfl", "wealth", "moneyfy"):
        return (
            os.environ.get(f"{prefix}_ENTITY_ID")
            or os.environ.get("TATA_ENTITY_ID")
            or os.environ.get("TATA_RCS_ENTITY_ID")
            or "1001490234791338781"
        )
    return os.environ.get(f"{prefix}_ENTITY_ID") or ""


def get_rcs_esmeaddr(client: str = "tata") -> str:
    """Return the ESME address specifically configured for RCS for the given client."""
    _load_env_file()
    c = client.strip().lower() if isinstance(client, str) else client
    prefix = _account_prefix(c)
    esme = (
        os.environ.get(f"{prefix}_RCS_ESMEADDR")
        or os.environ.get(f"{prefix}_ESMEADDR")
        or DEFAULT_RCS_ESMEADDRS.get(c)
    )
    if not esme:
        raise OSError(f"Missing RCS ESME address for {client} ({prefix}_RCS_ESMEADDR).")
    return str(esme).strip()


def get_rcs_auth_headers(client: str = "tata", *, auth_token: str | None = None) -> dict[str, str]:
    """
    Build the HTTP headers required for official Karix RCS Bot Builder requests.
    Strictly isolated per client account. Never leaks credentials across accounts.
    """
    _load_env_file()
    c = client.strip().lower() if isinstance(client, str) else client
    prefix = _account_prefix(c)

    bearer = auth_token if auth_token is not None else (
        os.environ.get(f"{prefix}_RCS_AUTH_TOKEN")
        or os.environ.get(f"{prefix}_KARIX_BEARER_TOKEN")
    )
    bearer = re.sub(r"^(?:Authorization\s*:\s*)?Bearer(?:\s+|$)", "", (bearer or "").strip(), flags=re.IGNORECASE).strip()
    session = os.environ.get(f"{prefix}_KARIX_SESSION")
    user = os.environ.get(f"{prefix}_KARIX_USER")
    if not bearer or not bearer.strip():
        raise OSError(
            f"Missing required RCS Bearer token for {client} ({prefix}_KARIX_BEARER_TOKEN or {prefix}_RCS_AUTH_TOKEN). "
            f"Please enter Bearer Token in Settings under {client}."
        )
    headers = {
        "Authorization": f"Bearer {bearer.strip()}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Origin": "https://rcmui.instaalerts.zone",
        "Referer": "https://rcmui.instaalerts.zone/",
    }

    if session:
        headers["Session"] = session.strip()
    if user:
        headers["User"] = user.strip()

    return headers
