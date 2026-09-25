"""
Google Gemini 3.1 Flash-Lite Semantic Decision Engine for Karix Whitelisting.
Provides supreme structured judgments on identified template components:
1. Meta WhatsApp Category Classification (MARKETING, UTILITY, AUTHENTICATION).
2. Regional Language Code Identification across English and Indian languages.
3. Template Completeness & Readiness Adjudication (identifies missing parts or truncation).
4. Component Identification & Metadata Separation:
   - Evaluates candidate headers/titles to identify whether they are internal names/artifacts
     (e.g. 'LAS_Whitelisting', 'SWCM_59', ticket keys, sheet names) vs genuine customer-facing headlines.
   - Rejects internal workflow identifiers so they never leak into customer-facing headers.
5. Robust local deterministic fallback if uncredentialed or offline.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import requests

from config import _load_env_file

logger = logging.getLogger(__name__)

_DECISION_CACHE: dict[str, dict[str, Any]] = {}
DEFAULT_MODEL = "gemini-3.1-flash-lite"


def get_gemini_api_key() -> str:
    """Retrieve the Google Gemini API key from the process environment or .env."""
    _load_env_file()
    return (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()


def is_internal_identifier(name: str | None, summary: str = "", sheet_name: str = "") -> bool:
    """
    Detect whether a candidate header, card title, or cell label is an internal workflow artifact
    (e.g. 'LAS_Whitelisting', 'SWCM_59', 'TCN-536', 'Sheet1', 'Campaign 1', 'Sep Base Refill')
    rather than a genuine customer-facing headline.
    """
    if not name or not name.strip():
        return False
    clean = name.strip()
    lower = clean.lower()

    # 1. Underscore-separated identifier format without natural spacing (e.g. LAS_Whitelisting, swcm_59_wa_1)
    if "_" in clean and not any(p in clean for p in (" ", "{{")):
        return True

    # 2. Jira ticket key patterns (e.g. SWCM-59, TCN-536, SWCM_58)
    if re.search(r"^[A-Z]{2,6}[-_]\d+", clean):
        return True

    # 3. Known internal operational and workflow terms
    internal_keywords = (
        "whitelisting",
        "campaign execution",
        "pos refill",
        "sep base",
        "standalone card",
        "execution format",
        "creative_",
        "card_",
        "cell_",
        "template_",
        "draft_",
        "sheet1",
        "sheet2",
    )
    if any(k in lower for k in internal_keywords):
        return True

    # 4. Matches ticket summary or creative base name (internal campaign label)
    if summary:
        s_clean = summary.strip().lower()
        if lower == s_clean or (len(clean) >= 6 and clean.lower() in s_clean and "_" in clean):
            return True

    # 5. Matches sheet name exactly
    if sheet_name:
        sh_clean = sheet_name.strip().lower()
        if lower == sh_clean:
            return True

    return False


def _derive_clean_card_title_heuristic(text: str) -> str:
    """Derive a professional, customer-facing card title from message body content."""
    if not text or not text.strip():
        return "Important Notice"
    low = text.lower()
    if "ltv" in low or "loan against" in low or "mutual fund" in low or "pledge" in low or "shares" in low:
        return "Notice: Revision in LTV"
    if "personal loan" in low or "pre-approved" in low or "instant funds" in low:
        return "Special Personal Loan Offer"
    if "home loan" in low or "property" in low:
        return "Special Home Loan Offer"
    if "business loan" in low:
        return "Business Loan Opportunity"
    if "emi" in low or "due date" in low or "overdue" in low or "payment" in low:
        return "Important Payment Reminder"
    if "otp" in low or "verification code" in low or "security" in low:
        return "Account Security Alert"
    if "credit card" in low or "card" in low:
        return "Exclusive Card Offer"
    return "Important Customer Notice"


def analyze_template_semantics(
    text: str,
    summary: str = "",
    sheet_name: str = "",
    candidate_header: str | None = None,
    candidate_title: str | None = None,
    candidate_cta_text: str | None = None,
    candidate_cta_url: str | None = None,
    channel: str = "WA",
    timeout: int = 10,
) -> dict[str, Any]:
    """
    Supreme Gemini semantic decision engine for Karix Whitelisting.
    Adjudicates identified components without fabricating customer words:
    - Category & Language classification
    - Template Completeness & Readiness scoring
    - Header/Title Adjudication: rejects internal names (e.g. 'LAS_Whitelisting')
    - CTA genuineness
    """
    clean_text = text.strip()
    if not clean_text:
        return {
            "category": "MARKETING",
            "language": "en",
            "is_valid_template": False,
            "is_complete": False,
            "completeness_score": 0.0,
            "missing_components": ["body"],
            "completeness_notes": "Empty text body.",
            "is_candidate_header_genuine": False,
            "is_internal_name": False,
            "header_rejection_reason": None,
            "customer_facing_title": None,
            "is_cta_genuine": False,
            "source": "empty",
        }

    cand_header = candidate_header or candidate_title or ""
    cache_key = f"{summary[:30]}_{sheet_name[:20]}_{channel}_{cand_header[:30]}_{clean_text[:100]}"
    if cache_key in _DECISION_CACHE:
        return _DECISION_CACHE[cache_key]

    api_key = get_gemini_api_key()
    if not api_key:
        decision = _heuristic_decision(
            clean_text,
            summary=summary,
            sheet_name=sheet_name,
            candidate_header=candidate_header,
            candidate_title=candidate_title,
            candidate_cta_text=candidate_cta_text,
            candidate_cta_url=candidate_cta_url,
            channel=channel,
        )
        _DECISION_CACHE[cache_key] = decision
        return decision

    prompt = (
        f"You are a supreme compliance and quality auditor for Meta WhatsApp and Karix templates.\n"
        f"Analyze the identified template components and return structured semantic judgments.\n"
        f"MUST NOT generate, rewrite, summarize, or translate customer copy.\n"
        f"Adjudicate ONLY the identified elements provided:\n\n"
        f"TICKET CONTEXT: {summary}\n"
        f"SHEET CONTEXT: {sheet_name}\n"
        f"CHANNEL: {channel}\n"
        f"CANDIDATE HEADER/TITLE: {cand_header or 'None'}\n"
        f"CANDIDATE CTA: {candidate_cta_text or 'None'} (URL: {candidate_cta_url or 'None'})\n"
        f'TEMPLATE CONTENT BODY:\n"""\n{clean_text[:1200]}\n"""\n\n'
        f"Adjudication Rules:\n"
        f"1. category: 'UTILITY' for operational updates, account alerts, receipts, EMI reminders, billing, LTV revisions, or regulatory notifications.\n"
        f"   'AUTHENTICATION' for OTP or login verification codes.\n"
        f"   'MARKETING' for loan offers, discounts, promotions, product announcements.\n"
        f"2. language: choose matching supported language code ('en', 'hi', 'gu', 'pa', 'mr', 'bn', 'ta', 'te', 'kn', 'ml').\n"
        f"3. is_valid_template: true if this is genuine customer-facing copy; false if internal notes, error logs, or code.\n"
        f"4. is_complete: true if the message body is a complete, grammatically coherent customer communication (not cut off mid-sentence, not placeholder-only).\n"
        f"5. completeness_score: float from 0.0 to 1.0 evaluating template completeness.\n"
        f"6. missing_components: list of missing elements if any, e.g. ['cta_url'], ['brand_signoff'], or empty list if complete.\n"
        f"7. completeness_notes: concise rationale regarding completeness.\n"
        f"8. is_candidate_header_genuine:\n"
        f"   STRICT RULE: Check if CANDIDATE HEADER/TITLE is genuine customer-facing headline copy, or if it is an internal identifier.\n"
        f"   If CANDIDATE HEADER/TITLE contains underscores (e.g. 'LAS_Whitelisting'), matches ticket/sheet names, contains operational terms like 'whitelisting', or is NOT present in the content body and represents internal metadata, you MUST set is_candidate_header_genuine: false and is_internal_name: true.\n"
        f"9. is_internal_name: true if the candidate header/title is an internal workflow or campaign label.\n"
        f"10. header_rejection_reason: explanation if rejected (e.g. \"'LAS_Whitelisting' is an internal campaign/ticket identifier, not customer copy\"), or null if genuine.\n"
        f"11. customer_facing_title: If channel is RCS and requires a card title, provide a concise, professional customer-facing headline derived strictly from the topic in the content body (e.g. 'Notice: Revision in LTV' or 'Important Loan Update'). If no headline is appropriate or channel is WA, return null.\n"
        f"12. is_cta_genuine: true if candidate CTA is a genuine customer action button (e.g. 'Apply Now', 'Regularise Facility', 'Explore Now')."
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
                    "is_complete": {"type": "BOOLEAN"},
                    "completeness_score": {"type": "NUMBER"},
                    "missing_components": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "completeness_notes": {"type": "STRING"},
                    "is_candidate_header_genuine": {"type": "BOOLEAN"},
                    "is_internal_name": {"type": "BOOLEAN"},
                    "header_rejection_reason": {"type": "STRING"},
                    "customer_facing_title": {"type": "STRING"},
                    "is_cta_genuine": {"type": "BOOLEAN"},
                },
                "required": [
                    "category",
                    "language",
                    "is_valid_template",
                    "is_complete",
                    "completeness_score",
                    "is_candidate_header_genuine",
                    "is_internal_name",
                ],
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

            # Always verify internal name flag against deterministic guard
            is_internal = bool(
                raw_decision.get("is_internal_name")
                or is_internal_identifier(cand_header, summary=summary, sheet_name=sheet_name)
            )
            is_genuine = bool(raw_decision.get("is_candidate_header_genuine")) and not is_internal

            decision = {
                "category": category,
                "language": language,
                "is_valid_template": is_valid,
                "is_complete": bool(raw_decision.get("is_complete", True)),
                "completeness_score": float(raw_decision.get("completeness_score", 1.0)),
                "missing_components": list(raw_decision.get("missing_components") or []),
                "completeness_notes": str(raw_decision.get("completeness_notes") or ""),
                "is_candidate_header_genuine": is_genuine,
                "is_internal_name": is_internal,
                "header_rejection_reason": raw_decision.get("header_rejection_reason")
                or (f"'{cand_header}' is an internal identifier, not customer copy" if is_internal else None),
                "customer_facing_title": raw_decision.get("customer_facing_title"),
                "is_cta_genuine": bool(raw_decision.get("is_cta_genuine", True)),
                "source": "gemini_3.1_flash_lite",
            }
            _DECISION_CACHE[cache_key] = decision
            return decision
    except Exception as exc:
        logger.warning("Gemini semantic analysis fallback to local classifications: %s", exc)

    fallback = _heuristic_decision(
        clean_text,
        summary=summary,
        sheet_name=sheet_name,
        candidate_header=candidate_header,
        candidate_title=candidate_title,
        candidate_cta_text=candidate_cta_text,
        candidate_cta_url=candidate_cta_url,
        channel=channel,
    )
    _DECISION_CACHE[cache_key] = fallback
    return fallback


def _heuristic_decision(
    text: str,
    summary: str = "",
    sheet_name: str = "",
    candidate_header: str | None = None,
    candidate_title: str | None = None,
    candidate_cta_text: str | None = None,
    candidate_cta_url: str | None = None,
    channel: str = "WA",
) -> dict[str, Any]:
    """Deterministic local fallback when Gemini is offline or uncredentialed."""
    from briefing_parser import detect_category, detect_language, is_valid_template_copy

    cat = detect_category(summary, text, sheet_name)
    lang = detect_language(text, sheet_name)
    valid = is_valid_template_copy(text)

    header_cand = candidate_header or candidate_title or ""
    is_internal = is_internal_identifier(header_cand, summary=summary, sheet_name=sheet_name)
    is_genuine_header = bool(header_cand and not is_internal and header_cand.lower() in text.lower())
    rejection_reason = (
        f"'{header_cand}' is an internal ticket or campaign identifier, not customer copy" if is_internal else None
    )

    has_min_len = len(text.strip()) >= 30
    ends_cleanly = text.strip()[-1] in (".", "!", "?", "-", "}", ">", ")", "।") if text.strip() else False
    has_signoff = any(k in text.lower() for k in ("-tata capital", "-bajaj", "tata capital", "bajaj finserv"))
    missing: list[str] = []
    if not has_signoff and "tata" not in text.lower() and "bajaj" not in text.lower():
        missing.append("brand_signoff")
    if candidate_cta_text and not candidate_cta_url:
        missing.append("cta_url")

    completeness_score = 1.0 if (has_min_len and ends_cleanly) else (0.7 if has_min_len else 0.4)
    is_complete = bool(has_min_len and ends_cleanly and valid)

    clean_title = None
    if channel.upper() == "RCS" and (is_internal or not header_cand):
        clean_title = _derive_clean_card_title_heuristic(text)

    return {
        "category": cat,
        "language": lang,
        "is_valid_template": valid,
        "is_complete": is_complete,
        "completeness_score": completeness_score,
        "missing_components": missing,
        "completeness_notes": "Template is complete and verified."
        if is_complete
        else "Template may be truncated or missing signoff.",
        "is_candidate_header_genuine": is_genuine_header,
        "is_internal_name": is_internal,
        "header_rejection_reason": rejection_reason,
        "customer_facing_title": clean_title,
        "is_cta_genuine": bool(candidate_cta_text and len(candidate_cta_text) <= 25),
        "source": "local_heuristics",
    }
