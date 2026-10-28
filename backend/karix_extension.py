"""Account-scoped browser Auth Sync with immutable, revocable device capabilities."""

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
from config import _esmeaddr_from_session_token, get_esmeaddr, get_waba_id
from db import get_db, init_database
from portal_sessions import load_session, load_settings, record_validation, save_session, session_record

router = APIRouter(prefix="/api/karix-extension", tags=["Karix Auth Sync"])
PAIRING_SECONDS = 300
DEVICE_SECONDS = 90 * 24 * 3600
ASSET_DIR = Path(__file__).resolve().parent.parent / "browser-extension" / "karix-auth-sync"
DEFAULT_ORIGINS = {"https://whitelisting-agent.onrender.com", "http://localhost:3000", "http://127.0.0.1:3000"}
Integration = Literal["whatsapp", "rcs", "moengage"]


class OriginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_origin: str = Field(max_length=300)


class PairingRequest(OriginRequest):
    account: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    integration: Integration


class RedeemRequest(OriginRequest):
    code: str = Field(min_length=32, max_length=200)


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    integration: Integration
    bearer_token: str = Field(min_length=1, max_length=16000)
    session: str | None = Field(default=None, min_length=1, max_length=1000)
    user: str | None = Field(default=None, min_length=1, max_length=300)
    waba_id: str | None = Field(default=None, max_length=100)
    esmeaddr: str | None = Field(default=None, max_length=100)
    bot_id: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=300)
    workspace_id: str | None = Field(default=None, max_length=128)
    refresh_token: str | None = Field(default=None, max_length=16000)
    cookie: str | None = Field(default=None, max_length=32000)

    @field_validator("bearer_token", "session", "user", "refresh_token", "cookie", "waba_id", "esmeaddr", "bot_id", "base_url", "workspace_id")
    @classmethod
    def clean_header(cls, value: str | None) -> str | None:
        if value is None:
            return None
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
        raise HTTPException(status_code=403, detail="This agent origin is not approved for Auth Sync. Configure KARIX_EXTENSION_AGENT_ORIGINS.")
    return origin


def _known_accounts() -> set[str]:
    from api import load_accounts
    from config import DEFAULT_WABA_IDS, DEFAULT_ESMEADDRS
    from rcs_config import DEFAULT_RCS_BOT_IDS

    return {row["id"] for row in load_accounts()} | set(DEFAULT_WABA_IDS) | set(DEFAULT_ESMEADDRS) | set(DEFAULT_RCS_BOT_IDS)


def _authorize(account: str, user: dict) -> None:
    require_tenant_access(account, user)
    if account not in _known_accounts():
        raise HTTPException(status_code=404, detail="Unknown configured account.")


def target_identity(account: str, integration: str) -> dict:
    """Only server-owned settings/defaults establish identity; never captured credentials."""
    if integration == "whatsapp":
        return {"waba_id": get_waba_id(account), "esmeaddr": get_esmeaddr(account)}
    if integration == "rcs":
        from rcs_config import get_rcs_bot_ids, get_rcs_esmeaddr
        bots = get_rcs_bot_ids(account)
        if not bots:
            raise OSError("Configure this account's RCS bot IDs in Settings.")
        return {"bot_ids": bots, "esmeaddr": get_rcs_esmeaddr(account)}
    if integration == "moengage":
        # Identity must be available even when an old session is undecryptable.
        prefix = account.upper() + "_MOENGAGE_"
        settings = load_settings(account, "moengage")
        base = settings.get(prefix + "BASE_URL", os.environ.get(prefix + "BASE_URL", "")).rstrip("/")
        workspace = settings.get(prefix + "WORKSPACE_ID", os.environ.get(prefix + "WORKSPACE_ID", ""))
        if not re.fullmatch(r"https://dashboard(?:-\d+)?\.moengage\.com", base) or not re.fullmatch(r"[A-Za-z0-9]{24}", workspace):
            raise OSError("Configure this account's exact MoEngage dashboard origin and 24-character alphanumeric dashboard workspace ID first.")
        return {"base_url": base, "workspace_id": workspace}
    raise OSError("This integration uses static credentials, not browser sessions.")


