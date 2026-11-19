"""Upload previews retain source identity and never infer an empty offline catalog."""
import io

import openpyxl
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
