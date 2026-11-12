"""Consumer regressions for native layouts found in the open TCN description audit."""

from briefing_parser import parse_jira_brief
from jira_client import adf_to_text


def paragraph(text):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def table(rows):
    return {"type": "table", "content": [
        {"type": "tableRow", "content": [
            {"type": "tableCell", "content": [paragraph(value)]} for value in row
        ]} for row in rows
    ]}


def parse(nodes, summary="Whitelisting WA utility content"):
    adf = {"type": "doc", "version": 1, "content": nodes}
    return parse_jira_brief({
        "key": "TCN-999", "summary": summary, "description_raw": adf,
        "description_text": adf_to_text(adf), "attachments": [], "comments": [],
    }, download_creatives=False, use_ai=False)


def customer_copy(label):
    return (f"Dear <Name>, {label}. Your Tata Capital Personal Loan application is ready. "
            "Complete the next step to continue your application securely. T&Cs apply.")


def test_variant_copy_table_keeps_each_cta_and_customer_variable():
    """TCN-508: eight A-H rows became one body and one cross-row CTA."""
    labels = ["Continue Application", "Verify & Continue", "Verify Now", "Resume Application",
              "Complete Verification", "Continue Now", "Verify & Continue", "Continue Application"]
    rows = [["Variant", "Copy"]] + [
        [f"Variant {index}", customer_copy(f"Message {index}") + f"\nCTA: {label}"]
        for index, label in enumerate(labels, 1)
    ]
    drafts = parse([table(rows)]).whatsapp_templates
    assert len(drafts) == 8
    assert [draft["button_text"].lower() for draft in drafts] == [label.lower() for label in labels]
    assert all(draft["body"].startswith("Dear {{1}}") for draft in drafts)
    assert all(draft["variables"] == ["1"] for draft in drafts)
    assert all("CTA:" not in draft["body"] for draft in drafts)


def test_unlabelled_promo_and_retargeting_messages_do_not_merge():
    """TCN-584: four promo plus four retargeting SMS messages became one."""
    copies = [customer_copy(f"Festive message {index}") for index in range(1, 9)]
    parsed = parse([
        paragraph("Kindly whitelist the below SMS content."), paragraph("SMS:"), paragraph("Promo:"),
        *[paragraph(copy) for copy in copies[:4]], paragraph("Retargeting:"),
        *[paragraph(copy) for copy in copies[4:]],
    ], "Whitelisting SMS festive content")
    assert len(parsed.sms_templates) == 8
    assert all(f"Festive message {index}" in draft["text"] for index, draft in enumerate(parsed.sms_templates, 1))
    assert all("whitelist" not in draft["text"].lower() for draft in parsed.sms_templates)


def test_headerless_character_count_grid_keeps_seven_sms_messages():
    """TCN-542: the count column and all seven rows leaked into one SMS."""
    copies = [customer_copy(f"Message {index}") for index in range(1, 8)]
    parsed = parse([paragraph("Pls whitelist below on priority basis"),
                    table([[copy, str(100 + index)] for index, copy in enumerate(copies)])],
                   "PAPL SMS - 120 characters")
    assert [draft["text"] for draft in parsed.sms_templates] == copies
    assert all(" | " not in draft["text"] for draft in parsed.sms_templates)


def test_campaign_columns_and_ragged_split_test_rows_preserve_both_channels():
    """TCN-509: SMS Text was a copied label for separate SMS and WA columns."""
    sms = [customer_copy(f"SMS message {index}") for index in (1, 2)]
    wa = [customer_copy(f"App message {index}") for index in (1, 2)]
    parsed = parse([table([
        ["Campaign Name", "TCLMOE_App_SMS_September", "TCLMOE_App_WA_Utility_September", ""],
        ["SMS Text", sms[0], wa[0], "Split Test"],
        [sms[1], wa[1]],
        ["CTA / LINK", "https://www.tatacapital.com/sms", "https://www.tatacapital.com/app", ""],
        ["Database", "App_Downloads_Set1", "App_Downloads_Set2", ""],
    ])], "App Downloads : SMS & WhatsApp Utility")
    assert [draft["text"] for draft in parsed.sms_templates] == sms
    assert len(parsed.whatsapp_templates) == 2
    assert all(draft["body"].startswith("Dear {{1}}") for draft in parsed.whatsapp_templates)
    assert all(draft["button_url"].startswith("https://www.tatacapital.com/app") for draft in parsed.whatsapp_templates)
    assert all("Database" not in draft["body"] for draft in parsed.whatsapp_templates)


def test_revised_wa_copy_outside_sms_table_is_not_discarded():
    """TCN-516: native metadata extraction suppressed a separate revised WA copy."""
    wa = "Greetings <Name>! " + customer_copy("Revised WhatsApp image content")
    sms = [customer_copy(f"SMS message {index}") for index in range(1, 5)]
    parsed = parse([
        paragraph("Image is revised for below WA content. Pls help whitelist"), paragraph(wa),
        table([
            ["Campaign Name", "TCLMOE_LAP_SMS_September", "TCLMOE_LAP_SMS_Retargeting", "", ""],
            ["SMS Text", sms[0], sms[1], "", ""],
            [sms[2], sms[3], "", ""],
            ["CTA / LINK", "Mentioned in database", "Mentioned in database", "", ""],
            ["Database", "Primary_Base", "Clicker_Base", "", ""],
        ]),
    ], "LAP September Campaign")
    assert len(parsed.whatsapp_templates) == 1
    assert parsed.whatsapp_templates[0]["body"].startswith("Greetings {{1}}")
    assert len(parsed.sms_templates) == 4
    assert {draft["text"] for draft in parsed.sms_templates} == set(sms)


def test_report_tables_without_customer_copy_do_not_become_wa_templates():
    """TCN-593 and similar release/count tables contain no customer copy."""
    parsed = parse([paragraph("Kindly help with below release"), table([
        ["Offer: Offer Name", "File Name", "Offer: Created Date", "Valid Until", "Count"],
        ["BL Retention POS Refill", "BL_Retention_04112026", "25-10-2026", "30-11-2026", "3288"],
    ])], "Marketing Campaigns || Nov Base || Business Loan")
    assert not parsed.whatsapp_templates
    assert not parsed.sms_templates


def test_complete_unnumbered_first_copy_survives_restarted_numbering():
    """TCN-567 revision pattern: the pre-marker customer message is not preamble."""
    copies = [customer_copy(f"Utility message {index}") for index in range(1, 4)]
    parsed = parse([paragraph("Please whitelist these utility variants."), paragraph(copies[0]),
                    paragraph("1. " + copies[1]), paragraph("1. " + copies[2])])
    assert len(parsed.whatsapp_templates) == 3
    assert all(f"Utility message {index}" in draft["body"] for index, draft in enumerate(parsed.whatsapp_templates, 1))


def test_contextual_nonclicker_grids_keep_separate_wa_and_sms_sections():
    """TCN-143: identical generic headers inherit their own preceding channel."""
    rows = [["Non clicker", "Retargeting"]] + [
        [f"{index}." + customer_copy(f"Nonclicker {index}"), customer_copy(f"Retargeting {index}")]
        for index in range(1, 6)
    ]
    parsed = parse([
        paragraph("Kindly help whitelist below WA utility content"), table(rows),
        paragraph("Pls whitelist below SMS service"), table(rows),
    ], "WA Utility Content + SMS Implicit Content")
    assert len(parsed.whatsapp_templates) == 10
    assert len(parsed.sms_templates) == 10
    assert all(draft["body"].startswith("Dear {{1}}") for draft in parsed.whatsapp_templates)
    assert all("Non clicker | Retargeting" not in draft["body"] for draft in parsed.whatsapp_templates)


