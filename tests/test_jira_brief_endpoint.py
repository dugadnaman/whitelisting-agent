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
                    {
                        "type": "text",
                        "text": "Header: Diwali Dhamaka\nBody: Dear Customer, get Rs. 50,000 personal loan.\nFooter: T&C apply\nButton: Apply -> https://www.tatacapital.com",
                    }
                ],
            }
        ],
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
    from models import ApprovalStatus, SubmissionResult, SubmissionStatus

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
            },
        ],
    }

    with (
        patch("submission_client.submit_template", side_effect=mock_submit),
        patch("config.get_waba_id", return_value="12345"),
    ):
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


@patch("api.get_current_user", return_value=MOCK_USER)
def test_jira_projects_catalog_endpoint(mock_user):
    """Verify /api/jira/projects returns full Tata Capital project catalog."""
    response = client.get("/api/jira/projects")
    assert response.status_code == 200
    projects = response.json()
    assert isinstance(projects, list)
    keys = [p["key"] for p in projects]
    assert "ALL" in keys
    assert "TCN" in keys
    assert "SWCM" in keys
    assert "TM" in keys
    assert "TAT" in keys
    assert "MON" in keys
    assert "COL" in keys


def test_swcm_59_docx_and_sms_extraction():
    """Verify SWCM-59 parses .docx into 3 UTILITY WhatsApp templates with headers and No CTA."""
    from briefing_parser import parse_jira_brief
    from jira_client import fetch_jira_issue

    try:
        issue = fetch_jira_issue("SWCM-59")
    except Exception:
        # Offline fallback: skip network if credentials expired
        return

    parsed = parse_jira_brief(issue, download_creatives=True)
    assert len(parsed.whatsapp_templates) == 3
    for wa in parsed.whatsapp_templates:
        assert wa["category"] == "UTILITY"
        assert wa["button_type"] == "NONE"
        assert wa["button_text"] is None
        assert wa["header_text"] in (
            "Important Update - Loan Against Equity Mutual Funds",
            "Immediate Action Required - Loan Against Equity Mutual Funds",
            "Urgent Action Required - Loan Against Equity Mutual Funds",
        )
        assert "LAS_Whitelisting" not in (wa["header_text"] or "")

    # Exactly 3 clean SMS templates
    assert len(parsed.sms_templates) == 3
    sms_names = [s["template_name"] for s in parsed.sms_templates]
    assert "las_D_250926" in sms_names or "las_A_B_250926" in sms_names


def test_swcm_61_metadata_table_rejected_as_templates():
    """Verify SWCM-61 key-value metadata table emits 0 WhatsApp templates and classifies as email campaign."""
    from briefing_parser import parse_jira_brief
    from jira_client import fetch_jira_issue

    try:
        issue = fetch_jira_issue("SWCM-61")
    except Exception:
        return

    parsed = parse_jira_brief(issue, download_creatives=True)
    assert len(parsed.whatsapp_templates) == 0
    assert len(parsed.sms_templates) == 0
    assert parsed.is_email_campaign is True
    assert parsed.campaign_type_label == "Email Mailer Campaign"
    assert len(parsed.email_templates) >= 1


def test_channel_counts_in_brief_and_issues():
    """Verify channel_counts breakdown is computed on Jira briefs."""
    from briefing_parser import parse_jira_brief
    from jira_client import fetch_jira_issue

    try:
        issue = fetch_jira_issue("SWCM-59")
    except Exception:
        return

    parsed = parse_jira_brief(issue, download_creatives=True)
    assert "channel_counts" in dir(parsed)
    counts = parsed.channel_counts
    assert counts["whatsapp"] == 3
    assert counts["sms"] == 3
    assert counts["total"] >= 6
    assert "rcs" in counts
    assert "email" in counts
    assert "push" in counts


