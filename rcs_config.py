"""
Configuration for the Karix RCS / DLT template configuration pipeline.

Loads secrets and session credentials from environment variables.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Default Constants (from Bajaj BFDL_RCS account)
# ---------------------------------------------------------------------------

BAJAJ_ENTITY_ID = "110100001654"

KARIX_LOUNGE_BASE_URL = "https://karix.solutions/lounge/LoungePage"
KARIX_DLT_REGISTRATION_URL = f"{KARIX_LOUNGE_BASE_URL}/dltRegistration.php"
KARIX_DLT_ACTION_URL = f"{KARIX_LOUNGE_BASE_URL}/dltRegistrationAction.php"


def _load_env_file() -> None:
    """Load key-value pairs from a local .env file if present."""
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k and v and not os.environ.get(k):
                os.environ[k] = v


def get_rcs_entity_id(client: str = "bajaj") -> str:
    """Return the Entity ID for RCS DLT templates."""
    _load_env_file()
    if client.lower() == "tata":
        return os.environ.get("TATA_ENTITY_ID") or os.environ.get("TATA_RCS_ENTITY_ID") or ""
    return os.environ.get("BAJAJ_ENTITY_ID") or os.environ.get("ENTITY_ID") or BAJAJ_ENTITY_ID


def get_rcs_auth_headers(client: str = "bajaj") -> dict[str, str]:
    """
    Build the HTTP headers required for Karix Lounge DLT requests.
    Supports session cookies or Bearer/Session tokens from DevTools.
    """
    _load_env_file()

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": KARIX_DLT_REGISTRATION_URL,
        "Origin": "https://karix.solutions",
        "X-Requested-With": "XMLHttpRequest",
    }

    prefix = "TATA_" if client.lower() == "tata" else ""
    cookie = os.environ.get(f"{prefix}KARIX_LOUNGE_COOKIE") or os.environ.get("KARIX_LOUNGE_COOKIE")
    if cookie:
        headers["Cookie"] = cookie

    bearer = os.environ.get(f"{prefix}KARIX_BEARER_TOKEN") or os.environ.get("KARIX_BEARER_TOKEN")
    session = os.environ.get(f"{prefix}KARIX_SESSION") or os.environ.get("KARIX_SESSION")
    user = os.environ.get(f"{prefix}KARIX_USER") or os.environ.get("KARIX_USER")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if session:
        headers["Session"] = session
    if user:
        headers["User"] = user

    return headers
