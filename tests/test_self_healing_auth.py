"""
Tests for credential handling after Playwright removal.

The Karix portal requires an OTP, so browser auto-login is gone. These tests
verify the replacement contract:
- 401 responses produce an actionable "session expired" failure (no retry loop)
- missing credentials fail fast with the exact missing key named
- saving one-time settings persists encrypted per account, without env/files/Git writes
"""

import contextlib
import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import api
import auth
from loader import _row_to_submission
from models import ApprovalStatus, SubmissionStatus, TemplateSubmission
from submission_client import submit_template


class TestCredentialContract(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=False))
        # Ensure a clean slate for the account under test
        for k in list(os.environ):
            if k.startswith("TCHFL_"):
                del os.environ[k]

    def test_401_returns_actionable_error_without_retry(self):
        """A 401 from the portal API fails the template with a clear message — no browser, no retry."""
        submission = TemplateSubmission(
            client="tchfl",
            channel="whatsapp",
            template_name="t_401_test",
            language="en",
            category="MARKETING",
            waba_id="734197179371393",
            components=[],
            source_ref="test",
        )

        class FakeResponse:
            status_code = 401
            ok = False
            text = '{"detail":"unauthorized"}'

            def json(self):
                return {"detail": "unauthorized"}

        fake_session = MagicMock()
        fake_session.post.return_value = FakeResponse()
        with (
            patch("submission_client.get_portal_auth_headers") as mock_headers,
            patch("submission_client.get_http_session", return_value=fake_session),
        ):
            mock_headers.return_value = {"Authorization": "Bearer x", "Session": "s", "User": "u"}
            res = submit_template(submission, client="tchfl")

        self.assertEqual(res.status, SubmissionStatus.FAILED)
        self.assertIn("Session expired (401)", res.error)
        self.assertIn("Settings", res.error)
        # Exactly ONE HTTP call — no retry loop on 401
        self.assertEqual(fake_session.post.call_count, 1)

    def test_missing_credentials_fail_fast(self):
        """Missing portal credentials raise OSError naming the exact env keys."""
        from config import get_portal_auth_headers

        with patch("config._load_env_file"), patch.dict(os.environ, {}, clear=False):
            for k in list(os.environ):
                if k.startswith("TCHFL_"):
                    del os.environ[k]
            with self.assertRaises(OSError) as ctx:
                get_portal_auth_headers("tchfl")
        self.assertIn("TCHFL_KARIX_BEARER_TOKEN", str(ctx.exception))
        self.assertIn("Settings", str(ctx.exception))

    def test_update_credentials_persists_encrypted_per_account(self):
        """Static API credentials survive database reload without a plaintext export."""
        from fastapi.testclient import TestClient
        from config import get_official_auth_headers
        from portal_sessions import load_settings
        import db

        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(contextlib.chdir(directory))
        self.enterContext(patch("db.DEFAULT_SQLITE_PATH", Path(directory) / "auth.db"))
        self.enterContext(patch("db.get_database_url", return_value=""))
        self.enterContext(patch.dict(os.environ, {"JWT_SECRET": "0123456789abcdefFEDCBA9876543210" * 2}))
        self.enterContext(patch("api.QUEUE_MANAGER.notify_credentials_updated"))
        auth.init_auth_db()
        user = auth.register_user("cred-contract@example.com", "Credential-password-123", "Company Admin", "tata", "admin")
        client = self.enterContext(TestClient(api.app))
        login = client.post("/api/auth/login", json={"email": user["email"], "password": "Credential-password-123"})
        self.assertEqual(login.status_code, 200)
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        response = client.put("/api/credentials", headers=headers, json={
            "account": "tchfl", "channel": "whatsapp", "waba_auth_token": "one-time-tchfl-key",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["storage"], "encrypted_database")
        self.assertEqual(load_settings("tchfl", "whatsapp")["TCHFL_WABA_AUTH_TOKEN"], "one-time-tchfl-key")
        self.assertEqual(load_settings("tcl_promo", "whatsapp"), {})
        self.assertEqual(get_official_auth_headers("tchfl"), {"Authentication": "Bearer one-time-tchfl-key"})
        with db.get_db() as conn:
            encrypted = conn.execute(
                "SELECT encrypted_credentials FROM karix_scoped_credentials WHERE account = 'tchfl' AND kind = 'settings'"
            ).fetchone()[0]
        self.assertNotIn("one-time-tchfl-key", encrypted)
        self.assertNotIn("TCHFL_WABA_AUTH_TOKEN", os.environ)
        self.assertFalse(Path("credentials.json").exists())
        self.assertFalse(Path(".env").exists())



if __name__ == "__main__":
    unittest.main()
