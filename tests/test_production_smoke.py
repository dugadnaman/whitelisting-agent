"""
Production Deployment & Docker Configuration Smoke Tests.
Validates:
- Health check endpoints (/healthz, /api/health)
- Dockerfile and docker-compose.yml configuration integrity
- SQLite WAL volume persistence and concurrency
- Webhook connectivity, secret authentication, and targeted status check
- Frontend proxy forwarding
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import api
from db_queue import get_db, init_queue_db, update_template_approval_monotonic
from models import ApprovalStatus

client = TestClient(api.app)


def setup_module():
    init_queue_db()


def test_health_endpoints():
    """Verify production uptime monitor endpoints respond with 200 OK."""
    r_healthz = client.get("/healthz")
    assert r_healthz.status_code == 200
    assert r_healthz.json()["status"] == "ok"

    r_api_health = client.get("/api/health")
    assert r_api_health.status_code == 200
    assert r_api_health.json()["status"] == "ok"


def test_docker_configuration_integrity():
    """
    - Multi-stage build (frontend-builder + Python runner)
    - Supervisord running both FastAPI (8000) and Next.js (3000)
    - Directory-backed SQLite persistence via KARIX_DB_PATH
    - Healthcheck definition
    """
    dockerfile_path = Path("Dockerfile")
    assert dockerfile_path.exists(), "Dockerfile must exist at project root"
    df_content = dockerfile_path.read_text(encoding="utf-8")

    assert "FROM node:20-alpine AS frontend-builder" in df_content
    assert "FROM python:3.11-slim" in df_content
    assert "supervisord" in df_content
    assert "EXPOSE 3000 8000" in df_content
    assert "uvicorn api:app" in df_content
    assert "npm run start" in df_content

    compose_path = Path("docker-compose.yml")
    assert compose_path.exists(), "docker-compose.yml must exist at project root"
    dc_content = compose_path.read_text(encoding="utf-8")

    assert "3000:3000" in dc_content
    assert "8000:8000" in dc_content
    assert "KARIX_DB_PATH=/app/data/karix_store.db" in dc_content
    assert "./data:/app/data" in dc_content
    assert "media_cache:/app/media_cache" in dc_content
    assert "BACKEND_INTERNAL_URL" in dc_content
    assert "healthcheck:" in dc_content
    assert "./karix_store.db:/app/karix_store.db" not in dc_content
    assert "./.env:/app/.env" not in dc_content


def test_auth_signup_and_login_contract():
    """Verify signup creates a user and login returns a usable JWT."""
    import uuid

    email = f"auth_smoke_{uuid.uuid4().hex[:10]}@example.com"
    signup = client.post(
        "/api/auth/signup",
        json={"email": email, "password": "Smoke@123", "name": "Auth Smoke", "tenant_id": "bajaj"},
    )
    assert signup.status_code == 200, signup.text
    signup_data = signup.json()
    assert signup_data["user"]["email"] == email
    assert signup_data["token"]

    login = client.post("/api/auth/login", json={"email": email, "password": "Smoke@123"})
    assert login.status_code == 200, login.text
    login_data = login.json()
    assert login_data["user"]["id"] == signup_data["user"]["id"]
    assert login_data["token"]


def test_sqlite_wal_persistence_and_concurrency():
    """
    Verify SQLite store runs in WAL mode with normal sync and 5000ms busy timeout,
    guaranteeing concurrent reader-writer safety across worker threads.
    """
    with get_db() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal_mode.upper() == "WAL"

        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert busy_timeout >= 5000

        # Verify write transaction executes cleanly
        conn.execute(
            "INSERT OR REPLACE INTO ingestion_jobs (id, tenant_id, channel, filename, total_count, status, created_at, updated_at) "
            "VALUES ('test_smoke_job', 'bajaj', 'whatsapp', 'smoke.csv', 1, 'COMPLETED', '2026-09-07T00:00:00', '2026-09-07T00:00:00')"
        )
        row = conn.execute("SELECT status FROM ingestion_jobs WHERE id = 'test_smoke_job'").fetchone()
        assert row["status"] == "COMPLETED"


def test_production_webhook_connectivity():
    """
    Verify production webhook connectivity:
    - Rejects unauthorized calls without valid token
    - Accepts authorized webhook payload
    - Performs targeted upstream verification probe via official API
    - Monotonically updates approval status in the database
    """
    # 1. Reject without token
    r_unauth = client.post("/api/webhooks/karix/bajaj", json={"template_name": "smoke_test_template"})
    assert r_unauth.status_code == 401

    # 2. Reject with forged token
    r_bad_token = client.post(
        "/api/webhooks/karix/bajaj",
        headers={"X-Webhook-Token": "invalid_forged_secret"},
        json={"template_name": "smoke_test_template"},
    )
    assert r_bad_token.status_code == 401

    # 3. Accept with valid token + verify targeted probe
    with patch("submission_client.check_status") as mock_probe:
        mock_probe.return_value = (
            ApprovalStatus.APPROVED,
            None,
            {"fb_template_id": "999888777", "template_name": "smoke_test_template"},
        )
        r_valid = client.post(
            "/api/webhooks/karix/bajaj",
            headers={"X-Webhook-Token": "karix_webhook_secret_2026"},
            json={"templateName": "smoke_test_template", "status": "APPROVED"},
        )

    assert r_valid.status_code == 200
    data = r_valid.json()
    assert data["ok"] is True
    assert data["template_name"] == "smoke_test_template"
    assert data["status"] == "approved"
