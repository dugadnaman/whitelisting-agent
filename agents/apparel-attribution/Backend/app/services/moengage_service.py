"""Apparel-only attribution using the captured MoEngage behavior HTTP contract."""
from __future__ import annotations

import asyncio
import math
import re
from dataclasses import replace
from datetime import datetime, timedelta
from collections.abc import Callable

import httpx

from app.config.settings import Settings
from app.models.report import CampaignMetrics, CampaignRow

APPAREL_ACCOUNT_ID = "678e128849349be3423d6fc6"
DELIVERY_EVENTS = {"WhatsApp": "MOE_WHATSAPP_DELIVERED", "SMS": "SMS_DELIVERED", "RCS": "MOE_RCS_DELIVERED"}
MAX_SAFE_INTEGER = 2**53 - 1


def finite_metric(value) -> bool:
    # Compare before converting: math.isfinite() can overflow on arbitrary JSON integers.
    return type(value) in (int, float) and -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER and math.isfinite(value)


class MoEngageError(RuntimeError):
    pass


class MoEngageAuthenticationError(MoEngageError):
    pass


def apparel_session() -> dict[str, str]:
    # Resolve afresh: Auth Sync can replace a session without restarting the app.
    from moengage_sync import get_moengage_config
    return get_moengage_config("apparel")


def attribute(name: str, *, data_type: str = "string", operator: str = "in", value=None, negate: bool = False) -> dict:
    result = {"data_type": data_type, "category": "default", "name": name,
              "filter_type": "action_attributes", "case_sensitive": False,
              "operator": operator, "negate": negate}
    if value is not None:
        result["value"] = value
    if data_type == "array_string":
        result["array_filter_type"] = "any_of"
    return result


def attribute_types(attributes: dict, name: str) -> list[str]:
    info = attributes.get(name)
    types = info.get("data_types") if isinstance(info, dict) else None
    if not isinstance(types, list) or not types or any(not isinstance(kind, str) for kind in types):
        raise MoEngageError(f"MoEngage returned invalid metadata for purchase attribute {name}")
    return types


def behavior_payload(row: CampaignRow, metric: str, sale_attributes: dict, brand_values: dict) -> dict:
    """Build one daily query; never inherit stale campaign or segment filters."""
    if row.campaign_type not in {"Online", "Offline"} or metric not in {"unique_users", "total_revenue"}:
        raise MoEngageError("Select an Online/Offline query and a supported attribution metric")
    if row.channel not in DELIVERY_EVENTS or not row.campaign_id.strip():
        raise MoEngageError("The campaign requires a supported channel and a nonempty readable campaign ID")
    if row.end_date < row.start_date:
        raise MoEngageError("The goal range ends before it starts")
    if "Txn_Channel" not in sale_attributes:
        raise MoEngageError(f"{row.brand}: Sale_Array has no Txn_Channel; a confirmed online/offline classification rule is required. No metrics were written.")
    if "string" not in attribute_types(sale_attributes, "Txn_Channel"):
        raise MoEngageError("Txn_Channel no longer matches the confirmed classification schema")
    filters = [attribute("Txn_Channel", operator="exists", negate=row.campaign_type == "Offline")]
    if row.brand.casefold() == "cis":
        if "Brand_PM" not in sale_attributes:
            raise MoEngageError("CIS requires the confirmed Brand_PM contains SP purchase filter")
        if "array_string" not in attribute_types(sale_attributes, "Brand_PM"):
            raise MoEngageError("CIS Brand_PM no longer matches the confirmed purchase filter schema")
        filters.append(attribute("Brand_PM", data_type="array_string", operator="contains", value="SP"))
    if row.brand.casefold() == "agipl":
        target = (row.attribution_brand or "").strip()
        value = next((value for brand, value in brand_values.items() if brand.casefold() == target.casefold()), None)
        if not target or target.casefold() == "agipl" or not value or "Txn_Brand" not in sale_attributes:
            raise MoEngageError("AGIPL requires a supported target brand and its Txn_Brand purchase attribute")
        types = attribute_types(sale_attributes, "Txn_Brand")
        if not any(kind in types for kind in ("string", "array_string")):
            raise MoEngageError("AGIPL Txn_Brand no longer matches the confirmed purchase filter schema")
        kind = "array_string" if "array_string" in types else "string"
        filters.append(attribute("Txn_Brand", data_type=kind, operator="contains", value=value))
    sale = {"filter_type": "actions", "action_name": "Sale_Array", "executed": True,
            "execution": {"type": "atleast", "count": 1},
            "attributes": {"filter_operator": "and", "filters": filters}}
    aggregation = {}
    if metric == "total_revenue":
        if "Order_Net_Val" not in sale_attributes:
            raise MoEngageError("Sale_Array is missing the Order_Net_Val revenue attribute")
        if "double" not in attribute_types(sale_attributes, "Order_Net_Val"):
            raise MoEngageError("Order_Net_Val no longer matches the confirmed numeric revenue schema")
        aggregation = {"operation": "sum", "attr": {"attr_type": "event", "column_name": "Order_Net_Val",
                       "data_types": ["double"], "encrypted": False, "pii": False,
                       "readable_name": "Order_Net_Val", "type": "_f"}, "percentile_value": -1}
    start, end = f"{row.start_date.isoformat()} 00:00:00", f"{row.end_date.isoformat()} 23:59:59"
    return {
        "chart_type": "line", "type": "behavior", "version": "2.0",
        "events": [{"id": "A", "actions": [{
            "c_at_trigger_seg_v2": {"included_filters": {"filter_operator": "and", "filters": [sale]}},
            "c_at_act_seg_v2": {"included_filters": {"filter_operator": "and", "filters": []}},
        }], "split_by": [], "aggregation": aggregation}],
        "segmentation": [{"filters": {"included_filters": {"filter_operator": "and", "filters": [{
            "action_name": DELIVERY_EVENTS[row.channel], "executed": True, "filter_type": "actions",
            "execution": {"count": 1, "type": "atleast"},
            "primary_time_range": {"type": "inTheLast", "value": 120, "value_type": "relative_past", "period_unit": "days"},
            "attributes": {"filter_operator": "and", "filters": [attribute("moe_campaign_id", value=[row.campaign_id])]},
        }]}}}],
        "timerange": {"start": start, "end": end, "startDate": start, "endDate": end,
                      "label": "Custom Range", "dt_label": "custom", "value": (row.end_date - row.start_date).days},
        "granularity": "d", "analysis_type": "users" if metric == "unique_users" else "aggregation",
        "distribution": {}, "count_type": "number", "chart_plot_type": "linear", "rolling_value": -1,
        "user_aggregation_type": "", "user_aggregation_percentile": -1,
        "user_attr_grouped_by": [], "chart_sort_type": "descending", "comparison_timerange": {},
    }


