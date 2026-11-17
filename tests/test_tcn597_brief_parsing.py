"""TCN-597's real workbook layouts parse offline without losing regional copy."""

import json
from collections import Counter
from pathlib import Path

import openpyxl
import pytest

from briefing_parser import extract_templates_from_excel_file, is_valid_template_copy, parse_jira_brief


@pytest.fixture
def clicker_workbooks(tmp_path, monkeypatch):
    cells = json.loads((Path(__file__).parent / "fixtures" / "tcn597_workbook_cells.json").read_text())
    attachments = []
    for index, (filename, sheets) in enumerate(cells.items(), 1):
        workbook = openpyxl.Workbook()
        workbook.remove(workbook.active)
        for title, data in sheets.items():
            sheet = workbook.create_sheet(title)
            for coordinate, value in data["cells"].items():
                sheet[coordinate] = value
            for merged_range in data["merged_ranges"]:
                sheet.merge_cells(merged_range)
        path = tmp_path / filename
        workbook.save(path)
        workbook.close()
        attachment_id = ("38920", "38880")[index - 1]
        attachments.append({"id": attachment_id, "filename": filename, "local_path": str(path)})

    def no_network(*args, **kwargs):
        pytest.fail("Local Jira parsing must not download attachments or call semantic AI")

    monkeypatch.setattr("briefing_parser.download_jira_attachment", no_network)
    monkeypatch.setattr("gemini_intelligence.analyze_template_semantics", no_network)
    return cells, attachments


def test_tcn597_exact_layout_extracts_every_regional_language(clicker_workbooks):
    cells, attachments = clicker_workbooks
    attachment = attachments[0]
    items = extract_templates_from_excel_file(Path(attachment["local_path"]))
    expected_languages = {"mr", "kn", "hi", "ta", "te", "bn", "gu"}
    assert Counter(item["channel"] for item in items) == {"SMS": 28, "RCS": 28, "WA": 28, "PN": 28}
    for channel in ("SMS", "RCS", "WA", "PN"):
        assert Counter(item["language"] for item in items if item["channel"] == channel) == {
            language: 4 for language in expected_languages
        }
    source_cells = cells[attachment["filename"]]["Campaign Content"]["cells"]
    assert {item["raw_text"] for item in items} == {
        value for coordinate, value in source_cells.items()
        if coordinate[0] in "CDEFGHI" and coordinate[1:] != "1"
    }


def test_tcn597_unscoped_brief_keeps_both_complete_workbooks(clicker_workbooks):
    cells, attachments = clicker_workbooks
    brief = parse_jira_brief({
        "key": "TCN-597", "summary": "Clicker Flow New content",
        "description_text": "Pls help with whitelisting of Clickers content",
        "attachments": attachments,
    }, download_creatives=False)
    assert brief.account == "tcl_promo"
    assert brief.channel_counts == {"whatsapp": 40, "rcs": 37, "sms": 40, "email": 0, "push": 1, "total": 118}
    drafts_by_channel = {"SMS": brief.sms_templates, "RCS": brief.rcs_templates, "WhatsApp": brief.whatsapp_templates}
    regional = cells[attachments[0]["filename"]]["Campaign Content"]["cells"]
    english = cells[attachments[1]["filename"]]
    for channel, drafts in drafts_by_channel.items():
        expected = {
            regional[f"{column}{row}"]
            for row in range(2, 18) if regional[f"B{row}"] == channel
            for column in "CDEFGHI"
        }
        row = {"SMS": 2, "WhatsApp": 3, "RCS": 4}[channel]
        for title in ("Content", "Content 2"):
            expected.update(english[title]["cells"][f"{column}{row}"] for column in ("B", "I", "U", "Y"))
        first_row = {"SMS": 2, "RCS": 4, "WhatsApp": 6}[channel]
        expected.update(
            english["Updated"]["cells"][f"{column}{row}"]
            for row in (first_row, first_row + 1) for column in ("B", "D")
        )
        assert {draft["raw_source"] for draft in drafts} == expected
        assert len(drafts) == len(expected)
        assert Counter(draft["language"] for draft in drafts) == {
            "mr": 4, "kn": 4, "hi": 4, "ta": 4, "te": 4, "bn": 4, "gu": 4,
            "en": 9 if channel == "RCS" else 12,
        }
    otp_steps = english["Updated"]["cells"]["D6"]
    otp_draft = next(draft for draft in brief.whatsapp_templates if draft["raw_source"] == otp_steps)
    assert "1. Revisit your application." in otp_draft["body"]
    assert "2. Verify your registered mobile number using OTP." in otp_draft["body"]
    assert "3. Proceed to the next step." in otp_draft["body"]


