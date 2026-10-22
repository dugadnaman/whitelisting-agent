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
import karix_extension
import moengage_sync
import rcs_client
import rcs_config

ORIGIN = "http://localhost:3000"
PREFIX = "/api/karix-extension"
SCOPE = "?account=bajaj&integration=whatsapp"


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
    payload = {"account": "bajaj", "integration": "whatsapp", "bearer_token": token, "session": "fresh-session", "user": "BajajOperator", "waba_id": config.BAJAJ_WABA_ID, "esmeaddr": config.BAJAJ_ESMEADDR}
    client = TestClient(api.app)
    try:
        yield client, headers, payload, state, user
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join()


def pair(client, headers, account="bajaj", integration="whatsapp"):
    response = client.post(PREFIX + "/pairing", headers=headers, json={"agent_origin": ORIGIN, "account": account, "integration": integration})
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
    status = client.get(PREFIX + "/status" + SCOPE, headers=headers).json()
    assert status["paired"] and status["validation_state"] == "valid"
    assert status["last_synced_at"] == response.json()["last_synced_at"]
    with db.get_db() as conn:
        encrypted = conn.execute("SELECT encrypted_credentials FROM karix_scoped_credentials WHERE kind = 'session'").fetchone()[0]
        link = conn.execute("SELECT credential_hash FROM karix_extension_links WHERE kind = 'device'").fetchone()[0]
    assert payload["bearer_token"] not in encrypted and payload["session"] not in encrypted
    assert device["Authorization"][7:] != link
    # No process-local token cache: consumers reconstruct headers from the database.
    monkeypatch.setenv("BAJAJ_KARIX_SESSION", "expired-env-session")
    assert portal_sessions.load_session("bajaj", "whatsapp")["session"] == "fresh-session"
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
    original = portal_sessions.session_record("bajaj", "whatsapp")["updated_at"]
    other = {**payload, "bearer_token": portal_token("72389800000000", "TATACAPWABA")}
    before = len(state["requests"])
    assert client.post(PREFIX + "/sync", headers=device, json=other).status_code == 409
    assert len(state["requests"]) == before
    assert client.post(PREFIX + "/sync", headers=device, json={**payload, "session": "mixed-session"}).status_code == 422
    assert client.post(PREFIX + "/sync", headers=device, json={**payload, "waba_id": "734197179371393"}).status_code == 409
    assert client.post(PREFIX + "/sync", headers=device, json={**payload, "user": "bad\r\nHeader"}).status_code == 422
    assert portal_sessions.session_record("bajaj", "whatsapp")["updated_at"] == original
    assert config.get_portal_auth_headers()["Session"] == "fresh-session"
    state["status"] = 401
    result = client.post(PREFIX + "/check" + SCOPE, headers=headers)
    assert result.json()["validation_state"] == "invalid"
    assert result.json()["last_synced_at"] == original


def test_pairing_is_single_use_expires_and_rejects_unapproved_destinations(extension_flow):
    client, headers, _, _, _ = extension_flow
    _, code = pair(client, headers)
    assert client.post(PREFIX + "/redeem", json={"code": code, "agent_origin": ORIGIN}).status_code == 401
    assert client.post(PREFIX + "/pairing", headers=headers, json={"agent_origin": "https://attacker.example", "account": "bajaj", "integration": "whatsapp"}).status_code == 403
    pairing = client.post(PREFIX + "/pairing", headers=headers, json={"agent_origin": ORIGIN, "account": "bajaj", "integration": "whatsapp"}).json()
    assert client.post(PREFIX + "/redeem", json={"code": pairing["code"], "agent_origin": "http://127.0.0.1:3000"}).status_code == 401
    with db.get_db() as conn:
        conn.execute("UPDATE karix_extension_links SET expires_at = ? WHERE kind = 'pairing'", (time.time() - 1,))
    assert client.post(PREFIX + "/redeem", json={"code": pairing["code"], "agent_origin": ORIGIN}).status_code == 401
    assert client.post(PREFIX + "/pairing", json={"agent_origin": ORIGIN, "account": "bajaj", "integration": "whatsapp"}).status_code == 401


