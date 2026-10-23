"""Exercise MV3 capture from Karix's real frontend origin, not its API origin."""

import base64
import io
import json
import ssl
import subprocess
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
from fastapi.testclient import TestClient

import api
import config
import db
import portal_sessions
import rcs_client
import rcs_config


@pytest.fixture
def rcs_flow(tmp_path, monkeypatch, provision_user):
    esme, bot = "72434700000000", "Uv9tdd0KNADbq3pX"
    signed = base64.b64encode(("fixture" + esme + "TATA").encode()).decode().rstrip("=")
    token = "header." + signed + ".fixture-signature"
    state = {"status": 200, "bot": bot, "esme": esme, "token": token, "calls": []}

    class Inventory(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            state["calls"].append(("GET", self.path))
            self.reply(401, {"status": "failure"})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["calls"].append(("POST", body))
            valid = (
                self.path == "/api/rcstemplate/fetchTemplates"
                and body == {"senderId": bot, "esmeaddr": esme}
                and self.headers.get("Authorization") == "Bearer " + state["token"]
                and self.headers.get("Session") == "fixture-session"
                and self.headers.get("User") == "fixture-user"
            )
            self.reply(state["status"] if valid else 401, {"status": "success", "templateInfo": [{
                "templateId": "verified-inventory", "senderId": state["bot"], "esmeaddr": state["esme"],
            }]})

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Inventory)
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "_load_env_file", lambda: None)
    monkeypatch.setenv("KARIX_EXTENSION_AGENT_ORIGINS", "https://rcsgui.karix.solutions")
    monkeypatch.setenv("TCL_PROMO_KARIX_SESSION", "wrong-whatsapp-session")
    monkeypatch.setenv("TCL_PROMO_KARIX_USER", "wrong-whatsapp-user")
    base = f"http://127.0.0.1:{provider.server_port}"
    monkeypatch.setattr(rcs_client, "KARIX_RCS_FETCH_TEMPLATES_URL", base + "/api/rcstemplate/fetchTemplates")
    monkeypatch.setattr(api.QUEUE_MANAGER, "notify_credentials_updated", lambda account: None)
    _, headers = provision_user("tata")
    client = TestClient(api.app)
    origin = "https://rcsgui.karix.solutions"
    pairing = client.post("/api/karix-extension/pairing", headers=headers, json={
        "agent_origin": origin, "account": "tcl_promo", "integration": "rcs",
    })
    assert pairing.status_code == 200, pairing.text
    redeemed = client.post("/api/karix-extension/redeem", json={
        "agent_origin": origin, "code": pairing.json()["code"],
    })
    assert redeemed.status_code == 200, redeemed.text
    device = redeemed.json()["device_token"]
    payload = {"account": "tcl_promo", "integration": "rcs", "bot_id": bot,
               "esmeaddr": esme, "bearer_token": token, "session": "fixture-session", "user": "fixture-user"}
    try:
        yield client, headers, device, payload, state
    finally:
        client.close()
        provider.shutdown()
        provider.server_close()
        thread.join()


def assert_saved_inventory(payload):
    assert portal_sessions.load_session("tcl_promo", "rcs")["bearer_token"] == payload["bearer_token"]
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT encrypted_credentials FROM karix_scoped_credentials WHERE account = ? AND integration = ? AND kind = 'session'",
            ("tcl_promo", "rcs"),
        ).fetchone()
    assert row and payload["bearer_token"] not in row[0] and payload["session"] not in row[0]
    assert rcs_client.fetch_rcs_templates(client="tcl_promo") == [{
        "templateId": "verified-inventory", "senderId": payload["bot_id"], "esmeaddr": payload["esmeaddr"],
    }]