def test_product_columns_keep_each_wa_copy_and_bracket_cta():
    """TCN-299: three BL and three UCL rows cannot become one shared body."""
    parsed = parse([table([
        ["BL", "UCL"],
        *[[customer_copy(f"Business message {index}") + "\n[Interested]",
           customer_copy(f"Car message {index}") + "\n[Interested]"] for index in range(1, 4)],
    ])], "BL UCL WA Content")
    assert len(parsed.whatsapp_templates) == 6
    assert all(draft["button_text"].lower() == "interested" for draft in parsed.whatsapp_templates)
    assert all(draft["variables"] == ["1"] for draft in parsed.whatsapp_templates)
    assert all("[Interested]" not in draft["body"] for draft in parsed.whatsapp_templates)


def test_product_rcs_columns_keep_eight_copies_and_their_own_urls():
    """TCN-116: each product has two restarted-numbered copies and its own link."""
    products = ["BL", "UCL", "PL", "LAP"]
    parsed = parse([
        table([
            ["", *products],
            ["RCS Retargeting", *[
                "1. " + customer_copy(f"{product} first") + "\n1. " + customer_copy(f"{product} second")
                for product in products
            ]],
        ]),
        table([[f"{product}_VM_Blank_RCS", f"https://www.tatacapital.com/{product.lower()}"]
               for product in products]),
    ], "Whitelisting SMS and RCS Campaign")
    assert len(parsed.rcs_templates) == 8
    for product in products:
        drafts = [draft for draft in parsed.rcs_templates if f"{product} first" in draft["raw_source"]
                  or f"{product} second" in draft["raw_source"]]
        assert len(drafts) == 2
        assert all(draft["action_url"].startswith(f"https://www.tatacapital.com/{product.lower()}")
                   for draft in drafts)


def test_row_channels_join_greetings_bodies_and_utility_continuations():
    """TCN-152: physical ADF rows may be fragments, not independent messages."""
    parsed = parse([table([
        ["", "Seg 3-5"],
        ["SMS", "Dear <Name>,"],
        ["Your Tata Capital Personal Loan offer is ready. Check your available funds and apply now. T&Cs apply."],
        [customer_copy("Second SMS")],
        ["RCS", "Hi <Name>,"],
        ["Your Tata Capital Personal Loan offer is ready. Check your available funds and apply now. T&Cs apply."],
        ["WA", customer_copy("Main WhatsApp")],
        ["SMS retargeting", customer_copy("SMS retargeting")],
        ["SMS Service Implicit", customer_copy("SMS service")],
        ["WA utility", customer_copy("WA utility")],
        ["WA utility retargeting", customer_copy("WA utility retargeting")],
    ])], "Whitelisting KTTC content")
    assert len(parsed.sms_templates) == 4
    assert len(parsed.rcs_templates) == 1
    assert len(parsed.whatsapp_templates) == 3
    assert parsed.sms_templates[0]["text"].startswith("Dear <Name>,\nYour Tata Capital")
    assert all("Tata Capital" in draft["body"] for draft in parsed.whatsapp_templates)


def test_freeform_sms_and_wa_headings_scope_five_variants_each():
    """TCN-226: channel sections must not route every copy as the first channel."""
    parsed = parse([
        paragraph("Dear Team,"), paragraph("Kindly help whitelist below"),
        paragraph("SMS Service -"),
        *[paragraph("• " + customer_copy(f"SMS service {index}")) for index in range(1, 6)],
        paragraph("WA utility -"),
        *[paragraph("• " + customer_copy(f"WA utility {index}")) for index in range(1, 6)],
    ], "Service & Utility Content")
    assert len(parsed.sms_templates) == 5
    assert len(parsed.whatsapp_templates) == 5
    assert all("WA utility" not in draft["text"] for draft in parsed.sms_templates)
    assert all("SMS service" not in draft["body"] for draft in parsed.whatsapp_templates)


def test_freeform_sms_section_survives_following_wa_section():
    """TCN-301: two SMS copies and one WA copy share a prose description."""
    parsed = parse([
        paragraph("Hi Team,"), paragraph("SMS"),
        paragraph(customer_copy("Gudi Padwa SMS one")), paragraph(customer_copy("Gudi Padwa SMS two")),
        paragraph("WA-"), paragraph(customer_copy("Gudi Padwa WhatsApp")),
    ], "Whitelisting PL HTL Special Campaign SMS Whatsapp Email")
    assert len(parsed.sms_templates) == 2
    assert len(parsed.whatsapp_templates) == 1
    assert not parsed.rcs_templates


# Authored ADF copied from the audit evidence; only editor IDs/layout attributes removed.

