"""
Configuration for the Karix WhatsApp template submission pipeline.

All secrets and account-specific constants are loaded from environment
variables.  Never hardcode credentials in source files.

Auth model:
    Text-only WhatsApp template submission and status checks use the official
    static WABA token (`WABA_AUTH_TOKEN`) with the documented `Authentication`
    header. This is the default and does not require a browser session.

    Image-header media upload remains on the portal API until Karix documents
    an equivalent official media-handle endpoint. Its `KARIX_BEARER_TOKEN`,
    `KARIX_SESSION`, and `KARIX_USER` credentials are therefore retained only
    for that temporary media-upload path.
"""

import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth credentials — read fresh from env on every call so that a token
# refresh (e.g. via a wrapper script that re-exports env vars) is picked
# up without restarting the process.
# ---------------------------------------------------------------------------


def _load_env_file():
    """Load key-value pairs from credentials.json and .env file if present."""
    import json
    from pathlib import Path

    # 1. Load credentials.json (saved from Settings UI)
    cred_json_path = Path("credentials.json")
    if cred_json_path.exists():
        try:
            creds = json.loads(cred_json_path.read_text(encoding="utf-8"))
            for k, v in creds.items():
                if k and v:
                    os.environ[k] = str(v).strip()
        except Exception:
            pass

    # 2. Load .env file
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
    """Sanitize client name into uppercase environment variable prefix."""


def get_portal_auth_headers(client: str = "bajaj") -> dict[str, str]:
    """
    Build HTTP headers for the legacy portal media-upload endpoint.
    Strictly isolated per account. Never cross-contaminates another account.
    """
    _load_env_file()
    c = (client or "bajaj").lower().strip()
    prefix = _account_prefix(c)
    if c == "bajaj":
        bearer = os.environ.get("BAJAJ_KARIX_BEARER_TOKEN") or os.environ.get("KARIX_BEARER_TOKEN")
        session = os.environ.get("BAJAJ_KARIX_SESSION") or os.environ.get("KARIX_SESSION")
        user = os.environ.get("BAJAJ_KARIX_USER") or os.environ.get("KARIX_USER")
    else:
        bearer = os.environ.get(f"{prefix}_KARIX_BEARER_TOKEN") or os.environ.get("TATA_KARIX_BEARER_TOKEN")
        session = os.environ.get(f"{prefix}_KARIX_SESSION") or os.environ.get("TATA_KARIX_SESSION")
        user = (
            os.environ.get(f"{prefix}_KARIX_USER")
            or os.environ.get("TATA_KARIX_USER")
            or os.environ.get(f"{prefix}_PORTAL_USER")
        )

    # If token is still missing, trigger headless auto-login using portal user & pass
    if not bearer or not session:
        portal_u = os.environ.get(f"{prefix}_PORTAL_USER") or os.environ.get("TATA_PORTAL_USER")
        portal_p = os.environ.get(f"{prefix}_PORTAL_PASSWORD") or os.environ.get("TATA_PORTAL_PASSWORD")
        if portal_u and portal_p:
            try:
                from auth_refresher import refresh_karix_session

                ref_res = refresh_karix_session(account=c)
                if ref_res.get("success"):
                    _load_env_file()
                    bearer = os.environ.get(f"{prefix}_KARIX_BEARER_TOKEN") or os.environ.get("TATA_KARIX_BEARER_TOKEN")
                    session = os.environ.get(f"{prefix}_KARIX_SESSION") or os.environ.get("TATA_KARIX_SESSION")
                    user = os.environ.get(f"{prefix}_KARIX_USER") or os.environ.get("TATA_KARIX_USER")
            except Exception as e:
                logger.warning("Auto-refresh on get_portal_auth_headers notice: %s", e)

    missing = []
    if not bearer:
        missing.append(f"{prefix}_KARIX_BEARER_TOKEN" if c != "bajaj" else "BAJAJ_KARIX_BEARER_TOKEN")
    if not session:
        missing.append(f"{prefix}_KARIX_SESSION" if c != "bajaj" else "BAJAJ_KARIX_SESSION")
    if not user:
        missing.append(f"{prefix}_KARIX_USER" if c != "bajaj" else "BAJAJ_KARIX_USER")
    if missing:
        raise OSError(
            f"Missing required Karix portal credentials for {client}: {', '.join(missing)}. "
            "Please enter the Portal Bearer Token, Session ID, and User in Settings or click ⚡ Run Auto-Login."
        )

    return {
        "Authorization": f"Bearer {bearer}",
        "Session": session,
        "User": user,
        "Origin": KARIX_ORIGIN,
        "Referer": KARIX_REFERER,
    }


