"""
Jira Work Management & Autonomous Workload Dispatcher Engine.
Connects to Atlassian Jira Cloud (tatacapital-team.atlassian.net) to provide:
1. Assignee Workload & Capacity Tracking (Dnyanesh, Mrunalini, Neel, interns).
2. Timeline Due Date Bucketing (Overdue, Today, Tomorrow, Day After Tomorrow, Later).
3. Status Categorization (Pending, Blocked, Done).
4. Direct Ticket Transfer with Jira Cloud API Sync & Handover Audit Comments.
5. Autonomous AI Workload Rebalancing Agent using TypeSafe System One.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
import logging
import os
from typing import Any

import requests
from config import _load_env_file
from jira_client import (
    add_jira_comment,
    get_jira_auth_headers,
    get_jira_credentials,
    list_jira_issues,
)

logger = logging.getLogger(__name__)

_load_env_file()

# Primary team members specifically requested for work management
TEAM_MEMBERS_WHITELIST: dict[str, dict[str, str]] = {
    "Mrunalini Gawande": {
        "name": "Mrunalini Gawande",
        "account_id": "712020:ff55c67a-a1eb-4d5c-90cc-451d7d59b4bd",
        "role": "Core Operator",
        "email": "mrunalini.gawande@attributics.com",
    },
    "Dnyanesh Khawas": {
        "name": "Dnyanesh Khawas",
        "account_id": "712020:c9156214-6850-4f0b-9647-145f7a3d15b9",
        "role": "Core Operator",
        "email": "dnyanesh.khawas@attributics.com",
    },
    "Neel Shah": {
        "name": "Neel Shah",
        "account_id": "712020:fae946f9-8472-455a-9d27-6d773ecfb48d",
        "role": "Core Operator",
        "email": "neel.shah@attributics.com",
    },
    "Soham Das": {
        "name": "Soham Das",
        "account_id": "712020:c8914cff-1299-4ad7-989b-e38859cbcdbf",
        "role": "Core Operator",
        "email": "soham.das@attributics.com",
    },
    "Aadya": {
        "name": "Aadya",
        "account_id": "712020:50e16c11-d517-4909-8d30-b92693808eaa",
        "role": "Associate / Intern",
        "email": "aadya@attributics.com",
    },
}

TEAM_MEMBER_ROLES: dict[str, str] = {
    info["name"]: info["role"] for info in TEAM_MEMBERS_WHITELIST.values()
}
TEAM_MEMBER_ROLES["Aalya Mulla"] = "Associate / Intern"


@dataclass
class JiraUser:
    """Team member profile and active capacity metrics."""

    account_id: str
    name: str
    email: str = ""
    role: str = "Team Member"
    open_tickets_count: int = 0
    due_today_count: int = 0
    due_tomorrow_count: int = 0
    due_day_after_count: int = 0
    overdue_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkItem:
    """Categorized work ticket from Jira."""

    key: str
    id: str
    summary: str
    status: str
    status_category: str  # "PENDING" | "BLOCKED" | "DONE"
    assignee_name: str
    assignee_account_id: str | None
    assignee_role: str
    reporter: str
    duedate: str | None  # YYYY-MM-DD
    timeline_bucket: str  # "OVERDUE" | "TODAY" | "TOMORROW" | "DAY_AFTER" | "LATER" | "NO_DATE"
    days_relative: int | None
    channel: str  # "WhatsApp" | "RCS" | "SMS" | "Email" | "General"
    attachment_count: int
    created: str
    updated: str
    labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TransferProposal:
    """AI Workload Rebalancing transfer recommendation."""

    issue_key: str
    summary: str
    current_assignee: str
    target_assignee: str
    target_account_id: str
    reason: str
    executed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def categorize_status(status_raw: str | None) -> str:
    """Classify arbitrary Jira status into PENDING, BLOCKED, or DONE."""
    if not status_raw:
        return "PENDING"
    s = status_raw.lower().strip()
    if any(k in s for k in ("done", "closed", "resolved", "completed", "whitelisted", "approved")):
        return "DONE"
    if any(k in s for k in ("blocked", "hold", "waiting", "client feedback", "asset pending", "pause")):
        return "BLOCKED"
    return "PENDING"


def compute_timeline_bucket(duedate_str: str | None) -> tuple[str, int | None]:
    """Calculate timeline bucket relative to today's date."""
    if not duedate_str:
        return "NO_DATE", None

    try:
        due = date.fromisoformat(duedate_str.split("T")[0])
        today = datetime.now(UTC).date()
        diff = (due - today).days

        if diff < 0:
            return "OVERDUE", diff
        if diff == 0:
            return "TODAY", 0
        if diff == 1:
            return "TOMORROW", 1
        if diff == 2:
            return "DAY_AFTER", 2
        return "LATER", diff
    except Exception:
        return "NO_DATE", None


