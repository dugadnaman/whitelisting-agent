"""
Unit and endpoint tests for MoEngage MCP Client & OAuth 2.0 Connector (backend/moengage_mcp.py).
"""

import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api import app, get_current_user
from moengage_mcp import (
    call_mcp_tool,
    complete_mcp_oauth,
    get_mcp_status,
    save_mcp_tokens,
    start_mcp_oauth,
    test_mcp_connection as check_mcp_connection,
)
from moengage_ops_client import fetch_mcp_ops_records

MOCK_USER = {
    "id": 1,
    "email": "operator@attributics.com",
    "name": "Briefing Operator",
    "role": "superadmin",
    "tenant_id": "ALL",
}


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
        patch("moengage_mcp.update_env_vars"),
    ):
        done = complete_mcp_oauth(code="auth_code_999", state=res["state"])
        assert done["ok"] is True
        assert done["has_token"] is True
        assert done["has_refresh_token"] is True
        assert done["return_to"] == "/settings"


def test_mcp_rpc_initialize_list_tools_and_call_tool_sse():
    """Verify MCP JSON-RPC client handles initialize, tools/list, and tools/call over SSE."""
    with (
        patch.dict("os.environ", {}, clear=False),
        patch("moengage_mcp.update_env_vars"),
    ):
        save_mcp_tokens(account="tata", access_token="valid_mcp_token")

    def fake_post(url, headers=None, json=None, timeout=25):
        method = (json or {}).get("method")
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.headers = {"Content-Type": "text/event-stream", "Mcp-Session-Id": "sess_moe_1"}

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
        assert conn["ok"] is True
        assert conn["tool_count"] == 4
        assert "search_campaigns" in conn["tools"]

        call_res = call_mcp_tool("search_campaigns", {"limit": 10}, account="tata")
        assert call_res["ok"] is True
        assert isinstance(call_res["data"], list)
        assert call_res["data"][0]["campaign_name"] == "TCL_PAPL_Diwali_WA"

        ops_records = fetch_mcp_ops_records("tata")
        assert len(ops_records) == 2
        assert ops_records[0].name == "TCL_PAPL_Diwali_WA"
        assert ops_records[0].channel == "WhatsApp"
        assert ops_records[1].type == "Flow"


def test_mcp_api_endpoints():
    """Verify FastAPI /api/moengage/mcp/* endpoints."""
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    client = TestClient(app)
    try:
        r = client.get("/api/moengage/mcp/status?account=tata")
        assert r.status_code == 200
        body = r.json()
        assert body["mcp_url"] == "https://mcp.moengage.com"
        assert body["mcp_config_json"]["mcpServers"]["moengage"]["url"] == "https://mcp.moengage.com"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
