import json

import gemini_intelligence
from briefing_parser import decompose_content


class _GeminiResponse:
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
                                        "header_text": "MODEL GENERATED HEADER",
                                        "button_text": "MODEL GENERATED CTA",
                                    }
                                )
                            }
                        ]
                    }
                }
            ]
        }


def test_gemini_contract_returns_classifications_only(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["payload"] = json
        return _GeminiResponse()

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini_intelligence.requests, "post", fake_post)
    gemini_intelligence._DECISION_CACHE.clear()

    result = gemini_intelligence.analyze_template_semantics(
        "Dear Customer, your payment is due.",
        summary="zero-generation-contract",
    )

    assert result == {
        "category": "UTILITY",
        "language": "en",
        "is_valid_template": True,
        "source": "gemini_3.1_flash_lite",
    }
    schema = captured["payload"]["generationConfig"]["response_schema"]
    assert set(schema["properties"]) == {"category", "language", "is_valid_template"}
    assert "MUST NOT generate" in captured["payload"]["contents"][0]["parts"][0]["text"]


def test_parser_ignores_any_model_generated_text(monkeypatch):
    monkeypatch.setattr(
        gemini_intelligence,
        "analyze_template_semantics",
        lambda *args, **kwargs: {
            "category": "UTILITY",
            "language": "en",
            "is_valid_template": True,
            "header_text": "MODEL GENERATED HEADER",
            "button_text": "MODEL GENERATED CTA",
        },
    )

    result = decompose_content(
        "Dear Customer, your payment is due.",
        summary="model-text-is-forbidden",
    )

    assert result["header_text"] is None
    assert result["button_text"] != "MODEL GENERATED CTA"
    assert result["body"] == "Dear Customer, your payment is due."