def infer_channel_from_summary(summary: str) -> str:
    """Infer target messaging channel from ticket summary."""
    s = summary.lower()
    if any(k in s for k in ("_wa", "whatsapp", "wa util", "wa1", "wa2", "wa3", "wa4")):
        return "WhatsApp"
    if any(k in s for k in ("_rcs", "rcs", "rcscar", "rcs1", "rcs2")):
        return "RCS"
    if any(k in s for k in ("_sms", "sms", "sms1", "sms2", "sms3")):
        return "SMS"
    if any(k in s for k in ("mailer", "email", "_email", "edm")):
        return "Email"
    return "General"


def fetch_assignable_jira_users(project: str = "TCN") -> list[JiraUser]:
    """Fetch assignable users strictly scoped to the active team members."""
    users_list: list[JiraUser] = []
    for info in TEAM_MEMBERS_WHITELIST.values():
        users_list.append(
            JiraUser(
                account_id=info["account_id"],
                name=info["name"],
                email=info["email"],
                role=info["role"],
            )
        )
    return users_list


def get_work_management_dashboard(project: str = "TCN", limit: int = 100) -> dict[str, Any]:
    """
    Build the complete Work Management Dashboard:
    - Ingests Jira issues.
    - Classifies timeline (Overdue, Today, Tomorrow, Day After, Later).
    - Classifies status (Pending, Blocked, Done).
    - Builds Assignee capacity profiles (Dnyanesh, Mrunalini, Neel, interns).
    """
    raw_issues = list_jira_issues(project=project, limit=limit)
    assignable_users = fetch_assignable_jira_users(project=project)
    user_by_name = {u.name.lower(): u for u in assignable_users}
    if "aadya" in user_by_name:
        user_by_name["aalya mulla"] = user_by_name["aadya"]
    if "soham das" in user_by_name:
        user_by_name["soham"] = user_by_name["soham das"]

    work_items: list[WorkItem] = []

    timeline_counts = {
        "OVERDUE": 0,
        "TODAY": 0,
        "TOMORROW": 0,
        "DAY_AFTER": 0,
        "LATER": 0,
        "NO_DATE": 0,
    }

    status_counts = {
        "PENDING": 0,
        "BLOCKED": 0,
        "DONE": 0,
    }

    channel_counts = {
        "WhatsApp": 0,
        "RCS": 0,
        "SMS": 0,
        "Email": 0,
        "General": 0,
    }

    for item in raw_issues:
        summary = str(item.get("summary") or "")
        status_raw = str(item.get("status") or "")
        status_cat = categorize_status(status_raw)
        status_counts[status_cat] = status_counts.get(status_cat, 0) + 1

        duedate = item.get("duedate")
        t_bucket, days_rel = compute_timeline_bucket(duedate)
        if status_cat != "DONE":
            timeline_counts[t_bucket] = timeline_counts.get(t_bucket, 0) + 1

        chan = infer_channel_from_summary(summary)
        channel_counts[chan] = channel_counts.get(chan, 0) + 1

        assignee_name = str(item.get("assignee") or "Unassigned")
        if assignee_name.lower() in ("aalya mulla", "aadya"):
            assignee_name = "Aadya"
        elif assignee_name.lower() in ("soham", "soham das"):
            assignee_name = "Soham Das"
        assignee_u = user_by_name.get(assignee_name.lower())
        assignee_id = assignee_u.account_id if assignee_u else None
        role = TEAM_MEMBER_ROLES.get(assignee_name, "Team Member")

        # Update assignee capacity metrics for active tickets
        if assignee_u and status_cat != "DONE":
            assignee_u.open_tickets_count += 1
            if t_bucket == "OVERDUE":
                assignee_u.overdue_count += 1
            elif t_bucket == "TODAY":
                assignee_u.due_today_count += 1
            elif t_bucket == "TOMORROW":
                assignee_u.due_tomorrow_count += 1
            elif t_bucket == "DAY_AFTER":
                assignee_u.due_day_after_count += 1

        work_items.append(
            WorkItem(
                key=item["key"],
                id=item["id"],
                summary=summary,
                status=status_raw,
                status_category=status_cat,
                assignee_name=assignee_name,
                assignee_account_id=assignee_id,
                assignee_role=role,
                reporter=str(item.get("reporter") or "Anonymous"),
                duedate=duedate,
                timeline_bucket=t_bucket,
                days_relative=days_rel,
                channel=chan,
                attachment_count=item.get("attachment_count", 0),
                created=item.get("created", ""),
                updated=item.get("updated", ""),
                labels=item.get("labels", []),
            )
        )

    # Sort assignable users by core operators first, then open tickets count
    def _user_sort_key(u: JiraUser) -> tuple[int, int]:
        is_core = 0 if u.role == "Core Operator" else (1 if "Intern" in u.role else 2)
        return is_core, -u.open_tickets_count

    assignable_users.sort(key=_user_sort_key)

    return {
        "project": project,
        "total_tickets": len(work_items),
        "status_counts": status_counts,
        "timeline_counts": timeline_counts,
        "channel_counts": channel_counts,
        "assignees": [u.to_dict() for u in assignable_users],
        "work_items": [w.to_dict() for w in work_items],
        "last_synced_at": datetime.now(UTC).isoformat(),
    }