def test_rcs_post_validation_preserves_last_good_session(rcs_flow):
    client, _, device, payload, state = rcs_flow
    headers = {"Authorization": "Bearer " + device}
    response = client.post("/api/karix-extension/sync", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert_saved_inventory(payload)
    saved = portal_sessions.session_record("tcl_promo", "rcs")
    for field, value in (("bot", "another-bot"), ("esme", "another-esme"), ("status", 401)):
        original = state[field]
        state[field] = value
        response = client.post("/api/karix-extension/sync", headers=headers, json=payload)
        assert response.status_code == 422, response.text
        assert portal_sessions.session_record("tcl_promo", "rcs")["updated_at"] == saved["updated_at"]
        state[field] = original
        assert_saved_inventory(payload)
    assert all(method == "POST" for method, _ in state["calls"])


@pytest.mark.parametrize("cold_start", [False, True], ids=["awake", "worker-restart"])
def test_karix_frontend_inventory_syncs_exact_paired_target(tmp_path, cold_start, rcs_flow):
    client, headers, device, payload, state = rcs_flow
    extension = tmp_path / "extension"
    download = client.post("/api/karix-extension/download", headers=headers, json={
        "agent_origin": "https://rcsgui.karix.solutions",
    })
    assert download.status_code == 200, download.text
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        archive.extractall(extension)
    certificate, key = tmp_path / "certificate.pem", tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
         "-subj", "/CN=auth-sync.test", "-keyout", str(key), "-out", str(certificate)],
        check=True, capture_output=True,
    )
    esme, bot, token = payload["esmeaddr"], payload["bot_id"], payload["bearer_token"]
    observed = {"inventory": [], "sync": []}

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, body, content_type="application/json"):
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "https://rcmui.instaalerts.zone")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "authorization, session, user, content-type")
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            self.reply(200, {})

        def do_GET(self):
            if self.path not in ("/bot_builder_gui/", "/settings"):
                self.reply(404, {})
                return
            self.reply(200, "<!doctype html><title>Karix inventory fixture</title>", "text/html")

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/api/rcstemplate/fetchTemplates":
                observed["inventory"].append(body)
                self.reply(200, {"status": "success", "templateInfo": []})
            elif self.path == "/api/karix-extension/sync":
                observed["sync"].append({"body": body, "authorization": self.headers.get("Authorization")})
                response = client.post(self.path, headers={"Authorization": self.headers.get("Authorization", "")}, json=body)
                observed["sync"][-1]["status"] = response.status_code
                self.reply(response.status_code, response.json())
            else:
                self.reply(404, {})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate, key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            if not Path(playwright.chromium.executable_path).exists():
                pytest.skip("Install the browser with: playwright install chromium")
            context = playwright.chromium.launch_persistent_context(
                str(tmp_path / "profile"), channel="chromium", headless=True,
                ignore_https_errors=True,
                args=[
                    f"--disable-extensions-except={extension}", f"--load-extension={extension}",
                    "--ignore-certificate-errors", "--no-proxy-server",
                    "--host-resolver-rules="
                    f"MAP rcmui.instaalerts.zone:443 127.0.0.1:{server.server_port}, "
                    f"MAP rcsgui.karix.solutions:443 127.0.0.1:{server.server_port}",
                ],
            )
            try:
                worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
                await_key = "tcl_promo/rcs"
                worker.evaluate("""async ({key, esme, bot, device}) => {
                    await ready;
                    devices[key] = {account: 'tcl_promo', integration: 'rcs',
                        deviceToken: device, deviceExpiresAt: Date.now() / 1000 + 3600,
                        identity: {bot_ids: [bot], esmeaddr: esme}, lastSyncedAt: null, lastSuccessHash: null};
                    activeTarget = key;
                    transient[key] = {pendingSnapshot: null, lastError: '', syncing: false};
                    await persistLocal(); await persistSession();
                }""", {"key": await_key, "esme": esme, "bot": bot, "device": device})
                page = context.pages[0]
                page.goto("https://rcmui.instaalerts.zone/bot_builder_gui/")
                if cold_start:
                    cdp = context.new_cdp_session(page)
                    cdp.send("ServiceWorker.enable")
                    cdp.send("ServiceWorker.stopAllWorkers")
                    cdp.detach()
                capture = """async ({token, esme, bot, user = 'fixture-user'}) => {
                    const response = await fetch('https://rcsgui.karix.solutions/api/rcstemplate/fetchTemplates', {
                        method: 'POST', headers: {Authorization: 'Bearer ' + token,
                            Session: 'fixture-session', User: user, 'Content-Type': 'application/json'},
                        body: JSON.stringify({senderId: bot, esmeaddr: esme})
                    });
                    await response.json(); return response.status;
                }"""
                capture_args = {"token": token, "esme": esme, "bot": bot}
                response_status = page.evaluate(capture, capture_args)
                assert response_status == 200 and observed["inventory"] == [{"senderId": bot, "esmeaddr": esme}]
                deadline = time.monotonic() + 5
                while (not observed["sync"] or "status" not in observed["sync"][-1]) and time.monotonic() < deadline:
                    page.wait_for_timeout(25)
                assert observed["sync"] == [{
                    "authorization": "Bearer " + device, "status": 200,
                    "body": {"account": "tcl_promo", "integration": "rcs", "bot_id": bot,
                             "esmeaddr": esme, "bearer_token": token,
                             "session": "fixture-session", "user": "fixture-user"},
                }], "A successful, exactly matched Karix inventory must reach its paired agent, including after worker restart."
                assert_saved_inventory(payload)
                assert all(method == "POST" for method, _ in state["calls"])
                settings = context.new_page()
                settings.goto("https://rcsgui.karix.solutions/settings")

                def message(kind, account="tcl_promo", integration="rcs"):
                    return settings.evaluate("""({kind, account, integration}) => new Promise((resolve, reject) => {
                        const requestId = crypto.randomUUID();
                        const timer = setTimeout(() => { window.removeEventListener('message', receive); reject(new Error('No scoped response')); }, 5000);
                        function receive(event) {
                            if (event.source !== window || event.origin !== location.origin ||
                                event.data?.type !== 'KARIX_EXTENSION_RESULT' || event.data.requestId !== requestId) return;
                            clearTimeout(timer); window.removeEventListener('message', receive); resolve(event.data);
                        }
                        window.addEventListener('message', receive);
                        window.postMessage({type: kind, requestId, account, integration}, location.origin);
                    })""", {"kind": kind, "account": account, "integration": integration})

                browser_state = message("KARIX_EXTENSION_SCOPED_STATUS")
                assert browser_state["paired"] and not browser_state["pending"] and browser_state["error"] is None
                other_scope = message("KARIX_EXTENSION_SCOPED_STATUS", "bajaj", "whatsapp")
                assert not other_scope["paired"] and not other_scope["pending"] and other_scope["last_synced_at"] is None
                assert all(secret not in json.dumps(browser_state) + json.dumps(other_scope)
                           for secret in (device, token, payload["session"]))

                # A newly captured session rejected by the backend stays retryable in Settings.
                state["token"], state["status"] = token + "-renewed", 401
                renewed = {**payload, "bearer_token": state["token"]}
                assert page.evaluate(capture, {**capture_args, "token": state["token"]}) == 200
                deadline = time.monotonic() + 5
                while (len(observed["sync"]) < 2 or "status" not in observed["sync"][-1]) and time.monotonic() < deadline:
                    page.wait_for_timeout(25)
                assert observed["sync"][-1]["status"] == 422
                browser_state = message("KARIX_EXTENSION_SCOPED_STATUS")
                assert browser_state["paired"] and browser_state["pending"]
                assert browser_state["error"] == "provider_validation_failed"
                assert portal_sessions.load_session("tcl_promo", "rcs")["bearer_token"] == token
                assert all(secret not in json.dumps(browser_state) for secret in (device, state["token"], payload["session"]))
                state["status"] = 200
                retried = message("KARIX_EXTENSION_RETRY")
                assert retried["ok"] and retried["account"] == "tcl_promo" and retried["integration"] == "rcs"
                assert_saved_inventory(renewed)
                browser_state = message("KARIX_EXTENSION_SCOPED_STATUS")
                assert browser_state["paired"] and not browser_state["pending"] and browser_state["error"] is None

                # Oversized authentication is rejected before transport, never truncated or saved.
                sync_count = len(observed["sync"])
                assert page.evaluate(capture, {**capture_args, "token": state["token"], "user": "x" * 301}) == 200
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    browser_state = message("KARIX_EXTENSION_SCOPED_STATUS")
                    if browser_state["error"] == "capture_invalid":
                        break
                    page.wait_for_timeout(25)
                assert browser_state["error"] == "capture_invalid" and not browser_state["pending"]
                assert len(observed["sync"]) == sync_count
                assert_saved_inventory(renewed)
            finally:
                context.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
