"""
Unit tests for PowerPoint (.pptx) Brief Extraction in Karix Briefing Engine.
Tests multi-channel extraction (WhatsApp, RCS, SMS, Email, PN) from presentation slides.
"""

from pathlib import Path

import pytest

from briefing_parser import extract_templates_from_pptx_file, parse_jira_brief


def test_pptx_extraction_pre_expiry_topup():
    """Verify templates extracted from Pre-Expiry Top Up presentation."""
    p1 = Path("media_cache/jira_38655_TCL___MVP5___Pre-Expiry_Top_Up.pptx")
    if not p1.exists():
        pytest.skip("Pre-Expiry Top Up PPTX not cached locally")

    items = extract_templates_from_pptx_file(p1)
    assert len(items) >= 15
    channels = {it["channel"] for it in items}
    assert "SMS" in channels
    assert "WA" in channels
    assert "RCS" in channels
    assert "EMAIL" in channels

    wa_items = [it for it in items if it["channel"] == "WA"]
    assert len(wa_items) == 4
    for wa in wa_items:
        assert "Personal Loan Top-Up" in wa["text"]
        assert wa["button_text"] in ("Click Now", "Check Here")

    sms_items = [it for it in items if it["channel"] == "SMS"]
    assert len(sms_items) == 5

    rcs_items = [it for it in items if it["channel"] == "RCS"]
    assert len(rcs_items) == 4
    assert any(rcs["header"] == "Bring More of Your Plans to Life" for rcs in rcs_items)


def test_pptx_extraction_revised_offer():
    """Verify templates extracted from Revised Offer presentation."""
    p2 = Path("media_cache/jira_38656_TCL___MVP5___Revised_Offer.pptx")
    if not p2.exists():
        pytest.skip("Revised Offer PPTX not cached locally")

    items = extract_templates_from_pptx_file(p2)
    assert len(items) >= 20
    channels = {it["channel"] for it in items}
    assert "SMS" in channels
    assert "WA" in channels
    assert "RCS" in channels
    assert "PN" in channels
    assert "EMAIL" in channels

    wa_items = [it for it in items if it["channel"] == "WA"]
    assert len(wa_items) == 5
    assert any("Good news!" in wa["text"] for wa in wa_items)
    assert any("We’ve upgraded" in wa["text"] for wa in wa_items)


def test_parse_jira_brief_with_pptx():
    """Test parse_jira_brief end-to-end with mock PPTX issue."""
    p1 = Path("media_cache/jira_38655_TCL___MVP5___Pre-Expiry_Top_Up.pptx")
    if not p1.exists():
        pytest.skip("Pre-Expiry Top Up PPTX not cached locally")

    mock_issue = {
        "key": "TCN-583",
        "summary": "TCL _ MVP5 _ Revised Offer & Pre-Expiry Top Up _ Creatives _ PL",
        "status": "To Do",
        "assignee": "Mrunalini Gawande",
        "reporter": "Apurva Mohite",
        "duedate": "2026-11-15",
        "description_text": "Please whitelist SMS, Whatsapp & RCS content from given folders.",
        "description_raw": None,
        "attachments": [
            {
                "id": "38655",
                "filename": "TCL _ MVP5 _ Pre-Expiry Top Up.pptx",
                "local_path": str(p1),
            }
        ],
        "comments": [],
    }

    parsed = parse_jira_brief(mock_issue, download_creatives=False)
    assert parsed.channel_counts["whatsapp"] == 4
    assert parsed.channel_counts["sms"] == 5
    assert parsed.channel_counts["rcs"] == 4
    assert parsed.channel_counts["email"] == 4
    assert len(parsed.whatsapp_templates) == 4
    assert len(parsed.rcs_templates) == 4
    assert len(parsed.sms_templates) == 5
    assert len(parsed.email_templates) == 4