def daily_total(data: dict, row: CampaignRow, metric: str) -> float:
    """Preserve the existing daily-sum semantics; reject partial/duplicate/split results."""
    rows = data.get("data")
    if not isinstance(rows, list):
        raise MoEngageError("MoEngage returned no daily attribution results")
    expected = {row.start_date + timedelta(days=offset) for offset in range((row.end_date - row.start_date).days + 1)}
    seen = set()
    total = 0
    for item in rows:
        if not isinstance(item, dict):
            raise MoEngageError("MoEngage returned invalid daily attribution results")
        try:
            day = datetime.strptime(item["granularity"], "%Y/%m/%d").date()
        except (KeyError, TypeError, ValueError):
            raise MoEngageError("MoEngage returned an invalid attribution date") from None
        value = item.get("metric")
        if (day not in expected or day in seen or item.get("step") != "A"
                or item.get("splitby") != [] or item.get("grouped_by") != []
                or type(item.get("tseq")) is not int or item["tseq"] != 0
                or type(item.get("cseq")) is not int or item["cseq"] != 0
                or not finite_metric(value)
                or metric == "unique_users" and (value < 0 or value != int(value))):
            raise MoEngageError("MoEngage returned duplicate, unexpected or invalid daily attribution results")
        seen.add(day)
        total += int(value) if metric == "unique_users" else value
    if seen != expected or not finite_metric(total):
        raise MoEngageError("MoEngage returned an incomplete attribution date range; no metrics were written")
    return total


