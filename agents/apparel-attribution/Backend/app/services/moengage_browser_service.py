from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse, urlunparse

import httpx
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from app.config.settings import validate_private_cdp
from app.core.local_storage import private_directory, private_file
from app.models.report import CampaignRow

logger = logging.getLogger(__name__)


class BrowserAutomationError(RuntimeError):
    pass


class BrowserUnavailableError(BrowserAutomationError):
    """The remote browser process/CDP endpoint is temporarily unavailable."""


class BrowserAuthenticationError(BrowserAutomationError):
    """The persistent browser is reachable but its MoEngage login is invalid."""


@dataclass(frozen=True)
class BehaviorQueryPlan:
    transaction_operator: str
    delivery_event: str
    analysis_type: str
    result_row_label: str
    aggregation: str | None = None
    aggregation_attribute: str | None = None


DELIVERY_EVENTS = {
    "WhatsApp": "WhatsApp Message Delivered",
    "SMS": "SMS Delivered",
    "RCS": "RCS Delivered",
}
DELIVERY_LOOKBACK_DAYS = 120
CIS_BRAND_OPERATOR = "(any of) contains"
CIS_BRAND_VALUE = "SP"

PURCHASED_CUSTOMERS_TITLE = re.compile(
    r"(?:Number\s+of|Campaign)\s+Purc(?:hased|ahsed)\s+Customers", re.I
)
CIS_EVENT_BRAND_PATTERN = re.compile(
    r"Brand_PM.*?contains.*?\bSP\b",
    re.I | re.S,
)


def build_behavior_query_plan(row: CampaignRow, metric: str) -> BehaviorQueryPlan:
    if row.campaign_type not in {"Online", "Offline"}:
        raise BrowserAutomationError("Overall rows must be split into Online and Offline queries")
    try:
        delivery_event = DELIVERY_EVENTS[row.channel]
    except KeyError as exc:
        raise BrowserAutomationError(f"No delivered-event mapping for channel {row.channel!r}") from exc
    operator = "exists" if row.campaign_type == "Online" else "does not exist"
    if metric == "unique_users":
        return BehaviorQueryPlan(operator, delivery_event, "Unique users", "Sale_Array")
    if metric == "total_revenue":
        return BehaviorQueryPlan(
            operator,
            delivery_event,
            "Aggregation",
            "Sum of Order_Net_Val in Sale_Array",
            aggregation="Sum",
            aggregation_attribute="Order_Net_Val",
        )
    raise BrowserAutomationError(f"Unsupported metric {metric!r}")


