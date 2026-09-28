"""
Unit tests for universal attached spreadsheet parser and Jira comments revision parsing.
Verifies:
1. All client spreadsheet formats (Channel columns, section headers, multilingual tables) are extracted.
2. Multi-sheet workbooks extract templates across all sheets without premature termination.
3. Comments and copy changes posted in Jira comments are parsed into drafts and stored in ParsedJiraBrief.
"""

from pathlib import Path

import openpyxl

from briefing_parser import (
    extract_templates_from_excel_file,
    parse_jira_brief,
)


def test_excel_channel_column_and_section_header_extraction(tmp_path: Path):
    """Verify spreadsheet parser extracts from channel column and section header rows."""
    wb = openpyxl.Workbook()

    # Sheet 1: 2-column channel table like World Tourism Day (TCN-535)
    ws1 = wb.active
    ws1.title = "Campaign Copies"
    ws1.append(["Channel", "Content"])
    ws1.append(
        [
            "WhatsApp",
            "Dear {#Alphanumeric#}, travel the world with Tata Capital Personal Loan up to ₹35 Lakhs. T&Cs apply.",
        ]
    )
    ws1.append(
        [
            "RCS",
            "Title:\nTravel Offers\nBody:\nGet instant vacation loan approvals.\nCTA Button:\nApply Now",
        ]
    )

    # Sheet 2: Section header table like October Whitelisting (TCN-533)
    ws2 = wb.create_sheet(title="Section Format")
    ws2.append(["Content", "SMS Promotional"])
    ws2.append(["C1", "Hi {CustomerName}, pre-approved Two-Wheeler loan up to ₹3 Lacs is ready. Apply: <link>"])
    ws2.append(["Content", "WhatsApp"])
    ws2.append(["C1", "Hey {#alphanumeric#}, festive two-wheeler offers waiting for you! Apply: <link>"])

    file_path = tmp_path / "test_campaign.xlsx"
    wb.save(file_path)

    items = extract_templates_from_excel_file(file_path)
    assert len(items) >= 4, f"Expected at least 4 items, got {len(items)}"

    channels = {item["channel"] for item in items}
    assert "WA" in channels
    assert "RCS" in channels
    assert "SMS" in channels

    # Verify WhatsApp from Sheet 1
    wa_item = next(i for i in items if i["channel"] == "WA" and "travel the world" in i["text"])
    assert wa_item is not None

    # Verify RCS from Sheet 1
    rcs_item = next(i for i in items if i["channel"] == "RCS" and i.get("title") == "Travel Offers")
    assert rcs_item is not None

    # Verify SMS from Sheet 2
    sms_item = next(i for i in items if i["channel"] == "SMS" and "pre-approved Two-Wheeler" in i["text"])
    assert sms_item is not None


def test_comments_and_revision_parsing():
    """Verify parse_jira_brief stores comments and extracts revised copy from comments."""
    mock_issue = {
        "key": "TCN-540",
        "summary": "WhatsApp Festival Campaign",
        "status": "In Progress",
        "assignee": "Neel Shah",
        "reporter": "Apurva Mohite",
        "description_raw": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Initial brief: Dear Customer, Diwali offer is live. Apply: <link>",
                        }
                    ],
                }
            ],
        },
        "description_text": "Initial brief: Dear Customer, Diwali offer is live. Apply: <link>",
        "attachments": [],
        "comments": [
            {
                "id": "90001",
                "author": "Neel Shah",
                "created": "2026-09-23T10:00:00.000Z",
                "body_text": "Please check base count before deployment.",
            },
            {
                "id": "90002",
                "author": "Apurva Mohite",
                "created": "2026-09-23T11:30:00.000Z",
                "body_text": (
                    "Updated WA: Dear {#alphanumeric#}, special Diwali loan offer of ₹5 Lakhs "
                    "with zero processing fee is available. Apply now: https://u3.mnge.co/d\n\nT&Cs apply."
                ),
            },
        ],
    }

    brief = parse_jira_brief(mock_issue, download_creatives=False)

    # 1. Verify comments are retained
    assert len(brief.comments) == 2
    assert brief.comments[0]["author"] == "Neel Shah"
    assert brief.comments[1]["author"] == "Apurva Mohite"

    # 2. Verify revised copy from comment was parsed into WhatsApp templates
    assert len(brief.comment_updates) >= 1
    assert any("Diwali loan offer" in w["body"] for w in brief.whatsapp_templates)


def test_targeting_sheet_does_not_hallucinate_whatsapp_and_rcs_templates(tmp_path: Path):
    """Verify campaign targeting/cohort sheets do not hallucinate audience segment names into templates.

    Specifically reproduces TCN-534 where segment names were misread as 200+ WhatsApp/RCS templates:
    - 'WA Utility Regional DND + Non Clickers ( exclude World tourism day users)'
    - 'Email (Remove previous rounds Openers + Past 60 Days Open + Capping 60k) + WA Utility Regional ( DND & Non clickers)'
    - 'PN English App Users - Non Clickers of Durga Pooja/ Dussehra'
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Targeting Matrix"

    # Header row describing campaign planner segments
    ws.append(["Date", "Channel", "Segment Name", "Targeting Criteria", "Base Count"])

    # Targeting rows (cohorts, exclusions, caps, under 25 words)
    ws.append(["2026-09-28", "WA", "Seg_1", "WA Utility Regional DND + Non Clickers ( exclude World tourism day users)", "45000"])
    ws.append(["2026-09-28", "WA", "Seg_2", "Email (Remove previous rounds Openers + Past 60 Days Open + Capping 60k) + WA Utility Regional ( DND & Non clickers)", "60000"])
    ws.append(["2026-09-28", "PN", "Seg_3", "PN English App Users - Non Clickers of Durga Pooja/ Dussehra", "120000"])
    ws.append(["2026-09-28", "RCS", "Seg_4", "Regional DND Non Clickers of Gandhi Jayanti exclusion list", "35000"])

    # Sheet 2: The actual real campaign copy (30+ words)
    ws2 = wb.create_sheet(title="Campaign Copies")
    ws2.append(["Channel", "Content"])
    real_wa_copy = (
        "Dear {#CustomerName#}, Celebrate this festive season with Tata Capital Personal Loan of up to ₹5 Lakhs "
        "at attractive interest rates starting from 10.99% p.a. Flexible repayment tenure up to 60 months with zero foreclosure charges. "
        "Apply online in 2 minutes: https://u3.mnge.co/festive. T&C Apply. - Tata Capital Limited"
    )
    ws2.append(["WhatsApp", real_wa_copy])

    file_path = tmp_path / "tcn_534_planner.xlsx"
    wb.save(file_path)

    items = extract_templates_from_excel_file(file_path)

    # NONE of the 4 targeting cohort rows should be extracted as templates
    for item in items:
        assert "Non Clickers" not in item["text"]
        assert "Openers" not in item["text"]
        assert "App Users" not in item["text"]
        assert "DND" not in item["text"]

    # Only the genuine campaign copy should be extracted
    assert len(items) == 1
    assert items[0]["channel"] == "WA"
    assert "Tata Capital Personal Loan" in items[0]["text"]
