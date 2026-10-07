"""Offline HTTP integration checks for the Apparel gateway and an ASGI worker."""
import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.testclient import TestClient

import apparel_attribution as gateway
from auth import get_current_user

PREFIX = "/api/apparel/attribution"
TOKEN = "g9T2kP7xV4mQ8zA1wR6nH3cJ5sL0uE_bD"
SHEET_ID = "Approved_Apparel_Sheet_0123456789"
SHEET = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
LOGIN = "https://protected-browser.example/login?ticket=browser-secret"
USER = {"sub": "verified-operator", "email": "operator@company.example", "tenant_id": "apparel", "role": "operator"}
JOB = {"sheet_connection_id": "connection-1", "brands": ["Arrow"], "channels": ["SMS"], "sent_date_from": "2026-09-01", "sent_date_to": "2026-09-07"}
CSV = b'brand,campaign,revenue\r\nArrow,"Campaign, September",123.45\r\n'


class CaptureTransport(httpx.ASGITransport):
    def __init__(self, app, captured):
        super().__init__(app=app)
        self.captured = captured

    async def handle_async_request(self, request):
        self.captured.append({"method": request.method, "url": str(request.url), "headers": dict(request.headers), "timeout": request.extensions.get("timeout")})
        return await super().handle_async_request(request)


