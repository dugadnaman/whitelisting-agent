"""Tata-only, session-authenticated MoEngage unique click counts."""

from datetime import UTC, date, datetime, timedelta
from http.cookies import CookieError, SimpleCookie
import os
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import jwt
import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from auth import configured_jwt_secret, get_current_user, require_tenant_access
from moengage_sync import decode_moengage_token_expiry, get_moengage_config

CLICK_EVENTS = (
    "MOE_WHATSAPP_CLICKED",
    "MOE_EMAIL_CLICK",
    "MOE_SMS_CLICKED",
    "NOTIFICATION_CLICKED_MOE",
    "NOTIFICATION_CLICKED_IOS_MOE",
)


def validate_identifier(value: str, label: str, *, object_id: bool = False) -> str:
    pattern = r"[a-fA-F0-9]{24}" if object_id else r"[A-Za-z0-9_-]{1,128}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise HTTPException(status_code=400, detail=f"Invalid {label}.")
    return value


def base_metadata(base: dict, workspace: dict) -> dict:
    """Portal's offset-free created_time is UTC, not the workspace's wall time."""
    created = base.get("created_time")
    try:
        if not isinstance(created, str):
            raise ValueError
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])?", created):
            raise ValueError
        instant = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=UTC)
        timezone = ZoneInfo(workspace["timezone"])
        created_at = instant.astimezone(UTC).isoformat()
        start_date = instant.astimezone(timezone).date().isoformat()
    except (ValueError, TypeError, KeyError, OverflowError, ZoneInfoNotFoundError):
        raise HTTPException(status_code=502, detail="MoEngage returned an invalid base creation time or workspace timezone.") from None
    return {
        "id": base["id"],
        "name": base["name"],
        "created_at": created_at,
        "start_date": start_date,
        "timezone": workspace["timezone"],
    }


def validate_end_date(end_date: str, timezone: str | None = None) -> date:
    try:
        if not isinstance(end_date, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", end_date):
            raise ValueError
        end = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="End date must be a valid YYYY-MM-DD date.") from None
    if timezone is None:
        return end
    try:
        today = datetime.now(ZoneInfo(timezone)).date()
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise HTTPException(status_code=502, detail="MoEngage returned an invalid workspace timezone.") from None
    if end > today:
        raise HTTPException(status_code=400, detail="End date cannot be after today in the selected workspace.")
    return end


def click_count_payload(base: dict, end_date: str) -> dict:
    end = validate_end_date(end_date, base["timezone"])
    if end < date.fromisoformat(base["start_date"]):
        raise HTTPException(status_code=400, detail="End date cannot be before the imported base's creation date.")
    # Portal absolute ranges encode workspace calendar dates with a literal Z.
    # Preserve that observed contract rather than converting these bounds to UTC.
    time_range = {
        "period_unit": "days", "type": "between", "value_type": "absolute",
        "value": base["start_date"] + "T00:00:00.000Z",
        "value1": end.isoformat() + "T23:59:59.999Z",
    }
    actions = [{
        "action_name": event,
        "attributes": {"filter_operator": "and", "filters": []},
        "executed": True,
        "execution": {"count": 1, "type": "atleast"},
        "filter_type": "actions",
        "primary_time_range": time_range.copy(),
    } for event in CLICK_EVENTS]
    return {
        "channel_source": "all",
        "filters": {"included_filters": {
            "filter_operator": "and",
            "filters": [
                {"filter_operator": "or", "filter_type": "nested_filters", "filters": actions},
                {"filter_type": "custom_segments", "id": base["id"], "name": base["name"]},
            ],
        }},
        "reachability": {
            "email": {"aggregated_count_required": True},
            "push": {"aggregated_count_required": True, "platforms": ["ANDROID", "iOS", "web"]},
            "sms": {"aggregated_count_required": True},
            "whatsapp": {"aggregated_count_required": True},
        },
    }


