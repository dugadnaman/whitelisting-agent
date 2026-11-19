"""Jira review submissions exercise the real serializer and loopback HTTP transport."""

from copy import deepcopy
import json

from fastapi.testclient import TestClient
import pytest

import api
import db
import jira_client
from tests.test_whatsapp_media_transport import (  # noqa: F401 — shared pytest fixtures
    create_calls, isolated, multipart, portal_credentials, provider,
)


URL = "https://campaign.example.org/offers/{{1}}"
URL_SAMPLE = "https://campaign.example.org/offers/customer-offer"
PHONE = "+912234567890"
BODY = "Your requested offer is ready. Review the details when convenient."


def reviewed_drafts(schema):
    buttons = [
        {"type": "URL", "label": "View details", "url": URL, "example": [URL_SAMPLE]},
        {"type": "QUICK_REPLY", "label": "Later"},
        {"type": "PHONE_NUMBER", "label": "Call support", "phone_number": PHONE},
    ]
    expected = [{key: value for key, value in button.items() if key != "label"}
                | {"text": button["label"]} for button in buttons]
    for button in buttons:
        button.update(ui_selected=True, source_cell="Another sheet!C19", validation_note="review only")
    base = {"template_name": "reviewed_offer", "category": "MARKETING", "language": "en",
            "header_type": "NONE", "body": BODY}
    if schema == "label_and_text":
        for button, outgoing in zip(buttons, expected):
            button["text"] = outgoing["text"] = "Reviewed " + button["label"]
            button["label"] = "Obsolete copy"
    if schema == "flat_fields":
        drafts = []
        for index, button in enumerate(expected):
            drafts.append({**base, "template_name": f"reviewed_offer_{index}",
                           "button_type": button["type"], "button_text": button["text"],
                           "button_url": URL, "button_phone": PHONE})
        # Flat URL fields have no sample field; the shared CTA policy generates one.
        expected[0]["example"] = [URL.replace("{{1}}", "sample")]
        return drafts, [[button] for button in expected]
    return [{**base, "buttons": buttons}], [expected]


@pytest.fixture
def jira_http(monkeypatch):
    requested = []

    def fetch_issue(issue_key):
        requested.append(issue_key)
        # Keep the real briefing parser: only the external Jira HTTP fetch is replaced.
        return {"key": issue_key, "summary": "Reviewed campaign copy", "description_text": "",
                "attachments": [], "comments": []}

    monkeypatch.setattr(jira_client, "fetch_jira_issue", fetch_issue)
    return requested


