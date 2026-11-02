from __future__ import annotations

import asyncio
import contextlib
import logging

from typing import Any

import httpx


from app.models.report import CampaignRow

logger = logging.getLogger(__name__)

DELIVERY_ACTION_MAP = {
    "WhatsApp": "MOE_WHATSAPP_DELIVERED",
    "SMS": "SMS_DELIVERED",
    "RCS": "MOE_RCS_DELIVERED",
}


class MoEngageAnalyticsError(RuntimeError):
    pass


class MoEngageAnalyticsService:
    def __init__(
        self,
        dashboard_url: str,
        ui_config: dict[str, Any],
        bearer_token: str = "",
        refresh_token: str = "",
        cookie: str = "",
        client: httpx.AsyncClient | None = None,
    ):
        self.dashboard_url = dashboard_url.rstrip("/")
        self.ui = ui_config
        self.bearer_token = bearer_token
        self.refresh_token = refresh_token
        self.cookie = cookie
        self._external_client = client
        self._cached_workspace_tokens: dict[str, str] = {}
        self.active_workspace: str | None = None
        self._lock = asyncio.Lock()

    def _client(self) -> httpx.AsyncClient:
        if self._external_client:
            return self._external_client
        return httpx.AsyncClient(
            base_url=self.dashboard_url,
            timeout=httpx.Timeout(connect=10.0, read=90.0, write=15.0, pool=10.0),
            follow_redirects=False,
        )

    async def close(self) -> None:
        self._cached_workspace_tokens.clear()

    async def reset_login(self) -> None:
        self._cached_workspace_tokens.clear()

    async def start_login(self, profile_id: str = "default") -> str:
        return "Open MoEngage in Chrome and connect with Auth Sync."

    async def recover(self) -> None:
        self._cached_workspace_tokens.clear()

    def _auth_headers(self, token: str | None = None) -> dict[str, str]:
        t = (token or self.bearer_token or "").strip()
        auth_val = t if t.lower().startswith("bearer ") else f"Bearer {t}"
        headers = {
            "Authorization": auth_val,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": self.dashboard_url,
        }
        if self.refresh_token:
            headers["refreshtoken"] = self.refresh_token
        if self.cookie:
            headers["Cookie"] = self.cookie
        return headers

    async def status(self) -> tuple[str, str]:
        if not self.bearer_token:
            return "waiting_for_login", "No MoEngage session saved. Connect Auth Sync or configure APPAREL_MOENGAGE_BEARER_TOKEN."
        try:
            client = self._client()
            async with (client if not self._external_client else contextlib.nullcontext(client)) as http:
                res = await http.get("/dash/auth/listApps?sls_enabled=true", headers=self._auth_headers())
                if res.status_code == 200 and res.json().get("data"):
                    return "connected", "MoEngage Analytics API connected."
                if res.status_code in (401, 403) or not res.is_success:
                    return "waiting_for_login", "MoEngage session expired. Reconnect Auth Sync."
                return "connected", "MoEngage Analytics API connected."
        except Exception as exc:
            logger.warning("MoEngage session probe error: %s", exc)
            return "disconnected", f"Cannot reach MoEngage dashboard: {exc}"

    async def wait_until_ready(self, timeout_seconds: float = 30.0) -> None:
        status, message = await self.status()
        if status != "connected":
            raise MoEngageAnalyticsError(message)

    async def _resolve_workspace_token(self, http: httpx.AsyncClient, workspace_name: str) -> str:
        if workspace_name in self._cached_workspace_tokens:
            return self._cached_workspace_tokens[workspace_name]

        res = await http.get("/dash/auth/listApps?sls_enabled=true", headers=self._auth_headers())
        if not res.is_success:
            raise MoEngageAnalyticsError(f"MoEngage listApps failed with status {res.status_code}")
        apps = res.json().get("data", [])
        target = next((a for a in apps if a.get("name") == workspace_name or a.get("id") == workspace_name), None)
        if not target:
            raise MoEngageAnalyticsError(f"Workspace {workspace_name!r} not found in MoEngage organization.")

        change_res = await http.get(
            f"/dash/auth/changeApp?sls_enabled=true&app_id={target['id']}",
            headers=self._auth_headers(),
        )
        if not change_res.is_success:
            raise MoEngageAnalyticsError(f"MoEngage changeApp to {workspace_name} failed: {change_res.text[:200]}")
        data = change_res.json()
        token = data.get("data", {}).get("bearer")
        if not token:
            raise MoEngageAnalyticsError(f"MoEngage did not return bearer token for workspace {workspace_name}")

        self._cached_workspace_tokens[workspace_name] = token
        return token

    def _brand_chart_info(self, brand: str) -> tuple[str, str, str]:
        """Return (workspace_name, did, chart_id) for brand."""
        workspace_map = self.ui.get("workspace_map", {})
        query_map = self.ui.get("query_url_map", {})

        ws = next((v for k, v in workspace_map.items() if k.casefold() == brand.casefold()), None)
        query_url = next((v for k, v in query_map.items() if k.casefold() == brand.casefold()), None)

        if not ws:
            raise MoEngageAnalyticsError(f"No MoEngage workspace mapping configured for brand {brand!r}")
        if not query_url:
            raise MoEngageAnalyticsError(f"No MoEngage behavior URL configured for brand {brand!r}")

        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(query_url)
        params = parse_qs(parsed.query)
        did = params.get("did", [None])[0]
        chart_id = params.get("chartId", [None])[0]

        if not did or not chart_id:
            raise MoEngageAnalyticsError(f"Configured query URL for {brand} lacks did or chartId parameter: {query_url}")

        return ws, did, chart_id

    async def query_metric(self, row: CampaignRow, metric: str) -> float:
        async with self._lock:
            ws_name, did, chart_id = self._brand_chart_info(row.brand)

            client = self._client()
            async with (client if not self._external_client else contextlib.nullcontext(client)) as http:
                ws_token = await self._resolve_workspace_token(http, ws_name)
                headers = self._auth_headers(ws_token)

                # 1. Fetch current baseline filters
                filter_res = await http.get(f"/api/analytics/v4/dashboards/{did}/charts/{chart_id}/filters?api=1", headers=headers)
                if not filter_res.is_success:
                    raise MoEngageAnalyticsError(f"Failed to fetch chart filters for {row.brand} (HTTP {filter_res.status_code}): {filter_res.text[:200]}")
                payload = filter_res.json().get("data")
                if not payload:
                    raise MoEngageAnalyticsError(f"Empty chart filter definition returned for {row.brand}")

                # 2. Modify timerange
                start_str = f"{row.start_date.strftime('%Y-%m-%d')} 00:00:00"
                end_str = f"{row.end_date.strftime('%Y-%m-%d')} 23:59:59"
                days_span = max(1, (row.end_date - row.start_date).days + 1)
                payload["timerange"] = {
                    "dt_label": "custom",
                    "label": "Custom Range",
                    "start": start_str,
                    "startDate": start_str,
                    "end": end_str,
                    "endDate": end_str,
                    "value": days_span,
                }

                # 3. Modify delivery event segmentation filter
                delivery_action = DELIVERY_ACTION_MAP.get(row.channel, "MOE_WHATSAPP_DELIVERED")
                campaign_identifier = (row.campaign_id or "").strip()
                match_attribute = "moe_campaign_id"
                if not campaign_identifier:
                    campaign_identifier = (row.campaign_name or "").strip()
                    match_attribute = "moe_campaign_name"

                payload["segmentation"] = [
                    {
                        "filters": {
                          "included_filters": {
                            "filter_operator": "and",
                            "filters": [
                              {
                                "action_name": delivery_action,
                                "attributes": {
                                  "filter_operator": "and",
                                  "filters": [
                                    {
                                      "case_sensitive": False,
                                      "category": "default",
                                      "data_type": "string",
                                      "filter_type": "action_attributes",
                                      "name": match_attribute,
                                      "negate": False,
                                      "operator": "in",
                                      "value": [campaign_identifier],
                                    }
                                  ],
                                },
                                "executed": True,
                                "execution": {"count": 1, "type": "atleast"},
                                "filter_type": "actions",
                                "primary_time_range": {
                                  "period_unit": "days",
                                  "type": "inTheLast",
                                  "value": 120,
                                  "value_type": "relative_past",
                                },
                              }
                            ],
                          }
                        }
                    }
                ]

                # 4. Modify action attribute filters on Sale_Array
                # Online: Txn_Channel exists; Offline: Txn_Channel does not exist (negate=True)
                is_offline = row.campaign_type.casefold() == "offline"
                actions_list = payload.get("events", [{}])[0].get("actions", [{}])
                target_action = actions_list[0].get("c_at_trigger_seg_v2", {}).get("included_filters", {}).get("filters", [{}])[0]
                target_action["action_name"] = "Sale_Array"
                attr_filters = [
                    {
                        "case_sensitive": False,
                        "category": "default",
                        "data_type": "string",
                        "filter_type": "action_attributes",
                        "name": "Txn_Channel",
                        "negate": is_offline,
                        "operator": "exists",
                    }
                ]

                # CIS special brand condition: Brand_PM contains SP
                if row.brand.casefold() == "cis":
                    attr_filters.append(
                        {
                            "array_filter_type": "any_of",
                            "case_sensitive": False,
                            "category": "default",
                            "data_type": "array_string",
                            "filter_type": "action_attributes",
                            "name": "Brand_PM",
                            "negate": False,
                            "operator": "contains",
                            "value": "SP",
                        }
                    )
                # AGIPL special brand condition: Txn_Brand contains target_brand
                elif row.brand.casefold() == "agipl":
                    mapping = self.ui.get("agipl_attribution_brand_values", {})
                    target_brand = next((str(v) for k, v in mapping.items() if k.casefold() == (row.attribution_brand or "").casefold()), row.attribution_brand or "AL")
                    attr_filters.append(
                        {
                            "case_sensitive": False,
                            "category": "default",
                            "data_type": "string",
                            "filter_type": "action_attributes",
                            "name": "Txn_Brand",
                            "negate": False,
                            "operator": "contains",
                            "value": target_brand,
                        }
                    )

                target_action["attributes"] = {
                    "filter_operator": "and",
                    "filters": attr_filters,
                }

                # 5. Set analysis type & aggregation
                payload["did"] = did
                if metric == "unique_users":
                    payload["analysis_type"] = "users"
                    payload["events"][0]["aggregation"] = {}
                elif metric == "total_revenue":
                    payload["analysis_type"] = "aggregation"
                    payload["events"][0]["aggregation"] = {
                        "attr": {
                            "attr_type": "event",
                            "column_name": "Order_Net_Val",
                            "data_types": ["double"],
                            "encrypted": False,
                            "pii": False,
                            "readable_name": "Order_Net_Val",
                            "type": "_f",
                        },
                        "operation": "sum",
                        "percentile_value": -1,
                    }
                else:
                    raise MoEngageAnalyticsError(f"Unsupported metric: {metric!r}")

                # 6. Save updated chart filter definition
                put_res = await http.put(
                    f"/api/analytics/v4/dashboards/{did}/charts/{chart_id}",
                    headers=headers,
                    json=payload,
                )
                if not put_res.is_success:
                    raise MoEngageAnalyticsError(f"Failed to update chart filter for {row.brand}: {put_res.text[:200]}")

                # 7. Execute query (cache=false)
                post_res = await http.post(
                    f"/api/analytics/v4/dashboards/{did}/charts/{chart_id}?cache=false",
                    headers=headers,
                    json={},
                )
                if not post_res.is_success:
                    raise MoEngageAnalyticsError(f"Failed to execute query for {row.brand}: {post_res.text[:200]}")
                post_data = post_res.json()
                req_id = post_data.get("request_id")
                if not req_id:
                    raise MoEngageAnalyticsError(f"MoEngage did not return request_id: {post_data}")

                # 8. Poll for completion
                max_polls = 60
                status = "QUEUED"
                for _poll in range(max_polls):
                    await asyncio.sleep(1.5)
                    poll_res = await http.get(f"/api/analytics/v4/query/{req_id}/status", headers=headers)
                    if poll_res.is_success:
                        status = poll_res.json().get("status", "QUEUED")
                        if status == "SUCCESSFUL":
                            break
                        if status in ("FAILED", "FAILURE", "ERROR"):
                            raise MoEngageAnalyticsError(f"MoEngage query failed for {row.brand} ({req_id}): {poll_res.text[:200]}")

                if status != "SUCCESSFUL":
                    raise MoEngageAnalyticsError(f"MoEngage query timed out after {max_polls * 1.5}s for {row.brand} ({req_id})")

                # 9. Read results
                results_res = await http.get(f"/api/analytics/v4/query/{req_id}/results", headers=headers)
                if not results_res.is_success:
                    raise MoEngageAnalyticsError(f"Failed to fetch query results for {row.brand}: {results_res.text[:200]}")

                results_json = results_res.json()
                data_rows = results_json.get("data", [])
                if not isinstance(data_rows, list):
                    return 0.0

                total_val = sum(float(entry.get("metric", 0.0) or 0.0) for entry in data_rows if isinstance(entry, dict))
                return float(round(total_val, 2) if metric == "total_revenue" else int(total_val))