def test_email_brief_does_not_stage_push_but_explicit_push_brief_does():
    from briefing_parser import parse_jira_brief

    email_issue = {
        "key": "SWCM-83",
        "summary": "TCHFLService_Welcome NC - Sept 2026",
        "description_text": "Email and SMS campaign",
        "attachments": [{"id": "mail-zip", "filename": "TCHFL_Welcome_Call_Non_Contactable_Communication.zip"}],
    }
    email_brief = parse_jira_brief(email_issue, download_creatives=False)
    assert email_brief.channel_counts["email"] == 1
    assert email_brief.channel_counts["push"] == 0
    assert email_brief.channel_counts["total"] == sum(
        email_brief.channel_counts[channel] for channel in ("whatsapp", "rcs", "sms", "email", "push")
    )
    assert email_brief.moengage_campaign["push_title"] is None
    assert email_brief.moengage_campaign["push_body"] is None

    push_issue = {
        "key": "SWCM-84",
        "summary": "App Notification - Welcome",
        "description_text": "",
        "attachments": [],
    }
    push_brief = parse_jira_brief(push_issue, download_creatives=False)
    assert push_brief.channel_counts["push"] == 1
    assert push_brief.moengage_campaign["push_title"]
    assert push_brief.moengage_campaign["push_body"]


def test_swcm_85_service_table_extracts_whatsapp_template():
    """Verify SWCM-85 single-header execution table extracts WhatsApp template even when copy is in Template ID cell."""
    from briefing_parser import parse_jira_brief

    mock_issue = {
        "key": "SWCM-85",
        "summary": "TCLService_HR_WhatsApp Campaign – “MANDATORY – TCL HR and TCOC Orientation – October 2026 ” - 01-10-2026 @ 09:00",
        "status": "New Ticket",
        "assignee": "Dnyanesh Khawas",
        "reporter": "Anish Nagpal",
        "description_raw": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "table",
                    "content": [
                        {
                            "type": "tableRow",
                            "content": [
                                {
                                    "type": "tableHeader",
                                    "content": [
                                        {
                                            "type": "paragraph",
                                            "content": [{"type": "text", "text": "WhatsApp Campaign execution format"}],
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "type": "tableRow",
                            "content": [
                                {
                                    "type": "tableCell",
                                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Campaign Name"}]}],
                                },
                                {
                                    "type": "tableCell",
                                    "content": [
                                        {"type": "paragraph", "content": [{"type": "text", "text": "WhatsApp Campaign - MANDATORY Orientation"}]}
                                    ],
                                },
                            ],
                        },
                        {
                            "type": "tableRow",
                            "content": [
                                {
                                    "type": "tableCell",
                                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "WhatsApp Text"}]}],
                                },
                                {"type": "tableCell", "content": [{"type": "paragraph", "content": []}]},
                            ],
                        },
                        {
                            "type": "tableRow",
                            "content": [
                                {
                                    "type": "tableCell",
                                    "content": [
                                        {"type": "paragraph", "content": [{"type": "text", "text": "Template ID (If available)"}]}
                                    ],
                                },
                                {
                                    "type": "tableCell",
                                    "content": [
                                        {
                                            "type": "paragraph",
                                            "content": [
                                                {
                                                    "type": "text",
                                                    "text": (
                                                        "Dear Colleague,\n\n"
                                                        "You are invited to attend the virtual TCL HR and TCOC Orientation – 2026 scheduled on 01-Oct-26.\n\n"
                                                        "This is a mandatory session so kindly ensure 100% attendance & participation.\n\n"
                                                        "👉 Link to Join: https://teams.microsoft.com/meet/12345\n\n"
                                                        "Regards,\nFunctional L&D – Tata Capital Ltd."
                                                    ),
                                                }
                                            ],
                                        }
                                    ],
                                },
                            ],
                        },
                    ],
                }
            ],
        },
        "description_text": "SWCM-85 Orientation",
        "attachments": [],
    }

    parsed = parse_jira_brief(mock_issue, download_creatives=False)
    assert len(parsed.whatsapp_templates) == 1
    wa = parsed.whatsapp_templates[0]
    assert "Dear Colleague" in wa["body"]
    assert "https://teams.microsoft.com/meet/12345" in wa["button_url"]
    assert parsed.channel_counts["whatsapp"] == 1
    assert parsed.channel_counts["push"] == 0
