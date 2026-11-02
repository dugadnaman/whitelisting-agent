"""Unit tests for MoEngageAnalyticsService."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock
import httpx
import pytest

import sys
from pathlib import Path
backend_dir = Path(__file__).resolve().parent.parent / "agents" / "apparel-attribution" / "Backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.models.report import CampaignRow
from app.services.moengage_analytics_service import MoEngageAnalyticsService, MoEngageAnalyticsError


@pytest.fixture
def mock_ui_config():
    return {
        "workspace_map": {
            "Aldo": "AL_IN",
            "CIS": "AL_IN",
            "R&B": "RB_IN",
            "AGIPL": "AGIPL_Master_DB",
        },
        "query_url_map": {
            "Aldo": "https://dashboard-03.moengage.com/v4/analytics/v2/behavior?did=did_aldo&chartId=cid_aldo",
            "CIS": "https://dashboard-03.moengage.com/v4/analytics/v2/behavior?did=did_aldo&chartId=cid_cis",
            "R&B": "https://dashboard-03.moengage.com/v4/analytics/v2/behavior?did=did_rb&chartId=cid_rb",
            "AGIPL": "https://dashboard-03.moengage.com/v4/analytics/v2/behavior?did=did_agipl&chartId=cid_agipl",
        },
        "agipl_attribution_brand_values": {
            "AL": "AL",
            "VS": "VS",
            "CK": "CK",
        },
    }


def make_row(**overrides):
    base = {
        "excel_row": 2,
        "campaign_date": date(2026, 10, 1),
        "brand": "R&B",
        "channel": "WhatsApp",
        "campaign_type": "Online",
        "campaign_id": "cmp_12345",
        "campaign_name": "Test Campaign",
        "tracking_goal": "Goal",
        "start_date": date(2026, 10, 1),
        "end_date": date(2026, 10, 3),
    }
    base.update(overrides)
    return CampaignRow(**base)


@pytest.mark.asyncio
async def test_status_disconnected_when_no_token(mock_ui_config):
    svc = MoEngageAnalyticsService("https://dashboard-03.moengage.com", mock_ui_config, bearer_token="")
    status, msg = await svc.status()
    assert status == "waiting_for_login"


@pytest.mark.asyncio
async def test_query_metric_success_flow(mock_ui_config):
    calls = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append({"method": request.method, "url": url})

        if "/dash/auth/listApps" in url:
            return httpx.Response(200, json={"data": [{"name": "RB_IN", "id": "app_rb"}]})
        if "/dash/auth/changeApp" in url:
            return httpx.Response(200, json={"data": {"bearer": "token_rb"}})
        if "/filters?api=1" in url:
            return httpx.Response(200, json={"data": {
                "events": [{"actions": [{"c_at_trigger_seg_v2": {"included_filters": {"filters": [{}]}}}]}],
            }})
        if request.method == "PUT" and "/charts/cid_rb" in url:
            return httpx.Response(200, json={"status": "success"})
        if request.method == "POST" and "/charts/cid_rb" in url:
            return httpx.Response(200, json={"request_id": "req_999"})
        if "/api/analytics/v4/query/req_999/status" in url:
            return httpx.Response(200, json={"status": "SUCCESSFUL"})
        if "/api/analytics/v4/query/req_999/results" in url:
            return httpx.Response(200, json={"data": [
                {"granularity": "2026/10/01", "metric": 50.0},
                {"granularity": "2026/10/02", "metric": 75.0},
            ]})
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://dashboard-03.moengage.com")

    svc = MoEngageAnalyticsService(
        "https://dashboard-03.moengage.com",
        mock_ui_config,
        bearer_token="initial_token",
        client=client,
    )

    row = make_row(brand="R&B", campaign_type="Online")
    val = await svc.query_metric(row, "unique_users")
    assert val == 125.0

    # Ensure token switching occurred
    assert any("/dash/auth/changeApp" in c["url"] for c in calls)
    assert any("/api/analytics/v4/query/req_999/results" in c["url"] for c in calls)


@pytest.mark.asyncio
async def test_cis_brand_condition_applied(mock_ui_config):
    put_body = None

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal put_body
        url = str(request.url)
        if "/dash/auth/listApps" in url:
            return httpx.Response(200, json={"data": [{"name": "AL_IN", "id": "app_al"}]})
        if "/dash/auth/changeApp" in url:
            return httpx.Response(200, json={"data": {"bearer": "token_al"}})
        if "/filters?api=1" in url:
            return httpx.Response(200, json={"data": {
                "events": [{"actions": [{"c_at_trigger_seg_v2": {"included_filters": {"filters": [{}]}}}]}],
            }})
        if request.method == "PUT":
            import json
            put_body = json.loads(request.content)
            return httpx.Response(200, json={"status": "success"})
        if request.method == "POST":
            return httpx.Response(200, json={"request_id": "req_cis"})
        if "/status" in url:
            return httpx.Response(200, json={"status": "SUCCESSFUL"})
        if "/results" in url:
            return httpx.Response(200, json={"data": [{"metric": 10.0}]})
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://dashboard-03.moengage.com")
    svc = MoEngageAnalyticsService("https://dashboard-03.moengage.com", mock_ui_config, bearer_token="init", client=client)

    row = make_row(brand="CIS", campaign_type="Offline")
    await svc.query_metric(row, "total_revenue")

    assert put_body is not None
    filters = put_body["events"][0]["actions"][0]["c_at_trigger_seg_v2"]["included_filters"]["filters"][0]["attributes"]["filters"]
    # Txn_Channel should be negated for Offline
    txn_channel = next(f for f in filters if f["name"] == "Txn_Channel")
    assert txn_channel["negate"] is True
    # CIS Brand_PM SP filter
    brand_pm = next(f for f in filters if f["name"] == "Brand_PM")
    assert brand_pm["value"] == "SP"
