"""
Automated 3-Stage Daily SLA Email Dispatcher & Scheduler.

Schedules & dispatches progressive SLA notifications for campaigns due today that are incomplete:
1. 10:00 AM IST (Kickoff): Morning briefing stating total campaigns due today.
2. 01:00 PM IST (Midday): Progress check stating remaining pending campaigns.
3. 04:00 PM IST (EOD Escalation): Urgent alert warning that remaining unfinished campaigns require immediate attention.

Includes:
- 1-click manual trigger and preview endpoints.
- Continuous background scheduler loop matching IST (UTC+5:30) 10:00, 13:00, and 16:00 slots.
- Multi-recipient resolution from TEAM_MEMBERS_WHITELIST.
- Safe SMTP delivery with graceful simulation / dry-run fallback.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
import email.mime.multipart
import email.mime.text
import logging
import os
import smtplib
from typing import Any

from config import _load_env_file
from work_manager import (
    TEAM_MEMBERS_WHITELIST,
    get_work_management_dashboard,
)

logger = logging.getLogger(__name__)
_load_env_file()

IST_OFFSET = timedelta(hours=5, minutes=30)


def get_current_ist_time() -> datetime:
    """Return the current time in Indian Standard Time (IST, UTC+5:30)."""
    return datetime.now(UTC) + IST_OFFSET


def determine_current_stage(ist_now: datetime | None = None) -> str:
    """
    Determine the appropriate stage based on current IST time:
    - Before 12:00 PM IST -> MORNING (10:00 AM Kickoff)
    - 12:00 PM to 3:30 PM IST -> MIDDAY (1:00 PM Progress Check)
    - 3:30 PM IST onward -> EOD (4:00 PM Urgent Escalation)
    """
    now = ist_now or get_current_ist_time()
    hour = now.hour
    minute = now.minute

    total_minutes = hour * 60 + minute
    if total_minutes < 12 * 60:
        return "MORNING"
    elif total_minutes < 15 * 60 + 30:
        return "MIDDAY"
    else:
        return "EOD"


@dataclass
class OperatorTicketSummary:
    """Group of due-today incomplete tickets assigned to an operator."""
    operator_name: str
    operator_email: str
    role: str
    pending_count: int
    tickets: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AlertEmailDraft:
    """Prepared email ready for dispatch."""
    stage: str  # MORNING, MIDDAY, EOD
    recipient_email: str
    recipient_name: str
    subject: str
    body_text: str
    body_html: str
    pending_count: int
    ticket_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AlertSchedulerState:
    """In-memory state of the automated daily alert scheduler."""
    def __init__(self) -> None:
        self.enabled: bool = True
        self.last_sent: dict[str, str] = {}  # key: "YYYY-MM-DD_STAGE" -> timestamp
        self.history: list[dict[str, Any]] = []
        self.task: asyncio.Task | None = None

    def mark_sent(self, day_str: str, stage: str, details: dict[str, Any]) -> None:
        key = f"{day_str}_{stage}"
        self.last_sent[key] = datetime.now(UTC).isoformat()
        self.history.append({
            "slot_key": key,
            "stage": stage,
            "date": day_str,
            "dispatched_at": datetime.now(UTC).isoformat(),
            **details,
        })
        if len(self.history) > 100:
            self.history = self.history[-100:]

    def is_already_sent_today(self, day_str: str, stage: str) -> bool:
        return f"{day_str}_{stage}" in self.last_sent


SCHEDULER_STATE = AlertSchedulerState()


def get_due_today_incomplete_tickets(project: str = "ALL") -> list[dict[str, Any]]:
    """
    Query work items due today (timeline_bucket == 'TODAY') and not done (status_category != 'DONE').
    """
    dash = get_work_management_dashboard(project=project, limit=100)
    items = dash.get("work_items", [])
    incomplete_today = [
        item for item in items
        if item.get("timeline_bucket") == "TODAY" and item.get("status_category") != "DONE"
    ]
    return incomplete_today


def group_tickets_by_operator(tickets: list[dict[str, Any]]) -> list[OperatorTicketSummary]:
    """Group tickets by assignee and resolve their verified corporate email."""
    by_name: dict[str, list[dict[str, Any]]] = {}
    for t in tickets:
        name = str(t.get("assignee_name") or "Unassigned").strip()
        by_name.setdefault(name, []).append(t)

    summaries: list[OperatorTicketSummary] = []
    for name, op_tickets in by_name.items():
        # Match from whitelist
        wl_info = TEAM_MEMBERS_WHITELIST.get(name)
        if not wl_info:
            # Check lowercase matching
            for k, val in TEAM_MEMBERS_WHITELIST.items():
                if k.lower() == name.lower() or name.lower() in k.lower():
                    wl_info = val
                    break

        if wl_info:
            email_addr = wl_info["email"]
            role = wl_info["role"]
        else:
            # Default fallback for operator
            sanitized = name.lower().replace(" ", ".")
            email_addr = f"{sanitized}@attributics.com" if name != "Unassigned" else "ops-lead@attributics.com"
            role = "Operator"

        summaries.append(
            OperatorTicketSummary(
                operator_name=name,
                operator_email=email_addr,
                role=role,
                pending_count=len(op_tickets),
                tickets=op_tickets,
            )
        )

    # Sort operators with highest pending count first
    summaries.sort(key=lambda s: s.pending_count, reverse=True)
    return summaries


def build_stage_email(
    operator: OperatorTicketSummary,
    stage: str,
    today_str: str,
    project: str = "TATA",
) -> AlertEmailDraft:
    """Generate HTML and plain text email content tailored to the stage."""
    count = operator.pending_count
    ticket_keys = [t.get("key", "") for t in operator.tickets]
    # Stage-specific messaging
    if stage == "MORNING":
        badge_color = "#4f46e5"  # indigo
        badge_title = "10:00 AM KICKOFF • DAILY WORKLOAD BRIEF"
        subject = f"[10:00 AM Kickoff] You have {count} campaign(s) scheduled for delivery today ({today_str})"
        intro_heading = f"Good morning {operator.operator_name}!"
        intro_msg = (
            f"Here is your daily campaign workload brief. You have <strong>{count} campaign(s)</strong> "
            f"due today across the {project} queue. Please review copy, creative assets, and carrier "
            f"whitelist approval gates early to ensure on-time delivery."
        )
        urgency_note = "Goal: Aim to resolve carrier gateway and drafting dependencies before 1:00 PM."

    elif stage == "MIDDAY":
        badge_color = "#d97706"  # amber
        badge_title = "1:00 PM CHECKPOINT • MIDDAY THROUGHPUT STATUS"
        subject = f"[1:00 PM Checkpoint] {count} campaign(s) still pending today ({today_str})"
        intro_heading = f"Midday Status Check — {operator.operator_name}"
        intro_msg = (
            f"Midday SLA Checkpoint: You currently have <strong>{count} campaign(s)</strong> still pending completion "
            f"for today's dispatch. If you are waiting on Tata Capital audience files or Meta review approvals, "
            f"please flag them to leadership immediately."
        )
        urgency_note = "Action: Expedite gateway submissions or flag roadblocks before the 4:00 PM final window."

    else:  # EOD / URGENT
        badge_color = "#dc2626"  # red
        badge_title = "🚨 4:00 PM URGENT • ATTENTION REQUIRED"
        subject = f"🚨 [Action Required] {count} campaign(s) due today require your urgent attention"
        intro_heading = f"Action Required: Unfinished Campaigns — {operator.operator_name}"
        intro_msg = (
            f"<strong>URGENT SLA WARNING:</strong> You have <strong>{count} campaign(s)</strong> due today that remain "
            f"incomplete as of 4:00 PM. Immediate attention is required to prevent an SLA breach. "
            f"Please complete your submissions or initiate an emergency rebalance to available interns immediately."
        )
        urgency_note = "CRITICAL: Final carrier delivery window closes at 6:00 PM. Escalate any client blockers now."

    # Build tickets table HTML
    rows_html = ""
    rows_text = ""
    for t in operator.tickets:
        k = t.get("key", "")
        summary = t.get("summary", "")
        status = t.get("status", "Pending")
        channel = t.get("channel", "General")
        jira_url = f"https://tatacapital-team.atlassian.net/browse/{k}"

        rows_html += f"""
        <tr style="border-bottom: 1px solid #f3f4f6;">
            <td style="padding: 10px 12px; font-weight: bold;">
                <a href="{jira_url}" style="color: #4f46e5; text-decoration: none;">{k}</a>
            </td>
            <td style="padding: 10px 12px; color: #1f2937;">{summary}</td>
            <td style="padding: 10px 12px; color: #4b5563; font-size: 11px;">{channel}</td>
            <td style="padding: 10px 12px;">
                <span style="display: inline-block; padding: 2px 8px; border-radius: 9999px; font-size: 10px; font-weight: bold; background-color: #fef3c7; color: #92400e;">
                    {status}
                </span>
            </td>
        </tr>
        """
        rows_text += f"- [{k}] {summary} (Channel: {channel}, Status: {status})\n  Link: {jira_url}\n"

    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{subject}</title>
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 24px; background-color: #f9fafb; color: #111827;">
        <div style="max-width: 640px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; border: 1px solid #e5e7eb; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="background-color: {badge_color}; padding: 16px 24px; color: #ffffff;">
                <div style="font-size: 11px; font-weight: 800; letter-spacing: 0.05em; text-transform: uppercase; opacity: 0.9;">
                    {badge_title}
                </div>
                <h1 style="font-size: 18px; font-weight: 700; margin: 6px 0 0 0; color: #ffffff;">
                    {intro_heading}
                </h1>
            </div>

            <div style="padding: 24px;">
                <p style="font-size: 14px; line-height: 1.6; color: #374151; margin-top: 0;">
                    {intro_msg}
                </p>

                <div style="margin: 20px 0; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden;">
                    <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 12px;">
                        <thead>
                            <tr style="background-color: #f9fafb; border-bottom: 1px solid #e5e7eb; color: #6b7280; font-size: 10px; text-transform: uppercase;">
                                <th style="padding: 8px 12px;">Ticket</th>
                                <th style="padding: 8px 12px;">Campaign</th>
                                <th style="padding: 8px 12px;">Channel</th>
                                <th style="padding: 8px 12px;">Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows_html}
                        </tbody>
                    </table>
                </div>

                <div style="padding: 12px 16px; background-color: #f3f4f6; border-left: 4px solid {badge_color}; border-radius: 4px; font-size: 12px; color: #4b5563; margin-bottom: 20px;">
                    <strong>Notice:</strong> {urgency_note}
                </div>

                <div style="text-align: center; margin-top: 24px;">
                    <a href="https://tatacapital-team.atlassian.net" style="display: inline-block; padding: 10px 20px; background-color: #111827; color: #ffffff; text-decoration: none; border-radius: 6px; font-size: 12px; font-weight: bold;">
                        Open Jira Dispatcher &rarr;
                    </a>
                </div>
            </div>

            <div style="padding: 16px 24px; background-color: #f9fafb; border-top: 1px solid #e5e7eb; text-align: center; font-size: 11px; color: #9ca3af;">
                Attributics Automated Jira SLA Dispatcher • Sent at {get_current_ist_time().strftime('%I:%M %p IST')}
            </div>
        </div>
    </body>
    </html>
    """

    body_text = f"""
{subject}

{intro_heading}
{intro_msg}

Assigned Incomplete Campaigns:
{rows_text}

Notice: {urgency_note}

Jira Link: https://tatacapital-team.atlassian.net
Sent at {get_current_ist_time().strftime('%I:%M %p IST')} by Attributics SLA Dispatcher.
    """.strip()

    return AlertEmailDraft(
        stage=stage,
        recipient_email=operator.operator_email,
        recipient_name=operator.operator_name,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        pending_count=count,
        ticket_keys=ticket_keys,
    )


