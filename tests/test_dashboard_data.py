"""Dashboard must distinguish an empty WABA from an unavailable Karix inventory."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import api


@pytest.fixture
def client():
    api.app.dependency_overrides[api.get_current_user] = lambda: {
        "email": "operator@example.com",
        "tenant_id": "bajaj",
        "role": "operator",
    }
    try:
        yield TestClient(api.app)
    finally:
        api.app.dependency_overrides.clear()


@pytest.mark.parametrize("inventory_result", [([], "Karix HTTP 401"), RuntimeError("Karix unavailable")])
def test_dashboard_retains_tenant_local_history_when_inventory_unavailable(client, inventory_result):
    local_entries = [
        {"client": "bajaj", "template_name": "my_pending_template", "status": "submitted", "approval_status": "pending"},
        {"client": "tcl_promo", "template_name": "other_tenant_template", "status": "submitted", "approval_status": "approved"},
    ]
    inventory_patch = (
        patch("submission_client.fetch_template_list", side_effect=inventory_result)
        if isinstance(inventory_result, Exception)
        else patch("submission_client.fetch_template_list", return_value=inventory_result)
    )
    with (
        patch.object(api, "load_log", return_value=local_entries),
        patch.object(api, "get_pending_templates_sla_insights", return_value={"categories": {}}),
        inventory_patch,
    ):
        stats = client.get("/api/stats?account=bajaj&channel=whatsapp")
        templates = client.get("/api/templates?account=bajaj&channel=whatsapp")

    assert stats.status_code == 200
    assert stats.json()["total"] == 1
    assert stats.json()["pending"] == 1
    assert stats.json()["error"]
    assert templates.status_code == 200
    assert [row["template_name"] for row in templates.json()] == ["my_pending_template"]
    assert templates.json()[0]["live"] is False


def test_dashboard_empty_inventory_is_not_reported_as_outage(client):
    with (
        patch.object(api, "load_log", return_value=[]),
        patch.object(api, "get_pending_templates_sla_insights", return_value={"categories": {}}),
        patch("submission_client.fetch_template_list", return_value=([], None)),
    ):
        stats = client.get("/api/stats?account=bajaj&channel=whatsapp")
        templates = client.get("/api/templates?account=bajaj&channel=whatsapp")

    assert stats.json()["total"] == 0
    assert stats.json()["error"] is None
    assert templates.json() == []


def test_dashboard_reports_unavailable_local_history_instead_of_empty_list(client):
    with patch.object(api, "load_log", side_effect=OSError("database unavailable")):
        response = client.get("/api/templates?account=bajaj&channel=whatsapp")

    assert response.status_code == 503
    assert response.json()["detail"] == "Template history is temporarily unavailable."
