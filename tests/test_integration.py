#!/usr/bin/env python3
"""
Integration smoke test - verifies Karix API connection and status checks.

Uses official WABA_AUTH_TOKEN static credentials with optional portal fallback.
"""

import json
import logging
import os
import sys

# Optionally load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # .env loading is optional; env vars can be set directly

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from models import ApprovalStatus
from submission_client import check_status


def test_check_status():
    """Verify check_status can reach the API and find a known template.

    Picks the first APPROVED template from the live WABA list as the fixture
    so the test stays stable as templates churn on the Karix side.
    """
    from submission_client import fetch_template_list

    templates, err = fetch_template_list("bajaj")
    assert err is None, f"fetch_template_list failed: {err}"
    assert templates, "WABA returned no templates — cannot select fixture"

    fixture = next(
        (t for t in templates if (t.get("template_create_status") or t.get("status")) == "APPROVED"),
        None,
    )
    assert fixture is not None, "No APPROVED template found on WABA — cannot select fixture"

    known_sno = str(fixture["sno"])
    known_template_name = fixture["template_name"]

    print(f"\n--- Testing check_status(provider_ref_id={known_sno!r}) ---\n")

    approval_status, reason, raw = check_status(known_sno)

    print(f"  Approval status : {approval_status.value}")
    print(f"  Status reason   : {reason}")
    print(f"  Template name   : {raw.get('template_name', 'N/A')}")
    print(f"  sno             : {raw.get('sno', 'N/A')}")
    print()

    # Assertions
    assert approval_status != ApprovalStatus.UNKNOWN, (
        f"Got UNKNOWN — likely an auth/transport error. Raw: {json.dumps(raw, indent=2, default=str)[:1000]}"
    )
    assert raw.get("template_name") == known_template_name, (
        f"Expected template_name={known_template_name!r}, got {raw.get('template_name')!r}"
    )

    print(f"✓ check_status returned: {approval_status.value}")
    print(f"✓ Template name: {raw.get('template_name')}")
    print(f"✓ Status reason: {reason}")


def test_list_all_templates():
    """
    Verify fetch_template_list can fetch live templates from the WABA.
    """
    from submission_client import fetch_template_list

    print("\n--- Listing all templates (summary via fetch_template_list) ---\n")
    templates, err = fetch_template_list("bajaj")
    print(f"  Total templates returned: {len(templates)}, error: {err}")

    for t in templates[:10]:
        print(
            f"  sno={t.get('sno')}  fb_id={t.get('fb_template_id')}  name={t.get('template_name')!r:30s}  "
            f"status={t.get('template_create_status') or t.get('status')}"
        )
    assert isinstance(templates, list), "Expected templates to be a list"
    if templates:
        assert len(templates) > 0


