"""
FastAPI backend for the Karix WhatsApp & RCS template whitelisting tool.

Supports multiple accounts (Bajaj, Tata Capital) and multiple channels (WhatsApp, RCS).
Wraps the existing Python pipelines and exposes REST endpoints consumed by the Next.js frontend.
"""

import asyncio
import json
import logging
import os
import re
import tempfile
from dataclasses import asdict
from pathlib import Path

import requests as http_client
from fastapi import Body, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
from activity_tracker import (
    get_activity_summary,
    get_all_users,
    load_activities,
    log_activity,
    register_or_update_user,
)
from auth import (
    TATA_SUB_ACCOUNTS,
    authenticate_user,
    get_current_user,
    list_tenant_team,
    register_user,
    require_tenant_access,
)
from config import (
    BAJAJ_WABA_ID,
    OFFICIAL_TEMPLATE_BASE_URL,
    _account_prefix,
    _load_env_file,
)
from grammar_checker import lint_and_fix_body, validate_meta_technical_compliance
from loader import load_from_csv, load_from_excel
from models import ApprovalStatus, SubmissionResult, SubmissionStatus
from rcs_client import fetch_rcs_templates

# RCS pipeline imports
from rcs_config import (
    get_rcs_auth_headers,
    get_rcs_entity_id,
)
from rcs_loader import load_rcs_from_csv, load_rcs_from_excel
from rcs_models import RcsSubmissionResult, RcsSubmissionStatus
from rcs_runner import run_rcs
from rcs_tracker import load_rcs_log, log_rcs_result
from runner import get_pending_templates_sla_insights, poll_pending, run
from submission_client import _GOVERNOR, _STATUS_MAP, delete_template, delete_templates_bulk
from tracker import load_log, log_result, pending_entries

app = FastAPI(title="Karix Template Whitelisting API (WhatsApp & RCS)")

cors_origins_env = os.environ.get("ALLOWED_ORIGINS", "")
allowed_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
if not allowed_origins:
    allowed_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https?://.*" if not cors_origins_env else None,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

LOG_PATH = "submission_log.jsonl"
RCS_LOG_PATH = "rcs_submission_log.jsonl"


@app.get("/api/health")
@app.get("/healthz")
def health_check():
    """Health check endpoint for Render zero-downtime deploys and external uptime monitors."""
    return {"status": "ok", "service": "karix-whitelisting-api", "version": "2.1.0"}


MEDIA_CACHE_DIR = Path("media_cache")
MEDIA_CACHE_DIR.mkdir(exist_ok=True)


def _init_media_cache():
    try:
        from submission_client import _ensure_default_sample_image

        img_p = _ensure_default_sample_image()
        target = MEDIA_CACHE_DIR / "default_sample_header.png"
        if not target.exists() and Path(img_p).exists():
            target.write_bytes(Path(img_p).read_bytes())
    except Exception:
        pass
    # RCS ratio-specific fallbacks per official specs
    try:
        from PIL import Image

        for fname, size in (
            ("default_rcs_3x1.png", (1440, 480)),
            ("default_rcs_2x1.png", (1440, 720)),
            ("default_rcs_3x4.png", (768, 1024)),
        ):
            img_p = MEDIA_CACHE_DIR / fname
            if not img_p.exists():
                Image.new("RGB", size, (0, 120, 242)).save(img_p, format="PNG")
    except Exception:
        pass


@app.get("/api/media/{filename}")
def get_public_media(filename: str):
    """Serve cached template header images/videos/documents directly to Meta and frontend previews."""
    clean_fn = Path(filename).name
    file_p = MEDIA_CACHE_DIR / clean_fn
    if not file_p.exists():
        # Check root directory fallback
        root_p = Path(clean_fn)
        if root_p.exists():
            file_p = root_p
        else:
            raise HTTPException(status_code=404, detail="Media not found")
    media_type = "image/png"
    if clean_fn.endswith((".jpg", ".jpeg")):
        media_type = "image/jpeg"
    elif clean_fn.endswith(".mp4"):
        media_type = "video/mp4"
    elif clean_fn.endswith(".pdf"):
        media_type = "application/pdf"
    return FileResponse(str(file_p), media_type=media_type)


# ---------------------------------------------------------------------------
# Models & Account Store
# ---------------------------------------------------------------------------

ACCOUNTS_FILE = Path("accounts.json")
DEFAULT_ACCOUNTS = [
    {"id": "bajaj", "name": "Bajaj Finserv", "is_builtin": True},
    {"id": "tata", "name": "Tata Capital", "is_builtin": True},
]


def load_accounts() -> list[dict]:
    """Load accounts from accounts.json, credentials.json, and environment."""
    _load_env_file()
    accounts_map: dict[str, dict] = {d["id"]: dict(d) for d in DEFAULT_ACCOUNTS}

    # 1. From accounts.json
    if ACCOUNTS_FILE.exists():
        try:
            data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for a in data:
                    if isinstance(a, dict) and a.get("id"):
                        accounts_map[a["id"]] = a
        except Exception as exc:
            logger.warning("Error reading accounts.json: %s", exc)

    # 2. Auto-discover custom accounts from credentials.json & os.environ
    cred_json_path = Path("credentials.json")
    all_keys = list(os.environ.keys())
    if cred_json_path.exists():
        try:
            saved_creds = json.loads(cred_json_path.read_text(encoding="utf-8"))
            if isinstance(saved_creds, dict):
                all_keys.extend(saved_creds.keys())
        except Exception:
            pass

    for k in all_keys:
        if k.endswith("_WABA_ID") and not k.startswith("BAJAJ_") and not k.startswith("TATA_") and k != "WABA_ID":
            prefix = k[:-8]  # strip _WABA_ID
            acc_id = prefix.lower()
            if acc_id not in accounts_map:
                name = prefix.replace("_", " ").title()
                accounts_map[acc_id] = {"id": acc_id, "name": name, "is_builtin": False}
    accounts = list(accounts_map.values())
    try:
        ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass
    return accounts


def save_accounts(accounts: list[dict]) -> None:
    try:
        ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to write accounts.json: %s", exc)


def get_account_name(account_id: str) -> str:
    accs = load_accounts()
    for a in accs:
        if a.get("id") == account_id.lower():
            return a.get("name", account_id)
    return account_id.replace("_", " ").title()


class AccountCreate(BaseModel):
    name: str
    id: str | None = None


class UserRegister(BaseModel):
    name: str
    role: str | None = "Operator"


class CredentialUpdate(BaseModel):
    account: str = "bajaj"  # e.g. "bajaj", "tata", "tchfl", etc.
    channel: str = "whatsapp"  # "whatsapp" | "rcs"
    waba_auth_token: str | None = None
    waba_id: str | None = None
    bearer_token: str | None = None
    session: str | None = None
    user: str | None = None
    user_name: str | None = None  # Who is performing the update
    portal_username: str | None = None
    portal_password: str | None = None
    template_namespace_id: str | None = None
    entity_id: str | None = None
    lounge_cookie: str | None = None


# ---------------------------------------------------------------------------
def _clean_error_message(err) -> str | None:
    """Flatten error strings or nested error dictionaries into a clean message."""
    if not err:
        return None
    if isinstance(err, str):
        s = err.strip()
        if s.startswith("HTTP ") and ":" in s:
            prefix, rest = s.split(":", 1)
            cleaned_rest = _clean_error_message(rest.strip())
            if cleaned_rest and cleaned_rest != rest.strip():
                return cleaned_rest
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                parsed = json.loads(s)
                return _clean_error_message(parsed)
            except Exception:
                pass
        m = re.search(r'"error_user_msg"\s*:\s*"([^"]+)"', s)
        if m:
            return m.group(1)
        m = re.search(r'"message"\s*:\s*"([^"]+)"', s)
        if m and "Invalid parameter" not in m.group(1):
            return m.group(1)
        return err

    if isinstance(err, dict):
        if "error_user_msg" in err:
            return str(err["error_user_msg"])
        if "errorMessage" in err:
            return _clean_error_message(err["errorMessage"])
        if "error" in err:
            return _clean_error_message(err["error"])
        if "message" in err:
            return str(err["message"])
        if "reason" in err:
            return _clean_error_message(err["reason"])
        return str(err)
    return str(err)


