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
import email.mime.multipart
import email.mime.text
import json
import logging
import os
import smtplib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
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


STAGE_SCHEDULE: dict[str, dict[str, Any]] = {
    "MORNING": {
        "title": "10:00 AM SLA Kickoff • Daily Workload",
        "scheduled_time": "10:00 AM IST",
        "window_start_minutes": 9 * 60 + 55,  # 09:55 AM
        "window_end_minutes": 10 * 60 + 15,  # 10:15 AM
        "window_label": "09:55 AM – 10:15 AM IST",
    },
    "MIDDAY": {
        "title": "1:00 PM SLA Checkpoint • Midday Status",
        "scheduled_time": "01:00 PM IST",
        "window_start_minutes": 12 * 60 + 55,  # 12:55 PM
        "window_end_minutes": 13 * 60 + 15,  # 01:15 PM
        "window_label": "12:55 PM – 01:15 PM IST",
    },
    "EOD": {
        "title": "4:00 PM Urgent SLA Escalation • Attention Required",
        "scheduled_time": "04:00 PM IST",
        "window_start_minutes": 15 * 60 + 55,  # 03:55 PM
        "window_end_minutes": 16 * 60 + 15,  # 04:15 PM
        "window_label": "03:55 PM – 04:15 PM IST",
    },
}


def is_stage_within_window(stage: str, ist_now: datetime | None = None) -> tuple[bool, str]:
    """Check whether the requested stage is currently within its scheduled delivery window."""
    now = ist_now or get_current_ist_time()
    s = stage.upper()
    if s not in STAGE_SCHEDULE:
        return False, f"Unknown stage '{stage}'"
    info = STAGE_SCHEDULE[s]
    total_minutes = now.hour * 60 + now.minute
    in_window = info["window_start_minutes"] <= total_minutes <= info["window_end_minutes"]
    if in_window:
        return True, ""
    return False, (
        f"Off-schedule dispatch rejected: {info['title']} is scheduled for {info['scheduled_time']} "
        f"(allowed window: {info['window_label']}). Current time is {now.strftime('%I:%M %p IST')}."
    )


def determine_current_stage(ist_now: datetime | None = None) -> str:
    """
    Determine the appropriate stage based on current IST time:
    - Before 11:30 AM IST -> MORNING (10:00 AM Kickoff)
    - 11:30 AM to 2:30 PM IST -> MIDDAY (1:00 PM Progress Check)
    - 2:30 PM IST onward -> EOD (4:00 PM Urgent Escalation)
    """
    now = ist_now or get_current_ist_time()
    total_minutes = now.hour * 60 + now.minute
    if total_minutes < 11 * 60 + 30:
        return "MORNING"
    elif total_minutes < 14 * 60 + 30:
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
    """Persistent state of the automated daily alert scheduler backed by SQLite/PostgreSQL."""

    def __init__(self) -> None:
        self.enabled: bool = True
        self.last_sent: dict[str, str] = {}  # key: "YYYY-MM-DD_STAGE" -> timestamp
        self.history: list[dict[str, Any]] = []
        self.task: asyncio.Task | None = None
        self._load_from_db()

    def _load_from_db(self) -> None:
        try:
            from db import get_db, init_database

            init_database()
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT slot_key, day_str, stage, dispatched_at, details_json "
                    "FROM alert_scheduler_runs ORDER BY dispatched_at DESC LIMIT 100"
                ).fetchall()
                for r in rows:
                    key = r["slot_key"]
                    self.last_sent[key] = r["dispatched_at"]
                    try:
                        details = json.loads(r["details_json"])
                    except Exception:
                        details = {}
                    self.history.append(
                        {
                            "slot_key": key,
                            "stage": r["stage"],
                            "date": r["day_str"],
                            "dispatched_at": r["dispatched_at"],
                            **details,
                        }
                    )
        except Exception as exc:
            logger.warning("Could not load alert scheduler state from database: %s", exc)

    def mark_sent(self, day_str: str, stage: str, details: dict[str, Any]) -> None:
        key = f"{day_str}_{stage}"
        now_ts = datetime.now(UTC).isoformat()
        self.last_sent[key] = now_ts
        self.history.append(
            {
                "slot_key": key,
                "stage": stage,
                "date": day_str,
                "dispatched_at": now_ts,
                **details,
            }
        )
        if len(self.history) > 100:
            self.history = self.history[-100:]

        try:
            from db import get_db

            with get_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO alert_scheduler_runs "
                    "(slot_key, day_str, stage, dispatched_at, details_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (key, day_str, stage, now_ts, json.dumps(details)),
                )
                conn.commit()
        except Exception as exc:
            logger.warning("Could not persist alert scheduler state to database: %s", exc)

    def is_already_sent_today(self, day_str: str, stage: str) -> bool:
        if f"{day_str}_{stage}" in self.last_sent:
            return True
        try:
            from db import get_db

            with get_db() as conn:
                r = conn.execute(
                    "SELECT 1 FROM alert_scheduler_runs WHERE slot_key = ?",
                    (f"{day_str}_{stage}",),
                ).fetchone()
                if r:
                    self.last_sent[f"{day_str}_{stage}"] = datetime.now(UTC).isoformat()
                    return True
        except Exception:
            pass
        return False


