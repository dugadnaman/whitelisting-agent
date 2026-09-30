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

    # 4. T&Cs apply MUST stay in body without underscores and footer MUST be None
    assert "T&Cs apply" in clean_body
    assert "_T&Cs" not in clean_body
    assert "apply_" not in clean_body
    assert footer is None

    # 5. Also verify TCN-543 pattern ('_T&Cs apply <LINK>_' / '_T&Cs apply <link>_' / '_T&Cs apply {{1}}_')
    # strips underscores before and after while keeping {{1}} at the end ('T&Cs apply {{1}}').
    from briefing_parser import normalize_placeholders

    tcn_543_raw = (
        "👀 *What if your next Used Car loan deal didn't have to wait?* 🚗\n\n"
        "There's a *faster* way to move eligible cases with *Tata Capital. 🤝*\n\n"
        "⚡ *Same-day login. Same-day disbursal.* 💵\n\n"
        "Contact your Tata Capital representative for more details. 📞\n\n"
        "_T&Cs apply <link>_"
    )
    norm_543, samples_543 = normalize_placeholders(tcn_543_raw)
    body_543, _, _, foot_543 = extract_and_strip_cta(norm_543)
    assert body_543.endswith("T&Cs apply {{1}}")
    assert "_T&Cs" not in body_543
    assert "{{1}}_" not in body_543
    assert len(samples_543) == 1
    assert foot_543 is None

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


def test_cta_variable_extraction_and_stripping():
    """Verify CTA line with variable (e.g. 'CTA {{4}}') is extracted and stripped from body."""
    body = (
        "⚡ Funds in 24 Hours!\n"
        "Hi {{1}}, your Tata Capital {{2}} offer up to ₹{{3}} is ready.\n"
        "Need quick funds for medical needs, travel, bills, or urgent expenses?\n"
        "💰 Amount credited within 24 hours*\n"
        "✅ Minimal paperwork\n"
        "⚡ Instant approval\n\n"
        "CTA {{4}}"
    )
    clean_body, btn_text, btn_url, footer = extract_and_strip_cta(body)
    assert "CTA {{4}}" not in clean_body
    assert btn_text == "Apply Now"
    assert btn_url == "https://u3.mnge.co/{{4}}"


def test_cta_label_with_arrow_syntax():
    """Verify 'CTA: Apply Online -> https://tatacapital.com/pl' extracts label and URL."""
    body = (
        "Consolidate your outstanding loans into a single flexible EMI.\n"
        "CTA: Apply Online -> https://tatacapital.com/pl\n"
        "T&C apply."
    )
    clean_body, btn_text, btn_url, footer = extract_and_strip_cta(body)
    assert "CTA: Apply Online" not in clean_body
    assert "https://tatacapital.com/pl" not in clean_body
    assert btn_text == "Apply Online"
    assert btn_url == "https://tatacapital.com/pl"
    assert "T&C apply." in clean_body
    assert footer is None


def test_cta_label_without_url():
    """Verify 'CTA: Apply Now' without URL extracts label and uses default URL."""
    body = (
        "Special pre-approved loan of up to ₹5 Lakhs is waiting for you.\n"
        "CTA: Apply Now\n"
        "T&C apply."
    )
    clean_body, btn_text, btn_url, footer = extract_and_strip_cta(body)
    assert "CTA: Apply Now" not in clean_body
    assert btn_text == "Apply Now"
    assert btn_url == "https://u3.mnge.co/"


def test_tap_to_proceed_cta_extraction_and_stripping():
    """Verify 'Tap to proceed ⬇' is stripped from body and populates button."""
    body = (
        "Dear {{1}}, ✨\n\n"
        "Big plans on your mind? From home upgrades to education or lifestyle goals—don't let finances slow you down.\n"
        "✔ Enjoy {{2}} offer up to ₹{{3}} and bring your plans to life today.\n\n"
        "Tap to proceed ⬇"
    )
    clean_body, btn_text, btn_url, footer = extract_and_strip_cta(body)
    assert "Tap to proceed" not in clean_body
    assert "⬇" not in clean_body
    assert btn_text == "Proceed"
    assert btn_url == "https://u3.mnge.co/"


def test_card_title_and_body_deduplication(tmp_path):
    """Verify parse_jira_brief does not repeat the title as the first line of the body."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "RCS Copies"
    ws.append(["Channel", "Content"])
    ws.append([
        "RCS",
        "⚡ Funds in 24 Hours!\n\n"
        "Hi {{1}}, your Tata Capital {{2}} offer up to ₹{{3}} is ready.\n\n"
        "Need quick funds for medical needs, travel, bills, or urgent expenses?\n"
        "💰 Amount credited within 24 hours*\n"
        "✅ Minimal paperwork\n"
        "⚡ Instant approval\n\n"
        "CTA {{4}}",
    ])

    file_path = tmp_path / "campaign_templates.xlsx"
    wb.save(file_path)

    mock_issue = {
        "key": "TCN-534",
        "summary": "PAPL Oct Campaign | Seg 1-5",
        "status": "In Progress",
        "assignee": "Neel Shah",
        "reporter": "Apurva Mohite",
        "description_raw": None,
        "description_text": "See attached spreadsheet",
        "attachments": [
            {
                "id": "1001",
                "filename": "campaign_templates.xlsx",
                "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "local_path": str(file_path),
            }
        ],
    }
    brief = parse_jira_brief(mock_issue, download_creatives=False)
    assert len(brief.rcs_templates) >= 1
    rcs = brief.rcs_templates[0]
    assert rcs["card_title"] == "⚡ Funds in 24 Hours!"
    # Title must NOT be repeated in the body!
    assert not rcs["body"].startswith("⚡ Funds in 24 Hours!")
    assert rcs["body"].startswith("Hi {{1}}")
    # CTA {{4}} must be extracted into button and NOT in body
    assert "CTA {{4}}" not in rcs["body"]
    assert rcs["action_label"] == "Apply Now"
    assert rcs["action_url"] == "https://u3.mnge.co/{{4}}"
