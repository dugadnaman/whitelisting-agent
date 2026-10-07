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
    get_turnaround_and_bottleneck_analytics,
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
    assert "Soham Das" in names
    assert "Aadya" in names or "Aadya Trivedi" in names
    assert "Apurva Mohite" not in names
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
    prompt = (
        "Mrunalini is overloaded with tickets due this week, transfer some tickets to other team members or interns"
    )
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
    """Verify transfer_jira_ticket calls Atlassian API for licensed Jira users."""
    with patch("requests.put") as mock_put:
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


def test_swcm_project_dashboard_and_blocked_status():
    """Verify TATA Service and wealth Campaign Manager (SWCM) project queries and blocks status."""
    dash = get_work_management_dashboard(project="SWCM", limit=20)
    assert dash["project"] == "SWCM"
    assert dash["total_tickets"] > 0
    assert "BLOCKED" in dash["status_counts"]
    from work_manager import categorize_status

    assert categorize_status("Base Pending") == "BLOCKED"
    assert any(w["key"].startswith("SWCM-") for w in dash["work_items"])
    assert any(p["key"] == "SWCM" for p in dash["projects_catalog"])


def test_all_projects_combined_dashboard():
    """Verify combined querying across all Tata projects (ALL)."""
    dash = get_work_management_dashboard(project="ALL", limit=30)
    assert dash["project"] == "ALL"
    assert dash["total_tickets"] > 0
    keys = [w["key"] for w in dash["work_items"]]
    # Should contain tickets from both TCN and SWCM
    assert any(k.startswith("SWCM-") for k in keys) or any(k.startswith("TCN-") for k in keys)


def test_turnaround_and_bottleneck_analytics():
    """Verify cycle time calculations, operator turnaround velocity, and roadblock attribution."""
    analytics = get_turnaround_and_bottleneck_analytics(project="SWCM", limit=50)

    assert analytics["project"] == "SWCM"
    assert analytics["total_tickets_analyzed"] > 0
    assert analytics["completed_count"] > 0
    assert analytics["team_avg_cycle_time_days"] > 0.0
    assert analytics["team_avg_cycle_time_hours"] > 0.0

    # Roadblock Attribution checks
    attr = analytics["roadblock_attribution"]
    assert "total_roadblocks" in attr
    assert "tata_capital" in attr
    assert "karix_meta" in attr
    assert "attributics" in attr
    assert attr["total_roadblocks"] == (
        attr["tata_capital"]["count"] + attr["karix_meta"]["count"] + attr["attributics"]["count"]
    )
    if attr["total_roadblocks"] > 0:
        total_pct = (
            attr["tata_capital"]["percentage"] + attr["karix_meta"]["percentage"] + attr["attributics"]["percentage"]
        )
        assert round(total_pct) == 100

    # Operator Velocities checks
    ops = analytics["operator_velocities"]
    assert len(ops) > 0
    dnyanesh = next((o for o in ops if o["name"] == "Dnyanesh Khawas"), None)
    assert dnyanesh is not None
    assert dnyanesh["completed_count"] > 0
    assert dnyanesh["avg_cycle_time_days"] > 0.0
    assert dnyanesh["velocity_rating"] in ["EXCELLENT", "FAST", "STANDARD"]

    # Blocked tickets diagnostic
    blocked = analytics["blocked_tickets"]
    assert len(blocked) == attr["total_roadblocks"]
    for t in blocked:
        assert t["roadblock_category"] in [
            "Tata Capital (Client)",
            "Karix / Meta (Gateway)",
            "Attributics (Internal)",
        ]
        assert t["root_cause"] != ""
        assert t["aging_days"] >= 0.0


def test_api_turnaround_analytics_endpoint(provision_user):
    """Verify GET /api/work-management/turnaround-analytics returns expected analytics payload."""
    from fastapi.testclient import TestClient

    from api import app

    _, headers = provision_user(tenant="tata", role="operator", email="test@attributics.com")
    client = TestClient(app, headers=headers)

    issues = [
        {
            "key": "SWCM-1",
            "summary": "WhatsApp creative approved",
            "status": "Done",
            "assignee": "Dnyanesh Khawas",
            "created": "2026-09-01T09:00:00Z",
            "updated": "2026-09-02T09:00:00Z",
        },
        {
            "key": "SWCM-2",
            "summary": "SMS audience delivery",
            "status": "Base Pending",
            "assignee": "Neel Shah",
            "created": "2026-09-01T09:00:00Z",
            "updated": "2026-09-02T09:00:00Z",
        },
    ]
    with patch("work_manager.list_jira_issues", return_value=issues):
        resp = client.get("/api/work-management/turnaround-analytics?project=SWCM&limit=25")
    assert resp.status_code == 200
    data = resp.json()
    assert data["project"] == "SWCM"
    assert "team_avg_cycle_time_days" in data
    assert "roadblock_attribution" in data
    assert "operator_velocities" in data
    assert "blocked_tickets" in data
    assert "team_fastest_hours" in data
    assert "primary_bottleneck_driver" in data


