"""
Tests for Enterprise Hardened Queue, Per-WABA Rate Limiter,
Circuit Breaker, and Webhook Ingestion Engine.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import api
from db_queue import (
    create_job_with_tasks,
    get_db,
    get_job,
    get_job_tasks,
    init_queue_db,
    record_task_result,
    update_template_approval_monotonic,
)
from models import ApprovalStatus
from queue_manager import QUEUE_MANAGER, WabaTokenBucket

client = TestClient(api.app)


@pytest.fixture(autouse=True)
def setup_db():
    init_queue_db()


def test_db_queue_atomic_job_and_tasks_creation():
    """Verify atomic creation of ingestion_jobs and job_tasks in SQLite."""
    tasks = [
        {"template_name": "tpl_test_01", "source_ref": "ref_01", "category": "MARKETING"},
        {"template_name": "tpl_test_02", "source_ref": "ref_02", "category": "UTILITY"},
        {"template_name": "tpl_test_03", "source_ref": "ref_03", "category": "AUTHENTICATION"},
    ]
    job = create_job_with_tasks(
        tenant_id="tchfl",
        channel="whatsapp",
        filename="test_batch.csv",
        submitted_by="Tester",
        tasks_data=tasks,
    )
    assert job is not None
    assert job["total_count"] == 3
    assert job["status"] == "QUEUED"

    fetched_tasks = get_job_tasks(job["id"])
    assert len(fetched_tasks) == 3
    assert fetched_tasks[0]["template_name"] == "tpl_test_01"
    assert fetched_tasks[0]["status"] == "PENDING"
    assert fetched_tasks[0]["approval_status"] == "pending"


def test_monotonic_approval_state_machine():
    """
    Verify monotonic lifecycle guard:
    - PENDING -> APPROVED advances
    - Delayed carrier PENDING cannot overwrite APPROVED
    """
    import uuid
    tname = f"tpl_mono_{uuid.uuid4().hex[:6]}"
    tasks = [
        {"template_name": tname, "source_ref": "ref_m1", "status": "SUBMITTED", "approval_status": "pending"}
    ]
    job = create_job_with_tasks(
        tenant_id="tchfl",
        channel="whatsapp",
        filename="monotonic.csv",
        submitted_by="Tester",
        tasks_data=tasks,
    )

    # 1. Advance PENDING -> APPROVED
    updated = update_template_approval_monotonic(
        tenant_id="tchfl",
        template_name=tname,
        new_approval_status="approved",
        provider_ref_id="fb_12345",
    )
    assert updated == 1
    tasks_after = get_job_tasks(job["id"])
    assert tasks_after[0]["approval_status"] == "approved"
    assert tasks_after[0]["provider_ref_id"] == "fb_12345"

    # 2. Carrier sends delayed out-of-order PENDING event: MUST BE REJECTED
    updated_delayed = update_template_approval_monotonic(
        tenant_id="tchfl",
        template_name=tname,
        new_approval_status="pending",
    )
    assert updated_delayed == 0
    tasks_after_delayed = get_job_tasks(job["id"])
    assert tasks_after_delayed[0]["approval_status"] == "approved"  # Remains APPROVED!

    # 3. Carrier attempts to overwrite APPROVED with REJECTED: MUST BE REJECTED
    updated_conflict = update_template_approval_monotonic(
        tenant_id="tchfl",
        template_name=tname,
        new_approval_status="rejected",
    )
    assert updated_conflict == 0
    tasks_final = get_job_tasks(job["id"])
    assert tasks_final[0]["approval_status"] == "approved"


def test_rate_limiter_token_bucket_and_429_backoff():
    """Verify per-WABA token bucket consumption and dynamic 429 throttling."""
    async def _run_test():
        bucket = WabaTokenBucket(waba_id="test_waba_123", rate_per_sec=10.0, capacity=2.0)
        assert bucket.tokens == 2.0

        # Acquire 2 tokens
        await bucket.acquire(1.0)
        await bucket.acquire(1.0)
        assert bucket.tokens < 0.1

        # Record carrier 429
        bucket.record_429(backoff_sec=1.5)
        assert bucket.tokens == 0.0

        # Verify bucket throttled_until is in the future
        import time
        assert bucket.throttled_until > time.monotonic()

    asyncio.run(_run_test())

def test_circuit_breaker_paused_for_auth_and_auto_resume():
    """Verify PAUSED_FOR_AUTH circuit tripping and event-bus auto-resume."""
    tasks = [{"template_name": "tpl_cb_test", "source_ref": "ref_cb", "status": "PENDING"}]
    job = create_job_with_tasks(
        tenant_id="tcl_promo",
        channel="whatsapp",
        filename="cb_test.csv",
        submitted_by="Tester",
        tasks_data=tasks,
    )

    # Trip circuit on 401
    QUEUE_MANAGER.trip_auth_circuit("tcl_promo", job["id"], "Karix portal session expired (401)")
    assert QUEUE_MANAGER.is_auth_tripped("tcl_promo") is True

    paused_job = get_job(job["id"])
    assert paused_job["status"] == "PAUSED_FOR_AUTH"
    assert "session expired" in paused_job["error_message"].lower()

    # Operator updates credentials -> Auto-resume triggered
    _ = QUEUE_MANAGER.notify_credentials_updated("tcl_promo")
    assert QUEUE_MANAGER.is_auth_tripped("tcl_promo") is False

    resumed_job = get_job(job["id"])
    assert resumed_job["status"] == "RUNNING"
    assert resumed_job["error_message"] is None


def test_webhook_authentication_and_targeted_verification():
    """
    Verify POST /api/webhooks/karix/{tenant}
    - 401 on invalid/missing secret token
    - Targeted check_status official API probe
    - Monotonic state update in database
    """
    # Create target task in database
    tasks = [{"template_name": "hfl_patp_so_030926", "source_ref": "webhook_ref_1", "status": "SUBMITTED", "approval_status": "pending"}]
    job = create_job_with_tasks(
        tenant_id="tchfl",
        channel="whatsapp",
        filename="webhook.csv",
        submitted_by="Tester",
        tasks_data=tasks,
    )

    # 1. Reject without auth token
    r_unauth = client.post(
        "/api/webhooks/karix/tchfl",
        json={"template_name": "hfl_patp_so_030926", "status": "APPROVED"},
    )
    assert r_unauth.status_code == 401

    # 2. Valid token header with targeted check_status probe
    with patch("submission_client.check_status") as mock_probe:
        mock_probe.return_value = (
            ApprovalStatus.APPROVED,
            None,
            {"fb_template_id": "2010769589580071", "template_name": "hfl_patp_so_030926"},
        )
        r_auth = client.post(
            "/api/webhooks/karix/tchfl",
            headers={"X-Webhook-Token": "karix_webhook_secret_2026"},
            json={"templateName": "hfl_patp_so_030926", "status": "APPROVED"},
        )

    assert r_auth.status_code == 200
    data = r_auth.json()
    assert data["ok"] is True
    assert data["status"] == "approved"

    # Verify task updated in SQLite
    tasks_after = get_job_tasks(job["id"])
    assert tasks_after[0]["approval_status"] == "approved"
    assert tasks_after[0]["provider_ref_id"] == "2010769589580071"


def test_job_management_endpoints():
    """Verify GET /api/jobs/{id} and POST /api/jobs/{id}/resume endpoints."""
    # Authenticate as tchfl user
    email = "job_tester@attributics.com"
    client.post("/api/auth/signup", json={"email": email, "password": "Test@123", "name": "Job Tester", "tenant_id": "tchfl"})
    r_login = client.post("/api/auth/login", json={"email": email, "password": "Test@123"})
    token = r_login.json().get("token") or r_login.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}

    tasks = [{"template_name": "tpl_endpoint_test", "source_ref": "ref_end", "status": "PENDING"}]
    job = create_job_with_tasks(
        tenant_id="tchfl",
        channel="whatsapp",
        filename="endpoint_test.csv",
        submitted_by="Tester",
        tasks_data=tasks,
    )

    # 1. Fetch job
    r_get = client.get(f"/api/jobs/{job['id']}", headers=headers)
    assert r_get.status_code == 200
    job_data = r_get.json()
    assert job_data["job"]["id"] == job["id"]
    assert len(job_data["tasks"]) == 1

    # 2. Resume job
    r_resume = client.post(f"/api/jobs/{job['id']}/resume", headers=headers)
    assert r_resume.status_code == 200
    assert r_resume.json()["ok"] is True
