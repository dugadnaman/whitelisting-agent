"""
Unit and integration tests for Jira Work Management & Autonomous Workload Dispatcher Engine.
Tests:
1. Status categorization (PENDING, BLOCKED, DONE).
2. Due date timeline bucketing (OVERDUE, TODAY, TOMORROW, DAY_AFTER, LATER, NO_DATE).
3. Messaging channel inference from Jira summary.
4. Assignee capacity calculation (Dnyanesh, Mrunalini, Neel, interns).
5. Live dashboard generation.
6. Autonomous AI workload rebalancing agent proposals.
7. Ticket transfer & handover comment generation.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from work_manager import (
    JiraUser,
    WorkItem,
    ai_rebalance_workload,
    categorize_status,
    compute_timeline_bucket,
    fetch_assignable_jira_users,
    get_work_management_dashboard,
    infer_channel_from_summary,
    transfer_jira_ticket,
)


def test_status_categorization():
    """Verify arbitrary Jira statuses classify into PENDING, BLOCKED, or DONE."""
    assert categorize_status("To Do") == "PENDING"
    assert categorize_status("In Progress") == "PENDING"
    assert categorize_status("Under Review") == "PENDING"
    assert categorize_status("Blocked") == "BLOCKED"
    assert categorize_status("Waiting on Client") == "BLOCKED"
    assert categorize_status("Done") == "DONE"
    assert categorize_status("Resolved") == "DONE"
    assert categorize_status("Whitelisted") == "DONE"
    assert categorize_status("") == "PENDING"


def test_timeline_bucket_calculation():
    """Verify relative due dates are bucketed accurately relative to today."""
    today = datetime.now(UTC).date()
    yesterday = (today - timedelta(days=2)).isoformat()
    today_str = today.isoformat()
    tmrw_str = (today + timedelta(days=1)).isoformat()
    day_after_str = (today + timedelta(days=2)).isoformat()
    next_week_str = (today + timedelta(days=5)).isoformat()

    assert compute_timeline_bucket(yesterday)[0] == "OVERDUE"
    assert compute_timeline_bucket(today_str)[0] == "TODAY"
    assert compute_timeline_bucket(tmrw_str)[0] == "TOMORROW"
    assert compute_timeline_bucket(day_after_str)[0] == "DAY_AFTER"
    assert compute_timeline_bucket(next_week_str)[0] == "LATER"
    assert compute_timeline_bucket(None)[0] == "NO_DATE"


def test_channel_inference_from_summary():
    """Verify target channel is inferred from ticket title keywords."""
    assert infer_channel_from_summary("Whitelisting II WA Utility Content Sept") == "WhatsApp"
    assert infer_channel_from_summary("App Downloads : RCS") == "RCS"
    assert infer_channel_from_summary("September base || Marketing campaign || SMS") == "SMS"
    assert infer_channel_from_summary("TCL Mailers Sept") == "Email"
    assert infer_channel_from_summary("General Campaign Brief") == "General"


def test_assignable_users_and_capacity_tracking():
    """Verify team members and interns are parsed with appropriate roles."""
    users = fetch_assignable_jira_users(project="TCN")
    assert len(users) > 0

    names = {u.name for u in users}
    assert "Mrunalini Gawande" in names
    assert "Dnyanesh Khawas" in names
    assert "Neel Shah" in names

    mrunalini = next(u for u in users if u.name == "Mrunalini Gawande")
    assert mrunalini.role == "Core Operator"
    assert mrunalini.account_id.startswith("712020:")


def test_work_management_dashboard_aggregation():
    """Verify live work management dashboard ingests tickets and populates metrics."""
    dash = get_work_management_dashboard(project="TCN", limit=25)
    assert dash["project"] == "TCN"
    assert dash["total_tickets"] > 0
    assert "PENDING" in dash["status_counts"]
    assert "TODAY" in dash["timeline_counts"]
    assert "TOMORROW" in dash["timeline_counts"]
    assert len(dash["assignees"]) > 0
    assert len(dash["work_items"]) > 0


def test_ai_workload_rebalancing_proposals():
    """Verify AI workload dispatcher evaluates context and proposes ticket reassignments."""
    prompt = "Mrunalini is overloaded with tickets due this week, transfer some tickets to other team members or interns"
    res = ai_rebalance_workload(prompt, project="TCN", auto_execute=False)

    assert res["ok"] is True
    assert res["proposals_count"] > 0
    assert len(res["proposals"]) > 0

    first_proposal = res["proposals"][0]
    assert first_proposal["issue_key"].startswith("TCN-")
    assert first_proposal["current_assignee"] == "Mrunalini Gawande"
    assert first_proposal["target_assignee"] != "Mrunalini Gawande"
    assert first_proposal["target_account_id"].startswith("712020:")
    assert "Rebalancing" in first_proposal["reason"] or "transfer" in first_proposal["reason"]


def test_transfer_jira_ticket_mock():
    """Verify transfer_jira_ticket calls Atlassian API and posts handover comment."""
    with patch("requests.put") as mock_put, patch("work_manager.add_jira_comment") as mock_comment:
        mock_put.return_value.status_code = 204
        res = transfer_jira_ticket(
            issue_key="TCN-999",
            to_account_id="712020:fae946f9-8472-455a-9d27-6d773ecfb48d",
            handover_note="Passing WhatsApp creative review",
            transferred_by="Naman Dugad",
        )
        assert res["ok"] is True
        assert res["issue_key"] == "TCN-999"
        assert res["to_account_id"] == "712020:fae946f9-8472-455a-9d27-6d773ecfb48d"
        assert mock_put.called
        assert mock_comment.called
        comment_arg = mock_comment.call_args[0][1]
        assert "Passing WhatsApp creative review" in comment_arg
        assert "Naman Dugad" in comment_arg
