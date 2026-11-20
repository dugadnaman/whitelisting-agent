"""Jira returns persisted provider identities and never labels unknown writes rejected."""
import json

import pytest
from fastapi.testclient import TestClient

import api
import db
import rcs_client
import submission_client
from tests.test_jira_upload_contract import jira_http, reviewed_drafts  # noqa: F401
from tests.test_whatsapp_media_transport import isolated, provider  # noqa: F401


def test_successful_jira_result_returns_durable_identity_and_provider_evidence(provider, provision_user, jira_http):
    _, headers = provision_user("tata")
    drafts, _ = reviewed_drafts("label_only")
    response = TestClient(api.app, headers=headers).post("/api/jira/submit/SOURCE-417", json={
        "account": "tcl_promo", "channels": ["whatsapp"], "whatsapp_templates": drafts,
    })
    assert response.status_code == 200, response.text
    result, = response.json()["whatsapp_submitted"]
    assert result["source_ref"].startswith("SOURCE-417_")
    assert result["provider_ref_id"]
    assert result["provider_response"]
    assert result["updated_at"]
    assert result["approval_status"] == "pending"
    with db.get_db() as conn:
        stored = conn.execute("SELECT * FROM job_tasks").fetchone()
    assert result["provider_ref_id"] == stored["provider_ref_id"]
    assert result["source_ref"] == stored["source_ref"]
    assert result["updated_at"] == stored["updated_at"]


@pytest.mark.parametrize("channel", ["whatsapp", "rcs"])
def test_jira_interrupted_submission_is_persisted_unknown_never_rejected_or_replayed(provider, provision_user, jira_http, monkeypatch, channel):
    _, headers = provision_user("tata")
    attempts = []

    def interrupted(submission, **kwargs):
        attempts.append(submission.template_name)
        raise RuntimeError("Connection lost after a possible provider write")

    monkeypatch.setattr(submission_client, "submit_template", interrupted)
    monkeypatch.setattr(rcs_client, "submit_rcs_template", interrupted)
    drafts, _ = reviewed_drafts("label_only")
    response = TestClient(api.app, headers=headers).post("/api/jira/submit/INTERRUPTED-78", json={
        "account": "tcl_promo", "channels": [channel],
        "whatsapp_templates": drafts if channel == "whatsapp" else [],
        "rcs_templates": [{"template_name": "reviewed_offer", "body": "My reviewed RCS message."}] if channel == "rcs" else [],
        "expected_rcs_bot_id": api.get_rcs_bot_id("tcl_promo") if channel == "rcs" else None,
    })
    assert response.status_code == 200, response.text
    result, = response.json()[f"{channel}_submitted"]
    assert result["status"] == "failed"
    assert result["approval_status"] == "unknown"
    assert result["registration_outcome"] == "unknown"
    assert result["provider_response"]["retry_safe"] is False
    assert result["source_ref"].startswith("INTERRUPTED-78_")
    assert result["updated_at"]
    assert len(attempts) == 1
    with db.get_db() as conn:
        stored = conn.execute("SELECT * FROM job_tasks").fetchone()
    assert stored["tenant_id"] == "tcl_promo"
    assert stored["channel"] == channel
    assert stored["approval_status"] == "unknown"
    assert json.loads(stored["payload_json"])["provider_response"]["outcome"] == "unknown"
    api.refresh_pending_approvals()
    assert len(attempts) == 1
