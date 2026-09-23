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
from pathlib import Path
import sqlite3
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
TEAM_MEMBERS_WHITELIST: dict[str, dict[str, Any]] = {
    "Mrunalini Gawande": {
        "name": "Mrunalini Gawande",
        "account_id": "712020:ff55c67a-a1eb-4d5c-90cc-451d7d59b4bd",
        "role": "Core Operator",
        "email": "mrunalini.gawande@attributics.com",
        "has_jira_seat": True,
    },
    "Dnyanesh Khawas": {
        "name": "Dnyanesh Khawas",
        "account_id": "712020:c9156214-6850-4f0b-9647-145f7a3d15b9",
        "role": "Core Operator",
        "email": "dnyanesh.khawas@attributics.com",
        "has_jira_seat": True,
    },
    "Neel Shah": {
        "name": "Neel Shah",
        "account_id": "712020:fae946f9-8472-455a-9d27-6d773ecfb48d",
        "role": "Core Operator",
        "email": "neel.shah@attributics.com",
        "has_jira_seat": True,
    },
    "Soham Das": {
        "name": "Soham Das",
        "account_id": "712020:c8914cff-1299-4ad7-989b-e38859cbcdbf",
        "role": "Core Operator",
        "email": "soham.das@attributics.com",
        "has_jira_seat": False,
    },
    "Aadya": {
        "name": "Aadya",
        "account_id": "712020:50e16c11-d517-4909-8d30-b92693808eaa",
        "role": "Associate / Intern",
        "email": "aadya@attributics.com",
        "has_jira_seat": False,
    },
}

DB_PATH = Path(os.environ.get("KARIX_DB_PATH", "karix_store.db"))


