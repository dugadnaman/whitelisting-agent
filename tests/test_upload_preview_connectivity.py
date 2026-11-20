"""Upload previews retain source identity and never infer an empty offline catalog."""
import io
import json

import openpyxl
import pytest
from fastapi.testclient import TestClient

import api
import config


def workbook():
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "November"
    sheet.append(["Channel", "English", "Hindi"])
    sheet.append(["SMS", "SMS offer only.", "केवल एसएमएस संदेश।"])
    sheet.append(["WhatsApp", "Hi <name>, your personal loan offer is ready. CTA: Check Offer <link>",
                  "नमस्ते <name>, आपका ऋण ऑफर तैयार है। CTA: Apply <link>"])
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def test_native_upload_reuses_source_names_across_temporary_files(provision_user, monkeypatch):
    _, headers = provision_user("tata")
    monkeypatch.setattr(api, "_fetch_whatsapp_inventory", lambda client: ([], None))
    monkeypatch.setattr(config, "_load_env_file", lambda: None)
    client = TestClient(api.app, headers=headers)
    batches = []
    for _ in range(2):
        response = client.post("/api/preview?account=tcl_promo&channel=whatsapp",
                               files={"file": ("PAPL campaign.xlsx", workbook())})
        assert response.status_code == 200, response.text
        rows = response.json()
        assert len(rows) == 2
        assert len({row["template_name"] for row in rows}) == 2
        assert {row["language"] for row in rows} == {"en", "hi"}
        assert {row["source_ref"] for row in rows} == {
            "PAPL campaign.xlsx:November!B3", "PAPL campaign.xlsx:November!C3",
        }
        assert all(row["inventory_status"] == "verified" for row in rows)
        batches.append([(row["template_name"], row["source_ref"]) for row in rows])
    assert batches[0] == batches[1]


def test_karix_outage_retains_preview_but_blocks_duplicate_checked_submission(provision_user, monkeypatch):
    _, headers = provision_user("tata")
    monkeypatch.setattr(api, "_fetch_whatsapp_inventory", lambda client: ([], "Portal session expired"))
    monkeypatch.setattr(config, "_load_env_file", lambda: None)
    client = TestClient(api.app, headers=headers)
    data = b"template_name,body_text\nlocal_offer,Your offer is ready.\n"
    preview = client.post("/api/preview?account=tcl_promo&channel=whatsapp",
                          files={"file": ("offer.csv", data)})
    assert preview.status_code == 200, preview.text
    row = preview.json()[0]
    assert row["components"][0]["text"] == "Your offer is ready."
    assert row["inventory_status"] == "unverified"
    assert "expired" in row["inventory_error"]
    assert row["already_exists_on_waba"] is None
    assert row["exists_on_waba"] is None
    assert row["submission_ready"] is False
    submitted = client.post(
        "/api/submit?account=tcl_promo&channel=whatsapp&expected_account=tcl_promo&expected_channel=whatsapp",
        files={"file": ("offer.csv", data)},
    )
    assert submitted.status_code == 503, submitted.text
    assert "Reconnect" in submitted.json()["detail"]
    from db import get_db
    with get_db() as connection:
        assert connection.execute("SELECT COUNT(*) AS n FROM ingestion_jobs").fetchone()["n"] == 0


def regional_workbook():
    book = openpyxl.Workbook()
    book.active.title = "Regional"
    book.active["A1"] = "नमस्कार, तुमच्या अर्जाची माहिती उपलब्ध आहे."
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


@pytest.fixture
def language_review_client(provision_user, monkeypatch):
    _, headers = provision_user("tata")
    monkeypatch.setattr(api, "_fetch_whatsapp_inventory", lambda client: ([], None))
    monkeypatch.setattr(config, "_load_env_file", lambda: None)
    return TestClient(api.app, headers=headers)


def test_unreviewed_language_is_visible_and_never_queued(language_review_client):
    client = language_review_client
    upload = ("regional.xlsx", regional_workbook())
    preview = client.post("/api/preview?account=tcl_promo&channel=whatsapp", files={"file": upload})
    assert preview.status_code == 200, preview.text
    row = preview.json()[0]
    assert row["language"] == ""
    assert row["language_review_required"] is True
    assert "Select" in row["language_review_message"]
    assert row["submission_ready"] is False
    assert row["inventory_status"] == "verified"
    for skip_duplicates in ("true", "false"):
        submitted = client.post(
            "/api/submit?account=tcl_promo&channel=whatsapp&expected_account=tcl_promo"
            f"&expected_channel=whatsapp&skip_duplicates={skip_duplicates}",
            files={"file": upload},
        )
        assert submitted.status_code == 400, submitted.text
        assert "Language review required" in submitted.json()["detail"]
        assert row["source_ref"] in submitted.json()["detail"]
    from db import get_db
    with get_db() as connection:
        assert connection.execute("SELECT COUNT(*) AS n FROM ingestion_jobs").fetchone()["n"] == 0


