"""Authenticated, fixed-route broker for the isolated Apparel attribution worker."""
from __future__ import annotations

import ipaddress
import json
import os
import re
from datetime import date
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.datastructures import UploadFile

from auth import get_current_user

router = APIRouter(prefix="/api/apparel/attribution", tags=["Apparel attribution"])
WORKER_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=15.0, pool=5.0)
ID_PATTERN = r"^[A-Za-z0-9_-]{1,128}$"
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SheetRequest(StrictRequest):
    spreadsheet_url: str = Field(min_length=10, max_length=2048)
    worksheet_name: str = Field(default="Mastersheet", min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_sheet(self):
        sheet_id(self.spreadsheet_url)
        if not self.worksheet_name.strip():
            raise ValueError("Worksheet name cannot be blank")
        return self


class SetupRequest(SheetRequest):
    ui_config: dict[str, Any]


class SessionRequest(StrictRequest):
    profile_id: str = Field(default="default", min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_profile(self):
        if self.profile_id != "default" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", self.profile_id):
            raise ValueError("Choose default or a corporate email profile")
        return self


class JobRequest(StrictRequest):
    sheet_connection_id: str = Field(pattern=ID_PATTERN)
    overwrite_existing: bool = False
    row_limit: int | None = Field(default=None, ge=1, le=10000)
    brands: list[str] = Field(min_length=1, max_length=50)
    channels: list[str] = Field(min_length=1, max_length=10)
    sent_date: date | None = None
    sent_date_from: date | None = None
    sent_date_to: date | None = None
    agipl_attribution_brand: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_selection(self):
        if any(not value.strip() or len(value) > 120 for value in self.brands + self.channels):
            raise ValueError("Brand and channel selections must be nonempty")
        validate_dates(self.sent_date, self.sent_date_from, self.sent_date_to, required=True)
        target = (self.agipl_attribution_brand or "").strip()
        if any(brand.casefold() == "agipl" for brand in self.brands) and not target:
            raise ValueError("Choose an attribution brand for AGIPL")
        if target.casefold() == "agipl":
            raise ValueError("AGIPL cannot attribute campaigns to itself")
        return self


def validate_dates(single, start, end, *, required=False):
    if single and (start or end):
        raise ValueError("Use a sent date or a date range, not both")
    if bool(start) != bool(end):
        raise ValueError("Both sent-date range bounds are required")
    if start and end and not 0 <= (end - start).days <= 366:
        raise ValueError("Sent-date range must be ordered and at most 366 days")
    if required and not (single or start):
        raise ValueError("Choose a sent date or a date range")


def sheet_id(value: str) -> str:
    try:
        parsed = urlsplit(value)
        match = re.fullmatch(r"/spreadsheets/d/([A-Za-z0-9_-]{10,200})(?:/(?:edit|view|preview|copy))?/?", parsed.path)
        if (parsed.scheme != "https" or parsed.hostname != "docs.google.com"
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or not match
                or any(char.isspace() for char in value)):
            raise ValueError
        return match.group(1)
    except (ValueError, TypeError):
        raise ValueError("Choose a valid HTTPS Google Sheets URL") from None


def worker_configuration() -> tuple[str, str]:
    url = os.environ.get("APPAREL_ATTRIBUTION_WORKER_URL", "")
    token = os.environ.get("APPAREL_ATTRIBUTION_TOKEN", "")
    try:
        if (len(token) < 32 or len(set(token)) < 10 or not token.isascii()
                or any(char.isspace() or ord(char) < 33 or ord(char) > 126 for char in token)
                or re.search(r"change.?me|placeholder|replace.?me|your[-_ ]|example|default", token, re.I)
                or any(token == (token[:n] * ((len(token) + n - 1) // n))[:len(token)] for n in range(1, len(token) // 2 + 1))):
            raise ValueError
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if (not host or parsed.scheme not in {"http", "https"}
                or parsed.username is not None or parsed.password is not None
                or "?" in url or "#" in url or parsed.path not in {"", "/"}
                or any(char.isspace() for char in url) or "\\" in url
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
            private = address.is_loopback or (address.is_private and not (
                address.is_unspecified or address.is_multicast or address.is_link_local or address.is_reserved
            ))
        except ValueError:
            if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
                raise ValueError
            private = host == "localhost" or host.endswith(".internal")
        if parsed.scheme == "http" and not private:
            raise ValueError
        return url.rstrip("/"), token
    except (ValueError, TypeError):
        raise HTTPException(503, "Apparel attribution worker is not configured securely") from None


async def apparel_identity(user: dict = Depends(get_current_user)) -> dict:
    identity = user.get("sub") or user.get("id")
    if not identity or identity == "usr_anon":
        raise HTTPException(401, "Authentication required")
    if user.get("role") != "superadmin" and not (
        user.get("tenant_id") == "apparel" and user.get("role") in {"operator", "admin"}
    ):
        raise HTTPException(403, "Apparel attribution access required")
    return user


async def apparel_admin(user: dict = Depends(apparel_identity)) -> dict:
    if user.get("role") not in {"admin", "superadmin"}:
        raise HTTPException(403, "Apparel administrator access required")
    return user


def worker_transport():
    """Default HTTP transport; dependency injection keeps router tests offline."""
    return None


class Gateway:
    def __init__(self, client: httpx.AsyncClient, user: dict, token: str):
        self.client = client
        self.user = user
        self.token = token

    @property
    def admin(self):
        return self.user.get("role") in {"admin", "superadmin"}

    async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            upstream = await self.client.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise HTTPException(504, "Apparel attribution worker timed out") from None
        except httpx.RequestError:
            raise HTTPException(502, "Apparel attribution worker is unavailable") from None
        if 300 <= upstream.status_code < 400:
            raise HTTPException(502, "Apparel attribution worker returned an unexpected redirect")
        return upstream

    def safe_json(self, upstream: httpx.Response, *, session=False, redactions=()):
        try:
            payload = upstream.json()
        except ValueError:
            raise HTTPException(502, "Apparel attribution worker returned an invalid response") from None

        def clean(value, key=""):
            if isinstance(value, dict):
                result = {}
                for key, item in value.items():
                    if key.casefold() in {"password", "private_key", "private_key_id", "credentials", "token", "access_token", "refresh_token"}:
                        continue
                    if not self.admin and key in {"login_url", "browser_login_url"}:
                        result[key] = None
                    else:
                        result[key] = clean(item, key)
                return result
            if isinstance(value, list):
                return [clean(item, key) for item in value]
            if isinstance(value, str):
                value = value.replace(self.token, "[redacted]")
                for secret in redactions:
                    if secret:
                        value = value.replace(secret, "[redacted]")
                value = re.sub(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "[redacted private key]", value, flags=re.DOTALL)
                # Login links can appear in messages/errors, not just login_url.
                if not self.admin and (session or key in {"message", "error", "detail"}):
                    value = URL_PATTERN.sub("[redacted URL]", value)
                return value
            return value

        return clean(payload)

    def response(self, upstream: httpx.Response, *, session=False):
        return JSONResponse(self.safe_json(upstream, session=session), status_code=upstream.status_code)


async def gateway(
    user: dict = Depends(apparel_identity),
    transport=Depends(worker_transport),
):
    url, token = worker_configuration()
    actor = str(user.get("sub") or user.get("id") or user.get("email"))
    if not actor.isascii() or len(actor) > 254 or any(ord(char) < 32 or ord(char) == 127 for char in actor):
        raise HTTPException(401, "Verified identity is invalid")
    async with httpx.AsyncClient(
        base_url=url + "/api/", headers={"X-Apparel-Attribution-Token": token, "X-Apparel-Actor": actor},
        timeout=WORKER_TIMEOUT, follow_redirects=False, trust_env=False, transport=transport,
    ) as client:
        yield Gateway(client, user, token)


@router.get("/health")
async def health(worker: Gateway = Depends(gateway)):
    upstream = await worker.request("GET", "health")
    payload = worker.safe_json(upstream)
    if isinstance(payload, dict):
        payload["worker_configured"] = True
    return JSONResponse(payload, status_code=upstream.status_code)


@router.get("/google/config")
async def google_config(worker: Gateway = Depends(gateway)):
    return worker.response(await worker.request("GET", "google/config"))


@router.post("/google/connect")
async def google_connect(payload: SheetRequest, worker: Gateway = Depends(gateway)):
    if not worker.admin:
        config_response = await worker.request("GET", "google/config")
        if config_response.status_code != 200:
            return worker.response(config_response)
        config = worker.safe_json(config_response)
        if not isinstance(config, dict) or not config.get("configured") or not config.get("spreadsheet_url") or not config.get("worksheet_name"):
            raise HTTPException(503, "The approved Apparel sheet has not been configured")
        try:
            approved_id = sheet_id(config["spreadsheet_url"])
        except ValueError:
            raise HTTPException(503, "The approved Apparel sheet has not been configured") from None
        if sheet_id(payload.spreadsheet_url) != approved_id or payload.worksheet_name != config["worksheet_name"]:
            raise HTTPException(403, "Connect only the approved Apparel sheet and worksheet")
    return worker.response(await worker.request("POST", "google/connect", json=payload.model_dump(mode="json")))


@router.get("/google/connections/{connection_id}/campaigns")
async def campaigns(
    connection_id: str = Path(pattern=ID_PATTERN),
    brands: list[str] = Query(default=[]), channels: list[str] = Query(default=[]),
    sent_date_from: date | None = None, sent_date_to: date | None = None,
    limit: int = Query(default=100, ge=1, le=250), worker: Gateway = Depends(gateway),
):
    try:
        validate_dates(None, sent_date_from, sent_date_to)
        if len(brands) > 50 or len(channels) > 10 or any(not value.strip() or len(value) > 120 for value in brands + channels):
            raise ValueError("Invalid brand or channel selection")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    params = [("brands", value) for value in brands] + [("channels", value) for value in channels]
    params.append(("limit", str(limit)))
    if sent_date_from:
        params.extend([("sent_date_from", sent_date_from.isoformat()), ("sent_date_to", sent_date_to.isoformat())])
    return worker.response(await worker.request("GET", f"google/connections/{connection_id}/campaigns", params=params))


@router.get("/moengage/session")
async def session(worker: Gateway = Depends(gateway)):
    return worker.response(await worker.request("GET", "moengage/session"), session=True)


@router.post("/moengage/session/start", dependencies=[Depends(apparel_admin)])
async def session_start(payload: SessionRequest, worker: Gateway = Depends(gateway)):
    return worker.response(await worker.request("POST", "moengage/session/start", json=payload.model_dump()), session=True)


@router.post("/moengage/session/reset", dependencies=[Depends(apparel_admin)])
async def session_reset(payload: SessionRequest, worker: Gateway = Depends(gateway)):
    return worker.response(await worker.request("POST", "moengage/session/reset", json=payload.model_dump()), session=True)


@router.get("/jobs")
async def jobs(worker: Gateway = Depends(gateway)):
    return worker.response(await worker.request("GET", "jobs"))


@router.post("/jobs")
async def job_start(payload: JobRequest, worker: Gateway = Depends(gateway)):
    return worker.response(await worker.request("POST", "jobs", json=payload.model_dump(mode="json")))


@router.get("/jobs/{job_id}")
async def job(job_id: str = Path(pattern=ID_PATTERN), worker: Gateway = Depends(gateway)):
    return worker.response(await worker.request("GET", f"jobs/{job_id}"))


@router.post("/jobs/{job_id}/cancel")
async def cancel(job_id: str = Path(pattern=ID_PATTERN), worker: Gateway = Depends(gateway)):
    return worker.response(await worker.request("POST", f"jobs/{job_id}/cancel"))


@router.post("/jobs/{job_id}/retry-failed")
async def retry(job_id: str = Path(pattern=ID_PATTERN), worker: Gateway = Depends(gateway)):
    return worker.response(await worker.request("POST", f"jobs/{job_id}/retry-failed"))


@router.get("/jobs/{job_id}/results.csv")
async def results(job_id: str = Path(pattern=ID_PATTERN), worker: Gateway = Depends(gateway)):
    upstream = await worker.request("GET", f"jobs/{job_id}/results.csv")
    if upstream.status_code != 200:
        return worker.response(upstream)
    content_type = upstream.headers.get("content-type", "")
    if content_type.split(";", 1)[0].lower() not in {"text/csv", "application/csv"}:
        raise HTTPException(502, "Apparel attribution worker returned an invalid CSV response")
    match = re.search(r'(?:^|;)\s*filename="?([A-Za-z0-9][A-Za-z0-9._-]*\.csv)"?(?:;|$)', upstream.headers.get("content-disposition", ""), re.I)
    filename = match.group(1) if match and len(match.group(1)) <= 150 else f"attribution-{job_id}.csv"
    return Response(upstream.content, status_code=upstream.status_code, headers={
        "Content-Type": content_type, "Content-Disposition": f'attachment; filename="{filename}"',
    })


@router.get("/setup", dependencies=[Depends(apparel_admin)])
async def setup(worker: Gateway = Depends(gateway)):
    return worker.response(await worker.request("GET", "setup"))


@router.put("/setup", dependencies=[Depends(apparel_admin)])
async def setup_update(payload: SetupRequest, worker: Gateway = Depends(gateway)):
    return worker.response(await worker.request("PUT", "setup", json=payload.model_dump(mode="json")))


@router.post("/google/credentials", dependencies=[Depends(apparel_admin)])
async def credentials(request: Request, worker: Gateway = Depends(gateway)):
    async with request.form() as form:
        items = list(form.multi_items())
        if len(items) != 1 or items[0][0] != "credential" or not isinstance(items[0][1], UploadFile):
            raise HTTPException(422, "Upload only the credential .json file")
        credential = items[0][1]
        if not (credential.filename or "").lower().endswith(".json"):
            raise HTTPException(422, "Choose a .json service-account key")
        contents = await credential.read(2 * 1024 * 1024 + 1)
        if not contents or len(contents) > 2 * 1024 * 1024:
            raise HTTPException(422, "Service-account key must be nonempty and at most 2 MiB")
        upstream = await worker.request("POST", "google/credentials", files={"credential": ("credential.json", contents, "application/json")})
    # Preserve actionable worker conflicts without reflecting an uploaded key.
    redactions = [contents.decode("utf-8", errors="replace")]
    try:
        key = json.loads(contents)
        if isinstance(key, dict):
            redactions.extend(value for name, value in key.items() if name in {"private_key", "private_key_id"} and isinstance(value, str))
    except (ValueError, UnicodeDecodeError):
        pass  # Worker remains responsible for validating the actual credential.
    return JSONResponse(worker.safe_json(upstream, redactions=redactions), status_code=upstream.status_code)