def get_smtp_sender_info() -> dict[str, Any]:
    """Inspect environment variables and return active SMTP sender configuration."""
    _load_env_file()
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT") or "587")
    smtp_user = os.getenv("SMTP_USER")
    from_email = os.getenv("SMTP_FROM_EMAIL") or smtp_user or "alerts@attributics.com"
    is_configured = bool(smtp_host and smtp_user and os.getenv("SMTP_PASSWORD"))

    return {
        "is_configured": is_configured,
        "from_email": from_email,
        "smtp_host": smtp_host or "Not configured",
        "smtp_port": smtp_port,
        "smtp_user": smtp_user or "Not configured",
        "mode": "LIVE_SMTP" if is_configured else "SIMULATION",
    }


def preview_due_today_alerts(
    project: str = "ALL",
    stage: str = "AUTO",
) -> dict[str, Any]:
    """
    Generate drafts of all alert emails that would be sent right now.
    """
    resolved_stage = determine_current_stage() if stage == "AUTO" else stage.upper()
    today_str = date.today().isoformat()
    tickets = get_due_today_incomplete_tickets(project=project)
    operators = group_tickets_by_operator(tickets)
    sender_info = get_smtp_sender_info()

    drafts: list[AlertEmailDraft] = [
        build_stage_email(op, resolved_stage, today_str, project=project)
        for op in operators
    ]

    ist_now = get_current_ist_time()
    return {
        "ok": True,
        "project": project,
        "stage": resolved_stage,
        "ist_time": ist_now.strftime("%Y-%m-%d %H:%M:%S IST"),
        "sender_info": sender_info,
        "total_due_today_incomplete": len(tickets),
        "recipient_count": len(drafts),
        "drafts": [d.to_dict() for d in drafts],
    }

