"""Comprehensive tests for MoEngage WhatsApp bulk creation & draft worker."""

import copy
import json
import sys
import time
from unittest.mock import MagicMock, patch

import openpyxl
import pytest
from fastapi.testclient import TestClient
from api import app, get_current_user

import db
from backend.moengage_draft_creation import DraftCreation
from backend.moengage_whatsapp_worker import (
    automate_whatsapp_draft_batch,
    parse_cookie_string,
)
from scripts.bulk_whatsapp_creator import (
    automate_creation_via_playwright,
    main as bulk_main,
    parse_spreadsheet,
    print_banner,
)

USER = {
    "sub": "operator-wa",
    "tenant_id": "tata",
    "role": "operator",
    "email": "owner@example.com",
}

CATALOG_WA = {
    "account": "tata",
    "workspace_id": "tata-wa-workspace",
    "segments": [{"id": "seg-wa", "name": "WhatsApp Audience"}],
    "whatsapp_senders": [{"sender_name": "Tata Capital", "phone_number": "+919876543210", "provider": "KARIX"}],
    "whatsapp_templates": [{"id": "tpl-wa-100", "name": "pl_diwali_promo"}],
}

ROW_WA = {
    "account": "tata",
    "source_ref": "wa_rows.csv",
    "row_id": "row-wa-1",
    "channel": "WHATSAPP",
    "campaign_name": "Tata Diwali WA Offer",
    "segment_id": "seg-wa",
    "scheduled_at": "2026-10-15T10:00:00+05:30",
    "timezone": "Asia/Kolkata",
    "whatsapp_sender": "Tata Capital",
    "whatsapp_template_id": "tpl-wa-100",
}


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    test_db_path = tmp_path / "wa_test.db"
    monkeypatch.setattr(db, "DEFAULT_SQLITE_PATH", test_db_path)
    for name in ("DATABASE_URL", "POSTGRES_URL", "POSTGRESQL_URL"):
        monkeypatch.delenv(name, raising=False)
    db.init_database()
    return test_db_path


class FakeWhatsAppWriter:
    def __init__(self, campaign_id="fake-wa-id-12345"):
        self.calls = []
        self.campaign_id = campaign_id

    def create(self, payload, *, idempotency_key):
        self.calls.append(("create", idempotency_key, copy.deepcopy(payload)))
        return {"id": self.campaign_id, "status": "DRAFT"}


# -------------------------------------------------------------------------
# 1. scripts/bulk_whatsapp_creator.py tests
# -------------------------------------------------------------------------

def test_parse_spreadsheet_csv_filtering(tmp_path):
    csv_file = tmp_path / "campaigns.csv"
    csv_file.write_text(
        "campaign_name,channel,whatsapp_sender,whatsapp_template_id\n"
        "Diwali Loan,WHATSAPP,Tata Capital,tpl_001\n"
        "Car Loan Email,EMAIL,loans@tatacapital.com,tpl_002\n"
        "Personal Loan WA,whatsapp,Tata Capital,tpl_003\n"
        "SMS Blast,SMS,TATACAP,tpl_004\n",
        encoding="utf-8",
    )

    rows = parse_spreadsheet(str(csv_file))
    assert len(rows) == 2
    assert rows[0]["campaign_name"] == "Diwali Loan"
    assert rows[0]["whatsapp_template_id"] == "tpl_001"
    assert rows[1]["campaign_name"] == "Personal Loan WA"
    assert rows[1]["whatsapp_template_id"] == "tpl_003"


def test_parse_spreadsheet_xlsx_filtering(tmp_path):
    xlsx_file = tmp_path / "campaigns.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Campaigns"
    ws.append(["campaign_name", "channel", "whatsapp_sender", "whatsapp_template_id"])
    ws.append(["Festive WA", "WHATSAPP", "Tata Capital", "tpl_101"])
    ws.append(["Push Promo", "PUSH", "Tata Capital", "tpl_102"])
    ws.append(["Emergency WA", "WHATSAPP", "Tata Capital", "tpl_103"])
    wb.save(xlsx_file)

    rows = parse_spreadsheet(str(xlsx_file))
    assert len(rows) == 2
    assert rows[0]["campaign_name"] == "Festive WA"
    assert rows[1]["campaign_name"] == "Emergency WA"


def test_parse_spreadsheet_file_not_found():
    with pytest.raises(FileNotFoundError, match="File not found"):
        parse_spreadsheet("non_existent_spreadsheet.csv")


def test_parse_spreadsheet_invalid_extension(tmp_path):
    txt_file = tmp_path / "campaigns.txt"
    txt_file.write_text("dummy content", encoding="utf-8")
    with pytest.raises(ValueError, match="Supported formats: .csv or .xlsx"):
        parse_spreadsheet(str(txt_file))


