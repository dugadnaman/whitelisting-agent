"""
Activity tracker: logs user actions (template submissions, credential updates,
status polls, etc.) to a JSONL file for audit / visibility.

Every action records: who did it, what they did, which account/channel,
when, and a details dict with action-specific metadata.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

ACTIVITY_LOG_PATH = "activity_log.jsonl"


def log_activity(
    user: str,
    action: str,
    account: str,
    channel: str,
    details: dict | None = None,
    status: str = "success",
    ip_address: str | None = None,
    log_path: str = ACTIVITY_LOG_PATH,
) -> dict:
    """
    Append one activity record as a JSON line.
    Returns the record dict that was written.
    """
    record = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user": user or "Anonymous Operator",
        "action": action,
        "account": account,
        "channel": channel,
        "status": status,
        "details": details or {},
    }
    if ip_address:
        record["ip_address"] = ip_address

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")

    return record


def load_activities(
    user: str | None = None,
    action: str | None = None,
    account: str | None = None,
    channel: str | None = None,
    search: str | None = None,
    limit: int = 200,
    log_path: str = ACTIVITY_LOG_PATH,
) -> list[dict]:
    """
    Read back activity records, optionally filtered.
    Returns newest-first, capped at `limit`.
    """
    path = Path(log_path)
    if not path.exists():
        return []

    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # Apply filters
    if user:
        records = [r for r in records if r.get("user", "").lower() == user.lower()]
    if action:
        records = [r for r in records if r.get("action") == action]
    if account:
        records = [r for r in records if r.get("account", "").lower() == account.lower()]
    if channel:
        records = [r for r in records if r.get("channel", "").lower() == channel.lower()]
    if search:
        q = search.lower()
        records = [
            r for r in records
            if q in r.get("user", "").lower()
            or q in r.get("action", "").lower()
            or q in json.dumps(r.get("details", {})).lower()
        ]

    # Sort newest first
    records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)

    return records[:limit]


def get_activity_summary(log_path: str = ACTIVITY_LOG_PATH) -> dict:
    """
    Compute summary stats across all activity records.
    Returns a dict matching the ActivityStats type expected by the frontend.
    """
    all_records = load_activities(limit=100_000, log_path=log_path)

    users: dict[str, dict] = {}
    action_breakdown: dict[str, int] = {}
    total_templates = 0

    for r in all_records:
        u = r.get("user", "Anonymous Operator")
        act = r.get("action", "UNKNOWN")

        if u not in users:
            users[u] = {"actions": 0, "templates": 0}
        users[u]["actions"] += 1

        action_breakdown[act] = action_breakdown.get(act, 0) + 1

        if act == "TEMPLATE_SUBMISSION":
            count = r.get("details", {}).get("count", 0) or 0
            users[u]["templates"] += count
            total_templates += count

    # Build user_activity list sorted by most actions
    user_activity = sorted(
        [
            {"user": u, "actions": data["actions"], "templates": data["templates"]}
            for u, data in users.items()
        ],
        key=lambda x: x["actions"],
        reverse=True,
    )

    top_user = user_activity[0]["user"] if user_activity else "—"

    return {
        "total_actions": len(all_records),
        "total_users": len(users),
        "total_templates_submitted": total_templates,
        "top_user": top_user,
        "user_activity": user_activity,
        "action_breakdown": action_breakdown,
        "recent_activities": all_records[:10],
    }
