"""Settings must validate portal credentials against the portal, not the WABA API."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

import api
import config
import submission_client


@pytest.fixture
def portal_validation(tmp_path, monkeypatch, provision_user):
    state = {"status": 200, "payload": {"Success": {"templates": []}}, "requests": [],
             "official_status": 200, "official_payload": {"response": {"templates": []}}}

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state["requests"].append("official")
            authorized = self.headers.get("Authentication") == "Bearer fixture-valid-official-token"
            self.send_response(state["official_status"] if authorized else 401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(state["official_payload"] if authorized else {"message": "Invalid credentials"}).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            authorized = (
                self.path == "/portal/getAllTemplates"
                and self.headers.get("Authorization") == "Bearer fixture-valid-portal-token"
                and self.headers.get("Session") == "fixture-valid-session"
                and self.headers.get("User") == "fixture-portal-user"
                and body.get("wabaId") == config.BAJAJ_WABA_ID
                and body.get("esmeaddr") == config.BAJAJ_ESMEADDR
            )
            state["requests"].append("portal")
            self.send_response(state["status"] if authorized else 401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = state["payload"] if authorized else {"Failed": "Invalid credentials"}
            self.wfile.write(json.dumps(payload).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(api, "OFFICIAL_TEMPLATE_BASE_URL", base + "/official")
    monkeypatch.setattr(submission_client, "KARIX_BASE_URL", base + "/portal")
    monkeypatch.setattr(config, "_load_env_file", lambda: None)
    for key in ("BAJAJ_KARIX_BEARER_TOKEN", "BAJAJ_KARIX_SESSION", "BAJAJ_KARIX_USER", "KARIX_BEARER_TOKEN", "KARIX_SESSION", "KARIX_USER"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BAJAJ_WABA_AUTH_TOKEN", "fixture-invalid-official-token")
    monkeypatch.setenv("BAJAJ_WABA_ID", config.BAJAJ_WABA_ID)
    _, headers = provision_user("bajaj")
    payload = {"account": "bajaj", "channel": "whatsapp", "waba_id": config.BAJAJ_WABA_ID,
               "bearer_token": "fixture-valid-portal-token", "session": "fixture-valid-session", "user": "fixture-portal-user"}
    try:
        with TestClient(api.app, headers=headers) as client:
            yield client, payload, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("token", ["fixture-valid-portal-token", "Bearer fixture-valid-portal-token", "Authorization: Bearer fixture-valid-portal-token"])
def test_correct_portal_token_is_not_rejected_by_unrelated_official_credentials(portal_validation, token):
    client, payload, state = portal_validation
    payload["bearer_token"] = token
    response = client.post("/api/test-credentials", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ok"] is True, result["message"]
    assert state["requests"] == ["portal"]


@pytest.mark.parametrize("status,payload", [(401, {"Failed": "Invalid credentials"}), (403, {"Failed": "Invalid credentials"}), (200, {"Failed": "Invalid credentials"})])
def test_portal_authentication_failures_are_not_reported_as_valid(portal_validation, status, payload):
    client, credentials, state = portal_validation
    state.update(status=status, payload=payload)
    result = client.post("/api/test-credentials", json=credentials).json()
    assert result["ok"] is False
    assert state["requests"] == ["portal"]


def test_missing_portal_session_is_actionable_and_never_tests_other_credentials(portal_validation):
    client, payload, state = portal_validation
    del payload["session"]
    result = client.post("/api/test-credentials", json=payload).json()
    assert result["ok"] is False
    assert state["requests"] == []


def test_current_form_snapshot_replaces_stale_saved_portal_credentials(portal_validation, monkeypatch):
    client, payload, state = portal_validation
    monkeypatch.setenv("BAJAJ_KARIX_BEARER_TOKEN", "fixture-stale-token")
    monkeypatch.setenv("BAJAJ_KARIX_SESSION", "fixture-stale-session")
    monkeypatch.setenv("BAJAJ_KARIX_USER", "fixture-stale-user")
    result = client.post("/api/test-credentials", json=payload).json()
    assert result["ok"] is True, result["message"]
    assert state["requests"] == ["portal"]
    assert config.get_portal_auth_headers()["Session"] == "fixture-stale-session"


def test_saved_header_prefixed_token_validates_without_reentering_credentials(portal_validation, monkeypatch):
    client, _, state = portal_validation
    monkeypatch.setenv("BAJAJ_KARIX_BEARER_TOKEN", "Authorization: Bearer fixture-valid-portal-token")
    monkeypatch.setenv("BAJAJ_KARIX_SESSION", "fixture-valid-session")
    monkeypatch.setenv("BAJAJ_KARIX_USER", "fixture-portal-user")
    result = client.post("/api/test-credentials", json={"account": "bajaj", "channel": "whatsapp"}).json()
    assert result["ok"] is True, result["message"]
    assert state["requests"] == ["portal"]


def test_incorrect_new_token_does_not_fall_back_to_a_valid_saved_session(portal_validation, monkeypatch):
    client, payload, state = portal_validation
    monkeypatch.setenv("BAJAJ_KARIX_BEARER_TOKEN", "fixture-valid-portal-token")
    monkeypatch.setenv("BAJAJ_KARIX_SESSION", "fixture-valid-session")
    monkeypatch.setenv("BAJAJ_KARIX_USER", "fixture-portal-user")
    payload["bearer_token"] = "fixture-invalid-portal-token"
    result = client.post("/api/test-credentials", json=payload).json()
    assert result["ok"] is False
    assert state["requests"] == ["portal"]
    assert payload["bearer_token"] not in result["message"]


def test_explicit_official_token_still_uses_the_official_api(portal_validation, monkeypatch):
    client, _, state = portal_validation
    monkeypatch.setenv("BAJAJ_KARIX_BEARER_TOKEN", "fixture-stale-token")
    result = client.post("/api/test-credentials", json={
        "account": "bajaj", "channel": "whatsapp", "waba_id": config.BAJAJ_WABA_ID,
        "waba_auth_token": "fixture-valid-official-token",
    }).json()
    assert result["ok"] is True, result["message"]
    assert state["requests"] == ["official"]


def test_no_records_is_a_valid_portal_session_not_an_authentication_failure(portal_validation):
    client, payload, state = portal_validation
    state["payload"] = {"Failed": "No Records Found"}
    result = client.post("/api/test-credentials", json=payload).json()
    assert result["ok"] is True, result["message"]

def test_portal_templates_with_zero_esmeaddr_are_valid(portal_validation):
    client, payload, state = portal_validation
    state["payload"] = {"Success": {"templates": [{"template_name": "test_tpl", "waba_id": config.BAJAJ_WABA_ID, "esmeaddr": 0}]}}
    result = client.post("/api/test-credentials", json=payload).json()
    assert result["ok"] is True, result["message"]


def test_blank_token_checks_saved_official_credentials(portal_validation, monkeypatch):
    client, _, state = portal_validation
    monkeypatch.setenv("BAJAJ_WABA_AUTH_TOKEN", "fixture-valid-official-token")
    result = client.post("/api/test-credentials", json={"account": "bajaj", "channel": "whatsapp"}).json()
    assert result["ok"] is True


def test_invalid_official_draft_cannot_pass_using_saved_portal_credentials(portal_validation, monkeypatch):
    client, _, state = portal_validation
    monkeypatch.setenv("BAJAJ_KARIX_BEARER_TOKEN", "fixture-valid-portal-token")
    monkeypatch.setenv("BAJAJ_KARIX_SESSION", "fixture-valid-session")
    monkeypatch.setenv("BAJAJ_KARIX_USER", "fixture-portal-user")
    result = client.post("/api/test-credentials", json={
        "account": "bajaj", "channel": "whatsapp", "waba_auth_token": "fixture-invalid-draft",
    }).json()
    assert result["ok"] is False
    assert state["requests"] == ["official"]


@pytest.mark.parametrize("provider_payload", [{"error": "Invalid credentials"}, {}, {"response": {"templates": "not-an-inventory"}}])
def test_http_200_without_an_inventory_cannot_verify_official_credentials(portal_validation, provider_payload):
    client, _, state = portal_validation
    state["official_payload"] = provider_payload
    result = client.post("/api/test-credentials", json={
        "account": "bajaj", "channel": "whatsapp", "waba_auth_token": "fixture-valid-official-token",
    }).json()
    assert result["ok"] is False


def test_provider_errors_do_not_echo_draft_credentials(portal_validation):
    client, _, state = portal_validation
    secret = "fixture-valid-official-token"
    state.update(official_status=502, official_payload={"error": secret})
    result = client.post("/api/test-credentials", json={
        "account": "bajaj", "channel": "whatsapp", "waba_auth_token": secret,
    }).json()
    assert result["ok"] is False
    assert secret not in json.dumps(result)


def test_invalid_official_token_cannot_replace_saved_credentials(portal_validation, monkeypatch):
    client, _, _ = portal_validation
    monkeypatch.setenv("BAJAJ_WABA_AUTH_TOKEN", "fixture-valid-official-token")
    response = client.put("/api/credentials", json={
        "account": "bajaj", "channel": "whatsapp", "waba_auth_token": "fixture-invalid-draft",
    })
    assert response.status_code == 422
    assert config.get_official_auth_headers("bajaj")["Authentication"] == "Bearer fixture-valid-official-token"


@pytest.mark.parametrize("missing", ["bearer_token", "session", "user"])
def test_partial_manual_snapshot_never_borrows_saved_headers(portal_validation, monkeypatch, missing):
    client, payload, state = portal_validation
    monkeypatch.setenv("BAJAJ_KARIX_BEARER_TOKEN", "fixture-valid-portal-token")
    monkeypatch.setenv("BAJAJ_KARIX_SESSION", "fixture-valid-session")
    monkeypatch.setenv("BAJAJ_KARIX_USER", "fixture-portal-user")
    del payload[missing]
    result = client.post("/api/test-credentials", json=payload).json()
    assert result["ok"] is False
    assert state["requests"] == []


@pytest.mark.parametrize("identity", ["another-waba", 0, False])
def test_official_inventory_for_another_waba_is_rejected(portal_validation, identity):
    client, _, state = portal_validation
    state["official_payload"] = {"response": {"templates": [{"waba_id": identity, "template_name": "foreign_template"}]}}
    result = client.post("/api/test-credentials", json={
        "account": "bajaj", "channel": "whatsapp", "waba_auth_token": "fixture-valid-official-token",
    }).json()
    assert result["ok"] is False


def test_verified_official_token_persists_without_affecting_other_accounts(portal_validation, monkeypatch):
    from portal_sessions import load_settings
    client, _, _ = portal_validation
    monkeypatch.setattr(api.QUEUE_MANAGER, "notify_credentials_updated", lambda _account: None)
    response = client.put("/api/credentials", json={
        "account": "bajaj", "channel": "whatsapp", "waba_auth_token": "fixture-valid-official-token",
    })
    assert response.status_code == 200
    assert config.get_official_auth_headers("bajaj")["Authentication"] == "Bearer fixture-valid-official-token"
    assert load_settings("tchfl", "whatsapp") == {}