def test_parse_spreadsheet_empty_xlsx(tmp_path):
    xlsx_file = tmp_path / "empty.xlsx"
    wb = openpyxl.Workbook()
    wb.save(xlsx_file)
    rows = parse_spreadsheet(str(xlsx_file))
    assert rows == []


def test_print_banner(capsys):
    print_banner(5, "my_campaigns.csv")
    captured = capsys.readouterr().out
    assert "MOENGAGE BULK WHATSAPP CAMPAIGN CREATOR" in captured
    assert "my_campaigns.csv" in captured
    assert "5 campaigns found" in captured
    assert "DRAFT ONLY" in captured


def test_bulk_main_no_whatsapp_rows(tmp_path, monkeypatch):
    csv_file = tmp_path / "no_wa.csv"
    csv_file.write_text(
        "campaign_name,channel\nEmail Blast,EMAIL\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["bulk_whatsapp_creator.py", str(csv_file)])
    with pytest.raises(SystemExit) as exc:
        bulk_main()
    assert exc.value.code == 0


def test_automate_creation_via_playwright_mock():
    campaigns = [
        {
            "campaign_name": "Test_WA_Camp",
            "segment_name": "Test_Segment",
            "whatsapp_sender": "Tata Capital",
            "whatsapp_template_id": "test_tpl",
        }
    ]

    mock_playwright = MagicMock()
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()

    mock_context.new_page.return_value = mock_page
    mock_browser.new_context.return_value = mock_context
    mock_browser.contexts = [mock_context]
    mock_playwright.chromium.launch.return_value = mock_browser
    mock_playwright.chromium.connect_over_cdp.return_value = mock_browser

    with patch.dict(
        "sys.modules",
        {"playwright.sync_api": MagicMock(sync_playwright=lambda: MagicMock(__enter__=lambda self: mock_playwright, __exit__=lambda *args: None))}
    ):
        automate_creation_via_playwright(campaigns, cdp_url="http://localhost:9222")

    mock_playwright.chromium.connect_over_cdp.assert_called_once_with("http://localhost:9222")
    mock_page.goto.assert_called_once()
    mock_browser.close.assert_called_once()


# -------------------------------------------------------------------------
# 2. backend/moengage_whatsapp_worker.py tests
# -------------------------------------------------------------------------

def test_parse_cookie_string():
    raw = "session_id=abc123; user=tata_operator; csrf=xyz"
    cookies = parse_cookie_string(raw, domain=".moengage.com")
    assert len(cookies) == 3
    assert cookies[0] == {"name": "session_id", "value": "abc123", "domain": ".moengage.com", "path": "/"}
    assert cookies[1] == {"name": "user", "value": "tata_operator", "domain": ".moengage.com", "path": "/"}
    assert cookies[2] == {"name": "csrf", "value": "xyz", "domain": ".moengage.com", "path": "/"}


def test_automate_whatsapp_draft_batch_not_found(isolated_db):
    with pytest.raises(LookupError, match="Batch not found"):
        automate_whatsapp_draft_batch("non-existent-batch", "tata", USER)


def test_automate_whatsapp_draft_batch_no_whatsapp_rows(isolated_db):
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO moengage_draft_batches (batch_id, account, workspace_id, creator_sub, creator_email, source_ref, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("b1", "tata", "tata-wa-workspace", USER["sub"], USER["email"], "test.csv", time.time()),
        )
        conn.execute(
            "INSERT INTO moengage_draft_batch_rows (batch_id, position, account, workspace_id, source_ref, row_id, channel, row_json, candidate_json, source_fields_json, status, issues_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("b1", 1, "tata", "tata-wa-workspace", "test.csv", "r1", "EMAIL", "{}", None, "{}", "preview_ready", "[]", time.time()),
        )

    res = automate_whatsapp_draft_batch("b1", "tata", USER)
    assert res["ok"] is True
    assert res["total"] == 0
    assert "No uncreated WhatsApp campaigns found" in res["message"]


def test_automate_whatsapp_draft_batch_direct_http_success(isolated_db, monkeypatch):
    source_fields = {
        "campaign_name": "Festive WhatsApp Promo",
        "segment_name": "Test Segment",
        "segment_id": "seg_123",
    }
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO moengage_draft_batches (batch_id, account, workspace_id, creator_sub, creator_email, source_ref, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("b2", "tata", "tata-wa-workspace", USER["sub"], USER["email"], "test.csv", time.time()),
        )
        conn.execute(
            "INSERT INTO moengage_draft_batch_rows (batch_id, position, account, workspace_id, source_ref, row_id, channel, row_json, candidate_json, source_fields_json, status, issues_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("b2", 1, "tata", "tata-wa-workspace", "test.csv", "row_wa_1", "WHATSAPP", "{}", None, json.dumps(source_fields), "preview_ready", "[]", time.time()),
        )

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"status": "success", "data": {"id": "moe_wa_cid_9999"}}

    with patch("backend.moengage_whatsapp_worker.requests.post", return_value=mock_resp), \
         patch("moengage_sync.get_moengage_auth_headers", return_value={"Authorization": "Bearer fake"}), \
         patch("moengage_sync.get_moengage_config", return_value={"base_url": "https://api-03.moengage.com"}):
        res = automate_whatsapp_draft_batch("b2", "tata", USER)
    assert res["ok"] is True
    assert res["created"] == 1
    assert res["results"][0]["id"] == "moe_wa_cid_9999"

    # Verify DB update
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT status, campaign_id FROM moengage_draft_batch_rows WHERE batch_id='b2' AND row_id='row_wa_1'"
        ).fetchone()
        assert row["status"] == "VALIDATED"
        assert row["campaign_id"] == "moe_wa_cid_9999"


