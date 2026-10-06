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


def _extract_body_text(value: Any, _depth: int = 0) -> str:
    """Extract template body text from normalized or raw Karix response data."""
    if value is None or _depth > 6:
        return ""
    if isinstance(value, str):
        return value.strip()

    if isinstance(value, (list, tuple)):
        # Prefer the explicit BODY component over headers, footers, or buttons.
        for item in value:
            item_type = item.get("type", "") if isinstance(item, dict) else getattr(item, "type", "")
            if str(item_type).upper() == "BODY":
                body = _extract_body_text(item, _depth + 1)
                if body:
                    return body
        for item in value:
            body = _extract_body_text(item, _depth + 1)
            if body:
                return body
        return ""

    if not isinstance(value, dict):
        body = getattr(value, "text", None)
        return str(body).strip() if body else ""

    if str(value.get("type", "")).upper() == "BODY":
        for key in ("text", "body_text", "template_text", "content", "body", "message"):
            body = _extract_body_text(value.get(key), _depth + 1)
            if body:
                return body

    # Karix responses have appeared with both snake_case and camelCase/nested
    # body fields. Inspect structured body containers before generic metadata.
    for key in (
        "components",
        "body",
        "body_text",
        "bodyText",
        "template_body",
        "templateBody",
        "template",
        "data",
        "payload",
    ):
        if key in value:
            body = _extract_body_text(value[key], _depth + 1)
            if body:
                return body

    for key in (
        "text",
        "template_text",
        "templateText",
        "text_message",
        "textMessage",
        "content",
        "template_message",
        "templateMessage",
        "message",
    ):
        body = _extract_body_text(value.get(key), _depth + 1)
        if body:
            return body
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


_CACHED_MOENGAGE_WHATSAPP_TEMPLATES: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def fetch_cached_moengage_whatsapp_templates(account: str = "tata", max_age_sec: int = 300) -> list[dict[str, Any]]:
    """Fetch all live MoEngage WhatsApp templates with in-memory TTL caching and disk fallback."""
    import json
    import time
    from pathlib import Path

    now = time.time()
    cached = _CACHED_MOENGAGE_WHATSAPP_TEMPLATES.get(account)
    if cached and (now - cached[0]) < max_age_sec:
        return cached[1]
    tracked_cache = Path(__file__).resolve().parent / f"templates_cache_{account}.json"
    disk_cache = Path(f"data/whatsapp_templates_cache_{account}.json")

    try:
        import requests
        from moengage_sync import get_moengage_auth_headers, get_moengage_config
        headers = get_moengage_auth_headers(account)
        headers["page"] = "whatsapp/create/one-time"
        cfg = get_moengage_config(account)
        headers["origin"] = cfg["base_url"]
        url = f"{cfg['base_url']}/template_metadata?template_type=whatsapp"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.ok:
            data = resp.json().get("data", [])
            templates_with_body = []
            for t in data:
                tbody = t.get("meta_data", {}).get("content", {}).get("body", "")
                if tbody and len(tbody.strip()) > 15:
                    sender_list = t.get("meta_data", {}).get("sender_ids") or []
                    templates_with_body.append({
                        "id": t["id"],
                        "name": t.get("name") or t.get("display_name", ""),
                        "body": tbody,
                        "sender_id": sender_list[0] if sender_list else "6516baa397c87500027529a3",
                        "provider": t.get("meta_data", {}).get("provider", "Karix"),
                    })
            if templates_with_body:
                _CACHED_MOENGAGE_WHATSAPP_TEMPLATES[account] = (now, templates_with_body)
                return templates_with_body
    except Exception as exc:
        logger.debug("Could not fetch live MoEngage WhatsApp templates for matching: %s", exc)

    # Tracked file fallback (baked into repository & container)
    for p in (tracked_cache, disk_cache):
        if p.exists():
            try:
                disk_data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(disk_data, list) and disk_data:
                    _CACHED_MOENGAGE_WHATSAPP_TEMPLATES[account] = (now, disk_data)
                    return disk_data
            except Exception:
                pass

    fallback = cached[1] if cached else []
    _CACHED_MOENGAGE_WHATSAPP_TEMPLATES[account] = (now, fallback)
    return fallback