@pytest.mark.parametrize("issue_key,account", [("ORBIT-407", "tcl_promo"), ("NOVAOPS-1836", "tchfl")])
@pytest.mark.parametrize("schema", ["label_only", "label_and_text", "flat_fields"])
@pytest.mark.parametrize("portal", [False, True])
def test_jira_review_reaches_selected_provider_unchanged(
    provider, provision_user, jira_http, monkeypatch, issue_key, account, schema, portal,
):
    if portal:
        portal_credentials(monkeypatch, account.upper())
    _, headers = provision_user(tenant="tata")
    drafts, expected_buttons = reviewed_drafts(schema)
    original = deepcopy(drafts)
    response = TestClient(api.app).post(f"/api/jira/submit/{issue_key}", headers=headers, json={
        "account": account, "channels": ["whatsapp"], "whatsapp_templates": drafts,
        "rcs_templates": [],
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["issue_key"] == issue_key
    assert result["account"] == account
    assert result["jira_comment"]["skipped"] is True
    assert [row["status"] for row in result["whatsapp_submitted"]] == ["submitted"] * len(drafts)
    assert jira_http == [issue_key]
    calls = create_calls(provider)
    assert len(calls) == len(drafts)
    expected_path = "/portal/create" if portal else f"/official/local-{account.upper()}-waba"
    assert [call[1] for call in calls] == [expected_path] * len(drafts)
    for call, expected in zip(calls, expected_buttons):
        outgoing = (json.loads(multipart(call)["request"].get_payload(decode=True))
                    if portal else json.loads(call[2]))
        if portal:
            assert outgoing["waba_id"] == f"local-{account.upper()}-waba"
        else:
            assert "waba_id" not in outgoing  # Official transport scopes WABA in the URL.
        assert next(component for component in outgoing["components"] if component["type"] == "BODY")["text"] == BODY
        assert next(component for component in outgoing["components"] if component["type"] == "BUTTONS")["buttons"] == expected
    with db.get_db() as connection:
        rows = connection.execute("SELECT * FROM job_tasks ORDER BY template_name").fetchall()
    assert len(rows) == len(drafts)
    for row in rows:
        saved = json.loads(row["payload_json"])
        assert row["tenant_id"] == saved["client"] == account
        assert row["channel"] == "whatsapp"
        assert row["source_ref"] == f"{issue_key}_{row['template_name']}"
        assert saved["source_file"] == f"Jira: {issue_key}"
        assert row["provider_ref_id"]
    assert drafts == original


@pytest.mark.parametrize("portal", [False, True])
def test_unknown_jira_button_type_is_blocked_before_provider_side_effects(provider, provision_user, jira_http, monkeypatch, portal):
    if portal:
        portal_credentials(monkeypatch)
    _, headers = provision_user(tenant="tata")
    drafts, _ = reviewed_drafts("label_only")
    drafts[0]["buttons"][0]["type"] = "UNSUPPORTED_ACTION"
    response = TestClient(api.app).post("/api/jira/submit/ANOTHER-291", headers=headers, json={
        "account": "tcl_promo", "channels": ["whatsapp"], "whatsapp_templates": drafts,
        "rcs_templates": [],
    })
    assert response.status_code == 200, response.text
    result = response.json()["whatsapp_submitted"][0]
    assert result["status"] == "failed"
    assert "Unsupported WhatsApp button type" in result["error"]
    assert create_calls(provider) == []


@pytest.mark.parametrize("portal", [False, True])
def test_jira_provider_rejection_is_recorded_without_replay(
    provider, provision_user, jira_http, monkeypatch, portal,
):
    if portal:
        portal_credentials(monkeypatch)
    path = "/portal/create" if portal else "/official/local-TCL_PROMO-waba"
    provider.routes[path] = (400, {"error": "Invalid button text"})
    _, headers = provision_user(tenant="tata")
    drafts, _ = reviewed_drafts("label_only")
    response = TestClient(api.app).post("/api/jira/submit/REVIEW-928", headers=headers, json={
        "account": "tcl_promo", "channels": ["whatsapp"], "whatsapp_templates": drafts,
    })
    assert response.status_code == 200, response.text
    result = response.json()["whatsapp_submitted"][0]
    assert result["status"] == "failed"
    assert result["error"]
    assert len(create_calls(provider)) == 1
    with db.get_db() as connection:
        row = connection.execute("SELECT * FROM job_tasks").fetchone()
    assert row["status"] == "FAILED"
    assert not row["provider_ref_id"]
    assert row["source_ref"].startswith("REVIEW-928_")
    assert json.loads(row["payload_json"])["source_file"] == "Jira: REVIEW-928"


@pytest.mark.parametrize("tenant,target", [("apparel", "tcl_promo"), ("bajaj", "tchfl"),
                                            ("tchfl", "tcl_promo"), ("tata", "bajaj")])
def test_jira_review_cannot_cross_tenant_boundary(provider, provision_user, jira_http, tenant, target):
    _, headers = provision_user(tenant=tenant)
    drafts, _ = reviewed_drafts("label_and_text")
    response = TestClient(api.app).post("/api/jira/submit/BOUNDARY-62", headers=headers, json={
        "account": target, "channels": ["whatsapp"], "whatsapp_templates": drafts,
    })
    assert response.status_code == 403, response.text
    assert not provider.calls
    with db.get_db() as connection:
        assert connection.execute("SELECT COUNT(*) FROM job_tasks").fetchone()[0] == 0
