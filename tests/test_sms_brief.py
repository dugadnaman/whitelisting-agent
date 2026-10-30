"""Sanitized workbook layouts and fail-closed, pure review validation."""

import re
import zipfile
from copy import deepcopy

import openpyxl
import pytest

import sms_brief
from sms_brief import parse_brief, validate_brief_review


def workbook(tmp_path, sheets, filename="synthetic.xlsx"):
    path = tmp_path / filename
    book = openpyxl.Workbook()
    book.remove(book.active)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    book.save(path)
    return path


def test_persona_language_columns_exact_copy_continuations_and_metadata(tmp_path):
    body = "  Hi <Name>,\nYour  offer is available. Visit [link].  "
    path = workbook(tmp_path, {"Persona": [
        ["Channel", "Content", "Use Case", None, "Kannada", "Hindi"],
        ["SMS", body, "Family expenses", 157, "नमस्ते, यह आपका विशेष प्रस्ताव है।", "નમસ્તે, આ તમારી ખાસ ઓફર છે."],
        [None, "An alternative with preserved punctuation!", "Inventory", 123],
        ["SMS retargeting", "Your application is waiting. Continue today."],
        [None, "Another reminder, with exact spacing. "],
        ["WA", "Not SMS even when the copy is quite long."],
        [None, "This continuation belongs to WhatsApp only."],
        ["PN", "This notification is not SMS content either."],
    ]})
    report = parse_brief(str(path), path.name)
    items = report["candidates"]
    assert len(items) == 6
    assert items[0]["text"] == body
    assert items[0]["cell"] == "B2"
    assert items[0]["variables"] == ["<Name>", "[link]"]
    assert items[0]["segment"] == "Family expenses"
    assert items[1]["language"] == "Kannada"
    assert any("script" in warning for warning in items[1]["warnings"])
    assert items[2]["language"] == "Hindi"
    assert any("script" in warning for warning in items[2]["warnings"])
    assert [i["cell"] for i in items] == ["B2", "E2", "F2", "B3", "B4", "B5"]
    assert report["sheets"] == [{"name": "Persona", "candidate_count": 6}]


def test_headerless_monthly_rows_and_cross_channel_exclusion(tmp_path):
    path = workbook(tmp_path, {"Historical August": [
        ["SMS", "First historical offer, no body header needed."],
        [None, "Historical alternate body with more details."],
        ["SMS Retargetting", "Your older application is still waiting."],
        ["WA", "Do not take this WhatsApp body as an SMS."],
        [None, "Do not take its continuation as an SMS."],
        ["PN", "A push notification body is also excluded."],
    ], " Nov Content": [
        ["Channel", "Highlish + Witty", "Normal English"],
        ["SMS", "Aapka synthetic offer is ready for review.", "Your synthetic offer is ready for review."],
    ]})
    items = parse_brief(str(path), path.name)["candidates"]
    assert len(items) == 5
    assert {i["sheet"] for i in items} == {"Historical August", " Nov Content"}
    assert [i["language"] for i in items[-2:]] == ["Hinglish", "English"]


def test_parallel_channel_product_blocks_never_share_state(tmp_path):
    path = workbook(tmp_path, {"June": [
        [None, "Term product", None, None, None, None, None, "Hybrid product", "Characters", "Remark"],
        ["SMS", "The term product primary offer is available.", 160, None, None, None, "SMS", "The hybrid product primary offer is available.", 170, "Curiosity led"],
        [None, "The term product continuation remains SMS.", 160, None, None, None, "WA", "This hybrid product body is WhatsApp only.", 170, "Offer led"],
        ["WA", "This term product body is WhatsApp only.", None, None, None, None, "SMS Retargeting", "This hybrid reminder is a legitimate SMS."],
        [None, "Still WhatsApp in the left-hand product.", None, None, None, None, None, "Still SMS in the right-hand product."],
    ]})
    items = parse_brief(str(path), path.name)["candidates"]
    assert [i["cell"] for i in items] == ["B2", "B3", "H2", "H4", "H5"]
    assert items[0]["segment"] == "Term product"
    assert items[-1]["segment"] == "Hybrid product"
    assert "Retargeting" in items[-1]["scope"]


