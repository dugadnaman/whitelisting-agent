"""
Unit and API integration tests for the Automated 3-Stage Daily SLA Email Dispatcher.
Verifies stage determination (10am, 1pm, 4pm IST), recipient resolution,
progressive email copy generation, dry-run simulation, and REST endpoints.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from email_notifier import (
    AlertEmailDraft,
    AlertSchedulerState,
    OperatorTicketSummary,
    build_stage_email,
    determine_current_stage,
    dispatch_due_today_alerts,
    get_current_ist_time,
    group_tickets_by_operator,
    preview_due_today_alerts,
    send_email_smtp,
    send_google_chat_sla_alert,
    classify_ticket_ownership,
)


def test_determine_current_stage():
    """Verify time slot resolution for 10am kickoff, 1pm checkpoint, and 4pm escalation."""
    # Morning: 10:15 AM IST
    dt_morning = datetime(2026, 9, 23, 10, 15, tzinfo=UTC)
    assert determine_current_stage(dt_morning) == "MORNING"

    # Midday: 1:15 PM IST (13:15)
    dt_midday = datetime(2026, 9, 23, 13, 15, tzinfo=UTC)
    assert determine_current_stage(dt_midday) == "MIDDAY"

    # EOD Escalation: 4:10 PM IST (16:10)
    dt_eod = datetime(2026, 9, 23, 16, 10, tzinfo=UTC)
    assert determine_current_stage(dt_eod) == "EOD"


def test_group_tickets_by_operator():
    """Verify incomplete tickets are grouped by assignee and resolved to corporate emails."""
    tickets = [
        {"key": "SWCM-1", "summary": "WA campaign", "assignee_name": "Dnyanesh Khawas", "channel": "WhatsApp"},
        {"key": "SWCM-2", "summary": "RCS campaign", "assignee_name": "Dnyanesh Khawas", "channel": "RCS"},
        {"key": "TCN-10", "summary": "SMS campaign", "assignee_name": "Mrunalini Gawande", "channel": "SMS"},
    ]

    operators = group_tickets_by_operator(tickets)
    assert len(operators) == 2

    # Operator with 2 tickets should be first
    assert operators[0].operator_name == "Dnyanesh Khawas"
    assert operators[0].pending_count == 2
    assert operators[0].operator_email == "dnyanesh.khawas@attributics.com"

    assert operators[1].operator_name == "Mrunalini Gawande"
    assert operators[1].pending_count == 1
    assert operators[1].operator_email == "mrunalini.gawande@attributics.com"


def test_build_stage_email_messages():
    """Verify stage-specific messaging for morning kickoff, midday, and EOD urgent escalation."""
    op = OperatorTicketSummary(
        operator_name="Neel Shah",
        operator_email="neel.shah@attributics.com",
        role="Core Operator",
        pending_count=3,
        tickets=[
            {"key": "TCN-50", "summary": "Credit card campaign", "status": "To Do", "channel": "WhatsApp"},
            {"key": "TCN-51", "summary": "Loan disbursement notice", "status": "In Progress", "channel": "SMS"},
            {"key": "TCN-52", "summary": "Insurance push", "status": "Base Pending", "channel": "RCS"},
        ],
    )

    # 1. 10:00 AM Morning Kickoff
    morning_draft = build_stage_email(op, "MORNING", "2026-09-23")
    assert "10:00 AM Kickoff" in morning_draft.subject
    assert "3 campaign(s)" in morning_draft.subject
    assert "Good morning Neel Shah!" in morning_draft.body_html
    assert "TCN-50" in morning_draft.body_html

    # 2. 1:00 PM Midday Checkpoint
    midday_draft = build_stage_email(op, "MIDDAY", "2026-09-23")
    assert "1:00 PM Checkpoint" in midday_draft.subject
    assert "Midday Status Check" in midday_draft.body_html

    # 3. 4:00 PM Urgent Escalation
    eod_draft = build_stage_email(op, "EOD", "2026-09-23")
    assert "Action Required" in eod_draft.subject
    assert "URGENT SLA WARNING" in eod_draft.body_html
    assert "require your urgent attention" in eod_draft.subject


def test_send_email_smtp_simulation_fallback():
    """Verify safe fallback to simulation mode when SMTP credentials are not configured."""
    with patch.dict("os.environ", {}, clear=True):
        draft = AlertEmailDraft(
            stage="MORNING",
            recipient_email="test.operator@attributics.com",
            recipient_name="Test Operator",
            subject="Test Morning SLA Alert",
            body_text="You have 2 campaigns due today.",
            body_html="<p>You have 2 campaigns due today.</p>",
            pending_count=2,
            ticket_keys=["SWCM-1", "SWCM-2"],
        )

        res = send_email_smtp(draft)
        assert res["delivered"] is True
        assert res["simulated"] is True
        assert res["recipient"] == "test.operator@attributics.com"


def test_dispatch_due_today_alerts_dry_run():
    """Verify dispatch_due_today_alerts in dry-run mode returns draft summaries without errors."""
    mock_tickets = [
        {
            "key": "SWCM-99",
            "summary": "Alert Test",
            "assignee_name": "Dnyanesh Khawas",
            "timeline_bucket": "TODAY",
            "status_category": "PENDING",
            "channel": "WhatsApp",
        },
    ]

    with patch("email_notifier.get_due_today_incomplete_tickets", return_value=mock_tickets):
        result = dispatch_due_today_alerts(project="SWCM", stage="MORNING", dry_run=True, operator_name="Lead Tester")
        assert result["ok"] is True
        assert result["stage"] == "MORNING"
        assert result["dry_run"] is True
        assert result["delivered_count"] == 1
        assert result["failed_count"] == 0
        assert len(result["results"]) == 1


def test_client_pending_tickets_are_not_attributed_in_sla_webhook():
    """Client-owned blockers must not count against an operator at any SLA checkpoint."""
    issues = [
        {"key": "SWCM-79", "status": "Base Pending", "status_category": "BLOCKED",
         "timeline_bucket": "TODAY", "assignee_name": "Dnyanesh Khawas"},
        {"key": "SWCM-80", "status": "Content Pending", "status_category": "BLOCKED",
         "timeline_bucket": "TODAY", "assignee_name": "Mrunalini Gawande"},
        {"key": "SWCM-75", "status": "Test Sent", "status_category": "PENDING",
         "timeline_bucket": "TODAY", "assignee_name": "Dnyanesh Khawas"},
    ]
    with (
        patch("email_notifier.get_work_management_dashboard", return_value={"work_items": issues}),
        patch("requests.post") as post,
    ):
        post.return_value.ok = True
        preview = preview_due_today_alerts(project="SWCM", stage="MIDDAY")
        assert preview["total_due_today_incomplete"] == 1
        assert preview["recipient_count"] == 1
        assert preview["drafts"][0]["ticket_keys"] == ["SWCM-75"]

        result = dispatch_due_today_alerts(
            project="SWCM", stage="MIDDAY", dry_run=False, force=True, send_email=False,
            google_chat_webhook_url="https://chat.googleapis.com/v1/spaces/TEST/messages",
        )
        payload = post.call_args.kwargs["json"]
        assert result["total_tickets"] == 1
        assert "SWCM-75" in payload["text"]
        assert "SWCM-79" not in payload["text"]
        assert "SWCM-80" not in payload["text"]
        assert "Mrunalini" not in payload["text"]
        assert "1 campaigns remain pending" in payload["text"]


def test_only_client_pending_tickets_do_not_trigger_webhook():
    issues = [
        {"key": "SWCM-79", "status": "Base Pending", "status_category": "BLOCKED",
         "timeline_bucket": "TODAY", "assignee_name": "Dnyanesh Khawas"},
        {"key": "SWCM-80", "status": "Content Pending", "status_category": "BLOCKED",
         "timeline_bucket": "TODAY", "assignee_name": "Mrunalini Gawande"},
    ]
    with (
        patch("email_notifier.get_work_management_dashboard", return_value={"work_items": issues}),
        patch("requests.post") as post,
    ):
        result = dispatch_due_today_alerts(
            project="SWCM", stage="MIDDAY", dry_run=False, force=True, send_email=False,
            google_chat_webhook_url="https://chat.googleapis.com/v1/spaces/TEST/messages",
        )
        assert result["total_tickets"] == 0
        assert result["recipients_count"] == 0
        assert result["google_chat_result"]["skipped"] is True
        post.assert_not_called()

def test_scheduler_state_deduplication():
    """Verify AlertSchedulerState prevents duplicate sends for the same slot on the same day."""
    state = AlertSchedulerState()
    today_str = f"2099-09-23_{uuid.uuid4().hex[:8]}"
    assert state.is_already_sent_today(today_str, "MORNING") is False

    state.mark_sent(today_str, "MORNING", {"delivered_count": 3})
    assert state.is_already_sent_today(today_str, "MORNING") is True
    assert state.is_already_sent_today(today_str, "MIDDAY") is False


def test_send_google_chat_sla_alert_simulation():
    """Verify Google Chat fallback simulation when no webhook URL is configured."""
    operators = [
        OperatorTicketSummary(
            operator_name="Neel Shah",
            operator_email="neel.shah@attributics.com",
            role="Core Operator",
            pending_count=1,
            tickets=[{"key": "TCN-99", "summary": "Test Campaign"}],
        )
    ]

    with patch.dict("os.environ", {}, clear=True):
        res = send_google_chat_sla_alert("MORNING", operators, "10:00 AM IST", webhook_url="")
        assert res["simulated"] is True
        assert res["channel"] == "Google Chat"


def test_send_google_chat_sla_alert_live():
    """Verify Google Chat webhook POST request structure."""
    operators = [
        OperatorTicketSummary(
            operator_name="Neel Shah",
            operator_email="neel.shah@attributics.com",
            role="Core Operator",
            pending_count=1,
            tickets=[{"key": "TCN-99", "summary": "Test Campaign"}],
        )
    ]

    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        res = send_google_chat_sla_alert(
            "EOD", operators, "04:00 PM IST", webhook_url="https://chat.googleapis.com/v1/spaces/TEST/messages"
        )
        assert res["delivered"] is True
        assert res["simulated"] is False
        assert mock_post.call_count == 1
        payload = mock_post.call_args[1]["json"]
        assert "cardsV2" in payload
        assert "Urgent" in payload["text"] or "CRITICAL" in payload["text"]


def test_classify_ticket_ownership():
    """Verify accurate classification of tickets as Tata Capital vs Attributics."""
    # 1. Tata Capital dependencies
    assert classify_ticket_ownership({"status": "Test Sent"})["ownership"] == "Tata Capital"
    assert classify_ticket_ownership({"status": "Base Pending"})["ownership"] == "Tata Capital"
    assert classify_ticket_ownership({"status": "Content Pending"})["ownership"] == "Tata Capital"
    assert classify_ticket_ownership({"status": "Asset Pending"})["ownership"] == "Tata Capital"
    assert classify_ticket_ownership({"status": "Client Review"})["ownership"] == "Tata Capital"
    assert classify_ticket_ownership({"status": "Whitelisting"})["ownership"] == "Tata Capital"

    # 2. Attributics operator action items
    assert classify_ticket_ownership({"status": "To Do"})["ownership"] == "Attributics"
    assert classify_ticket_ownership({"status": "In Progress"})["ownership"] == "Attributics"
    assert classify_ticket_ownership({"status": "Test Approved"})["ownership"] == "Attributics"
    assert classify_ticket_ownership({"status": "Rework"})["ownership"] == "Attributics"


def test_send_google_chat_sla_alert_ownership_separation():
    """Verify webhook clearly separates Attributics action items from Tata Capital client blockers."""
    operators = [
        OperatorTicketSummary(
            operator_name="Dnyanesh Khawas",
            operator_email="dnyanesh.khawas@attributics.com",
            role="Core Operator",
            pending_count=3,
            tickets=[
                {"key": "SWCM-94", "status": "To Do", "summary": "PL Diwali"},
                {"key": "SWCM-90", "status": "Test Sent", "summary": "LAP Festive"},
                {"key": "SWCM-81", "status": "Base Pending", "summary": "HL Festive"},
            ],
        ),
        OperatorTicketSummary(
            operator_name="Neel Shah",
            operator_email="neel.shah@attributics.com",
            role="Core Operator",
            pending_count=1,
            tickets=[
                {"key": "TCN-546", "status": "In Progress", "summary": "Cards promo"},
            ],
        ),
    ]

    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        res = send_google_chat_sla_alert(
            "MIDDAY", operators, "01:00 PM IST", webhook_url="https://chat.googleapis.com/v1/spaces/TEST/messages"
        )
        assert res["delivered"] is True
        payload = mock_post.call_args[1]["json"]

        # Plain text assertions
        text = payload["text"]
        assert "Pending with Attributics" in text
        assert "Pending with Tata Capital" in text
        assert "SWCM-94" in text
        assert "SWCM-90" in text
        assert "SWCM-81" in text
        assert "Test Sent" in text
        assert "Base Pending" in text
        assert "Ownership Breakdown" in text

        # CardV2 assertions
        cards = payload["cardsV2"]
        assert len(cards) == 1
        card_header = cards[0]["card"]["header"]
        assert "2 with Attributics" in card_header["subtitle"]
        assert "2 with Tata Capital" in card_header["subtitle"]

        sections = cards[0]["card"]["sections"]
        assert len(sections) == 2
        assert "Pending with Attributics" in sections[0]["header"]
        assert "Pending with Tata Capital" in sections[1]["header"]

def test_api_alerts_endpoints():
    """Verify FastAPI preview, dispatch, and scheduler endpoints."""
    from api import app, get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"email": "lead@attributics.com", "name": "Team Lead"}
    client = TestClient(app)

    try:
        # 1. Preview endpoint
        resp_preview = client.get("/api/work-management/alerts/preview?project=SWCM&stage=EOD")
        assert resp_preview.status_code == 200
        preview_data = resp_preview.json()
        assert preview_data["ok"] is True
        assert preview_data["stage"] == "EOD"
        assert "drafts" in preview_data

        # 2. Dispatch endpoint (dry run)
        resp_dispatch = client.post(
            "/api/work-management/alerts/dispatch",
            json={"project": "SWCM", "stage": "EOD", "dry_run": True},
        )
        assert resp_dispatch.status_code == 200
        dispatch_data = resp_dispatch.json()
        assert dispatch_data["ok"] is True
        assert dispatch_data["stage"] == "EOD"
        assert dispatch_data["dry_run"] is True

        # 3. Scheduler status endpoint
        resp_status = client.get("/api/work-management/alerts/scheduler-status")
        assert resp_status.status_code == 200
        status_data = resp_status.json()
        assert "enabled" in status_data
        assert "current_stage" in status_data

        # 4. Scheduler toggle endpoint
        resp_toggle = client.post(
            "/api/work-management/alerts/scheduler-toggle",
            json={"enabled": True},
        )
        assert resp_toggle.status_code == 200
        toggle_data = resp_toggle.json()
        assert toggle_data["enabled"] is True

    finally:
        app.dependency_overrides.clear()


def test_off_schedule_rejection():
    """Verify that dispatching MORNING at 1:12 PM IST is rejected when force=False."""
    from email_notifier import is_stage_within_window

    dt_1pm = datetime(2026, 9, 28, 13, 12, tzinfo=UTC)
    is_valid, reason = is_stage_within_window("MORNING", dt_1pm)
    assert is_valid is False
    assert "Off-schedule" in reason
    assert "10:00 AM" in reason

    # MIDDAY at 13:12 IST is valid
    is_valid_midday, _ = is_stage_within_window("MIDDAY", dt_1pm)
    assert is_valid_midday is True

    # EOD at 13:12 IST is off-schedule
    is_valid_eod, reason_eod = is_stage_within_window("EOD", dt_1pm)
    assert is_valid_eod is False
    assert "04:00 PM" in reason_eod


def test_dispatch_time_window_enforcement():
    """Verify dispatch_due_today_alerts rejects out-of-window requests unless force=True."""
    dt_1pm = datetime(2026, 9, 28, 13, 12, tzinfo=UTC)

    with (
        patch("email_notifier.get_current_ist_time", return_value=dt_1pm),
        patch("email_notifier.get_due_today_incomplete_tickets", return_value=[{"key": "SWCM-1", "summary": "t"}]),
    ):
        # Trying to send MORNING at 1:12 PM without force
        res = dispatch_due_today_alerts(project="SWCM", stage="MORNING", dry_run=False, force=False)
        assert res["ok"] is False
        assert res["rejected_off_schedule"] is True
        assert "Off-schedule" in res["error"]

        # With force=True, it is permitted
        with patch("email_notifier.send_google_chat_sla_alert", return_value={"delivered": True}):
            res_forced = dispatch_due_today_alerts(
                project="SWCM", stage="MORNING", dry_run=False, force=True, send_email=False
            )
            assert res_forced["ok"] is True
            assert res_forced["stage"] == "MORNING"


def test_scheduler_db_persistence_deduplication():
    """Verify AlertSchedulerState persists to DB and prevents duplicate dispatch on same day."""
    state1 = AlertSchedulerState()
    test_day = f"2099-09-28_{uuid.uuid4().hex[:8]}"
    test_stage = "TEST_SLOT"
    state1.mark_sent(test_day, test_stage, {"delivered_count": 1})
    assert state1.is_already_sent_today(test_day, test_stage) is True

    # Create new instance (simulating server reboot)
    state2 = AlertSchedulerState()
    assert state2.is_already_sent_today(test_day, test_stage) is True
