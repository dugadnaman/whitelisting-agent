"""Offline V5 draft-create lifecycle: durability, read-back, validation and no-cost gates."""

import copy
import json
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import db
from api import app
from moengage_draft_creation import DraftCreation, RateLimitError

USER = {"sub": "operator-1", "tenant_id": "tata", "role": "operator", "email": "owner@example.com"}
CATALOG = {
    "account": "tata", "workspace_id": "offline-workspace",
    "segments": [{"id": "seg-vip", "name": "VIP"}],
    "subscription_categories": ["Offers"],
    "email_senders": [{"from_address": "mail@example.com", "sender_name": "Tata",
                       "connector_type": "SENDGRID", "connector_name": "Primary"}],
}
ROW = {
    "account": "tata", "source_ref": "rows.json", "row_id": "1", "channel": "EMAIL",
    "campaign_name": "VIP offer", "segment_id": "seg-vip",
    "scheduled_at": "2026-10-15T10:00:00+05:30", "timezone": "Asia/Kolkata",
    "content_type": "PROMOTIONAL", "subscription_category": "Offers",
    "from_address": "mail@example.com", "subject": "Offer", "html_content": "<p>Hello</p>",
}


class FakeWriter:
    def __init__(self, *, validation=None, create_error=None, readback_error=False, mismatch=False,
                 validate_error=None):
        self.validation = validation if validation is not None else {"valid": True}
        self.create_error = create_error
        self.readback_error = readback_error
        self.mismatch = mismatch
        self.validate_error = validate_error
        self.calls = []
        self.payloads = {}

    def create(self, payload, *, idempotency_key):
        self.calls.append(("create", idempotency_key))
        if self.create_error:
            raise self.create_error
        campaign_id = f"{len(self.payloads) + 1:024x}"
        self.payloads[campaign_id] = copy.deepcopy(payload)
        return {"id": campaign_id, "status": "DRAFT"}

    def get(self, campaign_id):
        self.calls.append(("get", campaign_id))
        if self.readback_error:
            self.readback_error = False
            raise TimeoutError("Simulated offline readback failure")
        payload = copy.deepcopy(self.payloads[campaign_id])
        if self.mismatch:
            payload["campaign_content"]["content"]["email"]["subject"] = "Different"
        return {"id": campaign_id, "status": "DRAFT", **payload, "updated_at": "ignored-provider-default"}

    def validate(self, campaign_id):
        self.calls.append(("validate", campaign_id))
        if self.validate_error:
            raise self.validate_error
        return self.validation


@pytest.fixture
def offline_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_SQLITE_PATH", tmp_path / "isolated_drafts.db")
    for name in ("DATABASE_URL", "POSTGRES_URL", "POSTGRESQL_URL"):
        monkeypatch.delenv(name, raising=False)


def service(writer, *, clock=lambda: 1_000_000.0):
    return DraftCreation("tata", USER, CATALOG, writer, clock=clock, allow_sqlite_for_tests=True)


def test_single_draft_is_read_back_validated_and_idempotent(offline_db):
    writer = FakeWriter()
    worker = service(writer)
    first = worker.create(ROW)
    assert first["state"] == "VALIDATED" and first["validation_errors"] == []
    assert first["campaign_id"] == "000000000000000000000001"
    assert [name for name, _ in writer.calls] == ["create", "get", "validate"]
    assert worker.create(ROW) == first
    assert [name for name, _ in writer.calls].count("create") == 1
    with db.get_db() as conn:
        stored = conn.execute("SELECT * FROM moengage_draft_attempts").fetchone()
    assert stored["state"] == "VALIDATED"
    assert stored["idempotency_key"] == writer.calls[0][1]
    assert stored["payload_hash"] and stored["campaign_id"] == first["campaign_id"]


def test_validation_failure_inside_success_response_is_blocking(offline_db):
    writer = FakeWriter(validation={"valid": False, "errors": [{"field": "connector", "issue": "Not configured"}]})
    result = service(writer).create(ROW)
    assert result["state"] == "NEEDS_FIX"
    assert result["validation_errors"] == [{"field": "connector", "issue": "Not configured"}]
    assert [name for name, _ in writer.calls] == ["create", "get", "validate"]


