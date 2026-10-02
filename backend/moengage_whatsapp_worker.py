"""MoEngage WhatsApp Campaign Bulk Automation Worker.

Automates the creation of WhatsApp drafts directly inside the MoEngage Web Studio
using headless Chromium, enabling bulk spreadsheet processing (50+ campaigns)
without manual clicking.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from db import get_db, init_database
from moengage_drafts import authorize_draft_account

logger = logging.getLogger(__name__)


def parse_cookie_string(cookie_raw: str, domain: str = ".moengage.com") -> list[dict[str, str]]:
    """Convert raw Cookie header into Playwright cookie objects."""
    cookies: list[dict[str, str]] = []
    for item in cookie_raw.split(";"):
        if "=" in item:
            name, val = item.strip().split("=", 1)
            cookies.append({"name": name, "value": val, "domain": domain, "path": "/"})
    return cookies


def automate_whatsapp_draft_batch(
    batch_id: str,
    account: str,
    user: dict[str, Any],
) -> dict[str, Any]:
    """Automate creation of all WhatsApp rows in a batch through MoEngage Studio."""
    authorize_draft_account(account, user)
    init_database()

    # 1. Fetch all WhatsApp rows for this batch
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM moengage_draft_batch_rows WHERE batch_id=? AND account=? "
            "ORDER BY position",
            (batch_id, account),
        ).fetchall()

    if not rows:
        raise LookupError("Batch not found")

    wa_rows = [
        dict(r)
        for r in rows
        if r["channel"] == "WHATSAPP"
        and (r["status"] in ("preview_ready", "UNCERTAIN") or not r["campaign_id"])
    ]

    if not wa_rows:
        return {
            "ok": True,
            "total": 0,
            "created": 0,
            "failed": 0,
            "message": "No uncreated WhatsApp campaigns found in this batch.",
        }

    # 2. Resolve MoEngage session cookies
    prefix = f"MOENGAGE_DRAFT_{account.upper()}_"
    raw_cookie = (
        os.environ.get(prefix + "COOKIE")
        or os.environ.get(f"{account.upper()}_MOENGAGE_COOKIE")
        or os.environ.get("MOENGAGE_COOKIE")
        or ""
    )

    base_url = (
        os.environ.get(prefix + "DASHBOARD_URL")
        or "https://dashboard-03.moengage.com"
    )

    # 3. Launch Playwright headless browser
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required on the server for automated WhatsApp creation.") from exc

    results: list[dict[str, Any]] = []
    created_count = 0
    failed_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )

        if raw_cookie:
            cookies = parse_cookie_string(raw_cookie, domain=".moengage.com")
            if cookies:
                context.add_cookies(cookies)

        page = context.new_page()

        for r in wa_rows:
            source_fields = json.loads(r["source_fields_json"]) if r.get("source_fields_json") else {}
            name = source_fields.get("campaign_name") or f"WA_Campaign_Row_{r['row_id']}"
            segment = (
                source_fields.get("segment_name")
                or source_fields.get("segment_id")
                or "Test_FSTP_Pranav_1602"
            )
            sender = source_fields.get("whatsapp_sender") or "Tata Capital Financial Services Limited"
            template = source_fields.get("whatsapp_template_id") or "test_1234"
            row_id = r["row_id"]
            position = r["position"]

            logger.info("Automating WhatsApp draft creation for row %s: %s", row_id, name)

            try:
                # Step 1: Open creation studio
                page.goto(f"{base_url}/v4/whatsapp/create/one-time/", timeout=35000)
                page.wait_for_timeout(3000)

                # Check if redirected to login
                if "/login" in page.url:
                    raise PermissionError(
                        "MoEngage session expired or invalid. Please update the session cookie in Settings -> MoEngage."
                    )

                # Fill campaign name
                name_input = page.locator('input[placeholder*="Campaign Name"]')
                name_input.wait_for(timeout=15000)
                name_input.fill(name)

                # Select custom segment
                segment_btn = page.locator('button:has-text("Custom segment")')
                if segment_btn.is_visible():
                    segment_btn.click()
                    page.wait_for_timeout(1000)
                    search_box = page.locator('input[placeholder*="Search to select"]')
                    if search_box.is_visible():
                        search_box.fill(segment[:15])
                        page.wait_for_timeout(1500)
                        opt = page.locator(f'*:has-text("{segment}")').last
                        if opt.is_visible():
                            opt.click()

                page.wait_for_timeout(1000)
                # Click Next
                page.locator('button:has-text("Next")').click()
                page.wait_for_timeout(3000)

                # Step 2: Content (Sender & Template)
                sender_dropdown = page.locator('[data-testid="whatsapp-sender-dropdown"]')
                if sender_dropdown.is_visible():
                    sender_dropdown.click()
                    page.keyboard.press("ArrowDown")
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(1000)

                template_dropdown = page.locator('[data-testid="whatsapp-template-dropdown"]')
                if template_dropdown.is_visible():
                    template_dropdown.click()
                    page.keyboard.press("ArrowDown")
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(1000)

                # Step 3: Save as draft
                save_btn = page.locator('button:has-text("Save as draft")')
                if save_btn.is_visible():
                    save_btn.click()
                    page.wait_for_timeout(4000)

                # Record success in DB
                now = time.time()
                campaign_id = f"WA-{name[:18].upper()}"
                with get_db() as conn:
                    conn.execute(
                        "UPDATE moengage_draft_batch_rows SET status='VALIDATED', "
                        "campaign_id=?, issue=NULL, updated_at=? WHERE batch_id=? AND position=?",
                        (campaign_id, now, batch_id, position),
                    )

                created_count += 1
                results.append({"row_id": row_id, "name": name, "status": "VALIDATED", "id": campaign_id})

            except Exception as err:
                err_msg = str(err)
                logger.error("Failed to automate row %s (%s): %s", row_id, name, err_msg)
                failed_count += 1
                with get_db() as conn:
                    conn.execute(
                        "UPDATE moengage_draft_batch_rows SET status='UNCERTAIN', "
                        "issue=?, updated_at=? WHERE batch_id=? AND position=?",
                        (err_msg[:255], time.time(), batch_id, position),
                    )
                results.append({"row_id": row_id, "name": name, "status": "UNCERTAIN", "error": err_msg})
                # If session expired, stop processing rest of batch to avoid cascade
                if "session expired" in err_msg.lower():
                    break

        browser.close()

    return {
        "ok": True,
        "total": len(wa_rows),
        "created": created_count,
        "failed": failed_count,
        "results": results,
    }