def _json_safe(obj):
    """
    Recursively coerce arbitrary values to plain JSON-safe primitives so the
    response encoder can never raise (e.g. a None in a sort key, a datetime,
    an enum, raw bytes, or any exotic nested value from a provider payload).
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, bytes):
        import base64

        return f"base64:{base64.b64encode(obj).decode()}"
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in obj]
    return str(obj)


def fetch_whatsapp_templates(client: str = "bajaj") -> list[dict]:
    """Fetch live templates directly from Karix WhatsApp API (Portal & Official)."""
    acc = client.lower().strip()
    try:
        from submission_client import fetch_template_list

        templates, _ = fetch_template_list(client=acc)
        return templates or []
    except Exception as e:
        logger.warning("Could not fetch live WhatsApp templates for %s: %s", acc, e)
        return []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
# Multi-Tenant Authentication Endpoints
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    email: str
    password: str
    name: str
    tenant_id: str = "bajaj"
    role: str = "operator"


class TeamInviteRequest(BaseModel):
    email: str
    name: str
    password: str
    role: str = "operator"


@app.post("/api/auth/signup")
def signup_endpoint(body: SignupRequest):
    """Register a new user account bound to a specific tenant organization."""
    try:
        auth_res = register_user(
            email=body.email,
            password=body.password,
            name=body.name,
            tenant_id=body.tenant_id,
            role=body.role,
        )
        log_activity(
            user=body.name,
            action="USER_SIGNUP",
            account=body.tenant_id,
            channel="all",
            details={"email": body.email, "tenant": body.tenant_id, "role": body.role},
            status="success",
        )
        return _json_safe(auth_res)
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err)) from val_err
    except Exception as exc:
        logger.exception("Signup error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error during registration.") from exc


@app.post("/api/auth/login")
def login_endpoint(body: LoginRequest):
    """Authenticate user with email & password, returning signed JWT with tenant claim."""
    auth_res = authenticate_user(body.email, body.password)
    if not auth_res:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    user_info = auth_res["user"]
    log_activity(
        user=user_info.get("name") or body.email,
        action="USER_LOGIN",
        account=user_info.get("tenant_id", "all"),
        channel="all",
        details={"email": body.email, "tenant": user_info.get("tenant_id")},
        status="success",
    )
    return _json_safe(auth_res)


@app.get("/api/auth/me")
def get_me_endpoint(current_user: dict = Depends(get_current_user)):
    """Return active user profile and tenant permissions."""
    return _json_safe(current_user)


@app.get("/api/auth/team")
def get_team_endpoint(current_user: dict = Depends(get_current_user)):
    """List team members within user's assigned organization."""
    tenant = current_user.get("tenant_id", "bajaj")
    members = list_tenant_team(tenant)
    return _json_safe(members)


@app.post("/api/auth/team/invite")
def invite_team_member(body: TeamInviteRequest, current_user: dict = Depends(get_current_user)):
    """Organization admins can onboard colleagues to their organization."""
    tenant = current_user.get("tenant_id", "bajaj")
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only organization admins can invite team members.")

    try:
        new_user = register_user(
            email=body.email,
            password=body.password,
            name=body.name,
            tenant_id=tenant,
            role=body.role,
        )
        return _json_safe(new_user)
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err)) from val_err


# ---------------------------------------------------------------------------
# Core Tenant Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/stats")
def get_stats(
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
    current_user: dict = Depends(get_current_user),
):
    require_tenant_access(account, current_user)
    acc = account.lower()
    chan = channel.lower()
    try:
        if chan == "rcs":
            local_entries = load_rcs_log(RCS_LOG_PATH)
            local_entries = [e for e in local_entries if (e.get("client", "bajaj") or "bajaj").lower() == acc]
            live_templates = fetch_rcs_templates(client=acc)
            seen_names = set()
            merged = []

            for lt in live_templates:
                vi = lt.get("viTemplate", {})
                name = vi.get("name") or str(lt.get("templateId", ""))
                status_str = str(lt.get("status", "SUBMITTED")).upper()
                merged.append(
                    {
                        "template_name": name,
                        "status": "submitted" if status_str in ("PENDING", "APPROVED", "SUBMITTED") else "failed",
                        "approval_status": status_str.lower(),
                    }
                )
                seen_names.add(name.lower())

            for le in local_entries:
                if le.get("template_name", "").lower() not in seen_names:
                    merged.append(le)

            total = len(merged)
            submitted = sum(1 for e in merged if e.get("status") == "submitted")
            failed = sum(1 for e in merged if e.get("status") == "failed")
            duplicate = sum(1 for e in merged if e.get("status") == "duplicate")
            return {
                "total": total,
                "submitted": submitted,
                "failed": failed,
                "duplicate": duplicate,
                "pending": sum(1 for e in merged if e.get("approval_status") == "pending"),
                "approved": sum(1 for e in merged if e.get("approval_status") == "approved"),
                "rejected": sum(1 for e in merged if e.get("approval_status") == "rejected"),
                "error": None,
                "karix_health": _GOVERNOR.get_health_stats(),
                "sla_insights": {"pending_count": 0, "due_for_poll_count": 0, "categories": {}, "next_recommended_poll_sec": 120},
            }

        # WhatsApp
        local_entries = load_log(LOG_PATH)
        local_entries = [e for e in local_entries if (e.get("client", "bajaj") or "bajaj").lower() == acc]

        live_templates = fetch_whatsapp_templates(client=acc)
        seen_names = set()
        merged = []

        for lt in live_templates:
            name = lt.get("template_name") or str(lt.get("fb_template_id", ""))
            status_str = str(lt.get("template_create_status", "PENDING")).upper()
            approval_val = (
                _STATUS_MAP.get(status_str, ApprovalStatus.UNKNOWN).value
                if status_str in _STATUS_MAP
                else status_str.lower()
            )
            merged.append(
                {
                    "template_name": name,
                    "status": "submitted",
                    "approval_status": approval_val,
                }
            )
            seen_names.add(name.lower())

        for le in local_entries:
            if le.get("template_name", "").lower() not in seen_names:
                merged.append(le)

        total = len(merged)
        submitted = sum(1 for e in merged if str(e.get("status", "")).lower() == "submitted")
        failed = sum(1 for e in merged if str(e.get("status", "")).lower() == "failed")
        pending = sum(1 for e in merged if str(e.get("approval_status", "")).lower() == "pending")
        approved = sum(1 for e in merged if str(e.get("approval_status", "")).lower() == "approved")
        rejected = sum(1 for e in merged if str(e.get("approval_status", "")).lower() == "rejected")
        return {
            "total": total,
            "submitted": submitted,
            "failed": failed,
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            "duplicate": 0,
            "error": None,
            "karix_health": _GOVERNOR.get_health_stats(),
            "sla_insights": get_pending_templates_sla_insights(LOG_PATH, client=acc),
        }
    except Exception as exc:
        logger.exception("Error in get_stats for %s (%s): %s", acc, chan, exc)
        return {
            "total": 0,
            "submitted": 0,
            "failed": 0,
            "pending": 0,
            "approved": 0,
            "rejected": 0,
            "duplicate": 0,
            "error": str(exc),
            "karix_health": _GOVERNOR.get_health_stats(),
            "sla_insights": {"pending_count": 0, "due_for_poll_count": 0, "categories": {}, "next_recommended_poll_sec": 120},
        }


def _filter_and_sort_templates(entries: list[dict], status: str | None, search: str | None) -> list[dict]:
    res = entries
    if status and isinstance(status, str):
        s_val = status.lower()
        res = [
            e
            for e in res
            if str(e.get("status", "")).lower() == s_val or str(e.get("approval_status", "")).lower() == s_val
        ]
    if search and isinstance(search, str):
        q = search.lower()
        res = [
            e
            for e in res
            if q in str(e.get("template_name", "")).lower()
            or q in str(e.get("template_id", "")).lower()
            or q in str(e.get("source_ref", "")).lower()
            or q in str(e.get("provider_ref_id", "")).lower()
        ]
    res.sort(key=lambda e: e.get("submitted_at") or "", reverse=True)
    return res


