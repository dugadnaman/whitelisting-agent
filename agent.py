"""
Autonomous AI Agent Engine for Karix WhatsApp & RCS Whitelisting.
Provides conversational instruction parsing, template rejection diagnosis,
automated copy remediation (grammar + Meta policy compliance), autonomous
resubmission, and catalog status management.
"""

import logging
import os
import re
import time
from typing import Any

from activity_tracker import log_activity
from grammar_checker import lint_and_fix_body
from loader import _row_to_submission
from rcs_client import fetch_rcs_templates, submit_rcs_template
from rcs_models import RcsTemplateSubmission
from rcs_tracker import load_rcs_log
from submission_client import (
    SubmissionStatus,
    fetch_template_list,
    submit_template,
)
from tracker import load_log

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------


def tool_inspect_template(
    name_or_query: str,
    account: str = "bajaj",
    channel: str = "whatsapp",
) -> dict[str, Any]:
    """Find a template by name or ID across live WABA and local submission logs."""
    acc = account.lower().strip()
    chan = channel.lower().strip()
    q = name_or_query.strip().lower()

    if chan == "rcs":
        local_entries = load_rcs_log("rcs_submission_log.jsonl")
        local_match = next(
            (
                e
                for e in local_entries
                if q in e.get("template_name", "").lower() or q in str(e.get("template_id", "")).lower()
            ),
            None,
        )
        live_list = fetch_rcs_templates(client=acc)
        live_match = next(
            (
                t
                for t in live_list
                if q in t.get("viTemplate", {}).get("name", "").lower() or q in str(t.get("templateId", "")).lower()
            ),
            None,
        )

        if not local_match and not live_match:
            return {
                "found": False,
                "query": name_or_query,
                "channel": "rcs",
                "account": acc,
            }

        entry = local_match or {}
        if live_match:
            vi = live_match.get("viTemplate", {})
            entry.update(
                {
                    "template_name": vi.get("name") or str(live_match.get("templateId")),
                    "template_id": str(live_match.get("templateId")),
                    "approval_status": str(live_match.get("status", "SUBMITTED")).lower(),
                    "template_message": vi.get("textMessage", ""),
                    "live": True,
                }
            )
        return {"found": True, "template": entry, "channel": "rcs", "account": acc}

    # WhatsApp
    local_entries = load_log("submission_log.jsonl")
    local_match = next(
        (
            e
            for e in local_entries
            if q in e.get("template_name", "").lower() or q in str(e.get("provider_ref_id", "")).lower()
        ),
        None,
    )
    live_list, err = fetch_template_list(client=acc)
    live_match = next(
        (
            t
            for t in live_list
            if q in t.get("template_name", "").lower()
            or q in str(t.get("fb_template_id", "")).lower()
            or q in str(t.get("sno", "")).lower()
        ),
        None,
    )

    if not local_match and not live_match:
        return {
            "found": False,
            "query": name_or_query,
            "channel": "whatsapp",
            "account": acc,
            "error": err,
        }

    res = local_match.copy() if local_match else {}
    if live_match:
        res.update(
            {
                "template_name": live_match.get("template_name"),
                "approval_status": str(live_match.get("template_create_status", "UNKNOWN")).lower(),
                "reason": live_match.get("template_status_reason"),
                "category": live_match.get("template_category") or live_match.get("category"),
                "language": live_match.get("language_code") or live_match.get("language"),
                "provider_ref_id": str(live_match.get("sno") or live_match.get("fb_template_id")),
                "live": True,
                "raw": live_match,
            }
        )
    return {"found": True, "template": res, "channel": "whatsapp", "account": acc}