def test_unconfirmed_validation_and_changed_status_require_review(offline_db):
    writer = FakeWriter(validation={"valid": False, "errors": []})
    assert service(writer).create(ROW)["state"] == "NEEDS_REVIEW"
    other = FakeWriter(validate_error=PermissionError("No longer DRAFT"))
    assert service(other).create({**ROW, "row_id": "other"})["state"] == "NEEDS_REVIEW"


def test_readback_mismatch_and_unknown_create_outcome_never_retry_post(offline_db):
    mismatch = FakeWriter(mismatch=True)
    worker = service(mismatch)
    result = worker.create(ROW)
    assert result["state"] == "NEEDS_REVIEW"
    assert [name for name, _ in mismatch.calls] == ["create", "get"]
    assert worker.create(ROW)["state"] == "NEEDS_REVIEW"
    unknown = FakeWriter(create_error=TimeoutError("ambiguous timeout"))
    other = service(unknown)
    row = {**ROW, "row_id": "2"}
    assert other.create(row)["state"] == "UNCERTAIN"
    assert other.create(row)["state"] == "UNCERTAIN"
    assert [name for name, _ in unknown.calls] == ["create"]
    with pytest.raises(ValueError, match="already reserved"):
        other.create({**row, "subject": "Changed after timeout"})


def test_readback_failure_resumes_without_another_create(offline_db):
    writer = FakeWriter(readback_error=True)
    worker = service(writer)
    assert worker.create(ROW)["state"] == "CREATED"
    assert worker.create(ROW)["state"] == "VALIDATED"
    assert [name for name, _ in writer.calls] == ["create", "get", "get", "validate"]


def test_workspace_create_limits_count_attempts_and_fail_closed(offline_db):
    tick = [1_000_000.0]
    writer = FakeWriter()
    worker = service(writer, clock=lambda: tick[0])
    for index in range(5):
        assert worker.create({**ROW, "row_id": str(index)})["state"] == "VALIDATED"
        tick[0] += 0.1
    with pytest.raises(RateLimitError):
        worker.create({**ROW, "row_id": "at-cap"})
    assert [name for name, _ in writer.calls].count("create") == 5
    tick[0] += 61
    assert worker.create({**ROW, "row_id": "after-window"})["state"] == "VALIDATED"


def test_workspace_hour_and_day_caps(offline_db):
    tick = [1_000_000.0]
    writer = FakeWriter()
    worker = service(writer, clock=lambda: tick[0])
    for index in range(25):
        worker.create({**ROW, "row_id": f"hour-{index}"})
        tick[0] += 61
    with pytest.raises(RateLimitError):
        worker.create({**ROW, "row_id": "hour-cap"})
    tick[0] += 3601
    for index in range(75):
        worker.create({**ROW, "row_id": f"day-{index}"})
        tick[0] += 151
    with pytest.raises(RateLimitError):
        worker.create({**ROW, "row_id": "day-cap"})
    assert [name for name, _ in writer.calls].count("create") == 100


def test_rate_limit_is_shared_by_workspace_not_account(offline_db):
    writer = FakeWriter()
    for index in range(5):
        service(writer).create({**ROW, "row_id": f"tata-{index}"})
    admin = {"sub": "admin-1", "tenant_id": "all", "role": "superadmin", "email": "admin@example.com"}
    other_catalog = {**CATALOG, "account": "bajaj"}
    other = DraftCreation("bajaj", admin, other_catalog, writer, clock=lambda: 1_000_000.0,
                          allow_sqlite_for_tests=True)
    with pytest.raises(RateLimitError):
        other.create({**ROW, "account": "bajaj", "row_id": "bajaj-1"})
    assert [name for name, _ in writer.calls].count("create") == 5


