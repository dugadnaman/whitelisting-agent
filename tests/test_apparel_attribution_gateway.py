"""Consumer-facing auth/configuration checks against the embedded attribution module."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import apparel_attribution as gateway

PREFIX = "/api/apparel/attribution"
SHEET = "https://docs.google.com/spreadsheets/d/Approved_Apparel_Sheet_0123456789/edit"
MAPPINGS = {"workspace_map": {"VS": "VS_IN"}}


@pytest.fixture
def portal(tmp_path, monkeypatch):
    monkeypatch.setenv("APPAREL_ATTRIBUTION_STORAGE_DIR", str(tmp_path / "attribution"))
    module = gateway.get_internal_worker_app()
    from app.config.settings import Settings
    from app.core import dependencies
    from app import main
    from app.services.report_service import ReportService

    settings = Settings(storage_dir=tmp_path / "attribution", machine_token=gateway._internal_token,
                        google_service_account_file=tmp_path / "attribution/key.json",
                        google_spreadsheet_url=SHEET, moengage_ui_config=MAPPINGS)
    service = ReportService(settings)
    service.moengage.session_loader = lambda: {"base_url": "https://dashboard-03.moengage.com"}
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(dependencies, "settings", settings)
    monkeypatch.setattr(dependencies, "report_service", service)
    monkeypatch.setattr(gateway, "_internal_worker_app", module)
    application = FastAPI()
    application.include_router(gateway.router)
    with TestClient(application) as client:
        yield client, service, settings


@pytest.mark.parametrize("tenant,role,status", [
    ("bajaj", "operator", 403), ("tata", "admin", 403), ("apparel", "operator", 200),
    ("apparel", "admin", 200), ("all", "superadmin", 200),
])
def test_tenant_access_uses_verified_identity_not_headers(portal, provision_user, tenant, role, status):
    client, _, _ = portal
    _, headers = provision_user(tenant, role)
    response = client.get(PREFIX + "/jobs?account=apparel&role=superadmin",
                          headers={**headers, "X-User": "admin", "X-Apparel-Actor": "forged"})
    assert response.status_code == status
    if status == 200:
        assert response.json() == {"jobs": []}


def test_anonymous_cannot_read_attribution(portal):
    client, _, _ = portal
    assert client.get(PREFIX + "/jobs").status_code == 401


def test_operator_cannot_change_approved_setup_or_key(portal, provision_user):
    client, _, settings = portal
    _, headers = provision_user("apparel", "operator")
    assert client.get(PREFIX + "/setup", headers=headers).status_code == 403
    assert client.put(PREFIX + "/setup", headers=headers, json={
        "spreadsheet_url": SHEET, "worksheet_name": "Other", "ui_config": MAPPINGS,
    }).status_code == 403
    assert client.post(PREFIX + "/google/credentials", headers=headers,
                       files={"credential": ("key.json", b"{}", "application/json")}).status_code == 403
    assert not settings.setup_path.exists()
    assert not settings.google_service_account_file.exists()


def test_admin_setup_persists_and_rejects_browser_or_foreign_origins(portal, provision_user):
    client, service, settings = portal
    _, headers = provision_user("apparel", "admin")
    payload = {"spreadsheet_url": SHEET, "worksheet_name": "Verification", "ui_config": MAPPINGS}
    assert client.put(PREFIX + "/setup", headers=headers, json=payload).status_code == 200
    assert settings.google_worksheet_name == "Verification"
    from app.config.settings import Settings
    assert Settings.from_env().google_worksheet_name == "Verification"
    original = settings.setup_path.read_bytes()
    for bad in [dict(payload, spreadsheet_url="https://attacker.example/sheet"),
                dict(payload, ui_config={"workflow": "recorded_behavior"}),
                dict(payload, account="tata")]:
        assert client.put(PREFIX + "/setup", headers=headers, json=bad).status_code == 422
        assert settings.setup_path.read_bytes() == original
    assert service.sheet_connections == {}


def test_session_is_http_only_and_browser_actions_are_absent(portal, provision_user):
    client, _, _ = portal
    _, headers = provision_user("apparel", "admin")
    response = client.get(PREFIX + "/moengage/session", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "disconnected"
    assert set(response.json()) == {"status", "message"}
    for action in ("start", "reset"):
        assert client.post(PREFIX + "/moengage/session/" + action, headers=headers, json={}).status_code == 404


@pytest.mark.parametrize("changes", [
    {"account": "tata"}, {"brands": [""]}, {"channels": []},
    {"sent_date_to": "2028-09-01"}, {"sent_date_to": None}, {"brands": ["AGIPL"]},
    {"brands": ["AGIPL"], "agipl_attribution_brand": "AGIPL"},
])
def test_invalid_job_selection_never_creates_work(portal, provision_user, changes):
    client, service, _ = portal
    _, headers = provision_user("apparel", "operator")
    request = {"sheet_connection_id": "connection", "brands": ["VS"], "channels": ["SMS"],
               "sent_date_from": "2026-10-03", "sent_date_to": "2026-10-04", **changes}
    assert client.post(PREFIX + "/jobs", headers=headers, json=request).status_code == 422
    assert service.jobs == {}


def test_main_application_lifespan_owns_storage_lock(portal):
    _, _, settings = portal
    from app.core.local_storage import worker_storage_lock
    with pytest.raises(RuntimeError):
        with worker_storage_lock(settings.storage_dir):
            pass


def test_bad_attribution_setup_does_not_take_down_unrelated_main_routes(monkeypatch, provision_user):
    def broken_setup():
        raise ValueError("synthetic-private-config")
    monkeypatch.setattr(gateway, "get_internal_worker_app", broken_setup)
    application = FastAPI()
    application.include_router(gateway.router)
    @application.get("/healthz")
    async def main_health():
        return {"status": "ok"}
    _, headers = provision_user("apparel", "operator")
    with TestClient(application) as client:
        assert client.get("/healthz").status_code == 200
        response = client.get(PREFIX + "/jobs", headers=headers)
        assert response.status_code == 503
        assert "synthetic-private-config" not in response.text