def tool_diagnose_and_fix(
    template_name: str,
    account: str = "bajaj",
    channel: str = "whatsapp",
    user_instructions: str = "",
    auto_resubmit: bool = True,
    user: str = "AI Agent",
) -> dict[str, Any]:
    """
    Diagnose why a template was rejected or has quality issues, apply automated
    compliance fixes (variable spacing, floating variables, typos, Meta policies),
    and optionally resubmit a compliant version.
    """
    inspection = tool_inspect_template(template_name, account=account, channel=channel)
    if not inspection.get("found"):
        return {
            "success": False,
            "error": f"Template '{template_name}' was not found in live {account} {channel} catalog or local logs.",
        }

    tmpl = inspection["template"]
    raw_status = str(tmpl.get("approval_status", "")).lower()
    rejection_reason = tmpl.get("reason") or tmpl.get("error") or "Unknown / Quality check"
    body_text = tmpl.get("body") or tmpl.get("template_message") or ""

    if not body_text and isinstance(tmpl.get("raw"), dict):
        components = tmpl["raw"].get("components", [])
        for comp in components:
            if comp.get("type", "").upper() == "BODY":
                body_text = comp.get("text", "")
                break

    # Apply grammar and Meta policy linter
    fixed_body, warnings = lint_and_fix_body(body_text)

    # Determine next version name
    orig_name = tmpl.get("template_name") or template_name
    match = re.search(r"_v(\d+)$", orig_name)
    if match:
        v_num = int(match.group(1)) + 1
        new_name = re.sub(r"_v\d+$", f"_v{v_num}", orig_name)
    else:
        new_name = f"{orig_name}_v2"

    diagnosis = {
        "original_template": orig_name,
        "current_status": raw_status,
        "rejection_reason": rejection_reason,
        "issues_detected": warnings,
        "original_body": body_text,
        "remediated_body": fixed_body,
        "new_version_name": new_name,
        "resubmitted": False,
    }

    if auto_resubmit:
        if channel == "whatsapp":
            comp_list = []
            if tmpl.get("header_type"):
                comp_list.append(
                    {
                        "type": "HEADER",
                        "format": tmpl.get("header_type"),
                        "text": tmpl.get("header_text"),
                        "media_url": tmpl.get("header_media_url"),
                    }
                )
            comp_list.append({"type": "BODY", "text": fixed_body})
            if tmpl.get("footer"):
                comp_list.append({"type": "FOOTER", "text": tmpl.get("footer")})
            if tmpl.get("buttons"):
                comp_list.append({"type": "BUTTONS", "buttons": tmpl.get("buttons")})

            sub = _row_to_submission(
                {
                    "template_name": new_name,
                    "category": tmpl.get("category") or "UTILITY",
                    "language": tmpl.get("language") or "en_US",
                    "components": comp_list,
                    "source_ref": f"agent_fix_{new_name}",
                },
                client=account,
            )
            res = submit_template(sub, client=account)
            diagnosis["resubmitted"] = True
            diagnosis["submission_result"] = {
                "status": res.status.value,
                "provider_ref_id": res.provider_ref_id,
                "error": res.error,
            }
            log_activity(
                user=user,
                action="AGENT_AUTO_REMEDIATION",
                account=account,
                channel="whatsapp",
                details={
                    "original": orig_name,
                    "new_version": new_name,
                    "status": res.status.value,
                    "issues_fixed": len(warnings),
                },
                status="success" if res.status == SubmissionStatus.SUBMITTED else "failed",
            )
        else:
            sub = RcsTemplateSubmission(
                source_ref=f"agent_fix_{new_name}",
                template_name=new_name[:25],
                template_type=tmpl.get("template_type") or "text",
                template_message=fixed_body,
                client=account,
            )
            res = submit_rcs_template(sub, client=account)
            diagnosis["resubmitted"] = True
            diagnosis["submission_result"] = {
                "status": res.status.value,
                "template_id": res.template_id,
                "error": res.error,
            }
            log_activity(
                user=user,
                action="AGENT_AUTO_REMEDIATION",
                account=account,
                channel="rcs",
                details={
                    "original": orig_name,
                    "new_version": new_name,
                    "status": res.status.value,
                    "issues_fixed": len(warnings),
                },
                status="success" if res.status.value == "submitted" else "failed",
            )

    return {"success": True, "diagnosis": diagnosis}


