"""Exercise MV3 capture from Karix's real frontend origin, not its API origin."""

import base64
import json
import shutil
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


@pytest.mark.parametrize("cold_start", [False, True], ids=["awake", "worker-restart"])
def test_karix_frontend_inventory_syncs_exact_paired_target(tmp_path, cold_start):
    source = Path(__file__).resolve().parents[1] / "browser-extension" / "karix-auth-sync"
    extension = tmp_path / "extension"
    shutil.copytree(source, extension)
    # Both provider and agent are loopback fixtures; no production credential or host is contacted.
    (extension / "config.js").write_text(
        "globalThis.KARIX_SYNC_CONFIG = {agentOrigin: 'https://rcsgui.karix.solutions'};"
    )
    certificate, key = tmp_path / "certificate.pem", tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
         "-subj", "/CN=auth-sync.test", "-keyout", str(key), "-out", str(certificate)],
        check=True, capture_output=True,
    )
    esme, bot = "72434700000000", "Uv9tdd0KNADbq3pX"
    signed_payload = base64.b64encode(("fixture" + esme + "TATA").encode()).decode().rstrip("=")
    token = "header." + signed_payload + ".fixture-signature"
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
            if self.path != "/bot_builder_gui/":
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
                self.reply(200, {"ok": True, "account": "tcl_promo", "integration": "rcs",
                                 "last_synced_at": time.time()})
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
                worker.evaluate("""async ({key, esme, bot}) => {
                    await ready;
                    devices[key] = {account: 'tcl_promo', integration: 'rcs',
                        deviceToken: 'fixture-device-token', deviceExpiresAt: Date.now() / 1000 + 3600,
                        identity: {bot_ids: [bot], esmeaddr: esme}, lastSyncedAt: null, lastSuccessHash: null};
                    activeTarget = key;
                    transient[key] = {pendingSnapshot: null, lastError: '', syncing: false};
                    await persistLocal(); await persistSession();
                }""", {"key": await_key, "esme": esme, "bot": bot})
                page = context.pages[0]
                page.goto("https://rcmui.instaalerts.zone/bot_builder_gui/")
                if cold_start:
                    cdp = context.new_cdp_session(page)
                    cdp.send("ServiceWorker.enable")
                    cdp.send("ServiceWorker.stopAllWorkers")
                    cdp.detach()
                response_status = page.evaluate("""async ({token, esme, bot}) => {
                    const response = await fetch('https://rcsgui.karix.solutions/api/rcstemplate/fetchTemplates', {
                        method: 'POST', headers: {Authorization: 'Bearer ' + token,
                            Session: 'fixture-session', User: 'fixture-user', 'Content-Type': 'application/json'},
                        body: JSON.stringify({senderId: bot, esmeaddr: esme})
                    });
                    await response.json(); return response.status;
                }""", {"token": token, "esme": esme, "bot": bot})
                assert response_status == 200 and observed["inventory"] == [{"senderId": bot, "esmeaddr": esme}]
                deadline = time.monotonic() + 5
                while not observed["sync"] and time.monotonic() < deadline:
                    page.wait_for_timeout(25)
                assert observed["sync"] == [{
                    "authorization": "Bearer fixture-device-token",
                    "body": {"account": "tcl_promo", "integration": "rcs", "bot_id": bot,
                             "esmeaddr": esme, "bearer_token": token,
                             "session": "fixture-session", "user": "fixture-user"},
                }], "A successful, exactly matched Karix inventory must reach its paired agent, including after worker restart."
            finally:
                context.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