SCHEDULER_STATE = AlertSchedulerState()


def get_due_today_incomplete_tickets(project: str = "ALL") -> list[dict[str, Any]]:
    """Return due-today operator work, excluding client-owned base/content blockers."""
    dash = get_work_management_dashboard(project=project, limit=100)
    return [
        item
        for item in dash.get("work_items", [])
        if item.get("timeline_bucket") == "TODAY"
        and item.get("status_category") != "DONE"
        and not any(status in str(item.get("status") or "").lower() for status in ("base pending", "content pending"))
    ]


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
                Attributics Automated Jira SLA Dispatcher • Sent at {get_current_ist_time().strftime("%I:%M %p IST")}
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
Sent at {get_current_ist_time().strftime("%I:%M %p IST")} by Attributics SLA Dispatcher.
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
    """Inspect environment variables and return active email sender configuration."""
    _load_env_file()
    resend_key = os.getenv("RESEND_API_KEY")
    sendgrid_key = os.getenv("SENDGRID_API_KEY")
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT") or "587")
    smtp_user = os.getenv("SMTP_USER")
    from_email = os.getenv("SMTP_FROM_EMAIL") or smtp_user or "alerts@attributics.com"
    brevo_key = os.getenv("BREVO_API_KEY")
    if brevo_key:
        return {
            "is_configured": True,
            "from_email": from_email,
            "smtp_host": "api.brevo.com (Port 443 HTTPS)",
            "smtp_port": 443,
            "smtp_user": "brevo_api",
            "mode": "LIVE_HTTPS_BREVO",
        }
    elif resend_key:
        return {
            "is_configured": True,
            "from_email": from_email,
            "smtp_host": "api.resend.com (Port 443 HTTPS)",
            "smtp_port": 443,
            "smtp_user": "resend_api",
            "mode": "LIVE_HTTPS_RESEND",
        }
    elif sendgrid_key:
        return {
            "is_configured": True,
            "from_email": from_email,
            "smtp_host": "api.sendgrid.com (Port 443 HTTPS)",
            "smtp_port": 443,
            "smtp_user": "apikey",
            "mode": "LIVE_HTTPS_SENDGRID",
        }

    is_smtp = bool(smtp_host and smtp_user and os.getenv("SMTP_PASSWORD"))
    return {
        "is_configured": is_smtp,
        "from_email": from_email,
        "smtp_host": smtp_host or "Not configured",
        "smtp_port": smtp_port,
        "smtp_user": smtp_user or "Not configured",
        "mode": "LIVE_SMTP" if is_smtp else "SIMULATION",
    }


