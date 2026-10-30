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
from fastapi.testclient import TestClient
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

import api
import config
import db
import moengage_sync
import portal_sessions
import rcs_client
import rcs_config
import submission_client
import vilpower_client


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
                        identity: {bot_ids: [bot], esmeaddr: esme}, lastSyncedAt: null};
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


@pytest.fixture
def scoped_browser(tmp_path, monkeypatch, provision_user):
    """Run the downloaded extension against real, loopback-only portal and agent servers."""
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlsplit

    origin = "https://rcsgui.karix.solutions"
    dashboard = "https://dashboard-03.moengage.com"
    waba, esme = "123456789012345", "72111100000000"
    workspace, other_workspace = "a" * 24, "b" * 24
    encoded = base64.b64encode(("fixture" + esme + "FIXTURE").encode()).decode().rstrip("=")
    token = "header." + encoded + ".fixture-signature"
    state = {"sync": [], "inventory": [], "validation": [], "drop_sync": False,
             "drop_disconnect": False, "inventory_status": 200, "inventory_gate": None, "validation_gate": None}
    state["sms_entity"] = "1101637310000019220"
    state["sms_validation"] = []

    def validate_sms(cookie, entity_id, client="tata"):
        state["sms_validation"].append({"cookie": cookie, "entity_id": entity_id, "client": client})
        if cookie != "portal_session=sms-request-cookie" or state["sms_entity"] != entity_id:
            raise ValueError("Provider rejected session")
        return {"entity_id": entity_id, "cookie": cookie, "provider": "vilpower"}

    monkeypatch.setattr(vilpower_client, "validate_session", validate_sms)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "_load_env_file", lambda: None)
    monkeypatch.setenv("KARIX_EXTENSION_AGENT_ORIGINS", origin)
    monkeypatch.setattr(api.QUEUE_MANAGER, "notify_credentials_updated", lambda account: None)
    _, bajaj_headers = provision_user("bajaj")
    _, tata_headers = provision_user("tata")
    client = TestClient(api.app)
    for account, app in (("bajaj", workspace), ("tcl_promo", other_workspace)):
        prefix = account.upper()
        portal_sessions.save_settings(account, "whatsapp", {
            prefix + "_WABA_ID": waba, prefix + "_ESMEADDR": esme,
        })
        portal_sessions.save_settings(account, "moengage", {
            prefix + "_MOENGAGE_BASE_URL": dashboard, prefix + "_MOENGAGE_WORKSPACE_ID": app,
        })

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
            path = urlsplit(self.path).path
            if path in ("/settings", "/bot_builder_gui/", "/"):
                self.reply(200, "<!doctype html><title>Scoped portal fixture</title>", "text/html")
            elif path in ("/dash/auth/listApps", "/appsettings", "/template_metadata"):
                state["inventory"].append({"path": self.path, "headers": dict(self.headers)})
                if path == "/dash/auth/listApps" and not isinstance(self.connection, ssl.SSLSocket):
                    if (self.headers.get("Authorization") != "Bearer captured-moengage"
                            or self.headers.get("refreshtoken") != "captured-refresh"
                            or self.headers.get("Cookie") != "portal_session=request-cookie"):
                        self.reply(401, {})
                        return
                if state["inventory_gate"] is not None:
                    state["inventory_started"].set()
                    assert state["inventory_gate"].wait(5), "Release the in-flight inventory request."
                self.reply(state["inventory_status"], {"data": [
                    {"id": app, "activated": True, "is_test": False}
                    for app in (workspace, other_workspace)
                ]})
            elif path == "/dash/auth/changeApp":
                app = parse_qs(urlsplit(self.path).query)["app_id"][0]
                state["validation"].append({"workspace": app, "headers": dict(self.headers)})
                self.reply(200, {"code": 200, "status": "success", "data": {
                    "bearer": "bound-" + app, "refresh_token": "renewed-" + app,
                    "app_access_details": "ALLOWED",
                }})
            else:
                self.reply(404, {})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.startswith("/api/karix-extension/"):
                if self.path.endswith("/sync"):
                    state["sync"].append({"body": body, "authorization": self.headers.get("Authorization")})
                    if state["drop_sync"]:
                        self.close_connection = True
                        return
                response = client.post(self.path, headers={
                    "Authorization": self.headers.get("Authorization", ""),
                }, json=body)
                self.reply(response.status_code, response.json())
            elif self.path == "/content_templates/contentTemplateJson/":
                state["inventory"].append({"body": body, "headers": dict(self.headers)})
                self.reply(state["inventory_status"], {"data": []})
            elif self.path == "/v1.0/templates/getAllTemplates":
                if isinstance(self.connection, ssl.SSLSocket):
                    state["inventory"].append({"body": body, "headers": dict(self.headers)})
                    self.reply(state["inventory_status"], {"Success": {"templates": []}})
                else:
                    state["validation"].append({"body": body, "headers": dict(self.headers)})
                    if state["validation_gate"] is not None:
                        state["validation_started"].set()
                        assert state["validation_gate"].wait(10), "Release backend session validation."
                    valid = (
                        body.get("wabaId") == waba and body.get("esmeaddr") == esme
                        and self.headers.get("Authorization") == "Bearer " + token
                        and self.headers.get("Session") == "wa-session"
                        and self.headers.get("User") == "wa-user"
                    )
                    self.reply(200 if valid else 401, {"Success": {"templates": []}})
            else:
                self.reply(404, {})

        def do_DELETE(self):
            if state["drop_disconnect"]:
                self.close_connection = True
                return
            response = client.delete(self.path, headers={
                "Authorization": self.headers.get("Authorization", ""),
            })
            self.reply(response.status_code, response.json())

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    monkeypatch.setattr(
        submission_client, "KARIX_BASE_URL",
        f"http://127.0.0.1:{provider.server_port}/v1.0/templates",
    )
    original_get = moengage_sync.requests.get

    def local_moengage_get(url, **kwargs):
        assert url.startswith(dashboard + "/"), "Provider checks must never leave loopback."
        return original_get(f"http://127.0.0.1:{provider.server_port}" + url[len(dashboard):], **kwargs)

    monkeypatch.setattr(moengage_sync.requests, "get", local_moengage_get)
    extension = tmp_path / "scoped-extension"
    downloaded = client.post("/api/karix-extension/download", headers=bajaj_headers, json={"agent_origin": origin})
    assert downloaded.status_code == 200, downloaded.text
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        archive.extractall(extension)
    certificate, key = tmp_path / "scoped-certificate.pem", tmp_path / "scoped-key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
         "-subj", "/CN=auth-sync.test", "-keyout", str(key), "-out", str(certificate)],
        check=True, capture_output=True,
    )
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
                str(tmp_path / "scoped-profile"), channel="chromium", headless=True,
                ignore_https_errors=True,
                args=[
                    f"--disable-extensions-except={extension}", f"--load-extension={extension}",
                    "--ignore-certificate-errors", "--no-proxy-server",
                    "--host-resolver-rules=" + ", ".join(
                        f"MAP {host}:443 127.0.0.1:{server.server_port}"
                        for host in ("rcmui.instaalerts.zone", "rcsgui.karix.solutions", "dashboard-03.moengage.com", "www.vilpower.in")
                    ),
                ],
            )
            try:
                # A worker can start between the cache read and event subscription.
                try:
                    worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
                except PlaywrightTimeoutError:
                    if not context.service_workers:
                        raise
                    worker = context.service_workers[0]
                worker.evaluate("() => ready")
                settings = context.pages[0]
                settings.goto(origin + "/settings")
                portal = context.new_page()
                portal.goto("https://rcmui.instaalerts.zone/bot_builder_gui/")
                moengage = context.new_page()
                moengage.goto(dashboard + "/")
                sms = context.new_page()
                sms.goto("https://www.vilpower.in/")
                popup = context.new_page()
                popup.goto(worker.evaluate("() => chrome.runtime.getURL('popup.html')"))

                def message(kind, account="bajaj", integration="whatsapp", **extra):
                    return settings.evaluate("""message => new Promise((resolve, reject) => {
                        const requestId = crypto.randomUUID();
                        const timer = setTimeout(() => {
                            window.removeEventListener('message', receive); reject(new Error('No scoped response'));
                        }, 5000);
                        function receive(event) {
                            if (event.source !== window || event.origin !== location.origin ||
                                event.data?.type !== 'KARIX_EXTENSION_RESULT' || event.data.requestId !== requestId) return;
                            clearTimeout(timer); window.removeEventListener('message', receive); resolve(event.data);
                        }
                        window.addEventListener('message', receive);
                        window.postMessage({...message, requestId}, location.origin);
                    })""", {"type": kind, "account": account, "integration": integration, **extra})

                def pair_target(account="bajaj", integration="whatsapp"):
                    headers = bajaj_headers if account == "bajaj" else tata_headers
                    response = client.post("/api/karix-extension/pairing", headers=headers, json={
                        "agent_origin": origin, "account": account, "integration": integration,
                    })
                    assert response.status_code == 200, response.text
                    result = message("KARIX_EXTENSION_PAIR", account, integration, code=response.json()["code"])
                    assert result["ok"] and result["account"] == account and result["integration"] == integration
                    return result

                def capture_wa(**overrides):
                    return portal.evaluate("""async ({waba, esme, token, ...changes}) => {
                        const headers = {Authorization: 'Bearer ' + token, Session: 'wa-session',
                            User: 'wa-user', 'Content-Type': 'application/json', ...changes.headers};
                        for (const [name, value] of Object.entries(headers)) if (value === null) delete headers[name];
                        const response = await fetch('https://rcsgui.karix.solutions/v1.0/templates/getAllTemplates', {
                            method: 'POST', headers,
                            body: JSON.stringify({wabaId: waba, esmeaddr: esme, ...changes.body})
                        });
                        await response.json(); return response.status;
                    }""", {"waba": waba, "esme": esme, "token": token, **overrides})

                def capture_moengage(path="/appsettings", **headers):
                    return moengage.evaluate("""async ({path, changes}) => {
                        const headers = {Authorization: 'Bearer captured-moengage', refreshtoken: 'captured-refresh', ...changes};
                        for (const [name, value] of Object.entries(headers)) if (value === null) delete headers[name];
                        const response = await fetch(path, {headers, credentials: 'include', cache: 'no-store'});
                        await response.json(); return response.status;
                    }""", {"path": path, "changes": headers})

                def wait_status(account="bajaj", integration="whatsapp", **expected):
                    deadline = time.monotonic() + 5
                    while True:
                        result = message("KARIX_EXTENSION_SCOPED_STATUS", account, integration)
                        if all(result.get(key) == value for key, value in expected.items()):
                            return result
                        assert time.monotonic() < deadline, f"Scoped status did not reach {expected}: {result}"
                        settings.wait_for_timeout(25)

                def settle():
                    current_worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
                    current_worker.evaluate("""async () => {
                        await ready;
                        while (requests.size) await new Promise(resolve => setTimeout(resolve, 10));
                        await operations;
                    }""")

                yield SimpleNamespace(
                    client=client, headers=bajaj_headers, context=context, state=state, settle=settle,
                    settings=settings, portal=portal, moengage=moengage, sms=sms, popup=popup,
                    pair=pair_target, message=message, capture_wa=capture_wa, capture_moengage=capture_moengage,
                    wait_status=wait_status, waba=waba, esme=esme, token=token, workspace=workspace,
                    other_workspace=other_workspace, dashboard=dashboard,
                )
            finally:
                context.close()
    finally:
        client.close()
        for running in (server, provider):
            running.shutdown()
            running.server_close()
        thread.join()
        provider_thread.join()


