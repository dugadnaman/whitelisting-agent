"""
Unit tests for the RCS Bot Builder template pipeline (current architecture).

Covers: row-key normalization, sample CSV loading, sender-ID parsing,
JSONL tracker round-trips, and client submission with mocked network.
"""

import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from rcs_client import submit_rcs_template
from rcs_loader import (
    _normalize_row_keys,
    _parse_sender_ids,
    load_rcs_from_csv,
)
from rcs_models import (
    RcsSubmissionResult,
    RcsSubmissionStatus,
    RcsTemplateSubmission,
)
from rcs_tracker import load_rcs_log, log_rcs_result, update_rcs_result


class TestRcsPipeline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(patch.stopall)
        patch("rcs_config._load_env_file", return_value=None).start()
        patch.dict(os.environ, {
            "TATA_RCS_AUTH_TOKEN": "local-test-token",
            "TATA_RCS_ESMEADDR": "72434700000000",
            "TATA_RCS_BOT_ID": "Uv9tdd0KNADbq3pX",
            "DATABASE_URL": "", "POSTGRES_URL": "", "POSTGRESQL_URL": "",
        }).start()
        patch("db.DB_PATH", Path(self.temp.name) / "private.sqlite").start()
        patch("db.DEFAULT_SQLITE_PATH", Path(self.temp.name) / "private.sqlite").start()
        patch("db.get_database_url", return_value="").start()

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
        tmp_log = str(Path(self.temp.name) / "test_rcs_log.jsonl")
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
        mock_resp.json.return_value = {"status": "success", "message": "Template Added", "templateId": "provider-123"}
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
        self.assertEqual(result.template_id, "provider-123")

    @patch("moengage_sync.get_moengage_auth_headers", return_value={"Authorization": "Bearer test"})
    @patch("moengage_sync.requests.post")
    def test_create_moengage_rcs_template_carousel(self, mock_post, mock_headers):
        from moengage_sync import create_moengage_rcs_template

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"status": True, "data": {"id": "moe_123", "created_at": "2026-10-14"}}
        mock_post.return_value = mock_resp

        carousel_cards = [
            {
                "cardTitle": "Festive Offer Card 1",
                "cardDescription": "Get personal loan up to 5L",
                "mediaUrl": "https://example.com/c1.jpg",
                "suggestions": [{"suggestionType": "url_action", "text": "Apply Now", "url": "https://example.com/apply"}]
            },
            {
                "cardTitle": "Festive Offer Card 2",
                "cardDescription": "Lowest interest rate 9.5%",
                "mediaUrl": "https://example.com/c2.jpg",
                "suggestions": [{"suggestionType": "url_action", "text": "Check Rates", "url": "https://example.com/rates"}]
            }
        ]

        res = create_moengage_rcs_template(
            template_name="festive_carousel",
            template_id="festive_carousel",
            card_title="Card Title",
            card_description="Card Desc",
            account="tata",
            template_type="carousel",
            carousel_cards=carousel_cards,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["moengage_id"], "moe_123")

        call_payload = mock_post.call_args[1]["json"]
        self.assertEqual(call_payload["meta_data"]["rcs_template_type"], "carousel")
        self.assertEqual(len(call_payload["meta_data"]["data"]["cards"]), 2)
        self.assertEqual(call_payload["meta_data"]["data"]["cards"][0]["title"], "Festive Offer Card 1")
        self.assertEqual(call_payload["meta_data"]["data"]["cards"][1]["title"], "Festive Offer Card 2")



if __name__ == "__main__":
    unittest.main()
