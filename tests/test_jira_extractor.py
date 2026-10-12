"""
Unit and integration tests for TypeSafe AI Jira Description & Template Extractor.
Tests:
1. Channel & purpose routing (WhatsApp, RCS, SMS).
2. Structural component segmentation (Header, Body, Footer, Button).
3. Calibrated variable sample generation with TypeSafe Choice.
4. End-to-end integration with briefing_parser.parse_jira_brief.
5. Offline fallback when uncredentialed.
"""

import pytest

from briefing_parser import parse_jira_brief
from jira_extractor import (
    _segment_text_components,
    extract_template_from_jira_text,
    route_jira_brief,
)


@pytest.fixture(autouse=True)
def offline_typesafe(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)


def test_jira_channel_routing_whatsapp():
    """Verify Jira brief for WhatsApp campaign routes to WHATSAPP with detected components."""
    desc = """
    Please whitelist this WhatsApp template for Personal Loan Diwali campaign:
    Header: Diwali Loan Mela 2026
    Body:
    Dear {{1}}, get pre-approved Personal Loan of Rs. {{2}} from Tata Capital.
    Footer: T&C apply.
    Button: Apply Now -> https://www.tatacapital.com
    """
    decision = route_jira_brief(desc, summary="Diwali WhatsApp Promo")
    assert decision.target_channel == "WHATSAPP"
    assert decision.campaign_purpose == "LOAN_OFFER"
    assert decision.has_header is True
    assert decision.has_footer is True
    assert decision.has_cta is True


def test_jira_channel_routing_rcs():
    """Verify RCS rich card campaign brief routes to RCS."""
    desc = """
    Team, create an RCS rich card template with banner creative for our home loan campaign.
    Card Title: Home Loan Festive Rates
    Description: Upgrade your dream home with Tata Capital Home Loans starting 8.5% p.a.
    Action: View Properties -> https://www.tatacapital.com/homeloan
    """
    decision = route_jira_brief(desc, summary="RCS Home Loan Brief", allow_ai=False)
    assert decision.target_channel == "RCS"
    assert decision.has_cta is True


@pytest.mark.parametrize("label", ["Action:", "action -", "ACTION –"])
def test_explicit_action_routes_as_cta_without_ai(label):
    decision = route_jira_brief(
        f"RCS campaign\n{label} View Properties -> https://example.com/homes",
        allow_ai=False,
    )
    assert decision.has_cta is True


@pytest.mark.parametrize("text", ["RCS campaign requires action tomorrow.", "RCS campaign\nAction: "])
def test_action_without_explicit_content_is_not_cta(text):
    assert route_jira_brief(text, allow_ai=False).has_cta is False


def test_jira_channel_routing_sms():
    """Verify SMS text brief routes to SMS."""
    desc = """
    DLT SMS template request:
    Dear Customer, your Tata Capital EMI of Rs. 12,500 is due on 10-Oct. Pay via link https://tcl.in/pay to avoid penalty.
    """
    decision = route_jira_brief(desc, summary="SMS EMI Reminder")
    assert decision.target_channel == "SMS"
    assert decision.campaign_purpose in ("EMI_COLLECTION", "TRANSACTION_SERVICE", "LOAN_OFFER")


def test_jira_component_segmentation():
    """Verify segmentation separates Header, Body, Footer, and CTA without leaking labels."""
    desc = """
    Header: Exclusive Car Loan Offer
    Body:
    Drive home your new car today with zero down payment!
    Special interest rate of 8.99% for pre-approved customers.
    Footer: Tata Capital Ltd. All rights reserved.
    Button: Explore Cars -> https://www.tatacapital.com/car-loan
    """
    comp = _segment_text_components(desc)
    assert comp.header_text == "Exclusive Car Loan Offer"
    assert "Drive home your new car" in comp.body_text
    assert "Special interest rate" in comp.body_text
    assert "Tata Capital Ltd. All rights reserved." in comp.body_text
    assert comp.footer_text is None
    assert comp.button_text == "Explore Cars"
    assert comp.button_url == "https://www.tatacapital.com/car-loan"
    assert comp.button_type == "URL"




def test_briefing_parser_integration_freeform_jira():
    """Verify briefing_parser.parse_jira_brief processes free-form description end-to-end."""
    fake_issue = {
        "key": "TCN-888",
        "summary": "Festive Two-Wheeler Loan",
        "description_text": """
        Hi Operations,
        Please whitelist this WhatsApp template for festive season:
        Header: Two Wheeler Loan Mela
        Body:
        Dear <name>, get a pre-approved Two-Wheeler loan up to Rs. <amount> at <roi>% interest.
        Repay in <tenure> monthly EMIs.
        Apply now!
        Footer: T&C apply. Tata Capital Financial Services.
        Button: Apply Now -> https://www.tatacapital.com/twl
        """,
        "description_raw": None,
        "attachments": [],
    }

    brief = parse_jira_brief(fake_issue, download_creatives=False)
    assert brief.issue_key == "TCN-888"
    assert len(brief.whatsapp_templates) == 1

    draft = brief.whatsapp_templates[0]
    assert draft["header_text"] == "Two Wheeler Loan Mela"
    assert "Dear {{1}}" in draft["body"]
    assert "Rs. {{2}}" in draft["body"]
    assert "at {{3}}% interest" in draft["body"]
    assert "Repay in {{4}} monthly EMIs" in draft["body"]
    assert "T&C apply. Tata Capital Financial Services." in draft["body"]
    assert draft["footer_text"] is None
    assert draft["button_text"] == "Apply Now"
    assert draft["button_url"] == "https://www.tatacapital.com/twl"
    assert len(draft["variables"]) == 4
    assert len(draft["sample_values"]) == 4


def test_jira_extractor_fallback_when_uncredentialed():
    """Verify extractor gracefully falls back to deterministic rule-based output when allow_ai=False."""
    desc = """
    Header: Quick Cash Loan
    Body: Dear {{1}}, your amount is {{2}}.
    Footer: Tata Capital.
    Button: Claim -> https://tatacapital.com
    """
    res = extract_template_from_jira_text(desc, allow_ai=False)
    assert res.ai_extracted is False
    assert res.template.header_text == "Quick Cash Loan"
    assert len(res.sample_values) == 2