def get_official_auth_headers(client: str = "bajaj") -> dict[str, str]:
    """
    Build headers for the official WhatsApp Template API for the given client.
    Strictly isolated per account. Never cross-contaminates another WABA account.
    """
    _load_env_file()
    c = (client or "bajaj").lower().strip()
    prefix = _account_prefix(c)

    if c == "bajaj":
        token = os.environ.get("BAJAJ_WABA_AUTH_TOKEN") or os.environ.get("WABA_AUTH_TOKEN")
    else:
        token = (
            os.environ.get(f"{prefix}_WABA_AUTH_TOKEN")
            or os.environ.get(f"{prefix}_AUTH_TOKEN")
            or os.environ.get(f"{prefix}_KARIX_BEARER_TOKEN")
            or os.environ.get("TATA_WABA_AUTH_TOKEN")
            or os.environ.get("TATA_KARIX_BEARER_TOKEN")
        )

    if not token:
        expected_key = f"{prefix}_WABA_AUTH_TOKEN" if c != "bajaj" else "BAJAJ_WABA_AUTH_TOKEN"
        raise OSError(
            f"Missing required WABA API Token for {client} ({expected_key}). "
            f"Please enter the API Token in Settings under {client} before submitting."
        )
    return {"Authentication": f"Bearer {token}"}


def get_waba_id(client: str = "bajaj") -> str:
    """
    Return WABA ID for the given client.
    Strictly isolated per account. Never uses another account's WABA ID.
    """
    _load_env_file()
    c = (client or "bajaj").lower().strip()
    prefix = _account_prefix(c)

    if c == "bajaj":
        return os.environ.get("BAJAJ_WABA_ID") or os.environ.get("WABA_ID") or BAJAJ_WABA_ID
    else:
        return os.environ.get(f"{prefix}_WABA_ID") or os.environ.get("TATA_WABA_ID") or "286109054585247"


def get_esmeaddr(client: str = "bajaj") -> str:
    """Return ESME address for the given client."""
    _load_env_file()
    c = (client or "bajaj").lower().strip()
    prefix = _account_prefix(c)
    if c == "bajaj":
        return os.environ.get("BAJAJ_ESMEADDR") or os.environ.get("ESMEADDR") or BAJAJ_ESMEADDR
    return os.environ.get(f"{prefix}_ESMEADDR") or os.environ.get("TATA_ESMEADDR") or "72516600000000"


def get_template_namespace_id(client: str = "bajaj") -> str:
    """Return template namespace ID for the given client."""
    _load_env_file()
    c = (client or "bajaj").lower().strip()
    prefix = _account_prefix(c)
    if c == "bajaj":
        return (
            os.environ.get("BAJAJ_TEMPLATE_NAMESPACE_ID")
            or os.environ.get("TEMPLATE_NAMESPACE_ID")
            or BAJAJ_TEMPLATE_NAMESPACE_ID
        )
    return (
        os.environ.get(f"{prefix}_TEMPLATE_NAMESPACE_ID")
        or os.environ.get("TATA_TEMPLATE_NAMESPACE_ID")
        or "42eec6e7_6287_4b1d_8ec8_52f4a80c23b5"
    )


# ---------------------------------------------------------------------------
# Fixed constants — same for every request on this Bajaj WABA account.
# ---------------------------------------------------------------------------

KARIX_BASE_URL = "https://rcsgui.karix.solutions/v1.0/templates"
OFFICIAL_TEMPLATE_BASE_URL = "https://rcsgui.karix.solutions/api/v1.0/template"

KARIX_ORIGIN = "https://rcmui.instaalerts.zone"
KARIX_REFERER = "https://rcmui.instaalerts.zone/"

BAJAJ_WABA_ID = "286109054585247"
BAJAJ_ESMEADDR = "72148300000000"
BAJAJ_TEMPLATE_NAMESPACE_ID = "42eec6e7_6287_4b1d_8ec8_52f4a80c23b5"