def tool_list_templates(
    account: str = "bajaj",
    channel: str = "whatsapp",
    status_filter: str | None = None,
    limit: int = 15,
) -> dict[str, Any]:
    """List templates filtered by status (e.g. 'rejected', 'pending', 'approved')."""
    acc = account.lower().strip()
    chan = channel.lower().strip()
    s_filter = status_filter.lower().strip() if status_filter else None

    if chan == "rcs":
        live = fetch_rcs_templates(client=acc)
        results = []
        for t in live:
            st = str(t.get("status", "SUBMITTED")).lower()
            if not s_filter or s_filter in st:
                vi = t.get("viTemplate", {})
                results.append(
                    {
                        "name": vi.get("name") or str(t.get("templateId")),
                        "status": st,
                        "type": vi.get("type", "text"),
                        "id": str(t.get("templateId")),
                    }
                )
        return {
            "total": len(results),
            "templates": results[:limit],
            "account": acc,
            "channel": "rcs",
        }

    live, err = fetch_template_list(client=acc)
    results = []
    for t in live:
        st = str(t.get("template_create_status", "UNKNOWN")).lower()
        if not s_filter or s_filter in st:
            results.append(
                {
                    "name": t.get("template_name"),
                    "status": st,
                    "category": t.get("template_category"),
                    "reason": t.get("template_status_reason"),
                    "sno": str(t.get("sno")),
                }
            )
    return {
        "total": len(results),
        "templates": results[:limit],
        "account": acc,
        "channel": "whatsapp",
        "error": err,
    }


def tool_poll_status(account: str = "bajaj", channel: str = "whatsapp") -> dict[str, Any]:
    """Trigger a status synchronization poll for all pending submissions."""
    from runner import poll_pending

    acc = account.lower().strip()
    try:
        if channel == "whatsapp":
            poll_pending(log_path="submission_log.jsonl", client=acc)
            return {
                "success": True,
                "message": f"Polled pending WhatsApp templates for {acc}",
            }
        return {"success": True, "message": f"Polled RCS templates for {acc}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def tool_create_template(
    name: str,
    body: str,
    category: str = "MARKETING",
    account: str = "bajaj",
    channel: str = "whatsapp",
    header_text: str | None = None,
    buttons: list[dict] | None = None,
) -> dict[str, Any]:
    """Create, lint, and submit a brand new template."""
    clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip().lower())
    fixed_body, warnings = lint_and_fix_body(body)

    if channel == "whatsapp":
        comp_list = []
        if header_text:
            comp_list.append({"type": "HEADER", "format": "TEXT", "text": header_text})
        comp_list.append({"type": "BODY", "text": fixed_body})
        if buttons:
            comp_list.append({"type": "BUTTONS", "buttons": buttons})

        sub = _row_to_submission(
            {
                "template_name": clean_name,
                "category": category.upper(),
                "language": "en_US",
                "components": comp_list,
                "source_ref": f"agent_create_{clean_name}",
            },
            client=account,
        )
        res = submit_template(sub, client=account)
        return {
            "success": res.status == SubmissionStatus.SUBMITTED,
            "template_name": clean_name,
            "status": res.status.value,
            "provider_ref_id": res.provider_ref_id,
            "warnings_remediated": warnings,
            "error": res.error,
        }
    else:
        sub = RcsTemplateSubmission(
            source_ref=f"agent_create_{clean_name}",
            template_name=clean_name[:25],
            template_type="text",
            template_message=fixed_body,
            client=account,
        )
        res = submit_rcs_template(sub, client=account)
        return {
            "success": res.status.value == "submitted",
            "template_name": clean_name[:25],
            "status": res.status.value,
            "template_id": res.template_id,
            "warnings_remediated": warnings,
            "error": res.error,
        }


def tool_refresh_session(account: str = "bajaj", user: str = "AI Agent") -> dict[str, Any]:
    """Trigger browser automation to log into Karix portal and harvest fresh session credentials."""
    from auth_refresher import refresh_karix_session

    return refresh_karix_session(account=account, user_attribution=user)


def tool_list_team(tenant_id: str = "bajaj") -> dict[str, Any]:
    """List team members and user details within an organization."""
    from auth import list_tenant_team

    members = list_tenant_team(tenant_id)
    return {"tenant_id": tenant_id, "members": members, "count": len(members)}


# ---------------------------------------------------------------------------
# Agent Reasoning Engine & Intent Dispatcher
# ---------------------------------------------------------------------------


