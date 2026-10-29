"""DLT registration owns its destination, exact copy, approval and durable dispatch."""

import asyncio
import csv

import pytest
from fastapi.testclient import TestClient

import api
import db
import db_queue
import sms_dlt
from models import ApprovalStatus, SubmissionResult, SubmissionStatus
from queue_manager import QueueManager


def draft(name="tata_sms", text="Your application is being processed.", **fields):
    return {"template_name": name, "text": text, "template_type": "1", "category_id": "category-id",
            "header_id": "header-id", "header": "HLTATA", "message_type": "1", "sample_message": text, **fields}


def live(name="tata_sms", text="Your application is being processed.", status="pending", ref="dlt-1"):
    return {"template_name": name, "template_message": text, "status": status, "template_id": ref, "header": "HLTATA"}


def inventory(monkeypatch, rows):
    import vilpower_client
    monkeypatch.setattr(vilpower_client, "fetch_sms_templates", lambda **kwargs: rows)


def test_import_preserves_dlt_whitespace_and_rejects_other_account(tmp_path):
    path = tmp_path / "templates.csv"
    text = " Dear customer,\namount  {#num#}. "
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["template_name", "text"])
        writer.writeheader()
        writer.writerow({"template_name": "tata_sms", "text": text})
    assert sms_dlt.load_drafts(str(path))[0]["text"] == text
    with pytest.raises(ValueError, match="only for Tata"):
        sms_dlt.load_drafts(str(path), "bajaj")
    with pytest.raises(ValueError, match="account"):
        sms_dlt.draft_from_row({**draft(), "account": "bajaj"})


def test_identification_distinguishes_pending_drift_and_exact_copy(monkeypatch):
    inventory(monkeypatch, [live(), live("approved", status="approved"), live("rejected", status="rejected")])
    report = sms_dlt.identify_drafts([draft(), draft("approved"), draft("rejected"),
                                    draft("missing", text="Different content."),
                                    draft("TATA_SMS", text="Your  application is being processed.")])
    assert [item["status"] for item in report["items"]] == [
        "PENDING", "WHITELISTED", "REJECTED", "NOT_WHITELISTED", "CONTENT_DRIFT"]
    assert report["whitelisted_count"] == 1
    assert report["missing_templates"][0]["template_name"] == "missing"


def test_repeated_portal_names_preserve_ids_and_match_exact_body_header(monkeypatch):
    rows = [
        live(status="approved", ref="dlt-approved"),
        live(text="Different registered copy.", ref="dlt-other-copy"),
        {**live(status="approved", ref="dlt-other-header"), "header": "OTHERT"},
    ]
    inventory(monkeypatch, rows)
    assert {item["template_id"] for item in sms_dlt.merged_inventory()} == {
        "dlt-approved", "dlt-other-copy", "dlt-other-header"}
    job = sms_dlt.stage_batch([draft()], "tata", "Tester", "drafts.csv")
    assert db_queue.get_job_tasks(job["id"])[0]["provider_ref_id"] == "dlt-approved"
    report = sms_dlt.identify_drafts([draft()])
    assert report["items"][0]["live_fb_id"] == "dlt-approved"
    assert report["items"][0]["status"] == "WHITELISTED"


def test_existing_pending_is_duplicate_not_approved_or_dispatched(monkeypatch):
    inventory(monkeypatch, [live()])
    job = sms_dlt.stage_batch([draft()], "tata", "Tester", "drafts.csv")
    task = db_queue.get_job_tasks(job["id"])[0]
    assert (task["status"], task["approval_status"], task["provider_ref_id"]) == ("DUPLICATE", "pending", "dlt-1")
    assert job["submitted_count"] == 0 and job["duplicate_count"] == 1
    assert db_queue.claim_task(task["id"], "tata", "sms") is None
    with pytest.raises(ValueError, match="different DLT content"):
        sms_dlt.stage_batch([draft(text="Changed registered copy.")], "tata", "Tester", "drafts.csv")
    with pytest.raises(ValueError, match="different header"):
        sms_dlt.stage_batch([draft(header="OTHERT")], "tata", "Tester", "drafts.csv")


