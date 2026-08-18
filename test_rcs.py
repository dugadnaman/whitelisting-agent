"""
Unit tests for the RCS Bot Builder template pipeline (current architecture).

Covers: row-key normalization, sample CSV loading, sender-ID parsing,
JSONL tracker round-trips, and client submission with mocked network.
"""

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from rcs_client import submit_rcs_template
from rcs_loader import (
    _normalize_row_keys,
    _parse_sender_ids,
    load_rcs_from_csv,
    load_rcs_from_list,
)
from rcs_models import (
    RcsSubmissionResult,
    RcsSubmissionStatus,
    RcsTemplateSubmission,
)
from rcs_tracker import load_rcs_log, log_rcs_result, update_rcs_result


class TestRcsPipeline(unittest.TestCase):

    def test_normalize_row_keys(self):
        raw = {
            "Template Name": "A",
            "botid": "B",
            " entity_id ": "E",
            "Unknown-Key": "K",
        }
        norm = _normalize_row_keys(raw)
        self.assertEqual(norm["template_name"], "A")
        self.assertEqual(norm["bot_id"], "B")
        self.assertEqual(norm["entity_id"], "E")
        self.assertEqual(norm["Unknown-Key"], "K")

    def test_parse_sender_ids(self):
        self.assertEqual(_parse_sender_ids("BajajM"), ["BajajM"])
        self.assertEqual(_parse_sender_ids("BFDLPS | BFDLTS"), ["BFDLPS", "BFDLTS"])
        self.assertEqual(_parse_sender_ids("BFDLPS, BFDLTS"), ["BFDLPS", "BFDLTS"])
        self.assertEqual(_parse_sender_ids(["A", " B "]), ["A", "B"])
        self.assertEqual(_parse_sender_ids(""), [])
        self.assertEqual(_parse_sender_ids(None), [])

    def test_load_sample_csv(self):
        csv_path = "rcs_templates_sample.csv"
        submissions = load_rcs_from_csv(csv_path)

        self.assertEqual(len(submissions), 5)

        by_name = {s.template_name: s for s in submissions}

        carousel = by_name["tata_product_carousel"]
        self.assertEqual(carousel.template_type, "carousel")
        self.assertEqual(len(carousel.carousel_cards), 2)
        self.assertTrue(carousel.carousel_cards[0]["mediaUrl"].startswith("https://"))

        text = by_name["tata_pl_instant_offer"]
        self.assertEqual(text.template_type, "text")
        self.assertIn("[Name]", text.text_message)

        richcard = by_name["tata_festive_card_offer"]
        self.assertEqual(richcard.template_type, "richcard")
        self.assertEqual(richcard.card_title, "Festive Personal Loan")

        dialer = by_name["tata_loan_service_dialer"]
        self.assertEqual(dialer.suggestions[0]["suggestionType"], "dialer_action")
        self.assertEqual(dialer.suggestions[0]["phoneNumber"], "+919999999999")

        reply = by_name["tata_feedback_survey"]
        self.assertEqual(len(reply.suggestions), 2)
        self.assertEqual(reply.suggestions[0]["suggestionType"], "reply")

    def test_tracker_log_and_read(self):
        tmp_log = "scratch/test_rcs_log.jsonl"
        Path("scratch").mkdir(parents=True, exist_ok=True)
        if os.path.exists(tmp_log):
            os.remove(tmp_log)

        res = RcsSubmissionResult(
            source_ref="Test_Ref",
            template_name="Test_Tpl",
            template_id="1107123456789012345",
            status=RcsSubmissionStatus.SUBMITTED,
            provider_response={"status": "success"},
        )
        log_rcs_result(res, log_path=tmp_log)

        entries = load_rcs_log(tmp_log)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["template_name"], "Test_Tpl")
        self.assertEqual(entries[0]["status"], "submitted")

        # Update entry
        self.assertTrue(update_rcs_result("Test_Ref", {"status": "duplicate"}, log_path=tmp_log))
        updated = load_rcs_log(tmp_log)
        self.assertEqual(updated[0]["status"], "duplicate")

        if os.path.exists(tmp_log):
            os.remove(tmp_log)

    @patch("rcs_client.requests.post")
    def test_client_submission_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "success", "message": "Template Added"}
        mock_post.return_value = mock_resp

        sub = RcsTemplateSubmission(
            template_name="Test_Tpl",
            template_id="1107123456789012345",
            template_type="Transactional",
            sender_ids=["BFDLPS"],
            template_message_type="Text",
            text_message="Test message {#var#}",
        )
        result = submit_rcs_template(sub)
        self.assertEqual(result.status, RcsSubmissionStatus.SUBMITTED)
        self.assertEqual(result.template_name, "Test_Tpl")
        self.assertIsNotNone(result.template_id)


if __name__ == "__main__":
    unittest.main()
