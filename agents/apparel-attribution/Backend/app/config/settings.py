"""Private, single-process Apparel worker configuration and durable admin setup."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.core.local_storage import private_directory, private_file


def strong_token(value: str) -> bool:
    return (
        32 <= len(value) <= 512
        and value.isascii() and all(33 <= ord(char) <= 126 for char in value)
        and len(set(value)) >= 10
        and not re.search(r"change.?me|placeholder|replace.?me|your[-_ ]|example|default", value, re.I)
        and not any(value == (value[:length] * ((len(value) + length - 1) // length))[:len(value)]
                    for length in range(1, len(value) // 2 + 1))
    )
def spreadsheet_identity(value: str) -> str:
    parsed = urlparse(value)
    match = re.fullmatch(r"/spreadsheets/d/([a-zA-Z0-9_-]{20,})(?:/.*)?", parsed.path)
    if (parsed.scheme != "https" or parsed.hostname != "docs.google.com"
            or parsed.username or parsed.password or parsed.port not in (None, 443) or not match):
        raise ValueError("Enter the approved HTTPS docs.google.com/spreadsheets/d/... URL")
    return match.group(1)


def validate_moengage_url(value: str) -> None:
    if not isinstance(value, str):
        raise ValueError("MoEngage URLs must be strings")
    parsed = urlparse(value)
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or not (host == "moengage.com" or host.endswith(".moengage.com"))
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("MoEngage URLs must use HTTPS on a moengage.com host without credentials")


def validate_ui_config(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "workflow", "query_url_map", "query_url", "workspace_map", "workspace_switcher",
        "login_url_contains", "logged_in_selector", "pending_special_workflows",
        "agipl_attribution_brand_values",
    }
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("ui_config contains unsupported settings; API/mock modes and secrets are not supported")
    if not value:
        return {}
    if value.get("workflow") != "recorded_behavior":
        raise ValueError("ui_config.workflow must be recorded_behavior")
    mapping = value.get("query_url_map")
    if not isinstance(mapping, dict) or not mapping or len(mapping) > 50:
        raise ValueError("ui_config.query_url_map must contain the supported brands' report URLs")
    seen = set()
    for brand, url in mapping.items():
        if not isinstance(brand, str) or not brand.strip() or len(brand) > 120 or brand.casefold() in seen:
            raise ValueError("Report brands must be unique, nonempty names")
        seen.add(brand.casefold())
        if not isinstance(url, str) or len(url) > 4096:
            raise ValueError("Report URLs must be strings of at most 4096 characters")
        validate_moengage_url(url)
    if "query_url" in value:
        validate_moengage_url(value["query_url"])
    for name in ("workspace_map", "agipl_attribution_brand_values"):
        if name in value and (not isinstance(value[name], dict) or any(
                not isinstance(key, str) or not isinstance(item, str) or not key.strip() or not item.strip()
                for key, item in value[name].items())):
            raise ValueError(f"ui_config.{name} must map brand names to strings")
    if "pending_special_workflows" in value and (not isinstance(value["pending_special_workflows"], list)
            or any(not isinstance(item, str) for item in value["pending_special_workflows"])):
        raise ValueError("pending_special_workflows must be a list of brand names")
    for name in ("workspace_switcher", "login_url_contains", "logged_in_selector"):
        if name in value and (not isinstance(value[name], str) or len(value[name]) > 4096):
            raise ValueError(f"ui_config.{name} must be a string")
    return value


def validate_private_cdp(value: str) -> None:
    parsed = urlparse(value)
    host = parsed.hostname or ""
    try:
        address = ipaddress.ip_address(host)
        private = (address.is_private or address.is_loopback) and not (
            address.is_unspecified or address.is_multicast or address.is_link_local or address.is_reserved
        )
    except ValueError:
        private = host == "localhost" or host.endswith(".internal") or bool(re.fullmatch(r"[A-Za-z0-9_-]+", host))
    if (parsed.scheme != "http" or not private or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ValueError("MOENGAGE_REMOTE_CDP_URL must be a private HTTP CDP origin; never publish the debugger")

def atomic_private_write(path: Path, content: bytes) -> None:
    private_directory(path.parent)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as destination:
            private_file(temporary)
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


DEFAULT_SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1QTeoRx9gHNDNXmDYRCedTaH-QmTdjFnTOCz0YmQYSOw/edit"
DEFAULT_UI_CONFIG = {
    "workflow": "recorded_behavior",
    "login_url_contains": "/auth/login",
    "logged_in_selector": "text=Create New",
    "query_url_map": {
        "Aldo": "https://dashboard-03.moengage.com/v4/analytics/v2/behavior?did=68d26980ac6269ea10b52cf5&chartId=68d26980cd4fd4ae6272de44",
        "CIS": "https://dashboard-03.moengage.com/v4/analytics/v2/behavior?did=68d26980ac6269ea10b52cf5&chartId=68d26a96a0dba5e79a2bb027",
        "VS": "https://dashboard-03.moengage.com/v4/analytics/v2/behavior?did=6876338ddf61211052d13d3e&chartId=68c7e1c1ec37f0adc738cdb2",
        "BBW": "https://dashboard-03.moengage.com/v4/analytics/v2/behavior?did=68c7f4e9742968d7235d27c0&chartId=68c7f4ead1045fd703a1910a",
        "Crocs": "https://dashboard-03.moengage.com/v4/analytics/v2/behavior?did=68ff2de28fa420e1be3622a2&chartId=68ff2de2ca8d4977c1a254b3",
        "R&B": "https://dashboard-03.moengage.com/v4/analytics/v2/behavior?did=68d2581b5f59d7fc44c4d372&chartId=68d2581ba583bed6d5db11be",
        "CK": "https://dashboard-03.moengage.com/v4/analytics/v2/behavior?did=68c92049d1045fd703a1b568&chartId=68c920494053703a90da7678",
        "AGIPL": "https://dashboard-03.moengage.com/v4/analytics/v2/behavior?did=68d26980ac6269ea10b52cf5&chartId=68d26980cd4fd4ae6272de44",
    },
    "workspace_map": {
        "Aldo": "AL_IN",
        "CIS": "AL_IN",
        "VS": "VS_IN",
        "BBW": "BBW_IN",
        "Crocs": "CROCS_IN",
        "R&B": "RB_IN",
        "CK": "CharlesKeith_IN",
        "AGIPL": "AGIPL_Master_DB",
    },
    "agipl_attribution_brand_values": {
        "Aldo": "AL",
        "VS": "VS",
        "BBW": "BBW",
        "CK": "CK",
        "R&B": "RB",
        "BHPC": "BHPC",
        "Crocs": "CROCS",
        "CIS": "SP",
    },
}

@dataclass
class Settings:
    app_name: str = "Apparel Attribution Worker"
    api_prefix: str = "/api"
    storage_dir: Path = Path("/data")
    machine_token: str = field(default="", repr=False)
    moengage_mode: str = "browser"
    moengage_browser_query_timeout_seconds: float = 180.0
    moengage_max_retries: int = 2
    moengage_dashboard_url: str = "https://dashboard.moengage.com/"
    moengage_remote_cdp_url: str = ""
    moengage_browser_login_url: str = ""
    moengage_ui_config: dict[str, Any] = field(default_factory=dict)
    google_service_account_file: Path = Path("/data/google-service-account.json")
    google_service_account_json: str = field(default="", repr=False)
    sealed_google_credentials: bool = False
    google_spreadsheet_url: str = ""
    google_worksheet_name: str = "Mastersheet"

    @property
    def setup_path(self) -> Path:
        return self.storage_dir / "setup.json"

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.getenv("MOENGAGE_MODE", "browser").strip().lower()
        if mode != "browser" or os.getenv("ALLOW_MOCK_WRITES", "false").lower() not in {"", "0", "false", "no"}:
            raise ValueError("Only genuine browser attribution is supported; remove API/mock settings")
        directory = Path(os.getenv("STORAGE_DIR", "/data"))
        credential_file_env = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
        result = cls(
            storage_dir=directory,
            machine_token=os.getenv("APPAREL_ATTRIBUTION_TOKEN", "").strip(),
            moengage_dashboard_url=os.getenv("MOENGAGE_DASHBOARD_URL", "").strip() or "https://dashboard.moengage.com/",
            moengage_remote_cdp_url=os.getenv("MOENGAGE_REMOTE_CDP_URL", "").strip(),
            moengage_browser_login_url=os.getenv("MOENGAGE_BROWSER_LOGIN_URL", "").strip(),
            moengage_ui_config=json.loads(os.getenv("MOENGAGE_UI_CONFIG_JSON", "").strip() or "{}"),
            moengage_browser_query_timeout_seconds=float(os.getenv("MOENGAGE_BROWSER_QUERY_TIMEOUT_SECONDS", "180")),
            moengage_max_retries=int(os.getenv("MOENGAGE_MAX_RETRIES", "2")),
            google_service_account_file=Path(credential_file_env) if credential_file_env else directory / "google-service-account.json",
            google_service_account_json=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip(),
            sealed_google_credentials=bool(credential_file_env or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()),
            google_spreadsheet_url=os.getenv("GOOGLE_SPREADSHEET_URL", "").strip(),
            google_worksheet_name=os.getenv("GOOGLE_WORKSHEET_NAME", "").strip() or "Mastersheet",
        )
        if result.setup_path.exists():
            try:
                persisted = json.loads(result.setup_path.read_text(encoding="utf-8"))
                result.google_spreadsheet_url = persisted.get("spreadsheet_url") or result.google_spreadsheet_url
                result.google_worksheet_name = persisted.get("worksheet_name") or result.google_worksheet_name
                result.moengage_ui_config = persisted.get("ui_config") or result.moengage_ui_config
            except Exception:
                pass
        if not result.google_spreadsheet_url:
            result.google_spreadsheet_url = DEFAULT_SPREADSHEET_URL
        if not result.moengage_ui_config:
            import copy
            result.moengage_ui_config = copy.deepcopy(DEFAULT_UI_CONFIG)
        if result.google_spreadsheet_url:
            spreadsheet_identity(result.google_spreadsheet_url)
        if not result.google_worksheet_name or len(result.google_worksheet_name) > 100:
            raise ValueError("GOOGLE_WORKSHEET_NAME must be a nonempty worksheet title of at most 100 characters")
        validate_ui_config(result.moengage_ui_config)
        validate_moengage_url(result.moengage_dashboard_url)
        if result.moengage_remote_cdp_url:
            validate_private_cdp(result.moengage_remote_cdp_url)
        if result.moengage_browser_login_url:
            parsed = urlparse(result.moengage_browser_login_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("MOENGAGE_BROWSER_LOGIN_URL must be a protected HTTPS URL without credentials")
        return result

    def persist_setup(self, spreadsheet_url: str, worksheet_name: str, ui_config: dict[str, Any]) -> None:
        spreadsheet_identity(spreadsheet_url)
        if not worksheet_name.strip() or len(worksheet_name) > 100:
            raise ValueError("Choose a nonempty worksheet title of at most 100 characters")
        validate_ui_config(ui_config)
        payload = {"spreadsheet_url": spreadsheet_url, "worksheet_name": worksheet_name, "ui_config": ui_config}
        atomic_private_write(self.setup_path, json.dumps(payload, ensure_ascii=False).encode())
        self.google_spreadsheet_url = spreadsheet_url
        self.google_worksheet_name = worksheet_name
        self.moengage_ui_config = ui_config


settings = Settings.from_env()
