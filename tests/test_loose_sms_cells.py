"""Exact-copy SMS cell grids and explicit channel isolation."""

import csv
from types import SimpleNamespace

import openpyxl
import pytest

from briefing_parser import detect_language, extract_templates_from_excel_file, parse_jira_brief
from sms_brief import parse_brief


MESSAGES = ["  नमस्ते {#num#}!  ", "نیا پیغام", "வணக்கம்", "ನಮಸ್ಕಾರ", "নমস্কার", "नमस्ते தமிழ்", "Hi <Name>,\nCafe\u0301 — [link]!"]


def save_book(tmp_path, sheets, filename="messages.xlsx"):
    path = tmp_path / filename
    book = openpyxl.Workbook()
    book.remove(book.active)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    book.save(path)
    return path


@pytest.mark.parametrize("horizontal", [False, True])
@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_headerless_cells_preserve_every_script_and_cell(tmp_path, horizontal, suffix):
    rows = [MESSAGES] if horizontal else [[message] for message in MESSAGES]
    if suffix == ".csv":
        path = tmp_path / "messages.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerows(rows)
    else:
        path = save_book(tmp_path, {"Messages": rows})
    first = parse_brief(str(path), path.name)
    assert first == parse_brief(str(path), path.name)
    items = first["candidates"]
    assert [item["text"] for item in items] == MESSAGES
    assert [item["cell"] for item in items] == ([f"{chr(65 + i)}1" for i in range(len(MESSAGES))] if horizontal else [f"A{i + 1}" for i in range(len(MESSAGES))])
    assert all(item["filename"] == path.name for item in items)
    assert all(item["message_type"] == "2" for item in items)
    assert [item["language"] for item in items[:6]] == ["Regional", "Regional", "Tamil", "Kannada", "Regional", "Regional"]


def test_sparse_multiple_sheets_and_duplicate_cells_remain_distinct(tmp_path):
    path = save_book(tmp_path, {
        "First": [[None, MESSAGES[0], None, MESSAGES[1]], [], [None, MESSAGES[0]]],
        "Second": [[], [None, None, MESSAGES[2]]],
    })
    items = parse_brief(str(path), path.name)["candidates"]
    assert [(item["sheet"], item["cell"]) for item in items] == [("First", "B1"), ("First", "D1"), ("First", "B3"), ("Second", "C2")]
    assert len({item["id"] for item in items}) == 4


def test_xls_cells_use_same_loose_extraction(tmp_path, monkeypatch):
    import xlrd

    path = tmp_path / "messages.xls"
    path.write_bytes(b"synthetic parser fixture")
    sheet = SimpleNamespace(name="Messages", nrows=2, ncols=2,
                            row_values=lambda index: [[MESSAGES[0], ""], ["", MESSAGES[1]]][index])
    book = SimpleNamespace(nsheets=1, sheets=lambda: [sheet], release_resources=lambda: None)
    monkeypatch.setattr(xlrd, "open_workbook", lambda *args, **kwargs: book)
    items = parse_brief(str(path), path.name)["candidates"]
    assert [(item["cell"], item["text"]) for item in items] == [("A1", MESSAGES[0]), ("B2", MESSAGES[1])]


def test_mixed_channels_unscoped_regions_and_planners_stay_excluded(tmp_path):
    path = save_book(tmp_path, {
        "Content": [["Lang", "SMS", "WA", "PN"], ["Hindi", MESSAGES[0], MESSAGES[1], MESSAGES[2]], ["Urdu", MESSAGES[1], MESSAGES[3], MESSAGES[4]]],
        "Regional": [[MESSAGES[2]], [MESSAGES[3]]],
        "RCS": [[MESSAGES[4]]],
        "Calendar": [[MESSAGES[4]]],
        "Notes": [[MESSAGES[4]]],
        "Metadata": [["Date", "2026-01-01"], ["Notes", MESSAGES[4]]],
    })
    items = parse_brief(str(path), path.name)["candidates"]
    assert [(item["sheet"], item["cell"], item["language"]) for item in items] == [("Content", "B2", "Hindi"), ("Content", "B3", "Urdu")]