def test_actual_tcn_509_description_preserves_every_source_copy():
    adf = {'type': 'doc',
     'version': 1,
     'content': [{'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Kindly take the below Campaign Live.'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text',
                               'text': 'Pfb, Brief for the same and please do Split Test in both the '
                                       'channels. '}]},
                 {'type': 'paragraph'},
                 {'type': 'table',
                  'content': [{'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Campaign\xa0Name'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'TCLMOE_App_Downloads_SMS_Campaign_September’26'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'TCLMOE_App_Downloads_WA_Utility_Campaign_September’26'}]}]},
                                           {'type': 'tableCell', 'content': [{'type': 'paragraph'}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'SMS Text'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Hi <Customer Name>,'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': 'Manage your loan with ease. Pay '
                                                                              'EMI online & download your '
                                                                              'SOA/Interest Certificate anytime '
                                                                              'on the Tata Capital Loan App. '
                                                                              'Install now: <link>'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Hi {#Name#} ,'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Thank you for choosing Tata '
                                                                              'Capital.'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Manage your loan conveniently '
                                                                              'with the Tata Capital Loan App.'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': '✔ Download Welcome Letter'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': '✔ View Amortization Schedule'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text', 'text': '✔ Pay EMI Online'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': '✔ Download SOA & Interest '
                                                                              'Certificate'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Install now:<link>'}]},
                                                        {'type': 'bulletList',
                                                         'content': [{'type': 'listItem',
                                                                      'content': [{'type': 'paragraph',
                                                                                   'content': [{'type': 'text',
                                                                                                'text': 'Tata '
                                                                                                        'Capital '
                                                                                                        'Limited'}]}]}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Split Test'}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': "Bills don't wait. Neither should "
                                                                              'you.{#alphanumeric#}'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': 'Pay utility bills and mobile '
                                                                              'recharges anytime with the Tata '
                                                                              'Capital Loan App. Download now: '
                                                                              '{#Link#}'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Dear Customer,'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '💡Pay Bills the Smart Way – With '
                                                                              'Tata Capital Loan App!'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Skip the queues, skip the '
                                                                              'hassle!'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': 'Your all-in-one finance app is '
                                                                              'here.'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text', 'text': '✅Recharge'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': 'Mobile | DTH | FASTag'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text', 'text': '✅Finance and Tax'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': 'Municipal Tax | Loans | Insurance '
                                                                              '| Credit Card'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': '✅Utilities & More'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': 'Electricity | Broadband | LPG | '
                                                                              'Education Fee | Water'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Access 80+ services – Anytime, '
                                                                              'Anywhere!'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Download Tata Capital Loan App '
                                                                              'now and enjoy Finance & Beyond at '
                                                                              'your fingertips!'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'CTA: Click to Download the '
                                                                              'App.'}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'CTA / LINK'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'https://tatacap.go.link/b9vxo',
                                                                      'marks': [{'type': 'link',
                                                                                 'attrs': {'href': 'https://ind01.safelinks.protection.outlook.com/?url=https%3A%2F%2Ftatacap.go.link%2Fb9vxo&data=05%7C02%7Capurva.mohite%40tatacapital.com%7Ca5f4f125da82471d419208df0436a121%7C5400f77975bb4573a4994c50de99f6ae%7C1%7C0%7C639234304823591264%7CUnknown%7CTWFpbGZsb3d8eyJFbXB0eU1hcGkiOnRydWUsIlYiOiIwLjAuMDAwMCIsIlAiOiJXaW4zMiIsIkFOIjoiTWFpbCIsIldUIjoyfQ%3D%3D%7C0%7C%7C%7C&sdata=FJd%2FYcMLsfcjyvIGEA8cDRBcxpSWG5ouwjMYDdLbraY%3D&reserved=0'}},
                                                                                {'type': 'underline'}]}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'https://tatacap.go.link/b9vxo',
                                                                      'marks': [{'type': 'link',
                                                                                 'attrs': {'href': 'https://ind01.safelinks.protection.outlook.com/?url=https%3A%2F%2Ftatacap.go.link%2Fb9vxo&data=05%7C02%7Capurva.mohite%40tatacapital.com%7Ca5f4f125da82471d419208df0436a121%7C5400f77975bb4573a4994c50de99f6ae%7C1%7C0%7C639234304823624271%7CUnknown%7CTWFpbGZsb3d8eyJFbXB0eU1hcGkiOnRydWUsIlYiOiIwLjAuMDAwMCIsIlAiOiJXaW4zMiIsIkFOIjoiTWFpbCIsIldUIjoyfQ%3D%3D%7C0%7C%7C%7C&sdata=8yosEMxz9vxLbyRWVyg7CNOJiIhK159wPViQaqXEy%2BI%3D&reserved=0'}},
                                                                                {'type': 'underline'}]}]}]},
                                           {'type': 'tableCell', 'content': [{'type': 'paragraph'}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Date & Time of execution'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': "30th August'2026"}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': "31st August'2026"}]}]},
                                           {'type': 'tableCell', 'content': [{'type': 'paragraph'}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Testing Mobile numbers'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '9594750515, 9004462947, '
                                                                              '9987277185'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '9594750515, 9004462947, '
                                                                              '9987277185'}]}]},
                                           {'type': 'tableCell', 'content': [{'type': 'paragraph'}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Database'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'App_Downloads_Set1_27082026'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'App_Downloads_Set2_27082026'}]}]},
                                           {'type': 'tableCell', 'content': [{'type': 'paragraph'}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Product'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Marketing'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Marketing'}]}]},
                                           {'type': 'tableCell', 'content': [{'type': 'paragraph'}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Sub Product'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'App Downloads'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'App Downloads'}]}]},
                                           {'type': 'tableCell', 'content': [{'type': 'paragraph'}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Campaign\xa0Tag'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'App Engagement'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'App Engagement'}]}]},
                                           {'type': 'tableCell', 'content': [{'type': 'paragraph'}]}]}]},
                 {'type': 'mediaSingle', 'content': [{'type': 'media'}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]},
                 {'type': 'table',
                  'content': [{'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Report Name'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'App_Downloads_Set1_27082026'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'App_Downloads_Set2_27082026'}]}]}]}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]}]}
    parsed = parse_jira_brief({
        "key": 'TCN-509', "summary": 'App Downloads : SMS & WhatsApp Utility',
        "description_raw": adf, "description_text": adf_to_text(adf),
        "attachments": [], "comments": [],
    }, download_creatives=False, use_ai=False)
    assert (len(parsed.sms_templates), len(parsed.whatsapp_templates), len(parsed.rcs_templates)) == (2, 2, 0)
    assert any("Bills don't wait" in draft["text"] for draft in parsed.sms_templates)

def test_actual_tcn_301_description_preserves_every_source_copy():
    adf = {'type': 'doc',
     'version': 1,
     'content': [{'type': 'paragraph',
                  'content': [{'type': 'mention'},
                              {'type': 'text', 'text': ' '},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': 'Hi Team,'}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Kindly help with whitelisting of below content'}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'SMS', 'marks': [{'type': 'strong'}]}]},
                 {'type': 'table',
                  'content': [{'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Dear <Name>,'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': 'Make this Gudi Padwa special with '
                                                                              'seamless access to ₹<amt> from '
                                                                              'your Tata Capital Personal Loan '
                                                                              'A/c <xxx>. Perfect for '
                                                                              'celebrations or personal plans.'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': 'Access via WhatsApp: <link> or '
                                                                              'our website: <link>.'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text', 'text': 'T&Cs apply'}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Dear <Name>,'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': 'Celebrate Gudi Padwa with new '
                                                                              'possibilities. Instantly access '
                                                                              '₹<amt> from your Tata Capital '
                                                                              'Personal Loan A/c <xxx> for '
                                                                              'festive expenses or new plans.'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': 'Avail funds via WhatsApp: <link> '
                                                                              'or log in at: <link>.'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': 'T&Cs apply'}]}]}]}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'WA-', 'marks': [{'type': 'strong'}]}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Dear <Name>,'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': 'Celebrate Gudi Padwa with new possibilities. ✨'}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text',
                               'text': 'Instantly access ₹<amt> from your Tata Capital Personal Loan A/c <xxx> '
                                       'for festive expenses or new plans.😎'}]},
                 {'type': 'paragraph'},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Avail funds via WhatsApp: <link> or log in at: <link>.'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': 'T&Cs apply <disclaimer Link>'}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'CTA- {Access Instantly} \xa0<link>'}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]}]}
    parsed = parse_jira_brief({
        "key": 'TCN-301', "summary": 'Whitelisting | PL HTL Special Campaign || SMS, Whatsapp & Email || Gudi Padwa  ',
        "description_raw": adf, "description_text": adf_to_text(adf),
        "attachments": [], "comments": [],
    }, download_creatives=False, use_ai=False)
    assert (len(parsed.sms_templates), len(parsed.whatsapp_templates), len(parsed.rcs_templates)) == (2, 1, 0)
    assert all("WhatsApp:" in draft["text"] for draft in parsed.sms_templates)

