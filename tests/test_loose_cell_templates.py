"""Selected-channel loose grids preserve cells, scripts, and source identity."""
import csv

import openpyxl
import pytest

from loader import load_from_csv, load_from_excel
from rcs_loader import load_rcs_from_csv, load_rcs_from_excel


def _load(path, channel, **kwargs):
    if channel == "whatsapp":
        loader = load_from_csv if path.suffix == ".csv" else load_from_excel
    else:
        loader = load_rcs_from_csv if path.suffix == ".csv" else load_rcs_from_excel
        if path.suffix != ".csv":
            kwargs["upload_media"] = False
    return loader(str(path), client="tcl_promo", **kwargs)


def _text(sub):
    if sub.channel == "rcs":
        return sub.text_message
    return next(component.text for component in sub.components if component.type == "BODY")


def _save(path, grids):
    if path.suffix == ".csv":
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            csv.writer(stream).writerows(grids[0][1])
        return
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for title, rows in grids:
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
    workbook.save(path)
    workbook.close()


@pytest.mark.parametrize("channel", ["whatsapp", "rcs"])
@pytest.mark.parametrize("extension", ["csv", "xlsx"])
@pytest.mark.parametrize("layout", ["vertical", "horizontal", "sparse"])
def test_every_headerless_message_cell_including_first_row_is_independent(tmp_path, channel, extension, layout):
    copy = ["வணக்கம்!", "તમારા {{1}} તૈયાર!", "आपले <नाव> तयार!", "  cafe\u0301 — اردو\n\n{{1}} [नाम]!?  "]
    if layout == "vertical":
        grid = [[value] for value in copy]
        cells = ["A1", "A2", "A3", "A4"]
    elif layout == "horizontal":
        grid = [copy]
        cells = ["A1", "B1", "C1", "D1"]
    else:
        grid = [[copy[0], None, copy[1]], [], [None, copy[2], None, copy[3]]]
        cells = ["A1", "C1", "B3", "D3"]
    path = tmp_path / f"temporary.{extension}"
    _save(path, [("Messages", grid)])
    source = f"original.{extension}"

    submissions = _load(path, channel, source_name=source)

    assert [_text(sub) for sub in submissions] == copy
    sheet = "original" if extension == "csv" else "Messages"
    assert [sub.source_ref for sub in submissions] == [f"{source}:{sheet}!{cell}" for cell in cells]
    assert len({sub.template_name for sub in submissions}) == len(copy)
    assert all(sub.channel == channel and sub.client == "tcl_promo" for sub in submissions)
    if channel == "rcs":
        assert all(sub.template_type == "text" and not sub.carousel_cards and not sub.suggestions for sub in submissions)
    else:
        assert all([component.type for component in sub.components] == ["BODY"] for sub in submissions)


@pytest.mark.parametrize("channel", ["whatsapp", "rcs"])
def test_all_sheets_and_merged_anchors_are_preserved_once(tmp_path, channel):
    path = tmp_path / "all.xlsx"
    _save(path, [("January", [["తెలుగు!", "ಕನ್ನಡ!"]]), ("Regional", [["മലയാളം!"], ["ਪੰਜਾਬੀ!"]])])
    workbook = openpyxl.load_workbook(path)
    sheet = workbook.create_sheet("Sparse")
    sheet["C4"] = "தமிழ் {{1}}!"
    sheet.merge_cells("C4:E5")
    workbook.active = 1
    workbook.save(path)
    workbook.close()

    submissions = _load(path, channel)

    assert len(submissions) == 5
    assert {sub.source_ref for sub in submissions} == {
        "all.xlsx:January!A1", "all.xlsx:January!B1", "all.xlsx:Regional!A1",
        "all.xlsx:Regional!A2", "all.xlsx:Sparse!C4",
    }
    assert _text(submissions[-1]) == "தமிழ் {{1}}!"


@pytest.mark.parametrize("channel", ["whatsapp", "rcs"])
def test_options_newlines_unicode_and_placeholders_are_not_english_split_or_rewritten(tmp_path, channel):
    text = "  Option 1: தமிழில் <பெயர்>!\n\nOption 2: आपले {{offer}} तयार — cafe\u0301.\nCTA: [तपासा] <link>  "
    path = tmp_path / "options.xlsx"
    _save(path, [("Messages", [[text]])])

    submissions = _load(path, channel)

    assert len(submissions) == 1
    assert _text(submissions[0]) == text
    assert submissions[0].source_ref == "options.xlsx:Messages!A1"


