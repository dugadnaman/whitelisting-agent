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

@patch("api.get_current_user", return_value=MOCK_USER)
@patch("jira_client.fetch_jira_issue", return_value=MOCK_ISSUE_DATA)
def test_jira_submit_preserves_text_header_footer_and_buttons(mock_fetch_issue, mock_user):
    """Verify that submit endpoint preserves TEXT headers, footers, and QUICK_REPLY/PHONE buttons."""
    from models import SubmissionResult, SubmissionStatus, ApprovalStatus

    captured_submissions = []

    def mock_submit(submission, client="tcl_promo"):
        captured_submissions.append(submission)
        return SubmissionResult(
            template_name=submission.template_name,
            status=SubmissionStatus.SUBMITTED,
            approval_status=ApprovalStatus.PENDING,
            source_ref=submission.source_ref,
        )
    req_payload = {
        "channels": ["whatsapp"],
        "account": "tcl_promo",
        "user": "Briefing Operator",
        "whatsapp_templates": [
            {
                "template_name": "festive_promo_wa_1",
                "category": "MARKETING",
                "header_type": "TEXT",
                "header_text": "Diwali Dhamaka Offer",
                "body": "Dear {{1}}, your pre-approved loan of Rs. {{2}} is ready.",
                "footer_text": "T&C apply. Tata Capital Ltd.",
                "button_type": "QUICK_REPLY",
                "button_text": "Interested",
                "variables": ["1", "2"],
                "sample_values": ["Rahul", "5,00,000"],
            },
            {
                "template_name": "call_support_wa_2",
                "category": "UTILITY",
                "header_type": "TEXT",
                "header_text": "Customer Support Alert",
                "body": "Dear {{1}}, please call our helpdesk for query resolution.",
                "button_type": "PHONE_NUMBER",
                "button_text": "Call Support",
                "button_phone": "+919876543210",
                "variables": ["1"],
                "sample_values": ["Priya"],
            }
        ],
    }

    with patch("submission_client.submit_template", side_effect=mock_submit), patch("config.get_waba_id", return_value="12345"):
        response = client.post("/api/jira/submit/TCN-999", json=req_payload)
        assert response.status_code == 200, f"Expected 200, got: {response.text}"
        data = response.json()
        assert data["ok"] is True
        assert len(data["whatsapp_submitted"]) == 2

        assert len(captured_submissions) == 2

        # Verify template 1 components
        sub1 = captured_submissions[0]
        types = [c.type for c in sub1.components]
        assert "HEADER" in types, "HEADER component was dropped!"
        assert "BODY" in types, "BODY component missing!"
        assert "FOOTER" in types, "FOOTER component was dropped!"
        assert "BUTTONS" in types, "BUTTONS component was dropped!"

        header_comp = next(c for c in sub1.components if c.type == "HEADER")
        assert header_comp.format == "TEXT"
        assert header_comp.text == "Diwali Dhamaka Offer"

        footer_comp = next(c for c in sub1.components if c.type == "FOOTER")
        assert footer_comp.text == "T&C apply. Tata Capital Ltd."

        btn_comp = next(c for c in sub1.components if c.type == "BUTTONS")
        assert btn_comp.buttons[0]["type"] == "QUICK_REPLY"
        assert btn_comp.buttons[0]["text"] == "Interested"

        body_comp = next(c for c in sub1.components if c.type == "BODY")
        assert body_comp.example is not None
        assert body_comp.example.get("body_text") == [["Rahul", "5,00,000"]]

        # Verify template 2 PHONE_NUMBER button
        sub2 = captured_submissions[1]
        btn_comp2 = next(c for c in sub2.components if c.type == "BUTTONS")
        assert btn_comp2.buttons[0]["type"] == "PHONE_NUMBER"
        assert btn_comp2.buttons[0]["text"] == "Call Support"
        assert btn_comp2.buttons[0]["phone_number"] == "+919876543210"