@pytest.mark.parametrize("language", ["mr", "ur", "or", "as"])
def test_reviewed_language_reparses_original_bytes_before_queue(
    language_review_client, monkeypatch, language,
):
    client = language_review_client
    upload = ("regional.xlsx", regional_workbook())
    preview = client.post("/api/preview?account=tcl_promo&channel=whatsapp", files={"file": upload})
    assert preview.status_code == 200, preview.text
    original = preview.json()[0]
    overrides = {"language_overrides": json.dumps({original["source_ref"]: language})}
    reviewed = client.post(
        "/api/preview?account=tcl_promo&channel=whatsapp",
        files={"file": upload}, data=overrides,
    )
    assert reviewed.status_code == 200, reviewed.text
    row = reviewed.json()[0]
    assert row["language"] == language
    assert row["language_review_required"] is False
    assert row["language_review_message"] is None
    assert row["submission_ready"] is True
    for field in ("source_ref", "template_name", "components"):
        assert row[field] == original[field]

    dispatched = []

    def record_reviewed_rows(rows, log_path, *, task_ids, **kwargs):
        from db_queue import record_task_result
        dispatched.extend(rows)
        for task_id in task_ids:
            record_task_result(task_id, "submitted", "pending", "reviewed-template")
        return rows

    monkeypatch.setattr(api, "run", record_reviewed_rows)
    submitted = client.post(
        "/api/submit?account=tcl_promo&channel=whatsapp&expected_account=tcl_promo"
        "&expected_channel=whatsapp&fix_grammar=false",
        files={"file": upload}, data=overrides,
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["submitted"] == 1
    assert len(dispatched) == 1
    assert dispatched[0]["language"] == language
    assert dispatched[0]["source_ref"] == original["source_ref"]
    assert dispatched[0]["template_name"] == original["template_name"]
    body = next(component["text"] for component in dispatched[0]["components"] if component["type"] == "BODY")
    assert body == "नमस्कार, तुमच्या अर्जाची माहिती उपलब्ध आहे."


@pytest.mark.parametrize("endpoint", ["preview", "submit"])
@pytest.mark.parametrize("overrides", [
    "not JSON", "null", "[]", '"mr"', '{"source":null}', '{"source":true}',
    '{"source":1}', '{"source":{}}', '{"source":"zz"}', '{"source":"MR"}',
    '{"source":" mr "}', '{"":"mr"}',
])
def test_language_overrides_require_strict_source_language_object(
    language_review_client, endpoint, overrides,
):
    response = language_review_client.post(
        f"/api/{endpoint}?account=tcl_promo&channel=whatsapp"
        "&expected_account=tcl_promo&expected_channel=whatsapp",
        files={"file": ("copy.csv", b"template_name,body_text\noriginal,Original customer copy.\n")},
        data={"language_overrides": overrides},
    )
    assert response.status_code == 400, response.text
    assert "language_overrides" in response.json()["detail"]


@pytest.mark.parametrize("endpoint", ["preview", "submit"])
def test_language_override_rejects_source_not_parsed_from_file(language_review_client, endpoint):
    response = language_review_client.post(
        f"/api/{endpoint}?account=tcl_promo&channel=whatsapp"
        "&expected_account=tcl_promo&expected_channel=whatsapp",
        files={"file": ("regional.xlsx", regional_workbook())},
        data={"language_overrides": '{"different.xlsx:Regional!A1":"ur"}'},
    )
    assert response.status_code == 400, response.text
    assert "unknown source_ref" in response.json()["detail"]


@pytest.mark.parametrize("channel", ["rcs", "sms"])
@pytest.mark.parametrize("endpoint", ["preview", "submit"])
def test_language_overrides_cannot_modify_other_channels(language_review_client, channel, endpoint):
    response = language_review_client.post(
        f"/api/{endpoint}?account=tcl_promo&channel={channel}"
        f"&expected_account=tcl_promo&expected_channel={channel}",
        files={"file": ("copy.csv", b"body_text\nOriginal customer copy.\n")},
        data={"language_overrides": '{"copy.csv:copy!A2":"ur"}'},
    )
    assert response.status_code == 400, response.text
    assert "only supported for WhatsApp" in response.json()["detail"]
