"""Authenticated Apparel intake, immutable review boundaries, and durable staging."""
import copy
import csv
import io
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import db
from api import app
import apparel_whatsapp
import moengage_draft_batches as batches
import moengage_draft_creation as creation
import moengage_workspaces

ROOT = "/api/apparel/whatsapp"
SENDER = "a" * 24
TEMPLATE = "b" * 24
CATALOG = {
    "account": "apparel", "workspace_id": "offline-crocs",
    "brands": [{"brand": "Crocs", "workspace_id": "offline-crocs", "no_goals": True}],
    "segments": [{"id": "include-id", "name": "Customers"}, {"id": "exclude-id", "name": "Suppressed"}],
    "whatsapp_senders": [{"id": SENDER, "sender_id": SENDER, "name": "Crocs sender",
        "sender_name": "Crocs sender", "number": "+919876543210", "phone_number": "+919876543210", "provider": "KARIX"}],
    "whatsapp_templates": [{"id": TEMPLATE, "name": "crocs_offer", "body": "Welcome!",
        "provider": "KARIX", "sender_ids": [SENDER], "template_content": {}}],
}


def brief(name="Reviewed campaign", padding=0):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    for label, value in [
        ("Campaign Name", name), ("Send Date", "15 October 2026"), ("Send Time", "6:30 PM"),
        ("Sender ID", "+919876543210"), ("Template ID", TEMPLATE),
        ("Include", "Customers"), ("Exclude", "Suppressed"),
        ("Track the goal for no of hours days", "3 days"), ("Notes", "x" * padding),
    ]:
        writer.writerow([label, "", value])
    return output.getvalue().encode()


def post(client, suffix, headers, options=None, data=None, sheet=None, raw=None):
    fields = {"options_json": raw if raw is not None else json.dumps(options or {"brand": "Crocs"})}
    if sheet is not None:
        fields["spreadsheet_url"] = sheet
    return client.post(ROOT + suffix, headers=headers, data=fields,
        files={"file": ("brief.csv", data, "text/csv")} if data is not None else None)


def stored_rows():
    with db.get_db() as connection:
        return connection.execute("SELECT * FROM moengage_draft_batch_rows").fetchall()


@pytest.fixture
def gateway(monkeypatch, provision_user):
    """Only workspace metadata is substituted; parser, preview and SQLite queue are real."""
    metadata = Mock(return_value=copy.deepcopy(CATALOG))
    monkeypatch.setattr(creation, "load_server_catalog", metadata)
    monkeypatch.setattr(moengage_workspaces, "workspace_catalog", metadata)
    monkeypatch.setattr(batches, "catalog_for_row", metadata)
    import apparel_whatsapp_google
    monkeypatch.setattr(apparel_whatsapp_google, "service_account_email", lambda: "offline@example.invalid")
    provider = Mock(side_effect=AssertionError("Campaign provider access is forbidden during intake"))
    monkeypatch.setattr(moengage_workspaces, "_metadata_request", provider)
    monkeypatch.setattr(creation.DraftCreation, "create", provider)
    original = batches.DraftBatchQueue

    def offline_queue(account, user, catalog):
        return original(account, user, catalog, allow_sqlite_for_tests=True)

    monkeypatch.setattr(batches, "DraftBatchQueue", offline_queue)
    _, headers = provision_user()
    with TestClient(app) as client:
        yield client, headers, metadata, provider
    provider.assert_not_called()


@pytest.mark.parametrize("identity", ["anonymous", "foreign"])
@pytest.mark.parametrize("suffix", ["/catalog", "/preview", "/batches"])
def test_denied_identity_never_reads_provider_or_stages(gateway, provision_user, identity, suffix):
    client, _, metadata, _ = gateway
    headers = {} if identity == "anonymous" else provision_user(tenant="tata")[1]
    response = client.get(ROOT + suffix, headers=headers) if suffix == "/catalog" else post(client, suffix, headers, data=brief())
    assert response.status_code in (401, 403)
    metadata.assert_not_called()
    assert stored_rows() == []


