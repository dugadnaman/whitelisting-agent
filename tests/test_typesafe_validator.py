"""
Unit and integration tests for TypeSafe AI Pre-Submission Validator & Category Checker.
Tests:
1. Meta category classification (UTILITY, MARKETING, AUTHENTICATION).
2. Category mismatch detection (promotional copy submitted as UTILITY).
3. Meta rejection risk scoring and floating variable detection.
4. Comprehensive pre-submission audit combining grammar, rules, and AI.
5. Graceful fallback when AI is disabled or uncredentialed.
6. Submission client pre-flight AI validation gate.
"""

import asyncio
import os

import pytest

from grammar_checker import validate_meta_technical_compliance, validate_template_pre_submission
from models import ApprovalStatus, SubmissionResult, SubmissionStatus, TemplateComponent, TemplateSubmission
from submission_client import submit_template
from template_validator import (
    SemanticValidationReport,
    async_validate_template_semantic_quality,
    validate_template_semantic_quality,
)


def test_typesafe_category_classification_utility():
    """Verify genuine transactional utility templates are classified as UTILITY without mismatch."""
    body = (
        "Dear {{1}}, your Bajaj Finserv EMI payment of Rs. {{2}} for Loan Account {{3}} "
        "has been successfully debited on {{4}}. Transaction Ref: {{5}}."
    )
    report = validate_template_semantic_quality(
        body_text=body,
        declared_category="UTILITY",
        client="bajaj",
    )
    assert report.ai_checked is True
    assert report.predicted_category == "UTILITY"
    assert report.category_mismatch is False
    assert report.category_confidence >= 0.75
    assert report.rejection_risk_level in ("SAFE", "LOW", "MODERATE")
    assert report.is_safe_to_submit is True


def test_typesafe_category_mismatch_promotional_in_utility():
    """Verify promotional sales copy declared as UTILITY is caught as a category mismatch."""
    promo_body = (
        "Exclusive festive offer from Bajaj Finserv! Get a pre-approved Personal Loan "
        "up to Rs. 5,00,000 at interest rates starting from 9.99% p.a. Zero processing fee. "
        "Apply now to claim your cash today!"
    )
    report = validate_template_semantic_quality(
        body_text=promo_body,
        declared_category="UTILITY",
        client="bajaj",
    )
    assert report.ai_checked is True
    assert report.predicted_category == "MARKETING"
    assert report.category_mismatch is True
    assert any(w["type"] in ("META_CATEGORY_MISMATCH", "PROMOTIONAL_IN_UTILITY") for w in report.warnings)
    # Severity should be error because submitting marketing as utility is forbidden by Meta
    assert any(w.get("severity") == "error" for w in report.warnings)
    assert report.is_safe_to_submit is False


def test_typesafe_authentication_otp_classification():
    """Verify OTP verification messages are classified as AUTHENTICATION."""
    otp_body = (
        "{{1}} is your one-time password (OTP) to log in to your Bajaj account. Valid for 5 minutes. Do not share it."
    )
    report = validate_template_semantic_quality(
        body_text=otp_body,
        declared_category="AUTHENTICATION",
        client="bajaj",
    )
    assert report.ai_checked is True
    assert report.predicted_category == "AUTHENTICATION"
    assert report.category_mismatch is False


def test_typesafe_rejection_risk_scoring():
    """Verify Score primitive returns calibrated risk levels."""
    # Under-specified, isolated variables template
    sparse_body = "Hello {{1}}, look at {{2}}"
    report = validate_template_semantic_quality(
        body_text=sparse_body,
        declared_category="MARKETING",
        client="bajaj",
    )
    assert report.ai_checked is True
    assert report.rejection_risk_score > 0.5
    assert report.floating_variables_probability > 0.40


def test_comprehensive_pre_submission_pipeline():
    """Verify grammar_checker.validate_template_pre_submission combines linter, technical rules, and AI."""
    raw_body = "congratualtions {{1}}!! you are eligibile for a pre-approved personal loan of Rs. {{2}}."
    res = validate_template_pre_submission(
        body_text=raw_body,
        declared_category="UTILITY",
        use_ai=True,
    )

    # Grammar typo fix
    assert "congratulations" in res["cleaned_body"].lower()
    assert "eligible" in res["cleaned_body"].lower()
    assert len(res["grammar_warnings"]) >= 1

    # AI category check
    assert res["predicted_category"] == "MARKETING"
    assert res["category_mismatch"] is True
    assert len(res["all_warnings"]) >= 2
    assert res["ai_report"] is not None


def test_graceful_fallback_when_ai_disabled():
    """Verify validator gracefully produces valid result when allow_ai=False or no API key."""
    body = "Dear {{1}}, your loan repayment is due on {{2}}."
    report = validate_template_semantic_quality(
        body_text=body,
        declared_category="UTILITY",
        allow_ai=False,
    )
    assert report.ai_checked is False
    assert report.is_safe_to_submit is True
    assert report.predicted_category == "UTILITY"
    assert report.category_mismatch is False


def test_async_typesafe_validator():
    """Verify async validator function runs without blocking."""
    body = "Your OTP code for verification is {{1}}."
    report = asyncio.run(
        async_validate_template_semantic_quality(
            body_text=body,
            declared_category="AUTHENTICATION",
        )
    )
    assert report.ai_checked is True
    assert report.predicted_category == "AUTHENTICATION"


def test_submission_client_validate_ai_gate():
    """Verify submit_template with validate_ai=True blocks submissions with critical AI compliance errors."""
    sub = TemplateSubmission(
        client="bajaj",
        channel="whatsapp",
        template_name="test_promo_as_utility_block",
        language="en",
        category="UTILITY",  # Mismatched!
        waba_id="286109054585247",
        source_ref="row_99",
        components=[
            TemplateComponent(
                type="BODY",
                text="Claim your pre-approved loan of Rs. 10 Lakhs right now! Click here for 50% discount.",
            )
        ],
    )

    result = submit_template(sub, client="bajaj", validate_ai=True)
    assert result.status == SubmissionStatus.FAILED
    assert result.approval_status == ApprovalStatus.REJECTED
    assert "BLOCKED (AI Pre-Submission Compliance)" in str(result.error)