def send_email_smtp(draft: AlertEmailDraft) -> dict[str, Any]:
    """
    Send one draft email via SMTP. Falls back gracefully to simulation if SMTP is unconfigured.
    """
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT") or "587")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("SMTP_FROM_EMAIL") or smtp_user or "alerts@attributics.com"

    if not smtp_host or not smtp_user or not smtp_pass:
        logger.info(
            "SMTP not fully configured (host=%s, user=%s). Simulating send to %s (%s).",
            smtp_host, smtp_user, draft.recipient_email, draft.subject
        )
        return {
            "delivered": True,
            "simulated": True,
            "recipient": draft.recipient_email,
            "subject": draft.subject,
            "message": "Email simulated successfully (SMTP credentials not configured in environment).",
        }

    try:
        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg["Subject"] = draft.subject
        msg["From"] = from_email
        msg["To"] = draft.recipient_email

        part1 = email.mime.text.MIMEText(draft.body_text, "plain", "utf-8")
        part2 = email.mime.text.MIMEText(draft.body_html, "html", "utf-8")
        msg.attach(part1)
        msg.attach(part2)

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            if smtp_port != 465:
                server.starttls()
                server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, [draft.recipient_email], msg.as_string())

        logger.info("Successfully sent alert email to %s: %s", draft.recipient_email, draft.subject)
        return {
            "delivered": True,
            "simulated": False,
            "recipient": draft.recipient_email,
            "subject": draft.subject,
            "message": "Email delivered via SMTP server.",
        }
    except Exception as exc:
        logger.error("Failed to send alert email via SMTP to %s: %s", draft.recipient_email, exc)
        return {
            "delivered": False,
            "simulated": False,
            "recipient": draft.recipient_email,
            "error": str(exc),
            "message": f"SMTP delivery failed: {exc}",
        }


