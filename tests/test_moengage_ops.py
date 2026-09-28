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


def test_screenshot_exact_channel_reconciliation():
    """Verify exact match to user's MoEngage screenshot counts: SMS 15, WA 13, RCS 4, Push 3, Email 2."""
    import csv
    import tempfile

    from moengage_ops_client import parse_moengage_export_file

    screenshot_campaigns = [
        *[
            {
                "Channel": "SMS",
                "Campaign Name": f"TCLMOE_SMS_{i}_15Sept26",
                "Created By": "soham.das@attributics.com",
                "Date": "2026-09-15",
            }
            for i in range(1, 16)
        ],
        *[
            {
                "Channel": "WhatsApp",
                "Campaign Name": f"TCLMOE_WA_{i}_18Sept26",
                "Created By": "mrunalini.gawande@attributics.com",
                "Date": "2026-09-18",
            }
            for i in range(1, 14)
        ],
        *[
            {
                "Channel": "RCS",
                "Campaign Name": f"TCLMOE_RCS_{i}_15Sept26",
                "Created By": "neel.shah@attributics.com",
                "Date": "2026-09-15",
            }
            for i in range(1, 5)
        ],
        *[
            {
                "Channel": "Push",
                "Campaign Name": f"TCLMOE_PN_{i}_15Sept26",
                "Created By": "neel.shah@attributics.com",
                "Date": "2026-09-15",
            }
            for i in range(1, 4)
        ],
        *[
            {
                "Channel": "Email",
                "Campaign Name": f"TCLMOE_Email_{i}_15Sept26",
                "Created By": "soham.das@attributics.com",
                "Date": "2026-09-15",
            }
            for i in range(1, 3)
        ],
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=["Channel", "Campaign Name", "Created By", "Date"])
        writer.writeheader()
        writer.writerows(screenshot_campaigns)
        tmp_path = tmp.name

    records = parse_moengage_export_file(tmp_path, default_vertical="TCL")
    metrics = compute_ops_dashboard_metrics(records, mode="custom", custom_start="2026-09-14", custom_end="2026-09-20")
    chans = metrics["account_overview"]["channel_breakdown"]

    assert len(records) == 37
    assert chans["SMS"] == 15
    assert chans["WhatsApp"] == 13
    assert chans["RCS"] == 4
    assert chans["Push"] == 3
    assert chans["Email"] == 2


def test_parse_moengage_export_zip_with_multiple_csvs():
    """Verify parse_moengage_export_file extracts and parses all CSVs in a MoEngage export ZIP."""
    import csv
    import io
    import tempfile
    import zipfile

    from moengage_ops_client import parse_moengage_export_file

    tcl_campaigns = [
        {"Channel": "WhatsApp", "Campaign Name": "TCLMOE_WA_Promo_1", "Created By": "soham.das@attributics.com", "Date": "2026-09-22"},
        {"Channel": "SMS", "Campaign Name": "TCLMOE_SMS_Alert_1", "Created By": "neel.shah@attributics.com", "Date": "2026-09-23"},
    ]
    wealth_campaigns = [
        {"Channel": "Email", "Campaign Name": "Wealth_AUM_Email_1", "Created By": "mrunalini.gawande@attributics.com", "Date": "2026-09-24"},
        {"Channel": "RCS", "Campaign Name": "Wealth_AUM_RCS_1", "Created By": "mrunalini.gawande@attributics.com", "Date": "2026-09-24"},
    ]
    flow_nodes = [
        {"Flow Name": "Onboarding_Journey_V1", "Node Name": "Welcome_WhatsApp_Node", "Channel": "WhatsApp", "Created By": "neel.shah@attributics.com", "Date": "2026-09-25"},
        {"Flow Name": "Onboarding_Journey_V1", "Node Name": "Reminder_SMS_Node", "Channel": "SMS", "Created By": "soham.das@attributics.com", "Date": "2026-09-26"},
    ]

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as zip_tmp:
        zip_path = zip_tmp.name

    with zipfile.ZipFile(zip_path, "w") as zf:
        # 1. TCL CSV
        buf_tcl = io.StringIO()
        w = csv.DictWriter(buf_tcl, fieldnames=["Channel", "Campaign Name", "Created By", "Date"])
        w.writeheader()
        w.writerows(tcl_campaigns)
        zf.writestr("TCL_Campaigns.csv", buf_tcl.getvalue())

        # 2. Wealth CSV
        buf_wealth = io.StringIO()
        w = csv.DictWriter(buf_wealth, fieldnames=["Channel", "Campaign Name", "Created By", "Date"])
        w.writeheader()
        w.writerows(wealth_campaigns)
        zf.writestr("reports/Wealth_Campaigns.csv", buf_wealth.getvalue())

        # 3. Flow Nodes CSV
        buf_nodes = io.StringIO()
        w = csv.DictWriter(buf_nodes, fieldnames=["Flow Name", "Node Name", "Channel", "Created By", "Date"])
        w.writeheader()
        w.writerows(flow_nodes)
        zf.writestr("flows/Flow_Nodes.csv", buf_nodes.getvalue())

    try:
        records = parse_moengage_export_file(zip_path, default_vertical="TCL")
        assert len(records) == 6

        # Verify types
        campaigns = [r for r in records if r.type == "Campaign"]
        nodes = [r for r in records if r.type == "Node"]
        assert len(campaigns) == 4
        assert len(nodes) == 2

        # Verify verticals inferred from filenames / campaign names
        tcl_records = [r for r in records if r.vertical == "TCL"]
        wealth_records = [r for r in records if r.vertical == "Wealth"]
        assert len(tcl_records) == 4  # 2 campaigns + 2 flow nodes defaulted to TCL
        assert len(wealth_records) == 2  # 2 wealth campaigns

        # Verify channels
        channels_found = {r.channel for r in records}
        assert channels_found == {"WhatsApp", "SMS", "Email", "RCS"}

        # Verify metric calculation
        metrics = compute_ops_dashboard_metrics(records, mode="custom", custom_start="2026-09-20", custom_end="2026-09-27")
        overview = metrics["account_overview"]
        assert overview["total_campaigns"] == 4
        assert overview["total_flow_nodes"] == 2
        assert overview["total_touchpoints"] == 6
    finally:
        Path(zip_path).unlink(missing_ok=True)


