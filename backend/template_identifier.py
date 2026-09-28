"""
Phase 1: WhatsApp & RCS Template Identification and Diffing Engine.

Compares a master catalog of templates (from CSV, Excel, or JSON briefs)
against live templates currently deployed on Karix / Meta WABA.

Classifies each master template as:
- WHITELISTED: Approved on Meta/Karix and ready for live blasts.
- NOT_WHITELISTED: Missing from Karix WABA entirely; requires submission.
- PENDING: Submitted to Karix/Meta, currently awaiting carrier/Meta review.
- REJECTED: Rejected by Meta/carrier; requires copy/variable remediation.
- CONTENT_DRIFT: Template exists by name, but approved live body differs from master.
"""

from __future__ import annotations

import difflib
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from loader import load_from_csv, load_from_excel, load_from_json
from models import TemplateSubmission
from submission_client import fetch_template_list

logger = logging.getLogger(__name__)


@dataclass
class TemplateDiscrepancyItem:
    """Detailed discrepancy assessment for a single master template."""

    template_name: str
    status: str  # WHITELISTED, NOT_WHITELISTED, PENDING, REJECTED, CONTENT_DRIFT, PAUSED
    category: str
    language: str
    master_body: str
    live_body: str = ""
    match_confidence: float = 0.0
    match_method: str = "NAME_EXACT"  # NAME_EXACT, SEMANTIC_AI, FUZZY_TOKEN, NONE
    diff_summary: str = ""
    live_fb_id: str | None = None
    live_status_raw: str | None = None
    action_required: str = "NONE"  # SUBMIT, REMEDIATE, WAIT, NONE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IdentificationReport:
    """Executive reconciliation report between master catalog and live WABA."""

    account: str
    total_master: int
    whitelisted_count: int
    missing_count: int
    pending_count: int
    rejected_count: int
    drift_count: int
    items: list[TemplateDiscrepancyItem] = field(default_factory=list)
    missing_templates: list[dict[str, Any]] = field(default_factory=list)
    summary_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "total_master": self.total_master,
            "whitelisted_count": self.whitelisted_count,
            "missing_count": self.missing_count,
            "pending_count": self.pending_count,
            "rejected_count": self.rejected_count,
            "drift_count": self.drift_count,
            "summary_notes": self.summary_notes,
            "items": [item.to_dict() for item in self.items],
            "missing_templates": self.missing_templates,
        }


def _extract_body_text(components: list | dict | str | None) -> str:
    """Extract the primary body text from template components."""
    if not components:
        return ""
    if isinstance(components, str):
        return components.strip()
    if isinstance(components, dict):
        if components.get("type") == "BODY":
            return str(components.get("text") or "").strip()
        return str(components.get("text") or components.get("body") or "").strip()

    for comp in components:
        if isinstance(comp, dict) and comp.get("type") == "BODY":
            return str(comp.get("text") or "").strip()
        if hasattr(comp, "type") and comp.type == "BODY":
            return str(getattr(comp, "text", "") or "").strip()

    # Fallback to first component with text
    for comp in components:
        txt = comp.get("text") if isinstance(comp, dict) else getattr(comp, "text", "")
        if txt:
            return str(txt).strip()
    return ""


def normalize_template_text(text: str) -> str:
    """
    Normalize template text for comparison:
    - Collapses variable placeholders ({{1}}, {{name}}, {#var#}) into standard token '<VAR>'
    - Normalizes multiple whitespaces and newlines
    - Standardizes quotes and dashes
    """
    if not text:
        return ""
    # Standardize curly braces & variable markers
    s = re.sub(r"\{\{[^}]+\}\}", "<VAR>", text)
    s = re.sub(r"\{#[^#]+#\}", "<VAR>", s)
    s = re.sub(r"<[^>]+>", "<VAR>", s)
    # Standardize whitespace
    s = re.sub(r"\s+", " ", s).strip()
    # Standardize quotes
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return s.lower()


def compute_text_similarity(text_a: str, text_b: str) -> float:
    """Compute normalized text similarity ratio (0.0 to 1.0)."""
    norm_a = normalize_template_text(text_a)
    norm_b = normalize_template_text(text_b)
    if not norm_a and not norm_b:
        return 1.0
    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0
    return round(difflib.SequenceMatcher(None, norm_a, norm_b).ratio(), 3)


