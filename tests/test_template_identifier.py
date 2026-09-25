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