def test_tcn597_latest_attached_regional_request_scopes_active_copy(clicker_workbooks):
    cells, attachments = clicker_workbooks
    brief = parse_jira_brief({
        "key": "TCN-597", "summary": "Clicker Flow New content",
        "description_text": "Pls help with whitelisting of Clickers content",
        "attachments": attachments,
        "comments": [
            {"id": "78095", "body_text": "Kindly whitelist the attached the regional content.",
             "attachment_ids": ["38920"]},
            {"id": "78105", "body_text": "Please use the attached image.",
             "attachment_ids": []},
        ],
    }, download_creatives=False)
    assert brief.account == "tcl_promo"
    assert brief.channel_counts == {"whatsapp": 28, "rcs": 28, "sms": 28, "email": 0, "push": 1, "total": 85}
    regional = cells[attachments[0]["filename"]]["Campaign Content"]["cells"]
    for channel, drafts in (
        ("SMS", brief.sms_templates), ("RCS", brief.rcs_templates), ("WhatsApp", brief.whatsapp_templates),
    ):
        expected = {
            regional[f"{column}{row}"]
            for row in range(2, 18) if regional[f"B{row}"] == channel
            for column in "CDEFGHI"
        }
        assert {draft["raw_source"] for draft in drafts} == expected
        assert Counter(draft["language"] for draft in drafts) == {
            "mr": 4, "kn": 4, "hi": 4, "ta": 4, "te": 4, "bn": 4, "gu": 4,
        }
    originals = {attachment["id"]: attachment for attachment in brief.attachments_mapped}
    assert originals["38920"]["included_in_brief"] is True
    assert originals["38880"]["included_in_brief"] is False
    assert originals["38880"]["local_path"] == attachments[1]["local_path"]
    assert originals["38880"]["scope_note"]


@pytest.mark.parametrize("comment", [
    {"body_text": "Kindly whitelist the attached content.", "attachment_ids": []},
    {"body_text": "Also whitelist the attached additional content.", "attachment_ids": ["38920"]},
    {"body_text": "Do not whitelist the attached content.", "attachment_ids": ["38920"]},
    {"body_text": "The attached image is for whitelisting.", "attachment_ids": ["image"]},
])
def test_tcn597_unresolved_additive_negative_and_image_requests_stay_additive(clicker_workbooks, comment):
    _, attachments = clicker_workbooks
    brief = parse_jira_brief({
        "key": "TCN-597", "summary": "Clicker Flow New content",
        "attachments": attachments, "comments": [comment],
    }, download_creatives=False)
    assert brief.channel_counts == {"whatsapp": 40, "rcs": 37, "sms": 40, "email": 0, "push": 1, "total": 118}
    assert all(attachment["included_in_brief"] for attachment in brief.attachments_mapped)


def test_latest_explicit_request_uses_comment_time_not_attachment_order(clicker_workbooks):
    _, attachments = clicker_workbooks
    brief = parse_jira_brief({
        "key": "SOURCE-1", "summary": "Campaign content",
        "attachments": list(reversed(attachments)),
        "comments": [
            {"body_text": "Whitelist the attached content.", "attachment_ids": ["38920"],
             "created": "2026-01-03T10:00:00+00:00"},
            {"body_text": "Whitelist the attached content.", "attachment_ids": ["38880"],
             "created": "2026-01-01T10:00:00+00:00"},
            {"body_text": "Please use the attached image for whitelisting.", "attachment_ids": ["image"],
             "created": "2026-01-04T10:00:00+00:00"},
            {"body_text": "Do not whitelist the attached content.", "attachment_ids": ["38880"],
             "created": "2026-01-05T10:00:00+00:00"},
        ],
    }, download_creatives=False)
    assert len(brief.sms_templates) == 28
    assert {attachment["id"]: attachment["included_in_brief"] for attachment in brief.attachments_mapped} == {
        "38920": True, "38880": False,
    }


def test_later_additive_request_extends_selected_scope(clicker_workbooks):
    _, attachments = clicker_workbooks
    brief = parse_jira_brief({
        "key": "SOURCE-2", "summary": "Campaign content", "attachments": attachments,
        "comments": [
            {"body_text": "Whitelist the attached content.", "attachment_ids": ["38920"]},
            {"body_text": "Also whitelist the attached additional content.", "attachment_ids": ["38880"]},
        ],
    }, download_creatives=False)
    assert brief.channel_counts == {"whatsapp": 40, "rcs": 37, "sms": 40, "email": 0, "push": 1, "total": 118}
    assert all(attachment["included_in_brief"] for attachment in brief.attachments_mapped)


def test_scope_skips_historical_embedded_creatives_but_keeps_standalone_images(
    clicker_workbooks, tmp_path, monkeypatch,
):
    _, attachments = clicker_workbooks
    standalone = tmp_path / "shared-wa.png"
    standalone.write_bytes(b"standalone creative")
    embedded = tmp_path / "current-embedded.png"
    embedded.write_bytes(b"embedded creative")
    extracted = []

    def workbook_images(path):
        extracted.append(path)
        return {"WhatsApp": [str(embedded)]}

    monkeypatch.setattr("briefing_parser._extract_images_from_xlsx", workbook_images)
    brief = parse_jira_brief({
        "key": "SOURCE-3", "summary": "Campaign content",
        "attachments": attachments + [
            {"id": "image", "filename": standalone.name, "local_path": str(standalone)},
        ],
        "comments": [
            {"body_text": "Whitelist the attached content.", "attachment_ids": ["38920"]},
        ],
    }, download_creatives=False)
    assert extracted == [Path(attachments[0]["local_path"])]
    mappings = {attachment["id"]: attachment for attachment in brief.attachments_mapped}
    assert mappings["38880"]["included_in_brief"] is False
    assert mappings["image"]["included_in_brief"] is True
    assert mappings[embedded.stem]["included_in_brief"] is True
    assert {draft["media_file"] for draft in brief.whatsapp_templates} <= {
        str(standalone), str(embedded),
    }


@pytest.mark.parametrize("header", [
    "created_at | valid_until | template_name | template_message",
    "Campaign report | grand total | template_name | message",
])
def test_database_headers_still_rejected_with_template_filters_supported(header):
    assert not is_valid_template_copy(header)
