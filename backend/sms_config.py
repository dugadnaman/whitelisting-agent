"""
Configuration for the Karix SMS pipeline.

Supports Karix SMS JSON API:
- POST https://japi.instaalerts.zone/httpapi/JsonReceiver
- Optional XML endpoint: https://japi.instaalerts.zone/httpapi/XMLReceiver

Supports account-specific credentials and configurations for multi-tenant deployments
(Bajaj, Tata Capital, etc.), with fresh reads from environment and credentials.json.
"""

import base64
import os
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Default Endpoints
# ---------------------------------------------------------------------------

KARIX_SMS_JSON_URL = "https://japi.instaalerts.zone/httpapi/JsonReceiver"
KARIX_SMS_XML_URL = "https://japi.instaalerts.zone/httpapi/XMLReceiver"

# Default Sender IDs
BAJAJ_SMS_DEFAULT_SENDER_ID = "BAJAJF"
TATA_SMS_DEFAULT_SENDER_ID = "TATACP"

_PREEXISTING_ENV = frozenset(os.environ.keys())


def _load_env_file() -> None:
    """Load key-value pairs from credentials.json and local .env file if present."""
    import json

    cred_path = Path("credentials.json")
    if cred_path.exists():
        try:
            creds = json.loads(cred_path.read_text(encoding="utf-8"))
            for k, v in creds.items():
                if k and v and (k not in _PREEXISTING_ENV or k not in os.environ):
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
            if k and v and (k not in _PREEXISTING_ENV or k not in os.environ):
                os.environ[k] = v


def _account_prefix(client: str) -> str:
    """Sanitize client name into uppercase environment variable prefix."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", client).strip("_").upper()

def _setting(client: str, suffix: str, *aliases: str) -> str:
    """Prefer encrypted one-time setup; never inherit another account's secrets."""
    from portal_sessions import load_settings

    _load_env_file()
    prefix = _account_prefix(client)
    saved = load_settings(client.lower().strip(), "sms")
    for key in (f"{prefix}_{suffix}", *(f"{prefix}_{alias}" for alias in aliases)):
        if saved.get(key) or os.environ.get(key):
            return str(saved.get(key) or os.environ[key]).strip()
    if client.lower().strip() == "bajaj":
        for key in (f"KARIX_{suffix}", *(f"KARIX_{alias}" for alias in aliases)):
            if os.environ.get(key):
                return os.environ[key].strip()
    return ""


def get_sms_api_url(client: str = "bajaj") -> str:
    """Return the JSON receiver API endpoint for this account."""
    return _setting(client, "SMS_API_URL") or KARIX_SMS_JSON_URL


def get_sms_key(client: str = "bajaj") -> str:
    """Return the Karix SMS Access Key (Authorization key)."""
    return _setting(client, "SMS_KEY", "SMS_ACCESS_KEY")


def get_sms_username(client: str = "bajaj") -> str:
    """Return the SMS account username for Basic HTTP Authorization."""
    return _setting(client, "SMS_USERNAME", "SMS_USER")


def get_sms_encryption_key(client: str = "bajaj") -> str:
    """
    Return the Base64-encoded AES-256 encryption key/password for PII encryption.

    Used when encrpt='1' in Send SMS API calls.
    """
    return _setting(client, "SMS_ENCRYPTION_KEY")


def get_sms_sender_id(client: str = "bajaj") -> str:
    """Return the registered DLT sender ID / header name for this account."""
    default = BAJAJ_SMS_DEFAULT_SENDER_ID if client.lower() == "bajaj" else TATA_SMS_DEFAULT_SENDER_ID
    return _setting(client, "SMS_SENDER_ID", "SENDER_ID") or default


def get_sms_dlt_entity_id(client: str = "bajaj") -> str:
    """Return the DLT Entity ID for this client."""
    return _setting(client, "SMS_ENTITY_ID", "DLT_ENTITY_ID", "ENTITY_ID")


def get_sms_dlr_auth_token(client: str = "bajaj") -> str:
    """
    Return the expected static token for DLR Webhook Authorization.

    Headers received from Karix: 'Authorization: Basic <Static Token>'
    """
    return _setting(client, "SMS_DLR_AUTH_TOKEN")


def get_sms_dlr_gcm_key(client: str = "bajaj") -> str:
    """Return AES-GCM decryption key for encrypted DLR callbacks."""
    return _setting(client, "SMS_DLR_GCM_KEY")


def get_sms_dlr_gcm_iv(client: str = "bajaj") -> str:
    """Return AES-GCM IV for encrypted DLR callbacks."""
    return _setting(client, "SMS_DLR_GCM_IV")


def get_sms_auth_headers(client: str = "bajaj") -> dict[str, str]:
    """
    Generate HTTP headers for Karix SMS API call.

    If username and key are present, generates Basic Auth header.
    Otherwise, standard Content-Type application/json header is returned.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    username = get_sms_username(client)
    key = get_sms_key(client)
    if username and key:
        token = base64.b64encode(f"{username}:{key}".encode()).decode("utf-8")
        headers["Authorization"] = f"Basic {token}"
    return headers
