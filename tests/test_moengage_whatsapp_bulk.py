"""Offline WhatsApp regressions: exact selection, durable readback and gated batches."""

import copy
import json
from unittest.mock import patch

import openpyxl
import pytest

import db
import moengage_draft_batches as batches
from moengage_draft_batches import DraftBatchQueue
from moengage_draft_creation import DraftCreation
from moengage_whatsapp_worker import automate_whatsapp_draft_batch
from scripts.bulk_whatsapp_creator import parse_spreadsheet

USER = {"sub": "operator-wa", "tenant_id": "tata", "role": "operator", "email": "owner@example.com"}
SENDER_ID = "685a47bfadfdfd854f960ab5"
TEMPLATE_ID = "685a47bfadfdfd854f960ab6"
CATALOG_WA = {
    "account": "tata", "workspace_id": "tata-wa-workspace",
    "segments": [{"id": "seg-wa", "name": "WhatsApp Audience"}],
    "whatsapp_senders": [
        {"id": "685a47bfadfdfd854f960ab7", "sender_name": "Other sender", "provider": "OTHER", "phone_number": "+910000000000"},
        {"id": SENDER_ID, "sender_id": SENDER_ID, "sender_name": "Tata Capital", "phone_number": "+919876543210", "provider": "KARIX"},
    ],
    "whatsapp_templates": [
        {"id": "685a47bfadfdfd854f960ab8", "name": "other_template"},
        {"id": TEMPLATE_ID, "name": "pl_diwali_promo"},
    ],
}
ROW_WA = {
    "account": "tata", "source_ref": "wa_rows.csv", "row_id": "row-wa-1", "channel": "WHATSAPP",
    "workspace_id": "tata-wa-workspace",
    "campaign_name": "Tata Diwali WA Offer", "segment_id": "seg-wa",
    "scheduled_at": "2026-10-15T10:00:00+05:30", "timezone": "Asia/Kolkata",
    "whatsapp_sender": "Tata Capital", "whatsapp_sender_id": SENDER_ID,
    "whatsapp_template_id": TEMPLATE_ID, "whatsapp_template_name": "pl_diwali_promo",
    "whatsapp_placeholders": json.dumps({"1": "Naman", "2": "Diwali offer"}),
}


@pytest.fixture(autouse=True)
def offline_row_catalog(monkeypatch):
    def catalog_for_row(account, user, row, default_catalog):
        if str(row.get("channel", "")).upper() != "WHATSAPP":
            return default_catalog
        if account != "tata" or row.get("workspace_id") != CATALOG_WA["workspace_id"]:
            raise ValueError("An explicit known WhatsApp workspace is required")
        return copy.deepcopy(CATALOG_WA)

    monkeypatch.setattr(batches, "catalog_for_row", catalog_for_row)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_SQLITE_PATH", tmp_path / "wa_test.db")
    for name in ("DATABASE_URL", "POSTGRES_URL", "POSTGRESQL_URL"):
        monkeypatch.delenv(name, raising=False)
    db.init_database()


class WhatsAppWriter:
    """In-memory remote store; create acknowledgement alone is never verification."""

    def __init__(self, *, mismatch=None, create_error=None, readback_error=False, campaign_id=None):
        self.calls = []
        self.payloads = {}
        self.mismatch = mismatch
        self.create_error = create_error
        self.readback_error = readback_error
        self.campaign_id = campaign_id

    def create(self, payload, *, idempotency_key):
        self.calls.append(("create", idempotency_key))
        if self.create_error:
            raise self.create_error
        campaign_id = self.campaign_id or f"{len(self.payloads) + 1:024x}"
        self.payloads[campaign_id] = copy.deepcopy(payload)
        return {"id": campaign_id, "status": "DRAFT"}

    def get(self, campaign_id):
        self.calls.append(("get", campaign_id))
        if self.readback_error:
            raise TimeoutError("readback temporarily unavailable")
        result = {**copy.deepcopy(self.payloads[campaign_id]), "id": campaign_id, "status": "DRAFT"}
        if self.mismatch:
            path, value = self.mismatch
            target = result
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
        return result

    def validate(self, campaign_id):
        raise AssertionError("WhatsApp verification must use GET, not validate")


def service(writer):
    return DraftCreation("tata", USER, CATALOG_WA, writer, allow_sqlite_for_tests=True)


def queue(writer):
    return DraftBatchQueue("tata", USER, CATALOG_WA, allow_sqlite_for_tests=True, creator=service(writer))


