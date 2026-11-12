"""Minimized layouts from the read-only open-TCN attachment audit."""

import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import docx
import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from briefing_parser import (
    _parse_raw_sheet_rows,
    extract_templates_from_docx_file,
    extract_templates_from_excel_file,
    parse_jira_brief,
)


class AttachmentAuditTests(unittest.TestCase):
    def test_lap_contiguous_row_grid_keeps_complete_messages(self):
        # TCN-525, attachment 37532: four SMS and four RCS, not one draft per cell.
        rows = [
            ["Channel", "Group 1,2", "Group 3,4,5"],
            ["SMS", "Too many EMIs? Bring them under one roof, <name>", "Hi <Name>,"],
            ["", "Transfer your Loan Against Property to Tata Capital & unlock an exclusive Top-Up offer up to ₹<amt> to consolidate your existing debts.", "A better ROI + extra funds — all in one move."],
            ["", "Check your offer: <link>", "Transfer your Loan Against Property to Tata Capital and get a Top-Up offer up to ₹<amt> & consolidate your existing debts."],
            ["", "T&Cs apply. T&Cs apply.", "Tap tpo save more: <link>"],
            ["", "", "T&Cs apply"],
            ["", "Hi <name>,", "Hi <Name>,"],
            ["", "Multiple EMIs ka load? Ab ise simplify karne ka waqt hai. Transfer your Loan Against Property to Tata Capital & get a Top-Up offer up to ₹<amt>", "ROI bhi better, Top-Up bhi extra!"],
            ["", "Simplify your repayments today: <link>", "Apna existing Loan Against Property Tata Capital mein transfer karein aur paayein Top-Up offer up to ₹<amt> jisse aapke financies simpler ho."],
            ["", "T&Cs apply.", "Tap<link>"],
            ["", "", "T&Cs apply."],
            ["RCS", "Hi <name>,", "Better ROI. Extra funds. One smart move."],
            ["", "🏠Multiple due dates comes with multiple reminders.", ""],
            ["", "Transfer your Loan Against Property to Tata Capital and consolidate your existing debts with:", "Hi <name>,Transfer your existing Loan Against Property to Tata Capital and get a personalised Top-Up offer up to ₹<amt>."],
            ["", "💰 Top-Up offer up to ₹<amt>", ""],
            ["", "🏠 Funding up to 75% of property value", "Simplify your finances by managing multiple loans with ease."],
            ["", "CTA: Consolidate My Debts <link>", "CTA: Check My Offer <link>"],
            ["", "T&Cs apply", "T&Cs apply."],
            ["", "🏠Existing debts ko consolidate karne ka smarter way explore karein <name>", "Ek transfer, do fayde! 🏠 ,<name>"],
            ["", "Apna Loan Against Property Tata Capital mein transfer karein aur paayein:", "Aapka existing Loan Against Property Tata Capital mein transfer karke paayein:"],
            ["", "💰 Top-Up up to ₹<amt>", ""],
            ["", "📌 Repayment ko simpler banane ka option", "📉 Better interest rate"],
            ["", "🏠 Property value ka up to 75% funding", "💰 Exclusive Top-Up offer up to ₹<amt>"],
            ["", "", "📌 Existing debts consolidate karne ka option"],
            ["", "CTA: Abhi Check Karein <link>", ""],
            ["", "T&Cs apply", "CTA: Apna Offer Dekhein <link>"],
            ["", "", "T&Cs apply"],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "copy.xlsx"
            wb = openpyxl.Workbook()
            for row in rows:
                wb.active.append(row)
            wb.save(path)
            items = extract_templates_from_excel_file(path, sheet_images_map={})
        self.assertEqual(Counter(item["channel"] for item in items), {"SMS": 4, "RCS": 4})
        self.assertTrue(all("T&Cs apply" in item["text"] for item in items))
        self.assertTrue(all("<link>" in item["text"] for item in items))
        self.assertEqual(sum("consolidate your existing debts" in item["text"] for item in items), 3)

    def test_campaign_form_pairs_distinct_creatives_and_keeps_rcs_channel(self):
        # TCN-526, attachment 37535. The campaign explicitly says RCS; SMS Text is a field label.
        first = "Dear Sir/Ma'am,\nTitle:\nManage Your Loan in Just a Few Taps\n\nBody:\nSkip the hassle and access your essential loan services anytime.\n✓ Welcome Letter Download\n✓ Amortization Schedule\n✓ EMI Payment\n✓ SOA & Interest Certificate\n\nInstall the Tata Capital Loan App and stay in control.\n\nCTA:\nDownload App"
        second = "Dear Sir/Ma'am,\nTitle:\nMeet Your Everyday Money Companion\n\nBody\nYour Tata Capital Loan App helps you do much more than manage your loan.\n\n✔ Pay Utility Bills\n✔ Mobile & DTH Recharges\n✔ Check FREE Credit Score\n\nDownload today and manage your finances effortlessly.\n\nCTA:\nDownload App"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "copy.xlsx"
            wb = openpyxl.Workbook()
            wb.active.append(["Campaign Name", "TCLMOE_App_Downloads_RCS_Campaign_September’26"])
            wb.active.append(["SMS Text", first])
            wb.active.append(["", second])
            wb.active.append(["CTA / LINK", "https://tatacap.go.link/b9vxo"])
            wb.save(path)
            items = extract_templates_from_excel_file(path, sheet_images_map={"Sheet": ["first.png", "second.png"]})
        self.assertEqual([item["channel"] for item in items], ["RCS", "RCS"])
        self.assertEqual([item["media_file"] for item in items], ["first.png", "second.png"])
        self.assertEqual([item["header"] for item in items], ["Manage Your Loan in Just a Few Taps", "Meet Your Everyday Money Companion"])
        self.assertTrue(all(item["button_text"] == "Download App" for item in items))
        self.assertTrue(all(item["button_url"] == "https://tatacap.go.link/b9vxo" for item in items))

    def test_referral_consent_messages_do_not_merge(self):
        # TCN-552/531, attachment 38077/38013: two successive complete messages lack greetings.
        messages = [
            "You have been referred by [Referrer’s Name] regarding <Loan> requirement. To proceed with journey, click here <link>\nT&Cs Apply <link> – Tata Capital Ltd",
            "Check <Loan > offer now!\n[Referrer’s Name] has referred you to Tata Capital! Click here <link>\nT&Cs Apply <link>",
            "{Referrer Name} just referred you for a <Loan>! Click <link> to see what you’re eligible for! T&Cs Apply <link> – Tata Capital Ltd",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Referral Content.docx"
            document = docx.Document()
            document.add_paragraph("SMS –")
            for message in messages:
                document.add_paragraph(message)
            document.save(path)
            items = extract_templates_from_docx_file(path)
        self.assertEqual([item["text"] for item in items], messages)

    def test_language_labels_require_explicit_document_channel(self):
        # Language-only Regional Promotional.docx is genuinely ambiguous; do not guess SMS.
        english = "Hi {FirstName}, your good repayment track has unlocked a Pre-Approved Top-Up Loan offer of up to ₹3 Lacs from Tata Capital. Get funds in as little as 6 hours. Apply now: {Link} T&Cs apply."
        marathi = "Hi {FirstName}, तुमच्या चांगल्या परतफेडीच्या रेकॉर्डमुळे Tata Capital कडून ₹3 लाखांपर्यंतची प्रीअप्रूव्ह्ड टॉपअप लोन ऑफर मिळाली आहे. केवळ 6 तासांत निधी मिळवा. आत्ताच अर्ज करा: {Link}अटी व शर्ती लागू।"
        with tempfile.TemporaryDirectory() as tmp:
            document = docx.Document()
            for line in ("English", english, "Marathi", marathi):
                document.add_paragraph(line)
            ambiguous = Path(tmp) / "Regional Promotional.docx"
            document.save(ambiguous)
            self.assertEqual(extract_templates_from_docx_file(ambiguous), [])
            explicit = Path(tmp) / "SMS Regional Promotional.docx"
            document.save(explicit)
            items = extract_templates_from_docx_file(explicit)
        self.assertEqual([item["language"] for item in items], ["en", "mr"])
        self.assertEqual([item["text"] for item in items], [english, marathi])

    def test_compact_word_channel_headings_keep_languages_separate(self):
        english = "Hi <Name>, access your Tata Capital personal loan offer up to ₹<amt>. Apply now: <link>. T&Cs apply"
        hindi = "नमस्ते <Name>, Tata Capital से अपना पर्सनल लोन ऑफर पाएं। आवेदन करें: <link>। नियम लागू।"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "copy.docx"
            document = docx.Document()
            document.add_paragraph("SMSRegional")
            document.add_paragraph(f"English:{english}Hindi:{hindi}")
            document.add_paragraph("WA1")
            document.add_paragraph("English")
            document.add_paragraph(english)
            document.save(path)
            items = extract_templates_from_docx_file(path)
        self.assertEqual([item["channel"] for item in items], ["SMS", "SMS", "WA"])
        self.assertEqual([item["language"] for item in items], ["en", "hi", "en"])
        self.assertEqual([item["text"] for item in items[:2]], [english, hindi])

    def test_binary_workbook_channel_continuations_skip_noncopy(self):
        # TCN-353: the RCS note in GC is not a new message.
        sms = [
            f"Dear <Name>, your Tata Capital personal loan offer number {i} is ready. Apply now: <link>. T&Cs apply"
            for i in range(5)
        ]
        visual = "Hi <Name>, your Tata Capital pre-approved personal loan offer up to ₹<amt> is ready. Apply now: <link>. T&Cs apply"
        propensity = [["SMS", sms[0], "185.0"], ["", sms[1], "217.0"], ["RCS", visual], ["WA", visual]]
        gc = [["SMS", sms[2], "163.0"], ["", sms[3], "159.0"], ["", sms[4], "171.0"], ["WA", visual], ["RCS", "New Made Already"]]
        items = _parse_raw_sheet_rows(propensity, "Propensity Retention") + _parse_raw_sheet_rows(gc, "GC")
        self.assertEqual(Counter(item["channel"] for item in items), {"SMS": 5, "WA": 2, "RCS": 1})
        self.assertNotIn("New Made Already", [item["text"] for item in items])

    def test_campaign_form_retains_all_parallel_content_columns(self):
        # TCN-551: four SMS occupy two campaign columns and two content rows.
        messages = [
            f"Dear <Name>, your Tata Capital business loan offer {index} is ready. Apply now: <link>. T&Cs apply"
            for index in range(4)
        ]
        rows = [
            ["Campaign Name", "TCL_Business_SMS", "TCL_Retargeting_SMS"],
            ["SMS Text", messages[0], "1. " + messages[1]],
            ["", messages[2], "2. " + messages[3]],
            ["CTA / LINK", "Mentioned in base", "Mentioned in base"],
        ]
        items = _parse_raw_sheet_rows(rows, "SMS")
        self.assertEqual([item["raw_text"] for item in items], messages)
        self.assertEqual([item["channel"] for item in items], ["SMS"] * 4)

    def test_pdf_and_xlsb_are_collected_without_creative_downloads(self):
        message = "Dear <Name>, your Tata Capital personal loan offer is ready. Apply now: <link>. T&Cs apply"
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "copy.pdf"
            binary = Path(tmp) / "copy.xlsb"
            pdf.write_bytes(b"pdf-fixture")
            binary.write_bytes(b"xlsb-fixture")
            issue = {
                "key": "TCN-353", "summary": "Whitelisting", "description_text": "Pick SMS for now.",
                "attachments": [
                    {"id": "pdf", "filename": pdf.name, "local_path": str(pdf)},
                    {"id": "binary", "filename": binary.name, "local_path": str(binary)},
                ],
            }
            with patch("pdf_copy_parser.extract_templates_from_pdf_file", return_value=[]) as read_pdf, patch(
                "briefing_parser._load_spreadsheet_sheets", return_value={"SMS": [["SMS", message]]},
            ) as read_binary:
                brief = parse_jira_brief(issue, download_creatives=False)
        read_pdf.assert_called_once_with(pdf, description="Pick SMS for now.", summary="Whitelisting")
        read_binary.assert_called_once_with(binary)
        self.assertEqual(len(brief.sms_templates), 1)
        self.assertEqual([att["target_channel"] for att in brief.attachments_mapped], ["PDF_BRIEF", "SPREADSHEET_BRIEF"])

    def test_real_xlsb_copy_and_noncopy_sheets_if_available(self):
        path = Path("/tmp/tcn-attachment-audit/jira_29369_Book1__version_1_.xlsb")
        if not path.exists():
            self.skipTest("Read-only TCN-353 corpus unavailable")
        items = extract_templates_from_excel_file(path, sheet_images_map={})
        self.assertEqual(Counter(item["channel"] for item in items), {"SMS": 5, "WA": 2, "RCS": 1})
        self.assertTrue(all("New Made Already" not in item["text"] for item in items))

    def test_carousel_never_cycles_mismatched_creatives(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "copy.xlsx"
            workbook = openpyxl.Workbook()
            workbook.active.title = "RCS Carousel"
            for index in range(3):
                workbook.active.append(["RCS", f"Dear <Name>, your Tata Capital personal loan offer {index} is ready. Apply now: <link>. T&Cs apply"])
            workbook.save(path)
            items = extract_templates_from_excel_file(path, sheet_images_map={"RCS Carousel": ["first.png", "second.png"]})
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["media_pairing_ambiguous"])
        self.assertTrue(all(card["media_url"] is None for card in items[0]["carousel_cards"]))


if __name__ == "__main__":
    unittest.main()