def test_campaign_blocks_keep_old_and_new_campaigns_and_stop_at_metadata(tmp_path):
    path = workbook(tmp_path, {"SMS": [
        ["SMS Whole Base"],
        ["PA", None, None, "PQ"],
        ["Campaign Name", "Synthetic_PA_Nov26", None, "Campaign Name", "Synthetic_PQ_Mar26"],
        ["SMS Text", "Current campaign original body is available.", None, "SMS Text", "Historical campaign body is also available."],
        [None, "Current campaign continuation is preserved."],
        ["Link", "https://example.test", None, "Link", "https://example.test/old"],
        [None, "Metadata continuation must not become SMS.", None, None, "Another metadata continuation is excluded."],
        ["Testing Mob No", "0000000000, 1111111111"],
        ["Database", "Synthetic database instruction with long name."],
        ["SMS Retargeting"],
        ["Campaign Name", "Synthetic_PA_Retarget", None, "Campaign Name", "Synthetic_PQ_Retarget"],
        ["C1", "A labeled campaign variant should be kept.", None, "SMS Text", "Right-hand retargeting copy should be kept."],
        ["C2", "Another labeled campaign variant is valid."],
        ["Link", "mentioned in database"],
    ]})
    items = parse_brief(str(path), path.name)["candidates"]
    assert {i["cell"] for i in items} == {"B4", "B5", "E4", "B12", "B13", "E12"}
    assert next(i for i in items if i["cell"] == "E4")["campaign"] == "Synthetic_PQ_Mar26"
    assert next(i for i in items if i["cell"] == "B4")["campaign"] == "Synthetic_PA_Nov26"
    assert all(i["source_kind"] == "campaign_block" for i in items)


def test_shared_labels_parallel_variant_scopes_and_literal_looking_tokens(tmp_path):
    body = "Hello <Name>, your <Pre-Approved> <Personal Loan Top-Up> is available. Visit [link], code (XXX)."
    path = workbook(tmp_path, {"SMS": [
        ["SMS Non Clicker", None, "SMS Retargeting"],
        ["Campaign Name", "Synthetic_Nov26", "Synthetic_Retarget_Nov26"],
        ["SMS Text", body, "This synthetic reminder is a distinct body."],
        [None, "Another primary variant remains unchanged.", "Another retargeting variant is unchanged."],
        ["CTA / LINK", "Mentioned in database", "Mentioned in database"],
        [None, "Must not continue after the metadata marker."],
    ]})
    items = parse_brief(str(path), path.name)["candidates"]
    assert len(items) == 4
    assert items[0]["variables"] == ["<Name>", "<Pre-Approved>", "<Personal Loan Top-Up>", "[link]", "(XXX)"]
    assert items[0]["text"] == body
    assert items[1]["scope"] == "SMS Retargeting"
    assert items[-1]["campaign"] == "Synthetic_Retarget_Nov26"


def test_service_implicit_scope_survives_sms_utility_body_label(tmp_path):
    body = "Hello {#var#}, new details about {#var#}{#var#} are available."
    path = workbook(tmp_path, {"SMS": [
        ["SMS Service Implicit"],
        ["Campaign Name", "Synthetic_Implicit_Feb26"],
        ["SMS Utility", body],
        ["Link", "https://example.test/"],
    ]})
    item, = parse_brief(str(path), path.name)["candidates"]
    assert item["text"] == body
    assert item["scope"] == "SMS Service Implicit"
    assert item["suggested_template_type"] == "3"
    assert item["variables"] == ["{#var#}"] * 3


def test_language_rows_channel_columns_and_repeated_language_headers(tmp_path):
    path = workbook(tmp_path, {"Regional August": [
        ["Lang", "SMS", "WA", "PN"],
        ["English", "Your regional SMS copy is available today.", "Your WhatsApp copy is not an SMS candidate.", "Your push copy is not an SMS candidate."],
        ["Hindi", "नमस्ते, आपका विशेष प्रस्ताव उपलब्ध है।"],
    ], "Regional content": [
        ["Channel", "English", "Hindi"],
        ["SMS", "The first regional SMS section is available.", "नमस्ते, यह पहला विशेष प्रस्ताव है।"],
        ["PN", "A notification should not become SMS copy."],
        ["Regional", "English", "Kannada"],
        ["SMS", "The repeated header begins another section.", "ನಮಸ್ಕಾರ, ನಿಮ್ಮ ವಿಶೇಷ ಕೊಡುಗೆ ಲಭ್ಯವಿದೆ."],
        ["PN title", "Do not take notification title as SMS copy."],
        ["English", "This unlabelled WhatsApp-like section is ambiguous."],
    ]})
    report = parse_brief(str(path), path.name)
    assert len(report["candidates"]) == 6
    assert [(i["cell"], i["language"]) for i in report["candidates"][-2:]] == [("B5", "English"), ("C5", "Kannada")]
    assert any("ambiguous" in warning for warning in report["warnings"])