def extract_variables_from_template_body(client_text: str, tpl_text: str) -> dict[str, str]:
    """Extract {{1}}, {{2}} placeholder values by matching literal prefixes before each tag."""
    tags = re.findall(r"\{\{(\d+)\}\}", tpl_text)
    if not tags:
        return {}

    placeholders: dict[str, str] = {}
    for tag in set(tags):
        m = re.search(r"([^\n\r{}]+?)\s*\{\{" + tag + r"\}\}", tpl_text)
        if m:
            raw_prefix = m.group(1).strip()
            words = re.findall(r"[a-zA-Z]+", raw_prefix)
            if words:
                pat = r"(?:^|\n)[^\w\n]*\b" + r"\s+".join(words) + r"\b\s*[:\-–]?\s*([^\n\r]+)"
                m_val = re.search(pat, client_text, re.IGNORECASE)
                if m_val:
                    tag_key = "{{" + str(tag) + "}}"
                    placeholders[tag_key] = m_val.group(1).strip()

    urls = re.findall(r"https?://[^\s]+", client_text)
    for tag in tags:
        key = "{{" + str(tag) + "}}"
        if key not in placeholders or not placeholders[key]:
            if urls:
                placeholders[key] = urls[0]
            else:
                placeholders[key] = ""

    return placeholders


def match_whatsapp_template_and_variables(
    client_body: str,
    account: str = "tata",
    min_confidence: float = 0.40,
) -> dict[str, Any] | None:
    """
    Given a raw message body from a client spreadsheet, match it against live whitelisted
    templates in MoEngage, return the matched template ID, name, sender ID, and extracted placeholders.
    """
    if not client_body or len(client_body.strip()) < 15:
        return None

    templates = fetch_cached_moengage_whatsapp_templates(account)
    if not templates:
        return None

    norm_client = normalize_template_text(client_body)
    best_sim = 0.0
    best_match = None

    for t in templates:
        norm_t = normalize_template_text(t["body"])
        sim = compute_text_similarity(norm_client, norm_t)
        if sim > best_sim:
            best_sim = sim
            best_match = t
            if sim >= 0.95:
                break

    if best_match and best_sim >= min_confidence:
        placeholders = extract_variables_from_template_body(client_body, best_match["body"])
        return {
            "matched": True,
            "template_id": best_match["id"],
            "template_name": best_match["name"],
            "sender_id": best_match["sender_id"],
            "provider": best_match.get("provider", "Karix"),
            "confidence": round(best_sim, 3),
            "placeholders": placeholders,
            "matched_template_body": best_match["body"],
        }

    return None

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


