"""Auth health checks expose health, never provider session secrets or echoed errors."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

import api
import config
import portal_sessions


@pytest.mark.parametrize("provider_status", [200, 401])
def test_moengage_health_never_returns_saved_credentials(tmp_path, monkeypatch, provision_user, provider_status):
    bearer, refresh, cookie = "private-fixture-bearer", "private-fixture-refresh", "session=private-fixture-cookie"

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            assert self.path == "/template_metadata?template_type=rcs"
            assert self.headers["Authorization"] == "Bearer " + bearer
            assert self.headers["Cookie"] == cookie
            data = {"data": [{"name": "approved-template"}]} if provider_status == 200 else {
                "error": " ".join((bearer, refresh, cookie)),
            }
            payload = json.dumps(data).encode()
            self.send_response(provider_status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "_load_env_file", lambda: None)
    base = f"http://127.0.0.1:{provider.server_port}"
    _, headers = provision_user("tata")
    portal_sessions.save_settings("tcl_promo", "moengage", {
        "TCL_PROMO_MOENGAGE_BASE_URL": base,
        "TCL_PROMO_MOENGAGE_WORKSPACE_ID": "0123456789abcdef01234567",
    })
    portal_sessions.save_session({"bearer_token": bearer, "refresh_token": refresh,
                                  "cookie": cookie, "base_url": base,
                                  "workspace_id": "0123456789abcdef01234567"}, "tcl_promo", "moengage")
    try:
        with TestClient(api.app) as client:
            response = client.post("/api/moengage/test?account=tcl_promo", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is (provider_status == 200)
        assert not ({"bearer_token", "refresh_token", "cookie"} & data.keys())
        assert all(secret not in response.text for secret in (bearer, refresh, cookie))
        if provider_status == 200:
            assert data["template_count"] == 1
        else:
            assert data["error"]
    finally:
        provider.shutdown()
        provider.server_close()
        thread.join()
