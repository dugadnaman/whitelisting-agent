"""
TypeSafe AI Semantic Template Validator for Meta WhatsApp & RCS.
Uses TypeSafe System One models (Jev) to evaluate templates as typed programming primitives:
- Category Classification (Choice primitive): Identifies UTILITY, MARKETING, or AUTHENTICATION.
- Rejection Risk Scorer (Score primitive): Evaluates Meta rejection probability on an ordered scale.
- Variable Context & Policy Compliance (Noul primitive): Detects floating parameters, promotional text inside utility, and policy violations.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any

from config import _load_env_file

logger = logging.getLogger(__name__)

# Ensure environment variables are loaded
_load_env_file()


@dataclass
class SemanticValidationReport:
    """Detailed outcome of a TypeSafe System One pre-submission inspection."""

    ai_checked: bool = False
    declared_category: str = "MARKETING"
    predicted_category: str = "MARKETING"
    category_confidence: float = 0.0
    category_probabilities: dict[str, float] = field(default_factory=dict)
    category_mismatch: bool = False
    rejection_risk_score: float = 0.0  # 0.0 (Safe) to 3.0 (High Risk)
    rejection_risk_level: str = "SAFE"  # SAFE, LOW, MODERATE, HIGH
    promotional_probability: float = 0.0
    floating_variables_probability: float = 0.0
    warnings: list[dict[str, Any]] = field(default_factory=list)
    is_safe_to_submit: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert report to standard serializable dictionary."""
        return asdict(self)


def _determine_risk_level(score: float) -> str:
    """Map numeric score (0-3) to discrete risk band."""
    if score < 0.75:
        return "SAFE"
    if score < 1.75:
        return "LOW"
    if score < 2.35:
        return "MODERATE"
    return "HIGH"


def _build_typesafe_questions() -> dict[str, Any]:
    """Define calibrated System One questions for WhatsApp template validation."""
    from typesafe_sdk import Choice, Noul, Score

    return {
        "category": Choice(
            instructions="Classify the WhatsApp template into its official Meta category.",
            criteria={
                "AUTHENTICATION": "OTP codes, one-time passwords, login verification, account security tokens",
                "UTILITY": "Transaction receipts, payment reminders, billing statements, existing account/loan service updates",
                "MARKETING": "Promotional offers, sales pitches, pre-approved loan advertisements, discounts, product recommendations",
            },
        ),
        "rejection_risk": Score(
            instructions="Evaluate the risk of Meta rejecting this template due to formatting or policy rules.",
            criteria=[
                "Safe: fully compliant with Meta policies and standard format",
                "Low risk: minor formatting or phrasing ambiguities",
                "Moderate risk: possible category mismatch or sparse context around variables",
                "High risk: policy violation, deceptive claims, or critical formatting defects",
            ],
        ),
        "promotional": Noul(
            instructions="Does this template contain promotional marketing, sales offers, or loan upsells?"
        ),
        "floating_variables": Noul(
            instructions="Are any variables in the template lacking clear surrounding context, isolated, or placed at the very end as a trailing variable?"
        ),
    }