def preview_due_today_alerts(
    project: str = "ALL",
    stage: str = "AUTO",
) -> dict[str, Any]:
    """
    Generate drafts of all alert emails that would be sent right now.
    """
    ist_now = get_current_ist_time()
    today_str = ist_now.date().isoformat()
    resolved_stage = determine_current_stage(ist_now) if stage == "AUTO" else stage.upper()
    tickets = get_due_today_incomplete_tickets(project=project)
    operators = group_tickets_by_operator(tickets)
    sender_info = get_smtp_sender_info()

    drafts: list[AlertEmailDraft] = [
        build_stage_email(op, resolved_stage, today_str, project=project) for op in operators
    ]

    is_valid_win, win_warn = is_stage_within_window(resolved_stage, ist_now)
    already_sent = SCHEDULER_STATE.is_already_sent_today(today_str, resolved_stage)

    slots_status: dict[str, Any] = {}
    for s_name, s_meta in STAGE_SCHEDULE.items():
        s_valid, _ = is_stage_within_window(s_name, ist_now)
        slots_status[s_name] = {
            "title": s_meta["title"],
            "scheduled_time": s_meta["scheduled_time"],
            "window_label": s_meta["window_label"],
            "already_sent": SCHEDULER_STATE.is_already_sent_today(today_str, s_name),
            "is_current_window": s_valid,
        }

    return {
        "ok": True,
        "project": project,
        "stage": resolved_stage,
        "requested_stage": stage,
        "ist_time": ist_now.strftime("%Y-%m-%d %H:%M:%S IST"),
        "scheduled_time": STAGE_SCHEDULE.get(resolved_stage, {}).get("scheduled_time", "Unknown"),
        "window_label": STAGE_SCHEDULE.get(resolved_stage, {}).get("window_label", ""),
        "is_valid_window": is_valid_win,
        "window_warning": win_warn,
        "already_sent_today": already_sent,
        "slots_status": slots_status,
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
            smtp_host,
            smtp_user,
            draft.recipient_email,
            draft.subject,
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

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(from_email, [draft.recipient_email], msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.ehlo()
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


def send_email_dispatcher(draft: AlertEmailDraft) -> dict[str, Any]:
    """
    Unified outbound email delivery:
    1. Resend API (HTTPS Port 443) if RESEND_API_KEY is configured (bypasses cloud host SMTP port blocking).
    2. SendGrid API (HTTPS Port 443) if SENDGRID_API_KEY is configured.
    3. Standard SMTP transport via send_email_smtp.
    """
    resend_key = os.getenv("RESEND_API_KEY")
    sendgrid_key = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("SMTP_FROM_EMAIL") or os.getenv("SMTP_USER") or "alerts@attributics.com"
    brevo_key = os.getenv("BREVO_API_KEY")
    if brevo_key:
        clean_brevo = brevo_key.strip().strip("'").strip('"')
        masked_key = f"{clean_brevo[:9]}...{clean_brevo[-4:]}" if len(clean_brevo) > 13 else "INVALID_LENGTH"
        try:
            import requests

            sender_name = os.getenv("SMTP_FROM_NAME") or "Naman Dugad"
            payload: dict[str, Any] = {
                "sender": {"name": sender_name, "email": from_email},
                "to": [{"email": draft.recipient_email, "name": draft.recipient_name}],
                "subject": draft.subject,
                "htmlContent": draft.body_html,
                "textContent": draft.body_text,
            }
            if from_email and from_email.lower() != draft.recipient_email.lower():
                payload["bcc"] = [{"email": from_email, "name": sender_name}]

            resp = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={
                    "api-key": clean_brevo,
                    "Content-Type": "application/json",
                    "accept": "application/json",
                },
                json=payload,
                timeout=15,
            )
            if resp.status_code in (200, 201, 202):
                logger.info("Brevo HTTP API sent email to %s: %s", draft.recipient_email, draft.subject)
                return {
                    "delivered": True,
                    "simulated": False,
                    "recipient": draft.recipient_email,
                    "subject": draft.subject,
                    "message": "Email delivered via Brevo HTTP API (Port 443 HTTPS).",
                }
            else:
                err_text = resp.text[:300]
                logger.error("Brevo HTTP API error for %s with key %s: %s", draft.recipient_email, masked_key, err_text)
                return {
                    "delivered": False,
                    "simulated": False,
                    "recipient": draft.recipient_email,
                    "error": f"Brevo API error (Key: {masked_key}): {err_text}",
                    "message": f"Brevo API returned status {resp.status_code}",
                }
        except Exception as exc:
            logger.error("Brevo request failed for %s: %s", draft.recipient_email, exc)
            return {
                "delivered": False,
                "simulated": False,
                "recipient": draft.recipient_email,
                "error": str(exc),
                "message": f"Brevo dispatch error: {exc}",
            }

    if resend_key:
        try:
            import requests

            resp = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {resend_key.strip()}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": from_email,
                    "to": [draft.recipient_email],
                    "subject": draft.subject,
                    "html": draft.body_html,
                    "text": draft.body_text,
                },
                timeout=15,
            )
            if resp.ok:
                logger.info("Resend HTTP API sent email to %s: %s", draft.recipient_email, draft.subject)
                return {
                    "delivered": True,
                    "simulated": False,
                    "recipient": draft.recipient_email,
                    "subject": draft.subject,
                    "message": "Email delivered via Resend HTTP API (Port 443 HTTPS).",
                }
            else:
                err_text = resp.text[:300]
                logger.error("Resend HTTP API error for %s: %s", draft.recipient_email, err_text)
                return {
                    "delivered": False,
                    "simulated": False,
                    "recipient": draft.recipient_email,
                    "error": f"Resend API error: {err_text}",
                    "message": f"Resend API returned status {resp.status_code}",
                }
        except Exception as exc:
            logger.error("Resend request failed for %s: %s", draft.recipient_email, exc)
            return {
                "delivered": False,
                "simulated": False,
                "recipient": draft.recipient_email,
                "error": str(exc),
                "message": f"Resend dispatch error: {exc}",
            }

    if sendgrid_key:
        try:
            import requests

            resp = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {sendgrid_key.strip()}",
                    "Content-Type": "application/json",
                },
                json={
                    "personalizations": [{"to": [{"email": draft.recipient_email}]}],
                    "from": {"email": from_email},
                    "subject": draft.subject,
                    "content": [
                        {"type": "text/plain", "value": draft.body_text},
                        {"type": "text/html", "value": draft.body_html},
                    ],
                },
                timeout=15,
            )
            if resp.status_code in (200, 202):
                logger.info("SendGrid HTTP API sent email to %s: %s", draft.recipient_email, draft.subject)
                return {
                    "delivered": True,
                    "simulated": False,
                    "recipient": draft.recipient_email,
                    "subject": draft.subject,
                    "message": "Email delivered via SendGrid HTTP API (Port 443 HTTPS).",
                }
            else:
                err_text = resp.text[:300]
                return {
                    "delivered": False,
                    "simulated": False,
                    "recipient": draft.recipient_email,
                    "error": f"SendGrid API error: {err_text}",
                    "message": f"SendGrid API returned status {resp.status_code}",
                }
        except Exception as exc:
            return {
                "delivered": False,
                "simulated": False,
                "recipient": draft.recipient_email,
                "error": str(exc),
                "message": f"SendGrid dispatch error: {exc}",
            }

    # Fallback to SMTP
    return send_email_smtp(draft)


