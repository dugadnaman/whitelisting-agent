"""
Unit and endpoint tests for MoEngage MCP Client & OAuth 2.0 Connector (backend/moengage_mcp.py).
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from fastapi.testclient import TestClient

from api import app
from moengage_mcp import (
    call_mcp_tool,
    complete_mcp_oauth,
    get_mcp_status,
    save_mcp_tokens,
    start_mcp_oauth,
    test_mcp_connection as check_mcp_connection,
)
from moengage_ops_client import fetch_mcp_ops_records

@pytest.fixture(autouse=True)
def isolated_mcp_credentials(monkeypatch):
    """MCP unit tests must neither load nor persist developer OAuth credentials."""
    import moengage_mcp

    for key in tuple(__import__("os").environ):
        if "MOENGAGE" in key:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(moengage_mcp, "_load_env_file", lambda: None)
    monkeypatch.setattr(moengage_mcp, "_MCP_SESSIONS", {})

def test_mcp_status_and_config_json():
    """Verify get_mcp_status returns standard mcpServers.moengage JSON configuration."""
    status = get_mcp_status("tata")
    assert status["mcp_url"] == "https://mcp.moengage.com"
    assert status["mcp_config_json"] == {
        "mcpServers": {
            "moengage": {
                "url": "https://mcp.moengage.com",
            }
        }
    }


def test_mcp_oauth_dynamic_registration_and_pkce_flow():
    """Verify start_mcp_oauth registers a client and complete_mcp_oauth exchanges the PKCE code."""
    mock_reg_resp = MagicMock()
    mock_reg_resp.ok = True
    mock_reg_resp.status_code = 201
    mock_reg_resp.json.return_value = {
        "client_id": "dyn_test_client_123",
        "client_name": "Karix Whitelisting Agent (MoEngage MCP)",
    }

    with patch("moengage_mcp.requests.post", return_value=mock_reg_resp) as mock_post:
        res = start_mcp_oauth(
            redirect_uri="https://whitelisting-agent.onrender.com/api/moengage/mcp/oauth/callback",
            account="tata",
            return_to="/settings",
        )
        assert res["ok"] is True
        assert res["client_id"] == "dyn_test_client_123"
        assert "https://moeauth.moengage.com/oauth2/authorize?" in res["authorize_url"]
        assert "code_challenge_method=S256" in res["authorize_url"]
        assert "resource=https%3A%2F%2Fmcp.moengage.com" in res["authorize_url"]
        mock_post.assert_called_once()

    mock_tok_resp = MagicMock()
    mock_tok_resp.ok = True
    mock_tok_resp.status_code = 200
    mock_tok_resp.json.return_value = {
        "access_token": "mcp_oauth_access_token_xyz",
        "refresh_token": "mcp_oauth_refresh_token_abc",
        "expires_in": 2592000,
    }

    with (
        patch.dict("os.environ", {}, clear=False),
        patch("moengage_mcp.requests.post", return_value=mock_tok_resp),
    ):
        done = complete_mcp_oauth(code="auth_code_999", state=res["state"])
        assert done["ok"] is True
        assert done["has_token"] is True
        assert done["has_refresh_token"] is True
        assert done["return_to"] == "/settings"


def test_mcp_rpc_initialize_list_tools_and_call_tool_sse(monkeypatch):
    """Verify MCP JSON-RPC client handles initialize, tools/list, and tools/call over SSE."""
    # Keep the prerequisite token alive throughout the RPC calls, not a shorter patch.dict scope.
    monkeypatch.setenv("TATA_MOENGAGE_MCP_ACCESS_TOKEN", "valid_mcp_token")
    monkeypatch.setenv("MOENGAGE_MCP_ACCESS_TOKEN", "valid_mcp_token")

    def fake_post(url, headers=None, json=None, timeout=25, **kwargs):
        method = (json or {}).get("method")
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.headers = {"Content-Type": "text/event-stream", "Mcp-Session-Id": "sess_moe_1"}
        if "oauth2/token" in str(url):
            resp.json.return_value = {"access_token": "valid_mcp_token_refreshed", "expires_in": 86400}
            resp.text = '{"access_token": "valid_mcp_token_refreshed"}'
            return resp

        if method == "initialize":
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "serverInfo": {"name": "moengage-mcp-server", "version": "1.0.0"},
                },
            }
            resp.text = f"event: message\ndata: {__import__('json').dumps(payload)}\n\n"
        elif method == "notifications/initialized":
            resp.text = ""
        elif method == "tools/list":
            payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "tools": [
                        {"name": "search_campaigns", "description": "Search campaigns"},
                        {"name": "search_flows", "description": "Search flows"},
                        {"name": "list_segments", "description": "Browse segments"},
                        {"name": "create_campaign_draft", "description": "Create draft"},
                    ]
                },
            }
            resp.text = f"event: message\ndata: {__import__('json').dumps(payload)}\n\n"
        elif method == "tools/call":
            tname = (json or {}).get("params", {}).get("name")
            if tname == "search_campaigns":
                inner = [
                    {
                        "campaign_name": "TCL_PAPL_Diwali_WA",
                        "channel": "WHATSAPP",
                        "created_by": "ops@attributics.com",
                        "campaign_status": "ACTIVE",
                        "created_at": "2026-09-29T10:00:00Z",
                    }
                ]
            else:
                inner = [{"name": "Welcome_Journey_Flow", "status": "Active", "created_by": "ops@attributics.com"}]
            payload = {
                "jsonrpc": "2.0",
                "id": 3,
                "result": {
                    "content": [{"type": "text", "text": __import__("json").dumps(inner)}],
                    "isError": False,
                },
            }
            resp.text = f"event: message\ndata: {__import__('json').dumps(payload)}\n\n"
        return resp

    with patch("moengage_mcp.requests.post", side_effect=fake_post):
        conn = check_mcp_connection("tata")
        assert conn["ok"] is True, conn
        assert conn["tool_count"] == 4
        assert "search_campaigns" in conn["tools"]

        call_res = call_mcp_tool("search_campaigns", {"limit": 10}, account="tata")
        assert call_res["ok"] is True, call_res
        assert isinstance(call_res["data"], list)
        assert call_res["data"][0]["campaign_name"] == "TCL_PAPL_Diwali_WA"

        ops_records = fetch_mcp_ops_records("tata")
        assert len(ops_records) == 2
        assert ops_records[0].name == "TCL_PAPL_Diwali_WA"
        assert ops_records[0].channel == "WhatsApp"
        assert ops_records[1].type == "Flow"


def test_mcp_api_endpoints(provision_user):
    """Verify FastAPI /api/moengage/mcp/* endpoints."""
    _, headers = provision_user(tenant="tata")
    client = TestClient(app, headers=headers)
    r = client.get("/api/moengage/mcp/status?account=tata")
    assert r.status_code == 200
    body = r.json()
    assert body["mcp_url"] == "https://mcp.moengage.com"
    assert body["mcp_config_json"]["mcpServers"]["moengage"]["url"] == "https://mcp.moengage.com"


def test_mcp_credentials_survive_reload_without_cross_account_or_portal_writes(tmp_path, monkeypatch):
    import base64
    import importlib
    import os
    import moengage_mcp
    from db import get_db
    from portal_sessions import load_session, save_session

    monkeypatch.chdir(tmp_path)
    portal = {"bearer_token": "original-portal", "refresh_token": "original-refresh", "cookie": "portal=original"}
    save_session(portal, "tcl_promo", "moengage")
    payload = base64.urlsafe_b64encode(json.dumps({"moe_bearer": "mcp-only-bearer"}).encode()).decode().rstrip("=")
    access = f"header.{payload}.signature"
    save_mcp_tokens("apparel", access_token=access, refresh_token="apparel-refresh", client_id="apparel-client")
    save_mcp_tokens("tcl_promo", access_token="promo-access", refresh_token="promo-refresh")
    monkeypatch.setenv("MOENGAGE_MCP_ACCESS_TOKEN", "unscoped-foreign-token")
    reloaded = importlib.reload(moengage_mcp)
    monkeypatch.setattr(reloaded, "_load_env_file", lambda: None)

    assert reloaded.get_mcp_config("apparel")["access_token"] == access
    assert reloaded.get_mcp_config("tcl_promo")["refresh_token"] == "promo-refresh"
    assert reloaded.get_mcp_config("bajaj")["access_token"] == ""
    assert reloaded.get_mcp_config("tata")["access_token"] == ""
    assert load_session("tcl_promo", "moengage") == portal
    assert not any(key.endswith("_MOENGAGE_BEARER_TOKEN") for key in os.environ)
    assert not (tmp_path / "credentials.json").exists()
    with get_db() as conn:
        ciphertext = " ".join(row["encrypted_credentials"] for row in conn.execute("SELECT encrypted_credentials FROM karix_scoped_credentials").fetchall())
        assert access not in ciphertext and "apparel-refresh" not in ciphertext and "promo-refresh" not in ciphertext


def test_mcp_refresh_rotates_numeric_expiry_credentials_only_for_requested_account(monkeypatch):
    import moengage_mcp

    save_mcp_tokens("apparel", access_token="old-access", refresh_token="old-refresh", client_id="apparel-client")
    save_mcp_tokens("tcl_promo", access_token="untouched-access", refresh_token="untouched-refresh")
    response = MagicMock(ok=True)
    response.json.return_value = {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600}
    with patch("moengage_mcp.requests.post", return_value=response):
        assert moengage_mcp.refresh_mcp_access_token("apparel") == "new-access"
    config = moengage_mcp.get_mcp_config("apparel")
    assert config["access_token"] == "new-access" and config["refresh_token"] == "new-refresh"
    assert config["expires_at"] > __import__("time").time()
    assert moengage_mcp.get_mcp_config("tcl_promo")["access_token"] == "untouched-access"


def test_oauth_state_is_encrypted_one_use_and_survives_module_reload(monkeypatch):
    import importlib
    import moengage_mcp

    # An existing other-account token must survive this Apparel OAuth exchange.
    save_mcp_tokens("tata", access_token="unrelated-tata-access")
    registration = MagicMock(ok=True)
    registration.json.return_value = {"client_id": "fixture-client"}
    with patch("moengage_mcp.requests.post", return_value=registration):
        pending = moengage_mcp.start_mcp_oauth("https://portal.example.invalid/callback", account="apparel")
    reloaded = importlib.reload(moengage_mcp)
    monkeypatch.setattr(reloaded, "_load_env_file", lambda: None)
    response = MagicMock(ok=True)
    response.json.return_value = {"access_token": "oauth-access", "refresh_token": "oauth-refresh", "expires_in": 3600}
    with patch("moengage_mcp.requests.post", return_value=response) as exchange:
        completed = reloaded.complete_mcp_oauth("fixture-code", pending["state"])
        assert completed["account"] == "apparel" and completed["has_token"]
        with pytest.raises(RuntimeError, match="Invalid or expired"):
            reloaded.complete_mcp_oauth("fixture-code", pending["state"])
        assert exchange.call_count == 1
    assert reloaded.get_mcp_config("tata")["access_token"] == "unrelated-tata-access"


def test_expired_mcp_oauth_state_never_exchanges_the_code(monkeypatch):
    import moengage_mcp
    from db import get_db

    registration = MagicMock(ok=True)
    registration.json.return_value = {"client_id": "fixture-client"}
    with patch("moengage_mcp.requests.post", return_value=registration):
        pending = moengage_mcp.start_mcp_oauth("https://portal.example.invalid/callback", account="apparel")
    with get_db() as conn:
        row = conn.execute("SELECT encrypted_credentials FROM karix_scoped_credentials WHERE kind LIKE 'mcp-oauth-%'").fetchone()
        assert pending["state"] not in row["encrypted_credentials"]
        conn.execute("UPDATE karix_scoped_credentials SET updated_at = updated_at - 601 WHERE kind LIKE 'mcp-oauth-%'")
    with patch("moengage_mcp.requests.post") as exchange:
        with pytest.raises(RuntimeError, match="Invalid or expired"):
            moengage_mcp.complete_mcp_oauth("fixture-code", pending["state"])
        exchange.assert_not_called()


def test_manual_mcp_token_replacement_discards_previous_expiry():
    import time
    import jwt

    save_mcp_tokens("tcl_promo", access_token="old-token", expires_in=-60)
    assert get_mcp_status("tcl_promo")["expired"]
    token = jwt.encode({"exp": int(time.time()) + 3600}, "synthetic-mcp-signing-key-at-least-32-bytes", algorithm="HS256")
    replacement = save_mcp_tokens("tcl_promo", access_token=token)
    assert not replacement["expired"]
    assert replacement["remaining_min"] > 50
