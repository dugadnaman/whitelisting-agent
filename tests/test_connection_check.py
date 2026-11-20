"""Read-only connection checks use live scoped evidence, never registration or settings writes."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

import api
import config
import portal_sessions
import rcs_client
import submission_client
import vilpower_client as vilpower


@pytest.fixture
def connection_provider(monkeypatch):
    state = {"calls": [], "status": 200, "profile": f"<div>{vilpower.TATA_ENTITY_NAME} | {vilpower.TATA_ENTITY_ID}</div>",
             "wa": {"Success": {"templates": []}}, "rcs": {"templateInfo": []}, "official": {"templates": []}}

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, payload):
            self.send_response(state["status"])
            self.end_headers()
            self.wfile.write((payload if isinstance(payload, str) else json.dumps(payload)).encode())

        def do_GET(self):
            state["calls"].append(("GET", self.path, None))
            self.respond(state["profile"] if self.path == "/accountsettings/profile" else state["official"])

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["calls"].append(("POST", self.path, body))
            self.respond(state["wa"] if self.path == "/getAllTemplates" else state["rcs"])

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    credentials = {"cookie": "sessionid=fixture-only", "entity_id": vilpower.TATA_ENTITY_ID, "provider": "vilpower"}
    monkeypatch.setattr(vilpower, "BASE_URL", base)
    monkeypatch.setattr(portal_sessions, "load_session", lambda account, channel: dict(credentials) if (account, channel) == ("tata", "sms") else None)
    monkeypatch.setattr(config, "get_portal_auth_headers", lambda *args, **kwargs: {"Authorization": "Bearer fixture-only", "Session": "fixture-session", "User": "fixture-user"})
    monkeypatch.setattr(submission_client, "get_portal_auth_headers", config.get_portal_auth_headers)
    monkeypatch.setattr(submission_client, "KARIX_BASE_URL", base)
    monkeypatch.setattr(submission_client, "get_waba_id", lambda account: "fixture-waba")
    monkeypatch.setattr(submission_client, "get_esmeaddr", lambda account: "fixture-esme")
    monkeypatch.setattr(rcs_client, "KARIX_RCS_FETCH_TEMPLATES_URL", base + "/rcs")
    monkeypatch.setattr(rcs_client, "get_rcs_auth_headers", lambda *args, **kwargs: {"Authorization": "Bearer fixture-only"})
    monkeypatch.setattr(rcs_client, "get_rcs_bot_ids", lambda account: ["fixture-bot"])
    monkeypatch.setattr(rcs_client, "get_rcs_esmeaddr", lambda account: "fixture-esme")
    monkeypatch.setattr(api, "get_rcs_bot_id", lambda account: "fixture-bot")
    monkeypatch.setattr(api, "get_rcs_esmeaddr", lambda account: "fixture-esme")
    monkeypatch.setattr(portal_sessions, "save_settings", lambda *args, **kwargs: pytest.fail("Connection checks cannot write credentials"))
    monkeypatch.setattr(portal_sessions, "save_session", lambda *args, **kwargs: pytest.fail("Connection checks cannot write sessions"))
    try:
        yield state
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()


def test_sms_live_check_reads_only_exact_tata_profile(connection_provider, provision_user):
    _, headers = provision_user("tata")
    result = TestClient(api.app, headers=headers).post("/api/connection-check?account=tata&channel=sms")
    assert result.status_code == 200, result.text
    assert result.json()["ok"] is True
    assert result.json()["inventory_verified"] is False
    assert connection_provider["calls"] == [("GET", "/accountsettings/profile", None)]
    assert "fixture-only" not in result.text


@pytest.mark.parametrize("status,code", [(401, "auth_expired"), (403, "auth_expired"), (503, "provider_unavailable")])
def test_sms_check_distinguishes_expired_session_from_outage(connection_provider, provision_user, status, code):
    _, headers = provision_user("tata")
    connection_provider["status"] = status
    result = TestClient(api.app, headers=headers).post("/api/connection-check?account=tata&channel=sms")
    assert result.status_code == 200
    assert result.json()["ok"] is False
    assert result.json()["error_code"] == code
    assert result.json()["inventory_verified"] is False
    assert len(connection_provider["calls"]) == 1


def test_sms_check_rejects_another_live_principal(connection_provider, provision_user):
    _, headers = provision_user("tata")
    connection_provider["profile"] = "<div>OTHER FINANCE LIMITED | 1101000000000000000</div>"
    result = TestClient(api.app, headers=headers).post("/api/connection-check?account=tata&channel=sms")
    assert result.json()["ok"] is False
    assert result.json()["error_code"] == "provider_unavailable"


@pytest.mark.parametrize("account,channel,body,status", [
    ("bajaj", "sms", None, 403), ("tata", "all", None, 400),
    ("all", "sms", None, 400), ("tata", "sms", {"cookie": "must-not-save"}, 400),
    ("tcl_promo", "sms", None, 400),
])
def test_connection_checks_reject_unauthorized_ambiguous_or_write_requests(connection_provider, provision_user, account, channel, body, status):
    _, headers = provision_user("tata")
    result = TestClient(api.app, headers=headers).post("/api/connection-check", params={"account": account, "channel": channel}, json=body)
    assert result.status_code == status, result.text
    assert connection_provider["calls"] == []


def test_connection_check_requires_authentication(connection_provider):
    result = TestClient(api.app).post("/api/connection-check?account=tata&channel=sms")
    assert result.status_code in (401, 403)
    assert connection_provider["calls"] == []


def test_whatsapp_check_uses_supported_one_row_probe(connection_provider, provision_user):
    _, headers = provision_user("tata")
    result = TestClient(api.app, headers=headers).post("/api/connection-check?account=tcl_promo&channel=whatsapp")
    assert result.status_code == 200, result.text
    assert result.json()["ok"] is True
    assert result.json()["inventory_verified"] is False
    assert connection_provider["calls"] == [("POST", "/getAllTemplates", {
        "wabaId": "fixture-waba", "esmeaddr": "fixture-esme", "start": 0, "limit": 1,
    })]


@pytest.mark.parametrize("channel,payload", [("whatsapp", {"Success": {"templates": [{"wabaId": "other-waba"}]}}),
                                              ("rcs", {"templateInfo": [{"botId": "other-bot"}]})])
def test_connection_probe_refuses_cross_scope_inventory(connection_provider, provision_user, channel, payload):
    _, headers = provision_user("tata")
    connection_provider["wa" if channel == "whatsapp" else "rcs"] = payload
    result = TestClient(api.app, headers=headers).post(f"/api/connection-check?account=tata&channel={channel}")
    assert result.status_code == 200
    assert result.json()["ok"] is False
    assert result.json()["inventory_verified"] is False


def test_rcs_check_reports_honest_inventory_verification(connection_provider, provision_user):
    _, headers = provision_user("tata")
    result = TestClient(api.app, headers=headers).post("/api/connection-check?account=tata&channel=rcs")
    assert result.status_code == 200, result.text
    assert result.json()["ok"] is True
    assert result.json()["inventory_verified"] is True
    assert connection_provider["calls"] == [("POST", "/rcs", {"esmeaddr": "fixture-esme", "senderId": "fixture-bot"})]


@pytest.mark.parametrize("channel", ["whatsapp", "rcs"])
@pytest.mark.parametrize("status,code", [(401, "auth_expired"), (503, "provider_unavailable")])
def test_other_channels_distinguish_provider_outage_from_auth(connection_provider, provision_user, channel, status, code):
    _, headers = provision_user("tata")
    connection_provider["status"] = status
    result = TestClient(api.app, headers=headers).post(f"/api/connection-check?account=tata&channel={channel}")
    assert result.status_code == 200
    assert result.json()["error_code"] == code


def test_official_whatsapp_fallback_is_live_inventory_not_saved_pairing(connection_provider, provision_user, monkeypatch):
    _, headers = provision_user("tata")

    def no_portal(*args, **kwargs):
        raise OSError("No saved portal session")

    monkeypatch.setattr(config, "get_portal_auth_headers", no_portal)
    monkeypatch.setattr(config, "get_official_auth_headers", lambda account: {"Authentication": "Bearer fixture-only"})
    monkeypatch.setattr(api, "get_waba_id", lambda account: "fixture-waba")
    monkeypatch.setattr(api, "_account_prefix", lambda account: "FIXTURE")
    monkeypatch.delenv("FIXTURE_KARIX_BEARER_TOKEN", raising=False)
    monkeypatch.setattr(portal_sessions, "session_record", lambda *args: None)
    monkeypatch.setattr(api, "OFFICIAL_TEMPLATE_BASE_URL", vilpower.BASE_URL + "/official")
    result = TestClient(api.app, headers=headers).post("/api/connection-check?account=tata&channel=whatsapp")
    assert result.status_code == 200, result.text
    assert result.json()["ok"] is True
    assert result.json()["inventory_verified"] is True
    assert connection_provider["calls"] == [("GET", "/official/fixture-waba", None)]


def test_rcs_network_timeout_is_not_reported_as_an_expired_session(connection_provider, provision_user, monkeypatch):
    import requests
    _, headers = provision_user("tata")
    def unavailable(*args, **kwargs):
        try:
            raise requests.Timeout("Network did not respond")
        except requests.Timeout as exc:
            raise rcs_client.RcsInventoryUnavailable("Cannot reach provider") from exc
    monkeypatch.setattr(api, "_fetch_rcs_inventory", unavailable)
    result = TestClient(api.app, headers=headers).post("/api/connection-check?account=tcl_promo&channel=rcs")
    assert result.json()["ok"] is False
    assert result.json()["error_code"] == "provider_unavailable"