@pytest.mark.parametrize("esme_sentinel", [False, True], ids=["exact-esme", "esme-zero"])
def test_whatsapp_complete_request_capture_is_scoped_and_backend_validated(scoped_browser, esme_sentinel):
    flow = scoped_browser
    from playwright.sync_api import expect

    flow.pair()
    flow.pair("tcl_promo")
    flow.pair("bajaj", "moengage")
    selected = flow.message("KARIX_EXTENSION_SELECT")
    assert selected["ok"] and selected["account"] == "bajaj" and selected["integration"] == "whatsapp"
    flow.wait_status(capture_active=True, pending=False, last_synced_at=None)
    expect(flow.popup.locator("#target")).to_have_value("bajaj/whatsapp")
    expect(flow.popup.locator("#state")).to_have_text("Paired — awaiting matching inventory request")
    assert not flow.message("KARIX_EXTENSION_SELECT", "tcl_trans", "whatsapp")["ok"]
    assert flow.message("KARIX_EXTENSION_SCOPED_STATUS")["capture_active"]
    if esme_sentinel:
        cdp = flow.context.new_cdp_session(flow.portal)
        cdp.send("ServiceWorker.enable")
        cdp.send("ServiceWorker.stopAllWorkers")
        cdp.detach()
    assert flow.capture_wa(body={"esmeaddr": 0} if esme_sentinel else {}) == 200
    status = flow.wait_status(pending=False, error=None)
    deadline = time.monotonic() + 5
    while status["last_synced_at"] is None and time.monotonic() < deadline:
        flow.settings.wait_for_timeout(25)
        status = flow.message("KARIX_EXTENSION_SCOPED_STATUS")
    assert status["last_synced_at"] is not None
    assert [request["body"] for request in flow.state["sync"]] == [{
        "account": "bajaj", "integration": "whatsapp", "waba_id": flow.waba, "esmeaddr": flow.esme,
        "bearer_token": flow.token, "session": "wa-session", "user": "wa-user",
    }]
    assert portal_sessions.load_session("tcl_promo", "whatsapp") is None
    assert portal_sessions.load_session("bajaj", "moengage") is None
    saved = portal_sessions.session_record("bajaj", "whatsapp")
    assert flow.token not in saved["encrypted_credentials"] and "wa-session" not in saved["encrypted_credentials"]
    assert flow.state["validation"][-1]["body"]["esmeaddr"] == flow.esme
    # Foreign WABAs and conflicting aliases must not route to any paired account.
    for body in ({"wabaId": "999"}, {"waba_id": "999"}, {"esmeaddr": "72999900000000"}):
        assert flow.capture_wa(body=body) == 200
    flow.settle()
    assert len(flow.state["sync"]) == 1
    assert flow.capture_wa(headers={"Session": None}) == 200
    flow.wait_status(error="capture_invalid", pending=False)
    foreign = base64.b64encode(b"fixture72999900000000FOREIGN").decode().rstrip("=")
    assert flow.capture_wa(token="header." + foreign + ".signature") == 200
    flow.settle()
    assert len(flow.state["sync"]) == 1
    assert portal_sessions.session_record("bajaj", "whatsapp") == saved
    assert all(secret not in json.dumps(status) for secret in (flow.token, "wa-session"))