def test_mixed_copies_with_same_name_fail_without_staging(monkeypatch):
    inventory(monkeypatch, [])
    with pytest.raises(ValueError, match="different SMS DLT fields"):
        sms_dlt.stage_batch([draft(), draft(text="Another message.")], "tata", "Tester", "drafts.csv")
    with db.get_db() as conn:
        assert conn.execute("SELECT count(*) AS n FROM ingestion_jobs WHERE channel='sms'").fetchone()["n"] == 0


def test_sms_worker_ignores_karix_auth_circuit_and_never_replays(monkeypatch):
    import vilpower_client
    inventory(monkeypatch, [])
    job = sms_dlt.stage_batch([draft()], "tata", "Tester", "drafts.csv")
    submitted = []

    def submit(row, client):
        submitted.append(row["template_name"])
        return SubmissionResult(source_ref=row["source_ref"], template_name=row["template_name"],
                                status=SubmissionStatus.FAILED, approval_status=ApprovalStatus.UNKNOWN,
                                error="Provider outcome unknown; reconcile before retrying.", client=client, channel="sms")

    monkeypatch.setattr(vilpower_client, "submit_sms_template", submit)
    manager = QueueManager()
    manager._auth_circuits["tata"] = True
    asyncio.run(manager._process_job_tasks(job["id"], "tata", "sms"))
    asyncio.run(manager._process_job_tasks(job["id"], "tata", "sms"))
    assert submitted == ["tata_sms"]
    assert manager._auth_circuits["tata"] is True
    result = db_queue.get_job(job["id"])
    assert (result["status"], result["failed_count"], result["submitted_count"]) == ("FAILED", 1, 0)
    with pytest.raises(ValueError, match="Tata Capital"):
        db_queue.create_job_with_tasks("bajaj", "sms", "bad.csv", "Tester", [draft()])


def test_poll_updates_exact_dlt_id_only_and_never_reverses_terminal(monkeypatch):
    inventory(monkeypatch, [])
    job = sms_dlt.stage_batch([draft()], "tata", "Tester", "drafts.csv")
    task = db_queue.get_job_tasks(job["id"])[0]
    db_queue.claim_task(task["id"], "tata", "sms")
    db_queue.record_task_result(task["id"], "submitted", "pending", provider_ref_id="dlt-1")
    inventory(monkeypatch, [live(status="approved", ref="wrong-id")])
    assert sms_dlt.poll_approvals() == {"checked": 1, "updated": 0}
    inventory(monkeypatch, [live(status="approved")])
    assert sms_dlt.poll_approvals() == {"checked": 1, "updated": 1}
    inventory(monkeypatch, [live(status="pending")])
    assert sms_dlt.poll_approvals() == {"checked": 0, "updated": 0}
    assert db_queue.get_job_tasks(job["id"])[0]["approval_status"] == "approved"


def test_sms_api_is_authenticated_and_rejects_bajaj_identity(provision_user):
    _, headers = provision_user("bajaj")
    client = TestClient(api.app)
    assert client.get("/api/sms-dlt/session?account=tata").status_code == 401
    assert client.get("/api/sms-dlt/session?account=tata", headers=headers).status_code == 403
    assert client.post("/api/sms-dlt/submit", headers=headers, json={
        "account": "tata", "expected_account": "tata", "expected_channel": "sms", "templates": [draft()],
    }).status_code == 403


def test_jira_sms_keeps_typed_variables_urls_and_distinct_long_copies():
    from briefing_parser import parse_jira_brief
    text = "Hello {#alp#}, amount  {#num#}. Visit https://example.test. " + "A" * 160
    other = text + " Different ending."
    brief = parse_jira_brief({
        "key": "TCN-99999", "summary": "Tata Capital SMS",
        "description_text": f"SMS | {text}\nSMS | {other}",
        "attachments": [], "comments": [],
    }, download_creatives=False)
    assert [item["text"] for item in brief.sms_templates] == [text, other]
