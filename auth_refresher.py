"""
Self-Healing Auth: Playwright Browser Automation for Karix Portal.
Automatically logs into Karix, intercepts network requests/storage to harvest
fresh Bearer, Session, and User tokens, updates credentials.json, and allows
submissions to resume without human intervention.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from activity_tracker import log_activity
from config import _account_prefix, _load_env_file

logger = logging.getLogger(__name__)

KARIX_PORTAL_LOGIN_URLS = [
    "https://rcmui.instaalerts.zone",
    "https://rcsgui.karix.solutions",
    "https://karix.solutions/lounge/LoungePage/login.php",
]


def update_persisted_credentials(
    account: str,
    tokens: dict[str, str],
    channel: str = "whatsapp",
) -> None:
    """Save newly harvested tokens into credentials.json, os.environ, and .env."""
    acc = account.lower().strip()
    prefix = _account_prefix(acc)
    is_tata = acc == "tata"
    is_bajaj = acc == "bajaj"

    mapping: dict[str, str] = {}

    if "bearer_token" in tokens and tokens["bearer_token"]:
        key = "TATA_KARIX_BEARER_TOKEN" if is_tata else ("BAJAJ_KARIX_BEARER_TOKEN" if is_bajaj else f"{prefix}_KARIX_BEARER_TOKEN")
        mapping[key] = tokens["bearer_token"].strip()
        os.environ[key] = tokens["bearer_token"].strip()
        if is_bajaj:
            os.environ["KARIX_BEARER_TOKEN"] = tokens["bearer_token"].strip()

    if "session" in tokens and tokens["session"]:
        key = "TATA_KARIX_SESSION" if is_tata else ("BAJAJ_KARIX_SESSION" if is_bajaj else f"{prefix}_KARIX_SESSION")
        mapping[key] = tokens["session"].strip()
        os.environ[key] = tokens["session"].strip()
        if is_bajaj:
            os.environ["KARIX_SESSION"] = tokens["session"].strip()

    if "user" in tokens and tokens["user"]:
        key = "TATA_KARIX_USER" if is_tata else ("BAJAJ_KARIX_USER" if is_bajaj else f"{prefix}_KARIX_USER")
        mapping[key] = tokens["user"].strip()
        os.environ[key] = tokens["user"].strip()
        if is_bajaj:
            os.environ["KARIX_USER"] = tokens["user"].strip()

    if "lounge_cookie" in tokens and tokens["lounge_cookie"]:
        key = "TATA_KARIX_LOUNGE_COOKIE" if is_tata else ("BAJAJ_KARIX_LOUNGE_COOKIE" if is_bajaj else f"{prefix}_KARIX_LOUNGE_COOKIE")
        mapping[key] = tokens["lounge_cookie"].strip()
        os.environ[key] = tokens["lounge_cookie"].strip()

    if not mapping:
        return

    # 1. Update credentials.json
    try:
        cred_path = Path("credentials.json")
        saved: dict[str, Any] = {}
        if cred_path.exists():
            try:
                saved = json.loads(cred_path.read_text(encoding="utf-8"))
            except Exception:
                saved = {}
        saved.update(mapping)
        cred_path.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not write credentials.json during auto-refresh: %s", exc)

    # 2. Update .env
    try:
        env_path = Path(".env")
        lines: list[str] = []
        seen: set[str] = set()
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k = stripped.split("=", 1)[0].strip()
                    if k in mapping:
                        lines.append(f"{k}={mapping[k]}")
                        seen.add(k)
                    else:
                        lines.append(line)
                else:
                    lines.append(line)

        for k, v in mapping.items():
            if k not in seen:
                lines.append(f"{k}={v}")

        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not update .env during auto-refresh: %s", exc)


def refresh_karix_session(
    account: str = "bajaj",
    username: str | None = None,
    password: str | None = None,
    login_url: str | None = None,
    timeout_sec: int = 35,
    user_attribution: str = "Self-Healing Auth Agent",
) -> dict[str, Any]:
    """
    Launch headless Playwright Chromium, navigate to Karix portal, log in,
    intercept and extract Authorization Bearer token, Session ID, and User header,
    and persist them to disk.
    """
    _load_env_file()
    acc = account.lower().strip()
    prefix = _account_prefix(acc)
    is_tata = acc == "tata"
    is_bajaj = acc == "bajaj"

    u = username or os.environ.get(f"{prefix}_PORTAL_USER") or os.environ.get("KARIX_PORTAL_USER") or os.environ.get(f"{prefix}_USER") or os.environ.get("KARIX_USER")
    p = password or os.environ.get(f"{prefix}_PORTAL_PASSWORD") or os.environ.get("KARIX_PORTAL_PASSWORD") or os.environ.get(f"{prefix}_PASSWORD") or os.environ.get("KARIX_PASSWORD")
    target_url = login_url or os.environ.get(f"{prefix}_PORTAL_URL") or KARIX_PORTAL_LOGIN_URLS[0]

    if not u or not p:
        msg = f"No portal username/password found for {account.title()} ({prefix}_PORTAL_USER / {prefix}_PORTAL_PASSWORD). Please configure portal login credentials in Settings."
        logger.warning(msg)
        return {
            "success": False,
            "account": acc,
            "error": msg,
            "requires_credentials": True,
        }

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        msg = "Playwright is not installed. Run 'pip install playwright && playwright install chromium' to enable self-healing browser login."
        logger.error(msg)
        return {"success": False, "account": acc, "error": msg}

    harvested: dict[str, str] = {}
    logger.info("Starting headless browser login for %s at %s...", acc, target_url)

    try:
        with sync_playwright() as p_ctx:
            browser = p_ctx.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                ignore_https_errors=True,
            )
            page = context.new_page()

            # Sniff network requests for auth headers
            def handle_request(req):
                headers = req.headers
                auth = headers.get("authorization") or headers.get("authentication")
                sess = headers.get("session") or headers.get("x-session-id")
                usr = headers.get("user") or headers.get("x-user")

                if auth and "bearer " in auth.lower():
                    token = auth.split(" ", 1)[1].strip()
                    if len(token) > 20 and not harvested.get("bearer_token"):
                        harvested["bearer_token"] = token
                        logger.info("Harvested Bearer token from request: %s...", token[:15])

                if sess and not harvested.get("session"):
                    harvested["session"] = sess.strip()
                    logger.info("Harvested Session ID: %s", sess)

                if usr and not harvested.get("user"):
                    harvested["user"] = usr.strip()

            # Sniff responses for token payloads
            def handle_response(resp):
                try:
                    if "json" in resp.headers.get("content-type", "").lower():
                        data = resp.json()
                        if isinstance(data, dict):
                            token = data.get("token") or data.get("access_token") or data.get("jwt") or data.get("bearer")
                            if token and isinstance(token, str) and len(token) > 20 and not harvested.get("bearer_token"):
                                harvested["bearer_token"] = token.replace("Bearer ", "").strip()
                            sess = data.get("sessionId") or data.get("session") or data.get("sessionId")
                            if sess and isinstance(sess, str) and not harvested.get("session"):
                                harvested["session"] = sess.strip()
                            user_val = data.get("user") or data.get("username")
                            if user_val and isinstance(user_val, str) and not harvested.get("user"):
                                harvested["user"] = user_val.strip()
                except Exception:
                    pass

            page.on("request", handle_request)
            page.on("response", handle_response)

            # Navigate to login page
            page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_sec * 1000)
            page.wait_for_timeout(1500)

            # Locate username field
            user_selectors = [
                'input[name="username"]',
                'input[name="user"]',
                'input[name="email"]',
                'input[type="email"]',
                '#username',
                '#user',
                '#email',
                'input[placeholder*="user" i]',
                'input[placeholder*="email" i]',
                'input[type="text"]',
            ]
            user_input = None
            for sel in user_selectors:
                if page.locator(sel).first.is_visible():
                    user_input = page.locator(sel).first
                    break

            if user_input:
                user_input.fill(u)
                page.wait_for_timeout(300)
            else:
                logger.warning("Username input field not detected on %s", target_url)

            # Locate password field
            pass_selectors = [
                'input[type="password"]',
                'input[name="password"]',
                'input[name="pass"]',
                '#password',
                '#pass',
                'input[placeholder*="pass" i]',
            ]
            pass_input = None
            for sel in pass_selectors:
                if page.locator(sel).first.is_visible():
                    pass_input = page.locator(sel).first
                    break

            if pass_input:
                pass_input.fill(p)
                page.wait_for_timeout(300)
            else:
                logger.warning("Password input field not detected on %s", target_url)

            # Submit form
            submit_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Login")',
                'button:has-text("Sign in")',
                'button:has-text("Submit")',
                '.login-btn',
                '#loginBtn',
            ]
            for sel in submit_selectors:
                if page.locator(sel).first.is_visible():
                    page.locator(sel).first.click()
                    break
            else:
                # Fallback: hit Enter on password
                if pass_input:
                    pass_input.press("Enter")

            # Wait for navigation / network idle after login
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                page.wait_for_timeout(3000)

            # Extract from localStorage and sessionStorage
            try:
                storage_data = page.evaluate("""() => {
                    const res = {};
                    for (let i = 0; i < localStorage.length; i++) {
                        const k = localStorage.key(i);
                        res[k] = localStorage.getItem(k);
                    }
                    for (let i = 0; i < sessionStorage.length; i++) {
                        const k = sessionStorage.key(i);
                        res[k] = sessionStorage.getItem(k);
                    }
                    return res;
                }""")

                for k, v in storage_data.items():
                    if isinstance(v, str):
                        if ("token" in k.lower() or "jwt" in k.lower() or "auth" in k.lower()) and len(v) > 20:
                            if not harvested.get("bearer_token"):
                                harvested["bearer_token"] = v.replace("Bearer ", "").strip()
                        if "session" in k.lower() and len(v) > 6:
                            if not harvested.get("session"):
                                harvested["session"] = v.strip()
                        if "user" in k.lower() and not harvested.get("user"):
                            try:
                                parsed = json.loads(v)
                                if isinstance(parsed, dict) and "name" in parsed:
                                    harvested["user"] = parsed["name"]
                            except Exception:
                                if len(v) < 50:
                                    harvested["user"] = v.strip()
            except Exception as e:
                logger.debug("Could not inspect browser storage: %s", e)

            # Extract cookies
            cookies = context.cookies()
            cookie_strs = [f"{c['name']}={c['value']}" for c in cookies]
            if cookie_strs:
                harvested["lounge_cookie"] = "; ".join(cookie_strs)

            browser.close()

    except Exception as exc:
        logger.exception("Playwright auto-login failed for %s: %s", acc, exc)
        return {
            "success": False,
            "account": acc,
            "error": f"Browser automation error: {str(exc)}",
        }

    # Verify if we got tokens
    if not harvested.get("bearer_token") and not harvested.get("session"):
        msg = f"Browser login completed for {account}, but no Bearer or Session token was captured from network or storage."
        logger.warning(msg)
        return {"success": False, "account": acc, "error": msg, "harvested": harvested}

    # Save harvested tokens
    update_persisted_credentials(account=acc, tokens=harvested)

    log_activity(
        user=user_attribution,
        action="AUTH_AUTO_REFRESH_SUCCESS",
        account=acc,
        channel="whatsapp",
        details={
            "has_bearer": bool(harvested.get("bearer_token")),
            "has_session": bool(harvested.get("session")),
            "user": harvested.get("user"),
        },
        status="success",
    )

    logger.info("Self-healing auth succeeded for %s: harvested fresh tokens.", acc)
    return {
        "success": True,
        "account": acc,
        "tokens_updated": list(harvested.keys()),
        "user": harvested.get("user"),
        "message": f"Successfully harvested fresh Karix session tokens for {account.title()}.",
    }