def _browser_identity(account: str, integration: str) -> dict:
    try:
        return target_identity(account, integration)
    except OSError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


def _device_user(authorization: str | None) -> tuple[dict, dict]:
    if not authorization or not authorization.startswith("Bearer kxs_") or len(authorization) > 300:
        raise HTTPException(status_code=401, detail="Reconnect Auth Sync in Settings.")
    digest = _hash(authorization[7:])
    with get_db() as conn:
        init_database(conn)
        row = conn.execute(
            "SELECT * FROM karix_extension_links WHERE credential_hash = ? AND kind = 'device' AND expires_at > ?",
            (digest, time.time()),
        ).fetchone()
    link = dict(row) if row else None
    user = get_user_profile(link["user_id"]) if link else None
    if not user:
        raise HTTPException(status_code=401, detail="Extension pairing expired or was disconnected. Reconnect in Settings.")
    _authorize(link["account"], user)  # Reload the real active user on every request.
    return user, link


def validate_session(body: SessionRequest, *, bind_workspace: bool = True) -> dict[str, str]:
    """Validate an unsaved exact snapshot; failure never changes stored credentials."""
    identity = _browser_identity(body.account, body.integration)
    bearer = re.sub(r"^(?:Authorization\s*:\s*)?Bearer\s+", "", body.bearer_token, flags=re.IGNORECASE).strip()
    if not bearer:
        raise HTTPException(status_code=422, detail="A portal bearer token is required.")
    for field in ("waba_id", "esmeaddr", "base_url", "workspace_id"):
        observed = getattr(body, field)
        if observed is not None and (field not in identity or observed != identity[field]):
            raise HTTPException(status_code=409, detail=f"Observed {field} does not match this configured account/integration.")
    snapshot = {"bearer_token": bearer}
    if body.integration in ("whatsapp", "rcs"):
        decoded_esme = _esmeaddr_from_session_token(bearer)
        if decoded_esme is not None and decoded_esme != identity["esmeaddr"]:
            raise HTTPException(status_code=409, detail="This Karix token belongs to another configured account/integration.")
        if body.session:
            snapshot["session"] = body.session
        if body.user:
            snapshot["user"] = body.user
        if body.integration == "whatsapp":
            if not body.session or not body.user:
                raise HTTPException(status_code=422, detail={"code": "incomplete_session", "integration": body.integration})
            if body.bot_id is not None:
                raise HTTPException(status_code=409, detail="An RCS bot cannot identify a WhatsApp session.")
            from submission_client import check_portal_credentials
            valid, _ = check_portal_credentials(
                body.account, bearer_token=bearer, session_id=body.session, portal_user=body.user,
                waba_id=identity["waba_id"], esmeaddr=identity["esmeaddr"],
            )
        else:
            bot = body.bot_id or (identity["bot_ids"][0] if identity.get("bot_ids") else None)
            if not bot or bot not in identity["bot_ids"]:
                raise HTTPException(status_code=409, detail="Observed RCS bot is not configured for this account.")
            from rcs_client import check_rcs_credentials
            valid, _ = check_rcs_credentials(
                body.account, bearer_token=bearer, session_id=body.session, portal_user=body.user,
                bot_id=bot, esmeaddr=identity["esmeaddr"],
            )
            snapshot["bot_id"] = bot
    else:
        if not body.refresh_token or not body.cookie:
            raise HTTPException(status_code=422, detail={"code": "incomplete_session", "integration": body.integration})
        from moengage_sync import check_moengage_session
        try:
            snapshot = check_moengage_session(
                body.account, bearer_token=bearer, refresh_token=body.refresh_token, cookie=body.cookie,
                base_url=identity["base_url"], workspace_id=identity["workspace_id"],
                bind_workspace=bind_workspace,
            )
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail={"code": "provider_validation_failed", "integration": body.integration}) from None
        valid = True
    if not valid:
        raise HTTPException(status_code=422, detail={"code": "provider_validation_failed", "integration": body.integration})
    snapshot.update({key: value for key, value in identity.items() if isinstance(value, str)})
    return snapshot