def test_duplicate_submission_skipping():
    """
    Verify that when skip_duplicates is enabled, templates already active on WABA
    are filtered into DUPLICATE status without hitting Karix/Meta create endpoints.
    """
    import io
    import tempfile
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    import api
    from models import SubmissionStatus

    client = TestClient(api.app)
    # Sign up/in as tata user
    email = "dupe_test@attributics.com"
    client.post("/api/auth/signup", json={"email": email, "password": "Test@123", "name": "Dupe Tester", "tenant_id": "tata"})
    r = client.post("/api/auth/login", json={"email": email, "password": "Test@123"})
    token = r.json().get("token") or r.json().get("access_token")
    H = {"Authorization": f"Bearer {token}"}

    # Mock live templates to contain 'existing_template_1'
    mock_live = [
        {"template_name": "existing_template_1", "template_create_status": "APPROVED", "fb_template_id": "999888"}
    ]

    csv_content = (
        "template_name,template_category,header_type,header_text,body_text\n"
        "existing_template_1,MARKETING,TEXT,Header,Hello {{1}}\n"
        "brand_new_template_2,MARKETING,TEXT,Header,Hello {{1}}\n"
    )

    def fake_run(raw_list, log_path, **kwargs):
        from models import SubmissionResult, SubmissionStatus
        from tracker import log_result
        for item in raw_list:
            res = SubmissionResult(
                source_ref=item.get("source_ref", item.get("template_name", "")),
                template_name=item.get("template_name", ""),
                status=SubmissionStatus.SUBMITTED,
                provider_ref_id="fake_123",
            )
            log_result(res, log_path)

    with patch("api.fetch_whatsapp_templates", return_value=mock_live), patch("api.run", side_effect=fake_run) as mock_run:
        r = client.post(
            "/api/submit?account=tchfl&channel=whatsapp&skip_duplicates=true",
            files={"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            headers=H,
        )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    results = data.get("results", [])
    assert len(results) == 2, f"Expected 2 results, got {len(results)}"

    # Check duplicate entry was safely skipped
    dupe_row = next((x for x in results if x.get("template_name") == "existing_template_1"), None)
    assert dupe_row is not None
    assert dupe_row.get("status") == SubmissionStatus.DUPLICATE.value
    assert "already active on waba" in dupe_row.get("error", "").lower()

    # Verify run was only invoked with the net-new template
    if mock_run.called:
        submitted_raw = mock_run.call_args[0][0]
        assert len(submitted_raw) == 1
        assert submitted_raw[0]["template_name"] == "brand_new_template_2"

    print("✓ test_duplicate_submission_skipping passed!")


def test_smart_account_routing_detection():
    """
    Verify that detect_spreadsheet_account correctly identifies target sub-accounts
    from header tags, prefixes, and keywords (Meta Memory).
    """
    from loader import TemplateComponent, TemplateSubmission, detect_spreadsheet_account

    # 1. HLTATA / hfl_ prefix -> TCHFL
    tchfl_subs = [
        TemplateSubmission(
            client="tata",
            channel="whatsapp",
            template_name="hfl_loan_approved_2508",
            language="en",
            category="MARKETING",
            waba_id="",
            components=[TemplateComponent(type="HEADER", text="HLTATA")],
            source_ref="row1",
        )
    ]
    res = detect_spreadsheet_account(tchfl_subs, current_account="tcl_promo")
    assert res["detected_account_id"] == "tchfl"
    assert res["is_mismatch"] is True
    assert "TCHFL" in res["detected_account_name"]

    # 2. PLTATA / pl_ prefix -> TCL Promo
    promo_subs = [
        TemplateSubmission(
            client="tata",
            channel="whatsapp",
            template_name="pl_instant_offer_01",
            language="en",
            category="MARKETING",
            waba_id="",
            components=[TemplateComponent(type="HEADER", text="PLTATA")],
            source_ref="row1",
        )
    ]
    res2 = detect_spreadsheet_account(promo_subs, current_account="tcl_promo")
    assert res2["detected_account_id"] == "tcl_promo"
    assert res2["is_mismatch"] is False

    # 3. MONEYFY keywords -> Moneyfy
    mf_subs = [
        TemplateSubmission(
            client="tata",
            channel="whatsapp",
            template_name="mf_sip_growth_scheme",
            language="en",
            category="MARKETING",
            waba_id="",
            components=[TemplateComponent(type="BODY", text="Start your Moneyfy Mutual Fund SIP today.")],
            source_ref="row1",
        )
    ]
    res3 = detect_spreadsheet_account(mf_subs, current_account="tchfl")
    assert res3["detected_account_id"] == "moneyfy"
    assert res3["is_mismatch"] is True

    print("✓ test_smart_account_routing_detection passed!")


def test_preflight_technical_compliance_validator():
    """
    Verify validate_meta_technical_compliance detects word ratio limits (Meta Error 2388293),
    length violations, and formatting tags (Semantic Memory).
    """
    from grammar_checker import validate_meta_technical_compliance

    # 1. Word-to-variable ratio too low (e.g. 'Hello {{1}}' -> 1 word, 1 var -> ratio 1:1 < 2.5)
    warns = validate_meta_technical_compliance(body_text="Hello {{1}}")
    assert any(w["type"] == "META_WORD_RATIO" for w in warns)
    assert any("2388293" in w["issue"] for w in warns)

    # 2. Compliant ratio (e.g. 'Dear customer, your personal loan account balance is {{1}}.')
    good_warns = validate_meta_technical_compliance(
        body_text="Dear valued customer, your requested loan application status is currently {{1}}."
    )
    assert not any(w["type"] == "META_WORD_RATIO" for w in good_warns)

    # 3. Header text length limit (> 60 chars)
    h_warns = validate_meta_technical_compliance(
        header_text="This is an excessively long header text that exceeds sixty characters easily",
        header_format="TEXT",
    )
    assert any(w["type"] == "HEADER_LENGTH_LIMIT" for w in h_warns)

    # 4. Button length limit (> 25 chars) and space in URL
    b_warns = validate_meta_technical_compliance(
        buttons=[
            {"type": "URL", "text": "This Button Text Is Far Too Long For Meta", "url": "https://example.com/ my path"}
        ]
    )
    assert any(w["type"] == "BUTTON_LENGTH_LIMIT" for w in b_warns)
    assert any(w["type"] == "BUTTON_URL_INVALID" for w in b_warns)

    print("✓ test_preflight_technical_compliance_validator passed!")


def test_adaptive_rate_limiting_and_governor():
    """
    Verify KarixHealthGovernor tracks latency and throttles concurrency during high load / 429s (Working Memory).
    """
    from submission_client import KarixHealthGovernor

    gov = KarixHealthGovernor(window_size=10)

    # 1. Optimal state (low latency, zero errors)
    for _ in range(5):
        gov.record_request(duration_sec=0.4, status_code=200)
    stats = gov.get_health_stats()
    assert stats["status"] == "optimal"
    assert stats["optimal_workers"] >= 6
    assert stats["pacing_delay_sec"] == 0.0

    # 2. Degraded state (high latency > 3.0s)
    for _ in range(8):
        gov.record_request(duration_sec=3.5, status_code=200)
    degraded_stats = gov.get_health_stats()
    assert degraded_stats["status"] in ("moderate", "degraded")
    assert degraded_stats["optimal_workers"] <= 4

    # 3. Throttled state on HTTP 429
    gov.record_request(duration_sec=1.0, status_code=429)
    throttled_stats = gov.get_health_stats()
    assert throttled_stats["status"] == "throttled"
    assert throttled_stats["optimal_workers"] <= 2
    assert throttled_stats["pacing_delay_sec"] >= 1.0

    print("✓ test_adaptive_rate_limiting_and_governor passed!")


def test_predictive_category_approval_polling():
    """
    Verify classify_template_category_sla and get_pending_templates_sla_insights
    correctly estimate review SLAs by template category (Procedural Memory).
    """
    from runner import classify_template_category_sla, get_pending_templates_sla_insights

    # 1. UTILITY template classification
    util_tier, util_sla = classify_template_category_sla({
        "category": "UTILITY",
        "components": [{"type": "BODY", "text": "Your account statement is ready."}],
    })
    assert util_tier == "UTILITY"
    assert util_sla["avg_approval_sec"] <= 300

    # 2. MARKETING Media template classification
    media_tier, media_sla = classify_template_category_sla({
        "category": "MARKETING",
        "components": [
            {"type": "HEADER", "format": "IMAGE"},
            {"type": "BODY", "text": "Check out our special offer."},
        ],
    })
    assert media_tier == "MARKETING_MEDIA"
    assert media_sla["avg_approval_sec"] >= 1800

    # 3. Insights calculation on empty/mock pending
    insights = get_pending_templates_sla_insights(client="bajaj")
    assert "next_recommended_poll_sec" in insights
    assert isinstance(insights["categories"], dict)

    print("✓ test_predictive_category_approval_polling passed!")

def test_duplicate_error_reconciliation_to_approved():
    """
    Verify that when Karix or Meta returns 'Template Already Exist.' or
    'There is already English content for this template', the client recognizes
    it as a duplicate, fetches the live status from Karix, and returns
    SubmissionStatus.DUPLICATE with the true ApprovalStatus (e.g. APPROVED)
    and fb_template_id instead of wrongly reporting FAILED.
    """
    from unittest.mock import MagicMock, patch
    from models import ApprovalStatus, SubmissionStatus, TemplateSubmission
    from submission_client import _evaluate_portal_create_response

    sub = TemplateSubmission(
        client="tchfl",
        channel="whatsapp",
        template_name="hfl_patp_fcst_030926",
        language="en_US",
        category="MARKETING",
        waba_id="123456",
        components=[],
        source_ref="test_ref_1",
    )

    # Case 1: Karix returns {"Failed": "Template Already Exist."}
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    portal_data_exist = {"Failed": "Template Already Exist."}

    with patch("submission_client.check_status") as mock_check:
        mock_check.return_value = (
            ApprovalStatus.APPROVED,
            None,
            {"fb_template_id": "2323001988540102", "template_name": "hfl_patp_fcst_030926"},
        )
        res = _evaluate_portal_create_response(mock_resp, portal_data_exist, sub, "tchfl", 0)

    assert res.status == SubmissionStatus.DUPLICATE
    assert res.approval_status == ApprovalStatus.APPROVED
    assert res.provider_ref_id == "2323001988540102"
    assert "already active on waba (approved)" in res.error.lower()

    # Case 2: Meta returns "There is already English content for this template. You can create a new template and try again."
    portal_data_meta_dupe = {
        "status": "failure",
        "reason": "There is already English content for this template. You can create a new template and try again.",
    }
    with patch("submission_client.check_status") as mock_check:
        mock_check.return_value = (
            ApprovalStatus.APPROVED,
            None,
            {"fb_template_id": "1009521115473587", "template_name": "hfl_patp_qcst_030926"},
        )
        res2 = _evaluate_portal_create_response(mock_resp, portal_data_meta_dupe, sub, "tchfl", 0)

    assert res2.status == SubmissionStatus.DUPLICATE
    assert res2.approval_status == ApprovalStatus.APPROVED
    assert res2.provider_ref_id == "1009521115473587"
    assert "already active on waba" in res2.error.lower()
    print("✓ test_duplicate_error_reconciliation_to_approved passed!")


def test_in_batch_duplicate_skipping_and_row_order():
    """
    Verify that duplicate template names within the same uploaded batch/spreadsheet
    are deduplicated in-batch without sending duplicate requests to Karix/Meta,
    and that results maintain exact row order matching the input spreadsheet.
    """
    import io
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    import api
    from models import SubmissionResult, SubmissionStatus

    client = TestClient(api.app)
    email = "batch_dupe_test@attributics.com"
    client.post("/api/auth/signup", json={"email": email, "password": "Test@123", "name": "Batch Tester", "tenant_id": "tchfl"})
    r = client.post("/api/auth/login", json={"email": email, "password": "Test@123"})
    token = r.json().get("token") or r.json().get("access_token")
    H = {"Authorization": f"Bearer {token}"}

    # 3 rows: row 1 and row 3 have the identical template name
    csv_content = (
        "template_name,template_category,header_type,header_text,body_text\n"
        "hfl_patp_qcst_030926,MARKETING,TEXT,Header,First copy\n"
        "hfl_patp_new_unique_1,MARKETING,TEXT,Header,Unique template\n"
        "hfl_patp_qcst_030926,MARKETING,TEXT,Header,Duplicate copy\n"
    )

    submitted_names = []
    def fake_run(raw_list, log_path, **kwargs):
        from tracker import log_result
        for item in raw_list:
            tname = item.get("template_name", "")
            submitted_names.append(tname)
            res = SubmissionResult(
                source_ref=item.get("source_ref", tname),
                template_name=tname,
                status=SubmissionStatus.SUBMITTED,
                provider_ref_id=f"ref_{tname}",
            )
            log_result(res, log_path)

    with patch("api.fetch_whatsapp_templates", return_value=[]), patch("api.run", side_effect=fake_run):
        r = client.post(
            "/api/submit?account=tchfl&channel=whatsapp&skip_duplicates=true",
            files={"file": ("batch.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            headers=H,
        )
    assert r.status_code == 200
    data = r.json()
    results = data.get("results", [])
    assert len(results) == 3, f"Expected 3 results, got {len(results)}"

    # Row 1: hfl_patp_qcst_030926 -> submitted
    assert results[0]["template_name"] == "hfl_patp_qcst_030926"
    assert results[0]["status"] == "submitted"

    # Row 2: hfl_patp_new_unique_1 -> submitted
    assert results[1]["template_name"] == "hfl_patp_new_unique_1"
    assert results[1]["status"] == "submitted"

    # Row 3: hfl_patp_qcst_030926 -> duplicate skipped in-batch!
    assert results[2]["template_name"] == "hfl_patp_qcst_030926"
    assert results[2]["status"] == "duplicate"
    assert "within uploaded file" in results[2]["error"].lower()

    # Verify run was only invoked with the 2 unique templates, not the duplicate!
    assert submitted_names == ["hfl_patp_qcst_030926", "hfl_patp_new_unique_1"]
    print("✓ test_in_batch_duplicate_skipping_and_row_order passed!")


def test_poll_pending_updates_duplicate_templates():
    """
    Verify that pending_entries includes duplicate templates that are still pending on Meta,
    and poll_pending successfully updates their approval_status to approved.
    """
    import tempfile
    from models import ApprovalStatus, SubmissionResult, SubmissionStatus
    from runner import poll_pending
    from tracker import log_result, pending_entries
    from unittest.mock import patch

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        tmp_path = tmp.name

    # Log a duplicate template with approval_status="pending"
    dupe_pending = SubmissionResult(
        source_ref="dupe_ref_1",
        template_name="hfl_patp_rnr_030926",
        status=SubmissionStatus.DUPLICATE,
        provider_ref_id="",
        approval_status=ApprovalStatus.PENDING,
        client="tchfl",
    )
    log_result(dupe_pending, tmp_path)

    # Ensure pending_entries picks it up
    pending = pending_entries(tmp_path)
    assert len(pending) == 1
    assert pending[0]["template_name"] == "hfl_patp_rnr_030926"
    assert pending[0]["status"] == "duplicate"

    # Mock live template list returning APPROVED
    mock_templates = [
        {"template_name": "hfl_patp_rnr_030926", "template_create_status": "APPROVED", "fb_template_id": "2029846117715567"}
    ]
    with patch("runner.fetch_template_list", return_value=(mock_templates, None)):
        summary = poll_pending(tmp_path, client="tchfl")

    assert summary["updated"] == 1
    assert summary["pending"] == 0

    from tracker import load_log
    updated_log = load_log(tmp_path)
    assert updated_log[0]["approval_status"] == "approved"
    assert updated_log[0]["provider_ref_id"] == "2029846117715567"
    print("✓ test_poll_pending_updates_duplicate_templates passed!")

if __name__ == "__main__":
    # Check credentials are set
    if not os.environ.get("WABA_AUTH_TOKEN"):
        print("✗ Missing environment variable: WABA_AUTH_TOKEN")
        print("  Set it in .env or your environment with your official Karix API token.")
        sys.exit(1)

    try:
        test_check_status()
        test_list_all_templates()
        print()
        print("=== ALL TESTS PASSED ===")
    except AssertionError as e:
        print(f"✗ FAIL: {e}")
        print("=== SOME TESTS FAILED ===")
        sys.exit(1)