def test_offline_retry_revocation_and_disconnect_preserve_last_good_session(scoped_browser):
    flow = scoped_browser
    from playwright.sync_api import expect

    flow.pair()
    flow.state["drop_sync"] = True
    assert flow.capture_wa() == 200
    pending = flow.wait_status(pending=True, error="network_error", syncing=False)
    assert pending["last_synced_at"] is None and portal_sessions.load_session("bajaj", "whatsapp") is None
    expect(flow.popup.locator("#retry")).to_be_enabled()
    flow.state["drop_sync"] = False
    flow.state["validation_gate"] = threading.Event()
    flow.state["validation_started"] = threading.Event()
    flow.popup.locator("#retry").click()
    assert flow.state["validation_started"].wait(5)
    expect(flow.popup.locator("#state")).to_have_text("Backend validation in progress")
    expect(flow.popup.locator("#retry")).to_be_disabled()
    assert flow.message("KARIX_EXTENSION_SCOPED_STATUS")["syncing"]
    flow.state["validation_gate"].set()
    expect(flow.popup.locator("#result")).to_contain_text("validated by the backend")
    flow.state["validation_gate"] = None
    accepted = flow.wait_status(pending=False, error=None)
    original = portal_sessions.session_record("bajaj", "whatsapp")
    flow.state["drop_disconnect"] = True
    flow.popup.locator("#disconnect").click()
    expect(flow.popup.locator("#error")).to_contain_text("Local pairing was preserved")
    assert flow.message("KARIX_EXTENSION_SCOPED_STATUS")["paired"]
    flow.state["drop_disconnect"] = False
    # The same captured bytes must be validated again, not reported successful from a permanent hash cache.
    flow.state["inventory_status"] = 401
    assert flow.capture_wa() == 401
    flow.wait_status(pending=False, error="inventory_failed")
    assert len(flow.state["sync"]) == 2
    flow.state["inventory_status"] = 200
    assert flow.client.delete("/api/karix-extension/pairing?account=bajaj&integration=whatsapp",
                              headers=flow.headers).status_code == 200
    assert flow.capture_wa() == 200
    revoked = flow.wait_status(paired=False, capture_active=False, pending=True, error="device_expired")
    assert revoked["last_synced_at"] == accepted["last_synced_at"]
    assert portal_sessions.session_record("bajaj", "whatsapp") == original
    expect(flow.popup.locator("#state")).to_have_text("Pairing expired")
    expect(flow.popup.locator("#retry")).to_be_disabled()
    flow.popup.locator("#disconnect").click()
    expect(flow.popup.locator("#state")).to_have_text("No paired targets")
    assert portal_sessions.session_record("bajaj", "whatsapp") == original
    assert all(secret not in json.dumps(revoked) for secret in (flow.token, "wa-session"))


