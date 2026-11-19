"""Synthetic upload and unavailable-inventory regressions; no live portal traffic."""

import csv
from urllib.parse import urlparse

import openpyxl
import pytest
import requests

import sms_brief
import sms_dlt
import vilpower_client as vilpower


LANGUAGES = ["English", "Marathi", "Kannada", "Hindi", "Tamil", "Telugu", "Bengali", "Gujarati"]


@pytest.mark.parametrize("filename,body_header", [
    ("followup_DEAL-284.csv", "SMS 2"),
    ("translated_notice_731.csv", "SMS 9"),
])
def test_named_sms_csv_keeps_eight_names_exact_copy_and_sources(tmp_path, filename, body_header):
    path = tmp_path / filename
    expected = [(f"offer_{language.lower()}", f"  Original {language} copy,\r\nwith exact spacing.  ") for language in LANGUAGES]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Template Name", body_header, "Language"])
        writer.writerows((name, text, language) for (name, text), language in zip(expected, LANGUAGES, strict=True))
    drafts = sms_dlt.load_drafts(str(path))
    assert [(row["template_name"], row["text"]) for row in drafts] == expected
    assert [row["source_ref"] for row in drafts] == [f"{path.stem}!B{index}" for index in range(2, 10)]
    assert [row["language"] for row in drafts] == LANGUAGES
    report = sms_brief.parse_brief(str(path), path.name)
    assert [row["suggested_template_name"] for row in report["candidates"]] == [name for name, _ in expected]


@pytest.mark.parametrize("source_filename,sheet_name,reorder", [
    ("case_LM-6142.xlsx", "Approved translations", False),
    ("retention_9283.xlsx", "Regional variants", True),
])
def test_language_matrix_reads_every_sms_cell_not_active_sheet(tmp_path, source_filename, sheet_name, reorder):
    path = tmp_path / "upload_temporary.xlsx"
    book = openpyxl.Workbook()
    book.active.title = "Cover"
    book.active.append(["Do not import this cover page as an SMS."])
    sheet = book.create_sheet(sheet_name)
    sheet.append(["Sr No ", *LANGUAGES])
    expected = []
    for number in range(1, 8):
        bodies = [f"  Message {number}: original {language} offer.\n " for language in LANGUAGES]
        sheet.append([f"SMS {number}", *bodies])
        expected.extend(bodies)
    book.save(path)
    if reorder:
        book.move_sheet(sheet, offset=-1)
    book.active = book.sheetnames.index("Cover")
    reordered = tmp_path / "upload_other_temporary.xlsx"
    book.save(reordered)
    drafts = sms_dlt.load_drafts(str(path), source_filename=source_filename)
    repeated = sms_dlt.load_drafts(str(reordered), source_filename=source_filename)
    assert {row["source_ref"]: row["template_name"] for row in drafts} == {
        row["source_ref"]: row["template_name"] for row in repeated
    }
    assert len(drafts) == 56
    assert len({row["template_name"] for row in drafts}) == 56
    assert [row["text"] for row in drafts] == expected
    assert [row["language"] for row in drafts] == LANGUAGES * 7
    assert all(row["source_file"] == source_filename for row in drafts)
    assert drafts[0]["source_ref"] == f"{sheet_name}!B2"
    assert drafts[-1]["source_ref"] == f"{sheet_name}!I8"


def test_flat_dlt_fields_and_native_sms_blocks_coexist_without_cross_channel_copy(tmp_path):
    path = tmp_path / "mixed.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Drafts"
    sheet.append(["Template Name", "Text", "Category ID", "Header ID", "Header", "Language"])
    sheet.append(["explicit_name", "  Short copy!  ", "finance", "header-id", "TATAXX", "English"])
    sms = book.create_sheet("SMS")
    sms.append(["Campaign Name", "Synthetic_campaign"])
    sms.append(["SMS Text", "Native SMS body must remain exactly unchanged. "])
    other = book.create_sheet("WA")
    other.append(["Template Name", "SMS 2"])
    other.append(["not_sms", "Copied SMS headings must not override the WA worksheet."])
    book.save(path)
    drafts = sms_dlt.load_drafts(str(path))
    assert len(drafts) == 2
    assert drafts[0]["template_name"] == "explicit_name"
    assert drafts[0]["text"] == "  Short copy!  "
    assert drafts[0]["category_id"] == "finance"
    assert drafts[1]["text"] == "Native SMS body must remain exactly unchanged. "


