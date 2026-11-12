"""PDF geometry fixtures: colored vectors are not necessarily annotations or authority."""

import json
import os
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from pdf_copy_parser import extract_templates_from_pdf_file


REQUEST = ("Please pick the highlighted content for whitelisting. Pick SMS for now, "
           "will share creatives for RCS and Whatsapp.")
FIRST = "Dear <Name>,\nSelected first copy.\nOffer: <Link>\nT&C Apply."
SECOND = "Dear <Name>,\nUnselected second copy.\nOffer: <OtherLink>\nT&C Apply."


def add_page(document, channel="SMS", marked=(), banner=False, font=False, partial=False):
    page = document.new_page(width=620, height=400)
    page.insert_text((30, 30), channel + " | Pre Approved", fontsize=14)
    # Decorative brand rectangle: never an instruction to select nearby body text.
    page.draw_rect(fitz.Rect(0, 40, 620, 44), color=None, fill=(0.8, 0.9, 0.1))
    if banner:
        page.draw_rect(fitz.Rect(420, 10, 610, 38), color=None, fill=(0.57, 0.82, 0.31))
        page.insert_text((430, 30), "To Whitelist", fontsize=12)
    for index, text in enumerate((FIRST, SECOND)):
        x = 30 + index * 300
        if index in marked and not font:
            page.draw_rect(fitz.Rect(x - 5, 85, x + 260, 110 if partial else 185),
                           color=None, fill=(1, 1, 0))
        page.insert_textbox(fitz.Rect(x, 95, x + 255, 185), text, fontsize=11,
                            color=(0.9, 0, 0) if font and index in marked else (0, 0, 0))
        page.insert_text((x, 230), "168 characters", fontsize=10)
    return page


class PdfCopyParserTests(unittest.TestCase):
    def parse(self, document, description=REQUEST):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "copy.pdf"
            document.save(path)
            return extract_templates_from_pdf_file(path, description=description)

    def test_filled_highlight_without_annotation_excludes_unselected_copy(self):
        with fitz.open() as document:
            page = add_page(document, marked=(0,))
            self.assertEqual(list(page.annots() or ()), [])
            items = self.parse(document)
        self.assertEqual([item["channel"] for item in items], ["SMS"])
        self.assertEqual([item["text"] for item in items], [FIRST])
        self.assertNotIn("characters", items[0]["text"])
        self.assertEqual(items[0]["source_page"], 1)
        self.assertLess(items[0]["source_bbox"][2], 330)

    def test_selected_font_color_is_recovered_without_annotations(self):
        with fitz.open() as document:
            add_page(document, marked=(1,), font=True)
            items = self.parse(document)
        self.assertEqual([item["text"] for item in items], [SECOND])

    def test_uniform_colored_cards_are_ambiguous_not_whole_document_fallback(self):
        with fitz.open() as document:
            add_page(document, marked=(0, 1))
            with self.assertRaisesRegex(ValueError, "missing selection authority: all copies share"):
                self.parse(document)

    def test_partial_mark_requires_complete_copy_authority(self):
        with fitz.open() as document:
            add_page(document, marked=(0,), partial=True)
            with self.assertRaisesRegex(ValueError, "highlight covers only part of a copy"):
                self.parse(document)

    def test_unmarked_alternatives_are_excluded_with_audit_warning(self):
        with fitz.open() as document:
            add_page(document)
            with self.assertLogs("pdf_copy_parser", level="WARNING") as logs:
                items = self.parse(document)
        self.assertEqual(items, [])
        self.assertIn("missing positive selection authority", logs.output[0])

    def test_explicit_banner_is_scoped_to_sms_and_preserves_columns(self):
        with fitz.open() as document:
            add_page(document, banner=True)
            add_page(document, channel="WA", banner=True)
            add_page(document, channel="RCS", banner=True)
            items = self.parse(document)
        self.assertEqual([item["channel"] for item in items], ["SMS", "SMS"])
        self.assertEqual([item["text"] for item in items], [FIRST, SECOND])
        self.assertEqual([item["source_page"] for item in items], [1, 1])

    def test_sms_only_document_with_proven_other_channels_is_empty(self):
        with fitz.open() as document:
            add_page(document, channel="RCS", banner=True)
            self.assertEqual(self.parse(document), [])

    def test_unrestricted_request_uses_explicit_channel_headings(self):
        with fitz.open() as document:
            add_page(document)
            add_page(document, channel="WA")
            items = self.parse(document, "Please whitelist below content")
        self.assertEqual(Counter(item["channel"] for item in items), {"SMS": 2, "WA": 2})
        self.assertEqual([item["text"] for item in items], [FIRST, SECOND, FIRST, SECOND])

    def test_rich_channel_copy_cannot_borrow_unproven_media(self):
        with fitz.open() as document:
            add_page(document, channel="WA")
            add_page(document, channel="RCS")
            items = self.parse(document, "Please whitelist below content")
        self.assertEqual(Counter(item["channel"] for item in items), {"WA": 2, "RCS": 2})
        self.assertTrue(all(item["media_pairing_ambiguous"] for item in items))
        self.assertTrue(all("media_file" not in item for item in items))

    def test_unreadable_authored_text_does_not_silently_disappear(self):
        with fitz.open() as document:
            document.new_page()
            with self.assertRaisesRegex(ValueError, "missing selectable text authority"):
                self.parse(document)

    def test_missing_channel_does_not_default_to_sms(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((30, 100), FIRST)
            with self.assertRaisesRegex(ValueError, "missing explicit channel heading authority"):
                self.parse(document)

    @unittest.skipUnless(os.environ.get("TCN_PDF_CORPUS"), "set TCN_PDF_CORPUS to the read-only audit directory")
    def test_optional_eight_source_pdfs(self):
        root = Path(os.environ["TCN_PDF_CORPUS"])
        records = json.loads((root / "downloads.json").read_text())
        expected = {"33865": {"SMS": 2}, "33942": {"SMS": 2}, "34288": {},
                    "34416": {}, "34417": {}, "36242": {"SMS": 16, "WA": 12},
                    "36607": {"SMS": 16, "WA": 12}, "36334": {"SMS": 16, "WA": 12}}
        seen = set()
        for record in records:
            if record["id"] not in expected:
                continue
            seen.add(record["id"])
            with self.subTest(attachment=record["id"]):
                path = root / Path(record["path"]).name
                items = extract_templates_from_pdf_file(
                    path, REQUEST if record["ticket"] == "TCN-457" else "Please whitelist below content",
                    record["summary"],
                )
                self.assertEqual(Counter(item["channel"] for item in items), expected[record["id"]])
                self.assertTrue(all("characters" not in item["text"] for item in items))
                self.assertTrue(all(item["text"].startswith("Dear") for item in items))
        self.assertEqual(seen, set(expected))


if __name__ == "__main__":
    unittest.main()