def _process_typesafe_response(
    res: Any,
    declared_category: str,
    body_text: str,
) -> SemanticValidationReport:
    """Extract and analyze predictions from TypeSafe response."""
    cat_result = res.choices["category"]
    risk_result = res.scores["rejection_risk"]
    promo_prob = res.nouls["promotional"].noul
    floating_prob = res.nouls["floating_variables"].noul

    pred_category = str(cat_result.choice).upper()
    cat_conf = float(cat_result.confidence)
    cat_probs = {k.upper(): float(v) for k, v in cat_result.probabilities.items()}

    norm_declared = (declared_category or "MARKETING").strip().upper()
    risk_score = float(risk_result.score)
    risk_level = _determine_risk_level(risk_score)

    warnings: list[dict[str, Any]] = []

    # 1. Category Mismatch Detection
    is_mismatch = False
    if norm_declared != pred_category and cat_conf >= 0.70:
        is_mismatch = True
        severity = "error" if (norm_declared == "UTILITY" and pred_category == "MARKETING") else "warning"
        warnings.append(
            {
                "type": "META_CATEGORY_MISMATCH",
                "severity": severity,
                "issue": (
                    f"Template declared as '{norm_declared}', but semantic analysis classified it as "
                    f"'{pred_category}' with {cat_conf * 100:.1f}% confidence. "
                    + (
                        "Submitting marketing copy as UTILITY is the #1 cause of Meta rejections or sudden 10x cost escalations."
                        if norm_declared == "UTILITY"
                        else "Template may be miscategorized."
                    )
                ),
                "recommendation": f"Update category to '{pred_category}' prior to submission, or modify text to match '{norm_declared}'.",
                "predicted_category": pred_category,
                "confidence": cat_conf,
            }
        )
    elif norm_declared == "UTILITY" and promo_prob >= 0.75:
        # Subtle promotional leak into transactional template
        is_mismatch = True
        warnings.append(
            {
                "type": "PROMOTIONAL_IN_UTILITY",
                "severity": "error",
                "issue": (
                    f"Template is marked UTILITY, but contains strong promotional elements (promotional prob: {promo_prob * 100:.1f}%). "
                    "Meta strictly bans promotional discounts, offers, or upsell phrasing in Utility templates."
                ),
                "recommendation": "Switch category to MARKETING or remove promotional/upsell copy from this message.",
                "predicted_category": "MARKETING",
                "confidence": promo_prob,
            }
        )

    # 2. Rejection Risk Evaluation
    if risk_score >= 2.2:
        warnings.append(
            {
                "type": "HIGH_REJECTION_RISK",
                "severity": "error" if risk_score >= 2.5 else "warning",
                "issue": (
                    f"High probability of Meta rejection (Risk score: {risk_score:.2f}/3.0, Level: {risk_level}). "
                    "Template exhibits patterns frequently flagged during automated or manual Meta review."
                ),
                "recommendation": "Review message copy for clarity, ensure proper punctuation, and verify variable contexts.",
                "risk_score": risk_score,
                "risk_level": risk_level,
            }
        )

    # 3. Floating / Under-specified Variables
    if floating_prob >= 0.70:
        warnings.append(
            {
                "type": "FLOATING_VARIABLES_DETECTED",
                "severity": "warning",
                "issue": (
                    f"Template variables appear under-specified or lacking clear surrounding context "
                    f"(Floating probability: {floating_prob * 100:.1f}%). "
                    "Meta requires clear explanatory text preceding each parameter."
                ),
                "recommendation": "Ensure each parameter has an explicit label like 'EMI amount: Rs. {{1}}' rather than a detached {{1}}.",
                "probability": floating_prob,
            }
        )

    is_safe = not any(w.get("severity") == "error" for w in warnings)

    return SemanticValidationReport(
        ai_checked=True,
        declared_category=norm_declared,
        predicted_category=pred_category,
        category_confidence=cat_conf,
        category_probabilities=cat_probs,
        category_mismatch=is_mismatch,
        rejection_risk_score=risk_score,
        rejection_risk_level=risk_level,
        promotional_probability=promo_prob,
        floating_variables_probability=floating_prob,
        warnings=warnings,
        is_safe_to_submit=is_safe,
    )