def valid_draft():
    return {"template_name": "fixture_name", "text": "Your application is being processed.",
            "template_type": "1", "category_id": "finance", "header_id": "header-id", "header": "TATAXX"}


def test_preview_keeps_source_when_catalog_unavailable_and_submission_stays_closed(monkeypatch):
    def unavailable(*args, **kwargs):
        raise vilpower.VilpowerAuthExpired("VILPOWER session expired; refresh the Tata Capital session in Settings")

    monkeypatch.setattr(vilpower, "fetch_sms_templates", unavailable)
    monkeypatch.setattr(sms_dlt, "create_job_with_tasks", lambda *args, **kwargs: pytest.fail("Unavailable catalog must not stage registration"))
    preview, = sms_dlt.preview_drafts([valid_draft()])
    assert preview["components"][0]["text"] == valid_draft()["text"]
    assert preview["status"] == "UNVERIFIED"
    assert preview["inventory_status"] == "unverified"
    assert preview["already_exists_on_waba"] is None
    assert preview["submission_ready"] is False
    assert "session expired" in preview["inventory_error"]
    with pytest.raises(vilpower.VilpowerUnavailable):
        sms_dlt.stage_batch([valid_draft()], "tata", "Tester", "fixture.csv")
    with pytest.raises(vilpower.VilpowerUnavailable):
        sms_dlt.identify_drafts([valid_draft()])


@pytest.mark.parametrize("location,expired", [("/signin/", True), ("/sign-in/?next=/", True),
                                            ("https://other.example/signin/", False),
                                            ("/accountsettings/profile/", False)])
@pytest.mark.parametrize("method,path", [("GET", "/accountsettings/profile"), ("POST", vilpower._ADD)])
def test_portal_classifies_auth_redirects_without_following_any_redirect(monkeypatch, location, expired, method, path):
    calls = []

    def request(session, method, url, **kwargs):
        calls.append((method, urlparse(url).path))
        assert kwargs["allow_redirects"] is False
        response = requests.Response()
        response.status_code = 302
        response.headers["Location"] = location
        return response

    monkeypatch.setattr(requests.Session, "request", request)
    portal = vilpower._Portal({"cookie": "sessionid=fixture-only", "entity_id": vilpower.TATA_ENTITY_ID})
    try:
        with pytest.raises(vilpower.VilpowerAuthExpired if expired else vilpower.VilpowerUnavailable) as error:
            portal.request(method, path)
        if not expired:
            assert not isinstance(error.value, vilpower.VilpowerAuthExpired)
        assert calls == [(method, path)]
    finally:
        portal.close()


def test_creation_redirect_is_not_replayed_or_accepted_cross_origin(monkeypatch):
    calls = []

    def request(session, method, url, **kwargs):
        calls.append((method, url))
        response = requests.Response()
        response.status_code = 302
        response.headers["Location"] = "http://www.vilpower.in" + vilpower._INDEX
        return response

    monkeypatch.setattr(requests.Session, "request", request)
    portal = vilpower._Portal({"cookie": "sessionid=fixture-only", "entity_id": vilpower.TATA_ENTITY_ID})
    try:
        with pytest.raises(vilpower.VilpowerUnavailable):
            portal.request("POST", vilpower._ADD)
        assert len(calls) == 1
    finally:
        portal.close()


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_explicit_wrong_channel_rows_cannot_override_sms_named_table_scope(tmp_path, extension):
    path = tmp_path / f"review_QR-379.{extension}"
    rows = [
        ["Template Name", "SMS 2", "Channel"],
        ["native_sms", "This exact SMS text is approved for extraction. ", "sms"],
        ["copied_wa", "Copied SMS headings cannot override WhatsApp row scope.", "whatsapp"],
        ["unknown", "An unknown channel must not default to an SMS registration.", "unconfirmed"],
    ]
    if extension == "csv":
        with path.open("w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerows(rows)
    else:
        book = openpyxl.Workbook()
        for row in rows:
            book.active.append(row)
        book.save(path)
    report = sms_brief.parse_brief(str(path), path.name)
    assert [(row["suggested_template_name"], row["text"]) for row in report["candidates"]] == [
        ("native_sms", "This exact SMS text is approved for extraction. "),
    ]
    assert sum("channel row excluded" in warning for warning in report["warnings"]) == 2
    drafts = sms_dlt.load_drafts(str(path))
    assert [(row["template_name"], row["text"]) for row in drafts] == [
        ("native_sms", "This exact SMS text is approved for extraction. "),
    ]