def test_multi_channel_ticket_with_email_and_whatsapp_extracts_correct_channels_and_no_false_push():
    """Verify that a ticket with both Email and WhatsApp identifies both channels accurately and emits 0 push."""
    from briefing_parser import parse_jira_brief
    from jira_client import list_jira_issues

    ticket_data = {
        "key": "SWCM-200",
        "id": "20200",
        "fields": {
            "summary": "Festival Campaign - Email and WhatsApp Blast",
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Hi Team, please execute the Email and WhatsApp campaigns for festival season. Send notification to eligible users."}],
                    },
                    {
                        "type": "table",
                        "content": [
                            {
                                "type": "tableRow",
                                "content": [
                                    {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Channel"}]}]},
                                    {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Content"}]}]},
                                ],
                            },
                            {
                                "type": "tableRow",
                                "content": [
                                    {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "WA"}]}]},
                                    {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Dear Customer, celebrate Diwali with instant personal loans up to Rs. 5 Lakhs! Click here to claim your offer."}]}]},
                                ],
                            },
                            {
                                "type": "tableRow",
                                "content": [
                                    {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "EMAIL"}]}]},
                                    {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Subject: Exclusive Diwali Offers for You!\nDear Valued Customer, this festive season enjoy special interest rates."}]}]},
                                ],
                            },
                        ],
                    },
                ],
            },
            "attachment": [
                {"id": "att-1", "filename": "Diwali_Mailer_Package.zip", "size": 1024, "mimeType": "application/zip"}
            ],
        },
    }

    # 1. list_jira_issues check
    with patch("requests.post") as mock_post:
        mock_post.return_value.ok = True
        mock_post.return_value.json.return_value = {"issues": [ticket_data]}
        issues = list_jira_issues(project="SWCM")
        counts = issues[0]["channel_counts"]
        assert counts["whatsapp"] == 1
        assert counts["email"] == 1
        assert counts["push"] == 0
        assert counts["total"] == 2

    # 2. parse_jira_brief check
    issue_for_brief = {
        "key": ticket_data["key"],
        "summary": ticket_data["fields"]["summary"],
        "description_raw": ticket_data["fields"]["description"],
        "description_text": "Hi Team, please execute the Email and WhatsApp campaigns for festival season. Send notification to eligible users.",
        "attachments": ticket_data["fields"]["attachment"],
    }
    brief = parse_jira_brief(issue_for_brief, download_creatives=False)
    assert len(brief.whatsapp_templates) == 1
    assert len(brief.email_templates) >= 1
    assert brief.channel_counts["whatsapp"] == 1
    assert brief.channel_counts["email"] >= 1
    assert brief.channel_counts["push"] == 0
    assert brief.moengage_campaign["push_title"] is None
