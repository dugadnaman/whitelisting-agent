"""
FastAPI backend for the Karix WhatsApp & RCS template whitelisting tool.

Supports multiple accounts (Bajaj, Tata Capital) and multiple channels (WhatsApp, RCS).
Wraps the existing Python pipelines and exposes REST endpoints consumed by the Next.js frontend.
"""

import logging
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

import requests as http_client
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from config import (
    BAJAJ_ESMEADDR,
    KARIX_BASE_URL,
    OFFICIAL_TEMPLATE_BASE_URL,
    get_esmeaddr,
    get_official_auth_headers,
    get_portal_auth_headers,
    get_waba_id,
)
from loader import load_from_csv, load_from_excel
from models import ApprovalStatus
from runner import poll_pending, run_file
from submission_client import _STATUS_MAP
from tracker import load_log, pending_entries

# RCS pipeline imports
from rcs_config import (
    KARIX_DLT_ACTION_URL,
    get_rcs_auth_headers,
    get_rcs_entity_id,
)
from rcs_client import fetch_rcs_templates
from rcs_loader import load_rcs_from_csv, load_rcs_from_excel
from rcs_runner import run_rcs_file
from rcs_tracker import load_rcs_log

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


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CredentialUpdate(BaseModel):
    account: str = "bajaj"  # "bajaj" | "tata"
    channel: str = "whatsapp"  # "whatsapp" | "rcs"
    waba_auth_token: str | None = None
    waba_id: str | None = None
    bearer_token: str | None = None
    session: str | None = None
    user: str | None = None
    entity_id: str | None = None
    lounge_cookie: str | None = None


# ---------------------------------------------------------------------------
def _clean_error_message(err) -> str | None:
    """Flatten error strings or nested error dictionaries into a clean message."""
    if not err:
        return None
    if isinstance(err, str):
        return err
    if isinstance(err, dict):
        if "error" in err and isinstance(err["error"], dict):
            return err["error"].get("message") or err["error"].get("error_user_msg") or str(err)
        if "message" in err:
            return str(err["message"])
        if "reason" in err:
            return _clean_error_message(err["reason"])
        return str(err)
    return str(err)


def fetch_whatsapp_templates(client: str = "bajaj") -> list[dict]:
    """Fetch live templates directly from Karix WhatsApp API."""
    acc = client.lower()
    try:
        waba_id = get_waba_id(acc)
        headers = get_official_auth_headers(acc)
        resp = http_client.get(
            f"{OFFICIAL_TEMPLATE_BASE_URL}/{waba_id}",
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json() if "json" in resp.headers.get("content-type", "").lower() else {}
            return data.get("response", {}).get("templates", [])
    except Exception as e:
        logger.warning("Could not fetch live WhatsApp templates for %s: %s", acc, e)
    return []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/stats")
def get_stats(
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
):
    acc = account.lower()
    chan = channel.lower()
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
            merged.append({
                "template_name": name,
                "status": "submitted" if status_str in ("PENDING", "APPROVED", "SUBMITTED") else "failed",
                "approval_status": status_str.lower(),
            })
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
        approval_val = _STATUS_MAP.get(status_str, ApprovalStatus.UNKNOWN).value if status_str in _STATUS_MAP else status_str.lower()
        merged.append({
            "template_name": name,
            "status": "submitted",
            "approval_status": approval_val,
        })
        seen_names.add(name.lower())

    for le in local_entries:
        if le.get("template_name", "").lower() not in seen_names:
            merged.append(le)

    total = len(merged)
    submitted = sum(1 for e in merged if e.get("status") == "submitted")
    failed = sum(1 for e in merged if e.get("status") == "failed")
    pending = sum(1 for e in merged if e.get("approval_status") == "pending")
    approved = sum(1 for e in merged if e.get("approval_status") == "approved")
    rejected = sum(1 for e in merged if e.get("approval_status") == "rejected")
    return {
        "total": total,
        "submitted": submitted,
        "failed": failed,
        "pending": pending,
        "approved": approved,
        "rejected": rejected,
        "duplicate": 0,
    }

@app.get("/api/templates")
def get_templates(
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
    status: str | None = Query(None),
    search: str | None = Query(None),
):
    acc = account.lower()
    chan = channel.lower()

    if chan == "rcs":
        local_entries = load_rcs_log(RCS_LOG_PATH)
        local_entries = [e for e in local_entries if (e.get("client", "bajaj") or "bajaj").lower() == acc]

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
            }
            merged_entries.append(entry)
            seen_names.add(name.lower())

        for le in local_entries:
            if le.get("template_name", "").lower() not in seen_names:
                merged_entries.append(le)

        if status and isinstance(status, str):
            s_val = status.lower()
            merged_entries = [
                e for e in merged_entries
                if str(e.get("status", "")).lower() == s_val or str(e.get("approval_status", "")).lower() == s_val
            ]

        if search and isinstance(search, str):
            q = search.lower()
            merged_entries = [
                e for e in merged_entries
                if q in str(e.get("template_name", "")).lower()
                or q in str(e.get("template_id", "")).lower()
                or q in str(e.get("source_ref", "")).lower()
            ]
        merged_entries.sort(key=lambda e: e.get("submitted_at", ""), reverse=True)
        return merged_entries
    # WhatsApp
    local_entries = load_log(LOG_PATH)
    local_entries = [e for e in local_entries if (e.get("client", "bajaj") or "bajaj").lower() == acc]

    live_templates = fetch_whatsapp_templates(client=acc)
    seen_names = set()
    merged_entries = []

    for lt in live_templates:
        name = lt.get("template_name") or str(lt.get("fb_template_id", ""))
        status_str = str(lt.get("template_create_status", "PENDING")).upper()
        approval_val = _STATUS_MAP.get(status_str, ApprovalStatus.UNKNOWN).value if status_str in _STATUS_MAP else status_str.lower()

        entry = {
            "source_ref": name,
            "template_name": name,
            "status": "submitted",
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
        }
        merged_entries.append(entry)
        seen_names.add(name.lower())

    for le in local_entries:
        if le.get("template_name", "").lower() not in seen_names:
            le_clean = dict(le)
            le_clean["error"] = _clean_error_message(le.get("error"))
            merged_entries.append(le_clean)

    if status and isinstance(status, str):
        s_val = status.lower()
        merged_entries = [
            e for e in merged_entries
            if str(e.get("approval_status", "")).lower() == s_val or str(e.get("status", "")).lower() == s_val
        ]

    if search and isinstance(search, str):
        q = search.lower()
        merged_entries = [
            e for e in merged_entries
            if q in str(e.get("template_name", "")).lower()
            or q in str(e.get("source_ref", "")).lower()
            or q in str(e.get("provider_ref_id", "")).lower()
        ]

    merged_entries.sort(key=lambda e: e.get("submitted_at", ""), reverse=True)
    return merged_entries


