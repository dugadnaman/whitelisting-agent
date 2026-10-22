"""Encrypted, account/integration-scoped credentials; never exported to env or Git."""

import base64
import hashlib
import hmac
import json
import re
import time

from cryptography.fernet import Fernet, InvalidToken


def _cipher() -> Fernet:
    from auth import configured_jwt_secret

    key = hmac.new(configured_jwt_secret().encode(), b"karix/portal-sessions/v1", hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _scope(account: str, integration: str) -> tuple[str, str]:
    if not isinstance(account, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", account):
        raise ValueError("An explicit account key is required")
    if integration not in {"whatsapp", "rcs", "moengage", "sms", "gemini"}:
        raise ValueError("Unknown credential integration")
    return account, integration


def session_record(account: str, integration: str = "whatsapp") -> dict | None:
    from db import get_db, init_database

    scope = _scope(account, integration)
    with get_db() as conn:
        init_database(conn)
        row = conn.execute(
            "SELECT * FROM karix_scoped_credentials WHERE account = ? AND integration = ? AND kind = 'session'", scope,
        ).fetchone()
        return dict(row) if row else None


def _decrypt(record: dict, account: str, integration: str, kind: str) -> dict[str, str]:
    try:
        decoded = json.loads(_cipher().decrypt(record["encrypted_credentials"].encode()))
        # Scope inside the ciphertext prevents swapping database rows across tenants.
        if decoded.get("scope") != [account, integration, kind] or not isinstance(decoded.get("values"), dict):
            raise ValueError("Credential scope mismatch")
        values = decoded["values"]
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in values.items()):
            raise ValueError("Invalid credential mapping")
        return values
    except (InvalidToken, ValueError, TypeError, AttributeError, KeyError) as exc:
        raise OSError(f"Saved {integration} credentials for {account} cannot be decrypted. Reconfigure this integration.") from exc


def load_session(account: str, integration: str = "whatsapp") -> dict[str, str] | None:
    record = session_record(account, integration)
    return _decrypt(record, account, integration, "session") if record else None


def _save(values: dict[str, str], account: str, integration: str, kind: str, *, invalidate_session: bool = False) -> float:
    from db import get_db, init_database

    _scope(account, integration)
    if not isinstance(values, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in values.items()):
        raise ValueError("Credentials must be a string mapping")
    encrypted = _cipher().encrypt(json.dumps({"scope": [account, integration, kind], "values": values}, separators=(",", ":")).encode()).decode()
    now = time.time()
    with get_db() as conn:
        init_database(conn)
        conn.execute(
            "INSERT INTO karix_scoped_credentials (account, integration, kind, encrypted_credentials, updated_at, validated_at, validation_state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(account, integration, kind) DO UPDATE SET "
            "encrypted_credentials = excluded.encrypted_credentials, updated_at = excluded.updated_at, "
            "validated_at = excluded.validated_at, validation_state = excluded.validation_state",
            (account, integration, kind, encrypted, now, now if kind == "session" else None, "valid" if kind == "session" else "never"),
        )
        if invalidate_session:
            conn.execute(
                "DELETE FROM karix_scoped_credentials WHERE account = ? AND integration = ? AND kind = 'session'",
                (account, integration),
            )
    return now


def save_session(credentials: dict[str, str], account: str, integration: str = "whatsapp") -> float:
    return _save(credentials, account, integration, "session")


def load_settings(account: str, integration: str) -> dict[str, str]:
    from db import get_db, init_database

    scope = _scope(account, integration)
    with get_db() as conn:
        init_database(conn)
        row = conn.execute(
            "SELECT * FROM karix_scoped_credentials WHERE account = ? AND integration = ? AND kind = 'settings'", scope,
        ).fetchone()
    return _decrypt(dict(row), account, integration, "settings") if row else {}


def save_settings(account: str, integration: str, mapping: dict[str, str]) -> float:
    current = load_settings(account, integration)
    prefix = account.upper()
    expected: dict[str, str] = {}
    if integration == "whatsapp":
        from config import get_waba_id, get_esmeaddr
        for suffix, getter in (("WABA_ID", get_waba_id), ("ESMEADDR", get_esmeaddr)):
            try:
                expected[f"{prefix}_{suffix}"] = getter(account)
            except OSError:
                pass
    elif integration == "rcs":
        from rcs_config import get_rcs_bot_id, get_rcs_bot_ids, get_rcs_esmeaddr
        for suffix, getter in (("BOT_ID", get_rcs_bot_id), ("ESMEADDR", get_rcs_esmeaddr)):
            try:
                expected[f"{prefix}_RCS_{suffix}"] = getter(account)
            except OSError:
                pass
        expected[f"{prefix}_RCS_BOT_IDS"] = ",".join(get_rcs_bot_ids(account))
    elif integration == "moengage":
        import os
        expected = {
            key: current.get(key, os.environ.get(key, ""))
            for key in (f"{prefix}_MOENGAGE_BASE_URL", f"{prefix}_MOENGAGE_WORKSPACE_ID")
        }
    changed = any(
        key in mapping and mapping[key].strip().rstrip("/") != value.strip().rstrip("/")
        for key, value in expected.items()
    )
    return _save({**current, **mapping}, account, integration, "settings", invalidate_session=changed)


def record_validation(valid: bool, expected_updated_at: float, account: str, integration: str = "whatsapp") -> None:
    from db import get_db

    _scope(account, integration)
    with get_db() as conn:
        conn.execute(
            "UPDATE karix_scoped_credentials SET validated_at = ?, validation_state = ? "
            "WHERE account = ? AND integration = ? AND kind = 'session' AND updated_at = ?",
            (time.time(), "valid" if valid else "invalid", account, integration, expected_updated_at),
        )
