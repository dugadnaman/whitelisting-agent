"""
Unit tests for RCS DLT template configuration pipeline.
"""

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from rcs_client import _build_dlt_payload, submit_rcs_template
from rcs_config import BAJAJ_ENTITY_ID
from rcs_loader import (
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

    def test_parse_sender_ids(self):
        # Single sender
        self.assertEqual(_parse_sender_ids("BajajM"), ["BajajM"])
        # Multiple comma-separated
        self.assertEqual(_parse_sender_ids("BFDLPS, BFDLTS"), ["BFDLPS", "BFDLTS"])
        # Multiple pipe-separated
        self.assertEqual(_parse_sender_ids("BFDLPS | BFDLTS | BFDLPL"), ["BFDLPS", "BFDLTS", "BFDLPL"])
        # Max 5 enforcement
        six_senders = "S1, S2, S3, S4, S5, S6"
        self.assertEqual(_parse_sender_ids(six_senders), ["S1", "S2", "S3", "S4", "S5"])
        # Empty
        self.assertEqual(_parse_sender_ids(""), [])
        self.assertEqual(_parse_sender_ids(None), [])

    def test_load_sample_csv(self):
        csv_path = "rcs_templates_sample.csv"
        submissions = load_rcs_from_csv(csv_path)

        self.assertEqual(len(submissions), 4)

        # Row 1: Vehicle_Loan_Offer
        s1 = submissions[0]
        self.assertEqual(s1.template_name, "Vehicle_Loan_Offer")
        self.assertEqual(s1.template_id, "1107166074191019404")
        self.assertEqual(s1.template_type, "Transactional")
        self.assertEqual(s1.sender_ids, ["BFDLPS", "BFDLTS"])
        self.assertEqual(s1.template_message_type, "Text")
        self.assertEqual(s1.entity_id, "110100001654")
        self.assertIn("{#var#}", s1.template_message)

        # Row 2: Personal_Loan_Instant (3 sender IDs)
        s2 = submissions[1]
        self.assertEqual(s2.template_name, "Personal_Loan_Instant")
        self.assertEqual(s2.template_type, "Promotional")
        self.assertEqual(s2.sender_ids, ["BFDLPS", "BFDLTS", "BFDLPL"])

        # Row 3: Feedback_Survey_Request (Entity ID omitted -> defaulted to BAJAJ_ENTITY_ID)
        s3 = submissions[2]
        self.assertEqual(s3.template_name, "Feedback_Survey_Request")
        self.assertEqual(s3.template_type, "Service - Implicit")
        self.assertEqual(s3.sender_ids, ["BajajM"])
        self.assertEqual(s3.entity_id, BAJAJ_ENTITY_ID)

    def test_build_dlt_payload(self):
        sub = RcsTemplateSubmission(
            template_name="Test_Tpl",
            template_id="1107123456789012345",
            template_type="Transactional",
            sender_ids=["BFDLPS", "BFDLTS"],
            template_message_type="Text",
            template_message="Test message {#var#}",
            entity_id=BAJAJ_ENTITY_ID,
        )
        payload = _build_dlt_payload(sub)
        self.assertEqual(payload["action"], "addTemplate")
        self.assertEqual(payload["entityId"], BAJAJ_ENTITY_ID)
        self.assertEqual(payload["templateId"], "1107123456789012345")
        self.assertEqual(payload["templateName"], "Test_Tpl")
        self.assertEqual(payload["senderId"], ["BFDLPS", "BFDLTS"])
        self.assertEqual(payload["templateType"], "Transactional")
        self.assertEqual(payload["templateMsgType"], "Text")
        self.assertEqual(payload["templateMsg"], "Test message {#var#}")

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
        update_rcs_result("Test_Ref", {"status": "duplicate"}, log_path=tmp_log)
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
            template_message="Test message {#var#}",
        )
        result = submit_rcs_template(sub)
        self.assertEqual(result.status, RcsSubmissionStatus.SUBMITTED)
        self.assertEqual(result.template_name, "Test_Tpl")


if __name__ == "__main__":
    unittest.main()
