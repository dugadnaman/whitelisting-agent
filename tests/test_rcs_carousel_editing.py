"""
Tests for Carousel Card in-place editing and propagation to Karix RCS Whitelisting API.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

import api
from rcs_models import RcsSubmissionResult, RcsTemplateSubmission
from rcs_client import _build_rcs_carousel_vi_template


def test_build_rcs_carousel_uses_custom_card_cta_and_urls():
    """Verify that card-level button_text and button_url are preserved and converted to suggestions."""
    payload = RcsTemplateSubmission(
        client="tcl_promo",
        template_name="tcn_test_carousel",
        template_type="carousel",
        carousel_cards=[
            {
                "card_title": "Card 1: Festive Discount",
                "card_description": "Get 20% off today",
                "button_text": "Claim Deal",
                "button_url": "https://u3.mnge.co/deal-1",
            },
            {
                "card_title": "Card 2: Personal Loan",
                "card_description": "Apply in 2 minutes",
                "button_text": "Check Eligibility",
                "button_url": "https://u3.mnge.co/loan-2",
            },
        ],
    )

    vi_template, params = _build_rcs_carousel_vi_template(payload, "tcn_test_carousel", "bot_999")
    cards = vi_template["carouselCard"]
    assert len(cards) == 2

    # Card 1 assertions
    assert cards[0]["cardTitle"] == "Card 1: Festive Discount"
    assert cards[0]["suggestions"][0]["text"] == "Claim Deal"
    assert cards[0]["suggestions"][0]["postbackData"] == "Claim Deal"
    assert "https://u3.mnge.co/deal-1" in cards[0]["suggestions"][0]["url"]

    # Card 2 assertions
    assert cards[1]["cardTitle"] == "Card 2: Personal Loan"
    assert cards[1]["suggestions"][0]["text"] == "Check Eligibility"
    assert cards[1]["suggestions"][0]["postbackData"] == "Check Eligibility"
    assert "https://u3.mnge.co/loan-2" in cards[1]["suggestions"][0]["url"]


def test_submit_jira_brief_with_edited_carousel_cards():
    """Verify POST /api/jira/submit/{issue_key} preserves edited card title, description, and CTA."""
    api.app.dependency_overrides[api.get_current_user] = lambda: {
        "sub": "usr_tata_test",
        "email": "operator@tatacapital.com",
        "tenant_id": "tata",
        "role": "admin",
    }

    submitted_submissions = []

    def mock_submit(sub, client="tcl_promo"):
        submitted_submissions.append(sub)
        return RcsSubmissionResult(
            source_ref=sub.source_ref,
            template_name=sub.template_name,
            template_id="rcs_test_id_555",
            client=client,
        )

    try:
        with (
            patch("rcs_client.submit_rcs_template", side_effect=mock_submit),
            patch("rcs_tracker.log_rcs_result"),
            patch("tracker.log_result"),
            patch("api.log_activity"),
        ):
            client = TestClient(api.app)
            req_body = {
                "channels": ["rcs"],
                "account": "tcl_promo",
                "rcs_templates": [
                    {
                        "template_name": "tcn_550_smpl_carousel_v2",
                        "template_type": "carousel",
                        "card_title": "Default Card Title",
                        "body": "Default Card Body",
                        "carousel_cards": [
                            {
                                "card_title": "Card 1 Custom Title",
                                "card_description": "Card 1 Custom Description",
                                "button_text": "Apply Now Card 1",
                                "button_url": "https://u3.mnge.co/card1",
                            },
                            {
                                "card_title": "Card 2 Custom Title",
                                "card_description": "Card 2 Custom Description",
                                "button_text": "Learn More Card 2",
                                "button_url": "https://u3.mnge.co/card2",
                            },
                        ],
                    }
                ],
            }
            resp = client.post("/api/jira/submit/TCN-550", json=req_body)
            assert resp.status_code == 200, resp.text
            assert len(submitted_submissions) == 1
            sub = submitted_submissions[0]
            assert sub.template_type == "carousel"
            assert len(sub.carousel_cards) == 2
            assert sub.carousel_cards[0]["card_title"] == "Card 1 Custom Title"
            assert sub.carousel_cards[0]["button_text"] == "Apply Now Card 1"
            assert sub.carousel_cards[0]["button_url"] == "https://u3.mnge.co/card1"
            assert sub.carousel_cards[1]["card_title"] == "Card 2 Custom Title"
            assert sub.carousel_cards[1]["button_text"] == "Learn More Card 2"
            assert sub.carousel_cards[1]["button_url"] == "https://u3.mnge.co/card2"
    finally:
        api.app.dependency_overrides.pop(api.get_current_user, None)
