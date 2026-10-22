"""Consumer-visible session sync and isolation, using a real loopback Karix simulator."""

import base64
import io
import json
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

import api
import config
import db
import portal_sessions
import submission_client

ORIGIN = "http://localhost:3000"
PREFIX = "/api/karix-extension"


def portal_token(esme="72148300000000", account="BFDL_WABA"):
    payload = base64.b64encode(("msijafen" + esme + account).encode()).decode().rstrip("=")
    return "eyJhbGciOiJSUzI1NiJ9." + payload + ".test-signature"


@pytest.fixture
def extension_flow(tmp_path, monkeypatch, provision_user):
    token = portal_token()
    state = {"status": 200, "requests": [], "session": "fresh-session"}

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append({"body": body, "session": self.headers.get("Session")})
            valid = (
                self.path == "/portal/getAllTemplates"
                and self.headers.get("Authorization") == "Bearer " + token
                and self.headers.get("Session") == state["session"]
                and self.headers.get("User") == "BajajOperator"
                and body.get("wabaId") == config.BAJAJ_WABA_ID
                and body.get("esmeaddr") == config.BAJAJ_ESMEADDR
            )
            self.send_response(state["status"] if valid else 401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"Success": {"templates": [{"name": "bajaj_verified_template"}]}} if valid else {"Failed": "Invalid credentials"}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "_load_env_file", lambda: None)
    monkeypatch.setattr(submission_client, "KARIX_BASE_URL", f"http://127.0.0.1:{server.server_port}/portal")
    monkeypatch.setattr(api.QUEUE_MANAGER, "notify_credentials_updated", lambda account: None)
    user, headers = provision_user("bajaj")
    payload = {"bearer_token": token, "session": "fresh-session", "user": "BajajOperator", "waba_id": config.BAJAJ_WABA_ID, "esmeaddr": config.BAJAJ_ESMEADDR}
    client = TestClient(api.app)
    try:
        yield client, headers, payload, state, user
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join()


def pair(client, headers):
    response = client.post(PREFIX + "/pairing", headers=headers, json={"agent_origin": ORIGIN})
    assert response.status_code == 200, response.text
    code = response.json()["code"]
    redeemed = client.post(PREFIX + "/redeem", json={"agent_origin": ORIGIN, "code": code})
    assert redeemed.status_code == 200, redeemed.text
    return {"Authorization": "Bearer " + redeemed.json()["device_token"]}, code


def test_sync_is_encrypted_survives_reload_and_drives_real_inventory(extension_flow, monkeypatch):
    client, headers, payload, state, _ = extension_flow
    device, _ = pair(client, headers)
    response = client.post(PREFIX + "/sync", headers=device, json=payload)
    assert response.status_code == 200, response.text
    status = client.get(PREFIX + "/status", headers=headers).json()
    assert status["paired"] and status["validation_state"] == "valid"
    assert status["last_synced_at"] == response.json()["last_synced_at"]
    with db.get_db() as conn:
        encrypted = conn.execute("SELECT encrypted_credentials FROM karix_portal_sessions").fetchone()[0]
        link = conn.execute("SELECT credential_hash FROM karix_extension_links WHERE kind = 'device'").fetchone()[0]
    assert payload["bearer_token"] not in encrypted and payload["session"] not in encrypted
    assert device["Authorization"][7:] != link
    # No process-local token cache: consumers reconstruct headers from the database.
    monkeypatch.setenv("BAJAJ_KARIX_SESSION", "expired-env-session")
    monkeypatch.setenv("BAJAJ_WABA_ID", "wrong-env-waba")
    monkeypatch.setenv("BAJAJ_ESMEADDR", "wrong-env-esme")
    assert portal_sessions.load_session()["session"] == "fresh-session"
    templates, error = submission_client.fetch_template_list("bajaj")
    assert error is None and templates == [{"name": "bajaj_verified_template"}]
    saved_form = client.get("/api/credentials?account=bajaj&channel=whatsapp", headers=headers).json()
    assert saved_form["extension_session"] is True
    assert saved_form["bearer_token"] == saved_form["session"] == saved_form["user"] == ""
    assert not (api.Path("credentials.json").exists() or api.Path(".env").exists())
    # Device tokens cannot authenticate to unrelated agent endpoints.
    assert client.get("/api/accounts", headers=device).status_code == 401


