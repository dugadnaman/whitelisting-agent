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
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth credentials — read fresh from env on every call so that a token
# refresh (e.g. via a wrapper script that re-exports env vars) is picked
# up without restarting the process.
# ---------------------------------------------------------------------------


_PREEXISTING_ENV = frozenset(os.environ.keys())


def _load_env_file():
    """Load key-value pairs from credentials.json and .env file if present.

    Precedence: real environment variables (e.g. Render dashboard env vars)
    always win over file values — files are defaults only. This prevents the
    git-tracked credentials.json from overriding tokens set in the dashboard,
    which survive deploys unlike Render's ephemeral filesystem.
    """

    import json
    from pathlib import Path

    # 1. Load credentials.json (saved from Settings UI)
    cred_json_path = Path("credentials.json")
    if cred_json_path.exists():
        try:
            creds = json.loads(cred_json_path.read_text(encoding="utf-8"))
            for k, v in creds.items():
                if k and v and (k not in _PREEXISTING_ENV or k not in os.environ):
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
            if k and v and (k not in _PREEXISTING_ENV or k not in os.environ):
                os.environ[k] = v


def _account_prefix(client: str) -> str:
    """Sanitize client name into uppercase environment variable prefix."""
    import re

    return re.sub(r"[^a-zA-Z0-9_]", "_", client).strip("_").upper()


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
        # Strict tenant separation: each sub-account has its own portal login
        # (e.g. TCHFL=TATACAPWABA, TCL_PROMO=TATACAPPROMO). Never inherit the
        # parent TATA_* session — submitting under another login's session is
        # what caused Meta's "invalid media handle" cross-WABA rejections.
        bearer = os.environ.get(f"{prefix}_KARIX_BEARER_TOKEN")
        session = os.environ.get(f"{prefix}_KARIX_SESSION")
        user = os.environ.get(f"{prefix}_KARIX_USER") or os.environ.get(f"{prefix}_PORTAL_USER")

    # NOTE: no browser auto-login — the Karix portal requires an OTP only a
    # human can receive. Tokens are entered manually in Settings and persist
    # via credentials.json (committed back to the repo on save) until they
    # naturally expire.

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
            "Open Settings → " + client + " and paste the Portal Bearer Token, Session ID, and User "
            "from the Karix portal (logged-in browser → DevTools → Network → request headers)."
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
        # Strict tenant separation: no silent inheritance of the parent token.
        token = os.environ.get(f"{prefix}_WABA_AUTH_TOKEN")

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
        waba = os.environ.get(f"{prefix}_WABA_ID")
        if not waba:
            raise OSError(
                f"Missing WABA ID for {client} ({prefix}_WABA_ID). "
                f"Configure it in Settings under {client} — never fall back to another account's WABA."
            )
        return waba


def _esmeaddr_from_session_token(token: str | None) -> str | None:
    """
    Decode the esmeaddr embedded in a Karix portal session token.

    Token payload format: <random><esmeaddr><ACCOUNT_NAME>, e.g.
      'msijafen72148300000000BFDL_WABA'      -> 72148300000000 (Bajaj)
      'msx42ip072516600000000TATACAPPROMO'   -> 72516600000000
      'mt89yco272389800000000TATACAPWABA'    -> 72389800000000 (TCHFL)

    Every sub-account has its OWN esmeaddr — the authoritative source is the
    session token itself, not shared config values.
    """
    if not token or "." not in token:
        return None
    try:
        import base64

        payload = base64.b64decode(token.split(".")[1] + "==").decode("utf-8", errors="replace")
        m = re.search(r"(\d{14,15})([A-Z_]+)$", payload)
        if not m:
            return None
        digits = m.group(1)
        return digits[1:] if len(digits) == 15 else digits
    except Exception:
        return None


def get_esmeaddr(client: str = "bajaj") -> str:
    """
    Return ESME address for the given client.

    The esmeaddr embedded in the account's portal session token is
    authoritative (each sub-account has its own); env/config values are
    fallbacks for accounts without a session token yet.
    """
    _load_env_file()
    c = (client or "bajaj").lower().strip()
    prefix = _account_prefix(c)
    if c == "bajaj":
        token = os.environ.get("BAJAJ_KARIX_BEARER_TOKEN") or os.environ.get("KARIX_BEARER_TOKEN")
        return (
            _esmeaddr_from_session_token(token)
            or os.environ.get("BAJAJ_ESMEADDR")
            or os.environ.get("ESMEADDR")
            or BAJAJ_ESMEADDR
        )
    token = os.environ.get(f"{prefix}_KARIX_BEARER_TOKEN")
    esme = _esmeaddr_from_session_token(token) or os.environ.get(f"{prefix}_ESMEADDR")
    if not esme:
        raise OSError(
            f"Missing ESMEADDR for {client} ({prefix}_ESMEADDR or portal session token). "
            f"Configure credentials in Settings under {client}."
        )
    return esme


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
    return os.environ.get(f"{prefix}_TEMPLATE_NAMESPACE_ID") or os.environ.get("TATA_TEMPLATE_NAMESPACE_ID") or ""


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
