"""
Unit and integration tests for MoEngage Operations Dashboard & Scoping Engine.
Tests:
1. Test campaign filtering (is_test logic).
2. Work week Monday calculation.
3. Vertical inference and channel normalization.
4. In-scope Attributics author determination.
5. Executive overview and vertical breakdown aggregation.
6. Live Excel export into Master Data template.
7. Live Moneyfy API sync verification.
"""

from datetime import date
from pathlib import Path

from moengage_ops_client import (
    MoEngageWorkspaceConfig,
    NormalizedOpsRecord,
    _compute_week_start,
    _infer_vertical_from_name,
    _is_test_campaign,
    _normalize_channel_name,
    compute_ops_dashboard_metrics,
    export_ops_dashboard_excel,
    fetch_workspace_campaigns,
    fetch_workspace_flows,
)


def test_is_test_campaign_filtering():
    """Verify test, copy, and duplicate keywords are flagged as test campaigns."""
    assert _is_test_campaign("Test_PL_OD Campaign") is True
    assert _is_test_campaign("Campaign_copy_2") is True
    assert _is_test_campaign("Duplicate_Banner_Ad") is True
    assert _is_test_campaign("Moneyfy_Toppicks_engagement_Morning_Notification") is False


def test_compute_week_start():
    """Verify work-week start always computes the preceding Monday."""
    # 2026-09-21 is a Monday
    assert _compute_week_start(date(2026, 9, 21)) == "2026-09-21"
    # 2026-09-23 is a Wednesday -> Monday is 2026-09-21
    assert _compute_week_start(date(2026, 9, 23)) == "2026-09-21"
    # 2026-09-27 is a Sunday -> Monday is 2026-09-21
    assert _compute_week_start(date(2026, 9, 27)) == "2026-09-21"


def test_infer_vertical_from_name():
    """Verify campaign naming conventions accurately resolve to target business vertical."""
    assert _infer_vertical_from_name("TCLMOE_PAPL_TOP_UP_AB_SMS2_02Aug26", "Default") == "TCL"
    assert _infer_vertical_from_name("TCHFLService_Communication", "Default") == "TCHFL"
    assert _infer_vertical_from_name("TCLService_HR_WhatsApp", "Default") == "Services"
    assert _infer_vertical_from_name("2786_Wealth_AUM_SMS_Activity", "Default") == "Wealth"
    assert _infer_vertical_from_name("Moneyfy_Toppicks_Notification", "Default") == "Moneyfy"


def test_normalize_channel_name():
    """Verify raw MoEngage channel strings map to canonical dashboard channels."""
    assert _normalize_channel_name("PUSH") == "Push"
    assert _normalize_channel_name("SMS") == "SMS"
    assert _normalize_channel_name("EMAIL") == "Email"
    assert _normalize_channel_name("WHATSAPP") == "WhatsApp"
    assert _normalize_channel_name("RCS") == "RCS"


def test_compute_ops_dashboard_metrics():
    """Verify aggregation matches the exact Excel COUNTIFS formula rules."""
    records = [
        # In-scope Moneyfy campaign (Push)
        NormalizedOpsRecord(
            vertical="Moneyfy",
            type="Campaign",
            channel="Push",
            date="2026-08-25",
            week_start="2026-08-24",
            month="2026-08",
            in_scope=True,
            is_test=False,
            name="Moneyfy_Push_1",
            created_by="neel.shah@attributics.com",
            source="Moneyfy / Campaign",
        ),
        # In-scope Moneyfy campaign (SMS)
        NormalizedOpsRecord(
            vertical="Moneyfy",
            type="Campaign",
            channel="SMS",
            date="2026-08-26",
            week_start="2026-08-24",
            month="2026-08",
            in_scope=True,
            is_test=False,
            name="Moneyfy_SMS_1",
            created_by="neel.shah@attributics.com",
            source="Moneyfy / Campaign",
        ),
        # Out-of-scope test campaign (should not count)
        NormalizedOpsRecord(
            vertical="Moneyfy",
            type="Campaign",
            channel="Push",
            date="2026-08-27",
            week_start="2026-08-24",
            month="2026-08",
            in_scope=False,
            is_test=True,
            name="Test_Moneyfy_Push",
            created_by="neel.shah@attributics.com",
            source="Moneyfy / Campaign",
        ),
        # Live Collections Flow (Active)
        NormalizedOpsRecord(
            vertical="Collections",
            type="Flow",
            channel="",
            date="2024-05-29",
            week_start="2024-05-27",
            month="2024-05",
            in_scope=True,
            is_test=False,
            name="HFL_W-off_Stamped",
            created_by="admin",
            source="Collections / Flow",
            status="Active",
        ),
    ]

    metrics = compute_ops_dashboard_metrics(
        records,
        mode="custom",
        custom_start="2026-08-01",
        custom_end="2026-08-31",
    )

    overview = metrics["account_overview"]
    assert overview["total_campaigns"] == 2
    assert overview["channel_breakdown"]["Push"] == 1
    assert overview["channel_breakdown"]["SMS"] == 1

    # Collections is reported separately, not in account overview total
    v_breakdown = metrics["vertical_breakdown"]
    assert v_breakdown["Moneyfy"]["campaigns_total"] == 2
    assert v_breakdown["Collections"]["flows_total"] == 1
    assert v_breakdown["Collections"]["in_account_total"] is False


def test_export_ops_dashboard_excel():
    """Verify live export into Master Data sheet of MoEngage_Ops_Dashboard.xlsx."""
    records = [
        NormalizedOpsRecord(
            vertical="Moneyfy",
            type="Campaign",
            channel="Push",
            date="2026-08-25",
            week_start="2026-08-24",
            month="2026-08",
            in_scope=True,
            is_test=False,
            name="Test_Export_Campaign",
            created_by="neel.shah@attributics.com",
            source="Moneyfy / Campaign",
        )
    ]

    out_file = export_ops_dashboard_excel(
        records=records,
        template_path="MoEngage_Ops_Dashboard.xlsx",
        output_path="test_moengage_ops_output.xlsx",
    )

    p = Path(out_file)
    assert p.exists()
    assert p.stat().st_size > 5000
    p.unlink()


def test_live_moneyfy_workspace_sync():
    """Verify live API connection and data extraction from Moneyfy workspace."""
    cfg = MoEngageWorkspaceConfig(
        workspace_name="Moneyfy",
        vertical="Moneyfy",
        workspace_id="PLBRDCVUS0YE8ME3E8XSHV5D",
        api_key="F9ED1AC8BB3449E8B6D94E5C",
        data_center="03",
        is_active=True,
    )

    camps = fetch_workspace_campaigns(cfg, max_pages=2)
    assert len(camps) > 0
    # Confirm Attributics creators are present
    assert any("@attributics.com" in c.created_by.lower() for c in camps)

    flows = fetch_workspace_flows(cfg, max_pages=1)
    assert len(flows) > 0
