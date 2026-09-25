"""
Unit tests for CTA extraction, removal from body, and default URL fallback (https://u3.mnge.co/).
Verifies:
1. CTA line is extracted to button (text and URL) and completely removed from the template body.
2. T&C line is extracted to footer and removed from body.
3. If no URL is provided or generic homepage is used, URL defaults to https://u3.mnge.co/.
4. Specific custom/campaign URLs are preserved in the button.
5. End-to-end integration with parse_jira_brief.
"""

from briefing_parser import DEFAULT_CTA_URL, extract_and_strip_cta, parse_jira_brief


def test_cta_line_removed_from_body_and_moved_to_button():
    """Verify exact body from TCN-524 screenshot removes CTA line and sets button URL to https://u3.mnge.co/."""
    body = (
        "*Up to {{1}} Pre-Qualified* *offer could be available to you.*\n\n"
        "Thinking about getting more from your existing *Loan Against Property*?\n\n"
        "Switch to *Tata Capital* and explore *Higher Loan Eligibility & a* Hassle-free process*!\n\n"
        "👉 *Check Your Offer:* https://www.tatacapital.com\n\n"
        "_T&Cs apply https://www.tatacapital.com_"
    )

    clean_body, btn_text, btn_url, footer = extract_and_strip_cta(body)

    # 1. Body must NOT contain the CTA line or the URL
    assert "👉 *Check Your Offer:*" not in clean_body
    assert "https://www.tatacapital.com" not in clean_body

    # 2. Body must retain the actual marketing copy
    assert "*Up to {{1}} Pre-Qualified*" in clean_body
    assert "Thinking about getting more from your existing *Loan Against Property*?" in clean_body
    assert "Switch to *Tata Capital*" in clean_body

    # 3. Button must receive the extracted CTA text and the default URL
    assert btn_text == "Check Your Offer"
    assert btn_url == "https://u3.mnge.co/"

    # 4. Footer must receive T&C
    assert footer == "T&C apply"


def test_cta_with_custom_campaign_url_preserved():
    """Verify specific campaign tracking URLs are preserved in the button."""
    body = (
        "Special home loan interest rates starting 8.5%.\n"
        "Apply Online: https://u3.mnge.co/track/campaign_123\n"
        "T&Cs apply."
    )
    clean_body, btn_text, btn_url, footer = extract_and_strip_cta(body)
    assert "Apply Online:" not in clean_body
    assert "https://u3.mnge.co/track/campaign_123" not in clean_body
    assert btn_text == "Apply Online"
    assert btn_url == "https://u3.mnge.co/track/campaign_123"


def test_cta_without_url_defaults_to_u3_mnge_co():
    """Verify CTA line without URL defaults to https://u3.mnge.co/."""
    body = "Too many EMIs? Consolidate them today.\nCheck your offer: <link>\nT&Cs apply."
    clean_body, btn_text, btn_url, _ = extract_and_strip_cta(body)
    assert "<link>" not in clean_body
    assert "Check your offer:" not in clean_body
    assert btn_text == "Check Your Offer"
    assert btn_url == "https://u3.mnge.co/"


def test_parse_jira_brief_end_to_end_removes_cta_from_wa_body():
    """Verify parse_jira_brief integrates CTA extraction and places it only in the button."""
    mock_issue = {
        "key": "TCN-524",
        "summary": "WhatsApp LAP GST Content Whitelisting",
        "status": "In Progress",
        "assignee": "Mrunalini Gawande",
        "reporter": "Product Team",
        "description_raw": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "*Up to {{1}} Pre-Qualified* *offer could be available to you.*\n\n"
                                "Thinking about getting more from your existing *Loan Against Property*?\n\n"
                                "👉 *Check Your Offer:* https://www.tatacapital.com\n\n"
                                "_T&Cs apply_"
                            ),
                        }
                    ],
                }
            ],
        },
        "description_text": (
            "*Up to {{1}} Pre-Qualified* *offer could be available to you.*\n\n"
            "Thinking about getting more from your existing *Loan Against Property*?\n\n"
            "👉 *Check Your Offer:* https://www.tatacapital.com\n\n"
            "_T&Cs apply_"
        ),
        "attachments": [],
    }

    brief = parse_jira_brief(mock_issue, download_creatives=False)
    assert len(brief.whatsapp_templates) >= 1
    wa = brief.whatsapp_templates[0]

    # Body must not contain the CTA line
    assert "👉 *Check Your Offer:*" not in wa["body"]
    assert "https://www.tatacapital.com" not in wa["body"]

    # Button must have the CTA and https://u3.mnge.co/
    assert wa["button_type"] == "URL"
    assert wa["button_text"] == "Check Your Offer"
    assert wa["button_url"] == "https://u3.mnge.co/"