@app.post("/api/preview")
async def preview_file(
    file: UploadFile = File(...),
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
):
    suffix = Path(file.filename or "upload.csv").suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    chan = channel.lower()
    try:
        if chan == "rcs":
            if suffix in (".xlsx", ".xls"):
                submissions = load_rcs_from_excel(tmp_path, client=account)
            else:
                submissions = load_rcs_from_csv(tmp_path, client=account)
            return [asdict(s) for s in submissions]

        # WhatsApp
        if suffix in (".xlsx", ".xls"):
            submissions = load_from_excel(tmp_path, client=account)
        else:
            submissions = load_from_csv(tmp_path, client=account)
        for s in submissions:
            s.client = account
        return [asdict(s) for s in submissions]
    finally:
        os.unlink(tmp_path)


@app.post("/api/submit")
async def submit_file(
    file: UploadFile = File(...),
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
):
    suffix = Path(file.filename or "upload.csv").suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    acc = account.lower()
    chan = channel.lower()
    try:
        if chan == "rcs":
            before_count = len(load_rcs_log(RCS_LOG_PATH))
            run_rcs_file(tmp_path, RCS_LOG_PATH, client=acc)
            all_entries = load_rcs_log(RCS_LOG_PATH)
            new_entries = all_entries[before_count:]
            return {"submitted": len(new_entries), "results": new_entries}

        # WhatsApp
        before_count = len(load_log(LOG_PATH))
        run_file(tmp_path, LOG_PATH, client=acc)
        all_entries = load_log(LOG_PATH)
        new_entries = all_entries[before_count:]
        return {"submitted": len(new_entries), "results": new_entries}
    except Exception as exc:
        logger.exception("Submission failed for %s (%s): %s", acc, chan, exc)
        raise HTTPException(
            status_code=400,
            detail=f"Submission failed for {acc} ({chan}): {str(exc)}",
        )
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.post("/api/poll")
def poll(
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
):
    acc = account.lower()
    chan = channel.lower()

    if chan != "whatsapp":
        return {"checked": 0}
    all_pending = pending_entries(LOG_PATH)
    matching = [e for e in all_pending if (e.get("client", "bajaj") or "bajaj").lower() == acc]
    poll_pending(LOG_PATH, client=acc)
    return {"checked": len(matching)}