def test_revocation_and_user_scope_changes_stop_device_sync(extension_flow):
    client, headers, payload, state, user = extension_flow
    device, _ = pair(client, headers)
    assert client.delete(PREFIX + "/pairing" + SCOPE, headers=headers).status_code == 200
    assert client.post(PREFIX + "/sync", headers=device, json=payload).status_code == 401
    device, _ = pair(client, headers)
    with db.get_db() as conn:
        conn.execute("UPDATE users SET tenant_id = 'tata' WHERE id = ?", (user["id"],))
    assert client.post(PREFIX + "/sync", headers=device, json=payload).status_code == 403
    assert client.get(PREFIX + "/status" + SCOPE, headers=headers).status_code == 403
    assert state["requests"] == []


def test_download_scopes_manifest_and_contains_no_credentials(extension_flow):
    client, headers, payload, _, _ = extension_flow
    device, _ = pair(client, headers)
    response = client.post(PREFIX + "/download", headers=headers, json={"agent_origin": ORIGIN})
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert set(manifest["host_permissions"]) == {"https://rcsgui.karix.solutions/*", "https://*.moengage.com/*", ORIGIN + "/*"}
        assert manifest["content_scripts"][0]["matches"] == [ORIGIN + "/*"]
        assert "cookies" not in manifest["permissions"]
        all_assets = b"\n".join(archive.read(name) for name in archive.namelist())
        assert device["Authorization"][7:].encode() not in all_assets
        assert payload["bearer_token"].encode() not in all_assets


def test_manual_override_uses_encrypted_store_and_preserves_omitted_fields(extension_flow, monkeypatch):
    client, headers, payload, _, _ = extension_flow
    manual = {key: value for key, value in payload.items() if key != "integration"}
    response = client.put("/api/credentials", headers=headers, json={**manual, "channel": "whatsapp"})
    assert response.status_code == 200, response.text
    assert portal_sessions.load_session("bajaj", "whatsapp")["session"] == "fresh-session"
    for filename in (".env", "credentials.json"):
        assert not api.Path(filename).exists()
    assert client.put("/api/credentials", headers=headers, json={"account": "bajaj", "channel": "whatsapp", "waba_id": config.BAJAJ_WABA_ID}).status_code == 200
    assert portal_sessions.load_session("bajaj", "whatsapp")["session"] == "fresh-session"
    assert client.put("/api/credentials", headers=headers, json={"account": "bajaj", "channel": "whatsapp", "session": "incomplete"}).status_code == 422


def test_all_account_targets_are_authorized_and_unknown_identity_requires_setup(extension_flow, provision_user, monkeypatch):
    client, bajaj_headers, _, _, _ = extension_flow
    _, tata_headers = provision_user("tata")
    _, admin_headers = provision_user("all", "superadmin")
    monkeypatch.setattr(api, "load_accounts", lambda: [{"id": "custom"}, {"id": "bajaj"}, {"id": "apparel"}])
    all_targets = client.get(PREFIX + "/targets", headers=admin_headers).json()["targets"]
    accounts = {target["account"] for target in all_targets}
    assert {"custom", "bajaj", "apparel", "tcl_promo", "tcl_trans", "tchfl", "wealth", "moneyfy"} <= accounts
    assert all({target["integration"] for target in all_targets if target["account"] == account}
               == {"whatsapp", "rcs", "moengage", "sms"} for account in accounts)
    custom = {target["integration"]: target for target in all_targets if target["account"] == "custom"}
    assert custom["whatsapp"]["mode"] == custom["rcs"]["mode"] == custom["moengage"]["mode"] == "setup_required"
    assert custom["sms"]["mode"] == "static"
    assert "cannot generate" in custom["sms"]["message"]
    bajaj = client.get(PREFIX + "/targets", headers=bajaj_headers).json()["targets"]
    assert {target["account"] for target in bajaj} == {"bajaj"}
    tata = client.get(PREFIX + "/targets", headers=tata_headers).json()["targets"]
    assert "bajaj" not in {target["account"] for target in tata}
    assert client.get(PREFIX + "/targets?account=bajaj", headers=tata_headers).status_code == 403
    assert client.get(PREFIX + "/status?account=tcl_promo&integration=rcs", headers=bajaj_headers).status_code == 403
    assert client.post(PREFIX + "/pairing", headers=bajaj_headers, json={
        "agent_origin": ORIGIN, "account": "tcl_promo", "integration": "rcs",
    }).status_code == 403
    assert client.post(PREFIX + "/pairing", headers=admin_headers, json={
        "agent_origin": ORIGIN, "account": "custom", "integration": "whatsapp",
    }).status_code == 409


