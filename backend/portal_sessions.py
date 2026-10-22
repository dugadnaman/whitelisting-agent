"""Encrypted, database-backed Bajaj portal sessions; never exported to env or Git."""

import base64
import hashlib
import hmac
import json
import time

from cryptography.fernet import Fernet, InvalidToken


def _cipher() -> Fernet:
    from auth import configured_jwt_secret

    # Domain-separated key derivation keeps existing deployments zero-config.
    # JWT_SECRET must remain stable; changing it invalidates saved sessions.
    key = hmac.new(configured_jwt_secret().encode(), b"karix/portal-sessions/v1", hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def session_record() -> dict | None:
    from db import get_db, init_database

    with get_db() as conn:
        init_database(conn)
        row = conn.execute("SELECT * FROM karix_portal_sessions WHERE account = ?", ("bajaj",)).fetchone()
        return dict(row) if row else None


def load_session() -> dict[str, str] | None:
    record = session_record()
    if not record:
        return None
    try:
        return json.loads(_cipher().decrypt(record["encrypted_credentials"].encode()))
    except (InvalidToken, ValueError, TypeError) as exc:
        raise OSError("Saved Karix session cannot be decrypted. Reconnect Karix Auth Sync.") from exc


def save_session(credentials: dict[str, str]) -> float:
    from db import get_db, init_database

    encrypted = _cipher().encrypt(json.dumps(credentials, separators=(",", ":")).encode()).decode()
    now = time.time()
    with get_db() as conn:
        init_database(conn)
        conn.execute(
            "INSERT INTO karix_portal_sessions (account, encrypted_credentials, updated_at, validated_at, validation_state) "
            "VALUES (?, ?, ?, ?, 'valid') ON CONFLICT(account) DO UPDATE SET "
            "encrypted_credentials = excluded.encrypted_credentials, updated_at = excluded.updated_at, "
            "validated_at = excluded.validated_at, validation_state = excluded.validation_state",
            ("bajaj", encrypted, now, now),
        )
    return now


def record_validation(valid: bool, expected_updated_at: float) -> None:
    from db import get_db

    with get_db() as conn:
        # An old check must not mark a concurrently renewed session as invalid.
        conn.execute(
            "UPDATE karix_portal_sessions SET validated_at = ?, validation_state = ? "
            "WHERE account = ? AND updated_at = ?",
            (time.time(), "valid" if valid else "invalid", "bajaj", expected_updated_at),
        )