def test_rejected_or_cross_account_snapshots_never_replace_working_session(extension_flow):
    client, headers, payload, state, _ = extension_flow
    device, _ = pair(client, headers)
    assert client.post(PREFIX + "/sync", headers=device, json=payload).status_code == 200
    original = portal_sessions.session_record()["updated_at"]
    other = {**payload, "bearer_token": portal_token("72389800000000", "TATACAPWABA")}
    before = len(state["requests"])
    assert client.post(PREFIX + "/sync", headers=device, json=other).status_code == 409
    assert len(state["requests"]) == before
    assert client.post(PREFIX + "/sync", headers=device, json={**payload, "session": "mixed-session"}).status_code == 422
    assert client.post(PREFIX + "/sync", headers=device, json={**payload, "waba_id": "734197179371393"}).status_code == 422
    assert client.post(PREFIX + "/sync", headers=device, json={**payload, "user": "bad\r\nHeader"}).status_code == 422
    assert portal_sessions.session_record()["updated_at"] == original
    assert config.get_portal_auth_headers()["Session"] == "fresh-session"
    state["status"] = 401
    result = client.post(PREFIX + "/check", headers=headers)
    assert result.json()["validation_state"] == "invalid"
    assert result.json()["last_synced_at"] == original


def test_pairing_is_single_use_expires_and_rejects_unapproved_destinations(extension_flow):
    client, headers, _, _, _ = extension_flow
    _, code = pair(client, headers)
    assert client.post(PREFIX + "/redeem", json={"code": code, "agent_origin": ORIGIN}).status_code == 401
    assert client.post(PREFIX + "/pairing", headers=headers, json={"agent_origin": "https://attacker.example"}).status_code == 403
    pairing = client.post(PREFIX + "/pairing", headers=headers, json={"agent_origin": ORIGIN}).json()
    assert client.post(PREFIX + "/redeem", json={"code": pairing["code"], "agent_origin": "http://127.0.0.1:3000"}).status_code == 401
    with db.get_db() as conn:
        conn.execute("UPDATE karix_extension_links SET expires_at = ? WHERE kind = 'pairing'", (time.time() - 1,))
    assert client.post(PREFIX + "/redeem", json={"code": pairing["code"], "agent_origin": ORIGIN}).status_code == 401
    assert client.post(PREFIX + "/pairing", json={"agent_origin": ORIGIN}).status_code == 401


def test_revocation_and_user_scope_changes_stop_device_sync(extension_flow):
    client, headers, payload, state, user = extension_flow
    device, _ = pair(client, headers)
    assert client.delete(PREFIX + "/pairing", headers=headers).status_code == 200
    assert client.post(PREFIX + "/sync", headers=device, json=payload).status_code == 401
    device, _ = pair(client, headers)
    with db.get_db() as conn:
        conn.execute("UPDATE users SET tenant_id = 'tata' WHERE id = ?", (user["id"],))
    assert client.post(PREFIX + "/sync", headers=device, json=payload).status_code == 403
    assert client.get(PREFIX + "/status", headers=headers).status_code == 403
    assert state["requests"] == []


def test_download_scopes_manifest_and_contains_no_credentials(extension_flow):
    client, headers, payload, _, _ = extension_flow
    device, _ = pair(client, headers)
    response = client.post(PREFIX + "/download", headers=headers, json={"agent_origin": ORIGIN})
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert set(manifest["host_permissions"]) == {"https://rcsgui.karix.solutions/*", ORIGIN + "/*"}
        assert manifest["content_scripts"][0]["matches"] == [ORIGIN + "/*"]
        assert "cookies" not in manifest["permissions"]
        all_assets = b"\n".join(archive.read(name) for name in archive.namelist())
        assert device["Authorization"][7:].encode() not in all_assets
        assert payload["bearer_token"].encode() not in all_assets


def test_manual_override_uses_encrypted_store_and_preserves_omitted_fields(extension_flow, monkeypatch):
    client, headers, payload, _, _ = extension_flow
    monkeypatch.setattr(api, "_commit_credentials_to_github", lambda: None)
    response = client.put("/api/credentials", headers=headers, json={**payload, "account": "bajaj", "channel": "whatsapp"})
    assert response.status_code == 200, response.text
    assert portal_sessions.load_session()["session"] == "fresh-session"
    for filename in (".env", "credentials.json"):
        text = api.Path(filename).read_text()
        assert payload["bearer_token"] not in text and payload["session"] not in text
    assert client.put("/api/credentials", headers=headers, json={"account": "bajaj", "channel": "whatsapp", "waba_id": config.BAJAJ_WABA_ID}).status_code == 200
    assert portal_sessions.load_session()["session"] == "fresh-session"
    assert client.put("/api/credentials", headers=headers, json={"account": "bajaj", "channel": "whatsapp", "session": "incomplete"}).status_code == 422