def test_verified_draft_has_exact_selection_and_durable_idempotency(isolated_db):
    writer = WhatsAppWriter()
    result = service(writer).create(ROW_WA)
    assert result["state"] == "VERIFIED"
    assert result["campaign_id"] == "000000000000000000000001"
    assert [name for name, _ in writer.calls] == ["create", "get"]
    payload = writer.payloads[result["campaign_id"]]
    assert payload["channel"] == "WHATSAPP"
    assert payload["basic_details"]["name"] == ROW_WA["campaign_name"]
    assert "seg-wa" in json.dumps(payload["segmentation_details"])
    wa = payload["campaign_content"]["content"]["whatsapp"]
    assert wa["sender_id"] == SENDER_ID
    assert wa["provider"] == "KARIX"
    assert wa["template_id"] == TEMPLATE_ID
    assert wa["body_placeholders"] == json.loads(ROW_WA["whatsapp_placeholders"])
    assert service(writer).create(ROW_WA) == result
    assert [name for name, _ in writer.calls] == ["create", "get"]
    with db.get_db() as conn:
        attempt = conn.execute("SELECT state,campaign_id FROM moengage_draft_attempts").fetchone()
    assert dict(attempt) == {"state": "VERIFIED", "campaign_id": result["campaign_id"]}


@pytest.mark.parametrize("path,value", [
    (("status",), "PUBLISHED"),
    (("channel",), "EMAIL"),
    (("basic_details", "name"), "Wrong campaign"),
    (("segmentation_details",), {"segment_id": "wrong-audience"}),
    (("campaign_content", "content", "whatsapp", "sender_id"), "685a47bfadfdfd854f960ab7"),
    (("campaign_content", "content", "whatsapp", "provider"), "OTHER"),
    (("campaign_content", "content", "whatsapp", "template_id"), "685a47bfadfdfd854f960ab8"),
    (("campaign_content", "content", "whatsapp", "body_placeholders"), {"1": "Wrong recipient"}),
])
def test_readback_mismatch_requires_review_without_repost(isolated_db, path, value):
    writer = WhatsAppWriter(mismatch=(path, value))
    result = service(writer).create(ROW_WA)
    assert result["state"] == "NEEDS_REVIEW"
    assert result["campaign_id"] == "000000000000000000000001"
    assert service(writer).create(ROW_WA)["state"] == "NEEDS_REVIEW"
    assert [name for name, _ in writer.calls] == ["create", "get"]


def test_failed_readback_preserves_created_and_resumes_after_reconstruction(isolated_db):
    writer = WhatsAppWriter(readback_error=True)
    first = service(writer).create(ROW_WA)
    assert first["state"] == "CREATED"
    assert first["campaign_id"] == "000000000000000000000001"
    with db.get_db() as conn:
        attempt = conn.execute("SELECT state,campaign_id FROM moengage_draft_attempts").fetchone()
    assert dict(attempt) == {"state": "CREATED", "campaign_id": first["campaign_id"]}
    writer.readback_error = False
    resumed = service(writer).create(ROW_WA)
    assert resumed["state"] == "VERIFIED"
    assert resumed["campaign_id"] == first["campaign_id"]
    assert [name for name, _ in writer.calls] == ["create", "get", "get"]


def test_create_timeout_is_durable_uncertain_and_never_reposts(isolated_db):
    writer = WhatsAppWriter(create_error=TimeoutError("POST outcome unknown"))
    first = service(writer).create(ROW_WA)
    assert first["state"] == "UNCERTAIN"
    assert first["campaign_id"] is None
    assert service(writer).create(ROW_WA)["state"] == "UNCERTAIN"
    assert writer.calls == [("create", writer.calls[0][1])]
    with pytest.raises(ValueError, match="already reserved"):
        service(writer).create({**ROW_WA, "campaign_name": "Changed after timeout"})
    assert len(writer.calls) == 1


@pytest.mark.parametrize("campaign_id", ["WA-invented-success", "not-a-provider-id", ""])
def test_invalid_create_id_never_reports_success_or_synthesizes_id(isolated_db, campaign_id):
    writer = WhatsAppWriter(campaign_id=campaign_id)
    # Empty acknowledgement must stay empty rather than use the fake's normal ID generation.
    if not campaign_id:
        writer.campaign_id = None
        def empty_create(payload, *, idempotency_key):
            writer.calls.append(("create", idempotency_key))
            return {"status": "DRAFT"}
        writer.create = empty_create
    result = service(writer).create(ROW_WA)
    assert result["state"] not in {"VERIFIED", "VALIDATED"}
    assert not result.get("campaign_id")
    service(writer).create(ROW_WA)
    assert [name for name, _ in writer.calls] == ["create"]


@pytest.mark.parametrize("changes", [
    {"whatsapp_sender": "", "whatsapp_sender_id": ""},
    {"whatsapp_template_id": "", "whatsapp_template_name": ""},
    {"whatsapp_sender_id": "685a47bfadfdfd854f960ab7"},
    {"whatsapp_template_id": "ffffffffffffffffffffffff"},
])
def test_unresolved_or_conflicting_selection_blocks_before_post(isolated_db, changes):
    writer = WhatsAppWriter()
    batch_queue = queue(writer)
    batch = batch_queue.stage([{**ROW_WA, **changes}], ROW_WA["source_ref"])
    assert batch["items"][0]["status"] == "blocked"
    batch_queue.create_row(batch["batch_id"], ROW_WA["row_id"])
    assert writer.calls == []


