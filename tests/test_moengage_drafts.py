"""Offline security behavior for the MoEngage V5 draft-only seam."""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api import app
from moengage_drafts import DraftWriter

ACCOUNT = "tata"
USER = {"sub": "operator-1", "tenant_id": ACCOUNT, "role": "operator"}
KEY = "123e4567-e89b-42d3-a456-426614174000"
ID = "a" * 24


class FakeTransport:
    def __init__(self, *statuses):
        self.statuses = iter(statuses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        status = next(self.statuses)

        class Response:
            status_code = 200

            def json(self):
                return {"data": {"status": status, "id": ID}}

        return Response()


def draft_env():
    return {
        "MOENGAGE_DRAFT_TATA_LIVE_ENABLED": "true",
        "MOENGAGE_DRAFT_TATA_WORKSPACE_ID": "workspace-tata",
        "MOENGAGE_DRAFT_TATA_API_KEY": "test-tata-key",
        "MOENGAGE_DRAFT_TATA_DATA_CENTER": "03",
        "MOENGAGE_DRAFT_BAJAJ_LIVE_ENABLED": "true",
        "MOENGAGE_DRAFT_BAJAJ_WORKSPACE_ID": "workspace-bajaj",
        "MOENGAGE_DRAFT_BAJAJ_API_KEY": "test-bajaj-key",
        "MOENGAGE_DRAFT_BAJAJ_DATA_CENTER": "01",
        "MOENGAGE_MCP_ACCESS_TOKEN": "legacy-token-must-never-be-used",
    }


def test_draft_gate_and_tenant_binding_prevent_any_network():
    transport = FakeTransport()
    with patch.dict(os.environ, draft_env(), clear=True):
        with pytest.raises(PermissionError):
            DraftWriter("bajaj", USER, transport=transport)
        with pytest.raises(PermissionError):
            DraftWriter("tata", {"sub": "usr_anon", "tenant_id": "tata"}, transport=transport)
        with pytest.raises(PermissionError):
            DraftWriter("tata", {"sub": "operator-1", "tenant_id": "all"}, transport=transport)
        with pytest.raises(ValueError):
            DraftWriter("tata!", USER, transport=transport)
        os.environ.pop("MOENGAGE_DRAFT_TATA_LIVE_ENABLED")
        with pytest.raises(PermissionError):
            DraftWriter("tata", USER, transport=transport)
    assert transport.calls == []


def test_writer_never_falls_back_to_shared_or_other_account_key():
    transport = FakeTransport("DRAFT")
    with patch.dict(os.environ, draft_env(), clear=True):
        os.environ.pop("MOENGAGE_DRAFT_TATA_API_KEY")
        with pytest.raises(ValueError):
            DraftWriter("tata", USER, transport=transport)
        os.environ["MOENGAGE_DRAFT_TATA_API_KEY"] = "test-tata-key"
        writer = DraftWriter("tata", USER, transport=transport)
        assert writer.get(ID)["status"] == "DRAFT"
    assert transport.calls[0][:2] == (
        "GET", f"https://api-03.moengage.com/v5/campaigns/{ID}"
    )
    assert transport.calls[0][2]["auth"] == ("workspace-tata", "test-tata-key")
    assert transport.calls[0][2]["allow_redirects"] is False


def test_draft_only_operations_and_status_guard():
    transport = FakeTransport("DRAFT", "DRAFT", "DRAFT", "DRAFT")
    with patch.dict(os.environ, draft_env(), clear=True):
        writer = DraftWriter("tata", USER, transport=transport)
        for payload in (
            {"channel": "SMS", "campaign_delivery_type": "ONE_TIME", "created_by": "user@example.com"},
            {"channel": "EMAIL", "campaign_delivery_type": "EVENT_TRIGGERED", "created_by": "user@example.com"},
            {"channel": "EMAIL", "campaign_delivery_type": "ONE_TIME", "created_by": "user@example.com", "status": "ACTIVE"},
        ):
            with pytest.raises(ValueError):
                writer.create(payload, idempotency_key=KEY)
        with pytest.raises(ValueError):
            writer.get("../core-services/v1/campaigns")
        assert transport.calls == []

        created = writer.create(
            {"channel": "EMAIL", "campaign_delivery_type": "ONE_TIME", "created_by": "user@example.com"},
            idempotency_key=KEY,
        )
        assert created["status"] == "DRAFT"
        assert not hasattr(writer, "patch")
        assert writer.get(ID)["status"] == "DRAFT"
        writer.validate(ID)
    assert [call[0] for call in transport.calls] == ["POST", "GET", "GET", "POST"]
    assert transport.calls[-1][1].endswith(f"/{ID}/validate")
    assert all("/v5/campaigns" in call[1] for call in transport.calls)
    assert transport.calls[0][2]["headers"]["Idempotency-Key"] == KEY


@pytest.mark.parametrize("status", ["ACTIVE", "SCHEDULED", None])
def test_validate_rejects_non_draft_and_missing_status(status):
    transport = FakeTransport(status)
    with patch.dict(os.environ, draft_env(), clear=True):
        writer = DraftWriter("tata", USER, transport=transport)
        with pytest.raises(PermissionError):
            writer.validate(ID)
    assert [call[0] for call in transport.calls] == ["GET"]


def test_mcp_generic_route_rejects_writes_before_mcp_transport(provision_user):
    _, headers = provision_user(tenant="tata")
    client = TestClient(app)
    with patch("moengage_mcp.call_mcp_tool") as call:
        for tool in ("create_campaign_draft", "patch_campaign_components", "send_test_campaign", "publish_campaign", "trigger_flow_event"):
            response = client.post("/api/moengage/mcp/call", headers=headers, json={"account": "tata", "tool_name": tool})
            assert response.status_code == 403
        denied = client.post("/api/moengage/mcp/call", headers=headers, json={"account": "bajaj", "tool_name": "search_campaigns"})
        assert denied.status_code == 403
        call.assert_not_called()
        allowed = client.post("/api/moengage/mcp/call", headers=headers, json={"account": "tata", "tool_name": "search_campaigns"})
        assert allowed.status_code == 200
        call.assert_called_once()

        denied = client.post("/api/moengage/mcp/call", json={"account": "tata", "tool_name": "search_campaigns"})
        assert denied.status_code == 401
        call.assert_called_once()
