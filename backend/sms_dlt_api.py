"""Authenticated Tata-only VILPOWER session and draft review endpoints."""

import asyncio
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from activity_tracker import log_activity
from auth import get_current_user, require_tenant_access
from portal_sessions import load_session, save_session, session_record
from queue_manager import QUEUE_MANAGER
from sms_dlt import preview_drafts, require_tata, stage_batch

router = APIRouter(prefix="/api/sms-dlt", tags=["SMS DLT"])


def _authorize(account: str, current_user: dict) -> None:
    require_tenant_access(account, current_user)
    try:
        require_tata(account)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


class SessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: Literal["tata"]
    cookie: str = Field(min_length=1, max_length=32000)
    entity_id: str = Field(pattern=r"^[0-9]{10,25}$")


class DraftBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: Literal["tata"]
    templates: list[dict] = Field(min_length=1, max_length=500)


class SubmitBatch(DraftBatch):
    expected_account: Literal["tata"]
    expected_channel: Literal["sms"]
    skip_duplicates: bool = True
    user: str | None = None


@router.post("/brief")
async def import_brief(
    file: UploadFile = File(...),
    account: str = Query(...),
    current_user: dict = Depends(get_current_user),
):
    """Extract client copy for explicit source selection; never access the portal."""
    try:
        _authorize(account, current_user)
        filename = Path((file.filename or "").replace("\\", "/")).name
        suffix = Path(filename).suffix.lower()
        if suffix not in {".xlsx", ".xls"}:
            raise HTTPException(status_code=400, detail="Upload a client brief as XLSX or XLS.")
        from sms_brief import parse_brief

        with tempfile.TemporaryDirectory(prefix="sms-brief-") as directory:
            path = Path(directory) / ("brief" + suffix)
            size = 0
            with path.open("wb") as target:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 20 * 1024 * 1024:
                        raise HTTPException(status_code=413, detail="Client briefs must not exceed 20 MiB.")
                    target.write(chunk)
            if not size:
                raise HTTPException(status_code=400, detail="Uploaded brief is empty.")
            return await asyncio.to_thread(parse_brief, str(path), filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    finally:
        await file.close()


@router.get("/session")
def session_status(account: str = Query(...), current_user: dict = Depends(get_current_user)):
    _authorize(account, current_user)
    record = session_record(account, "sms")
    credentials = load_session(account, "sms") if record else None
    return {"provider": "vilpower", "configured": bool(credentials),
            "entity_id": credentials.get("entity_id", "") if credentials else "",
            "validated_at": record.get("validated_at") if record else None,
            "validation_state": record.get("validation_state", "never") if record else "never"}


@router.put("/session")
def update_session(body: SessionUpdate, account: str = Query("tata"), current_user: dict = Depends(get_current_user)):
    _authorize(body.account, current_user)
    if account != body.account:
        raise HTTPException(status_code=409, detail="SMS session destination changed. Select Tata Capital again.")
    from vilpower_client import VilpowerUnavailable, validate_session
    try:
        snapshot = validate_session(body.cookie, body.entity_id, client=body.account)
    except (ValueError, VilpowerUnavailable) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    save_session(snapshot, body.account, "sms")
    log_activity(user=current_user["name"], action="CREDENTIALS_UPDATE", account=body.account, channel="sms",
                 details={"provider": "vilpower", "storage": "encrypted_database"}, status="success")
    return {"ok": True, "provider": "vilpower", "entity_id": snapshot["entity_id"], "storage": "encrypted_database"}


@router.get("/options")
def options(account: str = Query(...), template_type: str = Query("1"), category_id: str = Query(""),
            search: str = Query(""), service_type: str = Query(""), current_user: dict = Depends(get_current_user)):
    _authorize(account, current_user)
    from vilpower_client import VilpowerUnavailable, fetch_sms_options
    try:
        return fetch_sms_options(client=account, template_type=template_type, category_id=category_id,
                                 search=search, service_type=service_type)
    except (ValueError, VilpowerUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.post("/preview")
def preview(body: DraftBatch, current_user: dict = Depends(get_current_user)):
    _authorize(body.account, current_user)
    from vilpower_client import VilpowerUnavailable
    try:
        return preview_drafts(body.templates, body.account)
    except (ValueError, VilpowerUnavailable) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


async def enqueue(rows: list[dict], account: str, user: str, filename: str, skip_duplicates: bool = True) -> dict:
    from vilpower_client import VilpowerUnavailable
    try:
        job = await asyncio.to_thread(stage_batch, rows, account, user, filename, skip_duplicates)
    except (ValueError, VilpowerUnavailable) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if job["status"] not in {"COMPLETED", "FAILED", "PARTIALLY_COMPLETED"}:
        QUEUE_MANAGER.start_job_execution(job["id"], account, "sms")
    log_activity(user=user, action="TEMPLATE_SUBMISSION", account=account, channel="sms",
                 details={"provider": "vilpower", "job_id": job["id"], "count": len(rows)}, status="success")
    return {"account": account, "channel": "sms", "job_id": job["id"], "status": job["status"],
            "total": job["total_count"], "skipped_duplicates": job["duplicate_count"], "results": []}


@router.post("/submit")
async def submit(body: SubmitBatch, current_user: dict = Depends(get_current_user)):
    _authorize(body.account, current_user)
    return await enqueue(body.templates, body.account, current_user["name"], "SMS DLT reviewed drafts", body.skip_duplicates)