def transfer_jira_ticket(
    issue_key: str,
    to_account_id: str,
    handover_note: str = "",
    transferred_by: str = "Work Management Operator",
) -> dict[str, Any]:
    """
    Reassign a Jira ticket via Atlassian Cloud REST API and post an audit handover comment.
    """
    base_url, _, _ = get_jira_credentials()
    headers = get_jira_auth_headers()
    clean_key = issue_key.strip().upper()

    # 1. Update Assignee in Jira
    assign_url = f"{base_url}/rest/api/3/issue/{clean_key}/assignee"
    assign_body = {"accountId": to_account_id.strip()}

    resp = requests.put(assign_url, headers=headers, json=assign_body, timeout=20)
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"Could not reassign {clean_key}: HTTP {resp.status_code}: {resp.text[:200]}")

    # 2. Add Handover Comment in Jira
    comment_text = f"🔄 Ticket Transfer / Handover\nReassigned by: {transferred_by}"
    if handover_note.strip():
        comment_text += f"\nHandover Note: {handover_note.strip()}"
    comment_text += f"\nTimestamp: {datetime.now(UTC).strftime('%d-%b-%Y %H:%M UTC')}"

    add_jira_comment(clean_key, comment_text)

    # 3. Log to activity tracker
    try:
        from activity_tracker import log_activity

        log_activity(
            user=transferred_by,
            action="TICKET_TRANSFER",
            account="tata",
            channel="jira",
            details={
                "issue_key": clean_key,
                "to_account_id": to_account_id,
                "note": handover_note,
            },
            status="success",
        )
    except Exception:
        pass

    logger.info("Successfully transferred %s to account %s", clean_key, to_account_id)
    return {
        "ok": True,
        "issue_key": clean_key,
        "to_account_id": to_account_id,
        "handover_note": handover_note,
        "transferred_at": datetime.now(UTC).isoformat(),
    }