@pytest.fixture
def portal(monkeypatch):
    monkeypatch.setenv("APPAREL_ATTRIBUTION_WORKER_URL", "http://worker.railway.internal")
    monkeypatch.setenv("APPAREL_ATTRIBUTION_TOKEN", TOKEN)
    state = {"user": dict(USER), "calls": [], "transport": [], "responses": {}, "configured": True,
             "sheet": SHEET, "worksheet": "Mastersheet", "running": False}
    worker = FastAPI()

    @worker.api_route("/api/{path:path}", methods=["GET", "POST", "PUT"])
    async def worker_route(path: str, request: Request):
        call = {"method": request.method, "path": path, "query": list(request.query_params.multi_items()), "headers": dict(request.headers)}
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            async with request.form() as form:
                call["form"] = [(key, value.filename, await value.read()) for key, value in form.multi_items()]
        else:
            body = await request.body()
            call["body"] = json.loads(body) if body else None
        state["calls"].append(call)
        assert request.headers["x-apparel-attribution-token"] == TOKEN
        override = state["responses"].get((request.method, path))
        if override is not None:
            return override
        if path == "health":
            return {"status": "ok", "configured_brands": ["Arrow"], "google_configured": state["configured"], "moengage_connected": False}
        if path == "google/config" or path == "google/credentials":
            return {"configured": state["configured"], "spreadsheet_url": state["sheet"], "worksheet_name": state["worksheet"], "service_account_email": "fixture@company.example"}
        if path == "google/connect":
            return {"connection_id": "connection-1", "row_count": 1, "preview": [], "warnings": []}
        if path.startswith("moengage/session"):
            return {"status": "waiting_for_login", "profile_id": "default", "profiles": ["default"], "login_url": LOGIN,
                    "message": f"Complete login at {LOGIN}", "nested": {"error": f"Visit {LOGIN}"}}
        if path == "setup":
            if request.method == "PUT" and state["running"]:
                return JSONResponse({"detail": "A job is active"}, status_code=409)
            return {"spreadsheet_url": state["sheet"], "worksheet_name": state["worksheet"], "ui_config": {}, "browser_login_url": LOGIN}
        if path.endswith("results.csv"):
            return Response(CSV, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="september.csv"', "Set-Cookie": "worker-secret=yes", "X-Internal": "private"})
        if path == "jobs" and request.method == "POST":
            state["running"] = True
            return JSONResponse({"job_id": "job-1", "status": "queued"}, status_code=202)
        if path.endswith("retry-failed"):
            return JSONResponse({"job_id": "job-1", "status": "queued"}, status_code=202)
        if path == "jobs":
            return {"jobs": [{"job_id": "job-1", "status": "processing"}] if state["running"] else []}
        if path.startswith("jobs/"):
            return {"job_id": "job-1", "status": "processing"}
        if path.endswith("campaigns"):
            return {"row_count": 1, "preview": [{"brand": "Arrow", "channel": "SMS"}], "warnings": ["Selected-date parse warning"], "warning_sent_date_from": "2026-09-01", "warning_sent_date_to": "2026-09-07"}
        return JSONResponse({"detail": "Unknown worker route"}, status_code=404)

    app = FastAPI()
    app.include_router(gateway.router)
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    app.dependency_overrides[gateway.worker_transport] = lambda: CaptureTransport(worker, state["transport"])
    with TestClient(app) as client:
        yield client, state, app


@pytest.mark.parametrize("tenant,role,status", [("bajaj", "operator", 403), ("tata", "admin", 403), ("all", "operator", 403), ("all", "admin", 403), ("apparel", "viewer", 403), ("apparel", "operator", 200), ("apparel", "admin", 200), ("all", "superadmin", 200)])
def test_verified_tenant_and_role_cannot_be_overridden(portal, tenant, role, status):
    client, state, _ = portal
    state["user"].update(tenant_id=tenant, role=role)
    response = client.get(PREFIX + "/health?account=apparel&tenant_id=apparel&role=superadmin", headers={"X-User": "administrator", "X-Apparel-Actor": "attacker"})
    assert response.status_code == status
    assert len(state["calls"]) == (1 if status == 200 else 0)
    if status == 200:
        assert state["calls"][0]["query"] == []
        assert state["calls"][0]["headers"]["x-apparel-actor"] == USER["sub"]
        assert response.json()["worker_configured"] is True


def test_missing_and_anonymous_identity_never_reaches_worker(portal):
    client, state, app = portal
    state["user"] = {"sub": "usr_anon", "tenant_id": "apparel", "role": "admin"}
    assert client.get(PREFIX + "/health").status_code == 401
    state["user"] = {"tenant_id": "apparel", "role": "admin"}
    assert client.get(PREFIX + "/health").status_code == 401
    app.dependency_overrides.pop(get_current_user)
    assert client.get(PREFIX + "/health", headers={"X-User": "forged-admin"}).status_code == 401
    assert state["calls"] == []


@pytest.mark.parametrize("method,path,body", [("GET", "/setup", None), ("PUT", "/setup", {"spreadsheet_url": SHEET, "worksheet_name": "Mastersheet", "ui_config": {}}), ("POST", "/google/credentials", None), ("POST", "/moengage/session/start", {"profile_id": "default"}), ("POST", "/moengage/session/reset", {"profile_id": "default"})])
def test_admin_actions_deny_operators_before_transport(portal, method, path, body):
    client, state, _ = portal
    assert client.request(method, PREFIX + path, json=body).status_code == 403
    assert state["calls"] == []


@pytest.mark.parametrize("role,tenant", [("admin", "apparel"), ("superadmin", "all")])
def test_admin_routes_forward_known_payloads(portal, role, tenant):
    client, state, _ = portal
    state["user"].update(role=role, tenant_id=tenant)
    assert client.get(PREFIX + "/setup").json()["browser_login_url"] == LOGIN
    setup = {"spreadsheet_url": SHEET, "worksheet_name": "Mastersheet", "ui_config": {"workflow": "recorded_behavior", "query_url_map": {"Arrow": "https://dashboard.moengage.com/reports/arrow"}}}
    assert client.put(PREFIX + "/setup", json=setup).status_code == 200
    assert state["calls"][-1]["body"] == setup
    for action in ("start", "reset"):
        response = client.post(PREFIX + "/moengage/session/" + action, json={"profile_id": "operator@company.example"})
        assert response.status_code == 200
        assert response.json()["login_url"] == LOGIN
        assert state["calls"][-1]["body"] == {"profile_id": "operator@company.example"}
    response = client.post(PREFIX + "/google/credentials", files={"credential": ("fixture.json", b'{"private_key":"fixture-only-no-real-key"}', "application/json")})
    assert response.status_code == 200
    assert state["calls"][-1]["form"] == [("credential", "credential.json", b'{"private_key":"fixture-only-no-real-key"}')]


@pytest.mark.parametrize("method,path", [("POST", "/health"), ("DELETE", "/jobs/job-1"), ("GET", "/healthz"), ("GET", "/docs"), ("POST", "/upload"), ("GET", "/proxy/health"), ("POST", "/jobs/job-1/publish"), ("GET", "/jobs/invalid.id"), ("GET", "/google/connections/invalid.id/campaigns")])
def test_route_and_path_allowlist_blocks_unknown_targets(portal, method, path):
    client, state, _ = portal
    response = client.request(method, PREFIX + path)
    assert response.status_code in {404, 405, 422}
    assert state["calls"] == []


def test_inbound_secrets_never_forwarded_and_timeout_covers_browser_admission(portal):
    client, state, _ = portal
    response = client.post(PREFIX + "/jobs?target=https://attacker.example&account=bajaj", json=JOB, headers={
        "Authorization": "Bearer inbound-jwt", "Cookie": "session=inbound-cookie", "X-Apparel-Attribution-Token": "inbound-machine-token",
        "X-Apparel-Actor": "forged-actor", "X-User": "forged-user", "X-Role": "superadmin",
    })
    assert response.status_code == 202
    call = state["calls"][0]
    assert call["query"] == []
    assert call["body"]["overwrite_existing"] is False
    assert call["headers"]["x-apparel-attribution-token"] == TOKEN
    assert call["headers"]["x-apparel-actor"] == USER["sub"]
    for name in ("authorization", "cookie", "x-user", "x-role"):
        assert name not in call["headers"]
    assert not any("inbound-" in value or "forged-" in value for value in call["headers"].values())
    assert state["transport"][0]["timeout"] == {"connect": 5.0, "read": 120.0, "write": 15.0, "pool": 5.0}


@pytest.mark.parametrize("payload", [dict(JOB, upload_id="workbook"), dict(JOB, account="apparel"), dict(JOB, brands=[""]), dict(JOB, channels=[]), dict(JOB, sent_date_to="2028-09-01"), dict(JOB, sent_date_to="2026-08-01"), dict(JOB, sent_date_to=None), dict(JOB, brands=["AGIPL"]), dict(JOB, brands=["AGIPL"], agipl_attribution_brand="AGIPL")])
def test_invalid_job_schemas_never_reach_worker(portal, payload):
    client, state, _ = portal
    assert client.post(PREFIX + "/jobs", json=payload).status_code == 422
    assert state["calls"] == []


@pytest.mark.parametrize("action", ["start", "reset"])
@pytest.mark.parametrize("payload", [{"profile_id": "default", "password": "must-not-forward"}, {"profile_id": "not-an-email"}, {"profile_id": "default", "tenant_id": "apparel"}])
def test_session_rejects_password_and_identity_fields(portal, action, payload):
    client, state, _ = portal
    state["user"]["role"] = "admin"
    assert client.post(PREFIX + "/moengage/session/" + action, json=payload).status_code == 422
    assert state["calls"] == []


def test_operator_session_redacts_login_url_in_fields_messages_and_errors(portal):
    client, state, _ = portal
    response = client.get(PREFIX + "/moengage/session")
    assert response.json()["login_url"] is None
    assert LOGIN not in response.text and "browser-secret" not in response.text
    state["responses"][("GET", "moengage/session")] = JSONResponse({"detail": f"Login failed; visit {LOGIN}", "login_url": LOGIN}, status_code=409)
    response = client.get(PREFIX + "/moengage/session")
    assert response.status_code == 409 and LOGIN not in response.text
    state["user"]["role"] = "admin"
    assert LOGIN in client.get(PREFIX + "/moengage/session").text


@pytest.mark.parametrize("url,worksheet,expected", [(SHEET.replace("/edit", "/view?gid=1#gid=1"), "Mastersheet", 200), (SHEET.replace(SHEET_ID, "Other_Sheet_0123456789012345"), "Mastersheet", 403), (SHEET, "mastersheet", 403), ("https://attacker.example/spreadsheets/d/Other_1234567890/edit", "Mastersheet", 422)])
def test_operator_connect_checks_sheet_identity_and_exact_worksheet(portal, url, worksheet, expected):
    client, state, _ = portal
    response = client.post(PREFIX + "/google/connect", json={"spreadsheet_url": url, "worksheet_name": worksheet})
    assert response.status_code == expected
    assert [call["path"] for call in state["calls"]] == (["google/config", "google/connect"] if expected == 200 else ["google/config"] if expected == 403 else [])
    assert state["calls"] == [] or state["calls"][0]["method"] == "GET"


@pytest.mark.parametrize("configured,sheet,worksheet", [(False, SHEET, "Mastersheet"), (True, "", "Mastersheet"), (True, "https://invalid.example/sheet", "Mastersheet"), (True, SHEET, "")])
def test_connect_missing_approved_setup_is_genuine_503(portal, configured, sheet, worksheet):
    client, state, _ = portal
    state.update(configured=configured, sheet=sheet, worksheet=worksheet)
    assert client.post(PREFIX + "/google/connect", json={"spreadsheet_url": SHEET, "worksheet_name": "Mastersheet"}).status_code == 503
    assert [call["path"] for call in state["calls"]] == ["google/config"]


def test_approved_reconnect_does_not_cancel_active_job(portal):
    client, state, _ = portal
    assert client.post(PREFIX + "/jobs", json=JOB).status_code == 202
    assert client.post(PREFIX + "/google/connect", json={"spreadsheet_url": SHEET, "worksheet_name": "Mastersheet"}).status_code == 200
    assert state["running"] is True
    assert [call["path"] for call in state["calls"]] == ["jobs", "google/config", "google/connect"]
    state["user"]["role"] = "admin"
    assert client.put(PREFIX + "/setup", json={"spreadsheet_url": SHEET, "worksheet_name": "Mastersheet", "ui_config": {}}).status_code == 409


def test_preview_forwards_only_controlled_repeated_query_and_real_warnings(portal):
    client, state, _ = portal
    response = client.get(PREFIX + "/google/connections/connection-1/campaigns", params=[("brands", "Arrow"), ("brands", "Flying Machine"), ("channels", "SMS"), ("channels", "RCS"), ("sent_date_from", "2026-09-01"), ("sent_date_to", "2026-09-07"), ("limit", "100"), ("account", "bajaj"), ("url", "https://attacker.example")])
    assert response.status_code == 200
    assert response.json()["warnings"] == ["Selected-date parse warning"]
    assert state["calls"][0]["query"] == [("brands", "Arrow"), ("brands", "Flying Machine"), ("channels", "SMS"), ("channels", "RCS"), ("limit", "100"), ("sent_date_from", "2026-09-01"), ("sent_date_to", "2026-09-07")]
    assert client.get(PREFIX + "/google/connections/connection-1/campaigns?sent_date_from=2026-09-01").status_code == 422
    assert len(state["calls"]) == 1


@pytest.mark.parametrize("url", ["", "https://name:secret@worker.example", "https://worker.example/api", "https://worker.example?target=attacker", "https://worker.example#fragment", "http://public.example", "http://8.8.8.8", "http://0.0.0.0", "file:///tmp/worker", "https://worker.example:bad", "https://worker.example/path/../", "https://worker.example\\attacker.example"])
def test_insecure_worker_urls_return_503_without_network(portal, monkeypatch, url):
    client, state, _ = portal
    monkeypatch.setenv("APPAREL_ATTRIBUTION_WORKER_URL", url)
    response = client.get(PREFIX + "/health")
    assert response.status_code == 503
    assert "worker_configured" not in response.json()
    assert "secret@" not in response.text
    assert state["calls"] == [] and state["transport"] == []


@pytest.mark.parametrize("url", ["https://worker.example", "https://worker.example/", "http://127.0.0.1:8000", "http://[::1]:8000", "http://10.1.2.3:8000", "http://worker.railway.internal", "http://worker.internal", "http://localhost:8000"])
def test_secure_fixed_worker_urls_are_accepted(portal, monkeypatch, url):
    client, state, _ = portal
    monkeypatch.setenv("APPAREL_ATTRIBUTION_WORKER_URL", url)
    assert client.get(PREFIX + "/health").status_code == 200
    assert state["transport"][0]["url"] == url.rstrip("/") + "/api/health"


@pytest.mark.parametrize("token", ["", "short", "a" * 64, "0123456789abcdef" * 4, "change-me-to-a-secure-random-token-at-least-32", "your-apparel-attribution-token-placeholder", TOKEN + "\n"])
def test_weak_machine_token_returns_503_and_is_never_exposed(portal, monkeypatch, token):
    client, state, _ = portal
    monkeypatch.setenv("APPAREL_ATTRIBUTION_TOKEN", token)
    response = client.get(PREFIX + "/health")
    assert response.status_code == 503
    assert state["calls"] == []
    if token:
        assert token not in response.text


def test_redirect_does_not_follow_or_forward_location_cookie_or_token(portal):
    client, state, _ = portal
    state["responses"][("GET", "health")] = Response(status_code=307, headers={"Location": "https://attacker.example/token", "Set-Cookie": "secret=yes"})
    response = client.get(PREFIX + "/health")
    assert response.status_code == 502
    assert len(state["calls"]) == 1
    assert "location" not in response.headers and "set-cookie" not in response.headers
    assert TOKEN not in response.text and "attacker.example" not in response.text


@pytest.mark.parametrize("error,status", [(httpx.ConnectError("sensitive transport details"), 502), (httpx.ReadTimeout("sensitive timeout details"), 504), (httpx.ConnectTimeout("sensitive connect details"), 504)])
def test_transport_failures_have_genuine_safe_status(portal, error, status):
    client, state, app = portal

    class FailingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise error

    app.dependency_overrides[gateway.worker_transport] = FailingTransport
    response = client.get(PREFIX + "/jobs")
    assert response.status_code == status
    assert "sensitive" not in response.text and TOKEN not in response.text
    assert state["calls"] == []


def test_worker_status_body_and_machine_secret_redaction(portal):
    client, state, _ = portal
    state["responses"][("GET", "jobs/job-1")] = JSONResponse({"detail": "Job unavailable", "status": "lost", "message": f"unsafe token {TOKEN}"}, status_code=404, headers={"Set-Cookie": "secret=yes"})
    response = client.get(PREFIX + "/jobs/job-1")
    assert response.status_code == 404
    assert response.json()["detail"] == "Job unavailable"
    assert response.json()["status"] == "lost"
    assert TOKEN not in response.text and "set-cookie" not in response.headers
    state["responses"][("GET", "jobs")] = Response(b"<html>secret internal failure</html>", status_code=500, media_type="text/html")
    assert client.get(PREFIX + "/jobs").status_code == 502


def test_jobs_history_status_cancel_and_retry_routes(portal):
    client, state, _ = portal
    assert client.get(PREFIX + "/jobs").json() == {"jobs": []}
    assert client.get(PREFIX + "/jobs/job-1").json()["job_id"] == "job-1"
    assert client.post(PREFIX + "/jobs/job-1/cancel").status_code == 200
    assert client.post(PREFIX + "/jobs/job-1/retry-failed").status_code == 202
    assert [(call["method"], call["path"]) for call in state["calls"]] == [("GET", "jobs"), ("GET", "jobs/job-1"), ("POST", "jobs/job-1/cancel"), ("POST", "jobs/job-1/retry-failed")]


def test_csv_forwards_genuine_bytes_and_safe_download_headers(portal):
    client, state, _ = portal
    response = client.get(PREFIX + "/jobs/job-1/results.csv")
    assert response.status_code == 200 and response.content == CSV
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="september.csv"'
    assert "set-cookie" not in response.headers and "x-internal" not in response.headers
    state["responses"][("GET", "jobs/job-1/results.csv")] = Response(CSV, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="../../unsafe.csv"'})
    response = client.get(PREFIX + "/jobs/job-1/results.csv")
    assert response.content == CSV
    assert response.headers["content-disposition"] == 'attachment; filename="attribution-job-1.csv"'
    state["responses"][("GET", "jobs/job-1/results.csv")] = JSONResponse({"detail": "Results not ready"}, status_code=409)
    response = client.get(PREFIX + "/jobs/job-1/results.csv")
    assert response.status_code == 409 and response.json() == {"detail": "Results not ready"}


def test_credential_extra_form_fields_never_forwarded(portal):
    client, state, _ = portal
    state["user"]["role"] = "admin"
    response = client.post(PREFIX + "/google/credentials", files={"credential": ("fixture.json", b"{}", "application/json")}, data={"account": "apparel"})
    assert response.status_code == 422 and state["calls"] == []


def test_operator_config_preserves_approved_sheet_url(portal):
    client, state, _ = portal
    response = client.get(PREFIX + "/google/config")
    assert response.status_code == 200
    assert response.json()["spreadsheet_url"] == SHEET
    assert response.json()["service_account_email"] == "fixture@company.example"
    assert state["calls"][0]["path"] == "google/config"


@pytest.mark.parametrize("payload", [
    {"spreadsheet_url": "https://attacker.example/sheet", "worksheet_name": "Mastersheet", "ui_config": {}},
    {"spreadsheet_url": SHEET, "worksheet_name": " ", "ui_config": {}},
    {"spreadsheet_url": SHEET, "worksheet_name": "Mastersheet", "ui_config": {}, "account": "bajaj"},
])
def test_setup_rejects_invalid_sheet_and_identity_override(portal, payload):
    client, state, _ = portal
    state["user"]["role"] = "admin"
    assert client.put(PREFIX + "/setup", json=payload).status_code == 422
    assert state["calls"] == []


def test_credentials_preserve_actionable_conflict_without_echoing_key(portal):
    client, state, _ = portal
    state["user"]["role"] = "admin"
    fixture_key = "fixture-private-key-not-a-real-secret"
    state["responses"][("POST", "google/credentials")] = JSONResponse({
        "detail": f"Sealed environment credentials cannot be replaced; update deployment configuration. Rejected key: {fixture_key}",
        "private_key": fixture_key,
    }, status_code=409)
    response = client.post(PREFIX + "/google/credentials", files={
        "credential": ("fixture.json", json.dumps({"private_key": fixture_key}).encode(), "application/json"),
    })
    assert response.status_code == 409
    assert "update deployment configuration" in response.json()["detail"]
    assert fixture_key not in response.text and "private_key" not in response.json()


@pytest.mark.parametrize("name,value", [
    ("APPAREL_ATTRIBUTION_TOKEN", ""),
    ("APPAREL_ATTRIBUTION_WORKER_URL", ""),
])
def test_missing_environment_configuration_cannot_claim_configured(portal, monkeypatch, name, value):
    client, state, _ = portal
    monkeypatch.delenv(name, raising=False)
    response = client.get(PREFIX + "/health")
    assert response.status_code == 503
    assert response.json().get("worker_configured") is not True
    assert state["calls"] == []