def dispatch_due_today_alerts(
    project: str = "ALL",
    stage: str = "AUTO",
    dry_run: bool = False,
    operator_name: str = "Automated Dispatcher",
) -> dict[str, Any]:
    """
    Dispatch due-today alert emails to all operators.
    """
    preview = preview_due_today_alerts(project=project, stage=stage)
    resolved_stage = preview["stage"]
    draft_dicts = preview["drafts"]

    results: list[dict[str, Any]] = []
    delivered_count = 0
    failed_count = 0

    today_str = date.today().isoformat()

    for d_dict in draft_dicts:
        draft = AlertEmailDraft(**d_dict)
        if dry_run:
            results.append({
                "delivered": True,
                "simulated": True,
                "recipient": draft.recipient_email,
                "subject": draft.subject,
                "message": "Dry run preview mode — no real network packets dispatched.",
            })
            delivered_count += 1
        else:
            send_res = send_email_smtp(draft)
            if send_res.get("delivered"):
                delivered_count += 1
            else:
                failed_count += 1
            results.append(send_res)

    sender_info = preview["sender_info"]
    real_sent_count = sum(1 for r in results if r.get("delivered") and not r.get("simulated"))
    simulated_count = sum(1 for r in results if r.get("simulated"))

    # Mark sent in scheduler state
    SCHEDULER_STATE.mark_sent(
        day_str=today_str,
        stage=resolved_stage,
        details={
            "delivered_count": delivered_count,
            "real_sent_count": real_sent_count,
            "simulated_count": simulated_count,
            "failed_count": failed_count,
            "from_email": sender_info["from_email"],
            "smtp_host": sender_info["smtp_host"],
            "recipients": [d["recipient_email"] for d in draft_dicts],
            "operator_name": operator_name,
            "dry_run": dry_run,
        }
    )

    return {
        "ok": True,
        "stage": resolved_stage,
        "date": today_str,
        "sender_info": sender_info,
        "total_tickets": preview["total_due_today_incomplete"],
        "recipients_count": len(draft_dicts),
        "delivered_count": delivered_count,
        "real_sent_count": real_sent_count,
        "simulated_count": simulated_count,
        "failed_count": failed_count,
        "dry_run": dry_run,
        "dispatched_by": operator_name,
        "results": results,
    }