class MoEngageService:
    def __init__(self, settings: Settings, session_loader: Callable[[], dict] = apparel_session, transport=None):
        self.settings = settings
        self.session_loader = session_loader
        self.transport = transport

    def configured_brands(self) -> list[str]:
        return sorted(self.settings.moengage_ui_config.get("workspace_map", {}), key=str.casefold)

    def execution_configured(self) -> bool:
        return bool(self.configured_brands())

    def _client(self) -> httpx.AsyncClient:
        config = self.session_loader()
        base = config.get("base_url", "").rstrip("/")
        token, refresh = config.get("bearer_token", "").strip(), config.get("refresh_token", "").strip()
        if not re.fullmatch(r"https://dashboard(?:-\d+)?\.moengage\.com", base):
            raise MoEngageAuthenticationError("Configure Apparel's MoEngage dashboard URL in Settings → MoEngage")
        if not token or not refresh:
            raise MoEngageAuthenticationError("Connect Apparel Auth Sync or refresh the Apparel bearer token, refresh token and cookie in Settings → MoEngage")
        headers = {"authorization": token if token.lower().startswith("bearer ") else f"Bearer {token}",
                   "refreshtoken": refresh, "accept": "application/json", "content-type": "application/json",
                   "origin": base, "referer": base + "/v4/analytics/v2/behavior", "page": "analytics/v2/behavior"}
        if config.get("cookie"):
            headers["cookie"] = config["cookie"]
        if any(not value.isascii() or any(ord(char) < 32 or ord(char) == 127 for char in value) for value in headers.values()):
            raise MoEngageAuthenticationError("Apparel session headers are malformed; reconnect Auth Sync")
        return httpx.AsyncClient(base_url=base, headers=headers, timeout=httpx.Timeout(45, connect=10),
                                 follow_redirects=False, trust_env=False, transport=self.transport)

    async def _request(self, client, method: str, path: str, **kwargs) -> dict:
        try:
            response = await client.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise MoEngageError("MoEngage timed out. Query submission was not automatically repeated; no sheet metrics were written.") from None
        except httpx.HTTPError:
            raise MoEngageError("Cannot reach MoEngage for Apparel attribution") from None
        if response.status_code in (401, 403) or 300 <= response.status_code < 400:
            raise MoEngageAuthenticationError("Apparel MoEngage session expired; reconnect Apparel Auth Sync in Settings → MoEngage")
        if response.status_code == 429:
            raise MoEngageError("MoEngage rate limit reached; wait before running attribution again")
        if not response.is_success:
            raise MoEngageError(f"MoEngage rejected the attribution request (HTTP {response.status_code})")
        try:
            data = response.json()
        except ValueError:
            raise MoEngageError("MoEngage returned invalid JSON for attribution") from None
        if not isinstance(data, dict):
            raise MoEngageError("MoEngage returned an invalid attribution response")
        if "status" in data and not isinstance(data["status"], str):
            raise MoEngageError("MoEngage returned an invalid attribution status")
        if str(data.get("code")) in {"401", "403"}:
            raise MoEngageAuthenticationError("Apparel MoEngage session expired; reconnect Apparel Auth Sync")
        explicit_success = str(data.get("code")) == "200" and data.get("status") == "success"
        if data.get("loggedIn") is False and not explicit_success:
            raise MoEngageAuthenticationError("Apparel MoEngage login expired; reconnect Apparel Auth Sync")
        if data.get("success") is False or data.get("status") in {"failed", "failure", "error"} or str(data.get("code", 200)) != "200":
            raise MoEngageError("MoEngage could not complete the Apparel attribution request")
        return data

    async def _apps(self, client) -> list[dict]:
        result = await self._request(client, "GET", "/dash/auth/listApps")
        apps = result.get("data")
        if not isinstance(apps, list) or any(not isinstance(app, dict) for app in apps):
            raise MoEngageError("MoEngage returned invalid workspace metadata")
        authorized = [app for app in apps if app.get("account_id") == APPAREL_ACCOUNT_ID
                      and app.get("activated") is True and app.get("is_test") is False]
        if not authorized:
            raise MoEngageAuthenticationError("This MoEngage session has no active workspaces in the Apparel organization")
        if any(not isinstance(app.get("id"), str) or not re.fullmatch(r"[a-fA-F0-9]{24}", app["id"])
               or not isinstance(app.get("name"), str) or not app["name"].strip() for app in authorized):
            raise MoEngageError("MoEngage returned invalid Apparel workspace identities")
        if len({app["id"] for app in authorized}) != len(authorized) or len({app["name"] for app in authorized}) != len(authorized):
            raise MoEngageError("MoEngage returned duplicate Apparel workspace identities")
        return authorized

    async def status(self) -> tuple[str, str]:
        try:
            await self.ensure_authenticated()
        except MoEngageAuthenticationError as exc:
            return "disconnected", str(exc)
        except (MoEngageError, OSError, ValueError):
            return "disconnected", "Could not verify the Apparel MoEngage HTTP session; check Settings → MoEngage"
        return "connected", "Apparel MoEngage HTTP session verified; no hosted browser is required"

    async def ensure_authenticated(self) -> None:
        async with self._client() as client:
            await self._apps(client)

    async def _activate(self, client, row: CampaignRow) -> dict:
        apps = await self._apps(client)
        mapping = self.settings.moengage_ui_config.get("workspace_map", {})
        name = next((name for brand, name in mapping.items() if brand.casefold() == row.brand.casefold()), None)
        matches = [app for app in apps if app["name"] == name]
        if len(matches) != 1:
            raise MoEngageError(f"No authorized Apparel workspace is configured for {row.brand}")
        app = matches[0]
        switched = await self._request(client, "GET", "/dash/auth/changeApp", params={"sls_enabled": "true", "app_id": app["id"]})
        data = switched.get("data")
        if not isinstance(data, dict) or data.get("app_access_details") != "ALLOWED" or not isinstance(data.get("bearer"), str) or not data["bearer"]:
            raise MoEngageAuthenticationError("MoEngage did not authorize the selected Apparel workspace")
        token = data["bearer"]
        client.headers["authorization"] = token if token.lower().startswith("bearer ") else "Bearer " + token
        if data.get("refresh_token"):
            client.headers["refreshtoken"] = data["refresh_token"]
        profile = (await self._request(client, "GET", "/getLoggedInUserData", params={"api": 1})).get("data")
        if not isinstance(profile, dict) or profile.get("account_id") != APPAREL_ACCOUNT_ID or profile.get("dbName") != app["name"]:
            raise MoEngageError("MoEngage workspace identity did not match the selected Apparel brand")
        return app

    async def _query(self, client, row: CampaignRow, metric: str, attributes: dict) -> float:
        payload = behavior_payload(row, metric, attributes, self.settings.moengage_ui_config.get("agipl_attribution_brand_values", {}))
        submitted = await self._request(client, "POST", "/api/analytics/v4/behavior", json=payload)
        query_id = submitted.get("request_id")
        if not isinstance(query_id, str) or not re.fullmatch(r"[a-fA-F0-9]{24}", query_id):
            raise MoEngageError("MoEngage did not return a valid attribution query ID")
        async with asyncio.timeout(self.settings.moengage_query_timeout_seconds):
            while True:
                result = await self._request(client, "GET", f"/api/analytics/v4/query/{query_id}/status")
                state = result.get("status")
                if state == "SUCCESSFUL":
                    break
                if state not in {"PROCESSING", "QUEUED", "RECEIVED", "PENDING"}:
                    raise MoEngageError("MoEngage attribution query failed or returned an unknown state; no metrics were written")
                await asyncio.sleep(1)
            results = await self._request(client, "GET", f"/api/analytics/v4/query/{query_id}/results")
        return daily_total(results, row, metric)

    async def fetch_metrics(self, row: CampaignRow) -> CampaignMetrics:
        async with self._client() as client:
            await self._activate(client, row)
            metadata = await self._request(client, "POST", "/v1/segmentation/metadata/user-event-attrs", json={
                "action": "Sale_Array", "exclude_array_datatypes": False, "exclude_object_types": False, "include_meta_fields": True})
            attributes = metadata.get("attributes")
            if not isinstance(attributes, dict):
                raise MoEngageError("MoEngage returned invalid purchase attribute metadata")
            async def typed(kind):
                query_row = replace(row, campaign_type=kind)
                users = await self._query(client, query_row, "unique_users", attributes)
                revenue = await self._query(client, query_row, "total_revenue", attributes)
                return self._typed_metrics(kind, users, revenue)
            try:
                if row.campaign_type == "Overall":
                    return self._combine_metrics(await typed("Online"), await typed("Offline"))
                return await typed(row.campaign_type)
            except TimeoutError:
                raise MoEngageError("MoEngage attribution query timed out; no metrics were written") from None

    @staticmethod
    def _typed_metrics(campaign_type: str, unique_users: float, revenue: float) -> CampaignMetrics:
        if (not finite_metric(unique_users) or unique_users < 0 or unique_users != int(unique_users)
                or not finite_metric(revenue)):
            raise MoEngageError("MoEngage returned invalid customer or revenue metrics")
        users, revenue = int(unique_users), round(float(revenue), 2)
        if (users == 0) != (revenue == 0):
            raise MoEngageError("MoEngage returned inconsistent customer/revenue metrics; no metrics were written")
        if campaign_type == "Online":
            return CampaignMetrics(users, revenue, online_unique_users=users, online_revenue=revenue)
        if campaign_type == "Offline":
            return CampaignMetrics(users, revenue, offline_unique_users=users, offline_revenue=revenue)
        raise MoEngageError(f"Unsupported campaign type {campaign_type!r}")

    @staticmethod
    def _combine_metrics(online: CampaignMetrics, offline: CampaignMetrics) -> CampaignMetrics:
        if not finite_metric(online.unique_users + offline.unique_users) or not finite_metric(online.total_revenue + offline.total_revenue):
            raise MoEngageError("Combined attribution metrics exceed supported numeric bounds")
        return CampaignMetrics(
            unique_users=online.unique_users + offline.unique_users,
            total_revenue=round(online.total_revenue + offline.total_revenue, 2),
            online_unique_users=online.online_unique_users, offline_unique_users=offline.offline_unique_users,
            online_revenue=online.online_revenue, offline_revenue=offline.offline_revenue,
        )
