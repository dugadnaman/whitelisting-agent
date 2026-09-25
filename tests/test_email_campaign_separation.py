"""
Unit tests for Email campaign separation from WhatsApp, RCS, and SMS.
Verifies:
1. Jira issues list tags is_email=True for mailer/email campaigns and is_email=False for messaging.
2. ParsedJiraBrief populates email_templates for email campaigns.
3. Messaging templates (WhatsApp, RCS, SMS) remain cleanly separated from email mailer assets.
"""

from unittest.mock import patch

from briefing_parser import parse_jira_brief
from jira_client import list_jira_issues


def test_list_jira_issues_separates_email_and_messaging():
    """Verify list_jira_issues tags email vs messaging campaigns."""
    mock_issues_data = {
        "issues": [
            {
                "key": "SWCM-101",
                "id": "20101",
                "fields": {
                    "summary": "TCLService_Contactability Email - Contact Update",
                    "status": {"name": "In Progress"},
                    "attachment": [
                        {"id": "501", "filename": "mailer_package.zip", "size": 1000, "mimeType": "application/zip"}
                    ],
                },
            },
            {
                "key": "TCN-202",
                "id": "20202",
                "fields": {
                    "summary": "Priority || Whitelisting || WTD PL Campaign",
                    "status": {"name": "In Progress"},
                    "attachment": [
                        {
                            "id": "502",
                            "filename": "content.xlsx",
                            "size": 2000,
                            "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        }
                    ],
                },
            },
        ]
    }

    with patch("requests.post") as mock_post:
        mock_post.return_value.ok = True
        mock_post.return_value.json.return_value = mock_issues_data

        results = list_jira_issues(project="ALL")
        assert len(results) == 2

        email_issue = next(i for i in results if i["key"] == "SWCM-101")
        assert email_issue["is_email"] is True
        assert email_issue["campaign_type"] == "email"

        messaging_issue = next(i for i in results if i["key"] == "TCN-202")
        assert messaging_issue["is_email"] is False
        assert messaging_issue["campaign_type"] == "messaging"


def test_parse_jira_brief_separates_email_templates():
    """Verify parse_jira_brief isolates email templates from WhatsApp/RCS/SMS."""
    email_issue = {
        "key": "SWCM-101",
        "summary": "TCL Mailers Sept Newsletter",
        "status": "In Progress",
        "assignee": "Apurva Mohite",
        "reporter": "Product Team",
        "description_raw": None,
        "description_text": "Please deploy the September mailer package.",
        "attachments": [
            {"id": "701", "filename": "tcl_sept_mailers.zip", "mimeType": "application/zip"},
            {
                "id": "702",
                "filename": "sept_subject_lines.docx",
                "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            },
        ],
    }

    brief = parse_jira_brief(email_issue, download_creatives=False)
    assert brief.is_email_campaign is True
    assert brief.campaign_type_label == "Email Mailer Campaign"

    # Email packages should be collected into email_templates
    assert len(brief.email_templates) == 2
    types = [e["file_type"] for e in brief.email_templates]
    assert "HTML Mailer Package" in types
    assert "Subject Lines & Preheaders" in types

    # WhatsApp and RCS should be empty for an email-only ticket
    assert len(brief.whatsapp_templates) == 0
    assert len(brief.rcs_templates) == 0