def test_parse_moengage_export_zip_skips_mac_metadata_and_hidden_files():
    """Verify zip parsing skips __MACOSX, .DS_Store, and non-CSV files."""
    import csv
    import io
    import tempfile
    import zipfile

    from moengage_ops_client import parse_moengage_export_file

    valid_data = [
        {"Channel": "Push", "Campaign Name": "Services_Loan_PN", "Created By": "soham.das@attributics.com", "Date": "2026-09-20"},
    ]

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as zip_tmp:
        zip_path = zip_tmp.name

    with zipfile.ZipFile(zip_path, "w") as zf:
        # Resource fork and hidden files
        zf.writestr("__MACOSX/._Services.csv", b"junk resource fork")
        zf.writestr(".DS_Store", b"junk ds_store")
        zf.writestr("README.txt", "Some read me text")

        # Valid CSV
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["Channel", "Campaign Name", "Created By", "Date"])
        w.writeheader()
        w.writerows(valid_data)
        zf.writestr("exports/Services.csv", buf.getvalue())

    try:
        records = parse_moengage_export_file(zip_path, default_vertical="Services")
        assert len(records) == 1
        assert records[0].name == "Services_Loan_PN"
        assert records[0].channel == "Push"
        assert records[0].vertical == "Services"
    finally:
        Path(zip_path).unlink(missing_ok=True)


def test_ingest_moengage_export_file_zip():
    """Verify ingest_moengage_export_file processes zip archive and updates cache/Excel."""
    import csv
    import io
    import tempfile
    import zipfile

    from moengage_ops_client import ingest_moengage_export_file

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as zip_tmp:
        zip_path = zip_tmp.name

    with zipfile.ZipFile(zip_path, "w") as zf:
        buf1 = io.StringIO()
        w1 = csv.DictWriter(buf1, fieldnames=["Channel", "Campaign Name", "Created By", "Date"])
        w1.writeheader()
        w1.writerow({"Channel": "SMS", "Campaign Name": "Zip_Ingest_SMS_1", "Created By": "neel.shah@attributics.com", "Date": "2026-09-21"})
        zf.writestr("part_1.csv", buf1.getvalue())

        buf2 = io.StringIO()
        w2 = csv.DictWriter(buf2, fieldnames=["Channel", "Campaign Name", "Created By", "Date"])
        w2.writeheader()
        w2.writerow({"Channel": "WhatsApp", "Campaign Name": "Zip_Ingest_WA_2", "Created By": "neel.shah@attributics.com", "Date": "2026-09-22"})
        zf.writestr("part_2.csv", buf2.getvalue())

    try:
        res = ingest_moengage_export_file(zip_path, default_vertical="TCL")
        assert res["ok"] is True
        assert res["new_records_parsed"] >= 2
        assert res["files_parsed"] == 2
        assert res["campaigns_count"] >= 2
    finally:
        Path(zip_path).unlink(missing_ok=True)


def test_upload_moengage_export_endpoint_zip():
    """Verify POST /api/moengage/ops/upload-export accepts ZIP file and returns accurate metrics."""
    import csv
    import io
    import tempfile
    import zipfile

    from fastapi.testclient import TestClient

    from api import app, get_current_user

    app.dependency_overrides[get_current_user] = lambda: {
        "email": "tester@attributics.com",
        "name": "Tester",
        "tenant_id": "all",
        "role": "superadmin",
    }
    client = TestClient(app)

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as zip_tmp:
        zip_path = zip_tmp.name

    with zipfile.ZipFile(zip_path, "w") as zf:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["Channel", "Campaign Name", "Created By", "Date"])
        w.writeheader()
        w.writerow({
            "Channel": "RCS",
            "Campaign Name": "TCLMOE_Endpoint_RCS_1",
            "Created By": "neel.shah@attributics.com",
            "Date": "2026-09-22",
        })
        zf.writestr("TCL_RCS.csv", buf.getvalue())

    try:
        with open(zip_path, "rb") as f:
            resp = client.post(
                "/api/moengage/ops/upload-export?mode=custom&custom_start=2026-09-20&custom_end=2026-09-27",
                files={"file": ("moengage_export.zip", f, "application/zip")},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["result"]["files_parsed"] >= 1
        assert data["result"]["new_records_parsed"] >= 1
        assert "metrics" in data
        assert data["metrics"]["account_overview"]["total_campaigns"] >= 1
    finally:
        app.dependency_overrides.clear()
        Path(zip_path).unlink(missing_ok=True)
