"""
Tests for Carousel Card in-place editing and propagation to Karix RCS Whitelisting API.
"""
from __future__ import annotations

from rcs_models import RcsTemplateSubmission
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
                "media_url": "https://example.test/card1.png",
                "fileName": "provider-card1",
                "button_text": "Claim Deal",
                "button_url": "https://u3.mnge.co/deal-1",
            },
            {
                "card_title": "Card 2: Personal Loan",
                "card_description": "Apply in 2 minutes",
                "button_text": "Check Eligibility",
                "media_url": "https://example.test/card2.png",
                "fileName": "provider-card2",
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