def test_live_test_only_approved_row_and_segment_once_across_time(offline_db):
    writer = FakeWriter()
    tick = [1_000_000.0]
    first = DraftCreation("tata", USER, CATALOG, writer, clock=lambda: tick[0],
                          allow_sqlite_for_tests=True,
                          approved_live_rows={("rows.json", "1"): (None, "seg-vip")})
    with pytest.raises(PermissionError, match="not approved"):
        first.create({**ROW, "segment_id": "not-test-segment"})
    with pytest.raises(PermissionError, match="not approved"):
        first.create({**ROW, "row_id": "2"})
    approved = first.create(ROW)
    assert approved["state"] == "VALIDATED"
    tick[0] += 100_000
    assert first.create(ROW) == approved
    next_row = DraftCreation("tata", USER, CATALOG, writer, clock=lambda: tick[0],
                             allow_sqlite_for_tests=True,
                             approved_live_rows={("rows.json", "2"): (None, "seg-vip")})
    with pytest.raises(RateLimitError, match="already used"):
        next_row.create({**ROW, "row_id": "2"})
    assert [name for name, _ in writer.calls].count("create") == 1


def test_uncertain_live_test_attempt_also_exhausts_limit(offline_db):
    writer = FakeWriter(create_error=TimeoutError("provider response unknown"))
    first = DraftCreation("tata", USER, CATALOG, writer, allow_sqlite_for_tests=True,
                          approved_live_rows={("rows.json", "1"): (None, "seg-vip")})
    assert first.create(ROW)["state"] == "UNCERTAIN"
    next_row = DraftCreation("tata", USER, CATALOG, writer, allow_sqlite_for_tests=True,
                             approved_live_rows={("rows.json", "2"): (None, "seg-vip")})
    with pytest.raises(RateLimitError, match="already used"):
        next_row.create({**ROW, "row_id": "2"})
    assert [name for name, _ in writer.calls] == ["create"]


def test_two_named_live_channels_have_exact_row_and_workspace_attempt_bounds(offline_db):
    writer = FakeWriter()
    catalog = {**CATALOG, "push_platforms": [{"platform": "ANDROID", "notification_channel": "campaigns"}]}
    push = {"account": "tata", "source_ref": "rows.json", "row_id": "2", "channel": "PUSH",
            "campaign_name": "Demo test push", "segment_id": "seg-vip",
            "scheduled_at": ROW["scheduled_at"], "timezone": ROW["timezone"],
            "push_platform": "ANDROID", "push_title": "Demo", "push_message": "Test only",
            "click_url": "https://example.com/demo"}
    approved = {("rows.json", "1"): ("EMAIL", "seg-vip"),
                ("rows.json", "2"): ("PUSH", "seg-vip")}
    worker = DraftCreation("tata", USER, catalog, writer, allow_sqlite_for_tests=True,
                           approved_live_rows=approved)
    with pytest.raises(PermissionError, match="not approved"):
        worker.create({**ROW, "row_id": "2"})
    assert worker.create(ROW)["state"] == "VALIDATED"
    assert worker.create(push)["state"] == "VALIDATED"
    assert worker.create(ROW)["state"] == "VALIDATED"
    rotated = DraftCreation("tata", USER, catalog, writer, allow_sqlite_for_tests=True,
                            approved_live_rows={("rows.json", "3"): ("EMAIL", "seg-vip"),
                                                ("rows.json", "4"): ("PUSH", "seg-vip")})
    with pytest.raises(RateLimitError, match="already used"):
        rotated.create({**ROW, "row_id": "3"})
    assert [name for name, _ in writer.calls].count("create") == 2


