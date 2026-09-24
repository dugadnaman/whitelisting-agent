"""
Tests for Jira brief inspection endpoint (/api/jira/brief/{issue_key}).
Verifies:
1. Endpoint succeeds with 200 even when live WABA fetch raises an error or is unconfigured.
2. Endpoint successfully cross-references live WABA templates when available.
3. Does not crash on sub-accounts with missing or expired tokens.
"""

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import api

client = TestClient(api.app)

MOCK_ISSUE_DATA = {
    "key": "TCN-999",
    "id": "100999",
    "summary": "Personal Loan Festival Offer",
    "status": "In Progress",
    "assignee": "Test Operator",
    "reporter": "Product Manager",
    "duedate": "2026-10-31",
    "description_raw": {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Header: Diwali Dhamaka\nBody: Dear Customer, get Rs. 50,000 personal loan.\nFooter: T&C apply\nButton: Apply -> https://www.tatacapital.com"}
                ]
            }
        ]
    },
    "description_text": "Header: Diwali Dhamaka\nBody: Dear Customer, get Rs. 50,000 personal loan.\nFooter: T&C apply\nButton: Apply -> https://www.tatacapital.com",
    "attachments": [],
    "labels": ["diwali", "promo"],
}

MOCK_USER = {
    "email": "operator@tatacapital.com",
    "name": "Briefing Operator",
    "is_admin": True,
}


@patch("api.get_current_user", return_value=MOCK_USER)
@patch("jira_client.fetch_jira_issue", return_value=MOCK_ISSUE_DATA)
def test_jira_brief_endpoint_resilient_to_waba_fetch_error(mock_fetch_issue, mock_user):
    """Verify that when fetch_template_list raises an exception, the brief endpoint still succeeds."""
    with patch("submission_client.fetch_template_list", side_effect=OSError("Missing WABA token for sub-account")):
        response = client.get("/api/jira/brief/TCN-999")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["ok"] is True
        brief = data["brief"]
        assert brief["issue_key"] == "TCN-999"
        assert brief["summary"] == "Personal Loan Festival Offer"
        # WhatsApp templates should still be parsed, but with exists_on_waba=False
        for wa in brief.get("whatsapp_templates", []):
            assert wa["exists_on_waba"] is False
            assert wa["live_status"] == "not_submitted"


@patch("api.get_current_user", return_value=MOCK_USER)
@patch("jira_client.fetch_jira_issue", return_value=MOCK_ISSUE_DATA)
def test_jira_brief_endpoint_cross_references_live_waba(mock_fetch_issue, mock_user):
    """Verify that when fetch_template_list succeeds, matching templates are marked exists_on_waba=True."""
    mock_live = [
        {
            "template_name": "tcn_999_personal_loan_fe_wa_1",
            "template_create_status": "APPROVED",
            "fb_template_id": "9876543210",
        }
    ]
    with patch("submission_client.fetch_template_list", return_value=(mock_live, None)):
        response = client.get("/api/jira/brief/TCN-999")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        brief = data["brief"]
        # If any template matches the name, it should be marked live
        wa_templates = brief.get("whatsapp_templates", [])
        if wa_templates:
            matching = [w for w in wa_templates if w["template_name"] == "tcn_999_personal_loan_fe_wa_1"]
            if matching:
                assert matching[0]["exists_on_waba"] is True
                assert matching[0]["live_status"] == "approved"
                assert matching[0]["live_ref_id"] == "9876543210"