def test_bulk_transfer_jira_tickets():
    """Verify bulk_transfer_jira_tickets iterates across issues, reassigns, and audits."""
    from unittest.mock import patch

    from work_manager import bulk_transfer_jira_tickets

    with patch("work_manager.transfer_jira_ticket") as mock_transfer:
        mock_transfer.side_effect = [
            {"success": True, "issue_key": "SWCM-101", "error": None},
            {"success": False, "issue_key": "SWCM-102", "error": "User inactive"},
            {"success": True, "issue_key": "SWCM-103", "error": None},
        ]

        res = bulk_transfer_jira_tickets(
            issue_keys=["SWCM-101", "SWCM-102", "SWCM-103"],
            to_account_id="712020:test-intern-id",
            to_account_name="Intern",
            handover_note="Batch reassignment for campaign sprint.",
            transferred_by="Dispatcher Lead",
        )

        assert res["total_requested"] == 3
        assert res["transferred_count"] == 2
        assert res["failed_count"] == 1
        assert len(res["transferred_keys"]) == 2
        assert "SWCM-101" in res["transferred_keys"]
        assert "SWCM-103" in res["transferred_keys"]
        assert len(res["failed_items"]) == 1
        assert res["failed_items"][0]["issue_key"] == "SWCM-102"
        assert res["failed_items"][0]["error"] == "User inactive"
        assert mock_transfer.call_count == 3


