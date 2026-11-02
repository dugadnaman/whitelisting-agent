"""Genuine MoEngage browser attribution; no API or fabricated-metric fallback."""
from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from pathlib import Path

from app.config.settings import Settings
from app.models.report import CampaignMetrics, CampaignRow
import os
from app.services.moengage_browser_service import BrowserAuthenticationError, MoEngageBrowserService


class MoEngageError(RuntimeError):
    pass


class MoEngageService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.active_profile = "default"
        self.browser = self._new_browser()

    def _new_browser(self):
        if self.settings.moengage_mode == "browser" and self.settings.moengage_remote_cdp_url:
            return MoEngageBrowserService(
                self.settings.storage_dir / "moengage-profile",
                self.settings.moengage_dashboard_url,
                self.settings.moengage_ui_config,
                self.settings.moengage_remote_cdp_url,
            )
        token = os.environ.get("APPAREL_MOENGAGE_BEARER_TOKEN") or os.environ.get("MOENGAGE_BEARER_TOKEN", "")
        refresh = os.environ.get("APPAREL_MOENGAGE_REFRESH_TOKEN") or os.environ.get("MOENGAGE_REFRESH_TOKEN", "")
        cookie = os.environ.get("APPAREL_MOENGAGE_COOKIE") or os.environ.get("MOENGAGE_COOKIE", "")
        try:
            from portal_sessions import load_session
            s = load_session("apparel", "moengage")
            if s:
                token = s.get("bearer_token") or token
                refresh = s.get("refresh_token") or refresh
                cookie = s.get("cookie") or cookie
        except Exception:
            pass
        from app.services.moengage_analytics_service import MoEngageAnalyticsService
        return MoEngageAnalyticsService(
            dashboard_url=self.settings.moengage_dashboard_url,
            ui_config=self.settings.moengage_ui_config,
            bearer_token=token,
            refresh_token=refresh,
            cookie=cookie,
        )

    def available_profiles(self) -> list[str]:
        return [self.active_profile]

    async def select_profile(self, profile_id: str | None) -> str:
        # One persistent corporate browser; a login hint never selects another tenant.
        self.active_profile = (profile_id or "default").strip().casefold()
        return self.active_profile

    async def reset_profile(self, profile_id: str | None) -> str:
        await self.select_profile(profile_id)
        await self.browser.reset_login()
        return self.active_profile

    def configured_brands(self) -> list[str]:
        mapping = self.settings.moengage_ui_config.get("query_url_map") or {}
        return sorted(mapping, key=str.casefold)

    def execution_configured(self) -> bool:
        if self.settings.moengage_mode == "browser" and self.settings.moengage_remote_cdp_url:
            return bool(self.configured_brands()
                        and self.settings.moengage_ui_config.get("workflow") in {"recorded_behavior", "analytics_api"})
        return bool(self.configured_brands())

    async def fetch_metrics(self, row: CampaignRow) -> CampaignMetrics:
        if not self.execution_configured():
            raise MoEngageError("Configure genuine MoEngage report mappings before running attribution")
        if row.campaign_type == "Overall":
            online = replace(row, campaign_type="Online")
            offline = replace(row, campaign_type="Offline")
            online_users = await self._browser_query_metric(online, "unique_users")
            offline_users = await self._browser_query_metric(offline, "unique_users")
            online_revenue = await self._browser_query_metric(online, "total_revenue")
            offline_revenue = await self._browser_query_metric(offline, "total_revenue")
            return self._combine_metrics(
                self._typed_metrics("Online", online_users, online_revenue),
                self._typed_metrics("Offline", offline_users, offline_revenue),
            )
        users = await self._browser_query_metric(row, "unique_users")
        revenue = await self._browser_query_metric(row, "total_revenue")
        return self._typed_metrics(row.campaign_type, users, revenue)

    async def wait_until_ready(self, timeout_seconds: float = 90.0) -> None:
        await self.browser.wait_until_ready(timeout_seconds=timeout_seconds)

    async def ensure_authenticated(self, timeout_seconds: float = 90.0) -> None:
        if not self.execution_configured():
            raise MoEngageError("Configure genuine MoEngage report mappings before running attribution")
        await self.browser.wait_until_ready(timeout_seconds=timeout_seconds)
        status, message = await self.browser.status()
        if status != "connected":
            raise BrowserAuthenticationError(
                f"{message} No campaign rows were processed. Ask an Apparel administrator to complete browser login."
            )

    async def _browser_query_metric(self, row: CampaignRow, metric: str) -> float:
        timeout = self.settings.moengage_browser_query_timeout_seconds
        try:
            return await asyncio.wait_for(self.browser.query_metric(row, metric), timeout=timeout)
        except TimeoutError as exc:
            try:
                await asyncio.wait_for(self.browser.recover(), timeout=30)
            except Exception:
                await self.browser.close()
            raise MoEngageError(
                f"MoEngage {metric} query timed out after {int(timeout)} seconds for sheet row {row.excel_row}; the browser tab was reset"
            ) from exc

    @staticmethod
    def _typed_metrics(campaign_type: str, unique_users: float, revenue: float) -> CampaignMetrics:
        users = int(unique_users)
        total_revenue = round(float(revenue), 2)
        if (users == 0) != (total_revenue == 0):
            raise MoEngageError(
                "MoEngage returned inconsistent attribution metrics: "
                f"unique_users={users}, revenue={total_revenue}. "
                "The campaign was not written to Google Sheets; retry it after the MoEngage query finishes refreshing."
            )
        if campaign_type == "Online":
            return CampaignMetrics(users, total_revenue, online_unique_users=users, online_revenue=total_revenue)
        if campaign_type == "Offline":
            return CampaignMetrics(users, total_revenue, offline_unique_users=users, offline_revenue=total_revenue)
        raise MoEngageError(f"Unsupported campaign type {campaign_type!r}")

    @staticmethod
    def _combine_metrics(online: CampaignMetrics, offline: CampaignMetrics) -> CampaignMetrics:
        online_users = online.online_unique_users or 0
        offline_users = offline.offline_unique_users or 0
        online_revenue = online.online_revenue or 0.0
        offline_revenue = offline.offline_revenue or 0.0
        return CampaignMetrics(
            unique_users=online_users + offline_users,
            total_revenue=round(online_revenue + offline_revenue, 2),
            online_unique_users=online_users,
            offline_unique_users=offline_users,
            online_revenue=online_revenue,
            offline_revenue=offline_revenue,
        )