def _merge_rcs_templates(acc: str, status: str | None, search: str | None) -> list[dict]:
    local_entries = [e for e in load_rcs_log(RCS_LOG_PATH) if (e.get("client", "bajaj") or "bajaj").lower() == acc]
    live_templates = fetch_rcs_templates(client=acc)
    seen_names = set()
    merged_entries = []

    for lt in live_templates:
        vi = lt.get("viTemplate", {})
        name = vi.get("name") or str(lt.get("templateId", ""))
        status_str = str(lt.get("status", "SUBMITTED")).upper()
        t_type = vi.get("type", "text")

        carousel_cards = vi.get("carouselCard", [])
        card_title = ""
        msg = vi.get("textMessage", "")
        if carousel_cards:
            t_type = f"carousel ({len(carousel_cards)} cards)"
            card_title = " | ".join([c.get("cardTitle", "") for c in carousel_cards if c.get("cardTitle")])
            msg = " | ".join([c.get("cardDescription", "") for c in carousel_cards if c.get("cardDescription")])
        elif vi.get("standaloneCard"):
            t_type = "richcard"
            card_title = vi.get("standaloneCard", {}).get("cardTitle", "")
            msg = vi.get("standaloneCard", {}).get("cardDescription", "")

        entry = {
            "source_ref": name,
            "template_name": name,
            "template_id": str(lt.get("templateId", "")),
            "template_type": t_type,
            "card_title": card_title,
            "template_message": msg,
            "sender_ids": [lt.get("botId", "")],
            "status": "submitted" if status_str in ("PENDING", "APPROVED", "SUBMITTED") else "failed",
            "approval_status": status_str.lower(),
            "submitted_at": lt.get("createdAt") or lt.get("modifiedAt") or "",
            "provider_response": lt,
            "client": acc,
            "channel": "rcs",
            "submitted_by": None,
            "source_file": None,
            "live": True,
            "exists_on_waba": True,
        }
        merged_entries.append(entry)
        seen_names.add(name.lower())

    for le in local_entries:
        le_name = (le.get("template_name") or "").strip().lower()
        le_clean = dict(le)
        le_clean["error"] = _clean_error_message(le.get("error"))
        if le_name in seen_names:
            for me in merged_entries:
                if me.get("template_name", "").strip().lower() == le_name:
                    me["submitted_by"] = me.get("submitted_by") or le.get("submitted_by")
                    me["source_file"] = me.get("source_file") or le.get("source_file")
                    me["exists_on_waba"] = True
        else:
            le_clean["live"] = False
            le_clean["exists_on_waba"] = False
            merged_entries.append(le_clean)
            seen_names.add(le_name)

    return _filter_and_sort_templates(merged_entries, status, search)


def _merge_wa_templates(acc: str, status: str | None, search: str | None) -> list[dict]:
    local_entries = [e for e in load_log(LOG_PATH) if (e.get("client", "bajaj") or "bajaj").lower() == acc]
    live_templates = fetch_whatsapp_templates(client=acc)
    seen_names = set()
    merged_entries = []

    for lt in live_templates:
        name = lt.get("template_name") or str(lt.get("fb_template_id", "") or lt.get("sno", ""))
        status_str = str(lt.get("template_create_status") or lt.get("status", "PENDING")).upper()
        approval_val = (
            _STATUS_MAP.get(status_str, ApprovalStatus.UNKNOWN).value
            if status_str in _STATUS_MAP
            else status_str.lower()
        )

        entry = {
            "source_ref": name,
            "template_name": name,
            "status": "submitted" if approval_val in ("approved", "pending", "submitted") else "failed",
            "provider_ref_id": str(lt.get("fb_template_id", "") or lt.get("sno", "")),
            "approval_status": approval_val,
            "approval_reason": lt.get("template_status_reason"),
            "error": None,
            "retry_count": 0,
            "submitted_at": lt.get("created_at") or lt.get("modified_at") or "",
            "updated_at": lt.get("modified_at"),
            "provider_response": lt,
            "client": acc,
            "channel": "whatsapp",
            "submitted_by": None,
            "source_file": None,
            "live": True,
            "exists_on_waba": True,
        }
        merged_entries.append(entry)
        seen_names.add(name.lower())

    for le in local_entries:
        le_name = (le.get("template_name") or "").strip().lower()
        le_clean = dict(le)
        le_clean["error"] = _clean_error_message(le.get("error"))
        if le_name in seen_names:
            for me in merged_entries:
                if me.get("template_name", "").strip().lower() == le_name:
                    me["submitted_by"] = me.get("submitted_by") or le.get("submitted_by")
                    me["source_file"] = me.get("source_file") or le.get("source_file")
                    me["exists_on_waba"] = True
        else:
            le_clean["live"] = False
            le_clean["exists_on_waba"] = False
            merged_entries.append(le_clean)
            seen_names.add(le_name)

    return _filter_and_sort_templates(merged_entries, status, search)


@app.get("/api/templates")
def get_templates(
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
    status: str | None = Query(None),
    search: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
):
    require_tenant_access(account, current_user)
    acc = account.lower()
    chan = channel.lower()
    try:
        if chan == "rcs":
            entries = _merge_rcs_templates(acc, status, search)
        else:
            entries = _merge_wa_templates(acc, status, search)
        return [_json_safe(e) for e in entries]
    except Exception as exc:
        logger.exception("Error in get_templates for %s (%s): %s", acc, chan, exc)
        return []


def _inspect_image_aspect_ratio(comp: dict, aspect_warnings: list[dict]) -> None:
    img_bytes = comp.get("image_bytes")
    if not img_bytes:
        return
    try:
        import base64
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(img_bytes))
        w, h = img.size
        ratio = w / h

        is_16_9 = abs(ratio - (16 / 9)) < 0.08
        is_2_1 = abs(ratio - 2.0) < 0.08
        is_3_4 = abs(ratio - 0.75) < 0.08

        if not is_16_9 and not is_2_1 and not is_3_4:
            shape_name = (
                "1:1 (Square)"
                if abs(ratio - 1.0) < 0.05
                else ("Portrait / Vertical" if ratio < 1.0 else f"Non-standard ({ratio:.2f}:1)")
            )
            aspect_warnings.append(
                {
                    "component": "HEADER (IMAGE)",
                    "original_size": f"{w}x{h}px",
                    "current_ratio": shape_name,
                    "recommended_ratio": "16:9 (1280x720) or 2:1 (1200x600)",
                    "action": "Auto-pad onto standard canvas with matching background so no text/logo is cropped.",
                }
            )
        f_type = comp.get("file_type") or "image/png"
        comp["thumbnail_url"] = f"data:{f_type};base64,{base64.b64encode(img_bytes).decode()}"
    except Exception as exc:
        logger.debug("Aspect ratio inspection notice: %s", exc)
    finally:
        comp.pop("image_bytes", None)


