"""DLT registration owns its destination, exact copy, approval and durable dispatch."""

import asyncio
import csv
import json

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
    from vilpower_client import TATA_ENTITY_ID
    return {"template_name": name, "template_message": text, "status": status, "template_id": ref,
            "header": "HLTATA", "entity_id": TATA_ENTITY_ID, "provider": "vilpower"}


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


@pytest.mark.parametrize("placeholder", ["<name>", "<link>", "<url>", "{#alphanumeric#}", "{#url#}"])
def test_preview_explains_unprepared_placeholders_without_rewriting_copy(monkeypatch, placeholder):
    inventory(monkeypatch, [])
    text = f"Hello {placeholder}."
    preview = sms_dlt.preview_drafts([draft(text=text, sample_message="Hello Example.")])[0]
    assert preview["status"] == "INVALID"
    assert preview["components"][0]["text"] == text
    assert preview["sms_dlt"]["text"] == text
    assert len(preview["compliance_warnings"]) == 1
    assert "Prepare placeholders" in preview["compliance_warnings"][0]["issue"]


def test_preview_allows_exact_repeats_and_stage_skips_only_the_repeat(monkeypatch):
    inventory(monkeypatch, [])
    rows = [draft(source_ref="sheet:2"), draft(source_ref="sheet:3")]
    previews = sms_dlt.preview_drafts(rows)
    assert [item["status"] for item in previews] == ["VALID", "VALID"]
    assert all(not item["compliance_warnings"] for item in previews)
    job = sms_dlt.stage_batch(rows, "tata", "Tester", "drafts.csv")
    assert job["duplicate_count"] == 1
    assert [item["status"] for item in db_queue.get_job_tasks(job["id"])] == ["PENDING", "DUPLICATE"]


@pytest.mark.parametrize("fields", [{"text": "Another message.", "sample_message": "Another message."},
                                  {"header": "OTHERT"}, {"category_id": "other-category"}])
def test_preview_rejects_same_name_with_different_dlt_fields(monkeypatch, fields):
    inventory(monkeypatch, [])
    previews = sms_dlt.preview_drafts([draft(), draft(**fields)])
    assert previews[1]["status"] == "INVALID"
    assert any("different SMS DLT fields" in warning["issue"]
               for warning in previews[1]["compliance_warnings"])
    with pytest.raises(ValueError, match="different SMS DLT fields"):
        sms_dlt.stage_batch([draft(), draft(**fields)], "tata", "Tester", "drafts.csv")


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


def uncertain_task(monkeypatch, **fields):
    inventory(monkeypatch, [])
    job = sms_dlt.stage_batch([draft(**fields)], "tata", "Tester", "drafts.csv")
    task = db_queue.get_job_tasks(job["id"])[0]
    db_queue.claim_task(task["id"], "tata", "sms")
    db_queue.record_task_result(
        task["id"], "failed", "unknown",
        error="Registration outcome unknown. Do not resubmit automatically; reconcile VILPOWER inventory before a new review.",
        result_payload={"provider_response": {"provider": "vilpower", "registration_attempted": True,
                                            "outcome": "unknown", "retry_safe": False}},
    )
    return job, task


def test_refresh_recovers_approved_unknown_without_registration_and_repairs_durable_counts(monkeypatch):
    import vilpower_client
    job, task = uncertain_task(monkeypatch)
    inventory(monkeypatch, [live(status="approved")])
    monkeypatch.setattr(vilpower_client, "submit_sms_template",
                        lambda *args, **kwargs: pytest.fail("Reconciliation must not register"))
    assert sms_dlt.reconcile_job(job["id"]) == {"checked": 1, "updated": 1}
    stored = db_queue.get_job_task(task["id"])
    payload = json.loads(stored["payload_json"])
    assert (stored["status"], stored["approval_status"], stored["provider_ref_id"], stored["error"]) == (
        "SUBMITTED", "approved", "dlt-1", None)
    assert payload["provider_response"]["outcome"] == "verified"
    assert payload["provider_response"]["retry_safe"] is False
    assert payload["error"] is None
    summary = db_queue.get_job(job["id"])
    assert (summary["status"], summary["submitted_count"], summary["failed_count"]) == ("COMPLETED", 1, 0)
    assert sms_dlt.load_history()[0]["error"] is None
    assert sms_dlt.reconcile_job(job["id"]) == {"checked": 0, "updated": 0}
    assert db_queue.claim_task(task["id"], "tata", "sms") is None


