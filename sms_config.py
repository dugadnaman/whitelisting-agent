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


def get_sms_api_url(client: str = "bajaj") -> str:
    """Return the JSON receiver API endpoint for this account."""
    _load_env_file()
    prefix = _account_prefix(client)
    return os.environ.get(f"{prefix}_SMS_API_URL") or os.environ.get("KARIX_SMS_API_URL") or KARIX_SMS_JSON_URL


def get_sms_key(client: str = "bajaj") -> str:
    """Return the Karix SMS Access Key (Authorization key)."""
    _load_env_file()
    prefix = _account_prefix(client)
    return (
        os.environ.get(f"{prefix}_SMS_KEY")
        or os.environ.get(f"{prefix}_SMS_ACCESS_KEY")
        or os.environ.get("KARIX_SMS_KEY")
        or os.environ.get("KARIX_SMS_ACCESS_KEY")
        or ""
    ).strip()


def get_sms_username(client: str = "bajaj") -> str:
    """Return the SMS account username for Basic HTTP Authorization."""
    _load_env_file()
    prefix = _account_prefix(client)
    return (
        os.environ.get(f"{prefix}_SMS_USERNAME")
        or os.environ.get(f"{prefix}_SMS_USER")
        or os.environ.get("KARIX_SMS_USERNAME")
        or os.environ.get("KARIX_SMS_USER")
        or ""
    ).strip()


def get_sms_encryption_key(client: str = "bajaj") -> str:
    """
    Return the Base64-encoded AES-256 encryption key/password for PII encryption.

    Used when encrpt='1' in Send SMS API calls.
    """
    _load_env_file()
    prefix = _account_prefix(client)
    return (
        os.environ.get(f"{prefix}_SMS_ENCRYPTION_KEY")
        or os.environ.get("KARIX_SMS_ENCRYPTION_KEY")
        or ""
    ).strip()


def get_sms_sender_id(client: str = "bajaj") -> str:
    """Return the registered DLT sender ID / header name for this account."""
    _load_env_file()
    prefix = _account_prefix(client)
    default = BAJAJ_SMS_DEFAULT_SENDER_ID if client.lower() == "bajaj" else TATA_SMS_DEFAULT_SENDER_ID
    return (
        os.environ.get(f"{prefix}_SMS_SENDER_ID")
        or os.environ.get(f"{prefix}_SENDER_ID")
        or os.environ.get("KARIX_SMS_SENDER_ID")
        or default
    ).strip()


def get_sms_dlt_entity_id(client: str = "bajaj") -> str:
    """Return the DLT Entity ID for this client."""
    _load_env_file()
    prefix = _account_prefix(client)
    return (
        os.environ.get(f"{prefix}_SMS_ENTITY_ID")
        or os.environ.get(f"{prefix}_DLT_ENTITY_ID")
        or os.environ.get(f"{prefix}_ENTITY_ID")
        or os.environ.get("KARIX_SMS_ENTITY_ID")
        or os.environ.get("KARIX_DLT_ENTITY_ID")
        or ""
    ).strip()


def get_sms_dlr_auth_token(client: str = "bajaj") -> str:
    """
    Return the expected static token for DLR Webhook Authorization.

    Headers received from Karix: 'Authorization: Basic <Static Token>'
    """
    _load_env_file()
    prefix = _account_prefix(client)
    return (
        os.environ.get(f"{prefix}_SMS_DLR_AUTH_TOKEN")
        or os.environ.get("KARIX_SMS_DLR_AUTH_TOKEN")
        or ""
    ).strip()


def get_sms_dlr_gcm_key(client: str = "bajaj") -> str:
    """Return AES-GCM decryption key for encrypted DLR callbacks."""
    _load_env_file()
    prefix = _account_prefix(client)
    return (
        os.environ.get(f"{prefix}_SMS_DLR_GCM_KEY")
        or os.environ.get("KARIX_SMS_DLR_GCM_KEY")
        or ""
    ).strip()


def get_sms_dlr_gcm_iv(client: str = "bajaj") -> str:
    """Return AES-GCM IV for encrypted DLR callbacks."""
    _load_env_file()
    prefix = _account_prefix(client)
    return (
        os.environ.get(f"{prefix}_SMS_DLR_GCM_IV")
        or os.environ.get("KARIX_SMS_DLR_GCM_IV")
        or ""
    ).strip()


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