def evaluate_semantic_equivalence_typesafe(master_text: str, live_text: str) -> tuple[bool, float, str]:
    """
    Use TypeSafe System One (Noul primitive) to determine if two template bodies
    are functionally identical despite variable naming or punctuation differences.
    Falls back to difflib SequenceMatcher if uncredentialed or offline.
    """
    api_key = os.getenv("TYPESAFE_API_KEY")
    if api_key and master_text and live_text:
        try:
            import asyncio

            from typesafe_sdk import Noul, TypeSafeClient

            async def _check():
                async with TypeSafeClient() as client:
                    resp = await client.system_one(
                        state={"master_template": master_text, "live_template": live_text},
                        questions={
                            "is_match": Noul(
                                instructions=(
                                    "Determine if the master template text and the live WhatsApp template "
                                    "represent the exact same message content, promotional offer, and intent, "
                                    "ignoring variable numbering syntax (e.g. {{1}} vs {{name}}), minor whitespace, "
                                    "and punctuation differences."
                                )
                            )
                        },
                    )
                    return resp.answers["is_match"].prob

            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    prob = pool.submit(asyncio.run, _check()).result(timeout=10)
            else:
                prob = asyncio.run(_check())

            is_eq = prob >= 0.85
            return is_eq, round(prob, 3), "SEMANTIC_AI"
        except Exception as exc:
            logger.debug("TypeSafe semantic comparison notice: %s", exc)

    # Fallback to normalized fuzzy diff
    sim = compute_text_similarity(master_text, live_text)
    return (sim >= 0.88), sim, "FUZZY_TOKEN"


