"""Offline draft review and timer readback never invoke provider catalogs."""
import pytest
from fastapi.testclient import TestClient

import api
import config
import db_queue
import sms_dlt
import vilpower_client


def deny_provider(*args, **kwargs):
    pytest.fail("Provider access is forbidden for offline review/readback")


@pytest.fixture
def no_provider(monkeypatch):
    monkeypatch.setattr(api, "_fetch_whatsapp_inventory", deny_provider)
    monkeypatch.setattr(api, "_fetch_rcs_inventory", deny_provider)
    monkeypatch.setattr(sms_dlt, "_inventory", deny_provider)
    monkeypatch.setattr(vilpower_client, "fetch_sms_options", deny_provider)
    monkeypatch.setattr(config, "_load_env_file", lambda: None)


@pytest.mark.parametrize("channel,data", [
    ("whatsapp", b"template_name,body_text\natt_source_offer,Your requested offer is ready.\n"),
    ("rcs", b"template_name,text_message\natt_source_offer,Your requested offer is ready.\n"),
    ("sms", b"template_name,text\natt_source_offer,Your requested offer is ready.\n"),
])
def test_offline_upload_preserves_copy_source_and_unverified_state(no_provider, provision_user, channel, data):
    _, headers = provision_user("tata")
    result = TestClient(api.app, headers=headers).post(
        f"/api/preview?account=tata&channel={channel}&verify_inventory=false",
        files={"file": ("original-offer.csv", data)},
    )
    assert result.status_code == 200, result.text
    row, = result.json()
    assert row["template_name"] == "att_source_offer"
    assert row["source_ref"]
    assert row["source_file"] == "original-offer.csv"
    text = row.get("text_message") if channel == "rcs" else row["components"][0]["text"]
    assert text == "Your requested offer is ready."
    assert row["inventory_status"] == "unverified"
    assert row["inventory_error"] is None
    assert row["submission_ready"] is False
    assert row["already_exists_on_waba"] is None
    assert row["exists_on_waba"] is None


def test_offline_sms_draft_review_keeps_manual_fields_and_provenance(no_provider, provision_user):
    _, headers = provision_user("tata")
    draft = {"template_name": "reviewed_offer", "text": "  My reviewed SMS copy.  ",
             "template_type": "1", "category_id": "finance", "header_id": "header-id", "header": "TATAXX",
             "source_ref": "Offers!C7", "source_file": "offers.xlsx"}
    result = TestClient(api.app, headers=headers).post("/api/sms-dlt/preview?verify_inventory=false",
                                                     json={"account": "tata", "templates": [draft]})
    assert result.status_code == 200, result.text
    row, = result.json()
    assert all(row["sms_dlt"][key] == value for key, value in draft.items())
    assert row["source_ref"] == "Offers!C7"
    assert row["inventory_status"] == "unverified"
    assert row["submission_ready"] is False


def test_default_preview_still_verifies_inventory(provision_user, monkeypatch):
    _, headers = provision_user("tata")
    calls = []
    monkeypatch.setattr(api, "_fetch_whatsapp_inventory", lambda account: (calls.append(account) or [], None))
    result = TestClient(api.app, headers=headers).post(
        "/api/preview?account=tata&channel=whatsapp",
        files={"file": ("offer.csv", b"template_name,body_text\nreviewed_offer,Your requested offer is ready.\n")},
    )
    assert result.status_code == 200, result.text
    assert result.json()[0]["inventory_status"] == "verified"
    assert result.json()[0]["submission_ready"] is True
    assert calls == ["tata"]


@pytest.mark.parametrize("channel", ["whatsapp", "rcs", "sms"])
def test_stored_templates_and_stats_are_exact_scope_and_explicitly_not_synced(no_provider, provision_user, channel):
    _, headers = provision_user("tata")
    rows = [
        {"template_name": "registered", "source_ref": "Original!C2", "client": "tata", "channel": channel,
         "status": "SUBMITTED", "approval_status": "pending", "provider_ref_id": "provider-1"},
        {"template_name": "approved", "source_ref": "Original!C3", "client": "tata", "channel": channel,
         "status": "SUBMITTED", "approval_status": "approved", "provider_ref_id": "provider-2"},
        {"template_name": "unknown", "source_ref": "Original!C4", "client": "tata", "channel": channel,
         "status": "FAILED", "approval_status": "unknown", "provider_response": {"outcome": "unknown", "retry_safe": False}},
    ]
    db_queue.create_job_with_tasks("tata", channel, "original.xlsx", "Tester", rows)
    # Neither another account nor another channel may bleed into the selected timer readback.
    db_queue.create_job_with_tasks("tchfl", "whatsapp", "other.xlsx", "Tester", [
        {"template_name": "another-account", "status": "SUBMITTED", "approval_status": "approved"},
    ])
    other_channel = "rcs" if channel != "rcs" else "whatsapp"
    db_queue.create_job_with_tasks("tata", other_channel, "other.xlsx", "Tester", [
        {"template_name": "another-channel", "status": "SUBMITTED", "approval_status": "approved"},
    ])
    client = TestClient(api.app, headers=headers)
    result = client.get("/api/templates", params={"account": "tata", "channel": channel, "live": "false"})
    assert result.status_code == 200, result.text
    stored = result.json()
    assert {row["template_name"] for row in stored} == {"registered", "approved", "unknown"}
    assert all(row["client"] == "tata" and row["channel"] == channel for row in stored)
    assert all(row["source"] == "stored" and row["inventory_status"] == "not_requested"
               and row["provider_synced"] is False for row in stored)
    stats = client.get("/api/stats", params={"account": "tata", "channel": channel, "live": "false"})
    assert stats.status_code == 200, stats.text
    assert {key: stats.json()[key] for key in ("total", "submitted", "failed", "pending", "approved")} == {
        "total": 3, "submitted": 2, "failed": 1, "pending": 1, "approved": 1,
    }
    assert stats.json()["source"] == "stored"
    assert stats.json()["provider_synced"] is False
    filtered = client.get("/api/templates", params={"account": "tata", "channel": channel, "live": "false", "status": "approved"})
    assert [row["template_name"] for row in filtered.json()] == ["approved"]
    forbidden = client.get("/api/templates", params={"account": "bajaj", "channel": channel, "live": "false"})
    assert forbidden.status_code == 403


@pytest.mark.parametrize("channel,content", [
    ("whatsapp", b"template_name,body_text\natt_stable_offer,Exact review copy.\n"),
    ("rcs", b"template_name,text_message\natt_stable_offer,Exact review copy.\n"),
])
def test_offline_and_verified_preview_keep_the_same_review_identity(monkeypatch, provision_user, channel, content):
    _, headers = provision_user("tata")
    monkeypatch.setattr(config, "_load_env_file", lambda: None)
    monkeypatch.setattr(api, "fetch_whatsapp_templates", lambda **kwargs: [])
    monkeypatch.setattr(api, "_fetch_rcs_inventory", lambda *args, **kwargs: [])
    client = TestClient(api.app, headers=headers)
    def preview(verify):
        response = client.post(f"/api/preview?account=tata&channel={channel}&verify_inventory={str(verify).lower()}",
                               files={"file": ("review.csv", content)})
        assert response.status_code == 200, response.text
        return response.json()[0]
    offline, verified = preview(False), preview(True)
    for field in ("template_name", "source_ref", "source_file", "source_sheet", "source_cell", "components",
                  "text_message", "template_message", "card_title", "card_description", "carousel_cards"):
        assert offline.get(field) == verified.get(field), field
    assert offline["submission_ready"] is False
    assert verified["submission_ready"] is True