def test_actual_tcn_116_description_preserves_every_source_copy():
    adf = {'type': 'doc',
     'version': 1,
     'content': [{'type': 'paragraph',
                  'content': [{'type': 'text',
                               'text': '\xa0Kindly help rewhitelist respective product images along with '
                                       'respective content & Links'}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]},
                 {'type': 'table',
                  'content': [{'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '\xa0'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'BL'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'UCL'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '\xa0\xa0 PL'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '\xa0\xa0 LAP'}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'RCS Retargeting'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '1.👋Hello Sir/Madam, your '},
                                                                     {'type': 'text',
                                                                      'text': 'Tata Capital Business Loan',
                                                                      'marks': [{'type': 'strong'}]},
                                                                     {'type': 'text',
                                                                      'text': ' journey is still incomplete.'}]},
                                                        {'type': 'paragraph'},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '⌛Don’t keep your funds waiting – '
                                                                              'avail '},
                                                                     {'type': 'text',
                                                                      'text': 'up to Rs. <90 lacs>!',
                                                                      'marks': [{'type': 'strong'}]},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': 'Tap below to proceed '
                                                                              'instantly.'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '\xa0'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'T&Cs apply'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '\xa0'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '{LINK}'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '\xa0'}]},
                                                        {'type': 'orderedList',
                                                         'content': [{'type': 'listItem',
                                                                      'content': [{'type': 'paragraph',
                                                                                   'content': [{'type': 'text',
                                                                                                'text': '🚨 '
                                                                                                        'Reminder '
                                                                                                        'Sir/Madam, '
                                                                                                        'still '
                                                                                                        'thinking '
                                                                                                        'about '
                                                                                                        'your '},
                                                                                               {'type': 'text',
                                                                                                'text': 'Business '
                                                                                                        'Loan',
                                                                                                'marks': [{'type': 'strong'}]},
                                                                                               {'type': 'text',
                                                                                                'text': '?'}]}]}]},
                                                        {'type': 'paragraph'},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '🙌 You’re just a few steps away '
                                                                              'from knowing your loan '
                                                                              'disbursal.'}]},
                                                        {'type': 'paragraph'},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '💰Proceed in your '},
                                                                     {'type': 'text',
                                                                      'text': 'Tata Capital',
                                                                      'marks': [{'type': 'strong'}]},
                                                                     {'type': 'text',
                                                                      'text': ' loan journey to receive quick '
                                                                              'funds '},
                                                                     {'type': 'text',
                                                                      'text': 'up to Rs. <90 lacs>!',
                                                                      'marks': [{'type': 'strong'}]}]},
                                                        {'type': 'paragraph'},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'T&Cs apply'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '\xa0'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '{LINK}'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '1.⚡ Don’t let this offer slip, '
                                                                              'Sir/Madam!'}]},
                                                        {'type': 'paragraph'},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '💵 Unlock up to '},
                                                                     {'type': 'text',
                                                                      'text': '200% Cash Loan',
                                                                      'marks': [{'type': 'strong'}]},
                                                                     {'type': 'text',
                                                                      'text': ' on your existing car with '},
                                                                     {'type': 'text',
                                                                      'text': 'Tata Capital.',
                                                                      'marks': [{'type': 'strong'}]}]},
                                                        {'type': 'paragraph'},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '🤩Your journey is almost complete. '
                                                                              'Tap Now to proceed! 🙌'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '\xa0'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'T&Cs apply'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '\xa0'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '{LINK}'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '\xa0'}]},
                                                        {'type': 'orderedList',
                                                         'content': [{'type': 'listItem',
                                                                      'content': [{'type': 'paragraph',
                                                                                   'content': [{'type': 'text',
                                                                                                'text': '🤩Don’t '
                                                                                                        'worry, '
                                                                                                        'Sir/Madam '
                                                                                                        '— '
                                                                                                        'picking '
                                                                                                        'up '
                                                                                                        'where '
                                                                                                        'you '
                                                                                                        'left '
                                                                                                        'off is '
                                                                                                        'easy!'}]}]}]},
                                                        {'type': 'paragraph'},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '🚘 Get up to '},
                                                                     {'type': 'text',
                                                                      'text': '200% Cash Loan',
                                                                      'marks': [{'type': 'strong'}]},
                                                                     {'type': 'text',
                                                                      'text': ' on your existing car with '},
                                                                     {'type': 'text',
                                                                      'text': 'Tata Capital! ',
                                                                      'marks': [{'type': 'strong'}]}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Click to complete your journey '
                                                                              'now!'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '\xa0'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'T&Cs apply'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '\xa0'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '{LINK}'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'orderedList',
                                                         'content': [{'type': 'listItem',
                                                                      'content': [{'type': 'paragraph',
                                                                                   'content': [{'type': 'text',
                                                                                                'text': 'Your '
                                                                                                        'Personal '
                                                                                                        'Loan '
                                                                                                        'application '
                                                                                                        'with '
                                                                                                        'Tata '
                                                                                                        'Capital '
                                                                                                        'is '
                                                                                                        'incomplete.'},
                                                                                               {'type': 'hardBreak'},
                                                                                               {'type': 'text',
                                                                                                'text': 'Here’s '
                                                                                                        'why you '
                                                                                                        'should '
                                                                                                        'complete '
                                                                                                        'it now '
                                                                                                        '👇:'}]}]}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '\xa0'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '✅ EMIs starting from just '
                                                                              '₹94/day'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '⚡ Quick disbursal'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'T&Cs apply'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '<link>'}]},
                                                        {'type': 'orderedList',
                                                         'content': [{'type': 'listItem',
                                                                      'content': [{'type': 'paragraph',
                                                                                   'content': [{'type': 'text',
                                                                                                'text': 'Dear '
                                                                                                        'Sir/ '
                                                                                                        'Ma’am,'}]}]}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': "You're just a few clicks away "
                                                                              'from accessing Personal Loan with '
                                                                              'Tata Capital.'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': '💸 Benefit of\xa0EMI starting at '
                                                                              'only ₹94/day\xa0– smart, '
                                                                              'affordable, and easy on your '
                                                                              'pocket.'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '\xa0'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '💰 Continue your loan journey and '
                                                                              'get funds quickly!'}]},
                                                        {'type': 'paragraph'},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'T&Cs apply'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '<Complete the Journey>'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '{LINK}'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'orderedList',
                                                         'content': [{'type': 'listItem',
                                                                      'content': [{'type': 'paragraph',
                                                                                   'content': [{'type': 'text',
                                                                                                'text': 'Hello '
                                                                                                        'Sir/ '
                                                                                                        'Madam, '
                                                                                                        'You’re '
                                                                                                        'just a '
                                                                                                        'few '
                                                                                                        'steps '
                                                                                                        'away '
                                                                                                        'from '
                                                                                                        'completing '
                                                                                                        'your '
                                                                                                        'Tata '
                                                                                                        'Capital '
                                                                                                        'LAP '
                                                                                                        'journey.'}]}]}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '\xa0'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '🙌 Unlock the true value of your '
                                                                              'property and enjoy\xa0'},
                                                                     {'type': 'text',
                                                                      'text': 'EMIs starting from just ₹965 per '
                                                                              'lakh',
                                                                      'marks': [{'type': 'strong'}]},
                                                                     {'type': 'text', 'text': '.'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': '💰 Proceed now to access quick and '
                                                                              'hassle-free funds.'}]},
                                                        {'type': 'paragraph'},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'T&Cs apply'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text', 'text': '{LINK}'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '\xa0'}]},
                                                        {'type': 'orderedList',
                                                         'content': [{'type': 'listItem',
                                                                      'content': [{'type': 'paragraph',
                                                                                   'content': [{'type': 'text',
                                                                                                'text': '🛠️\xa0'
                                                                                                        'Sir/Madam, '
                                                                                                        'your '
                                                                                                        'Tata '
                                                                                                        'Capital '
                                                                                                        'LAP '
                                                                                                        'application '
                                                                                                        'is '
                                                                                                        'almost '
                                                                                                        'complete'}]}]}]},
                                                        {'type': 'paragraph'},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '💰 Unlock funds with\xa0EMIs '
                                                                              'starting from ₹965/lakh\xa0and '
                                                                              'meet your financial goals.'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '\xa0'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'T&Cs apply'},
                                                                     {'type': 'hardBreak'},
                                                                     {'type': 'text',
                                                                      'text': '👉 Resume now: {LINK}'}]}]}]}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Links-'}]},
                 {'type': 'table',
                  'content': [{'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'PL_VM_Blank_RCS'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'https://www.tatacapital.com/online/loans/personal-loans/apply-now-personal-loan?sourceName=PL_VM_Blank_RCS&subsource=PL_VM_Blank_RCS&LEAD_SUB_SOURCE_1=PL_VM_Blank_RCS&cid=sms:pl:sept25:PL_VM_Blank_RCS::#!',
                                                                      'marks': [{'type': 'link',
                                                                                 'attrs': {'href': 'https://ind01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fwww.tatacapital.com%2Fonline%2Floans%2Fpersonal-loans%2Fapply-now-personal-loan%3FsourceName%3DPL_VM_Blank_RCS%26subsource%3DPL_VM_Blank_RCS%26LEAD_SUB_SOURCE_1%3DPL_VM_Blank_RCS%26cid%3Dsms%3Apl%3Asept25%3APL_VM_Blank_RCS%3A%3A%23!&data=05%7C02%7Cparth.modi%40tatacapital.com%7Cef5db970a22a48633b8c08de17800a54%7C5400f77975bb4573a4994c50de99f6ae%7C1%7C0%7C638974035878960654%7CUnknown%7CTWFpbGZsb3d8eyJFbXB0eU1hcGkiOnRydWUsIlYiOiIwLjAuMDAwMCIsIlAiOiJXaW4zMiIsIkFOIjoiTWFpbCIsIldUIjoyfQ%3D%3D%7C0%7C%7C%7C&sdata=5biEyXU7F2ZRZpuYoC2eQGXCvtl0FF7idLjJ6KjxrjE%3D&reserved=0'}},
                                                                                {'type': 'underline'}]}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'LAP_VM_Blank_RCS'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'https://www.tatacapital.com/online/loans/loan-against-property/apply-now-loan-against-property?sourceName=LAP_VM_Blank_RCS&subsource=LAP_VM_Blank_RCS&LEAD_SUB_SOURCE_1=LAP_VM_Blank_RCS&cid=sms:lap:sept25:LAP_VM_Blank_RCS::#!',
                                                                      'marks': [{'type': 'link',
                                                                                 'attrs': {'href': 'https://ind01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fwww.tatacapital.com%2Fonline%2Floans%2Floan-against-property%2Fapply-now-loan-against-property%3FsourceName%3DLAP_VM_Blank_RCS%26subsource%3DLAP_VM_Blank_RCS%26LEAD_SUB_SOURCE_1%3DLAP_VM_Blank_RCS%26cid%3Dsms%3Alap%3Asept25%3ALAP_VM_Blank_RCS%3A%3A%23!&data=05%7C02%7Cparth.modi%40tatacapital.com%7Cef5db970a22a48633b8c08de17800a54%7C5400f77975bb4573a4994c50de99f6ae%7C1%7C0%7C638974035878978926%7CUnknown%7CTWFpbGZsb3d8eyJFbXB0eU1hcGkiOnRydWUsIlYiOiIwLjAuMDAwMCIsIlAiOiJXaW4zMiIsIkFOIjoiTWFpbCIsIldUIjoyfQ%3D%3D%7C0%7C%7C%7C&sdata=hY3elb3u1ItODYylmu2tgv15X0BqubPoic6neUS0FpE%3D&reserved=0'}},
                                                                                {'type': 'underline'}]}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'BL_VM_Blank_RCS'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'https://www.tatacapital.com/online/loans/business-loans/home?sourceName=BL_VM_Blank_RCS&subsource=BL_VM_Blank_RCS&LEAD_SUB_SOURCE_1=BL_VM_Blank_RCS&cid=sms:bl:sept25:BL_VM_Blank_RCS::#!',
                                                                      'marks': [{'type': 'link',
                                                                                 'attrs': {'href': 'https://ind01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fwww.tatacapital.com%2Fonline%2Floans%2Fbusiness-loans%2Fhome%3FsourceName%3DBL_VM_Blank_RCS%26subsource%3DBL_VM_Blank_RCS%26LEAD_SUB_SOURCE_1%3DBL_VM_Blank_RCS%26cid%3Dsms%3Abl%3Asept25%3ABL_VM_Blank_RCS%3A%3A%23!&data=05%7C02%7Cparth.modi%40tatacapital.com%7Cef5db970a22a48633b8c08de17800a54%7C5400f77975bb4573a4994c50de99f6ae%7C1%7C0%7C638974035878989341%7CUnknown%7CTWFpbGZsb3d8eyJFbXB0eU1hcGkiOnRydWUsIlYiOiIwLjAuMDAwMCIsIlAiOiJXaW4zMiIsIkFOIjoiTWFpbCIsIldUIjoyfQ%3D%3D%7C0%7C%7C%7C&sdata=AxzxQGgpwsi4mhFjFi%2Bt%2FUcERcqVHov4pKnBaKKVcbA%3D&reserved=0'}},
                                                                                {'type': 'underline'}]}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'UCL_VM_Blank_RCS'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'https://www.tatacapital.com/online/loans/used-car-loans/apply-now-used-car-loan?sourceName=UCL_VM_Blank_RCS&subsource=UCL_VM_Blank_RCS&LEAD_SUB_SOURCE_1=UCL_VM_Blank_RCS&cid=sms:ucl:sept25:UCL_VM_Blank_RCS::#!',
                                                                      'marks': [{'type': 'link',
                                                                                 'attrs': {'href': 'https://ind01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fwww.tatacapital.com%2Fonline%2Floans%2Fused-car-loans%2Fapply-now-used-car-loan%3FsourceName%3DUCL_VM_Blank_RCS%26subsource%3DUCL_VM_Blank_RCS%26LEAD_SUB_SOURCE_1%3DUCL_VM_Blank_RCS%26cid%3Dsms%3Aucl%3Asept25%3AUCL_VM_Blank_RCS%3A%3A%23!&data=05%7C02%7Cparth.modi%40tatacapital.com%7Cef5db970a22a48633b8c08de17800a54%7C5400f77975bb4573a4994c50de99f6ae%7C1%7C0%7C638974035879002819%7CUnknown%7CTWFpbGZsb3d8eyJFbXB0eU1hcGkiOnRydWUsIlYiOiIwLjAuMDAwMCIsIlAiOiJXaW4zMiIsIkFOIjoiTWFpbCIsIldUIjoyfQ%3D%3D%7C0%7C%7C%7C&sdata=dXDbqCWTY4nbZRN9HRp7ugLyb5VTMeXd5gxj2deF8kQ%3D&reserved=0'}},
                                                                                {'type': 'underline'}]}]}]}]}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]}]}
    parsed = parse_jira_brief({
        "key": 'TCN-116', "summary": 'Whitelisting  || SMS and RCS Campaign II VM Blank Leads II All Products ',
        "description_raw": adf, "description_text": adf_to_text(adf),
        "attachments": [], "comments": [],
    }, download_creatives=False, use_ai=False)
    assert (len(parsed.sms_templates), len(parsed.whatsapp_templates), len(parsed.rcs_templates)) == (0, 0, 8)
    for product in ("BL", "UCL", "PL", "LAP"):
        assert sum(f"sourceName={product}_VM_Blank_RCS" in draft["action_url"] for draft in parsed.rcs_templates) == 2


