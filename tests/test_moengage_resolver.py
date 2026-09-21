"""
Unit and integration tests for TypeSafe AI MoEngage Semantic Resolver.
Tests:
1. Semantic duplicate detection (identical/similar vs distinct templates).
2. Search and screening against existing MoEngage template inventories.
3. Positional variable mapping to MoEngage UserAttribute personalization tags.
4. Offline fallback when uncredentialed.
5. Mocked integration with sync_karix_rcs_to_moengage.
"""

from unittest.mock import patch

from moengage_resolver import (
    check_semantic_duplicate_pair,
    find_semantic_duplicate,
    resolve_moengage_attributes,
)
from moengage_sync import sync_karix_rcs_to_moengage


def test_semantic_duplicate_identical_content():
    """Verify templates with identical message body are detected as duplicates regardless of name."""
    cand_name = "tcl_festive_offer_v2"
    cand_body = "Dear Customer, get pre-approved Personal Loan up to Rs. 5 Lakhs from Tata Capital. Apply today at tatacapital.com."
    exist_name = "TCL Festive Offer Q4"
    exist_body = "Dear Customer, get pre-approved Personal Loan up to Rs. 5 Lakhs from Tata Capital. Apply today at tatacapital.com."

    prob = check_semantic_duplicate_pair(cand_name, cand_body, exist_name, exist_body, allow_ai=True)
    assert prob >= 0.90


def test_semantic_duplicate_distinct_content():
    """Verify completely different campaigns are not flagged as duplicates."""
    cand_name = "tcl_home_loan"
    cand_body = "Own your dream home with Tata Capital Home Loans starting at 8.5% p.a. Zero processing fees."
    exist_name = "tcl_credit_card"
    exist_body = "Get 5X reward points on all supermarket and weekend dining transactions."

    prob = check_semantic_duplicate_pair(cand_name, cand_body, exist_name, exist_body, allow_ai=True)
    assert prob < 0.25


def test_find_semantic_duplicate_in_list():
    """Verify screening against a mock list of existing MoEngage templates."""
    existing_list = [
        {
            "id": "moe_001",
            "name": "tcl_car_loan_promo",
            "meta_data": {
                "template_id": "car_loan_101",
                "data": {"description": "Drive home your dream car with attractive interest rates."},
            },
        },
        {
            "id": "moe_002",
            "name": "tcl_personal_loan_diwali",
            "meta_data": {
                "template_id": "pl_diwali_2026",
                "data": {"description": "Celebrate Diwali with instant pre-approved personal loans from Tata Capital. Apply now!"},
            },
        },
    ]

    # Candidate matches moe_002 semantically
    cand_name = "tcl_pl_festive_diwali_v3"
    cand_body = "Celebrate Diwali with instant pre approved personal loans from Tata Capital. Apply now!"

    res = find_semantic_duplicate(cand_name, cand_body, existing_list, threshold=0.80, allow_ai=True)
    assert res.is_duplicate is True
    assert res.matched_template_name == "tcl_personal_loan_diwali"
    assert res.probability >= 0.80


def test_moengage_attribute_resolver_calibration():
    """Verify positional variables are mapped to appropriate UserAttribute tags."""
    tmpl_text = "Dear {{1}}, your EMI of Rs. {{2}} is due on {{3}} for Loan Account {{4}}. Pay via link {{5}}."
    trans = resolve_moengage_attributes(tmpl_text, allow_ai=True)

    assert trans.ai_resolved is True
    assert len(trans.mappings) == 5

    # Check mappings in order
    assert trans.mappings[0].attribute_name == "UserAttribute['first_name']"
    assert trans.mappings[1].attribute_name == "UserAttribute['emi_amount']"
    assert trans.mappings[2].attribute_name == "UserAttribute['due_date']"
    assert trans.mappings[3].attribute_name == "UserAttribute['loan_account_no']"
    assert trans.mappings[4].attribute_name == "UserAttribute['payment_url']"

    # Verify translated string
    assert "{{UserAttribute['first_name']}}" in trans.translated_text
    assert "{{UserAttribute['emi_amount']}}" in trans.translated_text
    assert "{{UserAttribute['due_date']}}" in trans.translated_text
    assert "{{UserAttribute['loan_account_no']}}" in trans.translated_text
    assert "{{UserAttribute['payment_url']}}" in trans.translated_text
    assert "{{1}}" not in trans.translated_text


def test_moengage_resolver_offline_fallback():
    """Verify deterministic fallback when allow_ai=False."""
    text = "Hello {{1}}, check your account {{2}}."
    trans = resolve_moengage_attributes(text, allow_ai=False)
    assert trans.ai_resolved is False
    assert len(trans.mappings) == 2
    assert "UserAttribute" in trans.mappings[0].attribute_name
    assert "{{1}}" not in trans.translated_text


def test_sync_karix_rcs_to_moengage_dedup_and_attributes_integration():
    """Verify sync skips semantic duplicates and resolves attributes before creation."""
    fake_karix_templates = [
        # Duplicate template
        {
            "templateId": "k_rcs_01",
            "status": "APPROVED",
            "viTemplate": {
                "name": "tcl_existing_dup",
                "standaloneCard": {
                    "cardTitle": "Diwali Offer",
                    "cardDescription": "Celebrate Diwali with personal loan offers.",
                },
            },
        },
        # New template with variables
        {
            "templateId": "k_rcs_02",
            "status": "APPROVED",
            "viTemplate": {
                "name": "tcl_new_campaign",
                "standaloneCard": {
                    "cardTitle": "EMI Reminder",
                    "cardDescription": "Dear {{1}}, your EMI of Rs. {{2}} is due on {{3}}.",
                },
            },
        },
    ]

    fake_moengage_existing = [
        {
            "id": "moe_existing_id",
            "name": "tcl_existing_dup",
            "meta_data": {
                "template_id": "k_rcs_01",
                "data": {"description": "Celebrate Diwali with personal loan offers."},
            },
        }
    ]

    with patch("rcs_client.fetch_rcs_templates", return_value=fake_karix_templates), \
         patch("moengage_sync.list_moengage_rcs_templates", return_value=fake_moengage_existing), \
         patch("moengage_sync.create_moengage_rcs_template") as mock_create:

        mock_create.return_value = {"ok": True, "moengage_id": "moe_new_123"}

        res = sync_karix_rcs_to_moengage(
            account="tata",
            semantic_dedup=True,
            resolve_attributes=True,
        )

        assert res["ok"] is True
        assert res["karix_total"] == 2
        assert len(res["created"]) == 1
        assert len(res["skipped"]) == 1
        assert "tcl_existing_dup" in res["skipped"][0]

        # Verify create_moengage_rcs_template received translated description with personalization tags
        call_args = mock_create.call_args[1]
        assert call_args["template_name"] == "tcl_new_campaign"
        assert "{{UserAttribute['first_name']}}" in call_args["card_description"]
        assert "{{UserAttribute['emi_amount']}}" in call_args["card_description"]
        assert "{{1}}" not in call_args["card_description"]
