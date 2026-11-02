"""Unit tests for MoEngage RCS workspace selection endpoints."""

from unittest.mock import patch
from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def test_apparel_workspaces_endpoint_requires_auth():
    res = client.get("/api/moengage/rcs/workspaces?account=apparel")
    assert res.status_code == 401


def test_apparel_workspaces_endpoint_success(provision_user):
    user, headers = provision_user(tenant="apparel")
    client.headers.update(headers)

    mock_workspaces = [
        {"id": "a" * 24, "name": "AL_IN"},
        {"id": "b" * 24, "name": "CROCS_IN"},
    ]
    with patch("moengage_sync.list_moengage_rcs_workspaces", return_value=mock_workspaces):
        res = client.get("/api/moengage/rcs/workspaces?account=apparel")
        assert res.status_code == 200
        data = res.json()
        assert data["workspaces"] == mock_workspaces


def test_apparel_sync_requires_workspace_id(provision_user):
    user, headers = provision_user(tenant="apparel")
    client.headers.update(headers)

    res = client.post(
        "/api/moengage/rcs/sync",
        json={
            "template_name": "test_tmpl",
            "card_title": "Title",
            "card_description": "Desc",
            "account": "apparel",
        },
    )
    assert res.status_code == 400
    assert "Select a destination MoEngage workspace" in res.json()["detail"]


def test_apparel_sync_karix_requires_workspace_id(provision_user):
    user, headers = provision_user(tenant="apparel")
    client.headers.update(headers)

    res = client.post("/api/moengage/rcs/sync-karix?account=apparel")
    assert res.status_code == 400
    assert "Select a destination MoEngage workspace" in res.json()["detail"]


def test_non_apparel_sync_rejects_workspace_id(provision_user):
    user, headers = provision_user(tenant="tata")
    client.headers.update(headers)

    res = client.post(
        "/api/moengage/rcs/sync",
        json={
            "template_name": "test_tmpl",
            "card_title": "Title",
            "card_description": "Desc",
            "account": "tata",
            "workspace_id": "a" * 24,
        },
    )
    assert res.status_code == 400
    assert "Apparel RCS sync only" in res.json()["detail"]


def test_apparel_sync_routes_to_specified_workspace(provision_user):
    user, headers = provision_user(tenant="apparel")
    client.headers.update(headers)

    mock_result = {
        "ok": True,
        "name": "test_tmpl",
        "template_id": "test_tmpl",
        "moengage_id": "moe_123",
        "workspace_id": "b" * 24,
    }
    with patch("moengage_sync.create_moengage_rcs_template", return_value=mock_result) as mock_create:
        res = client.post(
            "/api/moengage/rcs/sync",
            json={
                "template_name": "test_tmpl",
                "card_title": "Title",
                "card_description": "Desc",
                "account": "apparel",
                "workspace_id": "b" * 24,
            },
        )
        assert res.status_code == 200
        assert res.json()["moengage_id"] == "moe_123"
        assert mock_create.call_args.kwargs["workspace_id"] == "b" * 24