def test_same_token_multiple_accounts_and_integrations_remain_independent(extension_flow, provision_user, monkeypatch):
    client, bajaj_headers, payload, _, _ = extension_flow
    _, tata_headers = provision_user("tata")
    requests_seen = []

    def verify(account, **snapshot):
        requests_seen.append((account, snapshot))
        return True, "Verified"

    monkeypatch.setattr(rcs_client, "check_rcs_credentials", verify)
    snapshots = {}
    devices = {}
    for account in ("tcl_promo", "tcl_trans"):
        devices[account], _ = pair(client, tata_headers, account, "rcs")
        snapshots[account] = {
            "account": account, "integration": "rcs", "bearer_token": "shared-rcs-session",
            "bot_id": rcs_config.get_rcs_bot_id(account), "esmeaddr": rcs_config.get_rcs_esmeaddr(account),
            "session": account + "-rcs-session", "user": account + "-operator",
        }
        result = client.post(PREFIX + "/sync", headers=devices[account], json=snapshots[account])
        assert result.status_code == 200, result.text
        assert result.json()["account"] == account and result.json()["integration"] == "rcs"
    assert [account for account, _ in requests_seen] == ["tcl_promo", "tcl_trans"]
    assert portal_sessions.load_session("tcl_promo", "rcs")["session"] == "tcl_promo-rcs-session"
    assert portal_sessions.load_session("tcl_trans", "rcs")["session"] == "tcl_trans-rcs-session"
    assert portal_sessions.load_session("tcl_promo", "whatsapp") is None
    assert client.post(PREFIX + "/sync", headers=devices["tcl_promo"], json=snapshots["tcl_trans"]).status_code == 403
    assert client.post(PREFIX + "/sync", headers=devices["tcl_promo"], json={
        **snapshots["tcl_promo"], "integration": "whatsapp",
    }).status_code == 403
    assert client.post(PREFIX + "/sync", headers=devices["tcl_promo"], json={
        **snapshots["tcl_promo"], "bot_id": "unknown-bot",
    }).status_code == 409
    assert client.post(PREFIX + "/sync", headers=devices["tcl_promo"], json={
        **snapshots["tcl_promo"], "bearer_token": portal_token(),
    }).status_code == 409
    wa_device, _ = pair(client, bajaj_headers)
    assert client.post(PREFIX + "/sync", headers=wa_device, json=payload).status_code == 200
    rcs_device, _ = pair(client, bajaj_headers, "bajaj", "rcs")
    bajaj_rcs = {
        "account": "bajaj", "integration": "rcs", "bearer_token": "separate-rcs-token",
        "bot_id": rcs_config.get_rcs_bot_id("bajaj"),
    }
    assert client.post(PREFIX + "/sync", headers=rcs_device, json=bajaj_rcs).status_code == 200
    assert config.get_portal_auth_headers("bajaj")["Authorization"] == "Bearer " + payload["bearer_token"]
    assert rcs_config.get_rcs_auth_headers("bajaj")["Authorization"] == "Bearer separate-rcs-token"
    assert "Session" not in rcs_config.get_rcs_auth_headers("bajaj")
    assert client.delete(PREFIX + "/pairing" + SCOPE, headers=bajaj_headers).status_code == 200
    assert client.post(PREFIX + "/sync", headers=wa_device, json=payload).status_code == 401
    assert client.post(PREFIX + "/sync", headers=rcs_device, json=bajaj_rcs).status_code == 200
    assert client.delete(PREFIX + "/device?account=tcl_trans&integration=rcs", headers=devices["tcl_promo"]).status_code == 403
    assert client.delete(PREFIX + "/device?account=tcl_promo&integration=rcs", headers=devices["tcl_promo"]).status_code == 200
    assert client.post(PREFIX + "/sync", headers=devices["tcl_promo"], json=snapshots["tcl_promo"]).status_code == 401
    assert client.post(PREFIX + "/sync", headers=devices["tcl_trans"], json=snapshots["tcl_trans"]).status_code == 200


