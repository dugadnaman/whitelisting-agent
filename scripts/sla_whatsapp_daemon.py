#!/usr/bin/env python3
"""
Dedicated Local SLA WhatsApp Automation Daemon for Tata Capital / Internal_TCL<>Att.

Runs continuously in the background on your Mac.
Dispatches progressive SLA alerts strictly at:
- 10:00 AM IST (Morning Kickoff)
- 01:00 PM IST (Midday Checkpoint)
- 04:00 PM IST (EOD Escalation)

Directly connects to local WhatsApp Gateway (http://localhost:5005).
Zero external cloud sleep issues, zero Render free-tier timeouts.
Ensures alerts are delivered 100% autonomously every single day.
"""

import os
import sys
import time
import json
import logging
from pathlib import Path
from datetime import datetime, UTC, timedelta

# Ensure backend modules are on PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from config import _load_env_file
_load_env_file()

from email_notifier import (
    get_current_ist_time,
    preview_due_today_alerts,
    format_whatsapp_sla_message,
)
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(PROJECT_ROOT / "sla_daemon.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("SLA_Daemon")

STATE_FILE = PROJECT_ROOT / "data" / "sla_daemon_state.json"
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

GATEWAY_URL = os.getenv("WHATSAPP_GATEWAY_URL", "http://localhost:5005")
GROUP_NAME = os.getenv("WHATSAPP_SLA_GROUP_NAME", "Internal_TCL<>Att")
GROUP_ID = os.getenv("WHATSAPP_SLA_GROUP_ID", "120363413267146720@g.us")


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to write state file: %s", exc)


def is_already_sent(today_str: str, stage: str) -> bool:
    state = load_state()
    sent_key = f"{today_str}_{stage}"
    return bool(state.get(sent_key))


def mark_sent(today_str: str, stage: str, details: dict) -> None:
    state = load_state()
    sent_key = f"{today_str}_{stage}"
    state[sent_key] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "ist_time": get_current_ist_time().strftime("%Y-%m-%d %I:%M %p IST"),
        "details": details,
    }
    save_state(state)


def dispatch_slot(stage: str, today_str: str) -> bool:
    logger.info("Preparing SLA %s alert for %s...", stage, today_str)
    try:
        preview = preview_due_today_alerts(project="ALL", stage=stage)
        msg = preview.get("whatsapp_message") or ""
        if not msg:
            logger.error("Failed to format WhatsApp message for %s", stage)
            return False

        payload = {
            "group": GROUP_NAME,
            "group_id": GROUP_ID,
            "message": msg,
        }
        endpoint = f"{GATEWAY_URL.rstrip('/')}/send-message"
        resp = requests.post(endpoint, json=payload, timeout=20)
        if resp.ok:
            data = resp.json()
            logger.info("✅ SUCCESS: Dispatched %s SLA alert to WhatsApp group '%s'! Message ID: %s", stage, GROUP_NAME, data.get("message_id"))
            mark_sent(today_str, stage, {"status": "delivered", "message_id": data.get("message_id")})
            return True
        else:
            logger.error("❌ Gateway returned error: HTTP %s: %s", resp.status_code, resp.text)
            return False
    except Exception as exc:
        logger.error("❌ Exception during SLA dispatch for %s: %s", stage, exc)
        return False


def run_daemon() -> None:
    logger.info("==================================================================")
    logger.info("🚀 Starting Local SLA WhatsApp Automation Daemon")
    logger.info("Group: %s (%s)", GROUP_NAME, GROUP_ID)
    logger.info("Gateway: %s", GATEWAY_URL)
    logger.info("Scheduled slots (IST): 10:00 AM (Kickoff), 01:00 PM (Midday), 04:00 PM (EOD)")
    logger.info("==================================================================")

    while True:
        try:
            now_ist = get_current_ist_time()
            today_str = now_ist.date().isoformat()
            hour = now_ist.hour
            minute = now_ist.minute

            # Slot 1: 10:00 AM IST (Window: 10:00 to 10:30)
            if hour == 10 and 0 <= minute <= 30:
                if not is_already_sent(today_str, "MORNING"):
                    dispatch_slot("MORNING", today_str)

            # Slot 2: 01:00 PM IST (Window: 13:00 to 13:30)
            elif hour == 13 and 0 <= minute <= 30:
                if not is_already_sent(today_str, "MIDDAY"):
                    dispatch_slot("MIDDAY", today_str)

            # Slot 3: 04:00 PM IST (Window: 16:00 to 16:30)
            elif hour == 16 and 0 <= minute <= 30:
                if not is_already_sent(today_str, "EOD"):
                    dispatch_slot("EOD", today_str)

        except Exception as exc:
            logger.error("Unexpected error in daemon loop: %s", exc)

        time.sleep(20)


if __name__ == "__main__":
    run_daemon()
