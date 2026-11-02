"""Consumer-visible safeguards for account-bound Email/Push spreadsheet previews."""

import csv
import io
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook

from api import app
from tests.test_moengage_draft_creation import CATALOG, ROW, USER


def _csv_bytes(*rows):
    fields = ["channel", "campaign_name", "segment_id", "scheduled_at", "timezone",
              "content_type", "subscription_category", "from_address", "subject", "html_content"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fields})
    return buffer.getvalue().encode("utf-8")


def test_sheet_preview_requires_authenticated_tenant_and_server_catalog(tmp_path, monkeypatch, provision_user):
    _, headers = provision_user(tenant="tata", email=USER["email"])
    catalog_path = tmp_path / "account-catalog.json"
    catalog_path.write_text(json.dumps(CATALOG), encoding="utf-8")
    monkeypatch.setenv("MOENGAGE_DRAFT_TATA_CATALOG_FILE", str(catalog_path))
    monkeypatch.setenv("MOENGAGE_DRAFT_TATA_WORKSPACE_ID", CATALOG["workspace_id"])
    content = _csv_bytes(ROW, {**ROW, "campaign_name": "Unlisted audience", "segment_id": "not-a-segment"})
    upload = {"file": ("campaigns.csv", content, "text/csv")}
    client = TestClient(app)
    with patch("requests.request", side_effect=AssertionError("Preview must never call MoEngage")):
        assert client.post("/api/moengage/drafts/preview-upload", data={"account": "tata"}, files=upload).status_code == 401
        assert client.post("/api/moengage/drafts/preview-upload", headers=headers, data={"account": "bajaj"}, files=upload).status_code == 403
        preview = client.post("/api/moengage/drafts/preview-upload", headers=headers, data={
            "account": "tata", "catalog_json": '{"account":"tata","workspace_id":"attacker"}'
        }, files=upload)
        assert preview.status_code == 200, preview.text
        data = preview.json()
        assert data["workspace_id"] == CATALOG["workspace_id"]
        assert (data["ready"], data["blocked"]) == (1, 1)
        assert [item["row_id"] for item in data["items"]] == ["2", "3"]
        assert data["items"][0]["candidate_v5_payload"]["channel"] == "EMAIL"
        assert data["items"][1]["status"] == "blocked"
        assert data["items"][1]["source_fields"]["campaign_name"] == "Unlisted audience"
        assert data["items"][1]["candidate_v5_payload"] is None
        assert client.post("/api/moengage/drafts/batches", headers=headers, data={"account": "bajaj"}, files=upload).status_code == 403
        for name in ("DATABASE_URL", "POSTGRES_URL", "POSTGRESQL_URL"):
            monkeypatch.delenv(name, raising=False)
        stage = client.post("/api/moengage/drafts/batches", headers=headers, data={"account": "tata"}, files=upload)
        assert stage.status_code == 423
        assert "Shared PostgreSQL" in stage.json()["detail"]
        monkeypatch.delenv("MOENGAGE_DRAFT_TATA_CATALOG_FILE")
        assert client.post("/api/moengage/drafts/preview-upload", headers=headers, data={"account": "tata"}, files=upload).status_code == 423