async def run_scheduler_loop() -> None:
    """
    Background continuous scheduler loop.
    Checks IST time every 30 seconds and automatically dispatches at:
    - 10:00 AM IST (MORNING)
    - 01:00 PM IST (MIDDAY)
    - 04:00 PM IST (EOD)
    """
    logger.info("Starting Daily SLA Email Alert Scheduler loop (checking 10:00, 13:00, 16:00 IST slots)...")
    while True:
        try:
            if SCHEDULER_STATE.enabled:
                now_ist = get_current_ist_time()
                today_str = now_ist.date().isoformat()
                hour = now_ist.hour
                minute = now_ist.minute

                # Check 10:00 AM slot (10:00 to 10:05 window)
                if hour == 10 and 0 <= minute <= 5:
                    if not SCHEDULER_STATE.is_already_sent_today(today_str, "MORNING"):
                        logger.info("Triggering automated 10:00 AM IST Kickoff SLA reminder...")
                        dispatch_due_today_alerts(project="ALL", stage="MORNING", operator_name="Daily 10:00 AM Scheduler")

                # Check 1:00 PM slot (13:00 to 13:05 window)
                elif hour == 13 and 0 <= minute <= 5:
                    if not SCHEDULER_STATE.is_already_sent_today(today_str, "MIDDAY"):
                        logger.info("Triggering automated 1:00 PM IST Midday Checkpoint SLA reminder...")
                        dispatch_due_today_alerts(project="ALL", stage="MIDDAY", operator_name="Daily 1:00 PM Scheduler")

                # Check 4:00 PM slot (16:00 to 16:05 window)
                elif hour == 16 and 0 <= minute <= 5:
                    if not SCHEDULER_STATE.is_already_sent_today(today_str, "EOD"):
                        logger.info("Triggering automated 4:00 PM IST EOD Escalation SLA reminder...")
                        dispatch_due_today_alerts(project="ALL", stage="EOD", operator_name="Daily 4:00 PM Scheduler")

        except Exception as exc:
            logger.error("Error in alert scheduler loop: %s", exc)

        await asyncio.sleep(30)