@app.put("/api/credentials")
def update_credentials(creds: CredentialUpdate):
    env_path = Path(".env")
    acc = creds.account.lower()
    chan = creds.channel.lower()
    is_tata = acc == "tata"
    mapping = {}
    if chan == "whatsapp":
        if creds.waba_auth_token is not None and creds.waba_auth_token.strip():
            key = "TATA_WABA_AUTH_TOKEN" if is_tata else "WABA_AUTH_TOKEN"
            val = creds.waba_auth_token.strip()
            mapping[key] = val
            os.environ[key] = val
        if creds.waba_id is not None and creds.waba_id.strip():
            key = "TATA_WABA_ID" if is_tata else "BAJAJ_WABA_ID"
            val = creds.waba_id.strip()
            mapping[key] = val
            os.environ[key] = val
        if creds.bearer_token is not None and creds.bearer_token.strip():
            key = "TATA_KARIX_BEARER_TOKEN" if is_tata else "KARIX_BEARER_TOKEN"
            val = creds.bearer_token.strip()
            mapping[key] = val
            os.environ[key] = val
        if creds.session is not None and creds.session.strip():
            key = "TATA_KARIX_SESSION" if is_tata else "KARIX_SESSION"
            val = creds.session.strip()
            mapping[key] = val
            os.environ[key] = val
        if creds.user is not None and creds.user.strip():
            key = "TATA_KARIX_USER" if is_tata else "KARIX_USER"
            val = creds.user.strip()
            mapping[key] = val
            os.environ[key] = val
    elif chan == "rcs":
        if creds.entity_id is not None and creds.entity_id.strip():
            key = "TATA_ENTITY_ID" if is_tata else "BAJAJ_ENTITY_ID"
            val = creds.entity_id.strip()
            mapping[key] = val
            os.environ[key] = val
        if creds.lounge_cookie is not None and creds.lounge_cookie.strip():
            key = "TATA_KARIX_LOUNGE_COOKIE" if is_tata else "KARIX_LOUNGE_COOKIE"
            val = creds.lounge_cookie.strip()
            mapping[key] = val
            os.environ[key] = val

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
        import json
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

    return {"ok": True}


@app.post("/api/test-credentials")
def test_credentials(
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
    creds: CredentialUpdate | None = None,
):
    acc = (creds.account if creds and creds.account else account).lower()
    chan = (creds.channel if creds and creds.channel else channel).lower()
    acc_name = "Tata Capital" if acc == "tata" else "Bajaj"
    is_tata = acc == "tata"
    # Apply any supplied creds directly to environment in memory
    if creds:
        if creds.waba_id and creds.waba_id.strip():
            os.environ["TATA_WABA_ID" if is_tata else "BAJAJ_WABA_ID"] = creds.waba_id.strip()
        if creds.waba_auth_token and creds.waba_auth_token.strip():
            os.environ["TATA_WABA_AUTH_TOKEN" if is_tata else "WABA_AUTH_TOKEN"] = creds.waba_auth_token.strip()
        if creds.entity_id and creds.entity_id.strip():
            os.environ["TATA_ENTITY_ID" if is_tata else "BAJAJ_ENTITY_ID"] = creds.entity_id.strip()
        if creds.lounge_cookie and creds.lounge_cookie.strip():
            os.environ["TATA_KARIX_LOUNGE_COOKIE" if is_tata else "KARIX_LOUNGE_COOKIE"] = creds.lounge_cookie.strip()

    if chan == "rcs":
        try:
            entity_id = (creds.entity_id.strip() if creds and creds.entity_id and creds.entity_id.strip() else None) or get_rcs_entity_id(acc)
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

    # WhatsApp
    results = []
    try:
        waba_id = (
            (creds.waba_id.strip() if creds and creds.waba_id and creds.waba_id.strip() else None)
            or os.environ.get("TATA_WABA_ID" if is_tata else "BAJAJ_WABA_ID")
            or (BAJAJ_WABA_ID if not is_tata else None)
        )
        if not waba_id:
            return {
                "ok": False,
                "message": f"{acc_name} WhatsApp: Please enter the WABA ID in the field above or set {'TATA_WABA_ID' if is_tata else 'BAJAJ_WABA_ID'} in Render Environment.",
            }

        token = (
            (creds.waba_auth_token.strip() if creds and creds.waba_auth_token and creds.waba_auth_token.strip() else None)
            or os.environ.get("TATA_WABA_AUTH_TOKEN" if is_tata else "WABA_AUTH_TOKEN")
        )
        if not token:
            return {
                "ok": False,
                "message": f"{acc_name} WhatsApp: Please enter the WABA API Token in the field above or set {'TATA_WABA_AUTH_TOKEN' if is_tata else 'WABA_AUTH_TOKEN'} in Render Environment.",
            }

        headers = {"Authentication": f"Bearer {token}"}
        resp = http_client.get(
            f"{OFFICIAL_TEMPLATE_BASE_URL}/{waba_id}",
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json() if "json" in resp.headers.get("content-type", "").lower() else {}
            count = len(data.get("response", {}).get("templates", []))
            results.append(f"{acc_name} WhatsApp: Valid ({count} templates on WABA {waba_id})")
        elif resp.status_code == 401:
            results.append(f"{acc_name} WhatsApp: 401 Unauthorized — The API token or WABA ID ({waba_id}) is incorrect.")
        else:
            results.append(f"{acc_name} WhatsApp: HTTP {resp.status_code} ({resp.text[:200]})")
    except Exception as exc:
        results.append(f"{acc_name} WhatsApp: {exc}")
    is_ok = any("Valid" in r for r in results)
    return {"ok": is_ok, "message": " | ".join(results)}

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
