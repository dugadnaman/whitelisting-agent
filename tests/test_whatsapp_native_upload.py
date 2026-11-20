"""Consumer regressions for channel-scoped, source-preserving WhatsApp uploads."""

import csv
from io import BytesIO

import openpyxl
import pytest
from openpyxl.drawing.image import Image
from PIL import Image as PILImage

from loader import load_from_csv, load_from_excel


def _body(submission):
    return next(c.text for c in submission.components if c.type == "BODY")


def _header(submission):
    return next((c for c in submission.components if c.type == "HEADER"), None)


def _image(sheet, cell, color):
    data = BytesIO()
    PILImage.new("RGB", (2, 2), color).save(data, format="PNG")
    data.seek(0)
    sheet.add_image(Image(data), cell)


def test_mixed_workbook_extracts_all_months_and_source_cells(tmp_path):
    workbook = openpyxl.Workbook()
    may = workbook.active
    may.title = "May content"
    may.append(["SMS", "SMS copy must never be imported into WhatsApp."])
    may.append(["WA", "Hi <name>, your May personal loan offer is ready.\nCTA: {Get Funds Quickly} <link>\nT&Cs apply<link>"])
    may.append([None, "Hello <name>, a distinct May variant is waiting for you."])
    may.append(["PN", "Push notification copy must not be a WhatsApp template."])
    june = workbook.create_sheet("June content")
    june.append(["SMS", "Left SMS copy must not be imported.", None, "WA", "Right WhatsApp offer is available for your family."])
    june.append(["WA", "Left WhatsApp loan offer is ready for you.", None, "PN", "Right push notification must not be imported."])
    ambiguous = workbook.create_sheet("Dec content")
    ambiguous.append(["Hi <name>, this unlabelled offer needs channel confirmation."])
    campaign = workbook.create_sheet("WA")
    campaign.append(["Campaign Name", "TCLMOE_WhatsApp_July"])
    campaign.append(["C1", "Hello <name>, this utility update is now available for review."])
    campaign.append(["Link", "mentioned in database"])
    campaign.append([None, "Administrative notes should not restart the WhatsApp block."])
    path = tmp_path / "random_upload_a.xlsx"
    workbook.save(path)
    notes = []

    submissions = load_from_excel(str(path), client="tcl_promo", source_name="Original client brief.xlsx", import_notes=notes)

    assert len(submissions) == 5
    assert {s.source_ref for s in submissions} == {
        "Original client brief.xlsx:May content!B2", "Original client brief.xlsx:May content!B3",
        "Original client brief.xlsx:June content!E1", "Original client brief.xlsx:June content!B2",
        "Original client brief.xlsx:WA!B2",
    }
    assert all(s.channel == "whatsapp" and s.client == "tcl_promo" for s in submissions)
    assert all("must not" not in _body(s) and "must never" not in _body(s) for s in submissions)
    may_first = next(s for s in submissions if s.source_ref.endswith("May content!B2"))
    assert "CTA:" not in _body(may_first)
    assert _body(may_first).count("{{") == 1
    buttons = next(c.buttons for c in may_first.components if c.type == "BUTTONS")
    assert buttons[0]["text"] == "Get Funds Quickly"
    assert any("Dec content!A1" in note and "unscoped" in note.lower() for note in notes)
    assert any("month" in note.lower() for note in notes)


