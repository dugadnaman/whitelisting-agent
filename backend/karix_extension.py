"""Bajaj-only Chrome extension pairing, scoped device access and session sync."""

import hashlib
import io
import json
import os
import re
import secrets
import time
import zipfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from auth import get_current_user, get_user_profile, require_tenant_access
from config import BAJAJ_ESMEADDR, BAJAJ_WABA_ID, _esmeaddr_from_session_token
from db import get_db, init_database
from portal_sessions import load_session, record_validation, save_session, session_record

router = APIRouter(prefix="/api/karix-extension", tags=["Karix Auth Sync"])
PAIRING_SECONDS = 300
DEVICE_SECONDS = 90 * 24 * 3600
ASSET_DIR = Path(__file__).resolve().parent.parent / "browser-extension" / "karix-auth-sync"
DEFAULT_ORIGINS = {"https://whitelisting-agent.onrender.com", "http://localhost:3000", "http://127.0.0.1:3000"}


class OriginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_origin: str = Field(max_length=300)


class RedeemRequest(OriginRequest):
    code: str = Field(min_length=32, max_length=200)


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bearer_token: str = Field(min_length=1, max_length=16000)
    session: str = Field(min_length=1, max_length=1000)
    user: str = Field(min_length=1, max_length=300)
    waba_id: Literal["286109054585247"]
    esmeaddr: Literal["72148300000000"]

    @field_validator("bearer_token", "session", "user")
    @classmethod
    def clean_header(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Invalid header characters")
        value = value.strip()
        if not value:
            raise ValueError("A complete portal session is required")
        return value


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _approved_origin(origin: str) -> str:
    try:
        parsed = urlsplit(origin)
        local = parsed.hostname in ("localhost", "127.0.0.1")
    except ValueError:
        raise HTTPException(status_code=400, detail="An exact agent origin is required.") from None
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or not parsed.netloc:
        raise HTTPException(status_code=400, detail="An exact agent origin is required.")
    if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
        raise HTTPException(status_code=400, detail="Agent origins require HTTPS (except loopback development).")
    configured = os.environ.get("KARIX_EXTENSION_AGENT_ORIGINS") or os.environ.get("ALLOWED_ORIGINS", "")
    allowed = DEFAULT_ORIGINS | {value.strip().rstrip("/") for value in configured.split(",") if value.strip()}
    if origin not in allowed:
        raise HTTPException(status_code=403, detail="This agent origin is not approved for Karix Auth Sync. Configure KARIX_EXTENSION_AGENT_ORIGINS.")
    return origin


def _bajaj_user(user: dict) -> dict:
    require_tenant_access("bajaj", user)
    return user


def _device_user(authorization: str | None) -> tuple[dict, str]:
    if not authorization or not authorization.startswith("Bearer kxs_") or len(authorization) > 300:
        raise HTTPException(status_code=401, detail="Reconnect Karix Auth Sync in Settings.")
    digest = _hash(authorization[7:])
    with get_db() as conn:
        init_database(conn)
        row = conn.execute(
            "SELECT user_id FROM karix_extension_links WHERE credential_hash = ? AND kind = 'device' AND expires_at > ?",
            (digest, time.time()),
        ).fetchone()
    user = get_user_profile(row["user_id"]) if row else None
    if not user:
        raise HTTPException(status_code=401, detail="Extension pairing expired or was disconnected. Reconnect in Settings.")
    _bajaj_user(user)  # Reload active tenant/role on every request, never trust saved claims.
    return user, digest

def validate_session(body: SessionRequest) -> dict[str, str]:
    bearer = re.sub(r"^(?:Authorization\s*:\s*)?Bearer\s+", "", body.bearer_token, flags=re.IGNORECASE)
    # Decode only to reject a wrong account; Karix verifies the actual signature.
    if _esmeaddr_from_session_token(bearer) != BAJAJ_ESMEADDR:
        raise HTTPException(status_code=409, detail="This portal session is not a recognizable Bajaj session. Log into the Bajaj Karix account.")
    from submission_client import check_portal_credentials
    valid, _ = check_portal_credentials(
        "bajaj", bearer_token=bearer, session_id=body.session, portal_user=body.user,
        waba_id=BAJAJ_WABA_ID, esmeaddr=BAJAJ_ESMEADDR,
    )
    if not valid:
        raise HTTPException(status_code=422, detail="Karix did not validate this Bajaj session. Log in again and open the WhatsApp template list.")
    return {"bearer_token": bearer, "session": body.session, "user": body.user}


def _status(user: dict) -> dict:
    with get_db() as conn:
        init_database(conn)
        paired = conn.execute(
            "SELECT 1 FROM karix_extension_links WHERE user_id = ? AND kind = 'device' AND expires_at > ? LIMIT 1",
            (user["id"], time.time()),
        ).fetchone() is not None
    record = session_record()
    state = record["validation_state"] if record else "never"
    return {
        "paired": paired,
        "last_synced_at": record["updated_at"] if record else None,
        "last_validated_at": record["validated_at"] if record else None,
        "validation_state": state,
        "message": (
            "Session was accepted at the last validation; use Check session to verify it now." if state == "valid"
            else "Session could not be validated. Log into Bajaj Karix with your mobile OTP and open the WhatsApp template list." if state == "invalid"
            else "Log into Bajaj Karix with your mobile OTP and open the WhatsApp template list to sync."
        ),
    }


@router.post("/pairing")
def create_pairing(body: OriginRequest, response: Response, user: dict = Depends(get_current_user)):
    _bajaj_user(user)
    origin = _approved_origin(body.agent_origin)
    # Ensure the configured key is usable before issuing an install/pairing flow.
    from portal_sessions import _cipher
    _cipher()
    code, expires = secrets.token_urlsafe(32), time.time() + PAIRING_SECONDS
    with get_db() as conn:
        init_database(conn)
        conn.execute("DELETE FROM karix_extension_links WHERE expires_at <= ? OR (user_id = ? AND kind = 'pairing')", (time.time(), user["id"]))
        conn.execute(
            "INSERT INTO karix_extension_links (credential_hash, kind, user_id, agent_origin, expires_at) VALUES (?, 'pairing', ?, ?, ?)",
            (_hash(code), user["id"], origin, expires),
        )
    response.headers["Cache-Control"] = "no-store"
    return {"code": code, "expires_at": expires}


@router.post("/redeem")
def redeem_pairing(body: RedeemRequest, response: Response):
    origin, now = _approved_origin(body.agent_origin), time.time()
    token, expires = "kxs_" + secrets.token_urlsafe(32), now + DEVICE_SECONDS
    with get_db() as conn:
        init_database(conn)
        if not conn.is_postgres:
            conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT user_id FROM karix_extension_links WHERE credential_hash = ? AND kind = 'pairing' AND agent_origin = ? AND expires_at > ?",
            (_hash(body.code), origin, now),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Pairing code expired or already used. Click Connect extension again.")
        user = get_user_profile(row["user_id"])
        if not user:
            raise HTTPException(status_code=401, detail="Your agent account is no longer active.")
        _bajaj_user(user)
        # Compare-and-swap guarantees single use even with concurrent redemption.
        changed = conn.execute(
            "UPDATE karix_extension_links SET credential_hash = ?, kind = 'device', expires_at = ? "
            "WHERE credential_hash = ? AND kind = 'pairing' AND expires_at > ?",
            (_hash(token), expires, _hash(body.code), now),
        )
        if changed.rowcount != 1:
            raise HTTPException(status_code=401, detail="Pairing code already used. Connect again.")
    response.headers["Cache-Control"] = "no-store"
    return {"device_token": token, "expires_at": expires, "account": "bajaj"}


@router.post("/sync")
def sync_session(body: SessionRequest, response: Response, authorization: str | None = Header(None)):
    _device_user(authorization)
    credentials = validate_session(body)
    _device_user(authorization)  # A device revoked during validation cannot publish credentials.
    synced_at = save_session(credentials)
    from queue_manager import QUEUE_MANAGER
    QUEUE_MANAGER.notify_credentials_updated("bajaj")
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True, "last_synced_at": synced_at, "account": "bajaj"}