def get_brevo_event_logs(limit: int = 15) -> dict[str, Any]:
    """Fetch live transactional delivery events from Brevo API."""
    _load_env_file()
    brevo_key = os.getenv("BREVO_API_KEY")
    if not brevo_key:
        return {"ok": False, "message": "BREVO_API_KEY not configured."}

    clean_key = brevo_key.strip().strip("'").strip('"')
    try:
        import requests

        resp = requests.get(
            f"https://api.brevo.com/v3/smtp/statistics/events?limit={limit}&sort=desc",
            headers={
                "api-key": clean_key,
                "accept": "application/json",
            },
            timeout=10,
        )
        if resp.ok:
            return {"ok": True, "events": resp.json().get("events", [])}
        return {"ok": False, "status": resp.status_code, "error": resp.text}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def classify_ticket_ownership(ticket: dict[str, Any]) -> dict[str, str]:
    """
    Classify whether a ticket's pending action rests with Attributics (internal operator)
    or Tata Capital (client sign-off, test approval, base file, or content).
    """
    status_raw = str(ticket.get("status") or "").strip()
    s = status_raw.lower()

    # 1. Tata Capital Client Dependencies / Actions
    if any(k in s for k in ("test sent", "test_sent")):
        return {
            "ownership": "Tata Capital",
            "pending_with": "Tata Capital",
            "reason": "Test Sent (Awaiting Client Test Approval)",
            "short_reason": "Test Sent • Awaiting Client Approval",
            "badge": "🏢 Test Sent",
            "status_raw": status_raw or "Test Sent",
        }
    if any(k in s for k in ("base pending", "base_pending", "audience", "datamart")):
        return {
            "ownership": "Tata Capital",
            "pending_with": "Tata Capital",
            "reason": "Base Pending (Awaiting Customer Audience File from Tata Capital)",
            "short_reason": "Base Pending • Awaiting Audience File",
            "badge": "📁 Base Pending",
            "status_raw": status_raw or "Base Pending",
        }
    if any(k in s for k in ("content pending", "copy pending", "content_pending", "brief pending")):
        return {
            "ownership": "Tata Capital",
            "pending_with": "Tata Capital",
            "reason": "Content Pending (Awaiting Copy / Brand Content from Tata Capital)",
            "short_reason": "Content Pending • Awaiting Copy",
            "badge": "✍️ Content Pending",
            "status_raw": status_raw or "Content Pending",
        }
    if any(k in s for k in ("asset pending", "creative pending", "creative_pending")):
        return {
            "ownership": "Tata Capital",
            "pending_with": "Tata Capital",
            "reason": "Asset Pending (Awaiting Creatives / Images from Tata Capital)",
            "short_reason": "Creatives Pending",
            "badge": "🎨 Creatives Pending",
            "status_raw": status_raw or "Creatives Pending",
        }
    if any(k in s for k in ("client feedback", "waiting on client", "hold", "client review", "pending client")):
        return {
            "ownership": "Tata Capital",
            "pending_with": "Tata Capital",
            "reason": "Client Review (Waiting on Tata Capital Feedback / Sign-Off)",
            "short_reason": "Client Review • Awaiting Sign-Off",
            "badge": "⏳ Client Review",
            "status_raw": status_raw or "Client Review",
        }
    if any(k in s for k in ("whitelisting", "carrier review", "karix review", "meta review")):
        return {
            "ownership": "Tata Capital",
            "pending_with": "Tata Capital",
            "reason": "Carrier Gateway Review (Awaiting Karix / Meta Whitelisting Approval)",
            "short_reason": "Carrier Review",
            "badge": "📡 Gateway Review",
            "status_raw": status_raw or "Whitelisting",
        }

    # 2. Attributics Operator Actions
    if any(k in s for k in ("test approved", "test_approved")):
        return {
            "ownership": "Attributics",
            "pending_with": "Attributics",
            "reason": "Test Approved • Ready for Campaign Dispatch / Scheduling",
            "short_reason": "Test Approved • Ready to Dispatch",
            "badge": "🚀 Ready for Dispatch",
            "status_raw": status_raw or "Test Approved",
        }
    if any(k in s for k in ("in progress", "in_progress", "drafting")):
        return {
            "ownership": "Attributics",
            "pending_with": "Attributics",
            "reason": "In Progress (Operator Drafting Campaign)",
            "short_reason": "In Progress",
            "badge": "⚙️ In Progress",
            "status_raw": status_raw or "In Progress",
        }
    if any(k in s for k in ("to do", "todo", "open", "backlog", "reopened")):
        return {
            "ownership": "Attributics",
            "pending_with": "Attributics",
            "reason": "To Do (Operator Action Needed)",
            "short_reason": "To Do",
            "badge": "📋 Action Needed",
            "status_raw": status_raw or "To Do",
        }
    if any(k in s for k in ("rework", "review rework", "changes needed")):
        return {
            "ownership": "Attributics",
            "pending_with": "Attributics",
            "reason": "Rework Needed (Operator Changes Required)",
            "short_reason": "Rework Needed",
            "badge": "🔄 Rework Needed",
            "status_raw": status_raw or "Rework Needed",
        }

    return {
        "ownership": "Attributics",
        "pending_with": "Attributics",
        "reason": f"Attributics Ops Queue ({status_raw})",
        "short_reason": status_raw or "Action Needed",
        "badge": f"📌 {status_raw or 'Action Needed'}",
        "status_raw": status_raw or "Action Needed",
    }