def test_live_test_requires_explicit_operator_and_row(offline_db, monkeypatch):
    for field, value in {
        "ZERO_CHARGE_CONFIRMED": "true", "NO_PUBLISH_SCOPE_CONFIRMED": "true",
        "LIVE_TEST_SOURCE_REF": "rows.json", "LIVE_TEST_ROW_ID": "1",
        "LIVE_TEST_SEGMENT_ID": "seg-vip",
    }.items():
        monkeypatch.setenv("MOENGAGE_DRAFT_TATA_" + field, value)
    with pytest.raises(PermissionError, match="designated live test operator"):
        DraftCreation.from_environment("tata", USER)
    monkeypatch.setenv("MOENGAGE_DRAFT_TATA_LIVE_TEST_OPERATOR_EMAIL", "other@example.com")
    with pytest.raises(PermissionError, match="designated live test operator"):
        DraftCreation.from_environment("tata", USER)
    monkeypatch.setenv("MOENGAGE_DRAFT_TATA_LIVE_TEST_OPERATOR_EMAIL", USER["email"])
    monkeypatch.delenv("MOENGAGE_DRAFT_TATA_LIVE_TEST_SEGMENT_ID")
    with pytest.raises(PermissionError, match="approved live test source row and segment"):
        DraftCreation.from_environment("tata", USER)


def test_server_catalog_must_match_bound_workspace(offline_db, tmp_path, monkeypatch):
    from moengage_draft_creation import DraftCreation as ProductionDraftCreation

    catalog_file = tmp_path / "owner-catalog.json"
    catalog_file.write_text(json.dumps({**CATALOG, "workspace_id": "other-workspace"}))
    prefix = "MOENGAGE_DRAFT_TATA_"
    for field, value in {
        "ZERO_CHARGE_CONFIRMED": "true", "NO_PUBLISH_SCOPE_CONFIRMED": "true",
        "LIVE_TEST_OPERATOR_EMAIL": USER["email"], "LIVE_TEST_SOURCE_REF": "rows.json",
        "LIVE_TEST_ROW_ID": "1", "LIVE_TEST_SEGMENT_ID": "seg-vip",
        "LIVE_ENABLED": "true", "WORKSPACE_ID": CATALOG["workspace_id"],
        "DATA_CENTER": "03", "API_KEY": "offline-placeholder", "CATALOG_FILE": str(catalog_file),
    }.items():
        monkeypatch.setenv(prefix + field, value)
    monkeypatch.setattr("moengage_draft_creation.get_database_url", lambda: "postgresql://not-used")
    with patch("requests.request", side_effect=AssertionError("No provider call allowed")):
        with pytest.raises(ValueError, match="Catalog does not match"):
            ProductionDraftCreation.from_environment("tata", USER)
        catalog_file.write_text(json.dumps(CATALOG))
        production = ProductionDraftCreation.from_environment("tata", USER)
        assert production.approved_live_rows == {("rows.json", "1"): (None, "seg-vip")}
        monkeypatch.setenv(prefix + "LIVE_TEST_ROWS_JSON", "[]")
        with pytest.raises(PermissionError, match="Exactly one approved Email and one Push"):
            ProductionDraftCreation.from_environment("tata", USER)
        selected = [
            {"source_ref": "campaigns.csv", "row_id": "2", "channel": "EMAIL", "segment_id": "seg-vip"},
            {"source_ref": "campaigns.csv", "row_id": "3", "channel": "PUSH", "segment_id": "seg-vip"},
        ]
        monkeypatch.setenv(prefix + "LIVE_TEST_ROWS_JSON", json.dumps(selected))
        production = ProductionDraftCreation.from_environment("tata", USER)
        assert production.approved_live_rows == {
            ("campaigns.csv", "2"): ("EMAIL", "seg-vip"),
            ("campaigns.csv", "3"): ("PUSH", "seg-vip"),
        }



