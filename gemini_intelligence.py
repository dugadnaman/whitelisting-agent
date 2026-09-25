"""
Google Gemini 3.1 Flash-Lite Semantic Decision Engine for Karix Whitelisting.
Provides constrained structured judgments:
1. Meta WhatsApp Category Classification (MARKETING, UTILITY, AUTHENTICATION).
2. Regional Language Code Identification across English and Indian languages.
3. Template-validity classification.
4. Robust local classification fallback if uncredentialed or offline.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests
from config import _load_env_file

logger = logging.getLogger(__name__)

_DECISION_CACHE: dict[str, dict[str, Any]] = {}
DEFAULT_MODEL = "gemini-3.1-flash-lite"


def get_gemini_api_key() -> str:
    """Retrieve the Google Gemini API key from the process environment or .env."""
    _load_env_file()
    return (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    ).strip()


def analyze_template_semantics(
    text: str,
    summary: str = "",
    sheet_name: str = "",
    timeout: int = 10,
) -> dict[str, Any]:
    """
    Use Gemini only for bounded semantic decisions:
    - category classification
    - language classification
    - template-validity classification

    The model is explicitly forbidden from generating, rewriting, extracting, or
    suggesting customer-facing words. Any unexpected text fields in its response
    are discarded before the result reaches template assembly.
    """
    clean_text = text.strip()
    if not clean_text:
        return {
            "category": "MARKETING",
            "language": "en",
            "is_valid_template": False,
            "source": "empty",
        }

    # In-memory cache check to prevent redundant API calls for identical copies
    cache_key = f"{summary[:40]}_{sheet_name}_{clean_text[:120]}"
    if cache_key in _DECISION_CACHE:
        return _DECISION_CACHE[cache_key]

    api_key = get_gemini_api_key()
    if not api_key:
        return _heuristic_decision(clean_text, summary, sheet_name)

    prompt = (
        f"You are a strict compliance auditor for Meta WhatsApp and Karix templates.\n"
        f"Return classifications only. The application owns all customer-facing content.\n"
        f"MUST NOT generate, rewrite, summarize, translate, suggest, or extract even one customer-facing word.\n"
        f"MUST NOT return body text, header text, CTA text, URLs, sample values, or any other content.\n\n"
        f"TICKET SUMMARY: {summary}\n"
        f"SHEET NAME: {sheet_name}\n"
        f"TEMPLATE TEXT:\n\"\"\"\n{clean_text[:1200]}\n\"\"\"\n\n"
        f"Allowed decisions:\n"
        f"1. category: 'UTILITY' for account alerts, order receipts, approval status, EMI reminders, billing, or operational updates.\n"
        f"   'AUTHENTICATION' for OTP or login verification codes.\n"
        f"   'MARKETING' for loan offers, discounts, promotions, product announcements.\n"
        f"2. language: choose the matching supported language code.\n"
        f"3. is_valid_template: true if this is customer-facing marketing/utility copy, false if internal notes/codes."
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "response_schema": {
                "type": "OBJECT",
                "properties": {
                    "category": {
                        "type": "STRING",
                        "enum": ["MARKETING", "UTILITY", "AUTHENTICATION"],
                    },
                    "language": {
                        "type": "STRING",
                        "enum": ["en", "hi", "gu", "pa", "mr", "bn", "ta", "te", "kn", "ml"],
                    },
                    "is_valid_template": {"type": "BOOLEAN"},
                },
                "required": ["category", "language", "is_valid_template"],
            },
        },
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{DEFAULT_MODEL}:generateContent?key={api_key}"
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.ok:
            data = resp.json()
            raw_json = data["candidates"][0]["content"]["parts"][0]["text"]
            raw_decision = json.loads(raw_json)
            category = raw_decision.get("category")
            language = raw_decision.get("language")
            is_valid = raw_decision.get("is_valid_template")
            if (
                category not in {"MARKETING", "UTILITY", "AUTHENTICATION"}
                or language not in {"en", "hi", "gu", "pa", "mr", "bn", "ta", "te", "kn", "ml"}
                or not isinstance(is_valid, bool)
            ):
                raise ValueError("Gemini returned an invalid classification response")
            decision = {
                "category": category,
                "language": language,
                "is_valid_template": is_valid,
                "source": "gemini_3.1_flash_lite",
            }
            _DECISION_CACHE[cache_key] = decision
            return decision

    except Exception as exc:
        logger.warning("Gemini semantic analysis fallback to local classifications: %s", exc)
    fallback = _heuristic_decision(clean_text, summary, sheet_name)
    _DECISION_CACHE[cache_key] = fallback
    return fallback


def _heuristic_decision(text: str, summary: str = "", sheet_name: str = "") -> dict[str, Any]:
    """Deterministic local fallback when Gemini is offline or uncredentialed."""
    from briefing_parser import detect_category, detect_language, is_valid_template_copy

    cat = detect_category(summary, text, sheet_name)
    lang = detect_language(text, sheet_name)
    valid = is_valid_template_copy(text)

    return {
        "category": cat,
        "language": lang,
        "is_valid_template": valid,
        "source": "local_heuristics",
    }