def test_api_bulk_transfer_endpoint(provision_user):
    """Verify POST /api/work-management/bulk-transfer accepts batch reassignments."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from api import app

    _, headers = provision_user(tenant="tata", role="operator", email="dnyanesh.khawas@attributics.com")
    client = TestClient(app, headers=headers)

    with patch("work_manager.transfer_jira_ticket") as mock_transfer:
        mock_transfer.return_value = {"success": True, "issue_key": "SWCM-1", "error": None}

        resp = client.post(
            "/api/work-management/bulk-transfer",
            json={
                "issue_keys": ["SWCM-1", "SWCM-2"],
                "to_account_id": "712020:645c853f-intern",
                "handover_note": "Reassigning queue",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requested"] == 2
        assert data["transferred_count"] == 2
        assert data["failed_count"] == 0
        assert data["to_account_id"] == "712020:645c853f-intern"


def test_unassigned_tickets_auto_assigned_to_neel_shah():
    """Verify unassigned tickets automatically route to Neel Shah in work management."""
    from unittest.mock import patch

    from work_manager import NEEL_SHAH_NAME, get_work_management_dashboard

    mock_issues = [
        {
            "key": "TCN-999",
            "id": "100999",
            "summary": "Unassigned Personal Loan Blast",
            "status": "To Do",
            "assignee": "Unassigned",
            "reporter": "Product Manager",
            "duedate": None,
            "created": "2026-09-25T10:00:00Z",
            "updated": "2026-09-25T10:00:00Z",
            "attachment_count": 0,
            "attachments": [],
            "labels": [],
            "mentions_soham": False,
            "soham_mention_reasons": [],
            "comments_text": "",
            "description_text": "Please execute.",
            "is_email": False,
            "campaign_type": "messaging",
        }
    ]

    with (
        patch("work_manager.list_jira_issues", return_value=mock_issues),
        patch("work_manager.get_all_operational_assignments", return_value={}),
    ):
        dash = get_work_management_dashboard(project="TCN", limit=10)
        item = dash["work_items"][0]
        assert item["assignee_name"] == NEEL_SHAH_NAME
        assert item["is_operational_assignment"] is True
        assert item["original_assignee"] == "Unassigned"
        assert dash["unassigned_count"] == 1
        neel_u = next(u for u in dash["assignees"] if u["name"] == NEEL_SHAH_NAME)
        assert neel_u["open_tickets_count"] >= 1


def test_assign_unassigned_tickets_to_neel_endpoint(provision_user):
    """Verify POST /api/work-management/assign-unassigned reassigns unassigned tickets to Neel Shah."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from api import app

    _, headers = provision_user(tenant="tata", role="operator", email="neel.shah@attributics.com")
    client = TestClient(app, headers=headers)

    with patch("work_manager.assign_unassigned_tickets_to_neel") as mock_assign:
        mock_assign.return_value = {
            "ok": True,
            "total_found": 3,
            "transferred_count": 3,
            "transferred_keys": ["TCN-1", "TCN-2", "TCN-3"],
            "target_assignee": "Neel Shah",
        }

        resp = client.post("/api/work-management/assign-unassigned?project=ALL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["transferred_count"] == 3
        assert data["target_assignee"] == "Neel Shah"


def test_soham_mention_routing_in_comments_and_attachments():
    """
    Verify that if any ticket mentions Soham in comments, attachments, or description,
    it is automatically routed to Soham Das and removed from the original assignee's workload.
    """
    from unittest.mock import patch

    from work_manager import get_work_management_dashboard

    mock_issues = [
        {
            "key": "TCN-901",
            "id": "100901",
            "summary": "Referral Campaign Blast",
            "status": "In Progress",
            "assignee": "Mrunalini Gawande",
            "reporter": "Marketing",
            "duedate": "2026-09-23",
            "attachment_count": 1,
            "attachments": [{"filename": "soham_creatives_v1.png"}],
            "mentions_soham": True,
            "soham_mention_reasons": ["attachment"],
        },
        {
            "key": "TCN-902",
            "id": "100902",
            "summary": "Festival Offer Push",
            "status": "In Progress",
            "assignee": "Dnyanesh Khawas",
            "reporter": "Marketing",
            "duedate": "2026-09-23",
            "attachment_count": 0,
            "mentions_soham": True,
            "soham_mention_reasons": ["comment"],
        },
        {
            "key": "TCN-903",
            "id": "100903",
            "summary": "Standard Loan Disbursal",
            "status": "In Progress",
            "assignee": "Dnyanesh Khawas",
            "reporter": "Marketing",
            "duedate": "2026-09-23",
            "attachment_count": 0,
            "mentions_soham": False,
        },
    ]

    with patch("work_manager.list_jira_issues", return_value=mock_issues):
        dash = get_work_management_dashboard(project="TCN", limit=10)
        items = dash["work_items"]
        assignees = {a["name"]: a for a in dash["assignees"]}

        # TCN-901 was assigned to Mrunalini in Jira, but mentions Soham in attachment -> routed to Soham!
        item_901 = next(w for w in items if w["key"] == "TCN-901")
        assert item_901["assignee_name"] == "Soham Das"
        assert item_901["routed_to_soham"] is True
        assert item_901["original_assignee"] == "Mrunalini Gawande"

        # TCN-902 was assigned to Dnyanesh in Jira, but mentions Soham in comment -> routed to Soham!
        item_902 = next(w for w in items if w["key"] == "TCN-902")
        assert item_902["assignee_name"] == "Soham Das"
        assert item_902["routed_to_soham"] is True
        assert item_902["original_assignee"] == "Dnyanesh Khawas"

        # TCN-903 does NOT mention Soham -> stays with Dnyanesh
        item_903 = next(w for w in items if w["key"] == "TCN-903")
        assert item_903["assignee_name"] == "Dnyanesh Khawas"
        assert item_903["routed_to_soham"] is False

        # Workload capacity checks: Soham gets both 901 and 902
        assert assignees["Soham Das"]["open_tickets_count"] == 2
        # Dnyanesh only has 903 (902 was stripped and assigned to Soham)
        assert assignees["Dnyanesh Khawas"]["open_tickets_count"] == 1
        # Mrunalini has 0 open tickets (901 was stripped and assigned to Soham)
        assert assignees["Mrunalini Gawande"]["open_tickets_count"] == 0


def test_virtual_operational_assignment_soham_and_aadya():
    """Verify transfers to Soham Das or Aadya execute virtual operational assignments without calling Jira API."""
    from work_manager import (
        clear_operational_assignment,
        get_all_operational_assignments,
        transfer_jira_ticket,
    )

    # 1. Transfer to Soham Das (no Jira seat)
    res_soham = transfer_jira_ticket(
        issue_key="SWCM-888",
        to_account_id="712020:c8914cff-1299-4ad7-989b-e38859cbcdbf",
        handover_note="Handing off to Soham for campaign execution",
        transferred_by="Mrunalini Gawande",
    )
    assert res_soham["ok"] is True
    assert res_soham["virtual_assignment"] is True
    assert res_soham["assignee_name"] == "Soham Das"

    # Verify it is saved in SQLite store
    assignments = get_all_operational_assignments()
    assert "SWCM-888" in assignments
    assert assignments["SWCM-888"]["operational_assignee"] == "Soham Das"
    assert "Handing off to Soham" in assignments["SWCM-888"]["handover_note"]

    # 2. Transfer to Aadya (intern, no Jira seat)
    res_aadya = transfer_jira_ticket(
        issue_key="SWCM-889",
        to_account_id="712020:50e16c11-d517-4909-8d30-b92693808eaa",
        handover_note="Assigning to Aadya for creative checks",
        transferred_by="Dnyanesh Khawas",
    )
    assert res_aadya["ok"] is True
    assert res_aadya["virtual_assignment"] is True
    assert res_aadya["assignee_name"] in ("Aadya", "Aadya Trivedi")
    clear_operational_assignment("SWCM-888")
    clear_operational_assignment("SWCM-889")


def test_transfer_authorization_policy(provision_user):
    """Verify only authenticated Tata Jira managers (and admin) can transfer tickets."""
    from fastapi.testclient import TestClient

    from api import app

    client = TestClient(app)
    payload = {"issue_key": "SWCM-1", "to_account_id": "712020:test"}
    _, intern_headers = provision_user(tenant="tata", role="operator", email="intern@attributics.com")
    _, manager_headers = provision_user(tenant="tata", role="operator", email="dnyanesh.khawas@attributics.com")
    _, other_tenant_headers = provision_user(tenant="bajaj", role="operator", email="neel.shah@attributics.com")

    with patch("work_manager.transfer_jira_ticket") as mock_transfer:
        resp_missing = client.post("/api/work-management/transfer", json=payload)
        assert resp_missing.status_code == 401

        resp_other_tenant = client.post(
            "/api/work-management/transfer", json=payload, headers=other_tenant_headers
        )
        assert resp_other_tenant.status_code == 403

        # 1. Unauthorized operator (e.g. intern or other user)
        resp_unauth = client.post(
            "/api/work-management/transfer", json=payload, headers=intern_headers
        )
        assert resp_unauth.status_code == 403
        assert "Permission Denied" in resp_unauth.json()["detail"]
        mock_transfer.assert_not_called()

        # 2. Authorized manager (e.g. Dnyanesh Khawas)
        mock_transfer.return_value = {"ok": True, "success": True}
        resp_auth = client.post(
            "/api/work-management/transfer",
            json={"issue_key": "SWCM-1", "to_account_id": "712020:c8914cff-1299-4ad7-989b-e38859cbcdbf"},
            headers=manager_headers,
        )
        assert resp_auth.status_code == 200
def test_configurable_work_allocation_and_rebalancing(provision_user):
    """Verify team members can be included/excluded from work allocation, and rebalancing respects it."""
    from fastapi.testclient import TestClient
    from api import app
    from work_manager import (
        get_all_allocation_settings,
        set_member_allocation_status,
        fetch_assignable_jira_users,
        ai_rebalance_workload,
        _rule_based_rebalance,
    )

    _, headers = provision_user(tenant="tata", role="admin", email="neel.shah@attributics.com")

    try:
        # 1. Default state: all members active
        settings = get_all_allocation_settings()
        assert settings.get("Dnyanesh Khawas") is True
        assert settings.get("Neel Shah") is True

        # 2. Exclude Dnyanesh Khawas from allocation
        res = set_member_allocation_status("Dnyanesh Khawas", False)
        assert res["ok"] is True
        assert res["is_active_for_allocation"] is False

        # Verify fetch_assignable_jira_users reflects this
        users = fetch_assignable_jira_users()
        dnyanesh = next(u for u in users if u.name == "Dnyanesh Khawas")
        neel = next(u for u in users if u.name == "Neel Shah")
        assert dnyanesh.is_active_for_allocation is False
        assert neel.is_active_for_allocation is True

        # 3. Rule-based rebalancing test: Dnyanesh must NOT be a recipient
        mock_pending = [
            {"key": "TCN-1", "summary": "Task 1", "assignee_name": "Neel Shah", "status_category": "PENDING"},
            {"key": "TCN-2", "summary": "Task 2", "assignee_name": "Neel Shah", "status_category": "PENDING"},
        ]
        mock_assignees = [u.to_dict() for u in users]
        rebal_res = _rule_based_rebalance(
            context_prompt="Neel is overloaded, rebalance tickets",
            pending_items=mock_pending,
            assignees=mock_assignees,
            auto_execute=False,
            operator_name="Test Operator",
        )
        assert rebal_res["ok"] is True
        for prop in rebal_res["proposals"]:
            # Excluded member Dnyanesh must NEVER be chosen as target assignee!
            assert prop["target_assignee"] != "Dnyanesh Khawas"

        # 4. Test API endpoints
        client = TestClient(app, headers=headers)

        # GET allocation settings
        get_res = client.get("/api/work-management/allocation-settings")
        assert get_res.status_code == 200
        data = get_res.json()
        assert data["ok"] is True
        assert data["settings"]["Dnyanesh Khawas"] is False

        # POST allocation settings: reactivate Dnyanesh
        post_res = client.post(
            "/api/work-management/allocation-settings",
            json={"member_name": "Dnyanesh Khawas", "is_active": True},
        )
        assert post_res.status_code == 200
        post_data = post_res.json()
        assert post_data["ok"] is True
        assert post_data["is_active_for_allocation"] is True

        # Verify reactivated
        updated_users = fetch_assignable_jira_users()
        dnyanesh_reactivated = next(u for u in updated_users if u.name == "Dnyanesh Khawas")
        assert dnyanesh_reactivated.is_active_for_allocation is True

    finally:
        set_member_allocation_status("Dnyanesh Khawas", True)
def test_jira_reassignment_confirmation_sync_or_skip():
    """Verify users can choose to confirm Jira update (sync_to_jira=True) or skip Jira update (sync_to_jira=False)."""
    from unittest.mock import patch, MagicMock
    from work_manager import (
        transfer_jira_ticket,
        bulk_transfer_jira_tickets,
        get_all_operational_assignments,
        clear_operational_assignment,
    )

    try:
        # 1. Skip Jira update (sync_to_jira=False) even for a user with a Jira seat (Neel Shah)
        with patch("work_manager.requests.put") as mock_put:
            res_skip = transfer_jira_ticket(
                issue_key="SWCM-555",
                to_account_id="712020:fae946f9-8472-455a-9d27-6d773ecfb48d",
                handover_note="Internal handover only",
                transferred_by="Mrunalini Gawande",
                sync_to_jira=False,
            )
            assert res_skip["ok"] is True
            assert res_skip["sync_to_jira"] is False
            assert res_skip["jira_updated"] is False
            assert res_skip["virtual_assignment"] is True
            assert res_skip["assignee_name"] == "Neel Shah"
            assert not mock_put.called

            # Verify saved internally in operational_assignments
            ops = get_all_operational_assignments()
            assert "SWCM-555" in ops
            assert ops["SWCM-555"]["operational_assignee"] == "Neel Shah"

        # 2. Confirm Jira update (sync_to_jira=True) for Neel Shah
        with (
            patch("work_manager.get_jira_credentials", return_value=("https://example.atlassian.net", "u", "t")),
            patch("work_manager.get_jira_auth_headers", return_value={"Authorization": "Basic xxx"}),
            patch("work_manager.requests.put") as mock_put,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 204
            mock_put.return_value = mock_resp

            res_confirm = transfer_jira_ticket(
                issue_key="SWCM-555",
                to_account_id="712020:fae946f9-8472-455a-9d27-6d773ecfb48d",
                handover_note="Confirmed Jira transfer",
                transferred_by="Mrunalini Gawande",
                sync_to_jira=True,
            )
            assert res_confirm["ok"] is True
            assert res_confirm["sync_to_jira"] is True
            assert res_confirm["jira_updated"] is True
            assert res_confirm["virtual_assignment"] is False
            assert mock_put.called

            # Verify local virtual assignment was cleared since it synced to Jira
            ops_after = get_all_operational_assignments()
            assert "SWCM-555" not in ops_after

        # 3. Bulk transfer with sync_to_jira=False
        with patch("work_manager.requests.put") as mock_put:
            res_bulk = bulk_transfer_jira_tickets(
                issue_keys=["SWCM-556", "SWCM-557"],
                to_account_id="712020:fae946f9-8472-455a-9d27-6d773ecfb48d",
                handover_note="Bulk internal assignment",
                transferred_by="Dnyanesh Khawas",
                sync_to_jira=False,
            )
            assert res_bulk["ok"] is True
            assert res_bulk["sync_to_jira"] is False
            assert res_bulk["jira_updated"] is False
            assert res_bulk["transferred_count"] == 2
            assert not mock_put.called

    finally:
        clear_operational_assignment("SWCM-555")
        clear_operational_assignment("SWCM-556")
        clear_operational_assignment("SWCM-557")