def test_non_sms_sheets_copied_sms_labels_planners_and_ambiguous_matrices(tmp_path):
    sheets = {name: [["Campaign Name", "Synthetic_campaign"], ["SMS Text", "Misleading copied SMS label must be excluded."]]
              for name in ("RCS", "WA", "PN", "1 week Planner", "RCS Carousal")}
    sheets["Regional"] = [[None, "31-40", "Generic"], ["English", "Unscoped regional copy needs clarification.", "Another unscoped regional copy is not approved SMS."]]
    path = workbook(tmp_path, sheets)
    report = parse_brief(str(path), path.name)
    assert report["candidates"] == []
    assert len(report["sheets"]) == 6
    assert any("ambiguous regional" in warning for warning in report["warnings"])
    assert all(sheet["candidate_count"] == 0 for sheet in report["sheets"])


def test_flat_channel_campaign_rows_and_variant_columns(tmp_path):
    path = workbook(tmp_path, {"Flat": [
        ["Channel", "Campaign Name", "Content", "Segment"],
        ["SMS", "Synthetic_Old", "The old campaign source is explicitly retained.", "Returning"],
        ["SMS", "Synthetic_New", "The new campaign source is explicitly retained.", "New"],
    ], "Variants": [
        ["Channel", "A", "B", "C", "D"],
        ["SMS", "Variant A synthetic body is available.", "Variant B synthetic body is available.", "Variant C synthetic body is available.", "Variant D synthetic body is available."],
    ]})
    items = parse_brief(str(path), path.name)["candidates"]
    assert len(items) == 6
    assert [(i["campaign"], i["segment"]) for i in items[:2]] == [("Synthetic_Old", "Returning"), ("Synthetic_New", "New")]
    assert [i["segment"] for i in items[2:]] == ["A", "B", "C", "D"]


def test_safe_names_are_deterministic_source_unique_and_no_copy_deduplication(tmp_path):
    path = workbook(tmp_path, {"हिन्दी synthetic!": [
        ["SMS", "The exact same synthetic copy appears twice."],
        [None, "The exact same synthetic copy appears twice."],
    ]})
    first = parse_brief(str(path), path.name)
    second = parse_brief(str(path), path.name)
    assert first == second
    items = first["candidates"]
    assert len(items) == 2
    assert items[0]["id"] != items[1]["id"]
    assert items[0]["suggested_template_name"] != items[1]["suggested_template_name"]
    assert all(len(i["suggested_template_name"]) <= 60 and re.fullmatch(r"[A-Za-z0-9_]+", i["suggested_template_name"]) for i in items)


def test_formulas_urls_counts_and_phone_only_cells_are_not_copy(tmp_path):
    path = workbook(tmp_path, {"Monthly": [
        ["SMS", '=CONCAT("Never execute formulas", " as copy")'],
        [None, "https://example.test/long/path/not-a-message"],
        [None, "0000000000, 1111111111"],
        [None, 185],
        [None, "This is the legitimate non-formula SMS body."],
        ["Notes", "Do not import these long internal instructions."],
        [None, "Nor a continuation after the notes marker."],
    ]})
    # The explicit channel must be discoverable even when its first cell is a formula.
    report = parse_brief(str(path), path.name)
    assert [i["cell"] for i in report["candidates"]] == ["B5"]


def review(original="Hello <Name>, your offer is ready."):
    return {"original_text": original,
            "sources": [{"sheet": "Synthetic", "cell": "B2", "campaign": "Synthetic_old", "segment": "", "language": "English"}],
            "warnings": [], "variables": [{"token": token, "kind": "alp", "sample": "Sample"} for token in sms_brief._TOKEN.findall(original)],
            "acknowledged": True}


def test_review_repeated_variables_unicode_and_explicit_manual_copy_edits():
    metadata = review("😀 Hello {#var#}, code {#var#}. See [link].")
    metadata["variables"] = [
        {"token": "{#var#}", "kind": "alp", "sample": "Reader"},
        {"token": "{#var#}", "kind": "num", "sample": "123"},
        {"token": "[link]", "kind": "urg", "sample": "https://example.test"},
    ]
    assert validate_brief_review(metadata, "😀 Hello {#alp#}, code {#num#}. See {#urg#}.") == []
    assert validate_brief_review(metadata, "An explicitly edited final message with {#alp#}.") == []
    metadata["variables"][0]["sample"] = ""
    assert any("sample" in error for error in validate_brief_review(metadata, "Reviewed body."))