def test_regional_language_rows_columns_and_channel_columns(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Regional"
    sheet.append(["Channel", "English", "Marathi"])
    sheet.append(["SMS", "SMS offer is not WhatsApp copy.", "ही SMS ऑफर WhatsApp मजकूर नाही."])
    sheet.append(["WhatsApp", "Your English offer is ready for review.", "तुमची मराठी कर्जाची ऑफर आता तयार आहे."])
    sheet.append(["PN", "Push offer is not WhatsApp copy.", "ही पुश ऑफर WhatsApp मजकूर नाही."])
    sheet.append([])
    sheet.append(["WhatsApp", "31-40", "41-50", "Generic"])
    sheet.append(["English", "Your first age-group offer is now ready.", "Your second age-group offer is now ready.", "Your generic loan offer is now ready."])
    sheet.append(["Marathi", "तुमची पहिली मराठी कर्जाची ऑफर तयार आहे.", "तुमची दुसरी मराठी कर्जाची ऑफर तयार आहे.", "तुमची सर्वांसाठी मराठी कर्जाची ऑफर तयार आहे."])
    sheet.append(["PN", "31-40", "41-50", "Generic"])
    sheet.append(["Hindi", "यह पुश नोटिफिकेशन है और WhatsApp नहीं है।"])
    matrix = workbook.create_sheet("Regional matrix")
    matrix.append(["Language", "SMS", "WA", "PN"])
    matrix.append(["Marathi", "हा SMS मजकूर आहे आणि WhatsApp नाही.", "तुमच्या मराठी खात्याचे नवीन तपशील तयार आहेत.", "ही पुश सूचना WhatsApp मजकूर नाही."])
    path = tmp_path / "regional.xlsx"
    workbook.save(path)

    submissions = load_from_excel(str(path), client="tcl_promo")

    assert len(submissions) == 9
    assert {s.source_ref.rsplit(":", 1)[1] for s in submissions} == {
        "Regional!B3", "Regional!C3", "Regional!B7", "Regional!C7", "Regional!D7",
        "Regional!B8", "Regional!C8", "Regional!D8", "Regional matrix!C2",
    }
    assert [s.language for s in submissions].count("mr") == 5
    assert [s.language for s in submissions].count("en") == 4


def test_native_names_remain_unique_and_stable_across_temporary_uploads(tmp_path):
    workbook = openpyxl.Workbook()
    workbook.active.title = "WhatsApp"
    workbook.active.append(["WA", "Variant 1: Hello customer, your first offer is ready.\nVariant 2: Hello customer, your second offer is ready."])
    workbook.active.append([None, "Hello customer, this separate variant is ready for you."])
    paths = [tmp_path / "upload_random_one.xlsx", tmp_path / "upload_random_two.xlsx"]
    for path in paths:
        workbook.save(path)
    source_name = "A very long original filename that previously discarded every variant suffix.xlsx"

    first = load_from_excel(str(paths[0]), client="tcl_promo", source_name=source_name)
    second = load_from_excel(str(paths[1]), client="tcl_promo", source_name=source_name)

    assert len(first) == 3
    assert len({s.template_name for s in first}) == 3
    assert [s.template_name for s in first] == [s.template_name for s in second]
    assert all(s.template_name.startswith("att_") and len(s.template_name) <= 60 for s in first)
    assert {s.source_ref for s in first} == {f"{source_name}:WhatsApp!B1#1", f"{source_name}:WhatsApp!B1#2", f"{source_name}:WhatsApp!B2"}


def test_creatives_use_sheet_and_unambiguous_cell_anchors_not_archive_order(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "July Content"
    sheet.append(["SMS", "SMS copy owns the first embedded image, not WhatsApp."])
    sheet.append(["WA", "Your first WhatsApp offer has a matching creative."])
    sheet.append([None, "Your second WhatsApp offer has no matching creative."])
    _image(sheet, "C1", "red")
    _image(sheet, "C2", "blue")
    other = workbook.create_sheet("Nov content")
    other.append(["Channel", "A", "B"])
    other.append(["WA", "Your first November WhatsApp variant is available.", "Your second November WhatsApp variant is available."])
    _image(other, "E2", "green")
    _image(other, "E2", "yellow")
    parallel = workbook.create_sheet("Parallel")
    parallel.append(["SMS", "This SMS offer owns its own creative on the left.", None, "WA", "This WhatsApp offer must not borrow the SMS creative."])
    _image(parallel, "C1", "red")
    path = tmp_path / "creatives.xlsx"
    workbook.save(path)

    submissions = load_from_excel(str(path), client="tcl_promo")

    assert len(submissions) == 5
    first = next(s for s in submissions if s.source_ref.endswith("July Content!B2"))
    header = _header(first)
    assert header is not None and header.format == "IMAGE"
    with PILImage.open(BytesIO(header.image_bytes)) as image:
        assert image.getpixel((0, 0)) == (0, 0, 255)
    assert all(_header(s) is None for s in submissions if s is not first)


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_explicit_sms_upload_is_rejected_instead_of_fabricating_whatsapp(tmp_path, extension):
    path = tmp_path / f"sms.{extension}"
    rows = [["Template Name", "SMS 2"], ["sms_offer", "Unexpected expenses? Your personal loan offer is ready. Apply now: <link>"]]
    if extension == "csv":
        with path.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(rows)
        load = load_from_csv
    else:
        workbook = openpyxl.Workbook()
        for row in rows:
            workbook.active.append(row)
        workbook.save(path)
        load = load_from_excel

    with pytest.raises(ValueError, match="(?i)whatsapp.*SMS|SMS.*whatsapp"):
        load(str(path), client="tcl_promo")


def test_standard_and_semantic_workbook_contracts_work_across_all_sheets(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["template_name", "body", "header_type"])
    sheet.append(["standard_offer", "Your standard loan offer is ready for review.", "IMAGE"])
    _image(sheet, "D2", "blue")
    semantic = workbook.create_sheet("Semantic")
    semantic.append(["Copy ID", "Message Text"])
    semantic.append(["semantic_offer", "Your semantic loan offer is ready for review."])
    path = tmp_path / "standard.xlsx"
    workbook.save(path)

    submissions = load_from_excel(str(path), client="tcl_promo")

    assert len(submissions) == 2
    assert {s.template_name for s in submissions} == {"att_standard_offer", "att_semantic_offer"}
    assert _header(submissions[0]).image_bytes


def test_csv_channel_columns_and_rows_do_not_leak_other_channels(tmp_path):
    path = tmp_path / "mixed.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows([
            ["template_name", "body", "channel"],
            ["sms_offer", "Your SMS loan offer must not become WhatsApp copy.", "sms"],
            ["wa_offer", "Your WhatsApp loan offer is now ready for review.", "whatsapp"],
        ])
    submissions = load_from_csv(str(path), client="tcl_promo")
    assert len(submissions) == 1
    assert submissions[0].template_name == "att_wa_offer"