def test_moengage_captures_request_bound_headers_without_cross_account_fanout(scoped_browser):
    flow = scoped_browser
    from playwright.sync_api import expect

    flow.pair(integration="moengage")
    flow.pair("tcl_promo", "moengage")
    flow.message("KARIX_EXTENSION_SELECT", integration="moengage")
    expect(flow.popup.locator("#target")).to_have_value("bajaj/moengage")
    expect(flow.popup.locator("#capture-mode")).to_contain_text("Active MoEngage capture target")
    flow.context.add_cookies([{
        "name": "portal_session", "value": "request-cookie", "url": flow.dashboard,
        "secure": True, "httpOnly": True, "sameSite": "Lax",
    }])
    flow.moengage.evaluate("""() => {
        localStorage.setItem('bearer', 'wrong-storage-bearer');
        localStorage.setItem('refreshToken', 'wrong-storage-refresh');
    }""")
    # Separate incomplete requests must never be stitched together into a full session.
    assert flow.capture_moengage(refreshtoken=None) == 200
    flow.wait_status(integration="moengage", error="capture_invalid", pending=False)
    assert flow.capture_moengage(Authorization=None) == 200
    flow.wait_status(integration="moengage", error="capture_invalid", pending=False)
    assert not flow.state["sync"]
    assert flow.capture_moengage() == 200
    status = flow.wait_status(integration="moengage", error=None, pending=False)
    deadline = time.monotonic() + 5
    while status["last_synced_at"] is None and time.monotonic() < deadline:
        flow.settings.wait_for_timeout(25)
        status = flow.message("KARIX_EXTENSION_SCOPED_STATUS", integration="moengage")
    assert status["last_synced_at"] is not None
    assert [request["body"] for request in flow.state["sync"]] == [{
        "account": "bajaj", "integration": "moengage", "base_url": flow.dashboard,
        "workspace_id": flow.workspace, "bearer_token": "captured-moengage",
        "refresh_token": "captured-refresh", "cookie": "portal_session=request-cookie",
    }]
    saved = portal_sessions.load_session("bajaj", "moengage")
    assert saved["bearer_token"] == "bound-" + flow.workspace
    assert saved["refresh_token"] == "renewed-" + flow.workspace
    assert saved["cookie"] == "portal_session=request-cookie"
    assert portal_sessions.load_session("tcl_promo", "moengage") is None
    assert portal_sessions.load_session("bajaj", "whatsapp") is None
    # Switching the active target while an unscoped request is in flight must not reassign its snapshot.
    flow.state["inventory_gate"] = threading.Event()
    flow.state["inventory_started"] = threading.Event()
    flow.moengage.evaluate("""() => {
        window.inflight = fetch('/appsettings', {credentials: 'include', headers: {
            Authorization: 'Bearer old-target-request', refreshtoken: 'old-target-refresh'
        }}).then(response => response.json());
    }""")
    assert flow.state["inventory_started"].wait(5)
    switched = flow.message("KARIX_EXTENSION_SELECT", "tcl_promo", "moengage")
    assert switched["ok"]
    flow.state["inventory_gate"].set()
    flow.moengage.evaluate("() => window.inflight")
    flow.settle()
    flow.state["inventory_gate"] = None
    assert len(flow.state["sync"]) == 1
    assert portal_sessions.load_session("bajaj", "moengage") == saved
    assert portal_sessions.load_session("tcl_promo", "moengage") is None
    # Explicit foreign workspace is not redirected to the currently selected account.
    assert flow.capture_moengage("/template_metadata?app_id=" + "f" * 24) == 200
    flow.settle()
    assert len(flow.state["sync"]) == 1
    assert all(secret not in json.dumps(status) for secret in ("captured-moengage", "captured-refresh", "request-cookie"))