def test_actual_tcn_567_comment_77243_keeps_each_utility_greeting():
    body = "  Please whitelist without CTA.\nDear {{1}},\nA useful financial habit: review your monthly commitments and plan for upcoming expenses. Staying informed can help you make more considered financial decisions.T&Cs Apply.\n1. \n\nDear {{1}},\nClear communication makes for a better experience. Tata Capital strives to make customer interactions simple, convenient and easy to understand.\nFor more information : {{2}}. T&Cs Apply.\n\xa0\nContent pending for whitelisting-\n\xa0\n1. \n\nDear {{1}},\nTata Capital provides digital channels for accessing information and services.\nOur official channels details are as follows,\nWebsite - {{2}}\nNumber - {{3}}\nTata Capital Limited.\n\xa0\n1. \n\nDear {{1}},\nTata Capital Limited is part of the Tata Group. Information about the company is available on our official website: {{2}}.\nRegards,\nTata Capital Limited.\n\xa0\n1. \n\nDear {{1}},\nThis is Tata Capital Limited's official WhatsApp communication channel. Company information is available at {{2}}.\nTata Capital Limited.\n\xa0\n1. \n\nDear {{1}},\nBeware of fake websites, emails, and calls. Always verify Tata Capital-related information through our official channels:\nWebsite - {{2}}\nNumber - {{3}}\nTata Capital Limited.\n\xa0\n1. \n\nDear {{1}},\nBeware of fraudulent calls impersonating Tata Capital. Tata Capital uses designated 1600-series numbers for applicable service and transactional calls.\nOfficial website: {{2}}\nTata Capital Limited.\n"
    parsed = parse_jira_brief({
        "key": "TCN-567", "summary": "WhatsApp utility content whitelisting",
        "description_raw": None, "description_text": "", "attachments": [],
        "comments": [{"id": '77243', "author": "Author", "body_text": body}],
    }, download_creatives=False, use_ai=False)
    assert len(parsed.whatsapp_templates) == 7
    assert all(draft["body"].startswith("Dear {{1}}") for draft in parsed.whatsapp_templates)
    assert all(draft["body"].count("Dear ") == 1 for draft in parsed.whatsapp_templates)
    assert all("Content pending" not in draft["body"] for draft in parsed.whatsapp_templates)


