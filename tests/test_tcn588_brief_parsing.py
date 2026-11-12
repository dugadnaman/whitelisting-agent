"""
Regression tests for TCN-588 brief extraction and reference inventory dump filtering.
Verifies that:
1. Massive DLT database export dumps (e.g. sms_vilpower_wholecontent.csv with 15k rows)
   are identified as inventory dumps and NOT parsed as campaign brief templates.
2. In multi-month cumulative workbooks (like PL Bulls Eye nov.xlsx), only target month
   sheets (Nov content, Regional content Nov) are extracted, skipping historical months.
3. Multi-channel regional grids with language row headers extract appropriate language
   tags and clean channel variants.
"""

from pathlib import Path

import pytest

from briefing_parser import (
    extract_templates_from_excel_file,
    is_inventory_dump_attachment,
    parse_jira_brief,
)


def test_inventory_dump_identification():
    """Verify inventory database exports are identified and rejected from brief extraction."""
    assert is_inventory_dump_attachment("sms_vilpower_wholecontent.csv") is True
    assert is_inventory_dump_attachment("tata_dlt_whole_content.csv") is True
    assert is_inventory_dump_attachment("all_templates_catalog_export.xlsx") is True
    assert is_inventory_dump_attachment("PL Bulls Eye nov.xlsx") is False
    assert is_inventory_dump_attachment("WhatsApp_Campaign_Brief.xlsx") is False


def test_tcn588_excel_extraction_only_extracts_november():
    """Verify PL Bulls Eye nov.xlsx extracts only November content, skipping Jan-Oct."""
    excel_path = Path("/Users/naman/Downloads/PL Bulls Eye nov.xlsx")
    if not excel_path.is_file():
        pytest.skip("Test file /Users/naman/Downloads/PL Bulls Eye nov.xlsx not found locally")

    items = extract_templates_from_excel_file(excel_path)
    # Should extract ~47 templates (SMS, WA, PN), definitely not 293+ past-month templates
    assert 40 <= len(items) <= 60, f"Expected 40-60 November templates, got {len(items)}"

    channels = {item["channel"] for item in items}
    assert "WA" in channels
    assert "SMS" in channels

    # Verify languages from Regional content Nov are extracted
    languages = {item.get("language") for item in items if item.get("language")}
    assert {"mr", "kn", "hi", "ta", "te", "bn", "gu"}.issubset(languages)

    # Verify no Oct'26 or Sep'26 campaign tags leaked into November
    for item in items:
        raw_text = item.get("raw_text") or item.get("text", "")
        assert "TCLMOE_PL_Bulls_Eye_Ext_SMS_Oct'26" not in raw_text
        assert "TCLMOE_PL_Bulls_Eye_SMS_Int_Sep'26" not in raw_text


def test_tcn588_brief_ignores_wholecontent_csv():
    """Verify parse_jira_brief ignores 15,000-row wholecontent CSV and parses exactly ~40 templates."""
    excel_path = Path("/Users/naman/Downloads/PL Bulls Eye nov.xlsx")
    csv_path = Path("media_cache/jira_38790_sms_vilpower_wholecontent.csv")
    if not excel_path.is_file() or not csv_path.is_file():
        pytest.skip("TCN-588 cached media attachments not found locally")

    mock_issue = {
        "key": "TCN-588",
        "summary": "PQPL Bulls Eye Nov",
        "description_text": (
            "Kindly take below campaign live. Attached is the new content for both internal & external base. "
            "Pls help release rounds basis the planner for internal base too.\n\n"
            "Also, pls whitelist regional content- sheet reference- Regional content Nov\n\n"
            "Campaign Name | TCLMOE_PL_Bulls_Eye_SMS_Int_Nov'26\n"
        ),
        "attachments": [
            {
                "id": "38717",
                "filename": "PL Bulls Eye nov.xlsx",
                "local_path": str(excel_path),
            },
            {
                "id": "38790",
                "filename": "sms_vilpower_wholecontent.csv",
                "local_path": str(csv_path),
            },
        ],
    }

    parsed = parse_jira_brief(mock_issue, download_creatives=False)

    total_templates = len(parsed.whatsapp_templates) + len(parsed.rcs_templates) + len(parsed.sms_templates)
    assert total_templates < 100, f"Expected <100 templates for TCN-588, got {total_templates}"
    assert len(parsed.sms_templates) < 50, f"Expected <50 SMS templates, got {len(parsed.sms_templates)}"
    assert len(parsed.whatsapp_templates) == 19
    assert len(parsed.sms_templates) == 21