def test_revocation_during_provider_validation_prevents_publish(extension_flow, monkeypatch):
    client, headers, payload, _, _ = extension_flow
    device, _ = pair(client, headers)

    def revoke(*args, **kwargs):
        with db.get_db() as conn:
            conn.execute("DELETE FROM karix_extension_links WHERE kind = 'device'")
        return True, "Valid"

    monkeypatch.setattr(submission_client, "check_portal_credentials", revoke)
    assert client.post(PREFIX + "/sync", headers=device, json=payload).status_code == 401
    assert portal_sessions.load_session("bajaj", "whatsapp") is None


def test_static_settings_survive_reload_and_identity_change_forces_reconnect(extension_flow):
    client, headers, payload, _, _ = extension_flow
    portal_sessions.save_settings("bajaj", "whatsapp", {
        "BAJAJ_WABA_ID": config.BAJAJ_WABA_ID, "BAJAJ_ESMEADDR": config.BAJAJ_ESMEADDR,
        "BAJAJ_WABA_AUTH_TOKEN": "one-time-api-key",
    })
    device, _ = pair(client, headers)
    assert client.post(PREFIX + "/sync", headers=device, json=payload).status_code == 200
    original = portal_sessions.session_record("bajaj", "whatsapp")["updated_at"]
    portal_sessions.save_settings("bajaj", "whatsapp", {"BAJAJ_WABA_ID": config.BAJAJ_WABA_ID})
    assert portal_sessions.session_record("bajaj", "whatsapp")["updated_at"] == original
    assert config.get_official_auth_headers("bajaj") == {"Authentication": "Bearer one-time-api-key"}
    portal_sessions.save_settings("bajaj", "whatsapp", {"BAJAJ_WABA_ID": "new-configured-waba"})
    assert portal_sessions.load_session("bajaj", "whatsapp") is None
    assert config.get_waba_id("bajaj") == "new-configured-waba"
    assert portal_sessions.load_settings("bajaj", "whatsapp")["BAJAJ_WABA_AUTH_TOKEN"] == "one-time-api-key"
    assert portal_sessions.load_settings("tchfl", "whatsapp") == {}
    assert client.post(PREFIX + "/sync", headers=device, json=payload).status_code == 409