@pytest.mark.parametrize("changes", [
    {"template_name": "TATA_SMS"}, {"template_message": "Your  application is being processed."},
    {"header": "OTHERT"}, {"entity_id": "1101000000000000000"}, {"provider": "other"},
])
def test_unknown_recovery_never_adopts_mismatched_identity(monkeypatch, changes):
    job, task = uncertain_task(monkeypatch)
    inventory(monkeypatch, [{**live(status="approved"), **changes}])
    assert sms_dlt.reconcile_job(job["id"]) == {"checked": 1, "updated": 0}
    stored = db_queue.get_job_task(task["id"])
    assert (stored["status"], stored["approval_status"], stored["provider_ref_id"]) == ("FAILED", "unknown", None)
    assert "unknown" in stored["error"]


def test_delayed_inventory_stays_unknown_blocks_resubmission_then_recovers(monkeypatch):
    job, task = uncertain_task(monkeypatch)
    assert sms_dlt.poll_approvals() == {"checked": 1, "updated": 0}
    with pytest.raises(ValueError, match="outcome unknown"):
        sms_dlt.stage_batch([draft()], "tata", "Tester", "retry.csv", skip_duplicates=False)
    inventory(monkeypatch, [live(status="approved")])
    assert sms_dlt.poll_approvals() == {"checked": 1, "updated": 1}
    duplicate_job = sms_dlt.stage_batch([draft()], "tata", "Tester", "retry.csv", skip_duplicates=False)
    assert db_queue.get_job_tasks(duplicate_job["id"])[0]["status"] == "DUPLICATE"
    assert db_queue.get_job_task(task["id"])["approval_status"] == "approved"
    assert db_queue.get_job(job["id"])["failed_count"] == 0


def test_recovery_refuses_ambiguous_ids_and_missing_or_unavailable_inventory(monkeypatch):
    import vilpower_client
    job, task = uncertain_task(monkeypatch)
    inventory(monkeypatch, [live(status="approved"), live(status="approved", ref="dlt-2")])
    assert sms_dlt.reconcile_job(job["id"]) == {"checked": 1, "updated": 0}
    before = db_queue.get_job_task(task["id"])

    def unavailable(**kwargs):
        raise vilpower_client.VilpowerUnavailable("Inventory blocked; refresh the Tata session")

    monkeypatch.setattr(vilpower_client, "fetch_sms_templates", unavailable)
    with pytest.raises(vilpower_client.VilpowerUnavailable, match="Inventory blocked"):
        sms_dlt.reconcile_job(job["id"])
    assert db_queue.get_job_task(task["id"]) == before


def test_refresh_skips_active_definitive_failed_terminal_and_wrong_scope(monkeypatch):
    inventory(monkeypatch, [])
    job = sms_dlt.stage_batch([draft("pending"), draft("processing"), draft("failed"), draft("approved")],
                              "tata", "Tester", "drafts.csv")
    tasks = db_queue.get_job_tasks(job["id"])
    for task in tasks[1:]:
        db_queue.claim_task(task["id"], "tata", "sms")
    db_queue.record_task_result(tasks[2]["id"], "failed", "unknown", error="Invalid header")
    db_queue.record_task_result(tasks[3]["id"], "submitted", "approved", provider_ref_id="dlt-1")
    inventory(monkeypatch, [live("pending", status="approved"), live("processing", status="approved"),
                            live("failed", status="approved"), live("approved", status="pending")])
    monkeypatch.setattr(sms_dlt, "_inventory", lambda *args: pytest.fail("No reconciliation candidates"))
    assert sms_dlt.reconcile_job(job["id"]) == {"checked": 0, "updated": 0}
    with pytest.raises(ValueError, match="Tata"):
        sms_dlt.reconcile_job(job["id"], "bajaj")
    wa = db_queue.create_job_with_tasks("tata", "whatsapp", "wa.csv", "Tester", [])
    with pytest.raises(ValueError, match="SMS"):
        sms_dlt.reconcile_job(wa["id"])


@pytest.mark.parametrize("field,value", [("template_message", "Changed."), ("header", "OTHERT")])
def test_registered_id_approval_refresh_also_requires_exact_copy_and_header(monkeypatch, field, value):
    inventory(monkeypatch, [])
    job = sms_dlt.stage_batch([draft()], "tata", "Tester", "drafts.csv")
    task = db_queue.get_job_tasks(job["id"])[0]
    db_queue.claim_task(task["id"], "tata", "sms")
    db_queue.record_task_result(task["id"], "submitted", "pending", provider_ref_id="dlt-1")
    inventory(monkeypatch, [{**live(status="approved"), field: value}])
    assert sms_dlt.poll_approvals() == {"checked": 1, "updated": 0}
    assert db_queue.get_job_task(task["id"])["approval_status"] == "pending"