# -------------------------------------------------------------------------
# 3. backend/moengage_draft_creation.py WhatsApp tests
# -------------------------------------------------------------------------

def test_draft_creation_whatsapp_via_test_writer(isolated_db):
    writer = FakeWhatsAppWriter(campaign_id="test-wa-draft-1234")
    worker = DraftCreation("tata", USER, CATALOG_WA, writer, allow_sqlite_for_tests=True)

    result = worker.create(ROW_WA)
    assert result["state"] == "VALIDATED"
    assert result["campaign_id"] == "test-wa-draft-1234"
    assert result["validation_errors"] == []
    assert len(writer.calls) == 1
    assert writer.calls[0][0] == "create"

    # Idempotency: repeating create() returns stored result without another writer call
    repeat = worker.create(ROW_WA)
    assert repeat["state"] == "VALIDATED"
    assert repeat["campaign_id"] == "test-wa-draft-1234"
    assert len(writer.calls) == 1


def test_draft_creation_whatsapp_via_http_api_success(isolated_db):
    class NoOpWriter:
        pass

    worker = DraftCreation("tata", USER, CATALOG_WA, NoOpWriter(), allow_sqlite_for_tests=True)

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"status": "success", "data": {"id": "http_wa_cid_555"}}

    with patch("requests.post", return_value=mock_resp), \
         patch("moengage_sync.get_moengage_auth_headers", return_value={"Authorization": "Bearer fake"}), \
         patch("moengage_sync.get_moengage_config", return_value={"base_url": "https://api-03.moengage.com"}):
        result = worker.create(ROW_WA)

    assert result["state"] == "VALIDATED"
    assert result["campaign_id"] == "http_wa_cid_555"
def test_draft_creation_whatsapp_via_http_api_fallback_on_error(isolated_db):
    class NoOpWriter:
        pass

    worker = DraftCreation("tata", USER, CATALOG_WA, NoOpWriter(), allow_sqlite_for_tests=True)

    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 500

    with patch("requests.post", return_value=mock_resp), \
         patch("moengage_sync.get_moengage_auth_headers", return_value={"Authorization": "Bearer fake"}), \
         patch("moengage_sync.get_moengage_config", return_value={"base_url": "https://api-03.moengage.com"}):
        result = worker.create(ROW_WA)

    assert result["state"] == "VALIDATED"
    assert result["campaign_id"].startswith("WA-")

# -------------------------------------------------------------------------
# 4. API endpoint tests for /automate-whatsapp
# -------------------------------------------------------------------------

def test_api_automate_whatsapp_endpoint_success():
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: USER
    try:
        with patch("moengage_whatsapp_worker.automate_whatsapp_draft_batch", return_value={"ok": True, "created": 3}):
            resp = client.post(
                "/api/moengage/drafts/batches/batch-test-123/automate-whatsapp",
                data={"account": "tata"},
            )
            assert resp.status_code == 200
            assert resp.json() == {"ok": True, "created": 3}
    finally:
        app.dependency_overrides.clear()


def test_api_automate_whatsapp_endpoint_not_found():
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: USER
    try:
        with patch("moengage_whatsapp_worker.automate_whatsapp_draft_batch", side_effect=LookupError("Batch not found")):
            resp = client.post(
                "/api/moengage/drafts/batches/batch-test-404/automate-whatsapp",
                data={"account": "tata"},
            )
            assert resp.status_code == 404
            assert "Batch not found" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_api_automate_whatsapp_endpoint_permission_denied():
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: USER
    try:
        with patch("moengage_whatsapp_worker.automate_whatsapp_draft_batch", side_effect=PermissionError("Account access denied")):
            resp = client.post(
                "/api/moengage/drafts/batches/batch-test-423/automate-whatsapp",
                data={"account": "tata"},
            )
            assert resp.status_code == 423
            assert "Account access denied" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()
