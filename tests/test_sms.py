"""
Unit and integration tests for the Karix SMS pipeline.

Covers:
1. PII Cryptography (AES-256 CBC + PBKDF2 HMAC-SHA1 11 iterations) matching Karix PDF specification.
2. DLR Cryptography (AES-GCM encryption & decryption).
3. Models and request dictionary serialization.
4. Input loader (row key normalization, phone number cleaning, CSV parsing, previews).
5. SMS Client (validation, payload preparation, network mock, retries, PII encryption).
6. Tracker (process-safe JSONL logging, DLR tracking, statistics aggregation).
7. FastAPI Webhook and REST Endpoints (/api/sms/send, /api/sms/dlr, /api/sms/click, /api/sms/stats).
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api import app
from sms_client import send_quick_sms, send_sms, test_sms_connection as check_sms_connection
from sms_crypto import (
    decrypt_dlr_gcm,
    decrypt_sms_pii,
    encrypt_dlr_gcm,
    encrypt_sms_pii,
)
from sms_loader import (
    _clean_phone_number,
    _normalize_sms_row_keys,
    _parse_template_values,
    load_sms_from_csv,
    load_sms_from_list,
    preview_sms_rows,
)
from sms_models import (
    SMS_ERROR_CODES,
    SmsClickReport,
    SmsDlrReport,
    SmsMessage,
    SmsMessageType,
    SmsSubmissionResult,
)
from sms_tracker import (
    get_sms_stats,
    load_sms_clicks,
    load_sms_dlrs,
    load_sms_submissions,
    log_sms_click,
    log_sms_dlr,
    log_sms_submission,
)


class TestSmsCrypto(unittest.TestCase):
    """Verify cryptographic functions against Karix specification & PDF test vectors."""

    def test_karix_pdf_sample_decryption(self):
        """Test decryption of exact sample vectors given in Karix Send SMS API PDF."""
        secure_key = "ODAyMjY5MDAwMDAwMDAmbUdQclNhbGU="
        dest_enc = "KqSaXnGO7GOoIGyK8AC4dvcQjhAui8FC8/mSQ9vut3+aumgq7qe9VUROe1f59KWK4N1sgA=="
        text_enc = "TjylAIUBGOUu2qkSLJfMsjJ1AA6rI2XMdn/vRNNz9I+sI063um7CaEAUQwIelqBBtE2xW5hcRciDrPWH7DzaP9wf00KR/wv12OLYhxMqxu7+LOAYSRH5C2bcfX5Bzu9uPuDqsw=="

        dest_dec = decrypt_sms_pii(dest_enc, secure_key)
        text_dec = decrypt_sms_pii(text_enc, secure_key)

        self.assertEqual(dest_dec, "919008031474")
        self.assertEqual(text_dec, "Karix portal one time password for your transaction is : 1234")

    def test_pii_encryption_roundtrip(self):
        """Test that encrypting and decrypting with random salt & IV produces original plaintext."""
        key = "ODAyMjY5MDAwMDAwMDAmbUdQclNhbGU="
        original_text = "Your OTP for Bajaj Finserv is 998812. Do not share."
        encrypted = encrypt_sms_pii(original_text, key)

        self.assertNotEqual(encrypted, original_text)
        decrypted = decrypt_sms_pii(encrypted, key)
        self.assertEqual(decrypted, original_text)

    def test_dlr_aes_gcm_roundtrip(self):
        """Test AES-GCM encryption and decryption for DLR webhooks."""
        gcm_key = "0123456789abcdef0123456789abcdef"
        gcm_iv = "123456789012"
        payload = json.dumps({"status": "Delivered", "mid": "981273918237", "ackid": "ACK9021"})

        encrypted_b64 = encrypt_dlr_gcm(payload, gcm_key, gcm_iv)
        self.assertNotEqual(encrypted_b64, payload)

        decrypted_json = decrypt_dlr_gcm(encrypted_b64, gcm_key, gcm_iv)
        self.assertEqual(decrypted_json, payload)
        parsed = json.loads(decrypted_json)
        self.assertEqual(parsed["status"], "Delivered")
        self.assertEqual(parsed["ackid"], "ACK9021")

    def test_empty_string_handling(self):
        self.assertEqual(encrypt_sms_pii("", "dummy"), "")
        self.assertEqual(decrypt_sms_pii("", "dummy"), "")


class TestSmsModels(unittest.TestCase):
    """Test data models and dictionary serialization."""

    def test_sms_message_to_dict_plain(self):
        msg = SmsMessage(
            dest=["919876543210"],
            text="Test message",
            send="BAJAJF",
            type=SmsMessageType.PLAIN,
            dlt_entity_id="1001492930000010179",
            dlt_template_id="1107161951486743588",
            cust_ref="REF100",
        )
        d = msg.to_dict(encrypt=False)
        self.assertEqual(d["dest"], ["919876543210"])
        self.assertEqual(d["text"], "Test message")
        self.assertEqual(d["send"], "BAJAJF")
        self.assertEqual(d["type"], "PM")
        self.assertEqual(d["dlt_entity_id"], "1001492930000010179")
        self.assertEqual(d["cust_ref"], "REF100")

    def test_sms_message_to_dict_encrypted(self):
        key = "ODAyMjY5MDAwMDAwMDAmbUdQclNhbGU="
        msg = SmsMessage(
            dest=["919876543210"],
            text="Secret OTP",
            send="BAJAJF",
        )
        d = msg.to_dict(encrypt=True, encryption_key=key)
        self.assertNotEqual(d["dest"], ["919876543210"])
        self.assertNotEqual(d["text"], "Secret OTP")
        # Ensure we can decrypt it back
        self.assertEqual(decrypt_sms_pii(d["dest"][0], key), "919876543210")
        self.assertEqual(decrypt_sms_pii(d["text"], key), "Secret OTP")

    def test_dlr_report_helpers(self):
        delivered_report = SmsDlrReport(status_flag="Success", reason="Delivered")
        self.assertTrue(delivered_report.is_delivered())
        self.assertFalse(delivered_report.is_failed())

        failed_report = SmsDlrReport(status_flag="Failed", reason="Network Failed")
        self.assertFalse(failed_report.is_delivered())
        self.assertTrue(failed_report.is_failed())


class TestSmsLoader(unittest.TestCase):
    """Test input normalization and loading from list/CSV."""

    def test_normalize_sms_row_keys(self):
        raw = {
            "Phone Number": "919876543210",
            "Message Text": "Hello there",
            "Sender ID": "BAJAJF",
            "Entity ID": "ENT123",
            "Template ID": "TMP456",
        }
        norm = _normalize_sms_row_keys(raw)
        self.assertEqual(norm["dest"], "919876543210")
        self.assertEqual(norm["text"], "Hello there")
        self.assertEqual(norm["send"], "BAJAJF")
        self.assertEqual(norm["dlt_entity_id"], "ENT123")
        self.assertEqual(norm["dlt_template_id"], "TMP456")

    def test_clean_phone_number(self):
        # Excel float
        self.assertEqual(_clean_phone_number(919876543210.0), ["919876543210"])
        # String with symbols
        self.assertEqual(_clean_phone_number("+91-98765-43210"), ["919876543210"])
        # Multiple comma separated
        self.assertEqual(
            _clean_phone_number("919876543210, 919876543211"),
            ["919876543210", "919876543211"],
        )

    def test_load_sample_csv(self):
        msgs = load_sms_from_csv("sms_sample.csv")
        self.assertEqual(len(msgs), 5)
        self.assertEqual(msgs[0].send, "BAJAJF")
        self.assertTrue("OTP" in msgs[0].text)

        previews = preview_sms_rows(msgs)
        self.assertEqual(len(previews), 5)
        self.assertEqual(previews[0]["dest_count"], 1)
        self.assertEqual(previews[0]["sender_id"], "BAJAJF")


class TestSmsClient(unittest.TestCase):
    """Test SMS client sending with mocked HTTP."""

    def test_validation_empty_messages(self):
        resp = send_sms([])
        self.assertFalse(resp.success)
        self.assertEqual(resp.status_code, "-113")

    def test_validation_empty_dest(self):
        msg = SmsMessage(dest=[], text="Test", send="BAJAJF")
        resp = send_sms([msg])
        self.assertFalse(resp.success)
        self.assertEqual(resp.status_code, "-113")

    def test_validation_empty_text(self):
        msg = SmsMessage(dest=["919876543210"], text="", send="BAJAJF")
        resp = send_sms([msg])
        self.assertFalse(resp.success)
        self.assertEqual(resp.status_code, "-115")

    @patch("sms_client.requests.post")
    def test_successful_send(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ackid": "4100225541564261800",
            "time": "2026-09-08 12:00:00",
            "status": {"code": "200", "desc": "Request accepted"},
        }
        mock_post.return_value = mock_resp

        msg = SmsMessage(dest=["919876543210"], text="Hello", send="BAJAJF")
        resp = send_sms([msg], client="bajaj")

        self.assertTrue(resp.success)
        self.assertEqual(resp.ackid, "4100225541564261800")
        self.assertEqual(resp.status_code, "200")
        self.assertIsNone(resp.error_message)

    @patch("sms_client.requests.post")
    def test_api_error_response(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ackid": "N/A",
            "time": "2026-09-08 12:00:00",
            "status": {"code": "-108", "desc": "Invalid credentials"},
        }
        mock_post.return_value = mock_resp

        msg = SmsMessage(dest=["919876543210"], text="Hello", send="BAJAJF")
        resp = send_sms([msg], client="bajaj")

        self.assertFalse(resp.success)
        self.assertEqual(resp.status_code, "-108")
        self.assertEqual(resp.status_desc, "Invalid credentials")
        self.assertIn("-108", resp.error_message)

    @patch("sms_client.requests.post")
    def test_send_with_encryption(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ackid": "999888",
            "time": "2026-09-08 12:00:00",
            "status": {"code": "200", "desc": "Request accepted"},
        }
        mock_post.return_value = mock_resp

        msg = SmsMessage(dest=["919876543210"], text="Secret", send="BAJAJF")
        with patch("sms_client.get_sms_encryption_key", return_value="ODAyMjY5MDAwMDAwMDAmbUdQclNhbGU="):
            resp = send_sms([msg], client="bajaj", encrypt_pii=True)

        self.assertTrue(resp.success)
        # Check payload passed to post
        called_args, called_kwargs = mock_post.call_args
        payload = called_kwargs["json"]
        self.assertEqual(payload["encrpt"], "1")
        # Ensure dest and text in payload were encrypted
        self.assertNotEqual(payload["messages"][0]["dest"][0], "919876543210")
        self.assertNotEqual(payload["messages"][0]["text"], "Secret")


class TestSmsTracker(unittest.TestCase):
    """Test process-safe JSONL log tracker and stats aggregation."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.sub_log = os.path.join(self.tmp_dir.name, "sub.jsonl")
        self.dlr_log = os.path.join(self.tmp_dir.name, "dlr.jsonl")
        self.click_log = os.path.join(self.tmp_dir.name, "click.jsonl")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_tracker_logging_and_stats(self):
        # 1. Log submission
        sub = SmsSubmissionResult(
            client="bajaj",
            ackid="ACK12345",
            status="accepted",
            status_code="200",
            dest_count=2,
            sender_id="BAJAJF",
            message_preview="Test OTP",
        )
        log_sms_submission(sub, log_path=self.sub_log)
        subs = load_sms_submissions(self.sub_log, client="bajaj")
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["ackid"], "ACK12345")

        # 2. Log DLR
        dlr1 = SmsDlrReport(
            ackid="ACK12345",
            mid="MID001",
            dest="919876543210",
            status_flag="Success",
            reason="Delivered",
            client="bajaj",
        )
        dlr2 = SmsDlrReport(
            ackid="ACK12345",
            mid="MID002",
            dest="919876543211",
            status_flag="Failed",
            reason="Network Failed",
            client="bajaj",
        )
        log_sms_dlr(dlr1, log_path=self.dlr_log)
        log_sms_dlr(dlr2, log_path=self.dlr_log)

        # 3. Log click
        click = SmsClickReport(
            mobile_number="919876543210",
            mid="MID001",
            shorturl="2.kmbl.in/xyz",
            client="bajaj",
        )
        log_sms_click(click, log_path=self.click_log)

        # 4. Get stats
        stats = get_sms_stats(
            client="bajaj",
            submission_log_path=self.sub_log,
            dlr_log_path=self.dlr_log,
            click_log_path=self.click_log,
        )
        self.assertEqual(stats["total_submissions"], 1)
        self.assertEqual(stats["total_recipients"], 2)
        self.assertEqual(stats["delivered"], 1)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["clicks"], 1)
        self.assertEqual(stats["delivery_rate"], 50.0)