def query_result(row: dict, query_id: str, db_name: str) -> dict:
    if row.get("_id") != query_id or row.get("db_name") != db_name:
        raise HTTPException(status_code=404, detail="Query not found in the selected workspace.")
    result = {"query_id": query_id, "status": row.get("status"), "user_count": None, "reachable_users": None}
    if result["status"] in ("failed", "failure"):
        result["status"] = "failed"
        # Never echo provider failure_reason: it can include session data or raw queries.
        result["error"] = "MoEngage could not complete this query. No user count is available. You may submit a new query."
    elif result["status"] == "success":
        count = row.get("user_count")
        reachability = row.get("reachability_count")
        reachable = reachability.get("total_reachable_count") if isinstance(reachability, dict) else None
        if (type(count) is not int or not 0 <= count <= 9007199254740991
                or type(reachable) is not int or not 0 <= reachable <= count):
            raise HTTPException(status_code=502, detail="MoEngage completed the query without valid unique and reachable user counts.")
        result.update(user_count=count, reachable_users=reachable)
    elif result["status"] == "received":
        result["status"] = "queued"
    elif result["status"] not in ("queued", "running"):
        raise HTTPException(status_code=502, detail="MoEngage returned an unrecognized query status.")
    return result


SESSION_ERROR = "The Tata MoEngage portal session is missing or expired. Ask an administrator to refresh the Tata bearer token, refresh token, and cookie in Settings → MoEngage."
TATA_PORTAL_ACCOUNT_ID = "6399ced48c5fa78ad1eb39ea"