@dataclass
class ContentSearchResult:
    """Outcome of searching Karix template inventory by body copy / content."""

    found: bool
    template_name: str | None = None
    template_id: str | None = None
    status: str | None = None
    category: str | None = None
    language: str | None = None
    match_type: str = "NONE"  # EXACT, FUZZY, SEMANTIC, NONE
    similarity_score: float = 0.0
    matched_live_body: str = ""
    candidate_matches: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def find_template_by_content(
    content: str,
    client: str = "bajaj",
    channel: str = "whatsapp",
    min_similarity: float = 0.85,
    live_templates: list[dict[str, Any]] | None = None,
) -> ContentSearchResult:
    """
    Search Karix / WABA live inventory to detect if the given body text or content
    already exists in any registered template, returning its template name and template ID.
    """
    if not content or not content.strip():
        return ContentSearchResult(
            found=False,
            message="No content provided to search.",
        )

    query_text = content.strip()
    query_norm = normalize_template_text(query_text)

    fetch_error: str | None = None
    if live_templates is None:
        chan = (channel or "whatsapp").lower().strip()
        if chan == "whatsapp":
            from submission_client import fetch_template_list

            fetched, fetch_error = fetch_template_list(client)
            if fetch_error:
                logger.warning("Error fetching live WhatsApp templates for %s: %s", client, fetch_error)
            live_templates = fetched or []
        elif chan == "rcs":
            from rcs_client import fetch_rcs_templates

            live_templates = fetch_rcs_templates(client=client) or []
        else:
            from sms_tracker import load_sms_submissions

            live_templates = load_sms_submissions(client=client) or []

    candidates: list[dict[str, Any]] = []

    for lt in live_templates:
        vi_template = lt.get("viTemplate") if isinstance(lt.get("viTemplate"), dict) else {}
        t_name = str(
            lt.get("template_name")
            or lt.get("templateName")
            or lt.get("name")
            or lt.get("element_name")
            or vi_template.get("name")
            or ""
        ).strip()
        t_id = str(
            lt.get("id")
            or lt.get("fb_template_id")
            or lt.get("meta_id")
            or lt.get("template_id")
            or lt.get("templateId")
            or lt.get("dlt_template_id")
            or lt.get("sno")
            or ""
        ).strip()
        t_status = (
            str(
                lt.get("status")
                or lt.get("template_create_status")
                or lt.get("templateStatus")
                or lt.get("approval_status")
                or "UNKNOWN"
            )
            .strip()
            .upper()
        )
        t_cat = str(
            lt.get("category") or lt.get("template_category") or lt.get("categoryName") or "MARKETING"
        ).strip().upper()
        t_lang = str(
            lt.get("language") or lt.get("language_code") or lt.get("languageCode") or "en"
        ).strip()
        live_body = _extract_body_text(lt)
        if not live_body:
            continue

        live_norm = normalize_template_text(live_body)

        # Level 1: Exact Normalized Match
        if live_norm == query_norm:
            score = 1.0
            match_type = "EXACT"
        else:
            # Level 2: Fuzzy Token Similarity
            sim = compute_text_similarity(query_text, live_body)
            if sim >= 0.90:
                score = sim
                match_type = "FUZZY"
            elif sim >= 0.70:
                # Level 3: Semantic Equivalence check
                is_eq, prob, method = evaluate_semantic_equivalence_typesafe(query_text, live_body)
                if is_eq and prob >= 0.88:
                    score = prob
                    match_type = method
                else:
                    score = sim
                    match_type = "PARTIAL"
            else:
                score = sim
                match_type = "LOW"

        if score >= min_similarity:
            candidates.append(
                {
                    "template_name": t_name,
                    "template_id": t_id or None,
                    "status": t_status,
                    "category": t_cat,
                    "language": t_lang,
                    "similarity_score": round(score, 3),
                    "match_type": match_type,
                    "body": live_body,
                }
            )

    candidates.sort(
        key=lambda c: (
            1 if c["status"] in ("APPROVED", "WHITELISTED") else 0,
            c["similarity_score"],
        ),
        reverse=True,
    )

    if candidates:
        best = candidates[0]
        return ContentSearchResult(
            found=True,
            template_name=best["template_name"],
            template_id=best["template_id"],
            status=best["status"],
            category=best["category"],
            language=best["language"],
            match_type=best["match_type"],
            similarity_score=best["similarity_score"],
            matched_live_body=best["body"],
            candidate_matches=candidates,
            message=(
                f"Match found! Template '{best['template_name']}' (ID: {best['template_id'] or 'N/A'}) "
                f"matches with {int(best['similarity_score'] * 100)}% confidence ({best['match_type']}). "
                f"Current Karix Status: {best['status']}."
            ),
        )

    if fetch_error:
        return ContentSearchResult(
            found=False,
            candidate_matches=[],
            message=f"Karix catalog lookup failed for {client}: {fetch_error}",
            error=fetch_error,
        )
    return ContentSearchResult(
        found=False,
        candidate_matches=[],
        message="No existing template in Karix matched this content copy. The template does not exist and is safe to submit.",
    )