def _inspect_single_submission(
    s, live_names: set[str], account_detection: dict, account: str, channel: str
) -> dict:
    item = asdict(s) if not isinstance(s, dict) else dict(s)
    tname = (item.get("template_name") or "").strip()
    already_exists = tname.lower() in live_names if tname else False
    item["already_exists_on_waba"] = already_exists
    item["exists_on_waba"] = already_exists
    if already_exists:
        item["duplicate_warning"] = {
            "template_name": tname,
            "message": (
                f"Template '{tname}' already exists on WABA for {account.title()}. "
                "Meta will reject resubmission with duplicate content. "
                "Please use a new name (e.g. appending '_v2') or edit the existing template."
            ),
        }
    item["account_detection"] = account_detection

    aspect_warnings = []
    grammar_warnings = []
    components = item.get("components") or []
    for comp in components:
        if not isinstance(comp, dict):
            continue
        ctype = comp.get("type")
        cformat = str(comp.get("format", "")).upper()

        if ctype == "BODY" or (ctype == "HEADER" and cformat == "TEXT"):
            raw_text = comp.get("text", "")
            if raw_text:
                cleaned, g_warns = lint_and_fix_body(raw_text)
                if g_warns:
                    grammar_warnings.extend(g_warns)
                    comp["suggested_text"] = cleaned

        if ctype == "HEADER" and cformat == "IMAGE":
            _inspect_image_aspect_ratio(comp, aspect_warnings)
        elif "image_bytes" in comp:
            comp.pop("image_bytes", None)

    if channel == "rcs":
        for text_field in ("text_message", "template_message", "card_title", "card_description"):
            val = item.get(text_field)
            if val and isinstance(val, str):
                _, g_warns = lint_and_fix_body(val)
                grammar_warnings.extend(g_warns)

    item["aspect_ratio_warnings"] = aspect_warnings
    item["grammar_warnings"] = grammar_warnings

    body_text = next((str(c.get("text", "")) for c in components if isinstance(c, dict) and c.get("type") == "BODY"), "")
    header_comp = next((c for c in components if isinstance(c, dict) and c.get("type") == "HEADER"), None)
    footer_text = next((str(c.get("text", "")) for c in components if isinstance(c, dict) and c.get("type") == "FOOTER"), "")
    buttons_list = next((c.get("buttons", []) for c in components if isinstance(c, dict) and c.get("type") == "BUTTONS"), [])

    item["compliance_warnings"] = validate_meta_technical_compliance(
        body_text=body_text,
        header_text=header_comp.get("text") if header_comp else None,
        footer_text=footer_text,
        buttons=buttons_list,
        header_format=header_comp.get("format") if header_comp else None,
    )
    return item


def _inspect_template_quality_and_warnings(
    submissions: list, channel: str = "whatsapp", account: str = "bajaj"
) -> list[dict]:
    """
    Inspect image dimensions, text grammar/spelling, and cross-reference with live WABA list.
    Attaches aspect ratio warnings, spelling typos, duplicate warnings, and suggested fixes.
    """
    from loader import detect_spreadsheet_account

    acc = account.lower().strip()
    account_detection = detect_spreadsheet_account(submissions, current_account=acc)

    live_templates = fetch_whatsapp_templates(client=acc) if channel == "whatsapp" else fetch_rcs_templates(client=acc)
    live_names = {
        (lt.get("template_name") or lt.get("viTemplate", {}).get("name") or "").strip().lower()
        for lt in live_templates
        if lt.get("template_name") or lt.get("viTemplate", {}).get("name")
    }
    return [
        _json_safe(_inspect_single_submission(s, live_names, account_detection, account, channel))
        for s in submissions
    ]


@app.post("/api/preview")
async def preview_file(
    file: UploadFile = File(...),
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
    user: str = Query("Anonymous Operator"),
    current_user: dict = Depends(get_current_user),
):
    require_tenant_access(account, current_user)
    chan = channel.lower()
    suffix = Path(file.filename or "upload.csv").suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        if chan == "rcs":
            if suffix in (".xlsx", ".xls"):
                submissions = await asyncio.to_thread(load_rcs_from_excel, tmp_path, client=account)
            else:
                submissions = await asyncio.to_thread(load_rcs_from_csv, tmp_path, client=account)
            if not submissions:
                log_activity(
                    user=user,
                    action="TEMPLATE_PREVIEW",
                    account=account,
                    channel="rcs",
                    details={"filename": file.filename or "upload.csv", "count": 0},
                    status="failed",
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"No valid RCS templates found in '{file.filename or 'uploaded file'}'. Please make sure the file contains RCS template definitions.",
                )
            log_activity(
                user=user,
                action="TEMPLATE_PREVIEW",
                account=account,
                channel="rcs",
                details={
                    "filename": file.filename or "upload.csv",
                    "count": len(submissions),
                },
                status="success",
            )
            return _inspect_template_quality_and_warnings(submissions, channel="rcs", account=account)

        # WhatsApp
        if suffix in (".xlsx", ".xls"):
            submissions = await asyncio.to_thread(load_from_excel, tmp_path, client=account)
        else:
            submissions = await asyncio.to_thread(load_from_csv, tmp_path, client=account)

        if not submissions:
            log_activity(
                user=user,
                action="TEMPLATE_PREVIEW",
                account=account,
                channel="whatsapp",
                details={"filename": file.filename or "upload.csv", "count": 0},
                status="failed",
            )
            raise HTTPException(
                status_code=400,
                detail=f"No valid WhatsApp templates found in '{file.filename or 'uploaded file'}'. Please ensure the file contains required template columns (template_name, category, language, body) or use the sample CSV format.",
            )

        log_activity(
            user=user,
            action="TEMPLATE_PREVIEW",
            account=account,
            channel="whatsapp",
            details={
                "filename": file.filename or "upload.csv",
                "count": len(submissions),
            },
            status="success",
        )
        for s in submissions:
            s.client = account
        return _inspect_template_quality_and_warnings(submissions, channel="whatsapp", account=account)
    except HTTPException:
        raise
    except Exception as exc:
        # Don't leak a bare 500 for malformed/non-template uploads — surface a clean error.
        logger.exception("Preview failed for %s (%s): %s", account, channel, exc)
        raise HTTPException(
            status_code=400,
            detail=f"Preview failed for {channel}: {exc!s}",
        ) from exc
    finally:
        os.unlink(tmp_path)


async def _submit_rcs_batch(
    tmp_path: str, suffix: str, acc: str, user: str, skip_duplicates: bool, auto_route: bool, filename: str, current_user: dict
) -> dict:
    subs = load_rcs_from_excel(tmp_path, client=acc) if suffix in (".xlsx", ".xls") else load_rcs_from_csv(tmp_path, client=acc)
    if not subs:
        raise HTTPException(status_code=400, detail=f"No valid RCS templates found in '{filename}' to submit.")

    if auto_route:
        from loader import detect_spreadsheet_account
        detection = detect_spreadsheet_account(subs, current_account=acc)
        if detection.get("is_mismatch") and detection.get("confidence", 0) >= 0.45:
            target_acc = detection["detected_account_id"]
            try:
                require_tenant_access(target_acc, current_user)
                acc = target_acc
            except HTTPException:
                pass

    to_submit = []
    duplicate_entries = []
    if skip_duplicates:
        live_templates = fetch_rcs_templates(client=acc)
        live_map = {
            (lt.get("viTemplate", {}).get("name") or str(lt.get("templateId", ""))).strip().lower(): lt
            for lt in live_templates
            if (lt.get("viTemplate", {}).get("name") or lt.get("templateId"))
        }
        for s in subs:
            name_key = s.template_name.strip().lower()
            if name_key in live_map:
                live_obj = live_map[name_key]
                status_str = str(live_obj.get("status", "APPROVED")).upper()
                dupe_res = RcsSubmissionResult(
                    source_ref=s.source_ref,
                    template_name=s.template_name,
                    status=RcsSubmissionStatus.DUPLICATE,
                    provider_ref_id=str(live_obj.get("templateId", "")),
                    error="RCS template already active on DLT Bot — skipped duplicate submission.",
                    provider_response=live_obj,
                    approval_status=status_str.lower(),
                    client=acc,
                    channel="rcs",
                    submitted_by=user,
                    source_file=filename,
                )
                log_rcs_result(dupe_res, RCS_LOG_PATH)
                duplicate_entries.append(asdict(dupe_res))
            else:
                to_submit.append(s)
    else:
        to_submit = subs

    new_entries = []
    if to_submit:
        before_count = len(load_rcs_log(RCS_LOG_PATH))
        await asyncio.to_thread(run_rcs, [asdict(s) for s in to_submit], RCS_LOG_PATH, client=acc, user=user, source_file=filename)
        all_entries = load_rcs_log(RCS_LOG_PATH)
        new_entries = all_entries[before_count:]

    all_combined = duplicate_entries + new_entries
    cleaned_entries = []
    for e in all_combined:
        entry = dict(e)
        if "error" in entry:
            entry["error"] = _clean_error_message(entry["error"])
        cleaned_entries.append(entry)

    log_activity(
        user=user,
        action="TEMPLATE_SUBMISSION",
        account=acc,
        channel="rcs",
        details={
            "filename": filename,
            "count": len(cleaned_entries),
            "net_new_submitted": len(to_submit),
            "duplicates_skipped": len(duplicate_entries),
            "templates": [e.get("template_name") for e in cleaned_entries],
            "successful": len([e for e in cleaned_entries if e.get("status") in ("submitted", "duplicate")]),
            "failed": len([e for e in cleaned_entries if e.get("status") == "failed"]),
        },
        status="success" if any(e.get("status") in ("submitted", "duplicate") for e in cleaned_entries) else "failed",
    )
    return {
        "submitted": len(to_submit),
        "skipped_duplicates": len(duplicate_entries),
        "results": [_json_safe(e) for e in cleaned_entries],
    }