def test_xlsx_push_preview_keeps_worksheet_row_and_channel_specific_content(tmp_path, monkeypatch, provision_user):
    catalog = {**CATALOG, "push_platforms": [{"platform": "ANDROID", "notification_channel": "campaigns"}]}
    catalog_path = tmp_path / "account-catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setenv("MOENGAGE_DRAFT_TATA_CATALOG_FILE", str(catalog_path))
    monkeypatch.setenv("MOENGAGE_DRAFT_TATA_WORKSPACE_ID", CATALOG["workspace_id"])

    book = Workbook()
    sheet = book.active
    sheet.title = "October"
    sheet.append(["channel", "campaign_name", "segment_id", "scheduled_at", "timezone",
                  "push_platform", "push_title", "push_message", "click_url"])
    sheet.append(["PUSH", "Approved October alert", "seg-vip", ROW["scheduled_at"],
                  ROW["timezone"], "ANDROID", "Loan offer", "Review your offer",
                  "https://example.com/offer"])
    buffer = io.BytesIO()
    book.save(buffer)
    _, headers = provision_user(tenant="tata", email=USER["email"])
    client = TestClient(app, headers=headers)
    result = client.post(
        "/api/moengage/drafts/preview-upload",
        data={"account": "tata"},
        files={"file": ("planned.xlsx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert result.status_code == 200, result.text
    item = result.json()["items"][0]
    assert (item["source_ref"], item["row_id"], item["status"]) == ("planned.xlsx", "October!2", "preview_ready")
    payload = item["candidate_v5_payload"]
    assert payload["channel"] == "PUSH"
    assert payload["segmentation_details"]["included_filters"]["filters"][0]["id"] == "seg-vip"
    assert payload["campaign_content"]["content"]["push"]["android"]["basic_details"]["message"] == "Review your offer"

def test_client_whatsapp_workbook_resolves_only_explicit_workspace_audiences(tmp_path, monkeypatch, provision_user):
    workspace = "6516b0db87ee0c3c4499dc68"
    sender = "111111111111111111111111"
    template = "222222222222222222222222"
    catalog = {
        "account": "tata", "workspace_id": workspace, "workspace_name": "Tata Capital",
        "whatsapp_workspaces": [{"id": workspace, "name": "Tata Capital"}],
        "whatsapp_senders": [{"sender_id": sender, "sender_name": "Tata test sender", "provider": "KARIX"}],
        "whatsapp_templates": [{"id": template, "name": "training", "body": "Dear Colleague, attend {{1}}",
                                "provider": "KARIX", "sender_ids": [sender]}],
        "segments": [{"id": "segment-training", "name": "TTA_BATCH04_09102026"},
                     {"id": "segment-session", "name": "TTA_BATCH05_09102026"}],
    }
    catalog_path = tmp_path / "account-catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setenv("MOENGAGE_DRAFT_TATA_CATALOG_FILE", str(catalog_path))
    monkeypatch.setenv("MOENGAGE_DRAFT_TATA_WORKSPACE_ID", workspace)
    monkeypatch.setattr("moengage_workspaces.workspace_catalog", lambda *_: catalog)

    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet.append(["workspace_id", "Sr. No", "Message Body", "File Name on FileZilla",
                  "Date of Trigger", "Time of Trigger"])
    sheet.append([workspace, 1, "Dear Colleague, attend training", "TTA_BATCH04_09102026", "46303", "0.625"])
    sheet.append([workspace, 2, "Dear Colleague, attend session", "TTA_BATCH05_09102026", "46304", "0.45486"])
    sheet.append([workspace, 3, "Dear Colleague, attend training", "UNKNOWN_AUDIENCE", "46304", "0.625"])
    buffer = io.BytesIO()
    book.save(buffer)
    _, headers = provision_user(tenant="tata", email=USER["email"])
    response = TestClient(app, headers=headers).post(
        "/api/moengage/drafts/preview-upload", data={"account": "tata"},
        files={"file": ("Whatsapp message.xlsx", buffer.getvalue(),
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["ready"], result["blocked"]) == (2, 1)
    for item, audience, value, clock in zip(
        result["items"][:2], ("segment-training", "segment-session"), ("training", "session"),
        ("15:00:00", "10:55:00"), strict=True,
    ):
        payload = item["candidate_v5_payload"]
        assert item["workspace_id"] == workspace
        assert payload["segmentation_details"]["included_filters"]["filters"][0]["id"] == audience
        whatsapp = payload["campaign_content"]["content"]["whatsapp"]
        assert (whatsapp["sender_id"], whatsapp["template_id"], whatsapp["body_placeholders"]) == (
            sender, template, {"{{1}}": value},
        )
        assert payload["scheduling_details"]["start_time"].endswith(clock)
    assert result["items"][2]["candidate_v5_payload"] is None
