import sys
from pathlib import Path
worker_dir = Path(__file__).resolve().parent.parent / "agents" / "apparel-attribution" / "Backend"
if str(worker_dir) not in sys.path:
    sys.path.insert(0, str(worker_dir))

"""Integration tests for in-process Apparel attribution execution."""

import pytest
from fastapi.testclient import TestClient

from api import app

client = TestClient(app)

from unittest.mock import patch, AsyncMock


def test_inprocess_health_endpoint(provision_user, monkeypatch):
    monkeypatch.delenv("APPAREL_ATTRIBUTION_WORKER_URL", raising=False)
    monkeypatch.delenv("APPAREL_ATTRIBUTION_TOKEN", raising=False)

    user, headers = provision_user(tenant="apparel")
    client.headers.update(headers)

    with patch("app.services.moengage_analytics_service.MoEngageAnalyticsService.status", new_callable=AsyncMock) as mock_status:
        mock_status.return_value = ("connected", "Mock connected")
        res = client.get("/api/apparel/attribution/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["worker_configured"] is True
        assert "configured_brands" in data
def test_inprocess_google_config_endpoint(provision_user, monkeypatch):
    monkeypatch.delenv("APPAREL_ATTRIBUTION_WORKER_URL", raising=False)
    monkeypatch.delenv("APPAREL_ATTRIBUTION_TOKEN", raising=False)

    user, headers = provision_user(tenant="apparel")
    client.headers.update(headers)

    res = client.get("/api/apparel/attribution/google/config")
    assert res.status_code == 200
    data = res.json()
    assert "configured" in data
    assert "spreadsheet_url" in data
    assert "worksheet_name" in data


def test_inprocess_moengage_session_endpoint(provision_user, monkeypatch):
    monkeypatch.delenv("APPAREL_ATTRIBUTION_WORKER_URL", raising=False)
    monkeypatch.delenv("APPAREL_ATTRIBUTION_TOKEN", raising=False)

    user, headers = provision_user(tenant="apparel")
    client.headers.update(headers)

    res = client.get("/api/apparel/attribution/moengage/session")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("connected", "waiting_for_login", "disconnected")
    assert "profile_id" in data