def send_google_chat_sla_alert(
    stage: str,
    operators: list[OperatorTicketSummary],
    ist_time_str: str,
    webhook_url: str | None = None,
) -> dict[str, Any]:
    """
    Send an interactive rich card to Google Chat Space via Incoming Webhook.
    Uses standard HTTPS Port 443 (never blocked by cloud firewalls).
    """
    default_url = (
        "https://chat.googleapis.com/v1/spaces/AAQAsqKm6oQ/messages?"
        "key=AIzaSyDdI0hCZtE6vySjMm-WEfRq3CPzqKqqsHI&token=er00Zc1ZFnDfrmthvXlRvtkWQHXDd862nhHl9TlguLk"
    )
    # Never hit the hardcoded live Google Chat space during pytest runs unless webhook_url is explicitly passed
    if os.environ.get("PYTEST_CURRENT_TEST") and webhook_url is None:
        url = ""
    else:
        url = webhook_url if webhook_url is not None else (os.getenv("GOOGLE_CHAT_WEBHOOK_URL") or default_url)
    if not url:
        return {
            "delivered": True,
            "simulated": True,
            "channel": "Google Chat",
            "message": "Google Chat simulated (GOOGLE_CHAT_WEBHOOK_URL not configured).",
        }

    import collections

    known_ids: dict[str, str] = {
        "Dnyanesh Khawas": "118094956873954063156",
        "Dnyanesh": "118094956873954063156",
        "Mrunalini Gawande": "111262272226595238971",
        "Mrunali Gawande": "111262272226595238971",
        "Mrunalini": "111262272226595238971",
        "Mrunali": "111262272226595238971",
        "Neel Shah": "115510908861903356318",
        "Neel": "115510908861903356318",
        "Soham Das": "116501804443197433991",
        "Soham": "116501804443197433991",
        "Aadya": "113432812427365134875",
        "Aalya Mulla": "113432812427365134875",
        "Mudar": "110968683937158757696",
    }

    def _resolve_mention(op_name: str) -> str:
        first_word = op_name.split()[0].title() if op_name else ""
        uid = (
            known_ids.get(op_name)
            or known_ids.get(first_word)
            or os.getenv(f"GCHAT_USER_ID_{first_word.upper()}", "")
        )
        if uid:
            return f"<users/{uid}>"
        return f"*@{op_name}*"

    # Segregate tickets by ownership (Attributics vs Tata Capital)
    attributics_by_op: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    tata_tickets: list[tuple[dict[str, Any], dict[str, str], str]] = []

    for op in operators:
        for t in op.tickets:
            cls = classify_ticket_ownership(t)
            if cls["ownership"] == "Tata Capital":
                tata_tickets.append((t, cls, op.operator_name))
            else:
                attributics_by_op[op.operator_name].append(t)

    total_attributics = sum(len(tkts) for tkts in attributics_by_op.values())
    total_tata = len(tata_tickets)
    total_tickets = total_attributics + total_tata

    stage_meta = {
        "MORNING": {
            "title": "🌞 10:00 AM SLA Kickoff • Daily Workload",
            "color": "#4f46e5",
            "desc": f"Good morning team! We have {total_tickets} campaigns scheduled for delivery today.",
        },
        "MIDDAY": {
            "title": "🥪 1:00 PM SLA Checkpoint • Midday Status",
            "color": "#d97706",
            "desc": f"Midday status check: {total_tickets} campaigns remain pending for today.",
        },
        "EOD": {
            "title": "🚨 4:00 PM Urgent SLA Escalation • Attention Required",
            "color": "#dc2626",
            "desc": f"CRITICAL: {total_tickets} campaigns due today remain incomplete and require immediate attention.",
        },
    }.get(
        stage, {"title": f"🚨 SLA Alert • {stage}", "color": "#dc2626", "desc": f"{total_tickets} campaigns due today."}
    )

    # 1. Build Attributics Section
    attributics_lines = []
    mentions_list = []
    for op in operators:
        op_tkts = attributics_by_op.get(op.operator_name, [])
        if not op_tkts:
            continue
        mention_tag = _resolve_mention(op.operator_name)
        mentions_list.append(mention_tag)
        tkt_strs = []
        for t in op_tkts:
            c = classify_ticket_ownership(t)
            st = c["short_reason"]
            tkt_strs.append(f"`{t.get('key')}` [{st}]")
        attributics_lines.append(f"• {mention_tag} ({len(op_tkts)} action required): {', '.join(tkt_strs)}")

    attributics_text = "\n".join(attributics_lines) if attributics_lines else "• All internal operator action items are up to date! 🎉"

    # 2. Build Tata Capital Section
    tata_lines = []
    for t, cls, op_name in tata_tickets:
        k = t.get("key", "")
        reason = cls["short_reason"]
        tata_lines.append(f"• `{k}` [{cls['badge']} • {reason}] (Owner: {op_name})")

    tata_text = "\n".join(tata_lines) if tata_lines else "• No client-blocked campaigns."

    # Mentions header: ping operators who have Attributics action items;
    # if none, ping operators tracking Tata Capital items so space is informed.
    if not mentions_list and tata_tickets:
        for _, _, op_name in tata_tickets:
            m = _resolve_mention(op_name)
            if m not in mentions_list:
                mentions_list.append(m)

    mentions_header = f"<users/all> 🔔 Attn: {' '.join(mentions_list)}\n\n" if mentions_list else ""
    summary_breakdown = (
        f"📊 *Ownership Breakdown:* {total_attributics} Pending with Attributics (Action Needed) "
        f"• {total_tata} Pending with Tata Capital (Client Review / Dependencies)"
    )

    body_text = (
        f"{mentions_header}*{stage_meta['title']}*\n"
        f"{stage_meta['desc']}\n"
        f"{summary_breakdown}\n\n"
        f"🟡 *Pending with Attributics (Action Items: {total_attributics}):*\n"
        f"{attributics_text}\n\n"
        f"🏢 *Pending with Tata Capital (Client Dependencies: {total_tata}):*\n"
        f"{tata_text}"
    )

    card_sections = [
        {
            "header": f"🟡 Pending with Attributics (Action Required: {total_attributics})",
            "widgets": [{"textParagraph": {"text": attributics_text}}],
        },
        {
            "header": f"🏢 Pending with Tata Capital (Client Dependencies: {total_tata})",
            "widgets": [{"textParagraph": {"text": tata_text}}],
        },
    ]

    card_payload = {
        "text": body_text,
        "cardsV2": [
            {
                "cardId": f"slaAlert_{stage}",
                "card": {
                    "header": {
                        "title": stage_meta["title"],
                        "subtitle": f"{total_tickets} Due Today • {total_attributics} with Attributics • {total_tata} with Tata Capital • {ist_time_str}",
                    },
                    "sections": card_sections,
                },
            }
        ],
    }

    try:
        import requests

        resp = requests.post(url, json=card_payload, timeout=15)
        if resp.ok:
            logger.info("Successfully sent Google Chat SLA alert card for %s", stage)
            return {
                "delivered": True,
                "simulated": False,
                "channel": "Google Chat",
                "message": "Card successfully posted to Google Chat Space.",
            }
        logger.error("Google Chat webhook error: HTTP %s: %s", resp.status_code, resp.text)
        return {
            "delivered": False,
            "simulated": False,
            "channel": "Google Chat",
            "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
        }
    except Exception as exc:
        logger.error("Failed to post Google Chat SLA alert: %s", exc)
        return {
            "delivered": False,
            "simulated": False,
            "channel": "Google Chat",
            "error": str(exc),
        }