def test_create_route_requires_owner_approval_and_uses_server_catalog(offline_db, provision_user):
    _, headers = provision_user(tenant="tata", email=USER["email"])
    client = TestClient(app)
    with patch("requests.request", side_effect=AssertionError("No live network call allowed")):
        assert client.post("/api/moengage/drafts/create", json={"account": "tata", "row": ROW}).status_code == 401
        assert client.post("/api/moengage/drafts/create", headers=headers, json={"account": "bajaj", "row": ROW}).status_code == 403
        with patch.dict(os.environ, {"MOENGAGE_DRAFT_TATA_ZERO_CHARGE_CONFIRMED": "",
                                  "MOENGAGE_DRAFT_TATA_NO_PUBLISH_SCOPE_CONFIRMED": ""}):
            assert client.post("/api/moengage/drafts/create", headers=headers, json={"account": "tata", "row": ROW}).status_code == 423
        writer = FakeWriter()
        with patch("moengage_draft_creation.DraftCreation.from_environment", return_value=service(writer)):
            result = client.post("/api/moengage/drafts/create", headers=headers, json={"account": "tata", "row": ROW,
                                                                      "catalog": {"account": "bajaj"}})
            assert result.status_code == 200 and result.json()["state"] == "VALIDATED"
            assert writer.calls[0][0] == "create"
        guarded_writer = FakeWriter()
        guarded = DraftCreation("tata", USER, CATALOG, guarded_writer,
                                allow_sqlite_for_tests=True,
                                approved_live_rows={("rows.json", "1"): (None, "seg-vip")})
        with patch("moengage_draft_creation.DraftCreation.from_environment", return_value=guarded):
            forbidden = client.post("/api/moengage/drafts/create", headers=headers,
                                    json={"account": "tata", "row": {**ROW, "row_id": "not-approved"}})
            assert forbidden.status_code == 423 and guarded_writer.calls == []


def test_multi_operator_and_whatsapp_rows_in_live_test_config(offline_db, tmp_path, monkeypatch):
    """Verify multiple comma-separated operators and WhatsApp channel in live test configuration."""
    from moengage_draft_creation import DraftCreation as ProductionDraftCreation

    catalog_file = tmp_path / "tata_catalog.json"
    catalog_file.write_text(json.dumps(CATALOG))
    prefix = "MOENGAGE_DRAFT_TATA_"

    operators = "neel.shah@attributics.com, dnyanesh.khawas@attributics.com, " + USER["email"]
    wa_rows = [
        {"source_ref": "wa_campaigns.csv", "row_id": "1", "channel": "WHATSAPP", "segment_id": "seg-vip"},
        {"source_ref": "wa_campaigns.csv", "row_id": "2", "channel": "EMAIL", "segment_id": "seg-vip"},
    ]

    for field, value in {
        "ZERO_CHARGE_CONFIRMED": "true",
        "NO_PUBLISH_SCOPE_CONFIRMED": "true",
        "LIVE_TEST_OPERATOR_EMAIL": operators,
        "LIVE_TEST_ROWS_JSON": json.dumps(wa_rows),
        "LIVE_ENABLED": "true",
        "WORKSPACE_ID": CATALOG["workspace_id"],
        "DATA_CENTER": "03",
        "API_KEY": "offline-placeholder",
        "CATALOG_FILE": str(catalog_file),
    }.items():
        monkeypatch.setenv(prefix + field, value)
    monkeypatch.setattr("moengage_draft_creation.get_database_url", lambda: "postgresql://not-used")

    with patch("requests.request", side_effect=AssertionError("No provider call allowed")):
        # Allowed for USER
        prod = ProductionDraftCreation.from_environment("tata", USER)
        assert prod.approved_live_rows == {
            ("wa_campaigns.csv", "1"): ("WHATSAPP", "seg-vip"),
            ("wa_campaigns.csv", "2"): ("EMAIL", "seg-vip"),
        }

        # Allowed for another operator in the comma-separated list
        neel_user = {**USER, "email": "neel.shah@attributics.com"}
        prod_neel = ProductionDraftCreation.from_environment("tata", neel_user)
        assert prod_neel.approved_live_rows is not None

        # Denied for unlisted operator
        unlisted = {**USER, "email": "unlisted@example.com"}
        with pytest.raises(PermissionError, match="designated live test operator"):
            ProductionDraftCreation.from_environment("tata", unlisted)

        # Wildcard allows any operator
        monkeypatch.setenv(prefix + "LIVE_TEST_OPERATOR_EMAIL", "*")
        prod_wildcard = ProductionDraftCreation.from_environment("tata", unlisted)
        assert prod_wildcard.approved_live_rows is not None

