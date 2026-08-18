"""
Activity tracker: logs user actions (template submissions, credential updates,
status polls, etc.) to a JSONL file for audit / visibility.

Every action records: who did it, what they did, which account/channel,
when, and a details dict with action-specific metadata.
"""

import json
import os
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


def _iter_lines_reversed(log_path: str):
    """Yield lines newest-first by scanning the file backwards in chunks."""
    with open(log_path, "rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        chunk = b""
        while pos > 0:
            step = min(pos, 65536)
            pos -= step
            f.seek(pos)
            block = f.read(step)
            chunk = block + chunk
            # Emit complete lines; keep the partial head for the next chunk
            parts = chunk.split(b"\n")
            chunk = parts[0]
            for raw in reversed(parts[1:]):
                yield raw.decode("utf-8", errors="replace")
        if chunk:
            yield chunk.decode("utf-8", errors="replace")


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

    Streams the log backwards and stops reading the moment `limit` matching
    records are collected — O(needed) disk reads instead of parsing the whole
    file per request.
    """
    path = Path(log_path)
    if not path.exists():
        return []

    def matches(rec: dict) -> bool:
        if user and rec.get("user", "").lower() != user.lower():
            return False
        if action and rec.get("action", "").lower() != action.lower():
            return False
        if account and rec.get("account", "").lower() != account.lower():
            return False
        if channel and rec.get("channel", "").lower() != channel.lower():
            return False
        if search:
            q = search.lower()
            if (
                q not in rec.get("user", "").lower()
                and q not in rec.get("action", "").lower()
                and q not in json.dumps(rec.get("details", {})).lower()
            ):
                return False
        return True

    records = []
    for line in _iter_lines_reversed(str(path)):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if matches(rec):
            records.append(rec)
            if len(records) >= limit:
                break

    return records


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