def _status(user: dict, account: str, integration: str) -> dict:
    with get_db() as conn:
        init_database(conn)
        paired = conn.execute(
            "SELECT 1 FROM karix_extension_links WHERE user_id = ? AND account = ? AND integration = ? AND kind = 'device' AND expires_at > ? LIMIT 1",
            (user["id"], account, integration, time.time()),
        ).fetchone() is not None
    record = session_record(account, integration)
    state = record["validation_state"] if record else "never"
    return {
        "paired": paired, "account": account, "integration": integration,
        "last_synced_at": record["updated_at"] if record else None,
        "last_validated_at": record["validated_at"] if record else None,
        "validation_state": state,
        "message": (
            "Session was accepted at the last validation; use Check session to verify it now." if state == "valid"
            else "Session could not be validated. Log into this integration and open its read-only inventory to reconnect." if state == "invalid"
            else "Complete normal human login (including mobile OTP), then open this integration's inventory to sync."
        ),
    }


@router.get("/targets")
def extension_targets(response: Response, account: str | None = None, user: dict = Depends(get_current_user)):
    known = _known_accounts()
    if account is not None:
        _authorize(account, user)
        known = {account}
    targets = []
    for selected in sorted(known):
        try:
            require_tenant_access(selected, user)
        except HTTPException:
            continue
        for integration in ("whatsapp", "rcs", "moengage", "sms"):
            if integration == "sms":
                mode, identity = "static", {}
                message = "SMS API/encryption keys are one-time persistent Settings setup; browser login cannot generate them."
            else:
                try:
                    identity = target_identity(selected, integration)
                    mode, message = "browser", "Human login remains required; Auth Sync renews only this configured account/integration's session."
                except OSError as exc:
                    mode, identity, message = "setup_required", {}, str(exc)
            targets.append({"account": selected, "integration": integration, "mode": mode, "identity": identity, "message": message})
    response.headers["Cache-Control"] = "no-store"
    return {"targets": targets}


@router.post("/pairing")
def create_pairing(body: PairingRequest, response: Response, user: dict = Depends(get_current_user)):
    _authorize(body.account, user)
    _browser_identity(body.account, body.integration)
    origin = _approved_origin(body.agent_origin)
    from portal_sessions import _cipher
    _cipher()
    code, expires = secrets.token_urlsafe(32), time.time() + PAIRING_SECONDS
    with get_db() as conn:
        init_database(conn)
        conn.execute(
            "DELETE FROM karix_extension_links WHERE expires_at <= ? OR (user_id = ? AND account = ? AND integration = ? AND kind = 'pairing')",
            (time.time(), user["id"], body.account, body.integration),
        )
        conn.execute(
            "INSERT INTO karix_extension_links (credential_hash, kind, user_id, agent_origin, expires_at, account, integration) VALUES (?, 'pairing', ?, ?, ?, ?, ?)",
            (_hash(code), user["id"], origin, expires, body.account, body.integration),
        )
    response.headers["Cache-Control"] = "no-store"
    return {"code": code, "expires_at": expires, "account": body.account, "integration": body.integration}