def test_pairing_scope_mismatch_never_replaces_the_connected_target(scoped_browser):
    flow = scoped_browser
    flow.pair()
    original = flow.message("KARIX_EXTENSION_SCOPED_STATUS")
    pairing = flow.client.post("/api/karix-extension/pairing", headers=flow.headers, json={
        "agent_origin": "https://rcsgui.karix.solutions", "account": "bajaj", "integration": "whatsapp",
    })
    assert pairing.status_code == 200
    mismatched = flow.message(
        "KARIX_EXTENSION_PAIR", "tcl_promo", "whatsapp", code=pairing.json()["code"],
    )
    assert not mismatched["ok"] and mismatched["error_code"] == "request_failed"
    current = flow.message("KARIX_EXTENSION_SCOPED_STATUS")
    assert (current["account"], current["integration"], current["paired"], current["capture_active"]) == (
        original["account"], original["integration"], True, True,
    )
    assert not flow.message("KARIX_EXTENSION_SCOPED_STATUS", "tcl_promo", "whatsapp")["paired"]
    assert not flow.message("KARIX_EXTENSION_SELECT", "tcl_promo", "whatsapp")["ok"]
    assert flow.message("KARIX_EXTENSION_SCOPED_STATUS")["capture_active"]
    # Matching-origin traffic outside Settings has no authority to activate a target.
    flow.settings.goto("https://rcsgui.karix.solutions/")
    unauthorized = flow.settings.evaluate("""() => new Promise(resolve => {
        const requestId = crypto.randomUUID();
        function receive(event) {
            if (event.data?.requestId === requestId && event.data?.type === 'KARIX_EXTENSION_RESULT') {
                window.removeEventListener('message', receive); resolve(event.data);
            }
        }
        window.addEventListener('message', receive);
        window.postMessage({type: 'KARIX_EXTENSION_SELECT', requestId,
            account: 'tcl_promo', integration: 'whatsapp'}, location.origin);
        setTimeout(() => { window.removeEventListener('message', receive); resolve(null); }, 150);
    })""")
    assert unauthorized is None
    flow.settings.goto("https://rcsgui.karix.solutions/settings")
    assert flow.message("KARIX_EXTENSION_SCOPED_STATUS")["capture_active"]
    assert pairing.json()["code"] not in json.dumps(mismatched)