@pytest.mark.parametrize("filename,sheet_name,reorder", [
    ("campaign_ZX-4182.xlsx", "Archive September", False),
    ("regional_KL-905.xlsx", "Client translations", True),
])
def test_channel_copy_lookalikes_and_sheet_order_do_not_change_native_identity(tmp_path, filename, sheet_name, reorder):
    book = openpyxl.Workbook()
    cover = book.active
    cover.title = "Overview"
    cover.append(["Customer copy without channel approval must be excluded."])
    sheet = book.create_sheet(sheet_name)
    sheet.append(["Channel", "Content"])
    sheet.append(["WA", "WhatsApp content is ready for your account."])
    sheet.append([None, "SMS offers are not a channel label inside this copy."])
    sheet.append(["PN", "Notification content must stay outside WhatsApp."])
    sheet.append([None, "This continuation still belongs to the push channel."])
    wrong_channel = book.create_sheet("SMS")
    wrong_channel.append(["WA", "A copied WA label cannot override an SMS worksheet."])
    planner = book.create_sheet("Annual planner")
    planner.append(["WA", "Planner entries are not approved message content."])
    paths = [tmp_path / "random_first.xlsx", tmp_path / "random_second.xlsx"]
    book.save(paths[0])
    if reorder:
        book.move_sheet(sheet, offset=-1)
    book.active = book.sheetnames.index("Overview")
    book.save(paths[1])
    results = []
    for path in paths:
        notes = []
        submissions = load_from_excel(str(path), client="tcl_promo", source_name=filename, import_notes=notes)
        assert [_body(item) for item in submissions] == [
            "WhatsApp content is ready for your account.",
            "SMS offers are not a channel label inside this copy.",
        ]
        assert {item.source_ref for item in submissions} == {f"{filename}:{sheet_name}!B2", f"{filename}:{sheet_name}!B3"}
        assert any("Overview!A1" in note and "unscoped" in note for note in notes)
        assert any("SMS" in note and "excluded" in note for note in notes)
        assert any("planner" in note and "excluded" in note for note in notes)
        results.append({item.source_ref: item.template_name for item in submissions})
    assert results[0] == results[1]


@pytest.mark.parametrize("sheet_name, imported", [("Overview", False), ("Translations requested", True)])
def test_plain_message_grids_use_selected_channel_but_overview_sheets_do_not(tmp_path, sheet_name, imported):
    book = openpyxl.Workbook()
    book.active.title = sheet_name
    book.active.append(["An unlabelled customer offer requires channel confirmation."])
    path = tmp_path / "arbitrary_customer_file.xlsx"
    book.save(path)
    notes = []
    if imported:
        submissions = load_from_excel(str(path), client="tcl_promo", import_notes=notes)
        assert [_body(submission) for submission in submissions] == ["An unlabelled customer offer requires channel confirmation."]
        assert submissions[0].source_ref == f"arbitrary_customer_file.xlsx:{sheet_name}!A1"
    else:
        with pytest.raises(ValueError, match="(?i)No WhatsApp copy"):
            load_from_excel(str(path), client="tcl_promo", import_notes=notes)
        assert any(f"{sheet_name}!A1" in note and "unscoped" in note for note in notes)