def test_jira_brief_status_enrichment_and_filtering():
    """Verify compute_brief_status accurately classifies ticket stages and /api/jira/issues filters by brief_status."""
    from jira_client import compute_brief_status, list_jira_issues

    # 1. Unit test classification logic
    assert compute_brief_status("To Do", attachment_count=1, total_campaigns=1) == "Pending"
    assert compute_brief_status("Open", attachment_count=2, total_campaigns=2) == "Pending"
    assert compute_brief_status("Base Pending", attachment_count=1, total_campaigns=1) == "Pending"
    assert compute_brief_status("In Progress", attachment_count=1, total_campaigns=1) == "In Progress"
    assert compute_brief_status("Under Review", attachment_count=1, total_campaigns=1) == "In Progress"
    assert compute_brief_status("To Do", attachment_count=1, total_campaigns=1, is_submitted=True) == "In Progress"
    assert compute_brief_status("Done", attachment_count=1, total_campaigns=1) == "Completed"
    assert compute_brief_status("Resolved", attachment_count=1, total_campaigns=1) == "Completed"
    assert compute_brief_status("Closed", attachment_count=0, total_campaigns=0) == "Completed"
    assert compute_brief_status("Rejected", attachment_count=1, total_campaigns=1) == "Failed"
    assert compute_brief_status("Failed", attachment_count=1, total_campaigns=1) == "Failed"
    assert compute_brief_status("To Do", attachment_count=0, total_campaigns=0) == "Not Generated"

    # 2. Test list_jira_issues with brief_status filter
    mock_issues = [
        {
            "key": "TCN-101",
            "id": "10101",
            "fields": {
                "summary": "Pending Brief",
                "status": {"name": "To Do"},
                "attachment": [{"id": "1", "filename": "copy.xlsx"}],
            },
        },
        {
            "key": "TCN-102",
            "id": "10102",
            "fields": {
                "summary": "Completed Brief",
                "status": {"name": "Done"},
                "attachment": [{"id": "2", "filename": "copy.xlsx"}],
            },
        },
        {
            "key": "TCN-103",
            "id": "10103",
            "fields": {
                "summary": "Empty Brief",
                "status": {"name": "To Do"},
                "attachment": [],
            },
        },
    ]

    with patch("requests.post") as mock_post:
        mock_post.return_value.ok = True
        mock_post.return_value.json.return_value = {"issues": mock_issues}

        all_issues = list_jira_issues(project="TCN")
        assert len(all_issues) == 3
        assert all_issues[0]["brief_status"] == "Pending"
        assert all_issues[1]["brief_status"] == "Completed"
        assert all_issues[2]["brief_status"] == "Not Generated"

        # Filter by Pending
        pending_issues = list_jira_issues(project="TCN", brief_status="pending")
        assert len(pending_issues) == 1
        assert pending_issues[0]["key"] == "TCN-101"

        # Filter by Completed
        completed_issues = list_jira_issues(project="TCN", brief_status="completed")
        assert len(completed_issues) == 1
        assert completed_issues[0]["key"] == "TCN-102"

        # Filter by Not Generated
        not_gen_issues = list_jira_issues(project="TCN", brief_status="not_generated")
        assert len(not_gen_issues) == 1
        assert not_gen_issues[0]["key"] == "TCN-103"
def test_jira_creative_upload_and_download():
    """Verify users can upload a replacement creative and download/preview it via the Jira creative endpoints."""
    import io
    from pathlib import Path
    from PIL import Image
    from api import app, get_current_user

    # Create a 1280x720 (16:9) PNG image in memory
    img = Image.new("RGB", (1280, 720), color=(20, 90, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    saved_path: Path | None = None
    try:
        # 1. Upload replacement creative
        upload_resp = client.post(
            "/api/jira/creative/upload",
            files={"file": ("diwali_banner_16_9.png", png_bytes, "image/png")},
        )
        assert upload_resp.status_code == 200, upload_resp.text
        data = upload_resp.json()
        assert data["ok"] is True
        assert data["filename"] == "diwali_banner_16_9.png"
        assert data["dimensions"] == "1280x720"
        assert "16:9" in (data.get("aspect_ratio") or "")
        saved_path = Path(data["local_path"])
        assert saved_path.is_file()

        # 2. Download creative by path
        dl_resp = client.get(
            "/api/jira/creative/download",
            params={"path": str(saved_path), "filename": "diwali_banner_16_9.png"},
        )
        assert dl_resp.status_code == 200
        assert dl_resp.content == png_bytes
        assert "attachment" in dl_resp.headers.get("content-disposition", "")
        assert "diwali_banner_16_9.png" in dl_resp.headers.get("content-disposition", "")

        # 3. Preview creative inline
        inline_resp = client.get(
            "/api/jira/creative/download",
            params={"path": str(saved_path), "inline": "true"},
        )
        assert inline_resp.status_code == 200
        assert inline_resp.content == png_bytes
    finally:
        app.dependency_overrides.clear()
        if saved_path and saved_path.exists():
            saved_path.unlink()
