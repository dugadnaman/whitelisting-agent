"""Consumer-visible safeguards for account-bound Email/Push spreadsheet previews."""

import csv
import io
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook

from api import app, get_current_user
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


def test_sheet_preview_requires_authenticated_tenant_and_server_catalog(tmp_path, monkeypatch):
    catalog_path = tmp_path / "account-catalog.json"
    catalog_path.write_text(json.dumps(CATALOG), encoding="utf-8")
    monkeypatch.setenv("MOENGAGE_DRAFT_TATA_CATALOG_FILE", str(catalog_path))
    monkeypatch.setenv("MOENGAGE_DRAFT_TATA_WORKSPACE_ID", CATALOG["workspace_id"])
    content = _csv_bytes(ROW, {**ROW, "campaign_name": "Unlisted audience", "segment_id": "not-a-segment"})
    upload = {"file": ("campaigns.csv", content, "text/csv")}
    client = TestClient(app)
    with patch("requests.request", side_effect=AssertionError("Preview must never call MoEngage")):
        assert client.post("/api/moengage/drafts/preview-upload", data={"account": "tata"}, files=upload).status_code == 401
        app.dependency_overrides[get_current_user] = lambda: USER
        try:
            assert client.post("/api/moengage/drafts/preview-upload", data={"account": "bajaj"}, files=upload).status_code == 403
            preview = client.post("/api/moengage/drafts/preview-upload", data={
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
            assert client.post("/api/moengage/drafts/batches", data={"account": "bajaj"}, files=upload).status_code == 403
            for name in ("DATABASE_URL", "POSTGRES_URL", "POSTGRESQL_URL"):
                monkeypatch.delenv(name, raising=False)
            stage = client.post("/api/moengage/drafts/batches", data={"account": "tata"}, files=upload)
            assert stage.status_code == 423
            assert "Shared PostgreSQL" in stage.json()["detail"]
            monkeypatch.delenv("MOENGAGE_DRAFT_TATA_CATALOG_FILE")
            assert client.post("/api/moengage/drafts/preview-upload", data={"account": "tata"}, files=upload).status_code == 423
        finally:
            app.dependency_overrides.pop(get_current_user, None)


def test_xlsx_push_preview_keeps_worksheet_row_and_channel_specific_content(tmp_path, monkeypatch):
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
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: USER
    try:
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
    finally:
        app.dependency_overrides.pop(get_current_user, None)