@pytest.mark.parametrize("superadmin", [False, True])
def test_authorized_catalog_preview_and_durable_stage(gateway, provision_user, superadmin):
    client, headers, _, _ = gateway
    if superadmin:
        headers = provision_user(tenant="all", role="superadmin")[1]
    catalog = client.get(ROOT + "/catalog", params={"brand": "Crocs"}, headers=headers)
    assert catalog.status_code == 200
    assert catalog.json()["workspace_id"] == "offline-crocs"
    assert catalog.json()["brands"] == CATALOG["brands"]
    response = post(client, "/preview", headers, data=brief())
    assert response.status_code == 200
    preview = response.json()
    assert (preview["ready"], preview["blocked"]) == (1, 0)
    assert stored_rows() == []
    item = preview["items"][0]
    assert item["row_id"] == "WhatsApp!C"
    assert item["workspace_id"] == "offline-crocs"
    candidate = item["candidate_v5_payload"]
    assert candidate["basic_details"]["name"] == "Reviewed campaign"
    assert candidate["scheduling_details"]["start_time"] == "2026-10-15T18:30:00"
    wa = candidate["campaign_content"]["content"]["whatsapp"]
    assert (wa["sender_id"], wa["template_id"]) == (SENDER, TEMPLATE)
    response = post(client, "/batches", headers, data=brief(), options={
        "brand": "Crocs", "expected_source_digest": preview["source_digest"]})
    assert response.status_code == 200
    staged = response.json()
    assert staged["items"][0]["candidate_v5_payload"] == candidate
    rows = stored_rows()
    assert len(rows) == 1
    assert json.loads(rows[0]["candidate_json"]) == candidate
    assert rows[0]["campaign_id"] is None
    assert rows[0]["status"] == "preview_ready"


@pytest.mark.parametrize("raw", ["{", "[]", "null", '"Crocs"', '{"brand":"Crocs","account":"tata"}', " " * 262145])
@pytest.mark.parametrize("suffix", ["/preview", "/batches"])
def test_malformed_options_do_not_stage(gateway, raw, suffix):
    client, headers, _, _ = gateway
    response = post(client, suffix, headers, data=brief(), raw=raw)
    assert response.status_code == 400
    assert stored_rows() == []


@pytest.mark.parametrize("suffix", ["/preview", "/batches"])
def test_conflicting_sources_and_oversized_upload_fail_before_metadata(gateway, suffix):
    client, headers, metadata, _ = gateway
    response = post(client, suffix, headers, data=brief(), sheet="https://docs.google.com/spreadsheets/d/offline/edit")
    assert response.status_code == 400
    response = post(client, suffix, headers, data=b"x" * (5 * 1024 * 1024 + 1))
    assert response.status_code == 400
    metadata.assert_called()  # Local brand configuration is allowed; workspace/provider access is not.
    assert stored_rows() == []


@pytest.mark.parametrize("change", ["missing", "stale", "source_changed"])
def test_stage_requires_current_source_review_digest(gateway, change):
    client, headers, _, _ = gateway
    preview = post(client, "/preview", headers, data=brief()).json()
    options = {"brand": "Crocs"}
    if change != "missing":
        options["expected_source_digest"] = "0" * 64 if change == "stale" else preview["source_digest"]
    response = post(client, "/batches", headers, options=options,
        data=brief("Unreviewed replacement") if change == "source_changed" else brief())
    assert response.status_code == 400
    assert stored_rows() == []


