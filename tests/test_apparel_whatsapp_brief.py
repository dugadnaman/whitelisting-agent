import csv
import io

import pytest

from apparel_whatsapp_brief import read_brief, read_sheet_values, tracking_window


def brief(columns=(403, 404, 405, 406)):
    values = [[None] * (max(columns) + 1) for _ in range(24)]
    fields = {
        2: ("Owner", "Naman"), 3: ("Brief Date", "27th October2026"),
        4: ("Send Date and Day", "29th October|Thursday"), 5: ("Send Time", "6:30PM"),
        6: ("Campaign Name", "VS_Tili_ON_ATC"),
        7: ("Track the Goal for No.ofHours/Days", "29th October-1st November2026"),
        10: ("SenderID/WhatsApp Number", "8657864167"),
        11: ("TemplateID", "\u200bvs_tili_on_atc\ufeff"), 12: ("TemplateType", "Simple"),
        13: ("TargetAudience/Include", "VS_ON_ATC_91D_No_Pr"),
        14: ("Exclude", "AGIPL Internal"),
        15: ("BodyCopy/IfVariables", 'Use customer name; "Gorgeous" as fallback'),
        16: ("ImageURL", "https://drive.google.com/drive/folders/images"),
        17: ("CTALink", "Shop Now:\nhttps://example.com/shop?q=x\n\nDownload App:\nhttps://example.com/app"),
        18: ("GlobalControlGroup", "No"), 19: ("Notes", "Preserve this copy.  Exactly."),
        21: ("CampaignID", "\u200bexisting-id"), 24: ("CampaignStatus", "Draft"),
    }
    for row, (label, value) in fields.items():
        values[row - 1][0] = label
        for index, col in enumerate(columns):
            values[row - 1][col] = value + (f"_{index}" if row == 6 else "")
    return values


def test_physical_campaign_columns_and_canonical_fields():
    records = read_sheet_values(brief(), "VS", "sheet-url")
    assert [row["row_id"] for row in records] == ["WhatsApp!ON", "WhatsApp!OO", "WhatsApp!OP", "WhatsApp!OQ"]
    assert [row["campaign_name"] for row in records] == [f"VS_Tili_ON_ATC_{i}" for i in range(4)]
    for row in records:
        assert "_row_error" not in row
        assert "_row_warnings" not in row
        assert row["scheduled_at"] == "2026-10-29T18:30:00+05:30"
        assert row["tracking_value"] == "3"
        assert row["tracking_unit"] == "days"
        assert row["tracking_end"] == "2026-11-01T18:30:00+05:30"
        assert row["segment_name"] == "VS_ON_ATC_91D_No_Pr"
        assert row["exclude_segment_name"] == "AGIPL Internal"
        assert row["whatsapp_template_id"] == "vs_tili_on_atc"
        assert row["existing_campaign_id"] == "existing-id"
        assert row["source_ref"] == "sheet-url"
        assert row["whatsapp_name_fallback"] == "Gorgeous"
        assert row["notes"] == "Preserve this copy.  Exactly."
        assert row["whatsapp_cta_links"] == '{"Shop Now": "https://example.com/shop?q=x", "Download App": "https://example.com/app"}'
        assert all(isinstance(value, str) for value in row.values())


@pytest.mark.parametrize("text,start,value,end", [
    ("28th February-1st March2024", "2024-02-28T10:00:00+05:30", "2", "2024-03-01"),
    ("31st December-2nd January2027", "2026-12-31T10:00:00+05:30", "2", "2027-01-02"),
    ("31st December2026-2nd January", "2026-12-31T10:00:00+05:30", "2", "2027-01-02"),
    ("24 hours", "2026-10-29T10:00:00+05:30", "24", "2026-10-30"),
    ("3 days", "2026-10-29T10:00:00+05:30", "3", "2026-11-01"),
])
def test_elapsed_tracking_boundaries(text, start, value, end):
    result = tracking_window(text, start)
    assert result["tracking_value"] == value
    assert result["tracking_end"].startswith(end)


@pytest.mark.parametrize("text", ["", "0 days", "-1 days", "1st November2026-29th October2026", "29th October-29th October2026"])
def test_invalid_tracking_is_rejected(text):
    with pytest.raises(ValueError):
        tracking_window(text, "2026-10-29T18:30:00+05:30")


def test_missing_inputs_are_visible_and_columns_never_shift():
    values = brief((2, 4))
    values[5][2] = ""
    values[9][2] = ""
    values[10][4] = ""
    records = read_sheet_values(values, "VS", "input")
    assert [row["row_id"] for row in records] == ["WhatsApp!C", "WhatsApp!E"]
    assert all("_row_error" not in row for row in records)
    assert "Missing campaign_name" in records[0]["_row_warnings"]
    assert "Missing whatsapp_sender" in records[0]["_row_warnings"]
    assert "Missing whatsapp_template_id" in records[1]["_row_warnings"]
    assert len(read_sheet_values(values, "VS", "input", columns=["E"])) == 1
    assert read_sheet_values(values, "VS", "input", sheet="SMS") == []