class MoEngageBrowserService:
    def __init__(
        self,
        profile_dir: Path,
        dashboard_url: str,
        ui_config: dict[str, Any],
        remote_cdp_url: str = "",
    ):
        self.profile_dir = profile_dir
        self.dashboard_url = dashboard_url
        self.ui = ui_config
        self.remote_cdp_url = remote_cdp_url
        self.playwright: Playwright | None = None
        self.remote_browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.active_workspace: str | None = None
        self.lock = asyncio.Lock()
        self.connection_lock = asyncio.Lock()

    def _diagnostic_path(self, name: str) -> str:
        directory = self.profile_dir.parent / "diagnostics"
        private_directory(directory)
        # Dropdown labels can contain separators or characters forbidden on Windows.
        path = directory / re.sub(r"[^A-Za-z0-9._-]", "-", name)
        private_file(path)
        return str(path)

    async def start_login(self, login_hint: str | None = None) -> str:
        async with self.lock:
            await self._ensure_browser()
            await self.page.goto(self.dashboard_url, wait_until="domcontentloaded")
            await self.page.bring_to_front()
            return "Open the protected browser, complete Google/MoEngage login and MFA, then verify the session. Authentication is completed by a human."

    async def reset_login(self) -> None:
        """Clear authentication in the actual persistent remote browser."""
        async with self.lock:
            await self._ensure_browser()
            await self.context.clear_cookies()
            session = await self.context.new_cdp_session(self.page)
            try:
                origins = {self.dashboard_url, "https://accounts.google.com", "https://google.com"}
                for page in self.context.pages:
                    parsed = urlparse(page.url)
                    host = parsed.hostname or ""
                    if host.endswith(".moengage.com") or host == "moengage.com" or host.endswith(".google.com"):
                        origins.add(f"{parsed.scheme}://{parsed.netloc}")
                for origin in origins:
                    parsed = urlparse(origin)
                    await session.send("Storage.clearDataForOrigin", {
                        "origin": f"{parsed.scheme}://{parsed.netloc}", "storageTypes": "all",
                    })
            finally:
                await session.detach()
            self.active_workspace = None
            await self.page.goto(self.dashboard_url, wait_until="domcontentloaded")

    async def status(self) -> tuple[str, str]:
        if not self.remote_cdp_url:
            return "not_configured", "An administrator must configure the private Chromium service"
        if self.remote_cdp_url:
            try:
                await self._ensure_browser()
            except BrowserAutomationError as exc:
                return "disconnected", str(exc)
        if not self.page or self.page.is_closed():
            return "disconnected", "Open the MoEngage login window to connect."
        login_url = self.ui.get("login_url_contains", "login")
        logged_selector = self.ui.get("logged_in_selector")
        if login_url and login_url.lower() in self.page.url.lower():
            return "waiting_for_login", "Complete the login in the MoEngage window."
        expected_host = urlparse(self.dashboard_url).hostname
        current_host = urlparse(self.page.url).hostname
        if expected_host and expected_host != current_host:
            return "waiting_for_login", "Complete the login in the MoEngage window."
        if logged_selector:
            try:
                await self.page.locator(logged_selector).first.wait_for(timeout=3000)
            except Exception:
                return "waiting_for_login", "The configured logged-in marker is not visible yet."
        return "connected", "MoEngage session is connected and stored in the local browser profile."

    async def _ensure_browser(self, headless: bool = True):
        async with self.connection_lock:
            await self._connect_browser()

    async def _connect_browser(self):
        expected_host = urlparse(self.dashboard_url).hostname
        if (self.page and not self.page.is_closed()
                and (self.page.url == "about:blank"
                     or urlparse(self.page.url).hostname == expected_host)):
            try:
                await asyncio.wait_for(self.page.evaluate("1"), timeout=3.0)
                return
            except (PlaywrightError, RuntimeError, asyncio.TimeoutError):
                await self._clear_remote_connection()
        if self.context:
            try:
                for candidate in reversed(self.context.pages):
                    if candidate.is_closed() or urlparse(candidate.url).hostname != expected_host:
                        continue
                    try:
                        await asyncio.wait_for(candidate.evaluate("1"), timeout=3.0)
                        self.page = candidate
                        return
                    except (PlaywrightError, RuntimeError, asyncio.TimeoutError):
                        try:
                            await asyncio.wait_for(
                                candidate.close(run_before_unload=False), timeout=2
                            )
                        except Exception:
                            pass
                        continue
                self.page = await self.context.new_page()
                return
            except Exception:
                await self._clear_remote_connection()
        if self.playwright is None:
            self.playwright = await async_playwright().start()
        if self.remote_cdp_url:
            try:
                websocket_url = await self._remote_websocket_url()
                self.remote_browser = await self.playwright.chromium.connect_over_cdp(
                    websocket_url,
                    timeout=30000,
                )
            except (PlaywrightError, RuntimeError, httpx.HTTPError, OSError, ValueError) as exc:
                logger.exception("Could not attach to the Railway Chromium CDP endpoint")
                await self._clear_remote_connection()
                raise BrowserUnavailableError(
                    "The Railway login browser is recovering. The campaign has not been consumed; "
                    "automation will retry when Chromium is ready."
                ) from exc
            self.context = (
                self.remote_browser.contexts[0]
                if self.remote_browser.contexts
                else await self.remote_browser.new_context(viewport={"width": 1440, "height": 960})
            )
            self.page = next(
                (
                    page for page in self.context.pages
                    if not page.is_closed() and urlparse(page.url).hostname == expected_host
                ),
                None,
            )
            if self.page is None:
                self.page = await self.context.new_page()
            return
        raise BrowserUnavailableError("The private Chromium service is not configured")

    async def _clear_remote_connection(self) -> None:
        """Discard a dead CDP transport without terminating persistent Chromium."""
        self.page = None
        self.context = None
        self.remote_browser = None
        self.active_workspace = None
        if self.playwright:
            try:
                await asyncio.wait_for(self.playwright.stop(), timeout=5)
            except Exception:
                pass
        self.playwright = None

    async def wait_until_ready(
        self,
        timeout_seconds: float = 90.0,
        retry_interval_seconds: float = 3.0,
    ) -> None:
        """Wait for a restarting Railway Chromium before campaign processing starts."""
        deadline = time.monotonic() + max(timeout_seconds, 0)
        last_error: BrowserUnavailableError | None = None
        while True:
            try:
                await self._ensure_browser(headless=True)
                return
            except BrowserUnavailableError as exc:
                last_error = exc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BrowserUnavailableError(
                        "The Railway browser did not recover within "
                        f"{int(timeout_seconds)} seconds. No campaign rows were processed; "
                        "restart the browser service and retry the run."
                    ) from last_error
                await asyncio.sleep(min(retry_interval_seconds, remaining))

    async def _remote_websocket_url(self) -> str:
        """Resolve Railway private DNS and return Chromium's reachable CDP WebSocket URL."""
        parsed = urlparse(self.remote_cdp_url)
        validate_private_cdp(self.remote_cdp_url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            parsed.hostname,
            port,
            0,
            socket.SOCK_STREAM,
        )
        address = addresses[0][4][0]
        resolved = ipaddress.ip_address(address)
        if not (resolved.is_private or resolved.is_loopback) or any((
            resolved.is_unspecified, resolved.is_multicast, resolved.is_link_local, resolved.is_reserved,
        )):
            raise ValueError("The Chromium debugger must resolve to a trusted private address")
        ip_host = f"[{address}]" if ":" in address else address
        ip_netloc = f"{ip_host}:{port}"
        version_url = urlunparse((parsed.scheme, ip_netloc, "/json/version", "", "", ""))
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False, trust_env=False) as client:
            response = await client.get(version_url)
            response.raise_for_status()
            browser_websocket = response.json().get("webSocketDebuggerUrl")
        if not browser_websocket:
            raise ValueError("Chromium did not return a browser WebSocket URL")
        websocket_path = urlparse(browser_websocket).path
        if not re.fullmatch(r"/devtools/browser/[A-Za-z0-9-]+", websocket_path):
            raise ValueError("Chromium returned an invalid browser debugger path")
        websocket_scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunparse((websocket_scheme, ip_netloc, websocket_path, "", "", ""))

    async def close(self):
        if self.context and not self.remote_cdp_url:
            try:
                await self.context.close()
            except Exception:
                pass
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass
        self.page = None
        self.context = None
        self.remote_browser = None
        self.active_workspace = None
        self.playwright = None

    async def recover(self) -> None:
        """Replace an unresponsive automation tab without logging the user out."""
        async with self.lock:
            if self.remote_cdp_url:
                await self._replace_remote_page()
            else:
                await self._ensure_browser(headless=True)
                await self.page.goto(self.dashboard_url, wait_until="domcontentloaded")
                self.active_workspace = None

    async def query_metric(self, row: CampaignRow, metric: str) -> float:
        async with self.lock:
            await self._ensure_browser(headless=True)
            expected_host = urlparse(self.dashboard_url).netloc
            current_host = urlparse(self.page.url).netloc if self.page else ""
            if self.page and (self.page.url == "about:blank" or current_host != expected_host):
                await self.page.goto(self.dashboard_url, wait_until="domcontentloaded")
            state, message = await self.status()
            if state != "connected":
                if state == "waiting_for_login":
                    raise BrowserAuthenticationError(message)
                raise BrowserAutomationError(message)
            if self.ui.get("workflow") == "recorded_behavior":
                for attempt in range(2):
                    try:
                        return await self._query_recorded_behavior(row, metric)
                    except (BrowserAutomationError, PlaywrightError) as exc:
                        if isinstance(exc, PlaywrightError):
                            logger.warning(
                                "MoEngage browser error for row %s metric %s: %s",
                                row.excel_row,
                                metric,
                                exc,
                            )
                        recoverable = isinstance(exc, PlaywrightError) or any(
                            text in str(exc).casefold()
                            for text in (
                                "behavior query did not load",
                                "redirected away from the behavior report",
                                "target crashed",
                                "page crashed",
                            )
                        )
                        if attempt or not recoverable:
                            if recoverable and self.remote_cdp_url:
                                try:
                                    await self._replace_remote_page()
                                except Exception:
                                    logger.exception(
                                        "Could not prepare a clean browser tab after final failure"
                                    )
                            if isinstance(exc, PlaywrightError):
                                raise BrowserAutomationError(
                                    f"MoEngage browser query failed: {exc}"
                                ) from exc
                            raise
                        if self.remote_cdp_url:
                            await self._replace_remote_page()
                        else:
                            # MoEngage occasionally leaves a stale/hidden SPA shell in
                            # the DOM. A fresh navigation on the next attempt is safe
                            # because the query builder is read-only until APPLY.
                            await self.page.wait_for_timeout(1500)
            raise BrowserAutomationError("Only the configured recorded_behavior report workflow is supported")

    async def _replace_remote_page(self) -> None:
        """Dispose of a failed CDP tab and reconnect with a clean automation tab."""
        failed_page = self.page
        self.page = None
        self.active_workspace = None
        if failed_page and not failed_page.is_closed():
            try:
                await asyncio.wait_for(
                    failed_page.close(run_before_unload=False),
                    timeout=5,
                )
            except Exception:
                # A crashed renderer may no longer acknowledge Page.close.
                pass

        # A target crash can poison the existing CDP transport even when
        # BrowserContext.new_page() appears to succeed. Disconnect Playwright
        # and attach again to the persistent Chromium process before retrying.
        await self._clear_remote_connection()
        await self._ensure_browser()

        # Never repurpose a user's visible login/dashboard tab. If reconnecting
        # selected one, leave it intact and create a dedicated automation tab.
        if self.page.url != "about:blank":
            self.page = await self.context.new_page()
        await self.page.goto(self.dashboard_url, wait_until="domcontentloaded")

    async def _query_recorded_behavior(self, row: CampaignRow, metric: str) -> float:
        pending = {
            str(brand).casefold()
            for brand in self.ui.get("pending_special_workflows", [])
        }
        if row.brand.casefold() in pending and not (
            row.brand.casefold() == "agipl" and row.attribution_brand
        ):
            raise BrowserAutomationError(
                f"{row.brand} dashboard is configured, but its special query logic is still pending"
            )
        plan = build_behavior_query_plan(row, metric)
        page = self.page
        query_url = self._query_url_for_brand(row.brand)
        report_already_open = await self._switch_workspace(page, row.brand)
        if not report_already_open:
            await self._goto_behavior_report(page, query_url)
        try:
            await self._wait_for_behavior_report(page)
        except Exception as exc:
            screenshot_note = "disabled for the Railway browser"
            if not self.remote_cdp_url:
                screenshot_path = self._diagnostic_path("moengage-query-error.png")
                try:
                    await page.screenshot(path=str(screenshot_path), full_page=False)
                    screenshot_note = str(screenshot_path)
                except Exception:
                    screenshot_note = "unavailable"
            try:
                title = await page.title()
                body = (await page.locator("body").inner_text()).replace("\n", " | ")[:600]
                current_url = page.url
            except Exception:
                title, body, current_url = "unavailable", "unavailable", "unavailable"
            raise BrowserAutomationError(
                f"MoEngage behavior query did not load (url={current_url!r}, title={title!r}, "
                f"screenshot={screenshot_note!r}, page={body!r})"
            ) from exc

        await self._ensure_section_open(page, "Events & filters", "Sale_Array")
        await self._set_transaction_channel(page, plan.transaction_operator)
        if self._uses_event_transaction_brand(row.brand):
            await self._set_agipl_transaction_brand(page, row.attribution_brand)
        elif row.brand.casefold() == "cis":
            await self._ensure_cis_transaction_brand(page)

        await self._ensure_filter_editor_open(page)
        await self._set_delivery_event(page, plan.delivery_event)
        await self._set_delivery_lookback(page, DELIVERY_LOOKBACK_DAYS)
        await self._set_campaign_id(page, row.campaign_id)

        await self._ensure_section_open(page, "Behavior Options", "Analysis type")
        await self._set_behavior_options(page, row, plan)
        await self._set_daily_granularity(page)
        await page.get_by_role("button", name="APPLY", exact=True).click()
        return await self._read_behavior_total(
            page, plan.result_row_label, (row.end_date - row.start_date).days + 1,
        )

    @staticmethod
    def _uses_event_transaction_brand(brand: str) -> bool:
        """Only AGIPL stores its target-brand condition on Sale_Array itself."""
        return brand.casefold() == "agipl"

    def _agipl_transaction_brand_value(self, attribution_brand: str | None) -> str:
        if not attribution_brand:
            raise BrowserAutomationError("Choose the attribution brand for AGIPL campaigns")
        if attribution_brand.casefold() == "agipl":
            raise BrowserAutomationError("AGIPL cannot attribute campaigns to itself")
        mapping = self.ui.get("agipl_attribution_brand_values") or {}
        return next(
            (
                str(value)
                for brand, value in mapping.items()
                if brand.casefold() == attribution_brand.casefold()
            ),
            attribution_brand,
        )

    async def _set_agipl_transaction_brand(
        self, page: Page, attribution_brand: str | None
    ):
        value = self._agipl_transaction_brand_value(attribution_brand)
        try:
            attribute = await self._reset_transaction_attribute(page, "Txn_Brand")
            dropdowns = attribute.locator(".mds-dropdown:visible")
            count = await dropdowns.count()
            if count < 3:
                raise BrowserAutomationError(
                    "AGIPL report must contain Txn_Brand contains <brand> in Events & filters"
                )
            operator = dropdowns.nth(count - 2)
            await self._set_titled_dropdown_control(page, operator, "contains")
            # Selecting the operator can rerender the entire attribute. Resolve
            # the fresh value control again before opening it.
            attribute = page.locator(".mds-attr:visible").filter(
                has_text=re.compile(r"Txn_Brand", re.I)
            ).first
            brand_value = attribute.locator(".mds-dropdown:visible").last
            await self._set_agipl_brand_value(page, brand_value, value)
            selected_value = brand_value.locator(".mds-dropdown__trigger__inner").first
            retained = (await selected_value.inner_text()).strip()
            if retained.casefold() != value.casefold():
                raise BrowserAutomationError(
                    f"MoEngage retained Txn_Brand {retained!r} instead of {value!r}"
                )
            await brand_value.press("Escape")
        except BrowserAutomationError:
            raise
        except Exception as exc:
            screenshot_path = self._diagnostic_path("moengage-agipl-brand.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not set AGIPL Txn_Brand to {value!r} "
                f"(screenshot={screenshot_path!r})"
            ) from exc

    async def _ensure_cis_transaction_brand(self, page: Page):
        """Verify the saved CIS Brand_PM row without changing any of its controls."""
        txn_channel = page.locator(".mds-attr:visible").filter(
            has_text=re.compile(r"Txn_Channel", re.I)
        ).first
        try:
            await txn_channel.wait_for(state="visible", timeout=10000)
            event = txn_channel.locator(
                "xpath=ancestor::*[.//*[@data-test='attribute-add-btn']][1]"
            )
            await event.wait_for(state="visible", timeout=10000)
            brand_attribute = event.locator(".mds-attr:visible").filter(
                has_text=re.compile(r"Brand_PM", re.I)
            ).first
            await brand_attribute.wait_for(state="visible", timeout=10000)
            attribute_text = await brand_attribute.inner_text()
            inputs = brand_attribute.locator("input:visible")
            input_values = [
                await inputs.nth(index).input_value()
                for index in range(await inputs.count())
            ]
            operator_ok = (
                CIS_BRAND_OPERATOR.casefold() in attribute_text.casefold()
            )
            value_ok = any(
                value.strip() == CIS_BRAND_VALUE for value in input_values
            )
            if operator_ok and value_ok:
                return
        except PlaywrightError as exc:
            failure = str(exc)
        else:
            failure = (
                f"operator_text={attribute_text!r}, input_values={input_values!r}"
            )
        screenshot_path = self._diagnostic_path("moengage-cis-brand-readonly-check.png")
        await page.screenshot(path=screenshot_path, full_page=True)
        raise BrowserAutomationError(
            "CIS Brand_PM row must already be configured as "
            f"{CIS_BRAND_OPERATOR!r} with uppercase {CIS_BRAND_VALUE!r}. "
            "The automation did not change the row "
            f"({failure}, screenshot={screenshot_path!r})"
        )

    @staticmethod
    async def _set_agipl_brand_value(page: Page, control, value: str):
        await control.wait_for(state="visible", timeout=10000)
        await control.focus()
        await control.press("Enter")
        await page.wait_for_timeout(300)
        if not await page.locator(".mds-dropdown__popup:visible").count():
            await control.press("Space")
            await page.wait_for_timeout(300)
        if not await page.locator(".mds-dropdown__popup:visible").count():
            trigger = control.locator(".mds-dropdown__trigger").first
            await trigger.dispatch_event("mousedown")
            await trigger.dispatch_event("mouseup")
            await trigger.dispatch_event("click")
            await page.wait_for_timeout(300)
        await MoEngageBrowserService._select_open_option(page, value)

    @staticmethod
    async def _sale_event(page: Page):
        name = page.locator(
            ".mds-event__event-name .mds-dropdown__trigger__inner__single--value"
        ).filter(has_text=re.compile(r"^\s*Sale_Array\s*$", re.I)).first
        await name.wait_for(state="visible", timeout=10000)
        return name.locator(
            "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' mds-event ')][1]"
        )

    @staticmethod
    async def _reset_transaction_attribute(page: Page, target_attribute: str):
        """Delete and recreate a Sale_Array transaction attribute.

        The value dropdown is single-select and can retain its prior React state.
        Recreating the attribute guarantees that a run cannot accidentally use
        the value retained by the preceding campaign.
        """
        try:
            event = await MoEngageBrowserService._sale_event(page)

            target_pattern = re.compile(re.escape(target_attribute), re.I)
            attributes = event.locator(".mds-attr:visible").filter(
                has_text=target_pattern
            )
            removed = 0
            while await attributes.count():
                attribute = attributes.last
                delete_button = attribute.locator("[data-test='delete-button']").first
                await delete_button.wait_for(state="visible", timeout=5000)
                await delete_button.dispatch_event("mousedown")
                await delete_button.dispatch_event("mouseup")
                await delete_button.dispatch_event("click")
                await attribute.wait_for(state="detached", timeout=5000)
                removed += 1
                if removed > 10:
                    raise BrowserAutomationError(
                        f"MoEngage returned too many {target_attribute} attributes while clearing"
                    )
                attributes = event.locator(".mds-attr:visible").filter(
                    has_text=target_pattern
                )

            # A failed prior attempt can leave an incomplete "Select attribute"
            # row. Remove it before adding the target so retries always begin
            # from the same state.
            empty_attributes = event.locator(".mds-attr:visible").filter(
                has_text=re.compile(r"Select attribute", re.I)
            )
            while await empty_attributes.count():
                empty_attribute = empty_attributes.last
                delete_button = empty_attribute.locator(
                    "[data-test='delete-button']"
                ).first
                await delete_button.wait_for(state="visible", timeout=5000)
                await delete_button.click(force=True)
                await empty_attribute.wait_for(state="detached", timeout=5000)
                removed += 1
                if removed > 10:
                    raise BrowserAutomationError(
                        "MoEngage returned too many incomplete attributes while clearing"
                    )
                empty_attributes = event.locator(".mds-attr:visible").filter(
                    has_text=re.compile(r"Select attribute", re.I)
                )

            add_attribute = event.locator("[data-test='attribute-add-btn']").first
            await add_attribute.wait_for(state="visible", timeout=10000)
            await add_attribute.click(force=True)
            await page.wait_for_timeout(400)

            attribute_control = event.locator(
                ".mds-attr__name .mds-dropdown:visible"
            ).last
            await attribute_control.wait_for(state="visible", timeout=10000)
            popup_id = (await attribute_control.get_attribute("id")).replace("trigger_", "popup_", 1)
            if not await page.locator(f'[id="{popup_id}"]:visible').count():
                trigger = attribute_control.locator(".mds-dropdown__trigger").first
                await trigger.dispatch_event("mousedown")
                await trigger.dispatch_event("mouseup")
                await trigger.dispatch_event("click")
            await MoEngageBrowserService._select_open_option(
                page, target_attribute, allow_create=False
            )

            fresh_attribute = event.locator(".mds-attr:visible").filter(
                has_text=target_pattern
            ).last
            await fresh_attribute.wait_for(state="visible", timeout=10000)
            return fresh_attribute
        except BrowserAutomationError:
            raise
        except Exception as exc:
            raise BrowserAutomationError(
                f"Could not clear and recreate the {target_attribute} attribute"
            ) from exc

    @staticmethod
    async def _wait_for_behavior_report(page: Page):
        """Wait for report content without selecting a hidden duplicate title."""
        for _ in range(60):
            try:
                body_text = await page.locator("body").inner_text(timeout=2000)
                if PURCHASED_CUSTOMERS_TITLE.search(body_text):
                    return
            except PlaywrightError:
                pass
            await page.wait_for_timeout(500)
        raise BrowserAutomationError(
            "The purchased-customers report title did not appear in the visible page content"
        )

    @staticmethod
    async def _goto_behavior_report(page: Page, query_url: str):
        """Open a report after workspace redirects have fully settled."""
        # The dashboard's async startup scripts can still be loading after
        # DOMContentLoaded, even with its workspace label visible. Navigating
        # away then can leave the report permanently stuck in the SPA shell.
        await page.wait_for_load_state("load")
        last_error = None
        for attempt in range(3):
            try:
                await page.goto(query_url, wait_until="domcontentloaded")
            except PlaywrightError as exc:
                last_error = exc
                if "interrupted by another navigation" not in str(exc).lower():
                    raise
            await page.wait_for_timeout(1200)
            current_url = page.url
            if (
                "/analytics/v2/behavior" in current_url
                and "did=" in current_url
                and "chartId=" in current_url
            ):
                return
            if attempt < 2:
                await page.wait_for_timeout(1200)
        raise BrowserAutomationError(
            "MoEngage redirected away from the Behavior report while changing workspaces"
        ) from last_error

    def _query_url_for_brand(self, brand: str) -> str:
        mapping = self.ui.get("query_url_map") or {}
        if mapping:
            query_url = next(
                (value for key, value in mapping.items() if key.casefold() == brand.casefold()),
                None,
            )
            if not query_url:
                raise BrowserAutomationError(
                    f"No MoEngage Behavior query URL is configured for brand {brand!r}. "
                    "Add that brand's full behavior URL containing did and chartId."
                )
            return query_url
        query_url = self.ui.get("query_url")
        if not query_url:
            raise BrowserAutomationError("MOENGAGE_UI_CONFIG_JSON.query_url is required")
        return query_url

    @staticmethod
    def _dashboard_id_from_url(url: str) -> str | None:
        """Read a MoEngage dashboard ID from either a report or dashboard URL."""
        parsed = urlparse(url)
        query_dashboard = (parse_qs(parsed.query).get("did") or [None])[0]
        if query_dashboard:
            return query_dashboard
        dashboard_path = re.search(r"/dashboards/([^/?#]+)", parsed.path, re.I)
        return dashboard_path.group(1) if dashboard_path else None

    async def _switch_workspace(self, page: Page, brand: str) -> bool:
        """Select a workspace, returning True when its report was opened directly."""
        mapping = self.ui.get("workspace_map", {})
        target = next((value for key, value in mapping.items() if key.casefold() == brand.casefold()), None)
        if not target:
            raise BrowserAutomationError(f"No MoEngage workspace mapping configured for brand {brand!r}")
        # Behavior URLs contain the dashboard ID belonging to their workspace.
        # This is more reliable than a switcher label, which MoEngage hides on
        # some report layouts, and avoids reopening the same workspace for every
        # metric in a same-brand batch.
        target_query_url = self._query_url_for_brand(brand)
        current_dashboard = self._dashboard_id_from_url(page.url)
        target_dashboard = self._dashboard_id_from_url(target_query_url)
        if target_dashboard and current_dashboard == target_dashboard:
            self.active_workspace = target
            return False
        if self.active_workspace == target and current_dashboard is None:
            return False
        current = page.get_by_text(target, exact=True)
        for index in range(await current.count()):
            if await current.nth(index).is_visible():
                self.active_workspace = target
                return False
        known = sorted(set(mapping.values()), key=len, reverse=True)
        switcher = None
        selector = self.ui.get("workspace_switcher")
        if selector:
            switcher = page.locator(selector).first
        else:
            for name in known:
                candidate = page.get_by_text(name, exact=True)
                if await candidate.count() and await candidate.first.is_visible():
                    switcher = candidate.first
                    break
        if switcher is None:
            # MoEngage hides the switcher on several dashboard/report layouts.
            # The saved brand URL includes the authoritative dashboard ID, so
            # direct navigation is both faster and more reliable than failing.
            logger.warning(
                "Workspace switcher is hidden for brand %s at %s; opening its report directly",
                brand,
                page.url,
            )
            try:
                await self._goto_behavior_report(page, target_query_url)
            except Exception as exc:
                raise BrowserAutomationError(
                    f"Could not open the {brand} MoEngage workspace directly "
                    f"from {page.url!r}"
                ) from exc
            if self._dashboard_id_from_url(page.url) != target_dashboard:
                raise BrowserAutomationError(
                    f"MoEngage redirected away from the {brand} workspace "
                    f"to {page.url!r}"
                )
            self.active_workspace = target
            return True
        await switcher.click()
        await self._select_open_option(page, target)
        confirmation = page.get_by_role("button", name=re.compile("Change Workspace", re.I))
        if await confirmation.count() and await confirmation.first.is_visible():
            await confirmation.first.click()
        # Workspace changes trigger a delayed SPA redirect. Wait until the URL
        # has remained unchanged before opening the brand's Behavior report.
        await page.wait_for_timeout(1500)
        previous_url = page.url
        stable_checks = 0
        for _ in range(20):
            await page.wait_for_timeout(400)
            current_url = page.url
            if current_url == previous_url:
                stable_checks += 1
                if stable_checks >= 5:
                    break
            else:
                previous_url = current_url
                stable_checks = 0
        self.active_workspace = target
        return False

    @staticmethod
    async def _ensure_section_open(page: Page, heading: str, marker: str):
        title = page.get_by_text(heading, exact=True).first
        header = title.locator("xpath=ancestor::header[1]")
        icon = header.locator(".material-icons").last
        if await icon.count() and "keyboard_arrow_up" in (await icon.inner_text()).strip():
            return
        await title.scroll_into_view_if_needed()
        toggle = header.locator("[role='button']").last
        if await toggle.count():
            await toggle.evaluate("element => element.click()")
        else:
            await title.evaluate("element => element.click()")
        await page.wait_for_timeout(500)
        if heading == "Filter Users":
            nested_filter = page.locator(".mds-segmentation__nested-filter").filter(has_text=marker).first
            if await nested_filter.count():
                await nested_filter.locator(".mds-segmentation__arrow-wrapper").click(force=True)
        await page.get_by_text(re.compile(re.escape(marker), re.I)).first.wait_for(timeout=10000)

    async def _ensure_filter_editor_open(self, page: Page):
        heading = page.get_by_text("Filter Users", exact=True).first
        header = heading.locator("xpath=ancestor::header[1]")
        section_icon = header.locator(".material-icons").last
        delivery_pattern = re.compile(
            "|".join(re.escape(value) for value in DELIVERY_EVENTS.values()), re.I
        )
        nested_filter = page.locator(".mds-segmentation__nested-filter").filter(
            has_text=delivery_pattern
        ).first
        event_control = nested_filter.locator(".mds-event__event-name .mds-dropdown").first

        # A collapsed condition can hide the editor while Filter Users is open.
        # Only toggle the outer section when the condition itself is hidden.
        if not await nested_filter.is_visible():
            toggle = header.locator("[role='button']").last
            if await toggle.count():
                await toggle.click(force=True)
            else:
                await heading.click(force=True)
            await page.wait_for_timeout(600)

            nested_filter = page.locator(".mds-segmentation__nested-filter").filter(
                has_text=delivery_pattern
            ).first
            event_control = nested_filter.locator(".mds-event__event-name .mds-dropdown").first
        try:
            await nested_filter.wait_for(state="visible", timeout=10000)
        except Exception as exc:
            screenshot_path = self._diagnostic_path("moengage-filter-nested-missing.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not find the MoEngage delivered-event filter "
                f"(screenshot={screenshot_path!r})"
            ) from exc
        if not await event_control.is_visible():
            toggle = nested_filter.locator(
                "[data-testid^='segmentation-toggle-filter-']"
            ).first
            await toggle.dispatch_event("click")

        try:
            await event_control.wait_for(state="visible", timeout=10000)
        except Exception as exc:
            screenshot_path = self._diagnostic_path("moengage-filter-editor-error.png")
            await page.screenshot(path=str(screenshot_path), full_page=True)
            raise BrowserAutomationError(
                "Could not open the MoEngage filter editor "
                f"(section_icon={(await section_icon.inner_text()).strip()!r}, "
                f"screenshot={str(screenshot_path)!r})"
            ) from exc

    async def _set_transaction_channel(self, page: Page, operator: str):
        """Set the Sale_Array channel condition, creating it when absent."""
        event = await self._sale_event(page)
        attribute_name = page.locator(
            ".mds-attr__name .mds-dropdown__trigger__inner__single--value"
        ).filter(has_text=re.compile(r"^\s*Txn_Channel\s*$", re.I))
        attribute = event.locator(".mds-attr:visible").filter(has=attribute_name).first
        try:
            # Saved report attributes hydrate after the Sale_Array event.
            await attribute.wait_for(state="visible", timeout=12000)
        except PlaywrightTimeoutError:
            attribute = await self._reset_transaction_attribute(page, "Txn_Channel")
        control = attribute.locator(".mds-dropdown:visible").nth(1)
        await self._set_titled_dropdown_control(page, control, operator)
        retained = (
            await attribute.locator(".mds-dropdown__trigger__inner__single--value").nth(1).inner_text()
        ).strip()
        if retained != operator:
            raise BrowserAutomationError(
                f"MoEngage retained Txn_Channel {retained!r} instead of {operator!r}"
            )


    @staticmethod
    async def _select_open_option(page: Page, value: str, *, allow_create: bool = True):
        async def click_option() -> bool:
            titled_option = page.locator(
                f'.mds-dropdown__popup__list__item[title="{value}"]:visible'
            )
            if await titled_option.count():
                await titled_option.last.dispatch_event("click")
                return True
            popup_option = page.locator(".mds-dropdown__popup__list__item:visible").filter(
                has_text=re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)
            )
            if await popup_option.count():
                await popup_option.last.dispatch_event("click")
                return True
            option = page.get_by_role("option", name=value, exact=True)
            if await option.count() and await option.last.is_visible():
                await option.last.click()
                return True
            text_option = page.get_by_text(value, exact=True)
            for index in range(await text_option.count() - 1, -1, -1):
                candidate = text_option.nth(index)
                popup_item = candidate.locator("xpath=ancestor::*[contains(@class, 'mds-dropdown__popup__list__item')][1]")
                if await candidate.is_visible() and await popup_item.count():
                    await popup_item.click()
                    return True
            return False

        if await click_option():
            return
        search = page.locator(
            ".mds-dropdown__popup:visible input[placeholder*='Search' i], "
            ".mds-dropdown__menu:visible input[placeholder*='Search' i], "
            "[role='listbox']:visible input[placeholder*='Search' i]"
        ).last
        if await search.count() and await search.is_editable():
            await search.fill(value)
            await page.wait_for_timeout(1200)
            if await click_option():
                return
            if allow_create:
                await search.press("Enter")
                return
        popup_count = await page.locator(".mds-dropdown__popup:visible").count()
        visible_inputs = page.locator("input:visible")
        placeholders = []
        for index in range(await visible_inputs.count()):
            placeholders.append(await visible_inputs.nth(index).get_attribute("placeholder"))
        raise BrowserAutomationError(
            f"Could not select MoEngage option {value!r} "
            f"(visible_popups={popup_count}, input_placeholders={placeholders!r})"
        )

    async def _set_delivery_event(self, page: Page, event_name: str):
        delivery_pattern = re.compile(
            "|".join(re.escape(value) for value in DELIVERY_EVENTS.values()), re.I
        )
        nested_filter = page.locator(".mds-segmentation__nested-filter").filter(
            has_text=delivery_pattern
        ).first
        event_control = nested_filter.locator(".mds-event__event-name .mds-dropdown").first
        try:
            await event_control.wait_for(state="visible", timeout=10000)
        except Exception as exc:
            screenshot_path = self._diagnostic_path("moengage-delivery-event-control.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not open the MoEngage delivered-event control "
                f"(screenshot={screenshot_path!r})"
            ) from exc

        current = (await event_control.inner_text()).strip()
        if event_name.casefold() in current.casefold():
            return
        trigger = event_control.locator(".mds-dropdown__trigger").first
        await trigger.dispatch_event("mousedown")
        await trigger.dispatch_event("mouseup")
        await trigger.dispatch_event("click")
        await self._select_open_option(page, event_name)
        await page.wait_for_timeout(500)
        current_control = page.locator(".mds-event__event-name .mds-dropdown:visible").filter(
            has_text=re.compile(r"(WhatsApp Message Delivered|SMS Delivered|RCS Delivered)", re.I)
        ).last
        try:
            await current_control.wait_for(state="visible", timeout=5000)
            current = (await current_control.inner_text()).strip()
        except Exception:
            current = ""
        if event_name.casefold() not in current.casefold():
            screenshot_path = self._diagnostic_path("moengage-delivery-event-selection.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"MoEngage did not retain delivered event {event_name!r}; current control is "
                f"{current!r} (screenshot={screenshot_path!r})"
            )

    async def _set_delivery_lookback(self, page: Page, days: int):
        delivery_pattern = re.compile(
            "|".join(re.escape(value) for value in DELIVERY_EVENTS.values()), re.I
        )
        nested_filter = page.locator(".mds-segmentation__nested-filter").filter(
            has_text=delivery_pattern
        ).first
        numeric_inputs = nested_filter.locator("input[type='number']")
        try:
            # The first number is the execution count (at least 1); the second
            # is the relative lookback window (formerly 30 days).
            lookback = numeric_inputs.nth(1)
            await lookback.wait_for(state="visible", timeout=10000)
            if "days" not in (await nested_filter.inner_text()).casefold():
                raise BrowserAutomationError(
                    "The delivered-event lookback unit is not set to days"
                )
            if await lookback.input_value() != str(days):
                await lookback.fill(str(days))
                await lookback.press("Tab")
                await page.wait_for_timeout(500)
            # Re-resolve after React updates the nested filter.
            nested_filter = page.locator(".mds-segmentation__nested-filter").filter(
                has_text=delivery_pattern
            ).first
            retained = await nested_filter.locator("input[type='number']").nth(1).input_value()
            if retained != str(days):
                raise BrowserAutomationError(
                    f"MoEngage retained a {retained}-day delivery window instead of {days} days"
                )
        except BrowserAutomationError:
            raise
        except Exception as exc:
            screenshot_path = self._diagnostic_path("moengage-delivery-lookback.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not set the delivered-event lookback to {days} days "
                f"(screenshot={screenshot_path!r})"
            ) from exc

    async def _set_campaign_id(self, page: Page, campaign_id: str):
        # The recorded workflow opens the editor immediately before setting the
        # delivered event and campaign id. Calling the toggle helper a second
        # time here can race the header animation and collapse the section.
        value_control = await self._reset_campaign_attribute(page)
        # _ensure_filter_editor_open above is the single source of truth for the
        # section state. Re-reading the animated header icon here can briefly
        # report its previous value and toggle the section closed again.
        trigger = value_control.locator(".mds-dropdown__trigger").first
        is_open = await page.locator(".mds-dropdown__popup:visible").count() > 0
        if await trigger.count() and not is_open:
            # The parent dropdown is keyboard-focusable. Opening it with Enter
            # avoids the nested-filter overlay that captures coordinate clicks.
            await value_control.focus()
            await value_control.press("Enter")
            await page.wait_for_timeout(300)
            if not await page.locator(".mds-dropdown__popup:visible").count():
                await value_control.press("Space")
                await page.wait_for_timeout(300)
            if not await page.locator(".mds-dropdown__popup:visible").count():
                await value_control.press("ArrowDown")
                await page.wait_for_timeout(300)
        elif not await trigger.count():
            await value_control.click(force=True)
        try:
            await self._select_open_option(page, campaign_id)
        except Exception as exc:
            screenshot_path = self._diagnostic_path("moengage-campaign-id-option.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not select campaign id {campaign_id!r} "
                f"(screenshot={screenshot_path!r})"
            ) from exc
        await page.wait_for_timeout(400)
        selected_text = (await value_control.inner_text()).strip()
        if campaign_id.casefold() not in selected_text.casefold():
            screenshot_path = self._diagnostic_path("moengage-campaign-id-selection.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"MoEngage did not retain campaign id {campaign_id!r}; current control is "
                f"{selected_text!r} (screenshot={screenshot_path!r})"
            )

    async def _reset_campaign_attribute(self, page: Page):
        """Replace stale campaign-name/id constraints with one empty ID filter."""
        delivery_pattern = re.compile(
            "|".join(re.escape(value) for value in DELIVERY_EVENTS.values()), re.I
        )
        nested_filter = page.locator(".mds-segmentation__nested-filter").filter(
            has_text=delivery_pattern
        ).first
        campaign_attribute = page.locator(
            ".mds-attr__name .mds-dropdown__trigger__inner__single--value"
        ).filter(has_text=re.compile(r"^\s*(?:Readable Campaign Id|Campaign Name)\s*$", re.I))
        attributes = nested_filter.locator(".mds-attr:visible").filter(has=campaign_attribute)
        removed = 0
        while await attributes.count():
            attribute = attributes.last
            delete_button = attribute.locator("[data-test='delete-button']").first
            if not await delete_button.count() or not await delete_button.is_visible():
                screenshot_path = self._diagnostic_path("moengage-campaign-id-clear.png")
                await page.screenshot(path=screenshot_path, full_page=True)
                raise BrowserAutomationError(
                    "Could not clear the existing Readable Campaign Id filter "
                    f"(screenshot={screenshot_path!r})"
                )
            await delete_button.dispatch_event("mousedown")
            await delete_button.dispatch_event("mouseup")
            await delete_button.dispatch_event("click")
            try:
                await attribute.wait_for(state="detached", timeout=5000)
            except Exception as exc:
                screenshot_path = self._diagnostic_path("moengage-campaign-id-clear.png")
                await page.screenshot(path=screenshot_path, full_page=True)
                raise BrowserAutomationError(
                    "MoEngage did not clear the existing Readable Campaign Id filter "
                    f"(screenshot={screenshot_path!r})"
                ) from exc
            removed += 1
            if removed > 10:
                raise BrowserAutomationError(
                    "MoEngage returned too many Readable Campaign Id filters while clearing"
                )
            attributes = nested_filter.locator(".mds-attr:visible").filter(has=campaign_attribute)

        await self._ensure_campaign_attribute(page)
        fresh_attribute = nested_filter.locator(".mds-attr:visible").filter(
            has_text="Readable Campaign Id"
        ).last
        value_control = fresh_attribute.locator(
            ".mds-attr__value .mds-dropdown"
        ).first
        try:
            await value_control.wait_for(state="visible", timeout=10000)
        except Exception as exc:
            screenshot_path = self._diagnostic_path("moengage-campaign-id-control.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                "Could not create a fresh Readable Campaign Id value control "
                f"(screenshot={screenshot_path!r})"
            ) from exc
        return value_control

    async def _ensure_campaign_attribute(self, page: Page):
        delivery_pattern = re.compile(
            "|".join(re.escape(value) for value in DELIVERY_EVENTS.values()), re.I
        )
        nested_filter = page.locator(".mds-segmentation__nested-filter").filter(
            has_text=delivery_pattern
        ).first
        campaign_name = page.locator(
            ".mds-attr__name .mds-dropdown__trigger__inner__single--value"
        ).filter(has_text=re.compile(r"^\s*Readable Campaign Id\s*$", re.I))
        visible_attribute = nested_filter.locator(".mds-attr:visible").filter(has=campaign_name).first
        if await visible_attribute.count():
            return
        add_attribute = nested_filter.locator("[data-test='attribute-add-btn']").first
        try:
            await add_attribute.wait_for(state="visible", timeout=10000)
            await add_attribute.dispatch_event("mousedown")
            await add_attribute.dispatch_event("mouseup")
            await add_attribute.dispatch_event("click")
            await page.wait_for_timeout(400)
            await self._ensure_filter_editor_open(page)
            attribute_name = nested_filter.locator(".mds-attr__name .mds-dropdown:visible").last
            await attribute_name.wait_for(state="visible", timeout=10000)
            popup_id = (await attribute_name.get_attribute("id")).replace("trigger_", "popup_", 1)
            if not await page.locator(f'[id="{popup_id}"]:visible').count():
                attribute_trigger = attribute_name.locator(".mds-dropdown__trigger").first
                await attribute_trigger.dispatch_event("mousedown")
                await attribute_trigger.dispatch_event("mouseup")
                await attribute_trigger.dispatch_event("click")
            await self._select_open_option(page, "Readable Campaign Id", allow_create=False)
            await visible_attribute.wait_for(state="visible", timeout=10000)
            try:
                await page.locator(".mds-dropdown__popup:visible").wait_for(
                    state="visible", timeout=3000
                )
            except Exception:
                pass
        except Exception as exc:
            screenshot_path = self._diagnostic_path("moengage-readable-campaign-attribute.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not add the Readable Campaign Id attribute "
                f"(screenshot={screenshot_path!r})"
            ) from exc

    async def _set_behavior_options(self, page: Page, row: CampaignRow, plan: BehaviorQueryPlan):
        analysis = page.locator(".mds-dropdown:visible").filter(
            has_text=re.compile(r"^(Unique users|Aggregation)", re.I)
        ).first
        await self._set_analysis_type(page, analysis, plan.analysis_type)
        if plan.aggregation:
            await page.wait_for_timeout(500)
            operator = page.locator(".operators-wrapper .mds-dropdown:visible").first
            attribute = page.locator(".attribute-wrapper .mds-dropdown:visible").first
            await self._set_titled_dropdown_control(page, operator, plan.aggregation)
            await self._set_dropdown_control(page, attribute, plan.aggregation_attribute)
        await self._set_duration(page, row.start_date.isoformat(), row.end_date.isoformat())

    async def _set_daily_granularity(self, page: Page):
        candidates = page.get_by_text("Daily", exact=True)
        for index in range(await candidates.count()):
            candidate = candidates.nth(index)
            if await candidate.is_visible():
                await candidate.click()
                await page.wait_for_timeout(400)
                return
        screenshot_path = self._diagnostic_path("moengage-daily-granularity.png")
        await page.screenshot(path=screenshot_path, full_page=True)
        raise BrowserAutomationError(
            "Could not select Daily granularity in the MoEngage behavior chart "
            f"(screenshot={screenshot_path!r})"
        )

    async def _set_analysis_type(self, page: Page, dropdown, value: str):
        await self._set_titled_dropdown_control(page, dropdown, value)
        selected = page.get_by_text(
            re.compile(rf"Analysis for\s+{re.escape(value)}\s+between", re.I)
        ).first
        try:
            await selected.wait_for(state="visible", timeout=5000)
        except Exception as exc:
            screenshot_path = self._diagnostic_path("moengage-analysis-selection.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"MoEngage analysis type did not change to {value!r} "
                f"(screenshot={screenshot_path!r})"
            ) from exc

    async def _set_titled_dropdown_control(self, page: Page, dropdown, value: str):
        """Set a MoEngage dropdown through its exact, stable option title."""
        try:
            await dropdown.wait_for(state="visible", timeout=10000)
        except Exception as exc:
            screenshot_path = self._diagnostic_path(f"moengage-dropdown-{value.replace(' ', '-')}.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not find the MoEngage dropdown for {value!r} (screenshot={screenshot_path!r})"
            ) from exc
        selected_value = dropdown.locator(".mds-dropdown__trigger__inner__single--value").first
        if (await selected_value.count()
                and value.casefold() == (await selected_value.inner_text()).strip().casefold()):
            return
        trigger = dropdown.locator(".mds-dropdown__trigger").first
        await trigger.scroll_into_view_if_needed()
        await trigger.click(force=True)
        option = page.locator(
            f'.mds-dropdown__popup__list__item[title="{value}"]:visible'
        ).last
        try:
            await option.wait_for(state="visible", timeout=5000)
            await option.click()
        except Exception as exc:
            screenshot_path = self._diagnostic_path(f"moengage-option-{value.replace(' ', '-')}.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not select MoEngage option {value!r} (screenshot={screenshot_path!r})"
            ) from exc
        await page.wait_for_timeout(500)

    async def _set_dropdown_control(self, page: Page, dropdown, value: str):
        try:
            await dropdown.wait_for(state="visible", timeout=10000)
        except Exception as exc:
            screenshot_path = self._diagnostic_path(f"moengage-dropdown-{value.replace(' ', '-')}.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not find the MoEngage dropdown for {value!r} (screenshot={screenshot_path!r})"
            ) from exc
        if value in (await dropdown.inner_text()):
            return
        trigger = dropdown.locator(".mds-dropdown__trigger").first
        await trigger.scroll_into_view_if_needed()
        await trigger.click(force=True)
        await self._select_open_option(page, value)
        await page.wait_for_timeout(400)

        current = page.locator(".attribute-wrapper .mds-dropdown:visible").first if value == "Order_Net_Val" else dropdown
        selected_text = (await current.inner_text()).strip()
        if value.casefold() not in selected_text.casefold():
            screenshot_path = self._diagnostic_path(f"moengage-selection-{value.replace(' ', '-')}.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"MoEngage did not retain selection {value!r}; current control is "
                f"{selected_text!r} (screenshot={screenshot_path!r})"
            )

    async def _set_duration(self, page: Page, start_iso: str, end_iso: str):
        start = date.fromisoformat(start_iso)
        end = date.fromisoformat(end_iso)
        expected_start = start.strftime("%d %b %Y")
        expected_end = end.strftime("%d %b %Y")
        label = page.get_by_text("Duration", exact=True).last
        duration = label.locator("xpath=following::input[1]").first
        actual = await duration.input_value()
        if actual == f"{expected_start} - {expected_end}":
            return

        # Close attribute menus before opening the calendar's real UI.
        await label.dispatch_event("click")
        await duration.evaluate("el => el.scrollIntoView({block: 'center'})")
        await duration.click()
        calendar = page.locator(".mds-calender__container:visible").last
        await calendar.wait_for(state="visible", timeout=10000)
        await calendar.get_by_text(re.compile(r"^Custom range$", re.I)).click()

        for target in (start, end):
            target_month = target.strftime("%b %Y")
            months = calendar.locator(".mds-calender__month")
            month = months.filter(
                has=page.locator(".mds-calender__month__header > span").filter(
                    has_text=re.compile(rf"^\s*{re.escape(target_month)}\s*$")
                )
            ).first
            for _ in range(24):
                if await month.count():
                    break
                first_heading = calendar.locator(".mds-calender__month__header > span").first
                current = datetime.strptime((await first_heading.inner_text()).strip(), "%b %Y")
                delta = -1 if (target.year, target.month) < (current.year, current.month) else 1
                direction = "previous" if delta < 0 else "next"
                navigation = calendar.locator(f".{direction} .month-arrow:not(.disabled)").first
                await navigation.dispatch_event("click")
                year, zero_month = divmod(current.year * 12 + current.month - 1 + delta, 12)
                next_month = date(year, zero_month + 1, 1).strftime("%b %Y")
                await first_heading.filter(
                    has_text=re.compile(rf"^\s*{re.escape(next_month)}\s*$")
                ).wait_for(timeout=5000)
            else:
                raise BrowserAutomationError(f"Could not navigate the calendar to {target_month}")
            day = month.locator(
                ".mds-calender__month__dates__date"
                ":not(.mds-calender__month__dates__date--not-same-month)"
            ).filter(has_text=re.compile(rf"^\s*{target.day}\s*$")).first
            await day.dispatch_event("click")

        await calendar.get_by_role("button", name="Done", exact=True).click()
        await calendar.wait_for(state="hidden", timeout=5000)
        actual = await duration.input_value()
        if expected_start not in actual or expected_end not in actual:
            screenshot_path = self._diagnostic_path("moengage-duration-selection.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"MoEngage did not retain duration {expected_start!r} - {expected_end!r}; "
                f"current value is {actual!r} (screenshot={screenshot_path!r})"
            )

    @staticmethod
    async def _read_behavior_total(page: Page, row_label: str, expected_days: int) -> float:
        loading = page.get_by_text(re.compile("Please wait while the data loads", re.I))
        if await loading.count():
            await loading.first.wait_for(state="hidden", timeout=90000)
        pinned_row = page.locator("[role='row']").filter(
            has_text=re.compile(re.escape(row_label), re.I)
        ).first
        await pinned_row.wait_for(state="visible", timeout=90000)
        row_index = await pinned_row.get_attribute("row-index")
        grid = pinned_row.locator(
            "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' ag-root ')][1]"
        )
        if not row_index or not await grid.count():
            raise BrowserAutomationError("Could not identify the behavior-table result grid")
        viewport = grid.locator(".ag-body-horizontal-scroll-viewport").first
        if not await viewport.count():
            viewport = grid.locator(".ag-center-cols-viewport").first
        can_scroll = await viewport.count() > 0
        if can_scroll:
            await viewport.evaluate("el => { el.scrollLeft = 0; }")
            await page.wait_for_timeout(100)
        peer_rows = grid.locator(f"[role='row'][row-index='{row_index}']")
        numeric_cells = None
        for index in range(await peer_rows.count()):
            cells = peer_rows.nth(index).locator("[role='gridcell']")
            if await cells.count() >= 2:
                numeric_cells = cells
                break
        if numeric_cells is None:
            raise BrowserAutomationError(f"Could not read daily results for {row_label!r}")
        # Event labels may be pinned or inline. Only date-headed columns are
        # daily results; neither the label nor the selectable summary is a day.
        daily_header = re.compile(r"^\s*\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\s*$")
        daily_values = {}
        while True:
            headers = grid.locator(".ag-header-cell").filter(has_text=daily_header)
            date_columns = {
                await headers.nth(index).get_attribute("col-id")
                for index in range(await headers.count())
            }
            for index in range(await numeric_cells.count()):
                cell = numeric_cells.nth(index)
                column_id = await cell.get_attribute("col-id")
                if column_id not in date_columns:
                    continue
                if not column_id:
                    raise BrowserAutomationError("A behavior-table date has no column ID")
                value = MoEngageBrowserService._parse_number(await cell.inner_text())
                if column_id in daily_values and daily_values[column_id] != value:
                    raise BrowserAutomationError("MoEngage results changed while reading the table")
                daily_values[column_id] = value
            if not can_scroll:
                break
            moved = await viewport.evaluate("""el => {
                const previous = el.scrollLeft;
                el.scrollLeft = Math.min(
                    el.scrollWidth - el.clientWidth,
                    previous + Math.max(1, el.clientWidth * 0.8),
                );
                return el.scrollLeft > previous;
            }""")
            if not moved:
                break
            await page.wait_for_timeout(100)
        if len(daily_values) != expected_days:
            raise BrowserAutomationError(
                f"MoEngage returned {len(daily_values)} daily columns for a "
                f"{expected_days}-day range; incomplete results were not written"
            )
        return sum(daily_values.values())


    @staticmethod
    def _parse_number(value: str) -> float:
        cleaned = value.strip().replace(",", "").replace("₹", "").replace(" ", "")
        negative = cleaned.startswith("(") and cleaned.endswith(")")
        if negative:
            cleaned = cleaned[1:-1]
        match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d+)?|\.\d+))([kmb]?)", cleaned, re.I)
        if not match:
            raise BrowserAutomationError(f"MoEngage returned a non-numeric result: {value!r}")
        multiplier = {"": 1, "k": 1000, "m": 1000000, "b": 1000000000}[match[2].lower()]
        number = float(match[1]) * multiplier
        return -abs(number) if negative else number