class ClickCountClient:
    def __init__(self):
        config = get_moengage_config("tata")
        token = config["bearer_token"].strip()
        if not token or decode_moengage_token_expiry(token).get("expired"):
            raise HTTPException(status_code=503, detail=SESSION_ERROR)
        refresh_token = config.get("refresh_token", "").strip()
        if not refresh_token:
            raise HTTPException(status_code=503, detail="The Tata MoEngage portal refresh token is missing. Ask an administrator to copy the browser refreshtoken header into Settings → MoEngage.")
        self.base_url = config["base_url"].rstrip("/")
        if not re.fullmatch(r"https://dashboard(?:-\d+)?\.moengage\.com", self.base_url):
            raise HTTPException(status_code=503, detail="Configure a valid Tata MoEngage dashboard HTTPS URL in Settings.")
        self.headers = {
            "authorization": token if token.lower().startswith("bearer ") else f"Bearer {token}",
            "refreshtoken": refresh_token,
            "content-type": "application/json", "accept": "application/json",
            "origin": self.base_url,
            "referer": self.base_url + "/v4/segments",
            "page": "segments",
        }
        if config["cookie"]:
            self.headers["cookie"] = config["cookie"]
        self.account_id = os.environ.get("TATA_MOENGAGE_ACCOUNT_ID", TATA_PORTAL_ACCOUNT_ID)
        self.source_headers = self.headers.copy()

    def request(self, method: str, path: str, *, body: dict | None = None, params: dict | None = None) -> dict:
        try:
            response = requests.request(
                method, self.base_url + path, headers=self.headers,
                json=body, params=params, timeout=(10, 45), allow_redirects=False,
            )
        except requests.Timeout:
            detail = ("MoEngage query submission timed out; it may already be queued. No automatic resubmission was attempted."
                      if method == "POST" and "/count" in path else "MoEngage timed out. Try loading again.")
            raise HTTPException(status_code=504, detail=detail) from None
        except (requests.exceptions.InvalidHeader, UnicodeError):
            raise HTTPException(status_code=503, detail="The Tata MoEngage session headers are malformed. Copy the bearer token, refresh token and cookie again in Settings.") from None
        except requests.RequestException:
            raise HTTPException(status_code=502, detail="Cannot reach MoEngage. Check the Tata dashboard URL and network connectivity.") from None
        if response.status_code in (401, 403) or 300 <= response.status_code < 400:
            raise HTTPException(status_code=503, detail=SESSION_ERROR)
        if response.status_code == 429:
            raise HTTPException(status_code=503, detail="MoEngage is rate limiting requests. Wait before trying again.")
        if not response.ok:
            raise HTTPException(status_code=502, detail=f"MoEngage rejected the request (HTTP {response.status_code}). Ask an administrator to check the Tata session.") from None
        if response.cookies:
            try:
                cookies = SimpleCookie()
                cookies.load(self.headers.get("cookie", ""))
                for cookie in response.cookies:
                    cookies[cookie.name] = cookie.value
                self.headers["cookie"] = "; ".join(f"{cookie.key}={cookie.coded_value}" for cookie in cookies.values())
            except CookieError:
                raise HTTPException(status_code=502, detail="MoEngage returned invalid session cookies.") from None
        try:
            data = response.json()
        except (ValueError, RecursionError):
            raise HTTPException(status_code=502, detail="MoEngage returned an invalid response. Refresh the Tata session in Settings.") from None
        if not isinstance(data, dict):
            raise HTTPException(status_code=502, detail="MoEngage returned an unexpected response.")
        code = data.get("code")
        if isinstance(code, str) and re.fullmatch(r"[0-9]{3}", code):
            code = int(code)
            data["code"] = code
        if code is not None and type(code) is not int:
            raise HTTPException(status_code=502, detail="MoEngage returned an invalid response code.")
        # New-auth-stack responses can report the legacy UI-session flag as false.
        # Only their explicit success envelope overrides that flag; schemas below
        # still have to supply the required workspace/base/query data.
        explicit_success = code == 200 and data.get("status") == "success"
        if (data.get("loggedIn") is False and not explicit_success) or (path.startswith("/dash/auth/") and (
                data.get("status") in ("failure", "failed", "error")
                or type(code) is int and code >= 400)):
            raise HTTPException(status_code=503, detail=SESSION_ERROR)
        if (data.get("success") is False or data.get("status") in ("failure", "failed", "error")
                or type(code) is int and code >= 400):
            raise HTTPException(status_code=502, detail="MoEngage could not complete the request. Ask an administrator to check the Tata portal session.")
        return data

    def authorized_apps(self) -> list[dict]:
        data = self.request("GET", "/dash/auth/listApps")
        rows = data.get("data")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise HTTPException(status_code=502, detail="MoEngage returned an invalid workspace list.")
        apps = [row for row in rows if row.get("account_id") == self.account_id
                and row.get("activated") is True and row.get("is_test") is False]
        if any(not isinstance(row.get("id"), str) or not re.fullmatch(r"[a-fA-F0-9]{24}", row["id"])
               or not isinstance(row.get("name"), str) or not row["name"].strip() for row in apps):
            raise HTTPException(status_code=502, detail="MoEngage returned invalid Tata workspace details.")
        if len({row["id"] for row in apps}) != len(apps):
            raise HTTPException(status_code=502, detail="MoEngage returned duplicate Tata workspace identities.")
        if not apps:
            raise HTTPException(status_code=503, detail="The configured portal session has no active workspaces in the authorized Tata account. Ask an administrator to check the session and account ID.")
        return apps

    def bases(self, workspace: dict | None = None) -> list[dict]:
        if workspace is not None:
            try:
                ZoneInfo(workspace["timezone"])
            except (KeyError, ValueError, TypeError, ZoneInfoNotFoundError):
                raise HTTPException(status_code=502, detail="MoEngage returned an invalid workspace timezone.") from None
        if not hasattr(self, "_bases_cache") or self._bases_cache is None:
            result = self.request("POST", "/v2/custom-segments/dashboard",
                                  params={"archived": "false"}, body={})
            rows = result.get("custom_segments")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise HTTPException(status_code=502, detail="MoEngage returned an invalid imported-base list.")
            bases = []
            for row in rows:
                if (row.get("source") != "IMPORT_USERS" or row.get("type") != "FILE_V2"
                        or row.get("deleted") is True or row.get("archived") is True):
                    continue
                if any(flag in row and type(row[flag]) is not bool for flag in ("deleted", "archived")):
                    raise HTTPException(status_code=502, detail="MoEngage returned an invalid imported-base lifecycle state.")
                if (not isinstance(row.get("id"), str) or not re.fullmatch(r"[a-fA-F0-9]{24}", row["id"])
                        or not isinstance(row.get("name"), str) or not row["name"].strip()):
                    raise HTTPException(status_code=502, detail="MoEngage returned an invalid imported base.")
                item = {"id": row["id"], "name": row["name"]}
                if isinstance(row.get("created_time"), str):
                    item["_created_time"] = row["created_time"]
                bases.append(item)
            if len({row["id"] for row in bases}) != len(bases):
                raise HTTPException(status_code=502, detail="MoEngage returned duplicate imported-base identities.")
            self._bases_cache = bases
        result_bases = []
        for item in self._bases_cache:
            entry = {"id": item["id"], "name": item["name"]}
            if workspace and "_created_time" in item:
                try:
                    meta = base_metadata({"id": item["id"], "name": item["name"], "created_time": item["_created_time"]}, workspace)
                    entry["start_date"] = meta["start_date"]
                    entry["created_at"] = meta["created_at"]
                except HTTPException as error:
                    if error.status_code != 502:
                        raise
                    # Optional list timestamps can be absent or invalid; /meta
                    # remains the authoritative fallback and query validation.
            result_bases.append(entry)
        return result_bases

    def activate(self, app: dict) -> dict:
        # Imported-base membership is scoped to the currently activated app.
        # Clear before switching so failed switches cannot retain old membership.
        self._bases_cache = None
        self.headers = self.source_headers.copy()
        switched = self.request("GET", "/dash/auth/changeApp",
                                params={"sls_enabled": "true", "app_id": app["id"]})
        data = switched.get("data")
        token = data.get("bearer") if isinstance(data, dict) else None
        if (switched.get("code") != 200 or switched.get("status") != "success"
                or not isinstance(token, str) or not token or data.get("app_access_details") != "ALLOWED"):
            raise HTTPException(status_code=503, detail="MoEngage did not grant access to the selected Tata workspace. Refresh the Tata session in Settings.")
        self.headers["authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        if isinstance(data.get("refresh_token"), str) and data["refresh_token"]:
            self.headers["refreshtoken"] = data["refresh_token"]
        settings = self.request("GET", "/appsettings", params={"api": 1}).get("data")
        timezone = settings.get("time_zone") if isinstance(settings, dict) else None
        try:
            if not isinstance(timezone, str):
                raise ValueError
            ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise HTTPException(status_code=502, detail="MoEngage returned an invalid workspace timezone.") from None
        return {"id": app["id"], "name": app["name"], "timezone": timezone}

    def select_workspace(self, workspace_id: str) -> dict:
        validate_identifier(workspace_id, "workspace ID", object_id=True)
        self._bases_cache = None
        self.headers = self.source_headers.copy()
        apps = self.authorized_apps()
        app = next((row for row in apps if row.get("id") == workspace_id), None)
        if app is None:
            raise HTTPException(status_code=403, detail="The selected workspace is not an authorized Tata workspace.")
        return self.activate(app)

    def workspaces(self) -> list[dict]:
        self._bases_cache = None
        self.headers = self.source_headers.copy()
        return [self.activate(app) for app in self.authorized_apps()]

    def base(self, base_id: str, *, include_db: bool = True) -> tuple[dict, str]:
        validate_identifier(base_id, "base ID", object_id=True)
        if not any(row["id"] == base_id for row in self.bases()):
            raise HTTPException(status_code=404, detail="Imported base not found in the selected workspace.")
        metadata = self.request("GET", f"/v2/custom-segments/dashboard/{base_id}/meta")
        base = metadata.get("cs_details")
        if (not isinstance(base, dict) or base.get("id") != base_id
                or base.get("source") != "IMPORT_USERS" or base.get("type") != "FILE_V2"
                or base.get("deleted") is not False or base.get("archived") is not False
                or not isinstance(base.get("name"), str) or not base["name"].strip()):
            raise HTTPException(status_code=502, detail="MoEngage returned invalid imported-base metadata.")
        # cs_meta is optional; bind queries to the activated workspace, not cached base counts.
        db_name = self.workspace_database() if include_db else ""
        return base, db_name

    def workspace_database(self) -> str:
        profile = self.request("GET", "/getLoggedInUserData", params={"api": 1}).get("data")
        if (not isinstance(profile, dict) or profile.get("account_id") != self.account_id
                or not isinstance(profile.get("dbName"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", profile["dbName"])):
            raise HTTPException(status_code=502, detail="MoEngage returned invalid workspace database metadata.")
        return profile["dbName"]


def sign_query(query_id: str, workspace_id: str, db_name: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode({
        "aud": "tata-click-count", "purpose": "tata-click-count",
        "rq_id": query_id, "workspace_id": workspace_id, "db_name": db_name,
        "iat": now, "exp": now + timedelta(hours=24),
    }, configured_jwt_secret(), algorithm="HS256")


def read_query_ticket(ticket: str, workspace_id: str) -> dict:
    try:
        if not isinstance(ticket, str) or not ticket or len(ticket) > 4096:
            raise jwt.InvalidTokenError
        payload = jwt.decode(ticket, configured_jwt_secret(), algorithms=["HS256"],
                             audience="tata-click-count",
                             options={"strict_aud": True, "require": ["aud", "purpose", "rq_id", "workspace_id", "db_name", "iat", "exp"]})
        if (payload["purpose"] != "tata-click-count" or payload["workspace_id"] != workspace_id
                or not isinstance(payload["db_name"], str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", payload["db_name"])
                or type(payload["iat"]) is not int or type(payload["exp"]) is not int
                or not 0 < payload["exp"] - payload["iat"] <= 86400
                or not isinstance(payload["rq_id"], str)
                or not re.fullmatch(r"[a-fA-F0-9]{24}", payload["rq_id"])):
            raise jwt.InvalidTokenError
    except (jwt.InvalidTokenError, TypeError, KeyError, ValueError, OverflowError, RecursionError):
        raise HTTPException(status_code=404, detail="Query ID is invalid, expired, or belongs to another workspace.") from None
    return payload


def require_click_count_user(user: dict = Depends(get_current_user)) -> dict:
    if not (user.get("id") or user.get("sub")) or user.get("role") == "anonymous":
        raise HTTPException(status_code=401, detail="Valid authentication required.")
    require_tenant_access("tata", user)
    return user


class ClickCountQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    workspace_id: str
    base_id: str
    end_date: str


router = APIRouter(prefix="/api/moengage/click-count", dependencies=[Depends(require_click_count_user)])


@router.get("/workspaces")
def get_workspaces():
    return {"workspaces": ClickCountClient().workspaces()}


@router.get("/bases")
def get_bases(workspace_id: str = Query(...)):
    validate_identifier(workspace_id, "workspace ID", object_id=True)
    client = ClickCountClient()
    workspace = client.select_workspace(workspace_id)
    return {"bases": client.bases(workspace)}


@router.get("/bases/{base_id}")
def get_base(base_id: str, workspace_id: str = Query(...)):
    validate_identifier(workspace_id, "workspace ID", object_id=True)
    validate_identifier(base_id, "base ID", object_id=True)
    client = ClickCountClient()
    workspace = client.select_workspace(workspace_id)
    base, _ = client.base(base_id, include_db=False)
    return base_metadata(base, workspace)


@router.post("/queries")
def create_query(body: ClickCountQueryRequest):
    validate_identifier(body.workspace_id, "workspace ID", object_id=True)
    validate_identifier(body.base_id, "base ID", object_id=True)
    validate_end_date(body.end_date)
    client = ClickCountClient()
    workspace = client.select_workspace(body.workspace_id)
    validate_end_date(body.end_date, workspace["timezone"])
    raw_base, _ = client.base(body.base_id, include_db=False)
    base = base_metadata(raw_base, workspace)
    payload = click_count_payload(base, body.end_date)
    # Invalid provider timestamps and user ranges need no database lookup.
    db_name = client.workspace_database()
    result = client.request("POST", "/segmentation/recent_query/count",
                            params={"api": 1}, body=payload)
    query_id = result.get("rq_id")
    if result.get("success") is not True or not isinstance(query_id, str) or not re.fullmatch(r"[a-fA-F0-9]{24}", query_id):
        raise HTTPException(status_code=502, detail="MoEngage did not confirm a queued query. No automatic resubmission was attempted.")
    return {
        "query_id": sign_query(query_id, workspace["id"], db_name),
        "workspace_id": workspace["id"], "workspace_name": workspace["name"],
        "base_id": base["id"], "base_name": base["name"],
        "start_date": base["start_date"], "end_date": body.end_date,
        "timezone": workspace["timezone"], "status": "queued",
    }


@router.get("/queries/{query_id}")
def get_query(query_id: str, workspace_id: str = Query(...)):
    validate_identifier(workspace_id, "workspace ID", object_id=True)
    ticket = read_query_ticket(query_id, workspace_id)
    client = ClickCountClient()
    client.select_workspace(workspace_id)
    if client.workspace_database() != ticket["db_name"]:
        raise HTTPException(status_code=404, detail="Query not found in the selected workspace.")
    result = client.request("POST", "/segmentation/recent_query/get_bulk",
                            params={"api": 1}, body={"ids": [ticket["rq_id"]], "query_type": "filter"})
    rows = result.get("data")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise HTTPException(status_code=502, detail="MoEngage returned an invalid query result.")
    matching = [row for row in rows if row.get("_id") == ticket["rq_id"]]
    if len(matching) != 1:
        raise HTTPException(status_code=404, detail="Query not found in the selected workspace.")
    response = query_result(matching[0], ticket["rq_id"], ticket["db_name"])
    response["query_id"] = query_id
    return response