def test_actual_tcn_567_comment_77681_keeps_each_utility_greeting():
    body = " \nAs discussed, PFB Few more templates for whitelisting on priority.\n\xa0\nDear {{name}},\nFor information and services from Tata Capital, please use our official communication channels:\n• Website: {{url}}\n• Customer Care: <xx>\n\nStay connected through authorized Tata Capital platforms for secure assistance.\nTata Capital Limited\n1. \n\nDear {{ name }},\nTata Capital Limited is a trusted financial services company of the Tata Group.\nTo learn more about our products, services, and company information, please visit our official website: {{ url }}\nRegards,\nTata Capital Limited\n1. \n\nDear {{ name }},\nYou are interacting with Tata Capital Limited's verified WhatsApp channel.\nFor company information, products, and services, please visit: {{ url }}\nThank you for choosing Tata Capital.\nTata Capital Limited\n1. \n\nDear {{ name }},\nStay alert against fraudulent websites, emails, messages, or calls claiming to represent Tata Capital.\nAlways verify information through our official channels:\n• Website: {{url}}\n• Customer Care: <xx>\n\nYour vigilance helps protect you from fraud- Tata Capital Limited\n1. \n\nDear {{ name }},\nPlease be cautious of calls from individuals falsely claiming to represent Tata Capital.\nFor customer service and transaction-related communications, Tata Capital uses designated 1600-series numbers where applicable.\nFor verified information, visit our official website: {{url}}\nTata Capital Limited\n\xa0\n1. \n\nDear {{name}},\nFor your safety, always verify Tata Capital-related information through our official channels only.\nWebsite: {{url}}\nCustomer Care: <xx>\nStay informed. Stay secure.\nTata Capital Limited\n1. \n\nDear {{1}},\nTata Capital is committed to providing safe and reliable customer communication.\nFor verified information, services, and support, please visit: {{2}}\nTata Capital Limited\n1. \n\nDear {{name}},\nBefore sharing personal or financial information, ensure you are interacting through Tata Capital's official channels.\nOfficial Website: {{url}}\nHelpline: <xx>\nTata Capital Limited\n1. \n\nDear {{name}},\nFraudsters may use fake websites, messages, or calls claiming to represent Tata Capital.\nFor genuine information and updates, visit our official website: {{url}}\nTata Capital Limited\n10.\nDear {{name}},\nThis message is shared through an authorized Tata Capital communication channel.\nTo explore our products and services, visit: {{url}}\nThank you for your trust.\nTata Capital Limited\n11.\nDear {{name}},\nYour security is important to us. Be cautious of unauthorized communications claiming to be from Tata Capital. Tata Capital uses designated 1600-series numbers for applicable service and transactional calls.\nFor verified company information, please visit: {{url}}\nTata Capital Limited\n12.\nDear {{name}},\nTo ensure a safe experience, interact only through Tata Capital's verified communication channels.\nOfficial Website: {{url}}\nCustomer Support<xx>- Tata Capital Limited\n\xa0\n"
    parsed = parse_jira_brief({
        "key": "TCN-567", "summary": "WhatsApp utility content whitelisting",
        "description_raw": None, "description_text": "", "attachments": [],
        "comments": [{"id": '77681', "author": "Author", "body_text": body}],
    }, download_creatives=False, use_ai=False)
    assert len(parsed.whatsapp_templates) == 12
    assert all(draft["body"].startswith("Dear {{1}}") for draft in parsed.whatsapp_templates)
    assert all(draft["body"].count("Dear ") == 1 for draft in parsed.whatsapp_templates)
    assert all("Content pending" not in draft["body"] for draft in parsed.whatsapp_templates)