@pytest.mark.parametrize("payload,expected", [
    ('{"provider_response":{"outcome":"unknown","cookie":"never expose"}}', "unknown"),
    ('{"provider_response":{"outcome":"verified"}}', "verified"),
    ('{"provider_response":{"outcome":"failed"}}', "failed"),
    ('{"provider_response":{"outcome":["unknown"]}}', None),
    ('{"provider_response":"unknown"}', None), ("[]", None), ("null", None), ("invalid", None),
])
def test_job_surface_exposes_only_known_registration_outcome_scalar(payload, expected):
    assert sms_dlt.sms_task_registration_outcome({"payload_json": payload}) == expected


def test_manual_job_refresh_reconciles_after_authorization_only(monkeypatch, provision_user):
    job, task = uncertain_task(monkeypatch)
    inventory(monkeypatch, [live(status="approved")])
    _, tata_headers = provision_user("tata")
    _, bajaj_headers = provision_user("bajaj")
    client = TestClient(api.app)
    assert client.get(f"/api/jobs/{job['id']}?reconcile=true").status_code == 401
    assert client.get(f"/api/jobs/{job['id']}?reconcile=true", headers=bajaj_headers).status_code == 403
    assert db_queue.get_job_task(task["id"])["status"] == "FAILED"
    cached = client.get(f"/api/jobs/{job['id']}", headers=tata_headers)
    assert cached.status_code == 200
    assert cached.json()["tasks"][0]["registration_outcome"] == "unknown"
    refreshed = client.get(f"/api/jobs/{job['id']}?reconcile=true", headers=tata_headers)
    assert refreshed.status_code == 200
    response = refreshed.json()
    assert response["job"]["status"] == "COMPLETED"
    assert response["tasks"][0]["registration_outcome"] == "verified"
    assert response["tasks"][0]["approval_status"] == "approved"
    assert response["tasks"][0]["provider_ref_id"] == "dlt-1"
    assert response["tasks"][0]["error"] is None
    assert "payload_json" not in response["tasks"][0]


def test_empty_job_status_refresh_does_not_fetch_inventory(monkeypatch):
    job = db_queue.create_job_with_tasks("tata", "sms", "empty.csv", "Tester", [])
    monkeypatch.setattr(sms_dlt, "_inventory", lambda *args: pytest.fail("No candidates"))
    assert sms_dlt.reconcile_job(job["id"]) == {"checked": 0, "updated": 0}

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


@pytest.mark.parametrize("fields", [{"entity_id": "1101000000000000000"}, {"provider": "other"}])
def test_import_rejects_foreign_principal_or_provider(fields):
    with pytest.raises(ValueError, match="entity|provider"):
        sms_dlt.draft_from_row(draft(**fields))


def test_tcn588_batch_refresh_reads_inventory_once_and_recovers_all_sixteen(monkeypatch):
    import vilpower_client
    inventory(monkeypatch, [])
    names = [f"tcn_588_pqpl_bulls_eye_n_sms_{i}" for i in range(1, 17)]
    job = sms_dlt.stage_batch([draft(name) for name in names], "tata", "Tester", "TCN-588")
    for task in db_queue.get_job_tasks(job["id"]):
        db_queue.claim_task(task["id"], "tata", "sms")
        db_queue.record_task_result(
            task["id"], "failed", "unknown", error="Registration outcome unknown. Do not resubmit automatically.",
            result_payload={"provider_response": {"outcome": "unknown", "retry_safe": False,
                                                "registration_attempted": True, "provider": "vilpower"}},
        )
    reads = []

    def authoritative(**kwargs):
        reads.append(kwargs)
        return [live(name, status="approved", ref=f"dlt-{i}") for i, name in enumerate(names, 1)]

    monkeypatch.setattr(vilpower_client, "fetch_sms_templates", authoritative)
    monkeypatch.setattr(vilpower_client, "submit_sms_template",
                        lambda *args, **kwargs: pytest.fail("Never replay a TCN588 registration"))
    assert sms_dlt.reconcile_job(job["id"]) == {"checked": 16, "updated": 16}
    assert reads == [{"client": "tata", "search": ""}]
    summary = db_queue.get_job(job["id"])
    assert (summary["status"], summary["submitted_count"], summary["failed_count"]) == ("COMPLETED", 16, 0)
    tasks = db_queue.get_job_tasks(job["id"])
    assert all(task["status"] == "SUBMITTED" and task["approval_status"] == "approved" and task["error"] is None
               for task in tasks)
    assert {task["provider_ref_id"] for task in tasks} == {f"dlt-{i}" for i in range(1, 17)}