def test_declared_language_hints_and_ambiguous_scripts():
    assert detect_language("नमस्कार", "Marathi") == "mr"
    assert detect_language("नमस्कार") == "und"
    assert detect_language("نیا پیغام", "Urdu") == "ur"
    assert detect_language("نیا پیغام") == "und"
    assert detect_language("தமிழ் नमस्ते") == "und"
    assert detect_language("你好") == "und"


def test_jira_sms_attachment_reuses_cells_without_copy_normalization(tmp_path):
    path = save_book(tmp_path, {"Sheet1": [[MESSAGES[0], MESSAGES[1]], [MESSAGES[0], MESSAGES[-1]]]})
    items = extract_templates_from_excel_file(path, selected_channel="SMS")
    assert [item["text"] for item in items] == [MESSAGES[0], MESSAGES[1], MESSAGES[0], MESSAGES[-1]]
    assert [item["cell"] for item in items] == ["A1", "B1", "A2", "B2"]
    result = parse_jira_brief({"key": "SYN-1", "summary": "SMS copy approval", "description_text": "", "attachments": [{"id": "1", "filename": path.name, "local_path": str(path)}]}, download_creatives=False)
    assert [draft["text"] for draft in result.sms_templates] == [item["text"] for item in items]
    assert all(draft["message_type"] == "2" for draft in result.sms_templates)
    assert all("!Sheet1!" in draft["source_origin"] for draft in result.sms_templates)


def test_numbered_sms_language_matrix_keeps_all_short_regional_cells(tmp_path):
    languages = ["English", "Marathi", "Kannada", "Hindi", "Tamil", "Telugu", "Bengali", "Gujarati"]
    messages = ["Hello!", "नमस्कार", "ನಮಸ್ಕಾರ", "नमस्ते", "வணக்கம்", "నమస్కారం", "নমস্কার", "નમસ્તે"]
    path = save_book(tmp_path, {"Sheet1": [["Sr No ", *languages], *[
        [f"SMS {index}", *messages] for index in range(1, 8)
    ]]})
    items = parse_brief(str(path), path.name)["candidates"]
    assert len(items) == 56
    assert [item["text"] for item in items] == messages * 7
    assert sum(item["message_type"] == "2" for item in items) == 49
    assert [item["language"] for item in items[:8]] == languages


def test_metadata_words_in_customer_copy_are_not_headers(tmp_path):
    messages = ["Product ready — வாங்க!", "Link your account now.", "Notes for you: नमस्ते"]
    path = save_book(tmp_path, {"Sheet1": [messages]})
    assert [item["text"] for item in parse_brief(str(path), path.name)["candidates"]] == messages


def test_language_names_inside_loose_messages_are_not_language_headers(tmp_path):
    messages = ["  Message 1: original English offer.\n ", "Choose Hinglish for your updates.",
                "Your Hindi offer is ready.", "English offers are available."]
    path = save_book(tmp_path, {"Sheet1": [messages]})
    assert [item["text"] for item in parse_brief(str(path), path.name)["candidates"]] == messages


@pytest.mark.parametrize("sheet_name", ["Cover", "Cover page", "Cover_sheet", "Admin", "Administration", "README", "Metadata"])
def test_administrative_sheets_do_not_become_loose_sms_copy(tmp_path, sheet_name):
    path = save_book(tmp_path, {
        sheet_name: [["Do not import this cover page as an SMS."]],
        "Sheet1": [[MESSAGES[2]], ["Hello!"]],
    })
    report = parse_brief(str(path), path.name)
    assert [(item["sheet"], item["cell"], item["text"]) for item in report["candidates"]] == [
        ("Sheet1", "A1", MESSAGES[2]), ("Sheet1", "A2", "Hello!"),
    ]
    assert report["sheets"][0] == {"name": sheet_name, "candidate_count": 0}


