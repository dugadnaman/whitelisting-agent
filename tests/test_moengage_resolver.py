"""
Unit and integration tests for TypeSafe AI MoEngage Semantic Resolver.
Tests:
1. Semantic duplicate detection (identical/similar vs distinct templates).
2. Search and screening against existing MoEngage template inventories.
3. Positional variable mapping to MoEngage UserAttribute personalization tags.
4. Offline fallback when uncredentialed.
5. Mocked integration with sync_karix_rcs_to_moengage.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from moengage_resolver import (
    check_semantic_duplicate_pair,
    find_semantic_duplicate,
    resolve_moengage_attributes,
)
from moengage_sync import sync_karix_rcs_to_moengage


@pytest.fixture(autouse=True)
def offline_typesafe(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)


@pytest.fixture
def attribute_provider(monkeypatch):
    import typesafe_sdk

    roles = ["USER_FIRST_NAME", "USER_EMI_AMOUNT", "USER_DUE_DATE", "USER_LOAN_ACCOUNT", "USER_PAYMENT_URL"]
    response = SimpleNamespace(
        choices={
            f"var_{idx}": SimpleNamespace(choice=role, confidence=0.93)
            for idx, role in enumerate(roles, start=1)
        },
        nouls={"is_duplicate": SimpleNamespace(noul=0.94)},
    )
    provider = MagicMock()
    provider.__enter__.return_value = provider
    provider.system_one.return_value = response
    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-provider-fixture")
    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", MagicMock(return_value=provider))
    return provider


def test_semantic_duplicate_identical_content():
    """Verify templates with identical message body are detected as duplicates regardless of name."""
    cand_name = "tcl_festive_offer_v2"
    cand_body = "Dear Customer, get pre-approved Personal Loan up to Rs. 5 Lakhs from Tata Capital. Apply today at tatacapital.com."
    exist_name = "TCL Festive Offer Q4"
    exist_body = "Dear Customer, get pre-approved Personal Loan up to Rs. 5 Lakhs from Tata Capital. Apply today at tatacapital.com."

    prob = check_semantic_duplicate_pair(cand_name, cand_body, exist_name, exist_body, allow_ai=False)
    assert prob >= 0.90


def test_semantic_duplicate_distinct_content():
    """Verify completely different campaigns are not flagged as duplicates."""
    cand_name = "tcl_home_loan"
    cand_body = "Own your dream home with Tata Capital Home Loans starting at 8.5% p.a. Zero processing fees."
    exist_name = "tcl_credit_card"
    exist_body = "Get 5X reward points on all supermarket and weekend dining transactions."

    prob = check_semantic_duplicate_pair(cand_name, cand_body, exist_name, exist_body, allow_ai=False)
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
                "data": {
                    "description": "Celebrate Diwali with instant pre-approved personal loans from Tata Capital. Apply now!"
                },
            },
        },
    ]

    # Candidate matches moe_002 semantically
    cand_name = "tcl_pl_festive_diwali_v3"
    cand_body = "Celebrate Diwali with instant pre approved personal loans from Tata Capital. Apply now!"

    res = find_semantic_duplicate(cand_name, cand_body, existing_list, threshold=0.80, allow_ai=False)
    assert res.is_duplicate is True
    assert res.matched_template_name == "tcl_personal_loan_diwali"
    assert res.probability >= 0.80


def test_moengage_attribute_provider_choices_are_translated(attribute_provider):
    """Provider-selected semantic roles map to consumer personalization tags."""
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

    request = attribute_provider.system_one.call_args.kwargs
    assert request["state"] == {"template_text": tmpl_text}
    assert set(request["questions"]) == {"var_1", "var_2", "var_3", "var_4", "var_5"}
    assert all(mapping.confidence == 0.93 for mapping in trans.mappings)


def test_repeated_variable_uses_one_provider_mapping(attribute_provider):
    text = "Dear {{1}}, welcome back {{1}}."
    trans = resolve_moengage_attributes(text)
    assert trans.ai_resolved is True
    assert len(trans.mappings) == 1
    assert trans.translated_text == "Dear {{UserAttribute['first_name']}}, welcome back {{UserAttribute['first_name']}}."
    assert set(attribute_provider.system_one.call_args.kwargs["questions"]) == {"var_1"}


def test_semantic_duplicate_provider_probability_is_consumed(attribute_provider):
    probability = check_semantic_duplicate_pair("candidate", "Your EMI is due soon.", "existing", "Loan repayment reminder.")
    assert probability == 0.94
    assert attribute_provider.system_one.call_args.kwargs["state"] == {
        "candidate_template": {"name": "candidate", "body": "Your EMI is due soon."},
        "existing_template": {"name": "existing", "body": "Loan repayment reminder."},
    }


def test_semantic_duplicate_provider_failure_does_not_claim_duplicate(attribute_provider):
    attribute_provider.system_one.side_effect = RuntimeError("provider unavailable")
    assert check_semantic_duplicate_pair("candidate", "Your EMI is due soon.", "existing", "Loan repayment reminder.") == 0.0


def test_attribute_provider_failure_does_not_claim_ai_resolution(attribute_provider):
    attribute_provider.system_one.side_effect = RuntimeError("provider unavailable")
    trans = resolve_moengage_attributes("Dear {{1}}, your EMI is due.")
    assert trans.ai_resolved is False
    assert trans.mappings[0].semantic_type == "FALLBACK_DEFAULT"


def test_uncredentialed_attribute_resolution_is_truthful():
    trans = resolve_moengage_attributes("Dear {{1}}, your EMI is due.", allow_ai=True)
    assert trans.ai_resolved is False
    assert trans.mappings[0].semantic_type == "FALLBACK_DEFAULT"

def test_moengage_resolver_offline_fallback():
    """Verify deterministic fallback when allow_ai=False."""
    text = "Hello {{1}}, check your account {{2}}."
    trans = resolve_moengage_attributes(text, allow_ai=False)
    assert trans.ai_resolved is False
    assert len(trans.mappings) == 2
    assert "UserAttribute" in trans.mappings[0].attribute_name
    assert "{{1}}" not in trans.translated_text


def test_sync_karix_rcs_to_moengage_dedup_and_attributes_integration(attribute_provider):
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

    with (
        patch("rcs_client.fetch_rcs_templates", return_value=fake_karix_templates),
        patch("moengage_sync.list_moengage_rcs_templates", return_value=fake_moengage_existing),
        patch("moengage_sync.create_moengage_rcs_template") as mock_create,
    ):
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


def test_apparel_account_rcs_only_sync():
    """Verify sync_karix_rcs_to_moengage executes for apparel account."""
    fake_templates = [
        {
            "templateId": "apparel_rcs_festive",
            "status": "APPROVED",
            "viTemplate": {
                "name": "apparel_festive_collection",
                "standaloneCard": {
                    "cardTitle": "New Autumn Arrivals",
                    "cardDescription": "Shop the latest festive apparel with exclusive discounts!",
                },
            },
        }
    ]

    with (
        patch("rcs_client.fetch_rcs_templates", return_value=fake_templates),
        patch("moengage_sync.list_moengage_rcs_templates", return_value=[]),
        patch("moengage_sync.create_moengage_rcs_template") as mock_create,
    ):
        mock_create.return_value = {"ok": True, "moengage_id": "apparel_moe_1"}

        res = sync_karix_rcs_to_moengage(account="apparel")
        assert res["ok"] is True
        assert res["account"] == "apparel"
        assert len(res["created"]) == 1
        assert res["created"][0]["template_name"] == "apparel_festive_collection"


def test_apparel_account_blocks_spreadsheet_submission(provision_user):
    """Verify API blocks spreadsheet submission and preview for apparel account."""
    import io

    from fastapi.testclient import TestClient

    from api import app

    _, headers = provision_user(tenant="apparel")
    client = TestClient(app, headers=headers)

    fake_csv = io.BytesIO(b"template_name,body\ntpl_1,hello")

    # Preview should reject apparel
    resp_prev = client.post(
        "/api/preview?account=apparel&channel=whatsapp",
        files={"file": ("test.csv", fake_csv, "text/csv")},
    )
    assert resp_prev.status_code == 400
    assert "RCS Karix-to-MoEngage sync only" in resp_prev.json()["detail"]