def test_settings_capture_switch_waits_for_slow_validation_without_losing_browser_status(scoped_browser):
    flow = scoped_browser
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    compiled = subprocess.run(
        ["node", "-e", """
            const ts = require('typescript');
            const fs = require('node:fs');
            process.stdout.write(ts.transpileModule(fs.readFileSync(process.argv[1], 'utf8'), {
                compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX}
            }).outputText);
        """, str(frontend / "components" / "KarixAuthSync.tsx")],
        cwd=frontend, check=True, capture_output=True, text=True,
    ).stdout
    flow.settings.add_script_tag(content=(
        "(() => { const exports = {}; const require = () => ({}); " + compiled
        + " window.authSyncMessage = extensionMessage; })();"
    ))
    flow.pair()
    flow.pair("tcl_promo")
    flow.message("KARIX_EXTENSION_SELECT", "bajaj", "whatsapp")
    gate = threading.Event()
    flow.state["validation_gate"] = gate
    flow.state["validation_started"] = threading.Event()
    try:
        assert flow.capture_wa() == 200
        assert flow.state["validation_started"].wait(5)
        status = flow.message("KARIX_EXTENSION_SCOPED_STATUS", "bajaj", "whatsapp")
        assert status["ok"] and status["syncing"]
        flow.settings.evaluate("""() => {
            window.captureSwitch = window.authSyncMessage('KARIX_EXTENSION_SELECT', new AbortController().signal,
                {account: 'tcl_promo', integration: 'whatsapp'})
                .then(result => ({result}), error => ({error: error.message}));
        }""")
        timer = threading.Timer(3, gate.set)
        timer.start()
        try:
            switched = flow.settings.evaluate("() => window.captureSwitch")
        finally:
            timer.cancel()
        assert "error" not in switched, switched
        assert switched["result"]["account"] == "tcl_promo"
        status = flow.message("KARIX_EXTENSION_SCOPED_STATUS", "tcl_promo", "whatsapp")
        assert status["capture_active"] and not status["syncing"]
    finally:
        gate.set()
        flow.state["validation_gate"] = None