@pytest.mark.parametrize("brief_date,send_date,tracking,expected", [
    ("26th Aug", "29th Aug", "7 days", "2026-08-29T09:00:00+05:30"),
    ("26th Aug2025", "29th Aug", "7 days", "2025-08-29T09:00:00+05:30"),
    ("26th Aug2026", "29th Aug2027", "7 days", "2027-08-29T09:00:00+05:30"),
    ("26th Aug", "29th Aug", "29th Aug-1st September2027", "2027-08-29T09:00:00+05:30"),
])
def test_client_confirmed_brief_year_and_explicit_sheet_years(brief_date, send_date, tracking, expected):
    values = brief((2,))
    values[2][2], values[3][2], values[4][2], values[6][2] = brief_date, send_date, "9:00 AM", tracking
    values[16][2] = "https://www.charleskeith.in/in/stores?utm_source=CRM&utm_medium=WhatsApp"
    record = read_sheet_values(values, "CK", "input")[0]
    assert record["scheduled_at"] == expected
    assert record["send_date"] == send_date and record["send_time"] == "9:00 AM"
    assert record["cta_raw"] == values[16][2]
    assert "_row_warnings" not in record


def test_missing_send_time_is_not_invented():
    values = brief((2,))
    values[4][2] = ""
    assert read_sheet_values(values, "CK", "input")[0]["scheduled_at"] == ""


def test_screenshot_spacers_do_not_create_phantom_campaigns():
    # Zero-based DJ/DK/DL/DM/DN positions, including mapped separator metadata.
    values = brief((113, 116))
    for cells in values:
        cells.extend([None] * (118 - len(cells)))
    for column in (114, 115, 117):
        values[1][column] = "Owner"
        values[2][column] = "27th October2026"
        values[3][column] = "29th October|Thursday"
        values[4][column] = "6:30PM"
        values[6][column] = "3 days"
        values[17][column] = "No"
        values[18][column] = "separator notes"
        values[23][column] = "Draft"
        values[0][column] = "Unmapped formatting"
    values[0][0] = "Unmapped row"
    records = read_sheet_values(values, "VS", "input")
    assert [row["row_id"] for row in records] == ["WhatsApp!DJ", "WhatsApp!DM"]
    assert [row["campaign_name"] for row in records] == ["VS_Tili_ON_ATC_0", "VS_Tili_ON_ATC_1"]
    assert read_sheet_values(values, "VS", "input", columns=["DK", "DL", "DN"]) == []


@pytest.mark.parametrize("field", [
    "Campaign Name", "TemplateID", "SenderID", "BodyCopy", "TargetAudience",
    "Exclude", "ImageURL", "CTALink", "CampaignID",
])
def test_single_campaign_bearing_field_retains_partial_campaign(field):
    record = read_sheet_values([[field, "", "Supplied content"]], "VS", "input")[0]
    assert record["row_id"] == "WhatsApp!C"
    assert "_row_error" not in record
    assert isinstance(record["_row_warnings"], str)
    assert "Missing" in record["_row_warnings"]


def test_incomplete_schedule_and_cta_remain_source_values_not_errors():
    values = brief((2,))
    values[2][2] = "27th October"
    values[3][2] = "29th October|Thursday"
    values[4][2] = "Evening, confirm with owner"
    values[6][2] = "3 days"
    values[16][2] = "Shop Now:\nURL to be supplied"
    record = read_sheet_values(values, "VS", "input")[0]
    assert "_row_error" not in record
    assert "CTA requires" in record["_row_warnings"]
    assert "; " in record["_row_warnings"]
    assert record["scheduled_at"] == ""
    assert record["whatsapp_cta_links"] == ""
    assert record["send_date"] == values[3][2]
    assert record["send_time"] == values[4][2]
    assert record["cta_raw"] == values[16][2]
    assert record["whatsapp_variable_instructions"] == values[14][2]
    assert all(isinstance(value, str) for value in record.values())