@pytest.mark.parametrize("header,rows", [
    (["Sr No", "English", "Hindi"], [["SMS 1", "English", "नमस्ते"], ["SMS 2", "Message", "Hindi"]]),
    (["Channel", "Content", "Hindi"], [["SMS", "Notes", "नमस्ते"], ["SMS", "Message", "Hindi"]]),
    (["Language", "SMS", "WA"], [["English", "English", "not SMS"], ["Hindi", "Hindi", "not SMS"]]),
    (["Campaign Name", "Channel", "SMS Content"], [["Offer", "Multi-Channel", "English"], ["Offer", "Multi-Channel", "Message"]]),
])
def test_declared_sms_body_cells_are_not_filtered_as_metadata(tmp_path, header, rows):
    path = save_book(tmp_path, {"Sheet1": [header, *rows]})
    items = parse_brief(str(path), path.name)["candidates"]
    expected = [row[2] for row in rows] if header[-1] == "SMS Content" else [
        value for row in rows for value in (row[1:3] if header[0] != "Language" else row[1:2])
    ]
    assert [item["text"] for item in items] == expected


@pytest.mark.parametrize("cta_header", ["CTA URL", "CTA destination"])
def test_explicit_channel_headers_never_become_independent_row_labels(tmp_path, cta_header):
    path = save_book(tmp_path, {"Multi-ChannelRow": [
        ["Campaign Name", "Channel", "WhatsApp Text", "SMS Content", cta_header],
        ["Campaign A", "Multi-Channel", MESSAGES[1], MESSAGES[2], "https://example.test/offer"],
    ]})
    items = parse_brief(str(path), path.name)["candidates"]
    assert [(item["cell"], item["text"], item["source_kind"]) for item in items] == [
        ("D2", MESSAGES[2], "channel_columns"),
    ]


def test_cta_url_label_alone_is_not_loose_sms_copy(tmp_path):
    path = save_book(tmp_path, {"Sheet1": [["CTA URL"]]})
    assert parse_brief(str(path), path.name)["candidates"] == []


def test_scenario_headers_keep_each_sms_variant_and_continuation(tmp_path):
    path = save_book(tmp_path, {"Updated SMS": [
        ["Channel", "Scenario1&3–Explore Offer", None, "Scenario2&4–OTP Verification"],
        ["SMS", "First explore offer.", None, "First verification reminder."],
        [None, "Second explore offer.", None, "Second verification reminder."],
    ]})
    items = parse_brief(str(path), path.name)["candidates"]
    assert [(item["cell"], item["text"]) for item in items] == [
        ("B2", "First explore offer."), ("D2", "First verification reminder."),
        ("B3", "Second explore offer."), ("D3", "Second verification reminder."),
    ]


def test_parallel_blocks_inherit_consistent_shared_channel_rows(tmp_path):
    path = save_book(tmp_path, {"Content": [
        ["Channel", "Content"] * 4,
        ["SMS", "First SMS.", "SMS", "Second SMS.", "SMS", "Third SMS.", "SMS", "Fourth SMS."],
        ["WA", "First WA.", "WA", "Second WA.", "WA", "Third WA.", None, "Fourth WA."],
        ["RCS", "First RCS.", "RCS", "Second RCS.", "RCS", "Third RCS.", None, "Fourth RCS."],
        ["PN", "First PN.", "PN", "Second PN.", "PN", "Third PN.", None, "Fourth PN."],
    ]})
    items = parse_brief(str(path), path.name)["candidates"]
    assert [(item["cell"], item["text"]) for item in items] == [
        ("B2", "First SMS."), ("D2", "Second SMS."), ("F2", "Third SMS."), ("H2", "Fourth SMS."),
    ]


def test_parallel_conflicting_channels_preserve_independent_continuations(tmp_path):
    path = save_book(tmp_path, {"Content": [
        ["Channel", "Content"] * 4,
        ["SMS", "First SMS.", "SMS", "Second SMS.", "SMS", "Third SMS.", "SMS", "Fourth SMS."],
        ["WA", "First WA.", "RCS", "Second RCS.", "PN", "Third PN.", None, "Independent SMS."],
    ]})
    items = parse_brief(str(path), path.name)["candidates"]
    assert [(item["cell"], item["text"]) for item in items] == [
        ("B2", "First SMS."), ("D2", "Second SMS."), ("F2", "Third SMS."),
        ("H2", "Fourth SMS."), ("H3", "Independent SMS."),
    ]