@router.get("/status")
def extension_status(response: Response, user: dict = Depends(get_current_user)):
    _bajaj_user(user)
    response.headers["Cache-Control"] = "no-store"
    return _status(user)


@router.post("/check")
def check_session(response: Response, user: dict = Depends(get_current_user)):
    _bajaj_user(user)
    record = session_record()
    if record:
        from submission_client import check_portal_credentials
        try:
            saved = load_session()
            valid, _ = check_portal_credentials(
                "bajaj", bearer_token=saved["bearer_token"], session_id=saved["session"], portal_user=saved["user"],
                waba_id=BAJAJ_WABA_ID, esmeaddr=BAJAJ_ESMEADDR,
            )
        except OSError:
            valid = False
        record_validation(valid, record["updated_at"])
    response.headers["Cache-Control"] = "no-store"
    return _status(user)


@router.delete("/pairing")
def disconnect_pairings(user: dict = Depends(get_current_user)):
    _bajaj_user(user)
    with get_db() as conn:
        init_database(conn)
        conn.execute("DELETE FROM karix_extension_links WHERE user_id = ?", (user["id"],))
    return {"ok": True}


@router.delete("/device")
def disconnect_device(authorization: str | None = Header(None)):
    _, digest = _device_user(authorization)
    with get_db() as conn:
        conn.execute("DELETE FROM karix_extension_links WHERE credential_hash = ?", (digest,))
    return {"ok": True}


@router.post("/download")
def download_extension(body: OriginRequest, user: dict = Depends(get_current_user)):
    _bajaj_user(user)
    origin = _approved_origin(body.agent_origin)
    manifest = json.loads((ASSET_DIR / "manifest.json").read_text())
    manifest["host_permissions"] = ["https://rcsgui.karix.solutions/*", origin + "/*"]
    manifest["content_scripts"][0]["matches"] = [origin + "/*"]
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        for asset in sorted(ASSET_DIR.iterdir()):
            if asset.is_file() and asset.suffix in (".js", ".html", ".css", ".json"):
                content = asset.read_bytes()
                if asset.name == "manifest.json":
                    content = json.dumps(manifest, indent=2).encode()
                elif asset.name == "config.js":
                    content = ("globalThis.KARIX_SYNC_CONFIG = " + json.dumps({"agentOrigin": origin}) + ";\n").encode()
                archive.writestr(asset.name, content)
    return Response(payload.getvalue(), media_type="application/zip", headers={
        "Content-Disposition": 'attachment; filename="karix-auth-sync-extension.zip"', "Cache-Control": "no-store",
    })