class TestSmsApiEndpoints(unittest.TestCase):
    """Test FastAPI SMS endpoints via TestClient."""

    def setUp(self):
        self.client = TestClient(app)

    @patch("api.send_sms")
    def test_send_sms_api_endpoint(self, mock_send):
        from sms_models import SmsSendResponse

        mock_send.return_value = SmsSendResponse(
            ackid="ACK98765",
            time="2026-09-08 12:00:00",
            status_code="200",
            status_desc="Request accepted",
            success=True,
            raw={"ackid": "ACK98765"},
        )

        resp = self.client.post(
            "/api/sms/send",
            json={
                "dest": ["919876543210"],
                "text": "Your code is 4321",
                "send": "BAJAJF",
                "account": "bajaj",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["ackid"], "ACK98765")
        self.assertTrue(data["success"])

    def test_dlr_webhook_plain_json(self):
        """Test Karix plain JSON DLR callback."""
        dlr_payload = {
            "acode": "bajaj_acct",
            "ackid": "ACK98765",
            "mid": "MID8888",
            "dest": "919876543210",
            "send": "BAJAJF",
            "status": "1",
            "Statusflag": "Success",
            "reason": "Delivered",
            "stime": "2026-09-08 12:00:00",
            "dtime": "2026-09-08 12:00:02",
        }
        resp = self.client.post("/api/sms/dlr", json=dlr_payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "OK")
        self.assertEqual(data["ackid"], "ACK98765")
        self.assertEqual(data["status_flag"], "Success")

    def test_dlr_webhook_encrypted_gcm(self):
        """Test Karix AES-GCM encrypted DLR callback."""
        gcm_key = "0123456789abcdef0123456789abcdef"
        gcm_iv = "123456789012"
        plain_dlr = json.dumps({
            "acode": "bajaj_acct",
            "ackid": "ACK_GCM_999",
            "mid": "MID_GCM_111",
            "dest": "919876543210",
            "send": "BAJAJF",
            "Statusflag": "Success",
            "reason": "Delivered",
        })
        cipher_b64 = encrypt_dlr_gcm(plain_dlr, gcm_key, gcm_iv)

        payload = {
            "aes_mode": "GCM",
            "key": gcm_key,
            "iv_key": gcm_iv,
            "payload": cipher_b64,
        }
        resp = self.client.post("/api/sms/dlr", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "OK")
        self.assertEqual(data["ackid"], "ACK_GCM_999")
        self.assertEqual(data["status_flag"], "Success")

    def test_click_webhook(self):
        """Test Karix SMS Click report callback."""
        click_payload = {
            "mobile_number": "919876543210",
            "mid": "MID8888",
            "clicked_date": "2026-09-08",
            "clicked_time": "12:05:00",
            "shorturl": "2.kmbl.in/test",
            "senderid": "BAJAJF",
        }
        resp = self.client.post("/api/sms/click", json=click_payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "OK")
        self.assertEqual(data["mobile_number"], "919876543210")

    def test_sample_csv_for_sms(self):
        """Test downloading sample CSV for channel=sms."""
        resp = self.client.get("/api/sample-csv?channel=sms")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp.headers.get("content-type", ""))
        self.assertIn("dest,text,send", resp.text)


if __name__ == "__main__":
    unittest.main()
