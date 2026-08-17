"""
FastAPI backend for the Karix WhatsApp & RCS template whitelisting tool.

Supports multiple accounts (Bajaj, Tata Capital) and multiple channels (WhatsApp, RCS).
Wraps the existing Python pipelines and exposes REST endpoints consumed by the Next.js frontend.
"""

import os
import tempfile
from dataclasses import asdict
from pathlib import Path

import requests as http_client
from fastapi import FastAPI, File, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

# WhatsApp pipeline imports
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
from runner import poll_pending, run_file
from tracker import load_log, pending_entries

# RCS pipeline imports
from rcs_config import (
    KARIX_DLT_ACTION_URL,
    get_rcs_auth_headers,
    get_rcs_entity_id,
)
from rcs_loader import load_rcs_from_csv, load_rcs_from_excel
from rcs_runner import run_rcs_file
from rcs_tracker import load_rcs_log

# ---------------------------------------------------------------------------

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
        entries = load_rcs_log(RCS_LOG_PATH)
        entries = [e for e in entries if (e.get("client", "bajaj") or "bajaj").lower() == acc]
        total = len(entries)
        submitted = sum(1 for e in entries if e.get("status") == "submitted")
        failed = sum(1 for e in entries if e.get("status") == "failed")
        duplicate = sum(1 for e in entries if e.get("status") == "duplicate")
        return {
            "total": total,
            "submitted": submitted,
            "failed": failed,
            "duplicate": duplicate,
            "pending": 0,
            "approved": 0,
            "rejected": 0,
        }

    # WhatsApp
    entries = load_log(LOG_PATH)
    entries = [e for e in entries if (e.get("client", "bajaj") or "bajaj").lower() == acc]
    total = len(entries)
    submitted = sum(1 for e in entries if e.get("status") == "submitted")
    failed = sum(1 for e in entries if e.get("status") == "failed")
    pending = sum(
        1 for e in entries
        if e.get("status") == "submitted" and e.get("approval_status") == "pending"
    )
    approved = sum(1 for e in entries if e.get("approval_status") == "approved")
    rejected = sum(1 for e in entries if e.get("approval_status") == "rejected")
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
        entries = load_rcs_log(RCS_LOG_PATH)
        entries = [e for e in entries if (e.get("client", "bajaj") or "bajaj").lower() == acc]

        if status:
            entries = [e for e in entries if e.get("status") == status]

        if search:
            q = search.lower()
            entries = [
                e for e in entries
                if q in str(e.get("template_name", "")).lower()
                or q in str(e.get("template_id", "")).lower()
                or q in str(e.get("source_ref", "")).lower()
            ]

        entries.sort(key=lambda e: e.get("submitted_at", ""), reverse=True)
        return entries

    # WhatsApp
    entries = load_log(LOG_PATH)
    entries = [e for e in entries if (e.get("client", "bajaj") or "bajaj").lower() == acc]

    if status:
        entries = [
            e for e in entries
            if e.get("approval_status") == status or e.get("status") == status
        ]

    if search:
        q = search.lower()
        entries = [
            e for e in entries
            if q in str(e.get("template_name", "")).lower()
            or q in str(e.get("source_ref", "")).lower()
            or q in str(e.get("provider_ref_id", "")).lower()
        ]

    entries.sort(key=lambda e: e.get("submitted_at", ""), reverse=True)
    return entries


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
                submissions = load_rcs_from_excel(tmp_path)
            else:
                submissions = load_rcs_from_csv(tmp_path)
            return [asdict(s) for s in submissions]

        # WhatsApp
        if suffix in (".xlsx", ".xls"):
            submissions = load_from_excel(tmp_path)
        else:
            submissions = load_from_csv(tmp_path)
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
    finally:
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

    mapping = {}
    is_tata = acc == "tata"

    if chan == "whatsapp":
        if creds.waba_auth_token is not None and creds.waba_auth_token.strip():
            key = "TATA_WABA_AUTH_TOKEN" if is_tata else "WABA_AUTH_TOKEN"
            mapping[key] = creds.waba_auth_token.strip()
        if creds.waba_id is not None and creds.waba_id.strip():
            key = "TATA_WABA_ID" if is_tata else "BAJAJ_WABA_ID"
            mapping[key] = creds.waba_id.strip()
        if creds.bearer_token is not None and creds.bearer_token.strip():
            key = "TATA_KARIX_BEARER_TOKEN" if is_tata else "KARIX_BEARER_TOKEN"
            mapping[key] = creds.bearer_token.strip()
        if creds.session is not None and creds.session.strip():
            key = "TATA_KARIX_SESSION" if is_tata else "KARIX_SESSION"
            mapping[key] = creds.session.strip()
        if creds.user is not None and creds.user.strip():
            key = "TATA_KARIX_USER" if is_tata else "KARIX_USER"
            mapping[key] = creds.user.strip()
    elif chan == "rcs":
        if creds.entity_id is not None and creds.entity_id.strip():
            key = "TATA_ENTITY_ID" if is_tata else "BAJAJ_ENTITY_ID"
            mapping[key] = creds.entity_id.strip()
        if creds.lounge_cookie is not None and creds.lounge_cookie.strip():
            key = "TATA_KARIX_LOUNGE_COOKIE" if is_tata else "KARIX_LOUNGE_COOKIE"
            mapping[key] = creds.lounge_cookie.strip()
        if creds.bearer_token is not None and creds.bearer_token.strip():
            key = "TATA_KARIX_BEARER_TOKEN" if is_tata else "KARIX_BEARER_TOKEN"
            mapping[key] = creds.bearer_token.strip()

    if not mapping:
        return {"ok": True}

    lines: list[str] = []
    seen: set[str] = set()
    if env_path.exists():
        for line in env_path.read_text().splitlines():
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

    for k, v in mapping.items():
        os.environ[k] = v

    return {"ok": True}


@app.post("/api/test-credentials")
def test_credentials(
    account: str = Query("bajaj"),
    channel: str = Query("whatsapp"),
):
    acc = account.lower()
    chan = channel.lower()
    acc_name = "Tata Capital" if acc == "tata" else "Bajaj"

    if chan == "rcs":
        try:
            entity_id = get_rcs_entity_id(acc)
            headers = get_rcs_auth_headers(acc)
            # Test pinging DLT URL
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
        waba_id = get_waba_id(acc)
        official_headers = get_official_auth_headers(acc)
        resp = http_client.get(
            f"{OFFICIAL_TEMPLATE_BASE_URL}/{waba_id}",
            headers=official_headers,
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json() if "json" in resp.headers.get("content-type", "").lower() else {}
            count = len(data.get("response", {}).get("templates", []))
            results.append(f"{acc_name} WhatsApp: Valid ({count} templates on WABA {waba_id})")
        else:
            results.append(f"{acc_name} WhatsApp Official API: HTTP {resp.status_code}")
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
