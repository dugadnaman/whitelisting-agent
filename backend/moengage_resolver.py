"""
TypeSafe AI MoEngage Semantic Resolver.
Enhances the Karix-to-MoEngage sync and campaign staging pipeline:
1. Semantic Duplicate Detection (Noul primitive):
   Evaluates if an approved Karix template duplicates an existing MoEngage template,
   preventing redundant template registrations caused by minor naming or whitespace differences.
2. MoEngage Attribute Resolver (Choice primitive):
   Maps positional parameters ({{1}}, {{2}}) to verified MoEngage personalization tags
   (e.g. {{UserAttribute['first_name']}}, {{UserAttribute['emi_amount']}}).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from config import _load_env_file

logger = logging.getLogger(__name__)

_load_env_file()

# Standard MoEngage User & Custom Attributes mapping
MOENGAGE_ATTRIBUTE_MAP: dict[str, str] = {
    "USER_FIRST_NAME": "UserAttribute['first_name']",
    "USER_FULL_NAME": "UserAttribute['name']",
    "USER_EMI_AMOUNT": "UserAttribute['emi_amount']",
    "USER_LOAN_AMOUNT": "UserAttribute['loan_amount']",
    "USER_DUE_DATE": "UserAttribute['due_date']",
    "USER_LOAN_ACCOUNT": "UserAttribute['loan_account_no']",
    "USER_INTEREST_RATE": "UserAttribute['interest_rate']",
    "USER_PAYMENT_URL": "UserAttribute['payment_url']",
    "USER_TENURE_MONTHS": "UserAttribute['tenure_months']",
    "GENERIC_CUSTOM_ATTR": "CustomAttribute['custom_param']",
}

MOENGAGE_ATTRIBUTE_CRITERIA: dict[str, str] = {
    "USER_FIRST_NAME": "Customer first name or friendly name (e.g. Rahul, Priya)",
    "USER_FULL_NAME": "Customer complete name (e.g. Rahul Sharma, Priya Nair)",
    "USER_EMI_AMOUNT": "Monthly installment, EMI, or repayment fee amount (e.g. 15,000, 3,200)",
    "USER_LOAN_AMOUNT": "Principal sanctioned loan amount or credit limit (e.g. 5,00,000, 25,000)",
    "USER_DUE_DATE": "Payment due date, schedule date, or deadline (e.g. 15th Oct, 05/11/2026)",
    "USER_LOAN_ACCOUNT": "Loan account number, masked bank account, or agreement reference (e.g. TCF1234, XX9876)",
    "USER_INTEREST_RATE": "Interest percentage, ROI, or discount rate (e.g. 9.99, 10.5%)",
    "USER_PAYMENT_URL": "Payment link, portal web address, or personalized destination URL",
    "USER_TENURE_MONTHS": "Duration of loan, tenure, or number of EMIs (e.g. 24, 36)",
    "GENERIC_CUSTOM_ATTR": "Any generic code, identifier, or other custom attribute",
}


@dataclass
class AttributeMappingResult:
    """Mapping of a single positional variable to a MoEngage personalization tag."""

    original_variable: str  # e.g. "{{1}}"
    semantic_type: str  # e.g. "USER_FIRST_NAME"
    attribute_name: str  # e.g. "UserAttribute['first_name']"
    attribute_tag: str  # e.g. "{{UserAttribute['first_name']}}"
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MoEngageTemplateTranslation:
    """Result of converting positional variables in a template to MoEngage personalization tags."""

    original_text: str
    translated_text: str
    mappings: list[AttributeMappingResult] = field(default_factory=list)
    ai_resolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_text": self.original_text,
            "translated_text": self.translated_text,
            "mappings": [m.to_dict() for m in self.mappings],
            "ai_resolved": self.ai_resolved,
        }


@dataclass
class DuplicateCheckResult:
    """Result of a semantic duplicate evaluation against existing MoEngage templates."""

    is_duplicate: bool = False
    probability: float = 0.0
    matched_template_name: str | None = None
    matched_template_id: str | None = None
    reason: str = "No duplicate detected"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_semantic_duplicate_pair(
    candidate_name: str,
    candidate_body: str,
    existing_name: str,
    existing_body: str,
    allow_ai: bool = True,
) -> float:
    """
    Evaluate whether a candidate template semantically duplicates an existing template.
    Returns probability of duplicate (0.0 to 1.0).
    """
    c_body_norm = re.sub(r"\s+", " ", candidate_body).strip().lower()
    e_body_norm = re.sub(r"\s+", " ", existing_body).strip().lower()

    # Exact normalized match
    if c_body_norm and c_body_norm == e_body_norm:
        return 1.0

    # Clean variables for comparison
    c_no_vars = re.sub(r"\{\{[^}]+\}\}", "", c_body_norm).strip()
    e_no_vars = re.sub(r"\{\{[^}]+\}\}", "", e_body_norm).strip()
    if c_no_vars and c_no_vars == e_no_vars:
        return 0.98

    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not allow_ai or not api_key:
        # Simple word intersection heuristic
        c_words = set(re.findall(r"\b\w{4,}\b", c_body_norm))
        e_words = set(re.findall(r"\b\w{4,}\b", e_body_norm))
        if not c_words or not e_words:
            return 0.0
        jaccard = len(c_words & e_words) / len(c_words | e_words)
        return round(jaccard, 2)

    try:
        from typesafe_sdk import Noul, TypeSafeClient

        with TypeSafeClient(api_key=api_key) as client:
            res = client.system_one(
                state={
                    "candidate_template": {"name": candidate_name, "body": candidate_body},
                    "existing_template": {"name": existing_name, "body": existing_body},
                },
                questions={
                    "is_duplicate": Noul(
                        instructions=(
                            "Do candidate_template and existing_template represent the exact same messaging content "
                            "and campaign offer, despite minor naming differences, trailing punctuation, or variable syntax?"
                        )
                    )
                },
            )
        return float(res.nouls["is_duplicate"].noul)
    except Exception as err:
        logger.warning("TypeSafe semantic duplicate comparison failed: %s", err)
        return 0.0


def find_semantic_duplicate(
    candidate_name: str,
    candidate_body: str,
    existing_templates: list[dict[str, Any]],
    threshold: float = 0.85,
    allow_ai: bool = True,
) -> DuplicateCheckResult:
    """
    Search a list of existing MoEngage templates to find if candidate template is a duplicate.
    Checks exact matches first (zero latency), then screens potential candidates with TypeSafe Noul.
    """
    cand_name_norm = candidate_name.strip().lower()
    cand_body_norm = re.sub(r"\s+", " ", candidate_body).strip().lower()

    # Fast-path 1: Exact Name or ID match
    for ex in existing_templates:
        ex_name = str(ex.get("name") or ex.get("display_name") or "").strip()
        ex_id = str(ex.get("meta_data", {}).get("template_id") or ex.get("id") or "").strip()
        if cand_name_norm and (cand_name_norm == ex_name.lower() or cand_name_norm == ex_id.lower()):
            return DuplicateCheckResult(
                is_duplicate=True,
                probability=1.0,
                matched_template_name=ex_name,
                matched_template_id=ex_id,
                reason="Exact template name or ID match in MoEngage",
            )

    # Fast-path 2: Pre-screen top candidate for AI evaluation
    candidates_to_score: list[tuple[float, dict[str, Any]]] = []
    c_words = set(re.findall(r"\b\w{4,}\b", cand_body_norm))

    for ex in existing_templates:
        data = ex.get("meta_data", {}).get("data", {})
        ex_body = str(data.get("description") or ex.get("description") or "").strip().lower()
        if not ex_body:
            continue
        ex_words = set(re.findall(r"\b\w{4,}\b", ex_body))
        overlap = len(c_words & ex_words) / max(1, len(c_words | ex_words))
        if overlap > 0.40:
            candidates_to_score.append((overlap, ex))

    candidates_to_score.sort(key=lambda x: x[0], reverse=True)

    # Evaluate highest overlapping candidates with TypeSafe Noul
    for _, ex in candidates_to_score[:2]:
        ex_name = str(ex.get("name") or ex.get("display_name") or "").strip()
        ex_id = str(ex.get("meta_data", {}).get("template_id") or ex.get("id") or "").strip()
        data = ex.get("meta_data", {}).get("data", {})
        ex_body = str(data.get("description") or ex.get("description") or "").strip()

        prob = check_semantic_duplicate_pair(
            candidate_name=candidate_name,
            candidate_body=candidate_body,
            existing_name=ex_name,
            existing_body=ex_body,
            allow_ai=allow_ai,
        )
        if prob >= threshold:
            return DuplicateCheckResult(
                is_duplicate=True,
                probability=prob,
                matched_template_name=ex_name,
                matched_template_id=ex_id,
                reason=f"Semantic duplicate detected with {prob * 100:.1f}% confidence",
            )

    return DuplicateCheckResult(is_duplicate=False, probability=0.0)


def resolve_moengage_attributes(
    template_text: str,
    allow_ai: bool = True,
) -> MoEngageTemplateTranslation:
    """
    Analyze template text and map all positional parameters ({{1}}, {{2}}, etc.)
    to verified MoEngage user attributes (e.g. {{UserAttribute['first_name']}}).
    Executes in a single batched TypeSafe Choice call.
    """
    if not template_text or not template_text.strip():
        return MoEngageTemplateTranslation(original_text=template_text, translated_text=template_text)

    var_matches = re.findall(r"\{\{\d+\}\}", template_text)
    if not var_matches:
        return MoEngageTemplateTranslation(original_text=template_text, translated_text=template_text)

    # Unique variables preserving order
    unique_vars: list[str] = []
    for v in var_matches:
        if v not in unique_vars:
            unique_vars.append(v)

    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()

    # Rule-based fallback if offline or no key
    if not allow_ai or not api_key:
        mappings = []
        translated = template_text
        fallback_cycle = [
            "UserAttribute['first_name']",
            "UserAttribute['emi_amount']",
            "UserAttribute['due_date']",
            "UserAttribute['loan_account_no']",
            "UserAttribute['payment_url']",
        ]
        for idx, var in enumerate(unique_vars):
            attr_name = fallback_cycle[idx % len(fallback_cycle)]
            tag = f"{{{{{attr_name}}}}}"
            mappings.append(
                AttributeMappingResult(
                    original_variable=var,
                    semantic_type="FALLBACK_DEFAULT",
                    attribute_name=attr_name,
                    attribute_tag=tag,
                    confidence=0.5,
                )
            )
            translated = translated.replace(var, tag)
        return MoEngageTemplateTranslation(
            original_text=template_text,
            translated_text=translated,
            mappings=mappings,
            ai_resolved=False,
        )

    try:
        from typesafe_sdk import Choice, TypeSafeClient

        questions = {}
        for idx, var in enumerate(unique_vars, start=1):
            q_key = f"var_{idx}"
            questions[q_key] = Choice(
                instructions=f"What MoEngage user attribute should replace variable {var} given its surrounding sentence context in the template?",
                criteria=MOENGAGE_ATTRIBUTE_CRITERIA,
            )

        with TypeSafeClient(api_key=api_key) as client:
            res = client.system_one(
                state={"template_text": template_text},
                questions=questions,
            )

        mappings = []
        translated = template_text
        for idx, var in enumerate(unique_vars, start=1):
            q_key = f"var_{idx}"
            if q_key in res.choices:
                choice_val = str(res.choices[q_key].choice).upper()
                conf = float(res.choices[q_key].confidence)
                attr_name = MOENGAGE_ATTRIBUTE_MAP.get(choice_val, "CustomAttribute['custom_param']")
            else:
                choice_val = "GENERIC_CUSTOM_ATTR"
                conf = 0.5
                attr_name = "CustomAttribute['custom_param']"

            tag = f"{{{{{attr_name}}}}}"
            mappings.append(
                AttributeMappingResult(
                    original_variable=var,
                    semantic_type=choice_val,
                    attribute_name=attr_name,
                    attribute_tag=tag,
                    confidence=conf,
                )
            )
            translated = translated.replace(var, tag)

        return MoEngageTemplateTranslation(
            original_text=template_text,
            translated_text=translated,
            mappings=mappings,
            ai_resolved=True,
        )

    except Exception as err:
        logger.warning("TypeSafe MoEngage attribute resolution failed, using fallback: %s", err)
        return resolve_moengage_attributes(template_text, allow_ai=False)