def test_ciphertext_scope_swap_or_wrong_key_never_falls_back(extension_flow, monkeypatch):
    portal_sessions.save_session({"bearer_token": "first-token", "session": "first", "user": "operator"}, "bajaj", "whatsapp")
    portal_sessions.save_session({"bearer_token": "second-token"}, "bajaj", "rcs")
    with db.get_db() as conn:
        first = conn.execute(
            "SELECT encrypted_credentials FROM karix_scoped_credentials WHERE account = 'bajaj' AND integration = 'whatsapp' AND kind = 'session'"
        ).fetchone()[0]
        conn.execute(
            "UPDATE karix_scoped_credentials SET encrypted_credentials = ? WHERE account = 'bajaj' AND integration = 'rcs' AND kind = 'session'", (first,),
        )
    monkeypatch.setenv("BAJAJ_RCS_AUTH_TOKEN", "must-not-fall-back")
    with pytest.raises(OSError, match="cannot be decrypted"):
        rcs_config.get_rcs_auth_headers("bajaj")
    monkeypatch.setenv("JWT_SECRET", "different-stable-secret-0123456789-xyz" * 2)
    with pytest.raises(OSError, match="cannot be decrypted"):
        config.get_portal_auth_headers("bajaj")


def test_legacy_encrypted_bajaj_row_and_devices_migrate_without_plaintext(extension_flow):
    _, _, payload, _, user = extension_flow
    legacy = portal_sessions._cipher().encrypt(json.dumps({
        "bearer_token": payload["bearer_token"], "session": payload["session"], "user": payload["user"],
    }).encode()).decode()
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO karix_portal_sessions VALUES ('bajaj', ?, ?, ?, 'valid')", (legacy, 10.0, 11.0),
        )
        # Simulate an actual pre-scope links schema, retaining an existing token hash.
        conn.execute("DROP TABLE karix_extension_links")
        conn.execute(
            "CREATE TABLE karix_extension_links (credential_hash TEXT PRIMARY KEY, kind TEXT NOT NULL, user_id TEXT NOT NULL, agent_origin TEXT NOT NULL, expires_at DOUBLE PRECISION NOT NULL)"
        )
        conn.execute(
            "INSERT INTO karix_extension_links VALUES ('legacy-device-hash', 'device', ?, ?, ?)",
            (user["id"], ORIGIN, time.time() + 1000),
        )
        db.init_database(conn, force=True)
        link = conn.execute("SELECT * FROM karix_extension_links").fetchone()
        assert (link["account"], link["integration"]) == ("bajaj", "whatsapp")
        assert link["credential_hash"] == "legacy-device-hash"
        assert conn.execute("SELECT 1 FROM karix_portal_sessions").fetchone() is None
    assert portal_sessions.load_session("bajaj", "whatsapp")["session"] == payload["session"]
    assert portal_sessions.session_record("bajaj", "whatsapp")["updated_at"] == 10.0
    assert portal_sessions.load_session("bajaj", "rcs") is None


def test_undecryptable_legacy_row_is_preserved_and_fails_closed(extension_flow):
    with db.get_db() as conn:
        conn.execute("INSERT INTO karix_portal_sessions VALUES ('bajaj', 'not-valid-ciphertext', 10, 11, 'valid')")
    with pytest.raises(OSError, match="cannot be decrypted"):
        db.init_database(force=True)
    with db.get_db() as conn:
        row = conn.execute("SELECT encrypted_credentials FROM karix_portal_sessions").fetchone()
        assert row[0] == "not-valid-ciphertext"


