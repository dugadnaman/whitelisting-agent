import json

import gemini_intelligence
from briefing_parser import decompose_content, derive_clean_card_title
from gemini_intelligence import is_internal_identifier


class _GeminiDecisionResponse:
    ok = True

    def json(self):
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "category": "UTILITY",
                                        "language": "en",
                                        "is_valid_template": True,
                                        "is_complete": True,
                                        "completeness_score": 1.0,
                                        "missing_components": [],
                                        "completeness_notes": "Complete regulatory compliance notice.",
                                        "is_candidate_header_genuine": False,
                                        "is_internal_name": True,
                                        "header_rejection_reason": "'LAS_Whitelisting' is an internal campaign identifier, not customer copy.",
                                        "customer_facing_title": "Notice: Revision in LTV",
                                        "is_cta_genuine": True,
                                    }
                                )
                            }
                        ]
                    }
                }
            ]
        }


def test_gemini_supreme_decision_contract(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["payload"] = json
        return _GeminiDecisionResponse()

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini_intelligence.requests, "post", fake_post)
    gemini_intelligence._DECISION_CACHE.clear()

    result = gemini_intelligence.analyze_template_semantics(
        "Pursuant to the RBI's Clarification vide FAQ dated 15th Sept 2026, the applicable maximum LTV has been revised to 50%. -Tata Capital",
        summary="LAS_Whitelisting",
        candidate_header="LAS_Whitelisting",
        channel="RCS",
    )

    assert result["category"] == "UTILITY"
    assert result["language"] == "en"
    assert result["is_valid_template"] is True
    assert result["is_complete"] is True
    assert result["is_candidate_header_genuine"] is False
    assert result["is_internal_name"] is True
    assert result["header_rejection_reason"] == "'LAS_Whitelisting' is an internal campaign identifier, not customer copy."
    assert result["customer_facing_title"] == "Notice: Revision in LTV"
    assert result["source"] == "gemini_3.1_flash_lite"

    schema = captured["payload"]["generationConfig"]["response_schema"]
    required_props = {
        "category",
        "language",
        "is_valid_template",
        "is_complete",
        "completeness_score",
        "is_candidate_header_genuine",
        "is_internal_name",
    }
    assert required_props.issubset(set(schema["properties"]))
    prompt_text = captured["payload"]["contents"][0]["parts"][0]["text"]
    assert "LAS_Whitelisting" in prompt_text
    assert "MUST NOT generate, rewrite, summarize, or translate customer copy" in prompt_text


def test_las_whitelisting_detected_as_internal_identifier():
    assert is_internal_identifier("LAS_Whitelisting") is True
    assert is_internal_identifier("swcm_59_las_whitelisting_rcs_2") is True
    assert is_internal_identifier("SWCM-59") is True
    assert is_internal_identifier("TCN-536") is True
    assert is_internal_identifier("Sep_Base_Refill") is True
    assert is_internal_identifier("Whitelisting_Batch") is True
    assert is_internal_identifier("Sheet1") is True

    # Real customer headings must not be marked internal
    assert is_internal_identifier("Important Notice: Revision in LTV") is False
    assert is_internal_identifier("Special Festive Personal Loan Offer") is False
    assert is_internal_identifier("Payment Due Reminder") is False


def test_las_whitelisting_rejected_from_template_heading(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    gemini_intelligence._DECISION_CACHE.clear()
    swcm_body = (
        "Your Loan Against Mutual Funds facility is above 70% LTV. "
        "Regularise immediately to 70% through additional pledge/repayment Pursuant to the RBI's "
        "Clarification vide FAQ dated 15th September 2026, LTV is being revised from 70% to 50%. "
        "-Tata Capital"
    )

    result = decompose_content(
        swcm_body,
        explicit_header="LAS_Whitelisting",
        summary="LAS_Whitelisting",
    )

    # LAS_Whitelisting must NOT be the heading
    assert result["header_text"] is None
    assert result["is_complete"] is True
    assert result["completeness_score"] >= 0.7
    assert result["category"] == "UTILITY"


def test_rcs_card_title_derived_cleanly_from_body_topic():
    swcm_body_1 = (
        "Your Loan Against Mutual Funds facility is above 70% LTV. "
        "Regularise immediately to 70% through additional pledge/repayment. -Tata Capital"
    )
    swcm_body_2 = (
        "Pursuant to the RBI's Clarification vide FAQ dated 15th Sept 2026, the applicable "
        "maximum LTV for Loan Against Equity Mutual Funds has been revised to 50%."
    )
    promo_body = "Dear Customer, get instant Personal Loan up to Rs. 5 Lakhs at low interest rates. -Tata Capital"

    title_1 = derive_clean_card_title(swcm_body_1, account="tata")
    title_2 = derive_clean_card_title(swcm_body_2, account="tata")
    title_promo = derive_clean_card_title(promo_body, account="tata")

    assert title_1 == "Notice: Revision in LTV"
    assert title_2 == "Notice: Revision in LTV"
    assert title_promo == "Special Personal Loan Offer"
    assert "LAS_Whitelisting" not in (title_1, title_2, title_promo)


def test_parser_ignores_any_model_generated_text(monkeypatch):
    monkeypatch.setattr(
        gemini_intelligence,
        "analyze_template_semantics",
        lambda *args, **kwargs: {
            "category": "UTILITY",
            "language": "en",
            "is_valid_template": True,
            "is_complete": True,
            "completeness_score": 1.0,
            "is_candidate_header_genuine": False,
            "is_internal_name": True,
            "header_text": "MODEL GENERATED HEADER",
            "button_text": "MODEL GENERATED CTA",
        },
    )

    result = decompose_content(
        "Dear Customer, your payment is due. -Tata Capital",
        summary="model-text-is-forbidden",
    )

    assert result["header_text"] is None
    assert result["button_text"] != "MODEL GENERATED CTA"
    assert result["body"] == "Dear Customer, your payment is due. -Tata Capital"