async def _submit_wa_batch(
    tmp_path: str, suffix: str, acc: str, user: str, skip_duplicates: bool, auto_route: bool, fix_aspect_ratio: bool, fix_grammar: bool, filename: str, current_user: dict
) -> dict:
    subs = await asyncio.to_thread(load_from_excel, tmp_path, client=acc) if suffix in (".xlsx", ".xls") else await asyncio.to_thread(load_from_csv, tmp_path, client=acc)
    if not subs:
        raise HTTPException(status_code=400, detail=f"No valid WhatsApp templates found in '{filename}' to submit.")

    if auto_route:
        from loader import detect_spreadsheet_account
        detection = detect_spreadsheet_account(subs, current_account=acc)
        if detection.get("is_mismatch") and detection.get("confidence", 0) >= 0.45:
            target_acc = detection["detected_account_id"]
            try:
                require_tenant_access(target_acc, current_user)
                acc = target_acc
            except HTTPException:
                pass

    to_submit = []
    duplicate_entries = []
    if skip_duplicates:
        live_templates = fetch_whatsapp_templates(client=acc)
        live_map = {
            (lt.get("template_name") or "").strip().lower(): lt
            for lt in live_templates
            if lt.get("template_name")
        }
        for s in subs:
            name_key = s.template_name.strip().lower()
            if name_key in live_map:
                live_obj = live_map[name_key]
                status_str = str(live_obj.get("template_create_status") or live_obj.get("status", "APPROVED")).upper()
                approval_val = (
                    _STATUS_MAP.get(status_str, ApprovalStatus.APPROVED).value
                    if status_str in _STATUS_MAP
                    else status_str.lower()
                )
                ref_id = str(live_obj.get("fb_template_id", "") or live_obj.get("sno", "") or "")
                dupe_res = SubmissionResult(
                    source_ref=s.source_ref,
                    template_name=s.template_name,
                    status=SubmissionStatus.DUPLICATE,
                    provider_ref_id=ref_id,
                    error="Template already active on WABA — automatically skipped duplicate submission.",
                    provider_response=live_obj,
                    approval_status=ApprovalStatus(approval_val) if approval_val in ("approved", "pending", "rejected") else ApprovalStatus.APPROVED,
                    client=acc,
                    channel="whatsapp",
                    submitted_by=user,
                    source_file=filename,
                )
                log_result(dupe_res, LOG_PATH)
                duplicate_entries.append(asdict(dupe_res))
            else:
                to_submit.append(s)
    else:
        to_submit = subs

    new_entries = []
    if to_submit:
        before_count = len(load_log(LOG_PATH))
        await asyncio.to_thread(run, [asdict(s) for s in to_submit], LOG_PATH, client=acc, user=user, source_file=filename, fix_aspect_ratio=fix_aspect_ratio, fix_grammar=fix_grammar)
        all_entries = load_log(LOG_PATH)
        new_entries = all_entries[before_count:]

    all_combined = duplicate_entries + new_entries
    cleaned_entries = []
    for e in all_combined:
        entry = dict(e)
        if "error" in entry:
            entry["error"] = _clean_error_message(entry["error"])
        cleaned_entries.append(entry)

    log_activity(
        user=user,
        action="TEMPLATE_SUBMISSION",
        account=acc,
        channel="whatsapp",
        details={
            "filename": filename,
            "count": len(cleaned_entries),
            "net_new_submitted": len(to_submit),
            "duplicates_skipped": len(duplicate_entries),
            "templates": [e.get("template_name") for e in cleaned_entries],
            "successful": len([e for e in cleaned_entries if e.get("status") in ("submitted", "duplicate")]),
            "failed": len([e for e in cleaned_entries if e.get("status") == "failed"]),
        },
        status="success" if any(e.get("status") in ("submitted", "duplicate") for e in cleaned_entries) else "failed",
    )
    return {
        "submitted": len(to_submit),
        "skipped_duplicates": len(duplicate_entries),
        "results": [_json_safe(e) for e in cleaned_entries],
    }


@app.post("/api/submit")
async def submit_file(
    file: UploadFile = File(...),
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
    user: str = Query("Anonymous Operator"),
    fix_aspect_ratio: bool = Query(True),
    fix_grammar: bool = Query(True),
    skip_duplicates: bool = Query(True),
    auto_route: bool = Query(True),
    current_user: dict = Depends(get_current_user),
):
    require_tenant_access(account, current_user)
    suffix = Path(file.filename or "upload.csv").suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    acc = account.lower()
    chan = channel.lower()
    try:
        if chan == "rcs":
            return await _submit_rcs_batch(tmp_path, suffix, acc, user, skip_duplicates, auto_route, file.filename or "upload.csv", current_user)
        return await _submit_wa_batch(tmp_path, suffix, acc, user, skip_duplicates, auto_route, fix_aspect_ratio, fix_grammar, file.filename or "upload.csv", current_user)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Submission failed for %s (%s): %s", acc, chan, exc)
        raise HTTPException(
            status_code=400,
            detail=f"Submission failed for {acc} ({chan}): {exc!s}",
        ) from exc
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.post("/api/poll")
def poll(
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
    user: str = Query("Anonymous Operator"),
    current_user: dict = Depends(get_current_user),
):
    require_tenant_access(account, current_user)
    acc = account.lower()
    chan = channel.lower()
    try:
        if chan != "whatsapp":
            return {"checked": 0}
        all_pending = pending_entries(LOG_PATH)
        matching = [e for e in all_pending if (e.get("client", "bajaj") or "bajaj").lower() == acc]
        poll_res = poll_pending(LOG_PATH, client=acc)
        log_activity(
            user=user,
            action="STATUS_POLL",
            account=acc,
            channel=chan,
            details={
                "checked_count": poll_res.get("checked", len(matching)),
                "updated_count": poll_res.get("updated", 0),
            },
            status="success",
        )
        return _json_safe(poll_res)
    except Exception as exc:
        # Never leak a 500 on Poll — surface a clean, actionable error (e.g. missing credentials).
        logger.exception("Error in poll for %s (%s): %s", acc, chan, exc)
        raise HTTPException(
            status_code=400,
            detail=f"Poll failed for {acc}: {exc!s}",
        ) from exc



class DeleteTemplatesRequest(BaseModel):
    template_names: list[str] | None = None
    delete_all: bool = False


@app.post("/api/templates/delete")
def delete_templates_endpoint(
    body: DeleteTemplatesRequest,
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
    user: str = Query("Anonymous Operator"),
    current_user: dict = Depends(get_current_user),
):
    """Bulk-delete WhatsApp templates by name list, or all templates on the WABA."""
    require_tenant_access(account, current_user)
    acc = account.lower()
    if channel.lower() != "whatsapp":
        raise HTTPException(status_code=400, detail="Template deletion is only supported for WhatsApp.")

    if not body.template_names and not body.delete_all:
        raise HTTPException(status_code=400, detail="Provide template_names or set delete_all=true.")

    result = delete_templates_bulk(
        template_names=body.template_names,
        client=acc,
        delete_all=body.delete_all,
    )
    log_activity(
        user=user,
        action="TEMPLATE_DELETE",
        account=acc,
        channel="whatsapp",
        details={
            "total": result["total"],
            "deleted": len(result["deleted"]),
            "failed": len(result["failed"]),
            "delete_all": body.delete_all,
        },
        status="success" if not result["failed"] else "partial",
    )
    return _json_safe(result)


