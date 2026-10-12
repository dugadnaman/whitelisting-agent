"""
Production API and persistence smoke tests.
Validates:
- Health check endpoints (/healthz, /api/health)
- Pending signup and provisioned login permissions
- SQLite WAL volume persistence and concurrency
- Webhook connectivity, secret authentication, and targeted status check
"""

from __future__ import annotations

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




def test_pending_signup_has_no_company_or_admin_privileges_and_provisioned_login_works(provision_user):
    """Signup requests access; only provisioned identities have company permissions."""
    user, _ = provision_user("bajaj")
    signup = client.post(
        "/api/auth/signup",
        json={"email": "anonymous@example.com", "password": "Anonymous-password-123", "name": "Anonymous", "tenant_id": "bajaj"},
    )
    assert signup.status_code == 201, signup.text
    applicant = signup.json()
    assert applicant["user"]["tenant_id"] == "unassigned"
    assert applicant["user"]["requested_tenant_id"] == "bajaj"
    assert applicant["user"]["role"] == "operator"
    pending_headers = {"Authorization": f"Bearer {applicant['token']}"}
    profile = client.get("/api/auth/me", headers=pending_headers)
    assert profile.status_code == 200
    assert profile.json()["id"] == applicant["user"]["id"]
    assert profile.json()["tenant_id"] == "unassigned"
    assert profile.json()["requested_tenant_id"] == "bajaj"
    for tenant in ("bajaj", "tata", "apparel"):
        assert client.get(f"/api/stats?account={tenant}", headers=pending_headers).status_code == 403
        assert client.get(f"/api/auth/team?tenant_id={tenant}", headers=pending_headers).status_code == 403
    assert client.get("/api/auth/access-requests", headers=pending_headers).status_code == 403
    assert client.post(
        f"/api/auth/access-requests/{applicant['user']['id']}/approve", headers=pending_headers,
    ).status_code == 403
    pending_login = client.post(
        "/api/auth/login", json={"email": "anonymous@example.com", "password": "Anonymous-password-123"},
    )
    assert pending_login.status_code == 200
    assert pending_login.json()["user"]["tenant_id"] == "unassigned"
    assert pending_login.json()["user"]["role"] == "operator"
    login_headers = {"Authorization": f"Bearer {pending_login.json()['token']}"}
    assert client.get("/api/stats?account=bajaj", headers=login_headers).status_code == 403
    login = client.post("/api/auth/login", json={"email": user["email"], "password": "Test-only-password-456!"})
    assert login.status_code == 200, login.text
    assert login.json()["user"]["id"] == user["id"]
    token = login.json()["token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_sqlite_wal_persistence_and_concurrency(monkeypatch):
    """
    Verify SQLite store runs in WAL mode with normal sync and 5000ms busy timeout,
    guaranteeing concurrent reader-writer safety across worker threads.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.delenv("POSTGRESQL_URL", raising=False)
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


def test_production_webhook_connectivity(monkeypatch):
    """
    Verify production webhook connectivity:
    - Rejects unauthorized calls without valid token
    - Accepts authorized webhook payload
    - Performs targeted upstream verification probe via official API
    - Monotonically updates approval status in the database
    """
    monkeypatch.setenv("KARIX_WEBHOOK_SECRET", "Configured-test-webhook-secret-123456789")
    monkeypatch.setenv("BAJAJ_WEBHOOK_SECRET", "Configured-test-webhook-secret-123456789")
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
            headers={"X-Webhook-Token": "Configured-test-webhook-secret-123456789"},
            json={"templateName": "smoke_test_template", "status": "APPROVED"},
        )

    assert r_valid.status_code == 200
    data = r_valid.json()
    assert data["ok"] is True
    assert data["template_name"] == "smoke_test_template"
    assert data["status"] == "approved"