def test_bulk_uses_gated_queue_and_skips_blocked_uncertain_verified_rows(isolated_db):
    writer = WhatsAppWriter()
    batch_queue = queue(writer)
    rows = [{**ROW_WA, "row_id": name, "campaign_name": name} for name in ("verified", "uncertain", "ready")]
    rows.append({**ROW_WA, "row_id": "blocked", "segment_id": "missing-audience"})
    staged = batch_queue.stage(rows, ROW_WA["source_ref"])
    assert (staged["ready"], staged["blocked"]) == (3, 1)
    batch_id = staged["batch_id"]
    batch_queue.create_row(batch_id, "verified")
    writer.create_error = TimeoutError("ambiguous POST")
    batch_queue.create_row(batch_id, "uncertain")
    writer.create_error = None
    calls_before = list(writer.calls)
    with patch("moengage_whatsapp_worker.DraftBatchQueue", return_value=batch_queue), \
         patch("moengage_whatsapp_worker.load_server_catalog", return_value=CATALOG_WA):
        result = automate_whatsapp_draft_batch(batch_id, "tata", USER)
        repeated = automate_whatsapp_draft_batch(batch_id, "tata", USER)
    assert result["ok"] is True
    assert (result["total"], result["created"], result["failed"]) == (1, 1, 0)
    assert repeated["created"] == 0
    assert [name for name, _ in writer.calls[len(calls_before):]] == ["create", "get"]
    assert writer.calls[-1] == ("get", "000000000000000000000002")
    states = {item["row_id"]: item for item in batch_queue.get(batch_id)["items"]}
    assert {key: item["status"] for key, item in states.items()} == {
        "verified": "VERIFIED", "uncertain": "UNCERTAIN", "ready": "VERIFIED", "blocked": "blocked",
    }
    assert states["uncertain"]["campaign_id"] is None
    assert states["blocked"]["campaign_id"] is None
    assert states["blocked"]["source_fields"]["segment_id"] == "missing-audience"


def test_bulk_reports_readback_failure_as_not_created(isolated_db):
    writer = WhatsAppWriter(readback_error=True)
    batch_queue = queue(writer)
    batch = batch_queue.stage([ROW_WA], ROW_WA["source_ref"])
    with patch("moengage_whatsapp_worker.DraftBatchQueue", return_value=batch_queue), \
         patch("moengage_whatsapp_worker.load_server_catalog", return_value=CATALOG_WA):
        result = automate_whatsapp_draft_batch(batch["batch_id"], "tata", USER)
    assert result["created"] == 0
    assert result["failed"] == 1
    row = batch_queue.get(batch["batch_id"])["items"][0]
    assert row["status"] == "CREATED"
    assert row["campaign_id"] == "000000000000000000000001"


def test_parse_spreadsheet_csv_filtering(tmp_path):
    path = tmp_path / "campaigns.csv"
    path.write_text(
        "campaign_name,channel,whatsapp_sender,whatsapp_template_id,workspace\n"
        "Diwali Loan,WHATSAPP,Tata Capital,tpl_001,Services_TC\n"
        "Car Loan Email,EMAIL,loans@example.com,tpl_002,\n"
        "Personal Loan WA,whatsapp,Tata Capital,tpl_003,Tata Capital\n"
        "SMS Blast,SMS,TATACAP,tpl_004,\n", encoding="utf-8",
    )
    rows = parse_spreadsheet(str(path))
    assert [(row["campaign_name"], row["whatsapp_template_id"]) for row in rows] == [
        ("Diwali Loan", "tpl_001"), ("Personal Loan WA", "tpl_003"),
    ]
    assert [row["workspace"] for row in rows] == ["Services_TC", "Tata Capital"]


def test_parse_spreadsheet_xlsx_filtering(tmp_path):
    path = tmp_path / "campaigns.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["campaign_name", "channel", "whatsapp_sender", "whatsapp_template_id", "workspace"])
    sheet.append(["Festive WA", "WHATSAPP", "Tata Capital", "tpl_101", "Services_TC"])
    sheet.append(["Push Promo", "PUSH", "Tata Capital", "tpl_102", ""])
    sheet.append(["Emergency WA", "WHATSAPP", "Tata Capital", "tpl_103", "Tata Capital"])
    workbook.save(path)
    rows = parse_spreadsheet(str(path))
    assert [(row["campaign_name"], row["whatsapp_template_id"]) for row in rows] == [
        ("Festive WA", "tpl_101"), ("Emergency WA", "tpl_103"),
    ]
    assert [row["workspace"] for row in rows] == ["Services_TC", "Tata Capital"]


def test_parse_spreadsheet_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_spreadsheet(str(tmp_path / "missing.csv"))


def test_parse_spreadsheet_invalid_extension(tmp_path):
    path = tmp_path / "campaigns.txt"
    path.write_text("invalid format", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_spreadsheet(str(path))


def test_parse_spreadsheet_empty_xlsx(tmp_path):
    path = tmp_path / "empty.xlsx"
    openpyxl.Workbook().save(path)
    assert parse_spreadsheet(str(path)) == []