def validate_template_semantic_quality(
    body_text: str,
    declared_category: str = "MARKETING",
    header_text: str | None = None,
    footer_text: str | None = None,
    buttons: list | None = None,
    client: str = "bajaj",
    allow_ai: bool = True,
) -> SemanticValidationReport:
    """
    Perform synchronous pre-submission validation with TypeSafe System One.
    Gracefully degrades to an offline report if no API key is present or on network error.
    """
    norm_declared = (declared_category or "MARKETING").strip().upper()

    if not body_text or not body_text.strip():
        return SemanticValidationReport(
            ai_checked=False,
            declared_category=norm_declared,
            is_safe_to_submit=False,
            warnings=[
                {
                    "type": "EMPTY_TEMPLATE_BODY",
                    "severity": "error",
                    "issue": "Template body text is empty.",
                    "recommendation": "Provide non-empty body text before submitting.",
                }
            ],
        )

    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not allow_ai or not api_key:
        logger.debug("TypeSafe AI validation skipped (allow_ai=%s, key_present=%s)", allow_ai, bool(api_key))
        return SemanticValidationReport(
            ai_checked=False,
            declared_category=norm_declared,
            predicted_category=norm_declared,
            is_safe_to_submit=True,
        )

    try:
        from typesafe_sdk import TypeSafeClient

        state: dict[str, Any] = {
            "template_body": body_text.strip(),
            "declared_category": norm_declared,
            "account_client": client,
        }
        if header_text:
            state["header"] = header_text.strip()
        if footer_text:
            state["footer"] = footer_text.strip()
        if buttons:
            btn_texts = []
            for b in buttons:
                if isinstance(b, dict):
                    btn_texts.append(b.get("text", ""))
                elif hasattr(b, "text"):
                    btn_texts.append(getattr(b, "text", ""))
            state["buttons"] = [t for t in btn_texts if t]

        questions = _build_typesafe_questions()

        with TypeSafeClient(api_key=api_key) as typesafe_client:
            res = typesafe_client.system_one(
                state=state,
                questions=questions,
            )

        return _process_typesafe_response(res, norm_declared, body_text)

    except Exception as e:
        logger.warning("TypeSafe semantic validation encountered an error: %s", e, exc_info=True)
        return SemanticValidationReport(
            ai_checked=False,
            declared_category=norm_declared,
            predicted_category=norm_declared,
            is_safe_to_submit=True,
            error=str(e),
        )


async def async_validate_template_semantic_quality(
    body_text: str,
    declared_category: str = "MARKETING",
    header_text: str | None = None,
    footer_text: str | None = None,
    buttons: list | None = None,
    client: str = "bajaj",
    allow_ai: bool = True,
) -> SemanticValidationReport:
    """
    Perform asynchronous pre-submission validation with TypeSafe System One.
    Gracefully degrades to offline check on network or configuration errors.
    """
    norm_declared = (declared_category or "MARKETING").strip().upper()

    if not body_text or not body_text.strip():
        return SemanticValidationReport(
            ai_checked=False,
            declared_category=norm_declared,
            is_safe_to_submit=False,
            warnings=[
                {
                    "type": "EMPTY_TEMPLATE_BODY",
                    "severity": "error",
                    "issue": "Template body text is empty.",
                    "recommendation": "Provide non-empty body text before submitting.",
                }
            ],
        )

    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not allow_ai or not api_key:
        return SemanticValidationReport(
            ai_checked=False,
            declared_category=norm_declared,
            predicted_category=norm_declared,
            is_safe_to_submit=True,
        )

    try:
        from typesafe_sdk import AsyncTypeSafeClient

        state: dict[str, Any] = {
            "template_body": body_text.strip(),
            "declared_category": norm_declared,
            "account_client": client,
        }
        if header_text:
            state["header"] = header_text.strip()
        if footer_text:
            state["footer"] = footer_text.strip()
        if buttons:
            btn_texts = []
            for b in buttons:
                if isinstance(b, dict):
                    btn_texts.append(b.get("text", ""))
                elif hasattr(b, "text"):
                    btn_texts.append(getattr(b, "text", ""))
            state["buttons"] = [t for t in btn_texts if t]

        questions = _build_typesafe_questions()

        async with AsyncTypeSafeClient(api_key=api_key) as typesafe_client:
            res = await typesafe_client.system_one(
                state=state,
                questions=questions,
            )

        return _process_typesafe_response(res, norm_declared, body_text)

    except Exception as e:
        logger.warning("Async TypeSafe semantic validation encountered an error: %s", e, exc_info=True)
        return SemanticValidationReport(
            ai_checked=False,
            declared_category=norm_declared,
            predicted_category=norm_declared,
            is_safe_to_submit=True,
            error=str(e),
        )
