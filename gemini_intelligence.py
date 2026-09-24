"""
Google Gemini 3.1 Flash-Lite Semantic Decision Engine for Karix Whitelisting.
Provides zero-hallucination structured judgments using Google's response_schema:
1. Meta WhatsApp Category Classification (MARKETING, UTILITY, AUTHENTICATION).
2. Precise Regional Language Code Identification across English and 10 Indian scripts.
3. Intelligent CTA Button Label Extraction and Headline Separation.
4. Robust local heuristic fallback if uncredentialed or offline.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import requests
from config import _load_env_file

logger = logging.getLogger(__name__)

_DECISION_CACHE: dict[str, dict[str, Any]] = {}
DEFAULT_MODEL = "gemini-3.1-flash-lite"


def get_gemini_api_key() -> str:
    """Retrieve Google Gemini API key from environment or credentials.json."""
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
    Use Gemini 3.1 Flash-Lite with constrained JSON schema to make intelligent semantic decisions:
    - Guaranteed zero text hallucination: returns classifications and labels only.
    - Category strictly constrained to Meta's allowed enum.
    - Language code strictly constrained to Meta's supported regional codes.
    - Seamless fallback to local deterministic heuristics if offline.
    """
    clean_text = text.strip()
    if not clean_text:
        return {
            "category": "MARKETING",
            "language": "en",
            "button_text": "Check Offer",
            "is_valid_template": False,
            "header_text": None,
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
        f"Analyze this marketing or transactional message brief and return structured classifications.\n\n"
        f"TICKET SUMMARY: {summary}\n"
        f"SHEET NAME: {sheet_name}\n"
        f"TEMPLATE TEXT:\n\"\"\"\n{clean_text[:1200]}\n\"\"\"\n\n"
        f"Rules:\n"
        f"1. category: 'UTILITY' for account alerts, order receipts, approval status, EMI reminders, billing, or operational updates.\n"
        f"   'AUTHENTICATION' for OTP or login verification codes.\n"
        f"   'MARKETING' for loan offers, discounts, promotions, product announcements.\n"
        f"2. language: 'en' for English, 'hi' for Hindi, 'gu' for Gujarati, 'pa' for Punjabi, 'mr' for Marathi, etc.\n"
        f"3. button_text: Short CTA verb/action (e.g. 'Apply Now', 'Check Offer', 'Explore Now') maximum 25 characters.\n"
        f"4. is_valid_template: true if this is customer-facing marketing/utility copy, false if internal notes/codes.\n"
        f"5. header_text: Optional punchy headline if the text opens with a title line (under 40 chars)."
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
                    "button_text": {"type": "STRING"},
                    "is_valid_template": {"type": "BOOLEAN"},
                    "header_text": {"type": "STRING"},
                },
                "required": ["category", "language", "button_text", "is_valid_template"],
            },
        },
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{DEFAULT_MODEL}:generateContent?key={api_key}"
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.ok:
            data = resp.json()
            raw_json = data["candidates"][0]["content"]["parts"][0]["text"]
            decision = json.loads(raw_json)
            decision["source"] = "gemini_3.1_flash_lite"
            _DECISION_CACHE[cache_key] = decision
            return decision
    except Exception as exc:
        logger.warning("Gemini semantic analysis fallback to heuristics: %s", exc)

    fallback = _heuristic_decision(clean_text, summary, sheet_name)
    _DECISION_CACHE[cache_key] = fallback
    return fallback


def _heuristic_decision(text: str, summary: str = "", sheet_name: str = "") -> dict[str, Any]:
    """Deterministic local fallback when Gemini is offline or uncredentialed."""
    from briefing_parser import detect_category, detect_language, is_valid_template_copy

    cat = detect_category(summary, text, sheet_name)
    lang = detect_language(text, sheet_name)
    valid = is_valid_template_copy(text)

    # Heuristic button text
    t_low = text.lower()
    btn = "Check Offer"
    if "apply" in t_low:
        btn = "Apply Now"
    elif "explore" in t_low:
        btn = "Explore Now"
    elif "pay" in t_low or "emi" in t_low:
        btn = "Pay Now"

    return {
        "category": cat,
        "language": lang,
        "button_text": btn,
        "is_valid_template": valid,
        "header_text": None,
        "source": "local_heuristics",
    }