def test_actual_tcn_261_description_preserves_source_boundaries_and_routing():
    adf = {'type': 'doc',
     'version': 1,
     'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Hi Team,'}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text',
                               'text': 'Kindly whitelist TW top up RCS content with attached creative.'}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]},
                 {'type': 'orderedList',
                  'content': [{'type': 'listItem',
                               'content': [{'type': 'paragraph',
                                            'content': [{'type': 'text', 'text': '🚀 Fast. Simple. Stress‑Free!'},
                                                        {'type': 'hardBreak'},
                                                        {'type': 'text',
                                                         'text': 'Hi {#alphanumeric#} , your Tata Capital '
                                                                 'Pre‑approved Two‑Wheeler Top‑Up Loan is just 6 '
                                                                 'hrs away! ⏳'},
                                                        {'type': 'hardBreak'},
                                                        {'type': 'text', 'text': '💰 Up to ₹{#numeric#} Lacs'},
                                                        {'type': 'hardBreak'},
                                                        {'type': 'text', 'text': '📄 Zero Paperwork'},
                                                        {'type': 'hardBreak'},
                                                        {'type': 'text', 'text': '🧾 No Credit Check'},
                                                        {'type': 'hardBreak'},
                                                        {'type': 'text', 'text': 'Tap {#url#} to claim now!'},
                                                        {'type': 'hardBreak'},
                                                        {'type': 'text',
                                                         'text': 'T&Cs Apply.',
                                                         'marks': [{'type': 'em'}]}]}]}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]},
                 {'type': 'orderedList',
                  'content': [{'type': 'listItem',
                               'content': [{'type': 'paragraph',
                                            'content': [{'type': 'text', 'text': '⚡ Quick Funds in 6 hrs.'},
                                                        {'type': 'hardBreak'},
                                                        {'type': 'text',
                                                         'text': 'Hi {#alphanumeric#}, get your Tata Capital '
                                                                 '<Pre‑Approved Two-Wheeler Top‑Up Loan> up to '
                                                                 '₹{#numeric#} Lacs 🚀'},
                                                        {'type': 'hardBreak'},
                                                        {'type': 'text', 'text': '✨ No credit check'},
                                                        {'type': 'hardBreak'},
                                                        {'type': 'text',
                                                         'text': '✨ Instant online process'}]}]}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': '\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0 ✨Zero Hassle'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Claim now 👉 {#url#}'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': 'T&Cs Apply.', 'marks': [{'type': 'em'}]}]}]}
    parsed = parse_jira_brief({
        "key": 'TCN-261', "summary": 'Whitelisting | TW top up Campaign ',
        "description_raw": adf, "description_text": adf_to_text(adf),
        "attachments": [], "comments": [],
    }, download_creatives=False, use_ai=False)
    assert (len(parsed.sms_templates), len(parsed.whatsapp_templates), len(parsed.rcs_templates)) == (0, 0, 2)
    assert all("T&Cs Apply" in draft["body"] for draft in parsed.rcs_templates)


def test_actual_tcn_188_description_preserves_source_boundaries_and_routing():
    adf = {'type': 'doc',
     'version': 1,
     'content': [{'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Dear '},
                              {'type': 'mention'},
                              {'type': 'text', 'text': ' ,'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Kindly help with release basis below brief-'}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Count – 589037 + 479664'}]},
                 {'type': 'table',
                  'content': [{'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Campaign Name'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'TCLMOE_PA_NCL_SMS_Campaign_Dec’25'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'TCLMOE_ Retargeting '
                                                                              'PA_NCL_SMS_Campaign_Dec’25'}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'SMS Text'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Hi <Name>,'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Time’s running out! Your '
                                                                              'Pre-Approved Car Loan of up to '
                                                                              '₹<15 Lacs> is still '
                                                                              'active.'}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Your Pre-Approved Tata Capital '
                                                                              'Car Loan is ready – up to ₹<15 '
                                                                              'Lacs> with 100% on-road funding, '
                                                                              'no income proof required, and '
                                                                              'instant decisioning.'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Zero income docs. Faster '
                                                                              'approval. 100% on-road '
                                                                              'funding.'}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Act fast and drive your dream car '
                                                                              'today: <link>.T&Cs Apply'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Complete your application now: '
                                                                              '<link>. T&Cs Apply'}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'CTA / LINK'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Mentioned in base'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Mentioned in base'}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Date & Time of execution'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '18'},
                                                                     {'type': 'text',
                                                                      'text': 'th',
                                                                      'marks': [{'type': 'subsup',
                                                                                 'attrs': {'type': 'sup'}}]},
                                                                     {'type': 'text', 'text': ' Dec'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': '21'},
                                                                     {'type': 'text',
                                                                      'text': 'st ',
                                                                      'marks': [{'type': 'subsup',
                                                                                 'attrs': {'type': 'sup'}}]},
                                                                     {'type': 'text', 'text': 'Dec'}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Testing Mobile numbers'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '9004462947/9867291530'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': '9004462947/9867291530'}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Database'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'PA_NCL_DEC_06122025'}]},
                                                        {'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'PA_NCL2_DEC_06122025'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Clickers of PA_NCL_DEC_06122025 + '
                                                                              'PA_NCL2_DEC_06122025'}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Product'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'NCL'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'NCL'}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Sub Product'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'PA'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'PA'}]}]}]},
                              {'type': 'tableRow',
                               'content': [{'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Campaign Tag'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text', 'text': 'Cross sell'}]}]},
                                           {'type': 'tableCell',
                                            'content': [{'type': 'paragraph',
                                                         'content': [{'type': 'text',
                                                                      'text': 'Cross sell'}]}]}]}]},
                 {'type': 'mediaSingle', 'content': [{'type': 'media'}]}]}
    parsed = parse_jira_brief({
        "key": 'TCN-188', "summary": 'Marketing Campaign || Dec base || PA-NCL',
        "description_raw": adf, "description_text": adf_to_text(adf),
        "attachments": [], "comments": [],
    }, download_creatives=False, use_ai=False)
    assert (len(parsed.sms_templates), len(parsed.whatsapp_templates), len(parsed.rcs_templates)) == (2, 0, 0)
    assert all("T&Cs Apply" in draft["text"] for draft in parsed.sms_templates)
    assert any("Hi <Name>" in draft["text"] and "Act fast" in draft["text"] for draft in parsed.sms_templates)
    assert any("Time’s running out" in draft["text"] and "Zero income docs" in draft["text"] and "Complete your application" in draft["text"] for draft in parsed.sms_templates)


