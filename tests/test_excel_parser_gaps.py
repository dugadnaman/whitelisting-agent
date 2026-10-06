"""
Unit tests for Excel spreadsheet parser enhancements in briefing_parser.py.
Verifies:
1. Channel sheet name matching handles variations ("WhatsApp Content", "RCS Copies", "SMS_1").
2. Grid parser handles single empty rows as paragraph separators without prematurely splitting templates.
3. Grid parser correctly splits on true section dividers (channel headers, multiple empty rows).
"""

import openpyxl

from briefing_parser import (
    _match_sheet_channel,
    _parse_excel_channel_sheets,
    _parse_excel_grid_messages,
)


def test_match_sheet_channel_variations():
    """Verify sheet channel matcher recognizes common client naming variations."""
    assert _match_sheet_channel("WhatsApp Content") == "WA"
    assert _match_sheet_channel("WhatsApp Copies") == "WA"
    assert _match_sheet_channel("WA_1") == "WA"
    assert _match_sheet_channel("WA Content") == "WA"
    assert _match_sheet_channel("WHATSAPP") == "WA"
    assert _match_sheet_channel("WA") == "WA"

    assert _match_sheet_channel("RCS Copies") == "RCS"
    assert _match_sheet_channel("RCS Content") == "RCS"
    assert _match_sheet_channel("RCS_1") == "RCS"
    assert _match_sheet_channel("RCS") == "RCS"

    assert _match_sheet_channel("SMS_1") == "SMS"
    assert _match_sheet_channel("SMS Copies") == "SMS"
    assert _match_sheet_channel("SMS Content") == "SMS"
    assert _match_sheet_channel("SMS") == "SMS"

    # Non-channel sheets should return None
    assert _match_sheet_channel("Summary") is None
    assert _match_sheet_channel("Email Mailer") is None
    assert _match_sheet_channel("Warning Notes") is None
    assert _match_sheet_channel("Sheet1") is None


def test_parse_excel_channel_sheets_with_varied_names():
    """Verify _parse_excel_channel_sheets extracts templates from varied sheet names."""
    wb = openpyxl.Workbook()
    ws_wa = wb.active
    ws_wa.title = "WhatsApp Content"

    ws_wa.append(["template_name", "body", "header_text", "button_text", "button_url"])
    ws_wa.append(
        [
            "diwali_offer_wa",
            "Dear Customer, enjoy special Diwali loan offers with low interest rates from Tata Capital.",
            "Festive Offer",
            "Apply Now",
            "https://www.tatacapital.com/diwali",
        ]
    )

    ws_rcs = wb.create_sheet(title="RCS Copies")
    ws_rcs.append(["Copy Header", "Message Body"])
    ws_rcs.append(
        [
            "RCS Body",
            "Title: Dream Car Loans\nBody: Get instant car loan approval at 8.75% p.a.\nCTA: Check Eligibility",
        ]
    )

    ws_sms = wb.create_sheet(title="SMS_1")
    ws_sms.append(["SMS Text", "Dear Customer, your EMI of Rs. 15,000 is due on 5th Oct. Pay now: https://tcl.in"])

    items = _parse_excel_channel_sheets(wb)
    channels = {item["channel"] for item in items}
    assert "WA" in channels
    assert "RCS" in channels
    assert "SMS" in channels

    wa_item = next(i for i in items if i["channel"] == "WA")
    assert "special Diwali loan offers" in wa_item["text"]
    assert wa_item.get("header") == "Festive Offer"
    assert wa_item.get("button_text") == "Apply Now"

    rcs_item = next(i for i in items if i["channel"] == "RCS")
    assert "instant car loan approval" in rcs_item["text"]
    assert rcs_item.get("title") == "Dream Car Loans"


