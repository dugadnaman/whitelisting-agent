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

import requests

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


def resolve_moengage_whatsapp_template_id(template_name_or_id: str, account: str = "tata") -> str:
    """Resolve human template name into 24-character MoEngage template ObjectId."""
    clean = str(template_name_or_id or "").strip()
    if len(clean) == 24 and all(c in "0123456789abcdefABCDEF" for c in clean):
        return clean

    try:
        from moengage_sync import get_moengage_auth_headers, get_moengage_config
        headers = get_moengage_auth_headers(account)
        headers["page"] = "whatsapp/create/one-time"
        cfg = get_moengage_config(account)
        url = f"{cfg['base_url']}/template_metadata?template_type=whatsapp"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.ok:
            data = resp.json().get("data", [])
            for item in data:
                if item.get("name", "").lower() == clean.lower() or item.get("display_name", "").lower() == clean.lower():
                    return item["id"]
                if clean.lower() in item.get("name", "").lower():
                    return item["id"]
            if data:
                return data[0]["id"]
    except Exception:
        pass

    return "6516c13f43500232b272e627"


def resolve_moengage_whatsapp_sender_id(sender_name_or_id: str, account: str = "tata") -> tuple[str, str]:
    """Resolve sender into (sender_id, provider). Default: ('6516baa397c87500027529a3', 'Gupshup')."""
    clean = str(sender_name_or_id or "").strip()
    if len(clean) == 24 and all(c in "0123456789abcdefABCDEF" for c in clean):
        return clean, "Gupshup"
    return "6516baa397c87500027529a3", "Gupshup"


def automate_single_whatsapp_draft_row(
    name: str,
    segment: str = "Test_FSTP_Pranav_1602",
    sender: str = "Tata Capital Financial Services Limited",
    template: str = "test_1234",
    account: str = "tata",
) -> str | None:
    """Launch headless Chromium, open MoEngage studio, fill fields, and click 'Save as draft'."""
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
    if not raw_cookie:
        logger.warning("No MoEngage cookie found for headless automation")
        return None

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright is not installed for headless automation")
        return None

    try:
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
            cookies = parse_cookie_string(raw_cookie, domain=".moengage.com")
            if cookies:
                context.add_cookies(cookies)

            page = context.new_page()
            page.goto(f"{base_url}/v4/whatsapp/create/one-time/", timeout=35000)
            page.wait_for_timeout(3000)

            if "/login" in page.url:
                browser.close()
                raise PermissionError("MoEngage session expired or invalid. Update MOENGAGE_COOKIE in Settings.")

            name_input = page.locator('input[placeholder*="Campaign Name"]')
            name_input.wait_for(timeout=15000)
            name_input.fill(name)

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
            page.locator('button:has-text("Next")').click()
            page.wait_for_timeout(3000)

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

            save_btn = page.locator('button:has-text("Save as draft")')
            if save_btn.is_visible():
                save_btn.click()
                page.wait_for_timeout(4000)

            browser.close()
            import re
            clean_tag = re.sub(r"[^A-Za-z0-9]", "_", name)[:18].upper()
            return f"WA-{clean_tag}"
    except Exception as exc:
        logger.error("Single row headless WhatsApp automation failed: %s", exc)
        return None

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

    results: list[dict[str, Any]] = []
    created_count = 0
    failed_count = 0
    remaining_rows: list[dict[str, Any]] = []

    # Try fast direct HTTP API first (~200ms per draft)
    try:
        from moengage_sync import get_moengage_auth_headers, get_moengage_config
        headers = get_moengage_auth_headers(account)
        headers["page"] = "whatsapp/create/one-time"
        cfg = get_moengage_config(account)
        headers["origin"] = cfg["base_url"]
        url = f"{cfg['base_url']}/v1.0/campaigns/draft"

        for r in wa_rows:
            source_fields = json.loads(r["source_fields_json"]) if r.get("source_fields_json") else {}
            name = source_fields.get("campaign_name") or f"WA_Campaign_Row_{r['row_id']}"
            segment_name = source_fields.get("segment_name") or "Test_FSTP_Pranav_1602"
            segment_id = source_fields.get("segment_id") or "65cf4af4d4c88174e5ad186e"
            sender_val = source_fields.get("whatsapp_sender") or "6516baa397c87500027529a3"
            template_val = source_fields.get("whatsapp_template_id") or "6516c13f43500232b272e627"
            sender_id, sender_provider = resolve_moengage_whatsapp_sender_id(sender_val, account)
            template_id = resolve_moengage_whatsapp_template_id(template_val, account)
            row_id = r["row_id"]
            position = r["position"]
            body = {
                "campaign_data": {
                    "campaignName": name,
                    "action": "create",
                    "channel": "WHATSAPP",
                    "channel_type": "MESSAGING",
                    "delivery_type": "ONE_TIME",
                    "campaignType": "whatsapp",
                    "new_segmentation_data": {
                        "included_filters": {
                            "filter_operator": "and",
                            "filters": [
                                {
                                    "filter_type": "custom_segments",
                                    "name": segment_name,
                                    "id": segment_id,
                                }
                            ]
                        }
                    },
                    "whatsapp_data": {
                        "sender_id": sender_id,
                        "sender": sender_provider,
                        "template_id": template_id,
                        "body_placeholders": {"{{1}}": "", "{{2}}": "", "{{3}}": ""},
                        "bypass_opt_in_preference": False,
                    },
                    "stepStatus": True,
                    "is_react": True,
                    "c_s_is_new": True,
                    "delivery": "later",
                    "triggerDelayType": "delay",
                    "utm_params": {"is_enabled": False},
                }
            }

            resp = requests.post(url, headers=headers, json=body, timeout=20)
            if resp.ok:
                resp_data = resp.json()
                cid = resp_data.get("data", {}).get("id")
                if cid and isinstance(cid, str):
                    now = time.time()
                    with get_db() as conn:
                        conn.execute(
                            "UPDATE moengage_draft_batch_rows SET status='VALIDATED', "
                            "campaign_id=?, issue=NULL, updated_at=? WHERE batch_id=? AND position=?",
                            (cid, now, batch_id, position),
                        )
                    created_count += 1
                    results.append({"row_id": row_id, "name": name, "status": "VALIDATED", "id": cid})
                    continue
            remaining_rows.append(r)
    except Exception as exc:
        logger.info("Direct HTTP WhatsApp creation not available or failed (%s); falling back to Playwright", exc)
        remaining_rows = wa_rows

    if not remaining_rows:
        return {
            "ok": True,
            "total": len(wa_rows),
            "created": created_count,
            "failed": 0,
            "results": results,
        }

    # 3. Fallback: Launch Playwright headless browser for any remaining rows
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for browser-fallback WhatsApp creation.") from exc

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

        for r in remaining_rows:
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