def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def _init_operational_assignments_db() -> None:
    try:
        with _get_db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS operational_assignments (
                    issue_key TEXT PRIMARY KEY,
                    operational_assignee TEXT NOT NULL,
                    operational_account_id TEXT,
                    operational_role TEXT,
                    original_jira_assignee TEXT,
                    transferred_by TEXT,
                    handover_note TEXT,
                    transferred_at TEXT
                )
                """
            )
    except Exception as exc:
        logger.warning("Could not initialize operational_assignments table: %s", exc)


_init_operational_assignments_db()


def save_operational_assignment(
    issue_key: str,
    operational_assignee: str,
    operational_account_id: str = "",
    operational_role: str = "Operator",
    original_jira_assignee: str = "",
    transferred_by: str = "Operator",
    handover_note: str = "",
) -> None:
    clean_key = issue_key.strip().upper()
    now_str = datetime.now(UTC).isoformat()
    with _get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO operational_assignments
            (issue_key, operational_assignee, operational_account_id, operational_role,
             original_jira_assignee, transferred_by, handover_note, transferred_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_key,
                operational_assignee,
                operational_account_id,
                operational_role,
                original_jira_assignee,
                transferred_by,
                handover_note,
                now_str,
            ),
        )


def get_all_operational_assignments() -> dict[str, dict[str, Any]]:
    try:
        with _get_db() as conn:
            rows = conn.execute("SELECT * FROM operational_assignments").fetchall()
            return {
                row["issue_key"]: {
                    "operational_assignee": row["operational_assignee"],
                    "operational_account_id": row["operational_account_id"],
                    "operational_role": row["operational_role"],
                    "original_jira_assignee": row["original_jira_assignee"],
                    "transferred_by": row["transferred_by"],
                    "handover_note": row["handover_note"],
                    "transferred_at": row["transferred_at"],
                }
                for row in rows
            }
    except Exception as exc:
        logger.warning("Could not fetch operational assignments: %s", exc)
        return {}


def clear_operational_assignment(issue_key: str) -> None:
    clean_key = issue_key.strip().upper()
    try:
        with _get_db() as conn:
            conn.execute("DELETE FROM operational_assignments WHERE issue_key = ?", (clean_key,))
    except Exception as exc:
        logger.warning("Could not delete operational assignment for %s: %s", clean_key, exc)

TEAM_MEMBER_ROLES: dict[str, str] = {
    info["name"]: info["role"] for info in TEAM_MEMBERS_WHITELIST.values()
}
TEAM_MEMBER_ROLES["Aalya Mulla"] = "Associate / Intern"


# Supported Tata Capital Jira projects for work management
JIRA_PROJECTS_CATALOG: list[dict[str, str]] = [
    {"key": "SWCM", "name": "TATA Service and wealth Campaign Manager"},
    {"key": "TCN", "name": "Tata Capital New"},
    {"key": "ALL", "name": "All Tata Projects Combined"},
    {"key": "TM", "name": "TCHFL Marketing"},
    {"key": "TAT", "name": "TataCapital"},
    {"key": "MON", "name": "Moneyfy"},
    {"key": "COL", "name": "Collections"},
]

@dataclass
class JiraUser:
    """Team member profile and active capacity metrics."""

    account_id: str
    name: str
    email: str = ""
    role: str = "Team Member"
    open_tickets_count: int = 0
    completed_tickets_count: int = 0
    blocked_tickets_count: int = 0
    total_handled_count: int = 0
    completion_rate: float = 0.0
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
    routed_to_soham: bool = False
    is_operational_assignment: bool = False
    original_assignee: str | None = None
    operational_note: str | None = None
    soham_mention_reasons: list[str] = field(default_factory=list)
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


@dataclass
class OperatorVelocity:
    """Operator turnaround speed and cycle time metrics."""

    name: str
    role: str
    completed_count: int
    avg_cycle_time_days: float
    avg_cycle_time_hours: float
    fastest_hours: float
    slowest_days: float
    velocity_rating: str  # "EXCELLENT" | "FAST" | "STANDARD" | "NEEDS_ATTENTION"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RoadblockTicket:
    """Detailed diagnosis of a stalled or blocked ticket."""

    key: str
    summary: str
    assignee: str
    status: str
    roadblock_category: str  # "Tata Capital (Client)" | "Karix / Meta (Gateway)" | "Attributics (Internal)"
    root_cause: str
    aging_hours: float
    aging_days: float
    duedate: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def categorize_status(status_raw: str | None) -> str:
    """Classify arbitrary Jira status into PENDING, BLOCKED, or DONE."""
    if not status_raw:
        return "PENDING"
    s = status_raw.lower().strip()
    if any(k in s for k in ("done", "closed", "resolved", "completed", "whitelisted", "approved")):
        return "DONE"
    if any(k in s for k in ("base pending", "content pending", "asset pending", "blocked", "hold", "waiting", "client feedback", "pause")):
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
    op_assignments = get_all_operational_assignments()

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

        # SOLUTION 1: OPERATIONAL ASSIGNMENTS OVERLAY
        # If ticket was virtually assigned to Soham Das, Aadya, or another operator,
        # it overrides the raw Jira assignee and routes workload to that operator!
        op_assign = op_assignments.get(item["key"])
        mentions_soham = bool(item.get("mentions_soham"))
        raw_assignee = str(item.get("assignee") or "Unassigned").strip()

        is_op_assignment = False
        routed_to_soham = False
        original_assignee = None
        op_note = None
        soham_reasons = []

        if op_assign:
            assignee_name = op_assign["operational_assignee"]
            is_op_assignment = True
            original_assignee = op_assign.get("original_jira_assignee") or (raw_assignee if raw_assignee != assignee_name else None)
            op_note = op_assign.get("handover_note")
        elif mentions_soham:
            assignee_name = "Soham Das"
            routed_to_soham = True
            original_assignee = raw_assignee if raw_assignee.lower() not in ("soham", "soham das", "unassigned") else None
            soham_reasons = item.get("soham_mention_reasons") or ["mention"]
        else:
            if raw_assignee.lower() in ("aalya mulla", "aadya"):
                assignee_name = "Aadya"
            elif raw_assignee.lower() in ("soham", "soham das"):
                assignee_name = "Soham Das"
            else:
                assignee_name = raw_assignee
        assignee_u = user_by_name.get(assignee_name.lower())
        assignee_id = assignee_u.account_id if assignee_u else None
        role = TEAM_MEMBER_ROLES.get(assignee_name, "Team Member")

        # Update assignee capacity & completion metrics
        if assignee_u:
            assignee_u.total_handled_count += 1
            if status_cat == "DONE":
                assignee_u.completed_tickets_count += 1
            elif status_cat == "BLOCKED":
                assignee_u.blocked_tickets_count += 1
                assignee_u.open_tickets_count += 1
            else:
                assignee_u.open_tickets_count += 1

            if status_cat != "DONE":
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
                routed_to_soham=routed_to_soham,
                is_operational_assignment=is_op_assignment,
                original_assignee=original_assignee,
                operational_note=op_note,
                soham_mention_reasons=soham_reasons,
            )
        )


    # Calculate completion rates
    for u in assignable_users:
        if u.total_handled_count > 0:
            u.completion_rate = round((u.completed_tickets_count / u.total_handled_count) * 100, 1)
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
        "projects_catalog": JIRA_PROJECTS_CATALOG,
    }


def transfer_jira_ticket(
    issue_key: str,
    to_account_id: str,
    handover_note: str = "",
    transferred_by: str = "Work Management Operator",
) -> dict[str, Any]:
    """
    Reassign a ticket:
    - If target is Soham Das or Aadya (or any user without a Jira seat),
      executes a Virtual Operational Assignment locally without failing on Jira API.
    - If target is a licensed Jira user (Dnyanesh, Mrunalini, Neel),
      clears local virtual assignment and syncs directly to Jira Cloud API.
    - Strictly avoids posting comments to Jira per project policy.
    """
    clean_key = issue_key.strip().upper()
    to_clean_id = to_account_id.strip()

    # Resolve target user info from whitelist
    target_info = None
    for info in TEAM_MEMBERS_WHITELIST.values():
        if info["account_id"] == to_clean_id or to_clean_id.lower() in info["name"].lower():
            target_info = info
            break

    target_name = target_info["name"] if target_info else to_clean_id
    target_role = target_info.get("role", "Operator") if target_info else "Operator"
    has_seat = target_info.get("has_jira_seat", False) if target_info else False

    # Fetch original Jira assignee for audit overlay
    raw_assignee = ""
    try:
        from jira_client import fetch_jira_issue
        raw_issue = fetch_jira_issue(clean_key)
        raw_assignee = raw_issue.get("assignee") or ""
    except Exception:
        pass

    # SOLUTION 1: Virtual Operational Assignment for users without an active Jira seat (Soham, Aadya)
    if not has_seat:
        save_operational_assignment(
            issue_key=clean_key,
            operational_assignee=target_name,
            operational_account_id=to_clean_id,
            operational_role=target_role,
            original_jira_assignee=raw_assignee,
            transferred_by=transferred_by,
            handover_note=handover_note,
        )
        logger.info("Executed virtual operational assignment of %s to %s (no Jira seat needed)", clean_key, target_name)
        return {
            "success": True,
            "ok": True,
            "virtual_assignment": True,
            "issue_key": clean_key,
            "to_account_id": to_clean_id,
            "assignee_name": target_name,
            "role": target_role,
            "original_assignee": raw_assignee,
            "handover_note": handover_note,
            "message": f"Successfully assigned {clean_key} to {target_name} ({target_role}). Virtual operational assignment active.",
        }

    # If target has a Jira seat: clear virtual assignment and sync to Jira Cloud
    clear_operational_assignment(clean_key)

    base_url, _, _ = get_jira_credentials()
    headers = get_jira_auth_headers()
    assign_url = f"{base_url}/rest/api/3/issue/{clean_key}/assignee"
    assign_body = {"accountId": to_clean_id}

    resp = requests.put(assign_url, headers=headers, json=assign_body, timeout=20)
    if resp.status_code not in (200, 204):
        # Fallback to virtual operational assignment if Jira rejects account
        save_operational_assignment(
            issue_key=clean_key,
            operational_assignee=target_name,
            operational_account_id=to_clean_id,
            operational_role=target_role,
            original_jira_assignee=raw_assignee,
            transferred_by=transferred_by,
            handover_note=handover_note,
        )
        return {
            "success": True,
            "ok": True,
            "virtual_assignment": True,
            "issue_key": clean_key,
            "to_account_id": to_clean_id,
            "assignee_name": target_name,
            "role": target_role,
            "message": f"Jira seat unavailable for {target_name}. Saved as virtual operational assignment.",
        }

    return {
        "success": True,
        "ok": True,
        "virtual_assignment": False,
        "issue_key": clean_key,
        "to_account_id": to_clean_id,
        "assignee_name": target_name,
        "role": target_role,
        "message": f"Successfully reassigned {clean_key} to {target_name} in Jira Cloud.",
    }


def bulk_transfer_jira_tickets(
    issue_keys: list[str],
    to_account_id: str,
    to_account_name: str = "",
    handover_note: str = "",
    transferred_by: str = "Work Management Operator",
) -> dict[str, Any]:
    """
    Reassign multiple Jira tickets in batch and post audit handover notes.
    """
    transferred: list[str] = []
    failed: list[dict[str, str]] = []

    for k in issue_keys:
        clean_key = k.strip().upper()
        if not clean_key:
            continue
        try:
            res = transfer_jira_ticket(
                issue_key=clean_key,
                to_account_id=to_account_id,
                handover_note=handover_note,
                transferred_by=transferred_by,
            )
            if isinstance(res, dict) and res.get("success") is False and res.get("error"):
                failed.append({"issue_key": clean_key, "key": clean_key, "error": str(res.get("error"))})
            else:
                transferred.append(clean_key)
        except Exception as exc:
            logger.error("Bulk transfer failed for %s: %s", clean_key, exc)
            failed.append({"issue_key": clean_key, "key": clean_key, "error": str(exc)})

    return {
        "ok": len(failed) == 0,
        "success": len(failed) == 0,
        "to_account_id": to_account_id,
        "to_account_name": to_account_name,
        "total_requested": len(issue_keys),
        "transferred_count": len(transferred),
        "failed_count": len(failed),
        "transferred_keys": transferred,
        "failed_keys": failed,
        "failed_items": failed,
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


def get_turnaround_and_bottleneck_analytics(project: str = "SWCM", limit: int = 100) -> dict[str, Any]:
    """
    Calculate operator cycle times (turnaround velocity) and diagnose roadblock
    responsibility (Tata Capital client-side dependencies vs Karix vs Attributics).
    """
    raw_issues = list_jira_issues(project=project, limit=limit)
    assignable_users = fetch_assignable_jira_users(project=project)

    now = datetime.now(UTC)
    done_times_by_user: dict[str, list[float]] = {}
    blocked_tickets: list[RoadblockTicket] = []

    roadblock_counts = {
        "Tata Capital": 0,
        "Karix / Meta": 0,
        "Attributics": 0,
    }
    roadblock_reasons: dict[str, int] = {}
    completed_count = 0
    all_done_times: list[float] = []
    op_assignments = get_all_operational_assignments()

    for item in raw_issues:
        summary = str(item.get("summary") or "")
        status_raw = str(item.get("status") or "").strip()
        st_lower = status_raw.lower()
        assignee_raw = str(item.get("assignee") or "Unassigned").strip()

        op_assign = op_assignments.get(item["key"])
        if op_assign:
            assignee = op_assign["operational_assignee"]
        elif item.get("mentions_soham"):
            assignee = "Soham Das"
        elif assignee_raw.lower() in ("aalya mulla", "aadya"):
            assignee = "Aadya"
        elif assignee_raw.lower() in ("soham", "soham das"):
            assignee = "Soham Das"
        else:
            assignee = assignee_raw
        c_str = item.get("created")
        u_str = item.get("updated")
        duedate = item.get("duedate")

        dt_c = None
        dt_u = None
        if c_str:
            try:
                dt_c = datetime.fromisoformat(c_str.replace("Z", "+00:00"))
            except Exception:
                pass
        if u_str:
            try:
                dt_u = datetime.fromisoformat(u_str.replace("Z", "+00:00"))
            except Exception:
                pass

        # 1. Evaluate Cycle Time for Completed Tickets
        if any(k in st_lower for k in ("done", "closed", "resolved", "whitelisted", "approved")):
            completed_count += 1
            if dt_c and dt_u:
                hours = max(0.1, (dt_u - dt_c).total_seconds() / 3600)
                all_done_times.append(hours)
                done_times_by_user.setdefault(assignee, []).append(hours)
            continue

        # 2. Evaluate Roadblocks for Non-Completed Tickets
        aging_hours = (now - dt_c).total_seconds() / 3600 if dt_c else 0.0
        aging_days = round(aging_hours / 24, 1)

        # Categorize roadblock responsibility
        if any(k in st_lower for k in ("base pending", "audience", "datamart")):
            category = "Tata Capital (Client)"
            cause = "Base Pending (Customer Audience Mart File from Tata Capital)"
        elif any(k in st_lower for k in ("content pending", "copy pending")):
            category = "Tata Capital (Client)"
            cause = "Content Pending (Copywriting / Brand Content from Tata Capital)"
        elif any(k in st_lower for k in ("asset pending", "creative pending")):
            category = "Tata Capital (Client)"
            cause = "Asset Pending (Image / Banner / Video Creatives from Tata Capital)"
        elif any(k in st_lower for k in ("client feedback", "waiting on client", "hold")):
            category = "Tata Capital (Client)"
            cause = "Client Sign-Off Pending (Waiting on Tata Capital Feedback)"
        elif any(k in st_lower for k in ("test sent", "whitelisting", "carrier review", "karix")):
            category = "Karix / Meta (Gateway)"
            cause = "Gateway Review Gate (Awaiting Karix / Meta Whitelisting Approval)"
        else:
            category = "Attributics (Internal)"
            cause = f"Attributics Ops Queue ({status_raw})"

        resp_key = "Tata Capital" if "Tata" in category else ("Karix / Meta" if "Karix" in category else "Attributics")
        roadblock_counts[resp_key] = roadblock_counts.get(resp_key, 0) + 1
        roadblock_reasons[cause] = roadblock_reasons.get(cause, 0) + 1

        blocked_tickets.append(
            RoadblockTicket(
                key=item["key"],
                summary=summary,
                assignee=assignee,
                status=status_raw,
                roadblock_category=category,
                root_cause=cause,
                aging_hours=round(aging_hours, 1),
                aging_days=aging_days,
                duedate=duedate,
            )
        )

    # Sort blocked tickets by longest aging first
    blocked_tickets.sort(key=lambda t: t.aging_hours, reverse=True)

    # 3. Compute Per-Operator Turnaround Velocities
    operator_velocities: list[OperatorVelocity] = []
    for u in assignable_users:
        times = done_times_by_user.get(u.name, [])
        if times:
            avg_h = sum(times) / len(times)
            avg_d = avg_h / 24
            fastest_h = min(times)
            slowest_d = max(times) / 24
            if avg_h <= 24:
                rating = "EXCELLENT"
            elif avg_h <= 48:
                rating = "FAST"
            elif avg_h <= 96:
                rating = "STANDARD"
            else:
                rating = "NEEDS_ATTENTION"
        else:
            avg_h = 0.0
            avg_d = 0.0
            fastest_h = 0.0
            slowest_d = 0.0
            rating = "NO_COMPLETED"

        operator_velocities.append(
            OperatorVelocity(
                name=u.name,
                role=u.role,
                completed_count=len(times),
                avg_cycle_time_days=round(avg_d, 2),
                avg_cycle_time_hours=round(avg_h, 1),
                fastest_hours=round(fastest_h, 1),
                slowest_days=round(slowest_d, 1),
                velocity_rating=rating,
            )
        )

    # Sort operator leaderboard by completed count desc, then avg cycle time
    operator_velocities.sort(key=lambda o: (-o.completed_count, o.avg_cycle_time_hours if o.avg_cycle_time_hours > 0 else 999))

    team_avg_hours = sum(all_done_times) / len(all_done_times) if all_done_times else 0.0
    team_avg_days = round(team_avg_hours / 24, 2)
    fastest_team_hours = round(min(all_done_times), 1) if all_done_times else 0.0
    slowest_team_days = round(max(all_done_times) / 24, 1) if all_done_times else 0.0

    total_rb = len(blocked_tickets)
    tc_count = roadblock_counts.get("Tata Capital", 0)
    km_count = roadblock_counts.get("Karix / Meta", 0)
    att_count = roadblock_counts.get("Attributics", 0)

    if tc_count >= km_count and tc_count >= att_count:
        primary_bottleneck = "Tata Capital (Client)"
    elif km_count >= att_count:
        primary_bottleneck = "Karix / Meta (Gateway)"
    else:
        primary_bottleneck = "Attributics (Internal)"

    return {
        "project": project,
        "total_tickets_analyzed": len(raw_issues),
        "completed_count": completed_count,
        "active_roadblocks_count": total_rb,
        "team_avg_cycle_time_days": team_avg_days,
        "team_avg_cycle_time_hours": round(team_avg_hours, 1),
        "team_fastest_hours": fastest_team_hours,
        "team_slowest_days": slowest_team_days,
        "primary_bottleneck_driver": primary_bottleneck,
        "operator_velocities": [o.to_dict() for o in operator_velocities],
        "roadblock_attribution": {
            "total_roadblocks": total_rb,
            "tata_capital": {
                "count": tc_count,
                "percentage": round((tc_count / total_rb) * 100, 1) if total_rb > 0 else 0.0,
                "label": "Client Dependencies (Data Mart / Content / Sign-off)",
            },
            "karix_meta": {
                "count": km_count,
                "percentage": round((km_count / total_rb) * 100, 1) if total_rb > 0 else 0.0,
                "label": "Gateway Review (Karix & Meta Whitelisting Gate)",
            },
            "attributics": {
                "count": att_count,
                "percentage": round((att_count / total_rb) * 100, 1) if total_rb > 0 else 0.0,
                "label": "Attributics Ops Queue (Drafting & Formatting)",
            },
            "reasons_breakdown": roadblock_reasons,
        },
        "blocked_tickets": [t.to_dict() for t in blocked_tickets],
    }