def test_parse_excel_grid_messages_does_not_split_on_blank_row():
    """Verify _parse_excel_grid_messages preserves multi-paragraph copy with blank rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "LAP Content"

    # Multi-row grid layout where Row 0 has channel, Row 1 has paragraph 1,
    # Row 2 is an empty spacing row, Row 3 has paragraph 2, Row 4 has CTA
    ws.append(["Channel", "Variant 1"])
    ws.append(["SMS", "Dear Customer, get pre-approved Home Loan up to Rs. 75 Lakhs."])
    ws.append(["", ""])  # Single empty row inside body for paragraph spacing
    ws.append(["", "Special festival interest rate of 8.5% p.a. valid till 31st Oct."])
    ws.append(["", "Apply online: https://www.tatacapital.com/homeloan"])
    ws.append(["", ""])
    ws.append(["", ""])  # Two consecutive empty rows -> signals section end

    # Second channel section
    ws.append(["RCS", "Upgrade to a luxurious apartment with Tata Capital Home Loans."])
    ws.append(["", "Fast approvals with minimal documentation."])

    items = _parse_excel_grid_messages(wb)
    assert len(items) == 2, f"Expected exactly 2 templates (1 SMS, 1 RCS), got {len(items)}"

    sms_item = next(i for i in items if i["channel"] == "SMS")
    assert "Dear Customer, get pre-approved" in sms_item["text"]
    assert "Special festival interest rate" in sms_item["text"]
    assert "Apply online:" in sms_item["text"]

    rcs_item = next(i for i in items if i["channel"] == "RCS")
    assert "Upgrade to a luxurious apartment" in rcs_item["text"]
    assert "Fast approvals" in rcs_item["text"]
def test_extract_templates_from_excel_column0_channel_layout(tmp_path):
    """Verify sheets like 'Content' in SMPL campaign.xlsx where Column 0 has channel tags and Column 1 has text."""
    from briefing_parser import extract_templates_from_excel_file

    wb = openpyxl.Workbook()
    # 1. Planner sheet to be ignored
    ws_plan = wb.active
    ws_plan.title = "Planner"
    ws_plan.append(["Campaign Name", "2026-10-05"])
    ws_plan.append(["Channel", "SMS"])

    # 2. Content sheet with Column 0 channel tags and Column 1 copies
    ws_content = wb.create_sheet(title="Content")
    ws_content.append(["SMS", "Dear Customer, festival personal loan offer of up to Rs. 7.5 Lakhs. Click https://tcl.in T&Cs apply."])
    ws_content.append(["", "Dear Customer, simplify your finances with Tata Capital pre-approved personal loan. Click https://tcl.in T&C apply."])
    ws_content.append(["", "Unexpected expenses? No problem! Avail pre-qualified loan today. Click https://tcl.in T&Cs apply."])
    ws_content.append(["SMS Retargeting", "Hi Customer, your personal loan offer is still waiting. Apply now before it expires: https://tcl.in T&Cs apply."])
    ws_content.append(["RCS", "Hey Customer, celebrate your festive season with Tata Capital personal loan up to Rs. 7.5 Lakhs. Apply: https://tcl.in"])

    # 3. Carousel sheet with multiple cards
    ws_rcs = wb.create_sheet(title="RCS Carousal ")
    # Put 3 cards in row 10 in different columns
    row_data = [None] * 15
    row_data[1] = "Dear Customer, make every dream closer. Upgrade your lifestyle and enjoy a pre-qualified personal loan offer up to Rs. 5 Lakhs. Tap to proceed: https://tcl.in"
    row_data[6] = "From dreams to emergencies, get funds instantly with a Tata Capital pre-qualified personal loan. Tap below to check eligibility: https://tcl.in"
    row_data[11] = "Your dreams deserve flexibility, so do your repayments. Unlock your Tata Capital pre-qualified personal loan offer today. Tap to claim: https://tcl.in"
    for _ in range(9):
        ws_rcs.append([None] * 15)
    ws_rcs.append(row_data)

    file_path = tmp_path / "SMPL_test.xlsx"
    wb.save(file_path)

    extracted = extract_templates_from_excel_file(file_path)
    channels = [item["channel"] for item in extracted]

    # Exactly 4 SMS, 4 RCS, and 0 WhatsApp templates
    assert channels.count("SMS") == 4
    assert channels.count("RCS") == 4
    assert channels.count("WA") == 0

    sms_items = [item for item in extracted if item["channel"] == "SMS"]
    assert len(sms_items) == 4
    assert "festival personal loan offer" in sms_items[0]["text"]
    assert "simplify your finances" in sms_items[1]["text"]
    assert "Unexpected expenses" in sms_items[2]["text"]
    assert "personal loan offer is still waiting" in sms_items[3]["text"]

    rcs_items = [item for item in extracted if item["channel"] == "RCS"]
    assert len(rcs_items) == 4
    assert any("celebrate your festive season" in item["text"] for item in rcs_items)


def test_real_smpl_campaign_file_if_available():
    """Verify real /Users/naman/Downloads/SMPL campaign.xlsx extracts 4 SMS, 5 RCS, and 0 WA."""
    from pathlib import Path
    from briefing_parser import extract_templates_from_excel_file

    real_path = Path("/Users/naman/Downloads/SMPL campaign.xlsx")
    if not real_path.is_file():
        return

    extracted = extract_templates_from_excel_file(real_path)
    channels = [item["channel"] for item in extracted]

    assert channels.count("WA") == 0, f"Expected 0 WA templates, got {channels.count('WA')}"
    assert channels.count("SMS") == 4, f"Expected 4 SMS templates, got {channels.count('SMS')}"
    assert channels.count("RCS") == 5, f"Expected 5 RCS templates, got {channels.count('RCS')}"
