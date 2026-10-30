"""Native brief extraction is offline; only explicitly reviewed copy can enter the queue."""

import io
import json
import re

import openpyxl
import pytest
from fastapi.testclient import TestClient

import api
import db_queue
import sms_dlt
import vilpower_client


def workbook_bytes():
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "November"
    sheet.append(["Channel", "Content", "Characters"])
    sheet.append(["SMS", " Dear <Name>,\r\nYour offer is ready. ", 40])
    sheet.append(["WA", "Not SMS content", None])
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def no_provider(*args, **kwargs):
    pytest.fail("Brief extraction or unreviewed submission accessed VILPOWER")


def reviewed_draft():
    return {
        "template_name": "reviewed_november_copy", "text": " Dear {#alp#},\r\nYour offer is ready. ",
        "template_type": "1", "category_id": "financial", "header_id": "header", "header": "TATAXX",
        "message_type": "1", "sample_message": " Dear Guest,\r\nYour offer is ready. ",
        "source_file": "November client brief.xlsx", "source_ref": "November!B2",
        "brief": {
            "original_text": " Dear <Name>,\r\nYour offer is ready. ",
            "sources": [{"sheet": "November", "cell": "B2", "campaign": "November retention",
                         "segment": "Non-clicker", "language": "English"}],
            "warnings": [], "variables": [{"token": "<Name>", "kind": "alp", "sample": "Guest"}],
            "acknowledged": True,
        },
    }


def test_native_brief_upload_extracts_exact_sms_without_a_portal_session(provision_user, monkeypatch):
    _, headers = provision_user("tata")
    monkeypatch.setattr(vilpower_client.requests.Session, "request", no_provider)
    client = TestClient(api.app, headers=headers)
    response = client.post("/api/sms-dlt/brief?account=tata", files={"file": ("client.xlsx", workbook_bytes())})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["filename"] == "client.xlsx"
    assert [(item["sheet"], item["cell"], item["text"]) for item in result["candidates"]] == [
        ("November", "B2", " Dear <Name>,\r\nYour offer is ready. "),
    ]
    assert result["candidates"][0]["variables"] == ["<Name>"]


@pytest.mark.parametrize("tenant,account,status", [("bajaj", "tata", 403), ("all", "bajaj", 400)])
def test_brief_upload_cannot_cross_destination_scope(provision_user, tenant, account, status):
    _, headers = provision_user(tenant, role="superadmin" if tenant == "all" else "operator")
    response = TestClient(api.app, headers=headers).post(
        f"/api/sms-dlt/brief?account={account}", files={"file": ("client.xlsx", workbook_bytes())})
    assert response.status_code == status


def test_brief_upload_requires_authentication():
    response = TestClient(api.app).post(
        "/api/sms-dlt/brief?account=tata", files={"file": ("client.xlsx", workbook_bytes())})
    assert response.status_code == 401


@pytest.mark.parametrize("filename,contents,reason", [
    ("bad.xlsx", b"not a workbook", r"(?i)workbook|excel|xlsx"),
    ("empty.xlsx", b"", r"(?i)empty"),
    ("brief.csv", b"Channel,Content", r"(?i)xlsx.*xls"),
])
def test_invalid_brief_upload_returns_actionable_error(provision_user, filename, contents, reason):
    _, headers = provision_user("tata")
    response = TestClient(api.app, headers=headers).post(
        "/api/sms-dlt/brief?account=tata", files={"file": (filename, contents)})
    assert response.status_code == 400
    assert re.search(reason, response.json()["detail"])


def test_oversized_brief_is_rejected_before_parsing(provision_user):
    _, headers = provision_user("tata")
    response = TestClient(api.app, headers=headers).post(
        "/api/sms-dlt/brief?account=tata", files={"file": ("large.xlsx", b"x" * (20 * 1024 * 1024 + 1))})
    assert response.status_code == 413


def test_unreviewed_brief_cannot_enter_queue_or_contact_provider(monkeypatch):
    row = reviewed_draft()
    row["brief"]["acknowledged"] = False
    monkeypatch.setattr(vilpower_client, "fetch_sms_templates", no_provider)
    with pytest.raises(ValueError, match="(?i)review|acknowledge"):
        sms_dlt.stage_batch([row], "tata", "Operator", "reviewed drafts")


def test_reviewed_brief_retains_exact_copy_and_original_source_in_durable_job(monkeypatch):
    monkeypatch.setattr(vilpower_client, "fetch_sms_templates", lambda **kwargs: [])
    row = reviewed_draft()
    job = sms_dlt.stage_batch([row], "tata", "Operator", "reviewed drafts")
    task = db_queue.get_job_tasks(job["id"])[0]
    stored = json.loads(task["payload_json"])
    assert task["source_ref"] == "November!B2"
    assert stored["source_file"] == "November client brief.xlsx"
    assert stored["text"] == " Dear {#alp#},\r\nYour offer is ready. "
    assert stored["brief"]["original_text"] == " Dear <Name>,\r\nYour offer is ready. "
    assert stored["brief"]["sources"][0]["campaign"] == "November retention"
    assert stored["brief"]["variables"][0] == {"token": "<Name>", "kind": "alp", "sample": "Guest"}
    assert task["status"] == "PENDING"