def ai_rebalance_workload(
    context_prompt: str,
    project: str = "TCN",
    auto_execute: bool = False,
    operator_name: str = "AI Workload Agent",
) -> dict[str, Any]:
    """
    Autonomous AI Workload Balancing Agent.
    Evaluates operator capacity, deadlines, and context prompt (e.g. "Dnyanesh is overloaded",
    "Allocate to interns", "Rebalance tomorrow's briefs"), producing or executing transfer actions.
    """
    dashboard = get_work_management_dashboard(project=project)
    work_items: list[dict] = dashboard["work_items"]
    assignees: list[dict] = dashboard["assignees"]

    pending_items = [w for w in work_items if w["status_category"] != "DONE"]

    proposals: list[TransferProposal] = []
    reasoning_summary = ""

    # Check for TypeSafe API key
    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()

    if api_key:
        try:
            from typesafe_sdk import Choice, Noul, TypeSafeClient

            # Identify target team member to relieve
            names_criteria = {a["name"]: f"{a['role']} ({a['open_tickets_count']} open tickets)" for a in assignees}

            with TypeSafeClient(api_key=api_key) as client:
                res = client.system_one(
                    state={"context_prompt": context_prompt, "team": assignees},
                    questions={
                        "source_operator": Choice(
                            instructions="Which team member does the user want to relieve or rebalance tickets FROM?",
                            criteria={**names_criteria, "NONE_SPECIFIED": "No single specific operator mentioned"},
                        ),
                        "target_group": Choice(
                            instructions="Who should receive the rebalanced tickets?",
                            criteria={
                                "INTERNS": "Interns / Associates (Aadya)",
                                "PEERS": "Other core operators (Mrunalini, Neel, Dnyanesh, Soham)",
                                "ALL_AVAILABLE": "Any available member with low workload",
                            },
                        ),
                        "urgency": Noul(instructions="Is this an urgent or immediate rebalancing request?"),
                    },
                )

            src_op = str(res.choices["source_operator"].choice)
            target_grp = str(res.choices["target_group"].choice)

            # Filter candidate tickets to transfer
            candidate_tickets = []
            if src_op != "NONE_SPECIFIED":
                candidate_tickets = [w for w in pending_items if w["assignee_name"].lower() == src_op.lower()]
            else:
                # Pick operator with highest load
                max_load_op = max(assignees, key=lambda a: a["open_tickets_count"])
                candidate_tickets = [w for w in pending_items if w["assignee_name"] == max_load_op["name"]]
                src_op = max_load_op["name"]

            # Filter eligible recipients
            if target_grp == "INTERNS":
                recipients = [a for a in assignees if "Intern" in a["role"]]
            elif target_grp == "PEERS":
                recipients = [a for a in assignees if a["role"] == "Core Operator" and a["name"] != src_op]
            else:
                recipients = [a for a in assignees if a["name"] != src_op and "Stakeholder" not in a["role"]]

            if not recipients:
                recipients = [a for a in assignees if a["name"] != src_op]

            # Rebalance up to 3 tickets to lowest-load recipients
            recipients.sort(key=lambda a: a["open_tickets_count"])

            for idx, item in enumerate(candidate_tickets[:3]):
                target_user = recipients[idx % len(recipients)]
                prop = TransferProposal(
                    issue_key=item["key"],
                    summary=item["summary"],
                    current_assignee=src_op,
                    target_assignee=target_user["name"],
                    target_account_id=target_user["account_id"],
                    reason=(
                        f"AI Rebalancing: {src_op} currently holds {len(candidate_tickets)} active tickets. "
                        f"Reassigning to {target_user['name']} ({target_user['role']}, {target_user['open_tickets_count']} open tickets) "
                        f"for fair-share capacity distribution."
                    ),
                )
                if auto_execute and target_user["account_id"]:
                    try:
                        transfer_jira_ticket(
                            issue_key=item["key"],
                            to_account_id=target_user["account_id"],
                            handover_note=prop.reason,
                            transferred_by=operator_name,
                        )
                        prop.executed = True
                    except Exception as err:
                        logger.warning("Could not execute AI transfer for %s: %s", item["key"], err)

                proposals.append(prop)

            reasoning_summary = (
                f"AI Workload Engine evaluated {len(pending_items)} active tickets. "
                f"Identified {src_op} as needing relief based on '{context_prompt}'. "
                f"Proposed {len(proposals)} ticket transfers to {', '.join(set(p.target_assignee for p in proposals))}."
            )

        except Exception as exc:
            logger.warning("TypeSafe AI rebalancing failed, falling back to rule engine: %s", exc)
            return _rule_based_rebalance(context_prompt, pending_items, assignees, auto_execute, operator_name)
    else:
        return _rule_based_rebalance(context_prompt, pending_items, assignees, auto_execute, operator_name)

    return {
        "ok": True,
        "context_prompt": context_prompt,
        "auto_executed": auto_execute,
        "proposals_count": len(proposals),
        "proposals": [p.to_dict() for p in proposals],
        "reasoning": reasoning_summary,
    }


def _rule_based_rebalance(
    context_prompt: str,
    pending_items: list[dict],
    assignees: list[dict],
    auto_execute: bool,
    operator_name: str,
) -> dict[str, Any]:
    """Deterministic rule-based rebalancing fallback."""
    proposals: list[TransferProposal] = []

    # Detect mentioned names in prompt
    c_lower = context_prompt.lower()
    src_user = None
    for a in assignees:
        if a["name"].lower().split()[0] in c_lower:
            src_user = a
            break

    if not src_user:
        src_user = max(assignees, key=lambda a: a["open_tickets_count"])

    candidates = [w for w in pending_items if w["assignee_name"] == src_user["name"]]
    recipients = [a for a in assignees if a["name"] != src_user["name"] and "Stakeholder" not in a["role"]]
    recipients.sort(key=lambda a: a["open_tickets_count"])

    for idx, item in enumerate(candidates[:2]):
        target = recipients[idx % len(recipients)]
        prop = TransferProposal(
            issue_key=item["key"],
            summary=item["summary"],
            current_assignee=src_user["name"],
            target_assignee=target["name"],
            target_account_id=target["account_id"],
            reason=f"Capacity rebalance: transferring from {src_user['name']} to {target['name']}.",
        )
        if auto_execute and target["account_id"]:
            try:
                transfer_jira_ticket(
                    issue_key=item["key"],
                    to_account_id=target["account_id"],
                    handover_note=prop.reason,
                    transferred_by=operator_name,
                )
                prop.executed = True
            except Exception:
                pass
        proposals.append(prop)

    return {
        "ok": True,
        "context_prompt": context_prompt,
        "auto_executed": auto_execute,
        "proposals_count": len(proposals),
        "proposals": [p.to_dict() for p in proposals],
        "reasoning": f"Rule-based rebalancing reallocated {len(proposals)} tickets from {src_user['name']}.",
    }