@app.post("/api/templates/delete-file")
async def delete_templates_from_file(
    file: UploadFile = File(...),
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
    user: str = Query("Anonymous Operator"),
    current_user: dict = Depends(get_current_user),
):
    """Delete WhatsApp templates parsed from an uploaded spreadsheet (CSV / XLSX)."""
    require_tenant_access(account, current_user)
    acc = account.lower()
    if channel.lower() != "whatsapp":
        raise HTTPException(status_code=400, detail="File-based template deletion is only supported for WhatsApp.")

    suffix = Path(file.filename or "upload.csv").suffix.lower()
    if suffix not in (".csv", ".xlsx", ".xls"):
        raise HTTPException(status_code=400, detail="Only .csv and .xlsx/.xls files are supported.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        if suffix in (".xlsx", ".xls"):
            subs = await asyncio.to_thread(load_from_excel, tmp_path, client=acc)
        else:
            subs = await asyncio.to_thread(load_from_csv, tmp_path, client=acc)

        if not subs:
            raise HTTPException(status_code=400, detail=f"No valid template names found in '{file.filename}'.")

        # Extract unique template names in order of appearance
        seen = set()
        template_names = []
        for s in subs:
            tname = s.template_name.strip()
            if tname and tname not in seen:
                seen.add(tname)
                template_names.append(tname)

        if not template_names:
            raise HTTPException(status_code=400, detail="No template names extracted from the file.")

        result = await asyncio.to_thread(
            delete_templates_bulk,
            template_names=template_names,
            client=acc,
            delete_all=False,
        )

        log_activity(
            user=user,
            action="TEMPLATE_DELETE_FILE",
            account=acc,
            channel="whatsapp",
            details={
                "filename": file.filename,
                "total_in_file": len(template_names),
                "deleted": len(result["deleted"]),
                "failed": len(result["failed"]),
            },
            status="success" if not result["failed"] else "partial",
        )
        return _json_safe(result)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.get("/api/accounts")
def get_accounts(current_user: dict = Depends(get_current_user)):
    accs = load_accounts()
    tenant = current_user.get("tenant_id", "all")
    if tenant != "all" and current_user.get("role") != "superadmin":
        if tenant == "tata":
            return [
                a
                for a in accs
                if a.get("group") == "Tata Capital" or a.get("id") in TATA_SUB_ACCOUNTS or a.get("id") == "tata"
            ]
        elif tenant == "bajaj":
            return [a for a in accs if a.get("group") == "Bajaj" or a.get("id") == "bajaj"]
        return [a for a in accs if a.get("id") == tenant]
    return accs


@app.post("/api/accounts")
def create_account(body: AccountCreate, user: str = Query("Anonymous Operator")):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Account name is required.")

    if body.id and body.id.strip():
        acc_id = re.sub(r"[^a-z0-9_]", "_", body.id.strip().lower()).strip("_")
    else:
        acc_id = re.sub(r"[^a-z0-9_]", "_", name.lower().strip()).strip("_")

    if not acc_id:
        raise HTTPException(status_code=400, detail="Invalid account ID generated from name.")

    accounts = load_accounts()
    if any(a.get("id") == acc_id for a in accounts):
        raise HTTPException(status_code=400, detail=f"Account with ID '{acc_id}' already exists.")

    new_acc = {"id": acc_id, "name": name, "is_builtin": False}
    accounts.append(new_acc)
    save_accounts(accounts)

    log_activity(
        user=user,
        action="ACCOUNT_CREATE",
        account=acc_id,
        channel="all",
        details={"name": name, "id": acc_id},
        status="success",
    )
    return new_acc


@app.delete("/api/accounts/{account_id}")
def delete_account(account_id: str, user: str = Query("Anonymous Operator")):
    acc_id = account_id.lower().strip()
    if acc_id in ("bajaj", "tata"):
        raise HTTPException(status_code=400, detail=f"Cannot delete built-in account '{acc_id}'.")

    accounts = load_accounts()
    initial_count = len(accounts)
    accounts = [a for a in accounts if a.get("id") != acc_id]
    if len(accounts) == initial_count:
        raise HTTPException(status_code=404, detail=f"Account '{acc_id}' not found.")

    save_accounts(accounts)

    # Scrub any credentials for this account from credentials.json and os.environ
    prefix = _account_prefix(acc_id)
    cred_json_path = Path("credentials.json")
    if cred_json_path.exists():
        try:
            saved_creds = json.loads(cred_json_path.read_text(encoding="utf-8"))
            if isinstance(saved_creds, dict):
                keys_to_del = [k for k in saved_creds if k.startswith(f"{prefix}_")]
                for k in keys_to_del:
                    del saved_creds[k]
                    os.environ.pop(k, None)
                cred_json_path.write_text(json.dumps(saved_creds, indent=2) + "\n", encoding="utf-8")
        except Exception as exc:
            logger.warning("Error scrubbing credentials.json on account delete: %s", exc)

    env_keys_to_del = [k for k in os.environ if k.startswith(f"{prefix}_")]
    for k in env_keys_to_del:
        os.environ.pop(k, None)

    env_path = Path(".env")
    if env_path.exists():
        try:
            lines = []
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if "=" in line and line.strip().split("=")[0].strip().startswith(f"{prefix}_"):
                    continue
                lines.append(line)
            env_path.write_text("\n".join(lines) + "\n")
        except Exception:
            pass

    log_activity(
        user=user,
        action="ACCOUNT_DELETE",
        account=acc_id,
        channel="all",
        details={"deleted_id": acc_id},
        status="success",
    )
    return {"ok": True}


@app.get("/api/credentials")
def get_credentials(
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
    current_user: dict = Depends(get_current_user),
):
    require_tenant_access(account, current_user)
    """
    Return saved credentials from the server so any device/operator on the team
    instantly shares the single source of truth without re-entering keys.
    """
    _load_env_file()
    acc = account.lower().strip()
    chan = channel.lower().strip()
    prefix = _account_prefix(acc)
    is_tata = acc == "tata"
    is_bajaj = acc == "bajaj"

    w_tok_key = (
        "TATA_WABA_AUTH_TOKEN" if is_tata else ("BAJAJ_WABA_AUTH_TOKEN" if is_bajaj else f"{prefix}_WABA_AUTH_TOKEN")
    )
    w_id_key = "TATA_WABA_ID" if is_tata else ("BAJAJ_WABA_ID" if is_bajaj else f"{prefix}_WABA_ID")
    b_tok_key = (
        "TATA_KARIX_BEARER_TOKEN"
        if is_tata
        else ("BAJAJ_KARIX_BEARER_TOKEN" if is_bajaj else f"{prefix}_KARIX_BEARER_TOKEN")
    )
    s_key = "TATA_KARIX_SESSION" if is_tata else ("BAJAJ_KARIX_SESSION" if is_bajaj else f"{prefix}_KARIX_SESSION")
    u_key = "TATA_KARIX_USER" if is_tata else ("BAJAJ_KARIX_USER" if is_bajaj else f"{prefix}_KARIX_USER")
    e_id_key = "TATA_ENTITY_ID" if is_tata else ("BAJAJ_ENTITY_ID" if is_bajaj else f"{prefix}_ENTITY_ID")
    l_ck_key = (
        "TATA_KARIX_LOUNGE_COOKIE"
        if is_tata
        else ("BAJAJ_KARIX_LOUNGE_COOKIE" if is_bajaj else f"{prefix}_KARIX_LOUNGE_COOKIE")
    )

    waba_id = os.environ.get(w_id_key) or (BAJAJ_WABA_ID if is_bajaj else "")
    # Strict tenant separation: display ONLY this account's own tokens.
    # Never surface the parent TATA_* session here — it belongs to a different
    # portal login (e.g. TATACAPPROMO) and showing it under TCHFL made it look
    # like TCHFL was configured when it wasn't.
    waba_auth_token = os.environ.get(w_tok_key) or (os.environ.get("WABA_AUTH_TOKEN") if is_bajaj else "")
    bearer_token = os.environ.get(b_tok_key) or (os.environ.get("KARIX_BEARER_TOKEN") if is_bajaj else "")
    session = os.environ.get(s_key) or (os.environ.get("KARIX_SESSION") if is_bajaj else "")
    user = os.environ.get(u_key) or (os.environ.get("KARIX_USER") if is_bajaj else "")
    entity_id = os.environ.get(e_id_key) or ("110100001654" if is_bajaj else "1001490234791338781")
    lounge_cookie = os.environ.get(l_ck_key) or (os.environ.get("KARIX_LOUNGE_COOKIE") if is_bajaj else "")
    portal_username = os.environ.get(f"{prefix}_PORTAL_USER") or ""
    portal_password = os.environ.get(f"{prefix}_PORTAL_PASSWORD") or ""
    template_namespace_id = (
        os.environ.get(f"{prefix}_TEMPLATE_NAMESPACE_ID")
        or (os.environ.get("TATA_TEMPLATE_NAMESPACE_ID") if acc in TATA_SUB_ACCOUNTS else "")
        or "42eec6e7_6287_4b1d_8ec8_52f4a80c23b5"
    )

    return {
        "account": acc,
        "channel": chan,
        "waba_id": waba_id or "",
        "waba_auth_token": waba_auth_token or "",
        "bearer_token": bearer_token or "",
        "session": session or "",
        "user": user or "",
        "portal_username": portal_username or "",
        "portal_password": portal_password or "",
        "template_namespace_id": template_namespace_id or "42eec6e7_6287_4b1d_8ec8_52f4a80c23b5",
        "entity_id": entity_id or "",
        "lounge_cookie": lounge_cookie or "",
        "is_configured": bool(waba_id and waba_auth_token) if chan == "whatsapp" else bool(entity_id),
    }


def _build_wa_credentials_mapping(creds: CredentialUpdate, prefix: str, is_tata: bool, is_bajaj: bool) -> dict:
    mapping = {}
    fields = [
        (creds.waba_auth_token, "TATA_WABA_AUTH_TOKEN" if is_tata else ("BAJAJ_WABA_AUTH_TOKEN" if is_bajaj else f"{prefix}_WABA_AUTH_TOKEN")),
        (creds.waba_id, "TATA_WABA_ID" if is_tata else ("BAJAJ_WABA_ID" if is_bajaj else f"{prefix}_WABA_ID")),
        (creds.bearer_token, "TATA_KARIX_BEARER_TOKEN" if is_tata else ("BAJAJ_KARIX_BEARER_TOKEN" if is_bajaj else f"{prefix}_KARIX_BEARER_TOKEN")),
        (creds.session, "TATA_KARIX_SESSION" if is_tata else ("BAJAJ_KARIX_SESSION" if is_bajaj else f"{prefix}_KARIX_SESSION")),
        (creds.user, "TATA_KARIX_USER" if is_tata else ("BAJAJ_KARIX_USER" if is_bajaj else f"{prefix}_KARIX_USER")),
        (creds.portal_username, f"{prefix}_PORTAL_USER"),
        (creds.portal_password, f"{prefix}_PORTAL_PASSWORD"),
        (creds.template_namespace_id, f"{prefix}_TEMPLATE_NAMESPACE_ID"),
        (creds.entity_id, "TATA_ENTITY_ID" if is_tata else ("BAJAJ_ENTITY_ID" if is_bajaj else f"{prefix}_ENTITY_ID")),
        (creds.lounge_cookie, "TATA_KARIX_LOUNGE_COOKIE" if is_tata else ("BAJAJ_KARIX_LOUNGE_COOKIE" if is_bajaj else f"{prefix}_KARIX_LOUNGE_COOKIE")),
    ]
    for val, key in fields:
        if val is not None and val.strip():
            v = val.strip()
            mapping[key] = v
            os.environ[key] = v
    return mapping


@app.put("/api/credentials")
def update_credentials(creds: CredentialUpdate, current_user: dict = Depends(get_current_user)):
    require_tenant_access(creds.account, current_user)
    env_path = Path(".env")
    acc = creds.account.lower().strip()
    chan = creds.channel.lower().strip()
    prefix = _account_prefix(acc)
    is_tata = acc == "tata"
    is_bajaj = acc == "bajaj"

    mapping = _build_wa_credentials_mapping(creds, prefix, is_tata, is_bajaj) if chan == "whatsapp" else {}
    if not mapping:
        return {"ok": True}
    # 1. Update .env file
    try:
        lines: list[str] = []
        seen: set[str] = set()
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k = stripped.split("=", 1)[0].strip()
                    if k in mapping:
                        lines.append(f"{k}={mapping[k]}")
                        seen.add(k)
                    else:
                        lines.append(line)
                else:
                    lines.append(line)

        for k, v in mapping.items():
            if k not in seen:
                lines.append(f"{k}={v}")

        env_path.write_text("\n".join(lines) + "\n")
    except Exception:
        pass

    # 2. Update persistent credentials.json
    try:
        cred_json_path = Path("credentials.json")
        saved_creds = {}
        if cred_json_path.exists():
            try:
                saved_creds = json.loads(cred_json_path.read_text(encoding="utf-8"))
            except Exception:
                saved_creds = {}
        saved_creds.update(mapping)
        cred_json_path.write_text(json.dumps(saved_creds, indent=2) + "\n", encoding="utf-8")
    except Exception as ex:
        logger.warning("Could not write credentials.json: %s", ex)

    # 3. Persist to the GitHub repo so tokens survive Render's ephemeral
    # filesystem and every deploy/restart — "write once, works on all
    # devices" until the session itself expires. Requires GITHUB_TOKEN and
    # GITHUB_REPO env vars; silently skipped when not configured.
    gh_status = _commit_credentials_to_github()

    log_activity(
        user=creds.user_name or "Anonymous Operator",
        action="CREDENTIALS_UPDATE",
        account=acc,
        channel=chan,
        details={"keys_updated": list(mapping.keys()), "github_persisted": gh_status},
        status="success",
    )
    return {"ok": True, "github_persisted": gh_status}


def _commit_credentials_to_github() -> str | None:
    """Commit credentials.json to the configured GitHub repo. Returns status string or None."""
    import base64

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")  # e.g. "dugadnaman/whitelisting-agent"
    if not token or not repo:
        return None
    try:
        import requests as _rq

        api = f"https://api.github.com/repos/{repo}/contents/credentials.json"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        r = _rq.get(api, headers=headers, timeout=10)
        if not r.ok and r.status_code in (401, 403):
            reason = r.json().get("message", r.text[:120]) if "json" in r.headers.get("content-type", "") else r.text[:120]
            logger.warning("GitHub credentials access denied: HTTP %s: %s", r.status_code, reason)
            return f"failed_http_{r.status_code}: {reason}"
        sha = r.json().get("sha") if r.ok else None
        content = base64.b64encode(Path("credentials.json").read_bytes()).decode()
        payload = {
            "message": "chore: update saved credentials from Settings",
            "content": content,
        }
        if sha:
            payload["sha"] = sha
        r = _rq.put(api, headers=headers, json=payload, timeout=15)
        if r.status_code in (200, 201):
            logger.info("credentials.json committed to GitHub (%s)", repo)
            return "committed"
        logger.warning("GitHub credentials commit failed: HTTP %s: %s", r.status_code, r.text[:200])
        try:
            gh_reason = r.json().get("message", r.text[:120])
        except Exception:
            gh_reason = r.text[:120]
        return f"failed_http_{r.status_code}: {gh_reason}"
    except Exception as exc:
        logger.warning("GitHub credentials commit error: %s", exc)
        return "error"


def _test_rcs_channel(acc: str, acc_name: str, creds: CredentialUpdate | None) -> dict:
    try:
        entity_id = (
            creds.entity_id.strip() if creds and creds.entity_id and creds.entity_id.strip() else None
        ) or get_rcs_entity_id(acc)
        headers = get_rcs_auth_headers(acc)
        resp = http_client.get(
            "https://karix.solutions/lounge/LoungePage/dltRegistration.php",
            headers=headers,
            timeout=15,
        )
        has_auth = "sign_in" not in resp.url and resp.status_code == 200
        if has_auth or entity_id:
            return {
                "ok": True,
                "message": f"RCS Configured for {acc_name} (Entity ID: {entity_id or 'Configured'})",
            }
        return {
            "ok": False,
            "message": f"RCS Session/Cookie for {acc_name} returned {resp.status_code}",
        }
    except Exception as exc:
        return {"ok": False, "message": f"RCS Test error for {acc_name}: {exc}"}


def _test_whatsapp_channel(
    acc: str, acc_name: str, prefix: str, is_tata: bool, is_bajaj: bool, creds: CredentialUpdate | None, w_id_key: str, w_tok_key: str
) -> dict:
    results = []
    try:
        waba_id = (
            (creds.waba_id.strip() if creds and creds.waba_id and creds.waba_id.strip() else None)
            or os.environ.get(f"{prefix}_WABA_ID")
            or (BAJAJ_WABA_ID if is_bajaj else "")
        )
        if not waba_id:
            return {
                "ok": False,
                "message": f"{acc_name} WhatsApp: Please enter the WABA ID in the field above or set {w_id_key} in Settings.",
            }

        token = (
            (
                creds.waba_auth_token.strip()
                if creds and creds.waba_auth_token and creds.waba_auth_token.strip()
                else None
            )
            or os.environ.get(f"{prefix}_WABA_AUTH_TOKEN")
            or os.environ.get("TATA_WABA_AUTH_TOKEN" if acc in TATA_SUB_ACCOUNTS else "BAJAJ_WABA_AUTH_TOKEN")
            or (os.environ.get("WABA_AUTH_TOKEN") if is_bajaj else os.environ.get("TATA_KARIX_BEARER_TOKEN"))
        )
        if not token:
            return {
                "ok": False,
                "message": f"{acc_name} WhatsApp: Please enter the WABA API Token in the field above or set {w_tok_key} in Settings.",
            }
        headers = {"Authentication": f"Bearer {token}"}
        resp = http_client.get(
            f"{OFFICIAL_TEMPLATE_BASE_URL}/{waba_id}",
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                try:
                    data = json.loads(resp.text)
                except Exception:
                    data = {}
            count = len(data.get("response", {}).get("templates", []))
            results.append(f"{acc_name} WhatsApp: Valid ({count} templates on WABA {waba_id})")
        elif resp.status_code == 401:
            results.append(
                f"{acc_name} WhatsApp: 401 Unauthorized — The API token or WABA ID ({waba_id}) is incorrect."
            )
        else:
            results.append(f"{acc_name} WhatsApp: HTTP {resp.status_code} ({resp.text[:200]})")
    except Exception as exc:
        results.append(f"{acc_name} WhatsApp: {exc}")
    is_ok = any("Valid" in r for r in results)
    log_activity(
        user=(creds.user_name if creds and creds.user_name else "Anonymous Operator"),
        action="CREDENTIALS_TEST",
        account=acc,
        channel="whatsapp",
        details={"message": " | ".join(results), "valid": is_ok},
        status="success" if is_ok else "failed",
    )
    return {"ok": is_ok, "message": " | ".join(results)}


@app.post("/api/test-credentials")
def test_credentials(
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
    creds: CredentialUpdate | None = None,
    current_user: dict = Depends(get_current_user),
):
    body_fields = creds.model_fields_set if creds else set()
    acc = (creds.account if creds and "account" in body_fields else account).lower().strip()
    require_tenant_access(acc, current_user)
    chan = (creds.channel if creds and "channel" in body_fields else channel).lower().strip()
    acc_name = get_account_name(acc)
    prefix = _account_prefix(acc)
    is_tata = acc == "tata"
    is_bajaj = acc == "bajaj"
    _load_env_file()

    w_id_key = "TATA_WABA_ID" if is_tata else ("BAJAJ_WABA_ID" if is_bajaj else f"{prefix}_WABA_ID")
    w_tok_key = (
        "TATA_WABA_AUTH_TOKEN" if is_tata else ("BAJAJ_WABA_AUTH_TOKEN" if is_bajaj else f"{prefix}_WABA_AUTH_TOKEN")
    )
    e_id_key = "TATA_ENTITY_ID" if is_tata else ("BAJAJ_ENTITY_ID" if is_bajaj else f"{prefix}_ENTITY_ID")
    l_ck_key = (
        "TATA_KARIX_LOUNGE_COOKIE"
        if is_tata
        else ("BAJAJ_KARIX_LOUNGE_COOKIE" if is_bajaj else f"{prefix}_KARIX_LOUNGE_COOKIE")
    )

    # Apply any supplied creds directly to environment in memory
    if creds:
        if creds.waba_id and creds.waba_id.strip():
            os.environ[w_id_key] = creds.waba_id.strip()
        if creds.waba_auth_token and creds.waba_auth_token.strip():
            os.environ[w_tok_key] = creds.waba_auth_token.strip()
        if creds.entity_id and creds.entity_id.strip():
            os.environ[e_id_key] = creds.entity_id.strip()
        if creds.lounge_cookie and creds.lounge_cookie.strip():
            os.environ[l_ck_key] = creds.lounge_cookie.strip()

    if chan == "rcs":
        return _test_rcs_channel(acc, acc_name, creds)
    return _test_whatsapp_channel(acc, acc_name, prefix, is_tata, is_bajaj, creds, w_id_key, w_tok_key)

@app.get("/api/sample-csv")
def get_sample_csv(channel: str = Query("whatsapp")):
    chan = channel.lower()
    if chan == "rcs":
        sample_path = Path("rcs_templates_sample.csv")
        filename = "rcs_templates_sample.csv"
    else:
        sample_path = Path("templates_sample.csv")
        filename = "whatsapp_templates_sample.csv"

    if sample_path.exists():
        return FileResponse(
            str(sample_path),
            media_type="text/csv",
            filename=filename,
        )
    return PlainTextResponse("template_name,body\nexample_1,Sample message text\n")


@app.get("/api/activity")
def get_activity_logs(
    user: str = Query("all"),
    action: str = Query("all"),
    account: str = Query("all"),
    channel: str = Query("all"),
    search: str = Query(""),
    limit: int = Query(200),
    current_user: dict = Depends(get_current_user),
):
    tenant = current_user.get("tenant_id", "all")
    if tenant != "all" and current_user.get("role") != "superadmin":
        account = tenant
    records = load_activities(
        user=user if user != "all" else None,
        action=action if action != "all" else None,
        account=account if account != "all" else None,
        channel=channel if channel != "all" else None,
        search=search if search else None,
        limit=limit,
    )
    return [_json_safe(r) for r in records]


@app.get("/api/users")
def list_users():
    """Return all registered operator accounts."""
    return [_json_safe(u) for u in get_all_users()]


@app.post("/api/users")
def register_user_endpoint(body: UserRegister):
    """Create or switch operator profile."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="User name cannot be empty.")
    u = register_or_update_user(name, body.role or "Operator")
    log_activity(
        user=name,
        action="USER_LOGIN",
        account="all",
        channel="all",
        details={"name": name, "role": body.role or "Operator"},
        status="success",
    )
    return _json_safe(u)


@app.get("/api/activity/stats")
def get_activity_stats():
    summary = get_activity_summary()
    return _json_safe(summary)


@app.post("/api/activity")
def record_custom_activity(
    user: str = Query("Anonymous Operator"),
    action: str = Query("CUSTOM_EVENT"),
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
    details: dict = Body(default={}),
):
    rec = log_activity(
        user=user,
        action=action,
        account=account,
        channel=channel,
        details=details,
        status="success",
    )
    return _json_safe(rec)


# ---------------------------------------------------------------------------
# Autonomous Agent Endpoint
# ---------------------------------------------------------------------------

from agent import agent_instance


class AgentChatRequest(BaseModel):
    message: str
    account: str = "bajaj"
    channel: str = "whatsapp"
    user: str = "Operator"
    history: list[dict] = []


@app.post("/api/agent/chat")
def agent_chat_endpoint(req: AgentChatRequest, current_user: dict = Depends(get_current_user)):
    """
    Autonomous Whitelisting Agent endpoint.
    Accepts natural-language commands to diagnose rejections, auto-remediate copy,
    resubmit compliant templates, inspect catalogs, and sync approvals.
    """
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    require_tenant_access(req.account, current_user)

    res = agent_instance.execute_instruction(
        instruction=req.message,
        account=req.account,
        channel=req.channel,
        user=req.user or current_user.get("name", "Operator"),
        user_profile=current_user,
    )
    return _json_safe(res)