@pytest.mark.parametrize("text,language", [
    ("வா!", "ta"), ("આવો!", "gu"), ("రండి!", "te"), ("ಬನ್ನಿ!", "kn"),
    ("വരൂ!", "ml"), ("ਆਓ!", "pa"), ("ଆସନ୍ତୁ!", "or"),
    ("या!", ""), ("آئیں!", ""), ("বাংলা!", ""), ("தமிழ் ગુજરાતી!", ""), ("中文!", ""),
])
def test_short_regional_copy_uses_unique_scripts_or_requires_language_review(tmp_path, text, language):
    path = tmp_path / "regional.csv"
    _save(path, [("Messages", [[text]])])
    notes = []

    submissions = _load(path, "whatsapp", import_notes=notes)

    assert len(submissions) == 1
    assert _text(submissions[0]) == text
    assert submissions[0].language == language
    assert any("Language review required" in note for note in notes) is (language == "")


@pytest.mark.parametrize("channel", ["whatsapp", "rcs"])
def test_empty_numbers_formulas_and_url_only_cells_are_not_templates(tmp_path, channel):
    path = tmp_path / "filtered.xlsx"
    _save(path, [("Messages", [[None, 123, "123456", "=CONCAT(\"தமிழ்\")", "https://example.test/x", "www.example.test"], ["வா!"]])])

    submissions = _load(path, channel)

    assert [_text(sub) for sub in submissions] == ["வா!"]
    assert submissions[0].source_ref == "filtered.xlsx:Messages!A2"


@pytest.mark.parametrize("channel", ["whatsapp", "rcs"])
def test_true_metadata_and_planners_do_not_supply_loose_templates(tmp_path, channel):
    path = tmp_path / "metadata.xlsx"
    _save(path, [
        ("Messages", [["Product updates are ready.", "Link your account today.", "குறிப்பு: வாருங்கள்!"]]),
        ("Contacts", [["Name", "Address", "Phone"], ["Jane", "Mumbai", "9999999999"]]),
        ("Notes", [["வாருங்கள்! These are instructions, not customer copy."]]),
        ("Annual planner", [["வாருங்கள்! This planner is not approved copy."]]),
    ])

    submissions = _load(path, channel)

    assert [_text(sub) for sub in submissions] == ["Product updates are ready.", "Link your account today.", "குறிப்பு: வாருங்கள்!"]


@pytest.mark.parametrize("channel,column", [("whatsapp", "C2"), ("rcs", "D2")])
@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_explicit_channel_columns_never_leak_or_inherit_unscoped_regional_copy(tmp_path, channel, column, extension):
    path = tmp_path / f"mixed.{extension}"
    _save(path, [
        ("Regional matrix", [["Language", "SMS", "WA", "RCS", "PN"], ["Marathi", "SMS मजकूर!", "WA मजकूर!", "RCS मजकूर!", "PN मजकूर!"]]),
        ("Unlabelled regional", [["अनिश्चित मजकूर!"]]),
    ])

    submissions = _load(path, channel)

    assert len(submissions) == 1
    assert _text(submissions[0]) == ("WA मजकूर!" if channel == "whatsapp" else "RCS मजकूर!")
    title = "mixed" if extension == "csv" else "Regional matrix"
    assert submissions[0].source_ref == f"mixed.{extension}:{title}!{column}"
    if channel == "whatsapp":
        assert submissions[0].language == "mr"


@pytest.mark.parametrize("channel", ["whatsapp", "rcs"])
def test_short_regional_channel_rows_and_continuations_keep_their_channel(tmp_path, channel):
    path = tmp_path / "rows.xlsx"
    _save(path, [("Regional", [["Channel", "Tamil"], ["SMS", "எஸ்!"], ["WA", "வா!"], [None, "வாருங்கள்!"], ["RCS", "வாங்க!"], [None, "வருக!"], ["PN", "போ!"]])])

    submissions = _load(path, channel)

    assert [_text(sub) for sub in submissions] == (["வா!", "வாருங்கள்!"] if channel == "whatsapp" else ["வாங்க!", "வருக!"])


