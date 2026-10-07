"""Jira brief and MoEngage handoffs must not cross tenants or expose local files."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

import api



@pytest.fixture
def client():
    return TestClient(api.app)


@pytest.mark.parametrize("tenant,expected", [(None, 401), ("bajaj", 403)])
def test_tata_jira_briefs_and_creatives_reject_other_tenants(client, provision_user, tenant, expected):
    if tenant is not None:
        _, headers = provision_user(tenant=tenant, role="operator")
        client.headers.update(headers)
    with (
        patch("jira_client.list_jira_issues") as list_issues,
        patch("jira_client.fetch_jira_issue") as fetch_issue,
        patch("jira_client.download_jira_attachment") as download,
    ):
        responses = [
            client.get("/api/jira/projects"),
            client.get("/api/jira/issues"),
            client.get("/api/jira/brief/TCN-999"),
            client.post("/api/jira/submit/TCN-999", json={"channels": []}),
            client.get("/api/jira/creative/download", params={"attachment_id": "123"}),
            client.post("/api/jira/creative/upload", files={"file": ("test.png", b"image")}),
        ]
    assert [response.status_code for response in responses] == [expected] * len(responses)
    list_issues.assert_not_called()
    fetch_issue.assert_not_called()
    download.assert_not_called()


def test_tata_creative_download_cannot_read_other_temp_files(client, provision_user):
    _, headers = provision_user(tenant="tata", role="operator")
    client.headers.update(headers)
    with tempfile.NamedTemporaryFile(mode="w", prefix="jira-creative-probe-", delete=False) as handle:
        handle.write("private local content")
        path = Path(handle.name)
    try:
        response = client.get("/api/jira/creative/download", params={"path": str(path)})
        assert response.status_code == 404
        assert "private local content" not in response.text
    finally:
        path.unlink()


def test_tata_jira_brief_cannot_submit_to_bajaj(client, provision_user):
    _, headers = provision_user(tenant="tata", role="operator")
    client.headers.update(headers)
    with (
        patch("jira_client.fetch_jira_issue", return_value={"key": "TCN-999"}),
        patch("briefing_parser.parse_jira_brief", return_value=SimpleNamespace(account="tcl_promo")),
        patch("submission_client.submit_template") as submit,
    ):
        response = client.post("/api/jira/submit/TCN-999", json={"account": "bajaj", "channels": ["whatsapp"]})
    assert response.status_code == 403
    submit.assert_not_called()


def test_bajaj_cannot_read_or_update_tata_moengage_credentials_or_sync_rcs(client, provision_user):
    _, headers = provision_user(tenant="bajaj", role="operator")
    client.headers.update(headers)
    with (
        patch("moengage_sync.get_moengage_credentials") as credentials,
        patch("moengage_sync.test_moengage_connection") as connection,
        patch("moengage_sync.create_moengage_rcs_template") as create,
    ):
        responses = [
            client.get("/api/moengage/credentials?account=tata"),
            client.put("/api/moengage/credentials", json={"account": "tata", "bearer_token": "not-a-real-token"}),
            client.post("/api/moengage/test?account=tata"),
            client.post("/api/moengage/rcs/sync", json={
                "template_name": "test", "template_id": "test", "card_title": "test", "card_description": "test",
            }),
        ]
    assert [response.status_code for response in responses] == [403] * len(responses)
    credentials.assert_not_called()
    connection.assert_not_called()
    create.assert_not_called()


def test_tata_can_still_access_own_moengage_credentials(client, provision_user):
    _, headers = provision_user(tenant="tata", role="admin")
    client.headers.update(headers)
    with patch("moengage_sync.get_moengage_credentials", return_value={"has_token": True}) as credentials:
        response = client.get("/api/moengage/credentials?account=tata")
    assert response.status_code == 200
    assert response.json()["has_token"] is True
    credentials.assert_called_once_with("tata")

def test_tata_operator_cannot_read_own_moengage_credentials(client, provision_user):
    _, headers = provision_user(tenant="tata", role="operator")
    client.headers.update(headers)
    with patch("moengage_sync.get_moengage_credentials") as credentials:
        response = client.get("/api/moengage/credentials?account=tata")
    assert response.status_code == 403
    credentials.assert_not_called()


def test_apparel_can_sync_rcs_to_apparel_moengage(client, provision_user):
    _, headers = provision_user(tenant="apparel", role="operator")
    client.headers.update(headers)
    with patch("moengage_sync.create_moengage_rcs_template", return_value={"ok": True, "moengage_id": "moe_apparel_123"}) as create:
        response = client.post(
            "/api/moengage/rcs/sync",
            json={
                "account": "apparel",
                "template_name": "festive_sale",
                "template_id": "festive_sale_01",
                "card_title": "Festive Offer",
                "card_description": "Shop 50% off",
            },
        )
    assert response.status_code == 200
    assert response.json()["moengage_id"] == "moe_apparel_123"
    create.assert_called_once_with(
        template_name="festive_sale",
        template_id="festive_sale",
        card_title="Festive Offer",
        card_description="Shop 50% off",
        media_url=None,
        cta_text="Visit Store",
        cta_url=None,
        sender_id=None,
        account="apparel",
    )


def test_apparel_cannot_sync_rcs_to_tata_moengage(client, provision_user):
    _, headers = provision_user(tenant="apparel", role="operator")
    client.headers.update(headers)
    with patch("moengage_sync.create_moengage_rcs_template") as create:
        response = client.post(
            "/api/moengage/rcs/sync",
            json={
                "account": "tata",
                "template_name": "festive_sale",
                "template_id": "festive_sale_01",
                "card_title": "Festive Offer",
                "card_description": "Shop 50% off",
            },
        )
    assert response.status_code == 403
    create.assert_not_called()
