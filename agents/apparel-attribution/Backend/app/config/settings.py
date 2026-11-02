"""Private, single-process Apparel worker configuration and durable admin setup."""
from __future__ import annotations

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



def validate_ui_config(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {"workspace_map", "agipl_attribution_brand_values"}:
        raise ValueError("Configure only Apparel workspace_map and agipl_attribution_brand_values")
    mapping = value.get("workspace_map")
    if not isinstance(mapping, dict) or not mapping or len(mapping) > 50:
        raise ValueError("workspace_map must contain the supported Apparel brands")
    for name, entries in value.items():
        if not isinstance(entries, dict) or any(
            not isinstance(key, str) or not key.strip() or len(key) > 120
            or not isinstance(item, str) or not item.strip() or len(item) > 120
            for key, item in entries.items()
        ):
            raise ValueError(f"{name} must map brand names to nonempty strings")
        if len({key.casefold() for key in entries}) != len(entries):
            raise ValueError(f"{name} contains duplicate brand names")
    return value



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
    app_name: str = "Apparel Attribution"
    api_prefix: str = "/api"
    storage_dir: Path = Path("data/apparel-attribution")
    machine_token: str = field(default="", repr=False)
    moengage_query_timeout_seconds: float = 180.0
    moengage_ui_config: dict[str, Any] = field(default_factory=lambda: {
        key: dict(value) for key, value in DEFAULT_UI_CONFIG.items()
    })
    google_service_account_file: Path = Path("data/apparel-attribution/google-service-account.json")
    google_service_account_json: str = field(default="", repr=False)
    sealed_google_credentials: bool = False
    google_spreadsheet_url: str = ""
    google_worksheet_name: str = "Mastersheet"

    @property
    def setup_path(self) -> Path:
        return self.storage_dir / "setup.json"

    @classmethod
    def from_env(cls) -> "Settings":
        directory = Path(os.getenv("APPAREL_ATTRIBUTION_STORAGE_DIR") or (
            Path(os.getenv("KARIX_DB_PATH", "data/karix_store.db")).parent / "apparel-attribution"
        ))
        credential_file = os.getenv("APPAREL_GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
        credential_json = os.getenv("APPAREL_GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        result = cls(
            storage_dir=directory,
            moengage_query_timeout_seconds=float(os.getenv("APPAREL_MOENGAGE_QUERY_TIMEOUT_SECONDS", "180")),
            google_service_account_file=Path(credential_file) if credential_file else directory / "google-service-account.json",
            google_service_account_json=credential_json,
            sealed_google_credentials=bool(credential_file or credential_json),
            google_spreadsheet_url=os.getenv("APPAREL_GOOGLE_SPREADSHEET_URL", "").strip() or DEFAULT_SPREADSHEET_URL,
            google_worksheet_name=os.getenv("APPAREL_GOOGLE_WORKSHEET_NAME", "").strip() or "Mastersheet",
        )
        if result.setup_path.exists():
            persisted = json.loads(result.setup_path.read_text(encoding="utf-8"))
            result.google_spreadsheet_url = persisted["spreadsheet_url"]
            result.google_worksheet_name = persisted["worksheet_name"]
            # One-time data cutover: retain brand mappings, not obsolete browser selectors/workflows.
            result.moengage_ui_config = {
                name: value for name, value in persisted["ui_config"].items()
                if name in DEFAULT_UI_CONFIG
            }
        spreadsheet_identity(result.google_spreadsheet_url)
        if not result.google_worksheet_name or len(result.google_worksheet_name) > 100:
            raise ValueError("Choose an Apparel worksheet title of at most 100 characters")
        if not 1 <= result.moengage_query_timeout_seconds <= 3600:
            raise ValueError("APPAREL_MOENGAGE_QUERY_TIMEOUT_SECONDS must be between 1 and 3600")
        validate_ui_config(result.moengage_ui_config)
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