@router.post("/redeem")
def redeem_pairing(body: RedeemRequest, response: Response):
    origin, now = _approved_origin(body.agent_origin), time.time()
    token, expires = "kxs_" + secrets.token_urlsafe(32), now + DEVICE_SECONDS
    with get_db() as conn:
        init_database(conn)
        if not conn.is_postgres:
            conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM karix_extension_links WHERE credential_hash = ? AND kind = 'pairing' AND agent_origin = ? AND expires_at > ?",
            (_hash(body.code), origin, now),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Pairing code expired or already used. Click Connect extension again.")
        user = get_user_profile(row["user_id"])
        if not user:
            raise HTTPException(status_code=401, detail="Your agent account is no longer active.")
        _authorize(row["account"], user)
        identity = _browser_identity(row["account"], row["integration"])
        changed = conn.execute(
            "UPDATE karix_extension_links SET credential_hash = ?, kind = 'device', expires_at = ? WHERE credential_hash = ? AND kind = 'pairing' AND expires_at > ?",
            (_hash(token), expires, _hash(body.code), now),
        )
        if changed.rowcount != 1:
            raise HTTPException(status_code=401, detail="Pairing code already used. Connect again.")
        account, integration = row["account"], row["integration"]
    response.headers["Cache-Control"] = "no-store"
    return {"device_token": token, "expires_at": expires, "account": account, "integration": integration, "identity": identity}


@router.post("/sync")
def sync_session(body: SessionRequest, response: Response, authorization: str | None = Header(None)):
    _, link = _device_user(authorization)
    if (body.account, body.integration) != (link["account"], link["integration"]):
        raise HTTPException(status_code=403, detail="This device cannot publish outside its paired account/integration.")
    identity = _browser_identity(body.account, body.integration)
    credentials = validate_session(body)
    _device_user(authorization)  # Revocation during provider validation cannot publish.
    if _browser_identity(body.account, body.integration) != identity:
        raise HTTPException(status_code=409, detail="Configured identity changed during validation. Reconnect this exact target.")
    synced_at = save_session(credentials, body.account, body.integration)
    from queue_manager import QUEUE_MANAGER
    QUEUE_MANAGER.notify_credentials_updated(body.account)
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True, "last_synced_at": synced_at, "account": body.account, "integration": body.integration}


@router.get("/status")
def extension_status(response: Response, account: str, integration: Integration, user: dict = Depends(get_current_user)):
    _authorize(account, user)
    response.headers["Cache-Control"] = "no-store"
    return _status(user, account, integration)


@router.post("/check")
def check_session(response: Response, account: str, integration: Integration, user: dict = Depends(get_current_user)):
    _authorize(account, user)
    record = session_record(account, integration)
    if record:
        try:
            saved = load_session(account, integration)
            validate_session(SessionRequest(account=account, integration=integration, **saved), bind_workspace=False)
            valid = True
        except (HTTPException, OSError, ValueError):
            valid = False
        record_validation(valid, record["updated_at"], account, integration)
    response.headers["Cache-Control"] = "no-store"
    return _status(user, account, integration)


@router.delete("/pairing")
def disconnect_pairings(account: str, integration: Integration, user: dict = Depends(get_current_user)):
    _authorize(account, user)
    with get_db() as conn:
        init_database(conn)
        conn.execute("DELETE FROM karix_extension_links WHERE user_id = ? AND account = ? AND integration = ?", (user["id"], account, integration))
    return {"ok": True, "account": account, "integration": integration}


@router.delete("/device")
def disconnect_device(account: str, integration: Integration, authorization: str | None = Header(None)):
    _, link = _device_user(authorization)
    if (account, integration) != (link["account"], link["integration"]):
        raise HTTPException(status_code=403, detail="This device can disconnect only its paired scope.")
    with get_db() as conn:
        conn.execute("DELETE FROM karix_extension_links WHERE credential_hash = ?", (link["credential_hash"],))
    return {"ok": True, "account": account, "integration": integration}


@router.post("/download")
def download_extension(body: OriginRequest, user: dict = Depends(get_current_user)):
    if user.get("tenant_id") in (None, "", "unassigned"):
        raise HTTPException(status_code=403, detail="Organization access has not been approved.")
    origin = _approved_origin(body.agent_origin)
    manifest = json.loads((ASSET_DIR / "manifest.json").read_text())
    agent_matches = {match for script in manifest["content_scripts"] for match in script["matches"]}
    manifest["host_permissions"] = [
        permission for permission in manifest["host_permissions"] if permission not in agent_matches
    ] + [origin + "/*"]
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