def test_moengage_binds_provider_returned_tokens_and_preserves_failed_refresh(extension_flow, monkeypatch):
    client, headers, _, _, _ = extension_flow
    workspace = "0123456789abcdef01234567"
    base = "https://dashboard-03.moengage.com"
    portal_sessions.save_settings("bajaj", "moengage", {
        "BAJAJ_MOENGAGE_BASE_URL": base, "BAJAJ_MOENGAGE_WORKSPACE_ID": workspace,
    })
    calls, state = [], {"allowed": True, "switched": True}

    class ProviderResponse:
        status_code = 200
        ok = True

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    def request(url, **kwargs):
        calls.append((url, kwargs))
        assert kwargs["allow_redirects"] is False
        assert kwargs["headers"]["refreshtoken"] == "captured-refresh"
        assert kwargs["headers"]["cookie"] == "session=captured-cookie"
        if url.endswith("/listApps"):
            return ProviderResponse({"data": [{
                "id": workspace if state["allowed"] else "ffffffffffffffffffffffff",
                "activated": True, "is_test": False,
            }]})
        assert url == base + "/dash/auth/changeApp"
        assert kwargs["params"] == {"sls_enabled": "true", "app_id": workspace}
        return ProviderResponse({"code": 200, "status": "success", "data": {
            "bearer": "bound-workspace-token", "refresh_token": "bound-workspace-refresh",
            "app_access_details": "ALLOWED" if state["switched"] else "DENIED",
        }})

    monkeypatch.setattr(moengage_sync.requests, "get", request)
    device, _ = pair(client, headers, "bajaj", "moengage")
    payload = {
        "account": "bajaj", "integration": "moengage", "bearer_token": "captured-token",
        "refresh_token": "captured-refresh", "cookie": "session=captured-cookie",
        "workspace_id": workspace, "base_url": base,
    }
    response = client.post(PREFIX + "/sync", headers=device, json=payload)
    assert response.status_code == 200, response.text
    saved = portal_sessions.load_session("bajaj", "moengage")
    assert saved["bearer_token"] == "bound-workspace-token"
    assert saved["refresh_token"] == "bound-workspace-refresh"
    assert moengage_sync.get_moengage_config("bajaj")["workspace_id"] == workspace
    assert moengage_sync.get_moengage_auth_headers("bajaj")["authorization"] == "Bearer bound-workspace-token"
    original = portal_sessions.session_record("bajaj", "moengage")["updated_at"]
    for field, value in (("base_url", "https://attacker.invalid"), ("workspace_id", "ffffffffffffffffffffffff")):
        before = len(calls)
        assert client.post(PREFIX + "/sync", headers=device, json={**payload, field: value}).status_code == 409
        assert len(calls) == before
    state["allowed"] = False
    assert client.post(PREFIX + "/sync", headers=device, json=payload).status_code == 422
    state["allowed"], state["switched"] = True, False
    assert client.post(PREFIX + "/sync", headers=device, json=payload).status_code == 422
    assert portal_sessions.session_record("bajaj", "moengage")["updated_at"] == original
    assert portal_sessions.load_session("bajaj", "moengage") == saved
    portal_sessions.save_settings("bajaj", "moengage", {"BAJAJ_MOENGAGE_WORKSPACE_ID": workspace})
    assert portal_sessions.load_session("bajaj", "moengage") == saved
    portal_sessions.save_settings("bajaj", "moengage", {"BAJAJ_MOENGAGE_WORKSPACE_ID": "ffffffffffffffffffffffff"})
    assert portal_sessions.load_session("bajaj", "moengage") is None


def test_rcs_validation_uses_provider_inventory_and_never_whatsapp_headers(extension_flow, monkeypatch):
    calls = []

    class ProviderResponse:
        status_code = 200
        ok = True

        def json(self):
            return {"templateInfo": []}

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return ProviderResponse()

    monkeypatch.setattr(rcs_client.requests, "get", request)
    monkeypatch.setenv("TCL_PROMO_KARIX_SESSION", "wrong-wa-session")
    monkeypatch.setenv("TCL_PROMO_KARIX_USER", "wrong-wa-user")
    valid, _ = rcs_client.check_rcs_credentials(
        "tcl_promo", bearer_token="rcs-only-token", bot_id=rcs_config.get_rcs_bot_id("tcl_promo"),
        esmeaddr=rcs_config.get_rcs_esmeaddr("tcl_promo"),
    )
    assert valid
    url, options = calls[0]
    assert url == rcs_config.KARIX_RCS_FETCH_URL
    assert options["params"] == {"senderId": rcs_config.get_rcs_bot_id("tcl_promo")}
    assert options["headers"]["Authorization"] == "Bearer rcs-only-token"
    assert "Session" not in options["headers"] and "User" not in options["headers"]
    assert options["allow_redirects"] is False