def test_review_literal_vs_variable_choices_are_per_occurrence():
    metadata = review("Hi <Name>, <Pre-Approved> offer. <Name> again.")
    metadata["variables"][1].update(kind="literal", sample="")
    assert validate_brief_review(metadata, "Hi {#alp#}, <Pre-Approved> offer. {#alp#} again.") == []
    assert validate_brief_review(metadata, "Hi <Name>, <Pre-Approved> offer. {#alp#} again.")
    metadata = review("Use [link] literally once, but replace [link] the second time.")
    metadata["variables"][0].update(kind="literal", sample="")
    assert validate_brief_review(metadata, "Use [link] literally once, then {#urg#}.") == []
    assert validate_brief_review(metadata, "Use [link] twice: [link].")


def test_review_token_order_acknowledgement_and_legacy_tokens():
    metadata = review("Hi {{name}}, confirm <amount> and (XXX).")
    metadata["variables"].reverse()
    assert any("source token" in error for error in validate_brief_review(metadata, "Reviewed final body."))
    metadata = review()
    metadata["acknowledged"] = 1
    assert any("Acknowledge" in error for error in validate_brief_review(metadata, "Hi {#alp#}, your offer is ready."))
    metadata = review()
    assert any("unresolved" in error for error in validate_brief_review(metadata, "Hi {#var#}, your offer is ready."))
    metadata["variables"][0]["kind"] = ""
    assert any("Resolve" in error for error in validate_brief_review(metadata, "Hi {#alp#}."))


@pytest.mark.parametrize("metadata", [None, [], "bad", 1, {}, {"sources": [None]},
    {"original_text": [], "sources": "bad", "warnings": {}, "variables": None},
    {"original_text": "Hello <Name>, your offer is ready.", "variables": [{"token": "<Name>", "kind": [], "sample": "x"}]}])
def test_malformed_review_returns_errors_not_exceptions(metadata):
    assert validate_brief_review(metadata, "Synthetic final body.")


@pytest.mark.parametrize("change", [
    {"sources": []}, {"sources": [{}]}, {"sources": [{"sheet": "A", "cell": "B0", "campaign": "", "segment": "", "language": ""}]},
    {"warnings": [None]}, {"variables": []}, {"variables": [None]}, {"original_text": ""},
])
def test_malformed_review_fields_fail_closed(change):
    metadata = deepcopy(review())
    metadata.update(change)
    assert validate_brief_review(metadata, "Reviewed final body.")


def test_invalid_workbook_and_unsupported_extension_return_actionable_errors(tmp_path):
    path = tmp_path / "invalid.xlsx"
    path.write_bytes(b"not an excel file")
    with pytest.raises(ValueError, match="valid.*xlsx"):
        parse_brief(str(path), path.name)
    with pytest.raises(ValueError, match="xlsx or .xls"):
        parse_brief(str(path), "wrong.csv")


def test_expanded_size_and_cell_limits_fail_closed(tmp_path, monkeypatch):
    path = workbook(tmp_path, {"SMS": [["SMS", "Synthetic copy for safe size limit testing."]]})
    monkeypatch.setattr(sms_brief, "MAX_EXPANDED_BYTES", 1)
    with pytest.raises(ValueError, match="expanded size"):
        parse_brief(str(path), path.name)
    monkeypatch.setattr(sms_brief, "MAX_EXPANDED_BYTES", 80 * 1024 * 1024)
    monkeypatch.setattr(sms_brief, "MAX_CELLS", 1)
    with pytest.raises(ValueError, match="cell"):
        parse_brief(str(path), path.name)


def test_candidate_limit_rejects_instead_of_silently_truncating(tmp_path, monkeypatch):
    path = workbook(tmp_path, {"SMS": [["SMS", "First synthetic copy is available today."], [None, "Second synthetic copy is available today."]]})
    monkeypatch.setattr(sms_brief, "MAX_CANDIDATES", 1)
    with pytest.raises(ValueError, match="too many SMS candidates"):
        parse_brief(str(path), path.name)


def test_pathological_declared_dimensions_are_rejected(tmp_path):
    path = tmp_path / "dimensions.xlsx"
    original = workbook(tmp_path, {"SMS": [["SMS", "Synthetic safe body for dimension testing."]]}, "original.xlsx")
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(path, "w") as target:
        for entry in source.infolist():
            data = source.read(entry.filename)
            if entry.filename == "xl/worksheets/sheet1.xml":
                data = data.replace(b'ref="A1:B1"', b'ref="A1:XFD1048576"')
            target.writestr(entry, data)
    with pytest.raises(ValueError, match="dimensions"):
        parse_brief(str(path), path.name)