def test_sms_cookie_only_inventory_capture_and_worker_recovery(scoped_browser):
    flow = scoped_browser
    flow.pair()
    flow.pair("tata", "sms")
    assert flow.message("KARIX_EXTENSION_SELECT")["ok"]
    flow.popup.reload()
    sms_label = flow.popup.locator("#target option").filter(has_text="SMS").inner_text(timeout=2000)
    flow.popup.select_option("#target", label=sms_label)
    flow.wait_status("tata", "sms", capture_active=True)
    flow.context.add_cookies([{
        "name": "portal_session", "value": "sms-request-cookie", "domain": "www.vilpower.in",
        "path": "/", "secure": True, "httpOnly": True, "sameSite": "Strict",
    }])

    def capture(path="/content_templates/contentTemplateJson/"):
        return flow.sms.evaluate("""async path => {
            const response = await fetch(path, {method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json'}, body: '{}'});
            await response.json(); return response.status;
        }""", path)

    assert capture() == 200
    flow.settle()
    assert flow.state["sync"][-1]["body"] == {
        "account": "tata", "integration": "sms", "entity_id": "1101637310000019220",
        "cookie": "portal_session=sms-request-cookie",
    }
    assert portal_sessions.load_session("tata", "sms")["cookie"] == "portal_session=sms-request-cookie"
    assert flow.message("KARIX_EXTENSION_SCOPED_STATUS")["last_synced_at"] is None
    count = len(flow.state["sync"])
    # No inactive SMS capture, even with a valid logged-in portal.
    assert flow.message("KARIX_EXTENSION_SELECT")["ok"]
    assert capture() == 200
    flow.settle()
    assert len(flow.state["sync"]) == count
    assert flow.message("KARIX_EXTENSION_SELECT", "tata", "sms")["ok"]
    flow.state["inventory_status"] = 401
    assert capture() == 401
    flow.settle()
    assert len(flow.state["sync"]) == count
    assert flow.wait_status("tata", "sms", error="inventory_failed")
    flow.state["inventory_status"] = 200
    # A failed backend submission retains renewable credentials only in session storage.
    flow.state["drop_sync"] = True
    assert capture() == 200
    flow.wait_status("tata", "sms", pending=True, error="network_error")
    worker = flow.context.service_workers[0]
    local = worker.evaluate("async () => chrome.storage.local.get(null)")
    assert "sms-request-cookie" not in json.dumps(local)
    cdp = flow.context.new_cdp_session(flow.sms)
    cdp.send("ServiceWorker.enable")
    cdp.send("ServiceWorker.stopAllWorkers")
    cdp.detach()
    flow.state["drop_sync"] = False
    assert flow.message("KARIX_EXTENSION_RETRY", "tata", "sms")["ok"]
    flow.wait_status("tata", "sms", pending=False, error=None)
    # Wrong live entity is backend-rejected without replacing the saved credential.
    saved = portal_sessions.session_record("tata", "sms")
    flow.state["sms_entity"] = "another-entity"
    assert capture() == 200
    flow.wait_status("tata", "sms", pending=True, error="provider_validation_failed")
    assert portal_sessions.session_record("tata", "sms")["updated_at"] == saved["updated_at"]