def test_actual_tcn_103_description_preserves_source_boundaries_and_routing():
    adf = {'type': 'doc',
     'version': 1,
     'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Hi Team,'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Please help whitelist below RCS content on priority'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Gujarati:', 'marks': [{'type': 'strong'}]}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'પ્રિય <name> ,', 'marks': [{'type': 'strong'}]},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '🎁 ટાટા કેપિટલ પર્સનલ લોન એ આ તહેવારની તમારી ખાસ ભેટ છે!'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '💸 ₹ સુધીના લોન તહેવારના વિશિષ્ટ દરે મેળવો'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '⚡ ઝડપી મંજૂરી—તુરંત ફંડ મેળવો'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '📝 સરળ દસ્તાવેજીકરણ'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text',
                               'text': 'તમારું ઑફર તરત અનલૉક કરવા માટે નીચે ક્લિક કરો. નિયમો લાગુ પડે છે'}]},
                 {'type': 'rule'},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Kannada:', 'marks': [{'type': 'strong'}]}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'ಪ್ರಿಯ <name> \xa0,', 'marks': [{'type': 'strong'}]},
                              {'type': 'hardBreak'},
                              {'type': 'text',
                               'text': '🎁 ಟಾಟಾ ಕ್ಯಾಪಿಟಲ್ ವೈಯಕ್ತಿಕ ಸಾಲ ಈ ಹಬ್ಬದ ನಿಮಿತ್ತ ನಿಮ್ಮ ವಿಶೇಷ ಉಡುಗೊರೆ!'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '💸 ₹ ವರೆಗೆ ಹಬ್ಬದ ವಿಶೇಷ ದರದಲ್ಲಿ ಲಾಭ ಪಡೆಯಿರಿ'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '⚡ ತ್ವರಿತ ಅನುಮೋದನೆ—ತಕ್ಷಣ ಹಣ ಪಡೆಯಿರಿ'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '📝 ಸರಳ ದಾಖಲೆ ಪ್ರಕ್ರಿಯೆ'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text',
                               'text': 'ನಿಮ್ಮ ಆಫರ್ ತಕ್ಷಣ ಅನ್ಲಾಕ್ ಮಾಡಲು ಕೆಳಗಿನ ಲಿಂಕ್ ಕ್ಲಿಕ್ ಮಾಡಿ. ನಿಯಮಗಳು '
                                       'ಅನ್ವಯವಾಗುತ್ತವೆ'}]},
                 {'type': 'rule'},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Tamil:', 'marks': [{'type': 'strong'}]}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'அன்புள்ள <name> \xa0,', 'marks': [{'type': 'strong'}]},
                              {'type': 'hardBreak'},
                              {'type': 'text',
                               'text': '🎁 டாடா கேபிடல் தனிநபர் கடன் இந்த பண்டிகைக்காலத்தில் உங்களுக்கான சிறப்பு '
                                       'பரிசாகும்!'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '💸 ₹ வரை சிறப்பு பண்டிகை விகிதத்தில் பெறுங்கள்'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '⚡ விரைவான ஒப்புதல்—உடனடி நிதி பெறுங்கள்'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '📝 எளிய ஆவணங்கள்'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text',
                               'text': 'உங்கள் சலுகையை உடனடியாக திறக்க கீழே கிளிக் செய்யவும். விதிமுறைகள் '
                                       'பொருந்தும்'}]},
                 {'type': 'rule'},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Telugu:', 'marks': [{'type': 'strong'}]}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'ప్రియమైన <name> \xa0,', 'marks': [{'type': 'strong'}]},
                              {'type': 'hardBreak'},
                              {'type': 'text',
                               'text': '🎁 టాటా క్యాపిటల్ వ్యక్తిగత రుణం ఈ పండుగ సీజన్\u200cలో మీకు ప్రత్యేక '
                                       'బహుమతి!'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '💸 ₹ వరకు ప్రత్యేక పండుగ రేట్లతో పొందండి'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '⚡ తక్షణ ఆమోదం—వెంటనే నిధులు పొందండి'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '📝 సరళమైన డాక్యుమెంటేషన్'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text',
                               'text': 'మీ ఆఫర్\u200cను వెంటనే అన్లాక్ చేయడానికి క్రింద క్లిక్ చేయండి. నిబంధనలు '
                                       'వర్తిస్తాయి'}]},
                 {'type': 'rule'},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Bengali:', 'marks': [{'type': 'strong'}]}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'প্রিয় <name>,', 'marks': [{'type': 'strong'}]},
                              {'type': 'hardBreak'},
                              {'type': 'text',
                               'text': '🎁 টাটা ক্যাপিটাল পার্সোনাল লোন এই উৎসবের মরসুমে আপনার জন্য একটি বিশেষ '
                                       'উপহার!'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '💸 ₹ পর্যন্ত লোন উৎসবের বিশেষ রেটে গ্রহণ করুন'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '⚡ দ্রুত অনুমোদন—তৎক্ষণাৎ ফান্ড পান'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '📝 সহজ ডকুমেন্টেশন'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'আপনার অফার আনলক করতে নিচে ক্লিক করুন। শর্ত প্রযোজ্য'}]},
                 {'type': 'rule'},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Punjabi:', 'marks': [{'type': 'strong'}]}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'ਪਿਆਰੇ <name> \xa0,', 'marks': [{'type': 'strong'}]},
                              {'type': 'hardBreak'},
                              {'type': 'text',
                               'text': '🎁 ਟਾਟਾ ਕੈਪਿਟਲ ਨਿੱਜੀ ਕਰਜ਼ਾ ਇਸ ਤਿਉਹਾਰੀ ਮੌਸਮ ਵਿੱਚ ਤੁਹਾਡੀ ਖਾਸ ਤੋਹਫਾ ਹੈ!'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': "💸 ₹ ਤੱਕ ਦਾ ਕਰਜ਼ਾ ਖਾਸ ਤਿਉਹਾਰੀ ਦਰਾਂ 'ਤੇ ਲਵੋ"},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '⚡ ਤੁਰੰਤ ਮਨਜ਼ੂਰੀ—ਫੰਡ ਤੁਰੰਤ ਪ੍ਰਾਪਤ ਕਰੋ'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '📝 ਆਸਾਨ ਦਸਤਾਵੇਜ਼ੀ ਕਾਰਵਾਈ'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'ਆਪਣੀ ਆਫਰ ਤੁਰੰਤ ਅਨਲੌਕ ਕਰਨ ਲਈ ਹੇਠਾਂ ਕਲਿਕ ਕਰੋ। ਨਿਯਮ ਲਾਗੂ'}]},
                 {'type': 'rule'},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Odia:', 'marks': [{'type': 'strong'}]}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'ପ୍ରିୟ <name> \xa0,', 'marks': [{'type': 'strong'}]},
                              {'type': 'hardBreak'},
                              {'type': 'text',
                               'text': '🎁 ଟାଟା କ୍ୟାପିଟାଲ ବ୍ୟକ୍ତିଗତ ଋଣ ଏହି ପର୍ବ ଋତୁରେ ଆପଣଙ୍କ ପାଇଁ ବିଶେଷ ଉପହାର!'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '💸 ₹ ପର୍ଯ୍ୟନ୍ତ ଋଣ ପାଇଁ ପର୍ବ ରିଏଟ୍\u200cରେ ଉପଲବ୍ଧ'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '⚡ ତୁରନ୍ତ ଅନୁମୋଦନ—ଅତି ଶୀଘ୍ର ତହବିଲ ପାଆନ୍ତୁ'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '📝 ସହଜ ଡକ୍ୟୁମେଣ୍ଟସନ'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'ଆପଣଙ୍କର ଅଫର ଖୋଲିବାକୁ ନିମ୍ନରେ କ୍ଲିକ୍ କରନ୍ତୁ। ନିୟମ ଲାଗୁ'}]},
                 {'type': 'rule'},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Hindi:', 'marks': [{'type': 'strong'}]}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'प्रिय <name> \xa0,', 'marks': [{'type': 'strong'}]},
                              {'type': 'hardBreak'},
                              {'type': 'text',
                               'text': '🎁 टाटा कैपिटल पर्सनल लोन इस त्योहार में आपके लिए खास तोहफा है!'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '💸 ₹ तक का लोन खास फेस्टिव रेट्स पर पाएं'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '⚡ त्वरित मंजूरी—तुरंत फंड प्राप्त करें'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '📝 आसान दस्तावेज़ीकरण'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text',
                               'text': 'अपनी ऑफर तुरंत अनलॉक करने के लिए नीचे क्लिक करें। नियम और शर्तें लागू'}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'Marathi:', 'marks': [{'type': 'strong'}]}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'प्रिय <name>,', 'marks': [{'type': 'strong'}]},
                              {'type': 'hardBreak'},
                              {'type': 'text',
                               'text': '🎁 टाटा कॅपिटल वैयक्तिक कर्ज हे या सणासुदीचे तुमच्यासाठी खास भेट आहे!'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '💸 ₹ पर्यंतचे कर्ज खास सणासुदीच्या दरात मिळवा'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '⚡ जलद मंजुरी—तुरंत निधी मिळवा'},
                              {'type': 'hardBreak'},
                              {'type': 'text', 'text': '📝 सोपी कागदपत्र प्रक्रिया'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text', 'text': 'तुमची ऑफर लगेच उघडण्यासाठी खाली क्लिक करा. अटी लागू'}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': '\xa0'}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'PFB link:'}]},
                 {'type': 'paragraph',
                  'content': [{'type': 'text',
                               'text': 'https://www.tatacapital.com/online/loans/personal-loans/home?cid=RCS:Cross-sell-PA-PL-Oct25:RCSGUPSHUP:PC#!',
                               'marks': [{'type': 'link',
                                          'attrs': {'href': 'https://ind01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fwww.tatacapital.com%2Fonline%2Floans%2Fpersonal-loans%2Fhome%3Fcid%3DRCS%3ACross-sell-PA-PL-Oct25%3ARCSGUPSHUP%3APC%23!&data=05%7C02%7Cparth.modi%40tatacapital.com%7Cb2ad05ba8ad24bf2a9dc08de0d7ee910%7C5400f77975bb4573a4994c50de99f6ae%7C1%7C0%7C638963035877071939%7CUnknown%7CTWFpbGZsb3d8eyJFbXB0eU1hcGkiOnRydWUsIlYiOiIwLjAuMDAwMCIsIlAiOiJXaW4zMiIsIkFOIjoiTWFpbCIsIldUIjoyfQ%3D%3D%7C0%7C%7C%7C&sdata=%2Bk%2BQXCzSBGeymUIdBUy1F9ZqTPUelRtB61EArnBJ%2B%2FI%3D&reserved=0'}},
                                         {'type': 'underline'}]}]},
                 {'type': 'paragraph', 'content': [{'type': 'text', 'text': 'CTA button will be Apply now'}]}]}
    parsed = parse_jira_brief({
        "key": 'TCN-103', "summary": 'Translations || PAPL Seg 6',
        "description_raw": adf, "description_text": adf_to_text(adf),
        "attachments": [], "comments": [],
    }, download_creatives=False, use_ai=False)
    assert (len(parsed.sms_templates), len(parsed.whatsapp_templates), len(parsed.rcs_templates)) == (0, 0, 9)
    assert all("cid=RCS:Cross-sell-PA-PL-Oct25:RCSGUPSHUP:PC" in draft["action_url"] for draft in parsed.rcs_templates)
    assert all(draft["action_label"].lower() == "apply now" for draft in parsed.rcs_templates)
    assert all("PFB link" not in draft["body"] for draft in parsed.rcs_templates)
