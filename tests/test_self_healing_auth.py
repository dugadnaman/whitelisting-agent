"""
Tests for credential handling after Playwright removal.

The Karix portal requires an OTP, so browser auto-login is gone. These tests
verify the replacement contract:
- 401 responses fail without replaying creation
- missing credentials fail before contacting the provider
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from models import SubmissionStatus, TemplateSubmission
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




if __name__ == "__main__":
    unittest.main()