def test_sms_worker_registered_listeners_reject_invalid_capture():
    extension = Path(__file__).resolve().parents[1] / "browser-extension" / "karix-auth-sync"
    result = subprocess.run(["node", "-e", r"""
        const vm = require('node:vm'), fs = require('node:fs'), assert = require('node:assert/strict');
        const listeners = {}, stores = {local: {}, session: {}}, syncs = [];
        const event = name => ({addListener(fn) { listeners[name] = fn; }});
        const chrome = {
            runtime: {id:'fixture', getURL:p=>'chrome-extension://fixture/'+p, onMessage:event('message')},
            storage: Object.fromEntries(['local','session'].map(n => [n, {
                async setAccessLevel() {}, async get() { return structuredClone(stores[n]); },
                async set(v) { Object.assign(stores[n], structuredClone(v)); },
            }])),
            webRequest: Object.fromEntries(['onBeforeRequest','onBeforeSendHeaders','onCompleted',
                'onErrorOccurred','onBeforeRedirect'].map(n=>[n,event(n)])),
        };
        const ctx = vm.createContext({chrome, URL, TextDecoder, Uint8Array, AbortSignal, atob,
            importScripts() {}, KARIX_SYNC_CONFIG:{agentOrigin:'https://agent.test'},
            fetch: async (_u,o) => {
                syncs.push(JSON.parse(o.body));
                return {ok:true,json:async()=>({ok:true,account:'tata',integration:'sms',last_synced_at:1})};
            }});
        const run = s=>vm.runInContext(s,ctx);
        (async()=>{
            run(fs.readFileSync(process.argv[1]+'/background.js','utf8')); await run('ready');
            await run(`mutate(async()=>{
                devices['tata/sms']={account:'tata',integration:'sms',deviceToken:'device',
                    deviceExpiresAt:Date.now()/1000+3600,identity:{entity_id:'1101637310000019220'}};
                activeTarget='tata/sms'; await persistLocal();
            })`);
            let id=0;
            const base={url:'https://www.vilpower.in/content_templates/contentTemplateJson/',method:'POST'};
            async function capture(changes={},headers=[{name:'Cookie',value:'sessionid=fixture; csrf=atomic'}]) {
                const d={...base,requestId:String(++id),...changes};
                listeners.onBeforeRequest(d);
                listeners.onBeforeSendHeaders({...d,requestHeaders:headers});
                listeners.onCompleted({statusCode:200,fromCache:false,...d});
                await run('operations');
            }
            await capture();
            assert.deepEqual(syncs,[{account:'tata',integration:'sms',entity_id:'1101637310000019220',
                cookie:'sessionid=fixture; csrf=atomic'}]);
            assert(!JSON.stringify(stores.local).includes('sessionid='));
            for(const change of [{method:'GET'},{url:'https://evil.test/content_templates/contentTemplateJson/'},
                {url:'https://www.vilpower.in/content_templates/contentAdd/'},
                {url:'https://www.vilpower.in/login/'},{url:'https://www.vilpower.in/otp/'},
                {statusCode:401},{statusCode:500},{fromCache:true}]) await capture(change);
            for(const headers of [[],[{name:'Cookie',value:''}],
                [{name:'Cookie',value:'one'},{name:'cookie',value:'two'}],
                [{name:'Cookie',value:'x'.repeat(32001)}],
                [{name:'Cookie',value:'sessionid=bad\r\nInjected: yes'}]]) await capture({},headers);
            assert.equal(syncs.length,1);
            // Two request IDs cannot supply each other's missing credentials or completion.
            listeners.onBeforeRequest({...base,requestId:'first'});
            listeners.onBeforeRequest({...base,requestId:'second'});
            listeners.onBeforeSendHeaders({...base,requestId:'first',
                requestHeaders:[{name:'Cookie',value:'sessionid=uncompleted'}]});
            listeners.onCompleted({...base,requestId:'second',statusCode:200});
            listeners.onErrorOccurred({...base,requestId:'first'});
            await run('operations');
            assert.equal(syncs.length,1);
            await run("mutate(async()=>{activeTarget=''})"); await capture();
            assert.equal(syncs.length,1);
            await run("mutate(async()=>{activeTarget='tata/sms';devices['tata/sms'].deviceExpiresAt=0})");
            await capture(); assert.equal(syncs.length,1);
        })().catch(()=>{console.error('SMS listener regression failed');process.exitCode=1});
    """, str(extension)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