def dispatch_due_today_alerts(
    project: str = "ALL",
    stage: str = "AUTO",
    dry_run: bool = False,
    operator_name: str = "Automated Dispatcher",
    send_google_chat: bool = True,
    send_email: bool = True,
    google_chat_webhook_url: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Dispatch SLA alerts strictly via Google Chat Space and/or Direct Email.
    Enforces strict time-window boundaries unless force=True or dry_run=True.
    Jira remains strictly READ-ONLY (no comments or writes to Jira).
    """
    ist_now = get_current_ist_time()
    today_str = ist_now.date().isoformat()
    preview = preview_due_today_alerts(project=project, stage=stage)
    resolved_stage = preview["stage"]
    draft_dicts = preview["drafts"]
    tickets = get_due_today_incomplete_tickets(project=project)
    operators = group_tickets_by_operator(tickets)

    # 1. Enforce strict time window validation for real sends
    if not dry_run and not force:
        is_valid_win, win_warn = is_stage_within_window(resolved_stage, ist_now)
        if not is_valid_win:
            logger.warning("Rejected off-schedule SLA alert dispatch: %s", win_warn)
            return {
                "ok": False,
                "error": win_warn,
                "rejected_off_schedule": True,
                "stage": resolved_stage,
                "current_time_ist": ist_now.strftime("%I:%M %p IST"),
            }

        # 2. Prevent duplicate sends on the same day for this stage
        if SCHEDULER_STATE.is_already_sent_today(today_str, resolved_stage):
            logger.warning(
                "SLA alert for stage '%s' has already been dispatched today (%s). Skipping to prevent duplicates.",
                resolved_stage,
                today_str,
            )
            return {
                "ok": False,
                "error": f"SLA alert for stage '{resolved_stage}' has already been dispatched today ({today_str}). Pass force=True to re-dispatch.",
                "already_dispatched_today": True,
                "stage": resolved_stage,
                "dispatched_by": operator_name,
            }

    # 1. Google Chat Space Broadcast (strictly simulated when dry_run=True)
    google_chat_res: dict[str, Any] = {}
    if dry_run and send_google_chat:
        google_chat_res = {
            "delivered": True,
            "simulated": True,
            "channel": "Google Chat",
            "message": "Dry run preview mode — no real Google Chat webhook dispatched.",
        }
    elif send_google_chat and operators:
        google_chat_res = send_google_chat_sla_alert(
            resolved_stage, operators, preview["ist_time"], webhook_url=google_chat_webhook_url
        )
    elif send_google_chat:
        google_chat_res = {
            "delivered": False,
            "skipped": True,
            "channel": "Google Chat",
            "message": "No operator-owned pending campaigns due today.",
        }

    # 2. Direct Email Dispatch
    results: list[dict[str, Any]] = []
    delivered_count = 0
    failed_count = 0

    if send_email:
        for d_dict in draft_dicts:
            draft = AlertEmailDraft(**d_dict)
            if dry_run:
                results.append(
                    {
                        "delivered": True,
                        "simulated": True,
                        "recipient": draft.recipient_email,
                        "subject": draft.subject,
                        "message": "Dry run preview mode — no real network packets dispatched.",
                    }
                )
                delivered_count += 1
            else:
                send_res = send_email_dispatcher(draft)
                if send_res.get("delivered"):
                    delivered_count += 1
                else:
                    failed_count += 1
                results.append(send_res)

    sender_info = preview["sender_info"]
    real_sent_count = sum(1 for r in results if r.get("delivered") and not r.get("simulated"))
    simulated_count = sum(1 for r in results if r.get("simulated"))

    # Mark sent in scheduler state
    if not dry_run:
        SCHEDULER_STATE.mark_sent(
            day_str=today_str,
            stage=resolved_stage,
            details={
                "delivered_count": delivered_count,
                "real_sent_count": real_sent_count,
                "simulated_count": simulated_count,
                "failed_count": failed_count,
                "google_chat_delivered": google_chat_res.get("delivered", False),
                "recipients": [d["recipient_email"] for d in draft_dicts],
                "operator_name": operator_name,
                "dry_run": dry_run,
            },
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
        "google_chat_result": google_chat_res,
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
                        SCHEDULER_STATE.mark_sent(today_str, "MORNING", {"status": "claimed_by_scheduler"})
                        logger.info("Triggering automated 10:00 AM IST Kickoff SLA reminder...")
                        await asyncio.to_thread(
                            dispatch_due_today_alerts,
                            project="ALL",
                            stage="MORNING",
                            operator_name="Daily 10:00 AM Scheduler",
                            force=True,
                        )

                # Check 1:00 PM slot (13:00 to 13:05 window)
                elif hour == 13 and 0 <= minute <= 5:
                    if not SCHEDULER_STATE.is_already_sent_today(today_str, "MIDDAY"):
                        SCHEDULER_STATE.mark_sent(today_str, "MIDDAY", {"status": "claimed_by_scheduler"})
                        logger.info("Triggering automated 1:00 PM IST Midday Checkpoint SLA reminder...")
                        await asyncio.to_thread(
                            dispatch_due_today_alerts,
                            project="ALL",
                            stage="MIDDAY",
                            operator_name="Daily 1:00 PM Scheduler",
                            force=True,
                        )

                # Check 4:00 PM slot (16:00 to 16:05 window)
                elif hour == 16 and 0 <= minute <= 5:
                    if not SCHEDULER_STATE.is_already_sent_today(today_str, "EOD"):
                        SCHEDULER_STATE.mark_sent(today_str, "EOD", {"status": "claimed_by_scheduler"})
                        logger.info("Triggering automated 4:00 PM IST EOD Escalation SLA reminder...")
                        await asyncio.to_thread(
                            dispatch_due_today_alerts,
                            project="ALL",
                            stage="EOD",
                            operator_name="Daily 4:00 PM Scheduler",
                            force=True,
                        )
        except Exception as exc:
            logger.error("Error in alert scheduler loop: %s", exc)

        await asyncio.sleep(30)
