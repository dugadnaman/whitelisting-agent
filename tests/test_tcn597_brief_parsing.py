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
        attachments.append({"id": str(index), "filename": filename, "local_path": str(path)})

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


def test_tcn597_complete_jira_brief_keeps_copy_channels_and_languages(clicker_workbooks):
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


@pytest.mark.parametrize("header", [
    "created_at | valid_until | template_name | template_message",
    "Campaign report | grand total | template_name | message",
])
def test_database_headers_still_rejected_with_template_filters_supported(header):
    assert not is_valid_template_copy(header)