def test_unspecified_jira_attachment_keeps_short_explicit_sms_only(tmp_path):
    path = save_book(tmp_path, {
        "Mixed": [["Lang", "SMS", "WA"], ["Hindi", MESSAGES[0], MESSAGES[1]]],
        "Unscoped": [[MESSAGES[2], MESSAGES[3]]],
    })
    items = extract_templates_from_excel_file(path)
    sms_items = [item for item in items if item["channel"] == "SMS"]
    assert [(item["sheet"], item["cell"], item["text"]) for item in sms_items] == [("Mixed", "B2", MESSAGES[0])]


def test_dlt_message_schema_remains_explicit_sms_without_ticket_hint(tmp_path):
    path = save_book(tmp_path, {"Sheet1": [["Template ID", "Template Message"], ["123456", MESSAGES[1]]]})
    items = extract_templates_from_excel_file(path)
    assert [(item["channel"], item["cell"], item["text"]) for item in items] == [("SMS", "B2", MESSAGES[1])]


def test_shared_bengali_assamese_script_requires_declared_language():
    assert detect_language("নমস্কার") == "und"
    assert detect_language("নমস্কার", "Bengali") == "bn"
    assert detect_language("নমস্কাৰ", "Assamese") == "as"


def test_jira_whatsapp_loose_cells_keep_short_regional_copy(tmp_path):
    path = save_book(tmp_path, {"Sheet1": [[MESSAGES[1], MESSAGES[2]], [MESSAGES[1], MESSAGES[-1]]]})
    result = parse_jira_brief({
        "key": "SYN-2", "summary": "WhatsApp copy approval", "description_text": "",
        "attachments": [{"id": "1", "filename": path.name, "local_path": str(path)}],
    }, download_creatives=False)
    assert [draft["body"] for draft in result.whatsapp_templates] == [
        MESSAGES[1], MESSAGES[2], MESSAGES[1], MESSAGES[-1],
    ]
    assert [draft["language"] for draft in result.whatsapp_templates[:3]] == ["und", "ta", "und"]
    assert len({draft["source_origin"] for draft in result.whatsapp_templates}) == 4


def test_unresolved_language_never_reaches_karix(monkeypatch):
    from models import TemplateComponent, TemplateSubmission, SubmissionStatus
    import submission_client

    def unexpected_transport(*args, **kwargs):
        pytest.fail("Unresolved language must not reach a provider transport")

    monkeypatch.setattr(submission_client, "_submit_portal_template", unexpected_transport)
    monkeypatch.setattr(submission_client, "_submit_official_template", unexpected_transport)
    for language in ("", "und"):
        payload = TemplateSubmission(
            template_name="regional_review", language=language, client="tcl_promo",
            channel="whatsapp", category="MARKETING", waba_id="", source_ref="source!A1",
            components=[TemplateComponent(type="BODY", text="نیا پیغام")],
        )
        result = submission_client.submit_template(payload, client="tcl_promo")
        assert result.status == SubmissionStatus.FAILED
        assert "Choose the template language" in result.error


def test_planner_content_reference_is_not_message_copy(tmp_path):
    path = save_book(tmp_path, {"Plan": [
        ["Channel", "Time", "Logic", "Content reference"],
        ["SMS clickers", "within 15 mins", "OTP not verified", "scenario 1"],
    ]})
    assert parse_brief(str(path), path.name)["candidates"] == []


def test_section_and_multi_channel_sms_body_columns(tmp_path):
    path = save_book(tmp_path, {
        "Sections": [["Content", "SMS Promotional"], ["C1", MESSAGES[0]],
                     ["Content", "WhatsApp"], ["C1", MESSAGES[1]]],
        "Columns": [["Campaign Name", "Channel", "WhatsApp Text", "SMS Content"],
                    ["Campaign A", "Multi-Channel", MESSAGES[1], MESSAGES[2]]],
    })
    assert [item["text"] for item in parse_brief(str(path), path.name)["candidates"]] == [MESSAGES[0], MESSAGES[2]]