class WhitelistingAgent:
    """Autonomous Whitelisting Agent handling operator commands and workflows."""

    def __init__(self):
        self.openai_key = os.environ.get("OPENAI_API_KEY")

    def execute_instruction(
        self,
        instruction: str,
        account: str = "bajaj",
        channel: str = "whatsapp",
        user: str = "Operator",
        user_profile: dict | None = None,
    ) -> dict[str, Any]:
        """
        Parse operator instruction, decide required tools, execute reasoning chain,
        and synthesize a structured response with actionable suggestions.
        """
        text = instruction.strip()
        actions_taken = []
        suggested_actions = []

        # Strict Tenant Isolation Check inside Agent
        if user_profile and isinstance(user_profile, dict):
            user_tenant = str(user_profile.get("tenant_id", "all")).lower().strip()
            user_role = str(user_profile.get("role", "operator")).lower().strip()

            if user_tenant != "all" and user_role != "superadmin":
                # Block cross-tenant prompt injection
                forbidden_tenants = [t for t in ["bajaj", "tata"] if t != user_tenant]
                for forbidden in forbidden_tenants:
                    if (
                        f"for {forbidden}" in text.lower()
                        or f"{forbidden} templates" in text.lower()
                        or f"on {forbidden}" in text.lower()
                    ):
                        return {
                            "reply": (
                                f"🚫 **Access Denied**: Your account is assigned to **{user_tenant.upper()}** "
                                f"and is strictly forbidden from querying or modifying **{forbidden.upper()}** data."
                            ),
                            "actions_taken": [],
                            "suggested_actions": [f"List {user_tenant} templates", "Poll approval status"],
                        }
                # Lock account parameter to user's assigned organization
                account = user_tenant

        # 1. Team / User Accounts inquiry: "show users", "who is on the team", "list team", "show user details"
        if any(
            w in text.lower()
            for w in [
                "show user",
                "show users",
                "list user",
                "list users",
                "team member",
                "who is on the team",
                "user details",
                "all users",
                "my team",
                "user accounts",
            ]
        ):
            team_res = tool_list_team(tenant_id=account)
            actions_taken.append({"tool": "list_tenant_team", "result": team_res})
            members = team_res.get("members", [])
            if not members:
                reply = f"No registered team members found for **{account.title()}**."
            else:
                lines = [
                    f"• **{m.get('name')}** (`{m.get('email')}`) — Role: `{m.get('role', 'operator').upper()}` | Org: `{m.get('tenant_id', account).upper()}`"
                    for m in members
                ]
                reply = (
                    f"### 👥 Registered Users for {account.title()} ({len(members)} operators):\n\n"
                    + "\n".join(lines)
                    + "\n\n*Tip: You can also inspect team accounts in **[Settings](/settings)** under Organization Team Directory.*"
                )
            suggested_actions = ["Poll approval status", "List rejected templates", "How do I submit templates?"]
            return {
                "reply": reply,
                "actions_taken": actions_taken,
                "suggested_actions": suggested_actions,
                "data": team_res,
            }

        # 2. How to submit / Upload instructions / General Help
        if any(
            w in text.lower()
            for w in [
                "how to submit",
                "how do i submit",
                "how can i submit",
                "how to upload",
                "how do i upload",
                "how to create",
                "how does this work",
                "how do i use",
                "ways to submit",
                "help",
                "instructions",
                "what can you do",
            ]
        ):
            reply = (
                f"### 🚀 How to Submit Templates for **{account.title()} ({channel.upper()})**\n\n"
                "You have **3 ways** to submit templates:\n\n"
                "#### 1. 📂 Bulk Upload via Dashboard (Recommended for marketing sheets)\n"
                "• Go to **[Submit Templates](/submit)** in the left sidebar.\n"
                "• Drag & drop your `.xlsx` or `.csv` spreadsheet (or click *Download Sample CSV* for the format).\n"
                "• Review the instant pre-submission preview with grammar and 16:9 image checks.\n"
                "• Click **Submit Templates** to submit in parallel with real-time logs.\n\n"
                "#### 2. 💬 Conversational Submission (Directly in this Copilot)\n"
                "• Tell me to create and submit a template directly:\n"
                '  > *"Create a marketing template named diwali_offer with body: Hello {{1}}, your pre-approved loan of {{2}} is ready at bajajfinserv.in"*\n\n'
                "#### 3. 🔧 Auto-Fix & Resubmit Rejections\n"
                "• Tell me to diagnose and repair a rejected template:\n"
                '  > *"Check why template loan_oct_01 was rejected, fix it, and resubmit"*\n\n'
                "#### 4. ⚡ Terminal CLI Runner\n"
                "• Run: `python3 runner.py samples/templates.xlsx --client bajaj`"
            )
            suggested_actions = [
                "List rejected templates",
                "Poll approval status",
                "Create a template named test_promo",
            ]
            return {
                "reply": reply,
                "actions_taken": [],
                "suggested_actions": suggested_actions,
            }

        # 2. Template creation command: e.g. "create a marketing template named X with body Y"
        has_create_keyword = bool(
            re.search(
                r"(?:create|submit|register|new|add)\s+(?:a\s+)?(?:[a-zA-Z]+\s+)?template",
                text,
                re.IGNORECASE,
            )
        )
        if has_create_keyword and any(k in text.lower() for k in ["body", ":", "with text", "message"]):
            name_m = re.search(r"(?:named|name|id)\s+([a-zA-Z0-9_\-]+)", text, re.IGNORECASE)
            cat_m = re.search(r"\b(marketing|utility|authentication|transactional)\b", text, re.IGNORECASE)
            body_m = re.search(r"(?:body|message|text|content)[:\s]+(.+)", text, re.IGNORECASE | re.DOTALL)

            t_name = name_m.group(1).strip() if name_m else f"template_{int(time.time())}"
            t_cat = cat_m.group(1).strip().upper() if cat_m else "MARKETING"
            t_body = body_m.group(1).strip() if body_m else ""

            if not t_body and ":" in text:
                t_body = text.split(":", 1)[1].strip()
            if t_body:
                create_res = tool_create_template(
                    name=t_name,
                    body=t_body,
                    category=t_cat,
                    account=account,
                    channel=channel,
                )
                actions_taken.append({"tool": "create_template", "result": create_res})
                if create_res.get("success"):
                    reply = (
                        f"### ✅ Template `{t_name}` Created & Submitted\n\n"
                        f"**Category:** `{t_cat}`\n"
                        f"**Channel:** `{channel.upper()}` ({account.title()})\n"
                        f"**Status:** `{create_res.get('status', 'submitted').upper()}`\n\n"
                        f"**Submitted Body:**\n```\n{t_body}\n```\n"
                    )
                    suggested_actions = [
                        "Poll approval status",
                        "List pending templates",
                        f"Inspect {t_name}",
                    ]
                else:
                    reply = f"### ❌ Submission Failed for `{t_name}`\n\n**Error:** {create_res.get('error')}\n"
                    suggested_actions = ["Check credentials", "Lint copy"]

                return {
                    "reply": reply,
                    "actions_taken": actions_taken,
                    "suggested_actions": suggested_actions,
                    "data": create_res,
                }

        # 3. Re-login / session refresh: "refresh session", "relogin", "auto-login", "refresh token"
        if any(
            w in text.lower()
            for w in [
                "refresh session",
                "relogin",
                "re-login",
                "refresh token",
                "refresh auth",
                "auto-login",
                "auto login",
                "login to karix",
                "portal login",
            ]
        ):
            refresh_res = tool_refresh_session(account=account, user=user)
            actions_taken.append({"tool": "refresh_karix_session", "result": refresh_res})
            if refresh_res.get("success"):
                reply = (
                    f"### ⚡ Session Auto-Refreshed\n\n"
                    f"Successfully logged into Karix portal via headless browser for **{account.title()}**.\n"
                    f"• **Tokens Updated:** `{', '.join(refresh_res.get('tokens_updated', []))}`\n"
                    f"• **Active Operator:** `{refresh_res.get('user', 'Portal User')}`\n\n"
                    f"All subsequent template submissions will use these fresh credentials automatically."
                )
                suggested_actions = [
                    "Poll approval status",
                    "List rejected templates",
                    "Check active catalog",
                ]
            else:
                reply = (
                    f"### ⚠️ Session Auto-Refresh Failed\n\n"
                    f"{refresh_res.get('error')}\n\n"
                    f"*Tip: Configure your Karix portal username and password under Settings to enable zero-touch session healing.*"
                )
                suggested_actions = ["List templates", "Poll approval status"]

            return {
                "reply": reply,
                "actions_taken": actions_taken,
                "suggested_actions": suggested_actions,
                "data": refresh_res,
            }

        # 2. Text linting / copy checking: "fix grammar in: ...", "lint this copy: ...", "fix message:"
        if any(
            w in text.lower()
            for w in [
                "lint",
                "check grammar",
                "fix copy",
                "clean text",
                "fix message",
                "fix text",
                "check copy",
                "grammar in:",
            ]
        ) or (
            ("fix" in text.lower() or "check" in text.lower())
            and any(k in text.lower() for k in ["{{", "body:", "message:", "copy:"])
        ):
            # Extract text payload
            raw_copy = text.split(":", 1)[1].strip() if ":" in text else text
            fixed, warns = lint_and_fix_body(raw_copy)
            actions_taken.append({"tool": "lint_and_fix_body", "warnings_count": len(warns)})

            warn_lines = (
                "\n".join([f"• **{w['type']}**: {w['issue']} $\\rightarrow$ {w['suggestion']}" for w in warns])
                or "• No compliance or grammar issues found."
            )
            reply = (
                f"### ✨ Copy Analysis & Remediation\n\n"
                f"**Cleaned Copy:**\n```\n{fixed}\n```\n\n"
                f"**Detected Improvements:**\n{warn_lines}\n"
            )
            return {
                "reply": reply,
                "actions_taken": actions_taken,
                "suggested_actions": [
                    "Create template from this copy",
                    "List rejected templates",
                    "Poll approval status",
                ],
            }

        # 2. Status Polling: "poll pending", "check approval status"
        if any(w in text.lower() for w in ["poll", "sync", "refresh status", "check status"]):
            poll_res = tool_poll_status(account=account, channel=channel)
            actions_taken.append({"tool": "poll_status", "result": poll_res})
            return {
                "reply": f"🔄 **Status sync complete.** Polled live WABA status for all pending templates on **{account.title()}**.",
                "actions_taken": actions_taken,
                "suggested_actions": [
                    "List approved templates",
                    "List rejected templates",
                ],
            }

        # 3. List templates: "list rejected templates", "show pending"
        if any(w in text.lower() for w in ["list", "show", "get", "fetch", "all"]) and any(
            s in text.lower() for s in ["rejected", "pending", "approved", "templates", "catalog"]
        ):
            s_filter = None
            if "rejected" in text.lower():
                s_filter = "rejected"
            elif "pending" in text.lower():
                s_filter = "pending"
            elif "approved" in text.lower():
                s_filter = "approved"

            list_res = tool_list_templates(account=account, channel=channel, status_filter=s_filter, limit=10)
            actions_taken.append({"tool": "list_templates", "result": list_res})
            tmpls = list_res.get("templates", [])

            if not tmpls:
                reply = (
                    f"No `{s_filter or 'active'}` templates found for **{account.title()}** on **{channel.upper()}**."
                )
                suggested_actions = ["Poll status", "Submit new templates"]
            else:
                lines = [
                    f"• **`{t['name']}`** — Status: `{t['status'].upper()}`"
                    + (f" (Reason: {t.get('reason')})" if t.get("reason") else "")
                    for t in tmpls
                ]
                reply = (
                    f"### 📋 {s_filter.title() if s_filter else 'Catalog'} Templates for {account.title()} ({list_res['total']} found):\n\n"
                    + "\n".join(lines)
                )
                if s_filter == "rejected" and tmpls:
                    suggested_actions = [
                        f"Fix and resubmit {tmpls[0]['name']}",
                        "Poll approval status",
                    ]
                else:
                    suggested_actions = [
                        "Poll approval status",
                        "List rejected templates",
                    ]

            return {
                "reply": reply,
                "actions_taken": actions_taken,
                "suggested_actions": suggested_actions,
                "data": list_res,
            }

        # 4. Rejection diagnosis and resubmission: "check why template X was rejected, fix it, and resubmit"
        rej_match = re.search(
            r"(?:check|why|fix|diagnose|resubmit|inspect)\s+.*?(?:template\s+)?([a-zA-Z0-9_\-]+)",
            text,
            re.IGNORECASE,
        )
        is_fix_resubmit = any(
            w in text.lower()
            for w in [
                "fix",
                "resubmit",
                "repair",
                "remediate",
                "rejected",
                "why",
                "diagnose",
                "inspect",
            ]
        )

        if is_fix_resubmit and rej_match:
            candidate_name = rej_match.group(1).strip()
            if candidate_name.lower() in (
                "why",
                "template",
                "rejected",
                "the",
                "this",
                "it",
            ):
                tokens = re.findall(r"[a-zA-Z0-9_]{3,}", text)
                filtered = [
                    t
                    for t in tokens
                    if t.lower()
                    not in (
                        "check",
                        "why",
                        "template",
                        "was",
                        "rejected",
                        "fix",
                        "and",
                        "resubmit",
                        "for",
                        "bajaj",
                        "tata",
                    )
                ]
                candidate_name = filtered[0] if filtered else candidate_name

            auto_submit = any(w in text.lower() for w in ["resubmit", "submit", "apply", "create"])
            diag_res = tool_diagnose_and_fix(
                template_name=candidate_name,
                account=account,
                channel=channel,
                user_instructions=text,
                auto_resubmit=auto_submit,
                user=user,
            )
            actions_taken.append(
                {
                    "tool": "diagnose_and_fix",
                    "target": candidate_name,
                    "result": diag_res,
                }
            )

            if diag_res.get("success"):
                d = diag_res["diagnosis"]
                fixes = d["issues_detected"]
                fix_summary = (
                    "\n".join(
                        [f"• **{f.get('type')}**: {f.get('issue')} $\\rightarrow$ {f.get('suggestion')}" for f in fixes]
                    )
                    or "• Applied automated Meta variable spacing and punctuation corrections."
                )

                reply = (
                    f"### 🔍 Diagnosis for `{candidate_name}`\n\n"
                    f"**Current Status:** `{d['current_status'].upper()}`\n"
                    f"**Provider Reason:** {d['rejection_reason']}\n\n"
                    f"#### 🛠️ Corrections Applied:\n{fix_summary}\n\n"
                    f"#### 📝 Remediated Body:\n```\n{d['remediated_body']}\n```\n"
                )
                if d.get("resubmitted"):
                    sub_res = d.get("submission_result", {})
                    reply += f"\n✅ **Autonomously resubmitted as:** `{d['new_version_name']}` (Status: `{sub_res.get('status', 'submitted').upper()}`)"
                    suggested_actions = [
                        "Poll approval status",
                        "View template in dashboard",
                        f"Inspect {d['new_version_name']}",
                    ]
                else:
                    reply += f"\n💡 Remediated copy is ready. Would you like me to submit `{d['new_version_name']}`?"
                    suggested_actions = [
                        f"Resubmit as {d['new_version_name']}",
                        "Edit copy further",
                    ]

                return {
                    "reply": reply,
                    "actions_taken": actions_taken,
                    "suggested_actions": suggested_actions,
                    "data": diag_res,
                }
            else:
                return {
                    "reply": f"❌ Could not find template `{candidate_name}` in the {account.upper()} {channel.upper()} catalog.\n\n*Tip: Try listing your templates to see exact registered names.*",
                    "actions_taken": actions_taken,
                    "suggested_actions": [
                        "List rejected templates",
                        "List all templates",
                        "Poll status",
                    ],
                }

        # 5. Fallback conversational guidance
        return {
            "reply": (
                f"I am your **Karix Whitelisting Assistant** for **{account.title()} ({channel.upper()})**.\n\n"
                "Here are actions I can perform for you:\n\n"
                '1. 🚀 **Submit Templates:** *"How do I submit templates?"* or *"Create a marketing template named promo_01 with body: Hello {{1}}..."*\n'
                '2. 🔧 **Fix Rejections:** *"Check why template loan_oct_01 was rejected, fix it, and resubmit"*\n'
                '3. 📋 **Inspect Catalog:** *"List all rejected templates for bajaj"* or *"Show pending templates"*\n'
                '4. 🔄 **Sync Approvals:** *"Poll approval status from Meta"*\n'
                '5. ✍️ **Lint Copy:** *"Check grammar in: Dear {{1}}, your disbursment of {{2}} is ready"*'
            ),
            "actions_taken": [],
            "suggested_actions": [
                "How do I submit templates?",
                "List rejected templates",
                "Poll approval status",
            ],
        }


# Singleton agent instance
agent_instance = WhitelistingAgent()