def test_csv_and_xlsx_preserve_hyperlinks_and_ignore_other_sheets():
    import openpyxl
    values = brief((2,))
    text = io.StringIO()
    csv.writer(text).writerows(values)
    assert read_brief("brief.csv", text.getvalue().encode(), "VS")[0]["row_id"] == "WhatsApp!C"
    workbook = openpyxl.Workbook()
    workbook.active.title = "Other"
    workbook.active.append(["Tata", "tomorrow", "test"])
    sheet = workbook.create_sheet("WhatsApp")
    for row in values:
        sheet.append(row)
    sheet.cell(16, 3).hyperlink = "https://drive.google.com/drive/folders/real"
    sheet.cell(16, 3).value = "Images"
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    record = read_brief("brief.xlsx", stream.getvalue(), "VS")[0]
    assert record["whatsapp_image_url"] == "https://drive.google.com/drive/folders/real"
    assert record["campaign_name"] == "VS_Tili_ON_ATC_0"


def test_xlsx_numeric_sender_and_multi_link_cta_text_survive_google_export():
    import json
    import openpyxl
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "WhatsApp"
    for row in brief((2,)):
        sheet.append(row)
    sheet.cell(10, 3).value = 8657864167.0
    sheet.cell(17, 3).hyperlink = "https://example.com/shop?q=x"
    sheet.cell(11, 3).hyperlink = "https://dashboard-03.moengage.com/template"
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    record = read_brief("export.xlsx", stream.getvalue(), "VS")[0]
    assert "_row_warnings" not in record
    assert record["whatsapp_sender"] == "8657864167"
    assert record["whatsapp_template_id"] == "vs_tili_on_atc"
    assert json.loads(record["whatsapp_cta_links"]) == {
        "Shop Now": "https://example.com/shop?q=x",
        "Download App": "https://example.com/app",
    }


@pytest.mark.parametrize("brand", ["Crocs", "AGIPL", "R&B", "CK"])
@pytest.mark.parametrize("tracking", ["", "-", "No goals"])
def test_goal_free_brands_do_not_require_irrelevant_tracking_configuration(brand, tracking):
    values = brief((2,))
    values[6][2] = tracking
    assert "_row_warnings" not in read_sheet_values(values, brand, "brief")[0]


def test_limits_and_unknown_inputs():
    with pytest.raises(ValueError, match="5 MiB"):
        read_brief("brief.csv", b"x" * (5 * 1024 * 1024 + 1), "VS")
    with pytest.raises(ValueError, match="Only XLSX"):
        read_brief("brief.xls", b"", "VS")
    with pytest.raises(ValueError, match="Unknown Apparel"):
        read_sheet_values(brief((2,)), "Tata", "input")


def test_send_year_rolls_forward_from_explicit_brief_year():
    values = brief((2,))
    values[2][2] = "30th December2026"
    values[3][2] = "1st January|Friday"
    values[6][2] = "2 days"
    record = read_sheet_values(values, "VS", "input")[0]
    assert record["scheduled_at"] == "2027-01-01T18:30:00+05:30"
    assert record["tracking_end"] == "2027-01-03T18:30:00+05:30"


class GoogleResponse:
    def __init__(self, payload=None, *, content=None, status=200, mime="application/json"):
        import json
        self.content = content if content is not None else json.dumps(payload).encode()
        self.status_code = status
        self.headers = {"Content-Type": mime}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start:start + chunk_size]


class GoogleSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def test_google_sheet_reads_only_whatsapp_and_preserves_column_identity(monkeypatch):
    import apparel_whatsapp_google as google
    spreadsheet_id = "a" * 30
    grid = [{"values": [{"formattedValue": value or ""} for value in row]} for row in brief()]
    grid[15]["values"][403] = {"formattedValue": "Images", "hyperlink": "https://drive.google.com/drive/folders/" + "b" * 30}
    session = GoogleSession([GoogleResponse({"sheets": [{"properties": {"title": "WhatsApp"}, "data": [{"rowData": grid}]}]})])
    monkeypatch.setattr(google, "_session", lambda scopes: session)
    rows = google.read_google_brief(f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid=123", "VS", columns=["ON"])
    assert len(rows) == 1
    assert rows[0]["row_id"] == "WhatsApp!ON"
    assert rows[0]["source_ref"] == f"google:{spreadsheet_id}:WhatsApp"
    assert rows[0]["whatsapp_image_url"].endswith("b" * 30)
    assert session.calls[0][1]["params"]["ranges"] == "'WhatsApp'"
    assert session.calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize("url", [
    "http://docs.google.com/spreadsheets/d/" + "a" * 30,
    "https://docs.google.com.evil.test/spreadsheets/d/" + "a" * 30,
    "https://user@docs.google.com/spreadsheets/d/" + "a" * 30,
    "https://docs.google.com/spreadsheets/d/short",
])
def test_google_sheet_rejects_non_google_sources_before_network(url):
    from apparel_whatsapp_google import read_google_brief
    with pytest.raises(ValueError):
        read_google_brief(url, "VS")


def test_google_credentials_never_fall_back_to_other_accounts(monkeypatch):
    import apparel_whatsapp_google as google
    monkeypatch.delenv("APPAREL_GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("APPAREL_GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/some/other/account.json")
    assert google.service_account_email() == ""
    with pytest.raises(ValueError, match="APPAREL_GOOGLE_SERVICE_ACCOUNT"):
        google.get_google_credentials([google.SHEETS_SCOPE])
    with pytest.raises(ValueError, match="read-only"):
        google.get_google_credentials(["https://www.googleapis.com/auth/drive"])


def test_google_denied_access_explains_sharing_or_upload(monkeypatch):
    import apparel_whatsapp_google as google
    monkeypatch.setattr(google, "service_account_email", lambda: "apparel@example.iam.gserviceaccount.com")
    session = GoogleSession([GoogleResponse({}, status=403)])
    monkeypatch.setattr(google, "_session", lambda scopes: session)
    with pytest.raises(ValueError, match="Share.*apparel@example.*Viewer.*upload"):
        google.list_google_images("https://drive.google.com/file/d/" + "b" * 30 + "/view")


def test_google_drive_lists_folder_and_downloads_selected_image(monkeypatch):
    import apparel_whatsapp_google as google
    folder_id, image_id = "f" * 30, "i" * 30
    image = {"id": image_id, "name": "Campaign.png", "mimeType": "image/png", "size": "12"}
    listing = GoogleSession([
        GoogleResponse({"id": folder_id, "mimeType": google.FOLDER_TYPE}),
        GoogleResponse({"files": [image]}),
    ])
    download = GoogleSession([
        GoogleResponse(image), GoogleResponse(content=b"\x89PNG\r\n\x1a\nbody", mime="image/png"),
    ])
    sessions = iter([listing, download])
    monkeypatch.setattr(google, "_session", lambda scopes: next(sessions))
    assert google.list_google_images(f"https://drive.google.com/drive/folders/{folder_id}") == [
        {"id": image_id, "name": "Campaign.png", "mime_type": "image/png"},
    ]
    assert google.download_google_image(image_id) == (b"\x89PNG\r\n\x1a\nbody", "Campaign.png", "image/png")
    assert all(call[1]["allow_redirects"] is False for call in listing.calls + download.calls)


def test_google_download_bounds_and_mime_are_enforced(monkeypatch):
    import apparel_whatsapp_google as google
    image_id = "i" * 30
    image = {"id": image_id, "name": "Bad.png", "mimeType": "image/png", "size": "12"}
    monkeypatch.setattr(google, "_session", lambda scopes: GoogleSession([
        GoogleResponse(image), GoogleResponse(content=b"<html>not an image</html>", mime="text/html"),
    ]))
    with pytest.raises(ValueError, match="not the selected"):
        google.download_google_image(image_id)
    monkeypatch.setattr(google, "MAX_IMAGE_BYTES", 3)
    with pytest.raises(ValueError, match="10 MiB"):
        google.download_google_image(image_id)


@pytest.mark.parametrize("brand", ["Crocs", "AGIPL", "R&B", "CK"])
def test_no_goals_brands_allow_absent_tracking_without_inventing_a_window(brand):
    values = brief((2,))
    values[6][2] = ""
    row = read_sheet_values(values, brand, "input")[0]
    assert "_row_warnings" not in row
    assert row["tracking_goal"] == ""
    assert "tracking_value" not in row
    assert row["scheduled_at"] == "2026-10-29T18:30:00+05:30"


@pytest.mark.parametrize("instruction", [
    "The variable should be the name of customer. In the case where the name can't be found then use the copy - 'Gorgeous'",
    "The variable should be the name of customer.\nIn the case where the name can’t be found\nthen use the copy – ‘Gorgeous’",
    'The variable should be the name of customer. If the name cannot be found then use the copy: “Gorgeous”',
])
def test_explicit_missing_name_copy_is_extracted_without_rewriting_instructions(instruction):
    values = brief((2,))
    values[14][2] = instruction
    row = read_sheet_values(values, "VS", "input")[0]
    assert row["whatsapp_name_fallback"] == "Gorgeous"
    assert row["whatsapp_variable_instructions"] == instruction
    assert row["tracking_goal"] == "29th October-1st November2026"
    assert row["template_type"] == "Simple"


def test_sparse_oversized_worksheet_fails_before_materializing_blank_rows():
    import openpyxl
    workbook = openpyxl.Workbook()
    workbook.active.title = "WhatsApp"
    workbook.active.cell(1048576, 3).value = "not a brief"
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    with pytest.raises(ValueError, match="dimensions"):
        read_brief("sparse.xlsx", stream.getvalue(), "VS")


def test_malformed_xlsx_is_an_input_error():
    with pytest.raises(ValueError):
        read_brief("broken.xlsx", b"not an Excel archive", "VS")