def identify_master_templates(
    master_submissions: list[TemplateSubmission | dict[str, Any]],
    client: str = "bajaj",
    live_templates: list[dict[str, Any]] | None = None,
) -> IdentificationReport:
    """
    Core identification engine: compares master templates against live Karix WABA templates.
    """
    if live_templates is None:
        fetched, err = fetch_template_list(client)
        if err:
            logger.warning("Error fetching live templates for %s: %s", client, err)
        live_templates = fetched or []

    # Build lookup dictionaries from live Karix templates
    live_by_name: dict[str, dict[str, Any]] = {}
    for lt in live_templates:
        tname = str(lt.get("template_name") or lt.get("name") or "").strip().lower()
        if tname:
            live_by_name[tname] = lt

    items: list[TemplateDiscrepancyItem] = []
    missing_submissions: list[dict[str, Any]] = []

    whitelisted_cnt = 0
    missing_cnt = 0
    pending_cnt = 0
    rejected_cnt = 0
    drift_cnt = 0

    for sub in master_submissions:
        if isinstance(sub, TemplateSubmission):
            name = sub.template_name
            cat = sub.category
            lang = sub.language
            comps = sub.components
            sub_dict = asdict(sub)
        else:
            name = str(sub.get("template_name") or sub.get("name") or "")
            cat = str(sub.get("category") or "MARKETING")
            lang = str(sub.get("language") or "en")
            comps = sub.get("components") or []
            sub_dict = sub

        clean_name = name.strip()
        name_lower = clean_name.lower()
        master_body = _extract_body_text(comps)

        # 1. Look for live match by exact or normalized name
        live_match = live_by_name.get(name_lower)
        match_method = "NAME_EXACT"

        # If not found by exact name, try match by body similarity across approved templates
        if not live_match and master_body:
            for lt in live_templates:
                l_comps = lt.get("components") or lt.get("body") or []
                l_body = _extract_body_text(l_comps)
                if not l_body:
                    continue
                is_eq, prob, method = evaluate_semantic_equivalence_typesafe(master_body, l_body)
                if is_eq and prob >= 0.92:
                    live_match = lt
                    match_method = method
                    break

        if not live_match:
            # Not found on Karix at all -> NOT_WHITELISTED
            missing_cnt += 1
            item = TemplateDiscrepancyItem(
                template_name=clean_name,
                status="NOT_WHITELISTED",
                category=cat,
                language=lang,
                master_body=master_body,
                live_body="",
                match_confidence=0.0,
                match_method="NONE",
                diff_summary="Not found on Karix WABA catalog. Missing whitelisting approval.",
                action_required="SUBMIT",
            )
            items.append(item)
            missing_submissions.append(sub_dict)
            continue

        # Found match on Karix! Evaluate status and content
        live_status_raw = str(live_match.get("status") or "").upper().strip()
        live_fb_id = str(live_match.get("fb_template_id") or live_match.get("id") or "")
        live_comps = live_match.get("components") or live_match.get("body") or []
        live_body = _extract_body_text(live_comps)

        # Determine equivalence
        is_eq, sim_score, method = evaluate_semantic_equivalence_typesafe(master_body, live_body)
        if match_method != "NAME_EXACT":
            method = match_method

        if live_status_raw in ("APPROVED", "WHITELISTED"):
            if is_eq or not master_body:
                whitelisted_cnt += 1
                item = TemplateDiscrepancyItem(
                    template_name=clean_name,
                    status="WHITELISTED",
                    category=cat,
                    language=lang,
                    master_body=master_body,
                    live_body=live_body,
                    match_confidence=sim_score,
                    match_method=method,
                    diff_summary="Live approved template matches master specifications.",
                    live_fb_id=live_fb_id,
                    live_status_raw=live_status_raw,
                    action_required="NONE",
                )
            else:
                drift_cnt += 1
                item = TemplateDiscrepancyItem(
                    template_name=clean_name,
                    status="CONTENT_DRIFT",
                    category=cat,
                    language=lang,
                    master_body=master_body,
                    live_body=live_body,
                    match_confidence=sim_score,
                    match_method=method,
                    diff_summary=(
                        f"Template name exists on WABA ({live_status_raw}), but content has drifted "
                        f"({int(sim_score * 100)}% match). Requires review or update."
                    ),
                    live_fb_id=live_fb_id,
                    live_status_raw=live_status_raw,
                    action_required="REMEDIATE",
                )
        elif live_status_raw in ("PENDING", "SUBMITTED"):
            pending_cnt += 1
            item = TemplateDiscrepancyItem(
                template_name=clean_name,
                status="PENDING",
                category=cat,
                language=lang,
                master_body=master_body,
                live_body=live_body,
                match_confidence=sim_score,
                match_method=method,
                diff_summary="Awaiting Meta / Carrier whitelisting review.",
                live_fb_id=live_fb_id,
                live_status_raw=live_status_raw,
                action_required="WAIT",
            )
        elif live_status_raw in ("REJECTED", "FAILED"):
            rejected_cnt += 1
            item = TemplateDiscrepancyItem(
                template_name=clean_name,
                status="REJECTED",
                category=cat,
                language=lang,
                master_body=master_body,
                live_body=live_body,
                match_confidence=sim_score,
                match_method=method,
                diff_summary=f"Rejected on Meta ({live_match.get('reason') or 'Format / policy rejection'}).",
                live_fb_id=live_fb_id,
                live_status_raw=live_status_raw,
                action_required="SUBMIT",
            )
            missing_submissions.append(sub_dict)
        else:
            # Paused or other
            item = TemplateDiscrepancyItem(
                template_name=clean_name,
                status="PAUSED" if "PAUSE" in live_status_raw else live_status_raw,
                category=cat,
                language=lang,
                master_body=master_body,
                live_body=live_body,
                match_confidence=sim_score,
                match_method=method,
                diff_summary=f"Live status is {live_status_raw}.",
                live_fb_id=live_fb_id,
                live_status_raw=live_status_raw,
                action_required="REMEDIATE",
            )

        items.append(item)

    summary = (
        f"Phase 1 Identification reconciled {len(master_submissions)} master templates against {len(live_templates)} live WABA records. "
        f"{whitelisted_cnt} Whitelisted (Approved), {missing_cnt} Missing (Not Whitelisted), "
        f"{pending_cnt} Pending, {rejected_cnt} Rejected, and {drift_cnt} Content Drift."
    )

    return IdentificationReport(
        account=client,
        total_master=len(master_submissions),
        whitelisted_count=whitelisted_cnt,
        missing_count=missing_cnt,
        pending_count=pending_cnt,
        rejected_count=rejected_cnt,
        drift_count=drift_cnt,
        items=items,
        missing_templates=missing_submissions,
        summary_notes=summary,
    )


def identify_from_file(file_path: str | Path, client: str = "bajaj") -> IdentificationReport:
    """
    Load a master template catalog from CSV, Excel, or JSON and run Phase 1 Identification.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"Template master catalog not found: {file_path}")

    ext = p.suffix.lower()
    if ext == ".csv":
        submissions = load_from_csv(str(p), client=client)
    elif ext in (".xlsx", ".xls"):
        submissions = load_from_excel(str(p), client=client)
    elif ext == ".json":
        submissions = load_from_json(str(p), client=client)
    else:
        raise ValueError(f"Unsupported file format '{ext}'. Must be .csv, .xlsx, or .json")

    return identify_master_templates(submissions, client=client)