@pytest.mark.parametrize("overrides", [
    {"WhatsApp!D": {"campaign_name": "not selected"}},
    {"WhatsApp!C": {"workspace_id": "foreign"}},
    {"WhatsApp!C": {"account": "tata"}},
    {"WhatsApp!C": {"whatsapp_sender_id": "foreign"}},
    {"WhatsApp!C": {"campaign_name": {"injected": True}}},
    {"WhatsApp!C": {"campaign_name": "x" * 20001}},
])
def test_invalid_field_overrides_cannot_stage_unreviewed_data(gateway, overrides):
    client, headers, _, _ = gateway
    preview = post(client, "/preview", headers, data=brief()).json()
    response = post(client, "/batches", headers, data=brief(), options={"brand": "Crocs",
        "expected_source_digest": preview["source_digest"], "overrides": overrides})
    assert response.status_code == 400
    assert stored_rows() == []


def test_changed_review_fields_cannot_reuse_original_preview_digest(gateway):
    client, headers, _, _ = gateway
    preview = post(client, "/preview", headers, data=brief()).json()
    response = post(client, "/batches", headers, data=brief(), options={"brand": "Crocs",
        "expected_source_digest": preview["source_digest"],
        "overrides": {"WhatsApp!C": {"campaign_name": "Never previewed", "scheduled_at": "2026-12-20T10:00:00+05:30"}}})
    assert response.status_code == 400
    assert stored_rows() == []


@pytest.mark.parametrize("columns", [[], "C", ["c"], ["C", 3], ["AAAA"], ["C"] * 101])
def test_invalid_physical_column_selection_does_not_stage(gateway, columns):
    client, headers, _, _ = gateway
    response = post(client, "/preview", headers, data=brief(),
        options={"brand": "Crocs", "columns": columns})
    assert response.status_code == 400
    assert stored_rows() == []


def test_missing_source_does_not_stage(gateway):
    client, headers, _, _ = gateway
    assert post(client, "/preview", headers).status_code == 400
    assert post(client, "/batches", headers).status_code == 400
    assert stored_rows() == []


def test_exactly_five_mib_upload_remains_previewable(gateway):
    client, headers, _, _ = gateway
    content = brief()
    remaining = 5 * 1024 * 1024 - len(content)
    padding_row = b"x" * 1023 + b"\n"
    content += padding_row * (remaining // len(padding_row)) + b"\n" * (remaining % len(padding_row))
    assert len(content) == 5 * 1024 * 1024
    response = post(client, "/preview", headers, data=content)
    assert response.status_code == 200
    assert response.json()["items"][0]["candidate_v5_payload"]["basic_details"]["name"] == "Reviewed campaign"
    assert stored_rows() == []


@pytest.mark.parametrize("identity", ["anonymous", "foreign"])
def test_image_media_denies_foreign_and_anonymous_callers(gateway, provision_user, identity):
    client, _, metadata, provider = gateway
    headers = {} if identity == "anonymous" else provision_user(tenant="tata")[1]
    response = client.post(ROOT + "/media", headers=headers, data={"brand": "Crocs"},
                           files={"file": ("creative.png", b"invalid", "image/png")})
    assert response.status_code in (401, 403)
    metadata.assert_not_called()
    provider.assert_not_called()


@pytest.mark.parametrize("content,drive", [
    (None, None), (b"", "https://drive.google.com/file/d/example/view"),
    (b"invalid", None), (b"x" * (5 * 1024 * 1024 + 1), None),
])
def test_invalid_or_conflicting_media_fails_before_provider_access(gateway, monkeypatch, content, drive):
    client, headers, _, _ = gateway
    forbidden = Mock(side_effect=AssertionError("Invalid media must not contact a provider"))
    monkeypatch.setattr(moengage_workspaces, "portal_session", forbidden)
    import apparel_whatsapp_google
    monkeypatch.setattr(apparel_whatsapp_google, "list_google_images", forbidden)
    fields = {"brand": "Crocs"}
    if drive is not None:
        fields["drive_url"] = drive
    response = client.post(ROOT + "/media", headers=headers, data=fields,
        files={"file": ("creative.png", content, "image/png")} if content is not None else None)
    assert response.status_code == 400
    forbidden.assert_not_called()
