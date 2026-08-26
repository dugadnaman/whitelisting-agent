"""
Tests for credential handling after Playwright removal.

The Karix portal requires an OTP, so browser auto-login is gone. These tests
verify the replacement contract:
- 401 responses produce an actionable "session expired" failure (no retry loop)
- missing credentials fail fast with the exact missing key named
- saving credentials via the API persists to disk and reports GitHub status
"""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import api
from loader import _row_to_submission
from models import ApprovalStatus, SubmissionStatus, TemplateSubmission
from submission_client import submit_template


class TestCredentialContract(unittest.TestCase):
    def setUp(self):
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
        with patch("submission_client.get_portal_auth_headers") as mock_headers, patch(
            "submission_client.get_http_session", return_value=fake_session
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

    def test_update_credentials_persists_and_reports_github_status(self):
        """PUT /api/credentials writes credentials.json and returns github_persisted status."""
        import os

        os.environ.setdefault("ALLOWED_ORIGINS", "")
        from fastapi.testclient import TestClient

        client = TestClient(api.app)

        # Snapshot pre-existing values so the test restores them exactly —
        # never delete real operator credentials.
        saved_env = {
            k: os.environ.get(k)
            for k in ("TCHFL_KARIX_BEARER_TOKEN", "TCHFL_KARIX_SESSION", "TCHFL_KARIX_USER")
        }
        creds_path = Path("credentials.json")
        saved_file = creds_path.read_text(encoding="utf-8") if creds_path.exists() else None

        email = "cred_contract@attributics.com"
        client.post(
            "/api/auth/signup",
            json={"email": email, "password": "Test@123", "full_name": "CC", "tenant": "tata"},
        )
        r = client.post("/api/auth/login", json={"email": email, "password": "Test@123"})
        token = r.json().get("token") or r.json().get("access_token")
        H = {"Authorization": f"Bearer {token}"}

        r = client.put(
            "/api/credentials",
            json={
                "account": "tchfl",
                "channel": "whatsapp",
                "bearer_token": "cc_bearer_123",
                "session": "cc_session_456",
                "user": "CCUser",
            },
            headers=H,
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        # GITHUB_TOKEN not set in tests → skipped, not failed
        self.assertIn(body.get("github_persisted"), (None, "committed"))

        # Persisted to disk under the account's own prefix
        creds = json.loads(creds_path.read_text(encoding="utf-8"))
        self.assertEqual(creds.get("TCHFL_KARIX_BEARER_TOKEN"), "cc_bearer_123")
        self.assertEqual(creds.get("TCHFL_KARIX_SESSION"), "cc_session_456")

        # And readable back through the config layer (strict isolation)
        from config import get_portal_auth_headers

        h = get_portal_auth_headers("tchfl")
        self.assertEqual(h["Authorization"], "Bearer cc_bearer_123")
        self.assertEqual(h["Session"], "cc_session_456")

        # cleanup: restore prior state exactly (values OR absence)
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if saved_file is None:
            creds_path.unlink(missing_ok=True)
        else:
            creds_path.write_text(saved_file, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