@pytest.mark.parametrize("channel", ["whatsapp", "rcs"])
def test_xls_dispatch_reuses_existing_legacy_reader_for_all_sheets(tmp_path, monkeypatch, channel):
    import sms_brief

    path = tmp_path / "regional.xls"
    calls = []

    def read_legacy(actual_path, filename):
        calls.append((actual_path, filename))
        return [("First", [["வா!", "આવો!"]]), ("Second", [[None, "రండి!"]])]

    monkeypatch.setattr(sms_brief, "_read_sheets", read_legacy)
    submissions = _load(path, channel)

    assert calls == [(str(path), "regional.xls")]
    assert [_text(sub) for sub in submissions] == ["வா!", "આવો!", "రండి!"]
    assert submissions[-1].source_ref == "regional.xls:Second!B1"


def test_explicit_rcs_carousel_sheet_keeps_each_language_cell_independent(tmp_path):
    path = tmp_path / "regional_cards.xlsx"
    _save(path, [
        ("SMS", [["SMS", "This SMS copy must not become RCS."]]),
        ("RCS Carousal", [
            [], [None, "Campaign heading, not message copy."], [], [],
            ["Generic", "First card copy.", None, "Second card copy."],
            ["Marathi", "पहिला मजकूर!", None, "दुसरा मजकूर!"],
            ["Tamil", "வா!", None, "வாருங்கள்!"],
        ]),
    ])

    submissions = _load(path, "rcs")

    assert [_text(sub) for sub in submissions] == [
        "First card copy.", "Second card copy.", "पहिला मजकूर!", "दुसरा मजकूर!", "வா!", "வாருங்கள்!",
    ]
    assert all(sub.template_type == "text" and not sub.carousel_cards for sub in submissions)
    assert {sub.source_ref for sub in submissions} == {
        f"regional_cards.xlsx:RCS Carousal!{col}{row}" for row in (5, 6, 7) for col in ("B", "D")
    }


@pytest.mark.parametrize("channel", ["whatsapp", "rcs"])
def test_actual_sms_language_grid_shape_never_becomes_selected_other_channel(tmp_path, channel):
    path = tmp_path / "sms_language_grid.xlsx"
    languages = ["English", "Marathi", "Kannada", "Hindi", "Tamil", "Telugu", "Bengali", "Gujarati"]
    rows = [["SMS content", *languages]]
    rows.extend([[f"SMS {index}", *(f"प्रादेशिक मजकूर {index}!" for _ in languages)] for index in range(1, 8)])
    _save(path, [("Sheet1", rows)])

    if channel == "whatsapp":
        with pytest.raises(ValueError, match="No WhatsApp copy"):
            _load(path, channel)
    else:
        assert _load(path, channel) == []


@pytest.mark.parametrize("channel", ["whatsapp", "rcs"])
def test_plain_message_identity_is_stable_across_temporary_upload_names(tmp_path, channel):
    first = tmp_path / "temp_first.xlsx"
    second = tmp_path / "temp_second.xlsx"
    _save(first, [("Messages", [["તમારા {{1}} તૈયાર!"], ["તમારા {{1}} તૈયાર!"]])])
    second.write_bytes(first.read_bytes())

    one = _load(first, channel, source_name="original.xlsx")
    two = _load(second, channel, source_name="original.xlsx")

    assert [sub.source_ref for sub in one] == ["original.xlsx:Messages!A1", "original.xlsx:Messages!A2"]
    assert [sub.template_name for sub in one] == [sub.template_name for sub in two]
    assert len({sub.template_name for sub in one}) == 2


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_unscoped_language_columns_preserve_declared_hints_without_reshaping(tmp_path, extension):
    path = tmp_path / f"translations.{extension}"
    _save(path, [("Messages", [["Marathi", "Urdu", "Tamil"], ["या {{1}}!", "آئیں {{1}}!", "வா {{1}}!"]])])

    submissions = _load(path, "whatsapp")

    assert [_text(sub) for sub in submissions] == ["या {{1}}!", "آئیں {{1}}!", "வா {{1}}!"]
    assert [sub.language for sub in submissions] == ["mr", "ur", "ta"]


def test_unscoped_language_rows_preserve_hints_and_whole_cells(tmp_path):
    path = tmp_path / "translation_rows.xlsx"
    _save(path, [("Messages", [["Marathi", "या {{1}}!", None, "आपले <नाव> तयार!"], ["Urdu", "آئیں {{1}}!"]])])

    submissions = _load(path, "whatsapp")

    assert [_text(sub) for sub in submissions] == ["या {{1}}!", "आपले <नाव> तयार!", "آئیں {{1}}!"]
    assert [sub.language for sub in submissions] == ["mr", "mr", "ur"]
