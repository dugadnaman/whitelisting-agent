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

import os

# ---------------------------------------------------------------------------
# Auth credentials — read fresh from env on every call so that a token
# refresh (e.g. via a wrapper script that re-exports env vars) is picked
# up without restarting the process.
# ---------------------------------------------------------------------------

def _load_env_file():
    """Load key-value pairs from credentials.json and .env file if present."""
    from pathlib import Path
    import json

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
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k and v:
                os.environ[k] = v
def get_portal_auth_headers(client: str = "bajaj") -> dict[str, str]:
    """
    Build HTTP headers for the legacy portal media-upload endpoint.
    """
    _load_env_file()
    c = client.lower()
    if c == "tata":
        bearer = os.environ.get("TATA_KARIX_BEARER_TOKEN") or os.environ.get("KARIX_BEARER_TOKEN")
        session = os.environ.get("TATA_KARIX_SESSION") or os.environ.get("KARIX_SESSION")
        user = os.environ.get("TATA_KARIX_USER") or os.environ.get("KARIX_USER")
    else:
        bearer = os.environ.get("BAJAJ_KARIX_BEARER_TOKEN") or os.environ.get("KARIX_BEARER_TOKEN")
        session = os.environ.get("BAJAJ_KARIX_SESSION") or os.environ.get("KARIX_SESSION")
        user = os.environ.get("BAJAJ_KARIX_USER") or os.environ.get("KARIX_USER")

    missing = []
    if not bearer:
        missing.append("TATA_KARIX_BEARER_TOKEN" if c == "tata" else "KARIX_BEARER_TOKEN")
    if not session:
        missing.append("TATA_KARIX_SESSION" if c == "tata" else "KARIX_SESSION")
    if not user:
        missing.append("TATA_KARIX_USER" if c == "tata" else "KARIX_USER")
    if missing:
        raise OSError(
            f"Missing required Karix portal credentials for {client}: {', '.join(missing)}. "
            "Please enter the Portal Bearer Token, Session ID, and User in Settings under Legacy Portal Session Headers."
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
    """
    _load_env_file()
    if client.lower() == "tata":
        token = os.environ.get("TATA_WABA_AUTH_TOKEN") or os.environ.get("TATA_AUTH_TOKEN")
    else:
        token = os.environ.get("BAJAJ_WABA_AUTH_TOKEN") or os.environ.get("WABA_AUTH_TOKEN")

    if not token:
        client_name = "Tata Capital" if client.lower() == "tata" else "Bajaj"
        raise OSError(
            f"Missing required {client_name} official API credential: {('TATA_WABA_AUTH_TOKEN' if client.lower() == 'tata' else 'WABA_AUTH_TOKEN')}. "
            "Set it in Settings or .env file."
        )
    return {"Authentication": f"Bearer {token}"}


def get_waba_id(client: str = "bajaj") -> str:
    """Return WABA ID for the given client."""
    _load_env_file()
    if client.lower() == "tata":
        val = os.environ.get("TATA_WABA_ID")
        if not val:
            raise OSError("Missing required Tata WABA ID: TATA_WABA_ID in environment.")
        return val
    return os.environ.get("BAJAJ_WABA_ID") or os.environ.get("WABA_ID") or BAJAJ_WABA_ID


def get_esmeaddr(client: str = "bajaj") -> str:
    """Return ESME address for the given client."""
    _load_env_file()
    if client.lower() == "tata":
        val = os.environ.get("TATA_ESMEADDR")
        if not val:
            # Auto-extract from token or use standard Tata ESMEADDR
            import re
            token = os.environ.get("TATA_KARIX_BEARER_TOKEN") or os.environ.get("KARIX_BEARER_TOKEN") or ""
            m = re.search(r"(\d{10,16})", token)
            if m:
                return m.group(1)
            return "72516600000000"
        return val
    return os.environ.get("BAJAJ_ESMEADDR") or BAJAJ_ESMEADDR


def get_template_namespace_id(client: str = "bajaj") -> str:
    """Return template namespace ID for the given client."""
    _load_env_file()
    if client.lower() == "tata":
        return os.environ.get("TATA_TEMPLATE_NAMESPACE_ID") or os.environ.get("TEMPLATE_NAMESPACE_ID") or BAJAJ_TEMPLATE_NAMESPACE_ID
    return os.environ.get("BAJAJ_TEMPLATE_NAMESPACE_ID") or BAJAJ_TEMPLATE_NAMESPACE_ID
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
