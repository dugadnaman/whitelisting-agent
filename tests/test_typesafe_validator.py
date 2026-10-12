"""Offline contracts for semantic validation and the pre-submission gate.

Provider replies are controlled at the SDK boundary; these tests exercise policy
composition, not the live model's classification accuracy.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from grammar_checker import validate_template_pre_submission
from models import ApprovalStatus, SubmissionStatus, TemplateComponent, TemplateSubmission
from submission_client import submit_template
from template_validator import async_validate_template_semantic_quality, validate_template_semantic_quality


@pytest.fixture(autouse=True)
def offline_typesafe(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)


@pytest.fixture
def provider(monkeypatch):
    import typesafe_sdk

    response = SimpleNamespace(
        choices={"category": SimpleNamespace(choice="UTILITY", confidence=0.95, probabilities={"UTILITY": 0.97, "MARKETING": 0.02, "AUTHENTICATION": 0.01})},
        scores={"rejection_risk": SimpleNamespace(score=0.2)},
        nouls={"promotional": SimpleNamespace(noul=0.05), "floating_variables": SimpleNamespace(noul=0.05)},
    )
    sync = MagicMock()
    sync.__enter__.return_value = sync
    sync.system_one.return_value = response
    asynchronous = MagicMock()
    asynchronous.__aenter__ = AsyncMock(return_value=asynchronous)
    asynchronous.__aexit__ = AsyncMock(return_value=False)
    asynchronous.system_one = AsyncMock(return_value=response)
    monkeypatch.setenv("TYPESAFE_API_KEY", "offline-provider-fixture")
    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", MagicMock(return_value=sync))
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", MagicMock(return_value=asynchronous))
    return SimpleNamespace(response=response, sync=sync, asynchronous=asynchronous)


def test_provider_utility_report_preserves_input_context(provider):
    body = "Dear {{1}}, your EMI payment has been debited."
    report = validate_template_semantic_quality(
        body, declared_category=" utility ", client="bajaj", header_text=" Receipt ",
        footer_text=" Terms ", buttons=[{"text": "View receipt"}],
    )
    assert report.ai_checked is True
    assert report.predicted_category == "UTILITY"
    assert report.category_mismatch is False
    assert report.category_probabilities == provider.response.choices["category"].probabilities
    assert report.is_safe_to_submit is True
    request = provider.sync.system_one.call_args.kwargs
    assert request["state"] == {
        "template_body": body, "declared_category": "UTILITY", "account_client": "bajaj",
        "header": "Receipt", "footer": "Terms", "buttons": ["View receipt"],
    }
    assert set(request["questions"]) == {"category", "rejection_risk", "promotional", "floating_variables"}


def test_provider_promotional_category_blocks_utility(provider):
    provider.response.choices["category"].choice = "MARKETING"
    provider.response.choices["category"].probabilities = {"MARKETING": 0.95, "UTILITY": 0.04, "AUTHENTICATION": 0.01}
    report = validate_template_semantic_quality("Apply for our festive loan offer.", declared_category="UTILITY")
    assert report.ai_checked is True
    assert report.predicted_category == "MARKETING"
    assert report.category_mismatch is True
    assert any(w["type"] == "META_CATEGORY_MISMATCH" and w["severity"] == "error" for w in report.warnings)
    assert report.is_safe_to_submit is False


def test_uncertain_category_does_not_claim_mismatch(provider):
    provider.response.choices["category"].choice = "MARKETING"
    provider.response.choices["category"].confidence = 0.4
    report = validate_template_semantic_quality("Your account update.", declared_category="UTILITY")
    assert report.ai_checked is True
    assert report.predicted_category == "MARKETING"
    assert report.category_mismatch is False
    assert report.is_safe_to_submit is True


def test_promotional_probability_blocks_even_when_category_agrees(provider):
    provider.response.nouls["promotional"].noul = 0.9
    report = validate_template_semantic_quality("Your account update with an exclusive offer.", declared_category="UTILITY")
    assert report.category_mismatch is True
    assert report.is_safe_to_submit is False
    assert any(w["type"] == "PROMOTIONAL_IN_UTILITY" for w in report.warnings)


def test_provider_risk_and_floating_variables_control_warnings(provider):
    provider.response.scores["rejection_risk"].score = 2.8
    provider.response.nouls["floating_variables"].noul = 0.9
    report = validate_template_semantic_quality("Hello {{1}}, look at {{2}}", declared_category="UTILITY")
    assert report.rejection_risk_score == 2.8
    assert report.rejection_risk_level == "HIGH"
    assert report.floating_variables_probability == 0.9
    assert report.is_safe_to_submit is False
    assert {w["type"] for w in report.warnings} == {"HIGH_REJECTION_RISK", "FLOATING_VARIABLES_DETECTED"}


def test_comprehensive_pre_submission_pipeline(provider):
    provider.response.choices["category"].choice = "MARKETING"
    res = validate_template_pre_submission(
        body_text="congratualtions {{1}}!! you are eligibile for a pre-approved personal loan of Rs. {{2}}.",
        declared_category="UTILITY", use_ai=True,
    )
    assert "congratulations" in res["cleaned_body"].lower()
    assert "eligible" in res["cleaned_body"].lower()
    assert res["grammar_warnings"]
    assert res["predicted_category"] == "MARKETING"
    assert res["category_mismatch"] is True
    assert res["ai_report"]["ai_checked"] is True
    assert provider.sync.system_one.call_args.kwargs["state"]["template_body"] == res["cleaned_body"]


@pytest.mark.parametrize("allow_ai", [False, True])
def test_uncredentialed_validation_never_claims_ai_check(allow_ai):
    report = validate_template_semantic_quality("Your loan repayment is due.", declared_category="UTILITY", allow_ai=allow_ai)
    assert report.ai_checked is False
    assert report.predicted_category == "UTILITY"
    assert report.category_confidence == 0.0
    assert report.category_mismatch is False


def test_disabled_validation_does_not_call_provider(provider):
    report = validate_template_semantic_quality("Your account update.", allow_ai=False)
    assert report.ai_checked is False
    provider.sync.system_one.assert_not_called()


def test_provider_failure_is_not_reported_as_success(provider):
    provider.sync.system_one.side_effect = RuntimeError("provider unavailable")
    report = validate_template_semantic_quality("Your account update.", declared_category="UTILITY")
    assert report.ai_checked is False
    assert report.category_confidence == 0.0
    assert report.error == "provider unavailable"


def test_empty_body_blocks_without_provider(provider):
    report = validate_template_semantic_quality("   ")
    assert report.ai_checked is False
    assert report.is_safe_to_submit is False
    assert report.warnings[0]["type"] == "EMPTY_TEMPLATE_BODY"
    provider.sync.system_one.assert_not_called()


def test_async_provider_result(provider):
    provider.response.choices["category"].choice = "AUTHENTICATION"
    report = asyncio.run(async_validate_template_semantic_quality("Your OTP is {{1}}.", declared_category="AUTHENTICATION"))
    assert report.ai_checked is True
    assert report.predicted_category == "AUTHENTICATION"
    assert report.category_mismatch is False
    provider.asynchronous.system_one.assert_awaited_once()
    assert provider.asynchronous.system_one.call_args.kwargs["state"]["template_body"] == "Your OTP is {{1}}."


def test_async_uncredentialed_validation_is_truthful():
    report = asyncio.run(async_validate_template_semantic_quality("Your OTP is {{1}}.", declared_category="AUTHENTICATION"))
    assert report.ai_checked is False
    assert report.category_confidence == 0.0


def test_async_provider_failure_is_truthful(provider):
    provider.asynchronous.system_one.side_effect = RuntimeError("provider unavailable")
    report = asyncio.run(async_validate_template_semantic_quality("Your OTP is {{1}}."))
    assert report.ai_checked is False
    assert report.error == "provider unavailable"


def test_submission_client_validate_ai_gate(provider, monkeypatch):
    provider.response.choices["category"].choice = "MARKETING"
    sub = TemplateSubmission(
        client="bajaj", channel="whatsapp", template_name="test_promo_as_utility_block",
        language="en", category="UTILITY", waba_id="offline-waba", source_ref="row_99",
        components=[TemplateComponent(type="BODY", text="Claim your pre-approved loan today!")],
    )
    import submission_client

    transports = [MagicMock(side_effect=AssertionError("blocked submission reached transport")) for _ in range(2)]
    monkeypatch.setattr(submission_client, "_submit_portal_template", transports[0])
    monkeypatch.setattr(submission_client, "_submit_official_template", transports[1])
    result = submit_template(sub, client="bajaj", validate_ai=True)
    assert result.status == SubmissionStatus.FAILED
    assert result.approval_status == ApprovalStatus.REJECTED
    assert result.source_ref == "row_99"
    assert result.template_name == sub.template_name
    assert result.client == "bajaj"
    assert result.channel == "whatsapp"
    assert result.error
    for transport in transports:
        transport.assert_not_called()
