"""
Tests for Phase 1 WhatsApp & RCS Template Identification Engine.
Verifies master catalog comparison against live Karix WABA templates,
fuzzy diffing, TypeSafe AI semantic equivalence, and discrepancy reporting.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from models import TemplateComponent, TemplateSubmission
from template_identifier import (
    IdentificationReport,
    compute_text_similarity,
    evaluate_semantic_equivalence_typesafe,
    identify_master_templates,
    normalize_template_text,
)


def test_normalize_template_text():
    """Verify placeholders, quotes, and whitespace are normalized."""
    text1 = "Dear {{1}}, your EMI of Rs. {{2}} is due on {{3}}."
    text2 = "Dear <name>, your EMI of Rs. {#amount#} is due on {{date}}."

    norm1 = normalize_template_text(text1)
    norm2 = normalize_template_text(text2)

    assert norm1 == "dear <var>, your emi of rs. <var> is due on <var>."
    assert norm1 == norm2


def test_compute_text_similarity():
    """Verify similarity ratios for identical, variable-different, and distinct copy."""
    s1 = "Claim your exclusive pre-approved personal loan of Rs. {{1}} today!"
    s2 = "Claim your exclusive pre-approved personal loan of Rs. {{amount}} today!"
    s3 = "Your one-time password for login is {{1}}. Do not share this OTP."

    assert compute_text_similarity(s1, s2) == 1.0
    assert compute_text_similarity(s1, s3) < 0.50


def test_identify_master_templates_whitelisted():
    """Verify master templates matching live approved templates classify as WHITELISTED."""
    master = [
        TemplateSubmission(
            client="tcl_promo",
            channel="whatsapp",
            template_name="pl_preapproved_offer_v1",
            category="MARKETING",
            language="en",
            waba_id="123456",
            source_ref="row_1",
            components=[
                TemplateComponent(type="HEADER", format="TEXT", text="Special Offer"),
                TemplateComponent(type="BODY", text="Dear {{1}}, your pre-approved loan of Rs. {{2}} is ready!"),
            ],
        )
    ]
    live = [
        {
            "template_name": "pl_preapproved_offer_v1",
            "status": "APPROVED",
            "category": "MARKETING",
            "language": "en",
            "fb_template_id": "987654321012345",
            "components": [
                {"type": "HEADER", "text": "Special Offer"},
                {"type": "BODY", "text": "Dear {{1}}, your pre-approved loan of Rs. {{2}} is ready!"},
            ],
        }
    ]
    report = identify_master_templates(master, client="tcl_promo", live_templates=live)

    assert report.total_master == 1
    assert report.whitelisted_count == 1
    assert report.missing_count == 0
    assert report.drift_count == 0
    assert report.items[0].status == "WHITELISTED"
    assert report.items[0].action_required == "NONE"


def test_identify_master_templates_missing():
    """Verify templates not present on live WABA classify as NOT_WHITELISTED."""
    master = [
        TemplateSubmission(
            client="tchfl",
            channel="whatsapp",
            template_name="hl_instant_approval_new",
            category="MARKETING",
            language="en",
            waba_id="123456",
            source_ref="row_2",
            components=[
                TemplateComponent(type="BODY", text="Apply for Tata Capital Home Loan with rates starting at 8.75%."),
            ],
        )
    ]

    live = []  # No live templates

    report = identify_master_templates(master, client="tchfl", live_templates=live)

    assert report.total_master == 1
    assert report.missing_count == 1
    assert report.whitelisted_count == 0
    assert report.items[0].status == "NOT_WHITELISTED"
    assert report.items[0].action_required == "SUBMIT"
    assert len(report.missing_templates) == 1
    assert report.missing_templates[0]["template_name"] == "hl_instant_approval_new"


def test_identify_master_templates_content_drift():
    """Verify templates existing on WABA but with modified body classify as CONTENT_DRIFT."""
    master = [
        TemplateSubmission(
            client="tcl_promo",
            channel="whatsapp",
            template_name="festive_diwali_bonanza",
            category="MARKETING",
            language="en",
            waba_id="123456",
            source_ref="row_3",
            components=[
                TemplateComponent(
                    type="BODY", text="Diwali Special: Zero processing fee on all loans applied before Oct 31!"
                ),
            ],
        )
    ]

    live = [
        {
            "template_name": "festive_diwali_bonanza",
            "status": "APPROVED",
            "components": [
                {"type": "BODY", "text": "Old Copy: Get 50% discount on processing fee for Diwali."},
            ],
        }
    ]

    report = identify_master_templates(master, client="tcl_promo", live_templates=live)

    assert report.total_master == 1
    assert report.drift_count == 1
    assert report.whitelisted_count == 0
    assert report.items[0].status == "CONTENT_DRIFT"
    assert report.items[0].action_required == "REMEDIATE"
    assert "content has drifted" in report.items[0].diff_summary


def test_identify_master_templates_pending_and_rejected():
    """Verify live PENDING and REJECTED statuses are classified correctly."""
    master = [
        TemplateSubmission(
            client="bajaj",
            channel="whatsapp",
            template_name="emi_reminder_trans",
            category="UTILITY",
            language="en",
            waba_id="123456",
            source_ref="row_4",
            components=[TemplateComponent(type="BODY", text="Your EMI is pending.")],
        ),
        TemplateSubmission(
            client="bajaj",
            channel="whatsapp",
            template_name="promo_crypto_blast",
            category="MARKETING",
            language="en",
            waba_id="123456",
            source_ref="row_5",
            components=[TemplateComponent(type="BODY", text="Invest in crypto today.")],
        ),
    ]
    live = [
        {"template_name": "emi_reminder_trans", "status": "PENDING"},
        {"template_name": "promo_crypto_blast", "status": "REJECTED", "reason": "Prohibited financial products"},
    ]

    report = identify_master_templates(master, client="bajaj", live_templates=live)

    assert report.pending_count == 1
    assert report.rejected_count == 1
    assert report.items[0].status == "PENDING"
    assert report.items[0].action_required == "WAIT"
    assert report.items[1].status == "REJECTED"
    assert report.items[1].action_required == "SUBMIT"
    assert len(report.missing_templates) == 1
    assert report.missing_templates[0]["template_name"] == "promo_crypto_blast"


def test_typesafe_semantic_equivalence_offline_fallback():
    """Verify offline fallback produces reliable token similarity without API key."""
    with patch.dict("os.environ", {}, clear=True):
        m_text = "Dear {{1}}, your Tata Capital personal loan is ready."
        l_text = "Dear {{name}}, your Tata Capital personal loan is ready."

        is_eq, score, method = evaluate_semantic_equivalence_typesafe(m_text, l_text)
        assert is_eq is True
        assert score == 1.0
        assert method == "FUZZY_TOKEN"


def test_api_identify_json_endpoint():
    """Verify POST /api/templates/identify-json returns expected identification payload."""
    from api import app, get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"email": "operator@attributics.com", "role": "operator"}
    client = TestClient(app)

    try:
        with patch("template_identifier.fetch_template_list") as mock_fetch:
            mock_fetch.return_value = (
                [
                    {
                        "template_name": "demo_live_tpl",
                        "status": "APPROVED",
                        "components": [{"type": "BODY", "text": "Live hello."}],
                    }
                ],
                None,
            )

            resp = client.post(
                "/api/templates/identify-json",
                json={
                    "account": "tata",
                    "templates": [
                        {
                            "template_name": "demo_live_tpl",
                            "category": "UTILITY",
                            "components": [{"type": "BODY", "text": "Live hello."}],
                        },
                        {
                            "template_name": "demo_missing_tpl",
                            "category": "MARKETING",
                            "components": [{"type": "BODY", "text": "Brand new copy."}],
                        },
                    ],
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["total_master"] == 2
            assert data["whitelisted_count"] == 1
            assert data["missing_count"] == 1
            assert len(data["missing_templates"]) == 1
            assert data["missing_templates"][0]["template_name"] == "demo_missing_tpl"
    finally:
        app.dependency_overrides.clear()


def test_find_template_by_content_exact_and_fuzzy():
    """Verify find_template_by_content returns template name and ID when content exists."""
    from template_identifier import find_template_by_content

    mock_live = [
        {
            "name": "bajaj_emi_reminder_v1",
            "id": "109823908123901",
            "status": "APPROVED",
            "category": "UTILITY",
            "language": "en",
            "components": [
                {"type": "HEADER", "format": "TEXT", "text": "EMI Alert"},
                {
                    "type": "BODY",
                    "text": "Dear {{1}}, your EMI of Rs. {{2}} is due on {{3}}. Pay now to avoid charges.",
                },
            ],
        },
        {
            "name": "bajaj_festival_promo",
            "id": "209823908123902",
            "status": "APPROVED",
            "category": "MARKETING",
            "components": [
                {"type": "BODY", "text": "Celebrate this Diwali with zero processing fee on personal loans!"},
            ],
        },
    ]

    # 1. Exact match (with identical variables)
    res_exact = find_template_by_content(
        content="Dear {{1}}, your EMI of Rs. {{2}} is due on {{3}}. Pay now to avoid charges.",
        client="bajaj",
        live_templates=mock_live,
    )
    assert res_exact.found is True
    assert res_exact.template_name == "bajaj_emi_reminder_v1"
    assert res_exact.template_id == "109823908123901"
    assert res_exact.status == "APPROVED"
    assert res_exact.match_type == "EXACT"
    assert res_exact.similarity_score == 1.0

    # 2. Fuzzy match (named variables instead of numbers)
    res_fuzzy = find_template_by_content(
        content="Dear <name>, your EMI of Rs. {#amount#} is due on {#date#}. Pay now to avoid charges.",
        client="bajaj",
        live_templates=mock_live,
    )
    assert res_fuzzy.found is True
    assert res_fuzzy.template_name == "bajaj_emi_reminder_v1"
    assert res_fuzzy.template_id == "109823908123901"
    assert res_fuzzy.similarity_score >= 0.95

    # 3. Not found for brand new copy
    res_missing = find_template_by_content(
        content="Apply for your medical insurance coverage starting at only Rs 499 per month.",
        client="bajaj",
        live_templates=mock_live,
    )
    assert res_missing.found is False
    assert res_missing.template_name is None
    assert res_missing.template_id is None




def test_find_template_by_content_handles_karix_raw_template_fields():
    """Search must understand the field names returned by Karix getAllTemplates."""
    from template_identifier import find_template_by_content

    res = find_template_by_content(
        content="Dear {{1}}, your EMI payment of {{2}} is due today.",
        client="tcl_promo",
        live_templates=[
            {
                "templateName": "tcl_emi_due_v1",
                "templateId": "karix-123",
                "template_create_status": "APPROVED",
                "template_category": "UTILITY",
                "language_code": "en_US",
                "template_message": "Dear {{1}}, your EMI payment of {{2}} is due today.",
            }
        ],
    )

    assert res.found is True
    assert res.template_name == "tcl_emi_due_v1"
    assert res.template_id == "karix-123"
    assert res.status == "APPROVED"
def test_api_search_template_by_content_endpoint():
    """Verify POST /api/templates/search-by-content endpoint returns matching template name and id."""
    from api import app, get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"email": "tester@attributics.com", "name": "Tester"}
    client = TestClient(app)

    try:
        mock_templates = [
            {
                "template_name": "tata_quick_loan_v3",
                "fb_template_id": "99887766554433",
                "status": "APPROVED",
                "components": [
                    {"type": "BODY", "text": "Need instant funds? Get approved in 5 minutes with Tata Capital."},
                ],
            }
        ]
        with patch("submission_client.fetch_template_list", return_value=(mock_templates, None)):
            resp = client.post(
                "/api/templates/search-by-content",
                json={
                    "content": "Need instant funds? Get approved in 5 minutes with Tata Capital.",
                    "client": "tata",
                    "channel": "whatsapp",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["found"] is True
            assert data["template_name"] == "tata_quick_loan_v3"
            assert data["template_id"] == "99887766554433"
            assert data["status"] == "APPROVED"
            assert data["match_type"] == "EXACT"
    finally:
        app.dependency_overrides.clear()
