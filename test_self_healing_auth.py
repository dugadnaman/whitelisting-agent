"""
Tests for Self-Healing Auth and Browser Automation Tooling.
Verifies token persistence, agent tool dispatch, 401 recovery flow, and API endpoints.
"""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import api
from agent import agent_instance
from auth_refresher import refresh_karix_session, update_persisted_credentials
from loader import _row_to_submission
from models import SubmissionStatus
from submission_client import submit_template


class TestSelfHealingAuth(unittest.TestCase):
    def test_update_persisted_credentials(self):
        """Verify update_persisted_credentials safely writes to credentials.json and os.environ."""
        fake_tokens = {
            "bearer_token": "test_bearer_token_1234567890",
            "session": "test_session_abc",
            "user": "TestOperator",
        }

        update_persisted_credentials(account="bajaj", tokens=fake_tokens)

        # Check os.environ
        self.assertEqual(os.environ.get("BAJAJ_KARIX_BEARER_TOKEN"), "test_bearer_token_1234567890")
        self.assertEqual(os.environ.get("BAJAJ_KARIX_SESSION"), "test_session_abc")
        self.assertEqual(os.environ.get("BAJAJ_KARIX_USER"), "TestOperator")

        # Check credentials.json
        cred_path = Path("credentials.json")
        if cred_path.exists():
            data = json.loads(cred_path.read_text(encoding="utf-8"))
            self.assertEqual(data.get("BAJAJ_KARIX_BEARER_TOKEN"), "test_bearer_token_1234567890")
            self.assertEqual(data.get("BAJAJ_KARIX_SESSION"), "test_session_abc")

    def test_refresh_missing_credentials_returns_clean_error(self):
        """When no portal credentials are set for an account, returns clean requires_credentials diagnostic."""
        res = refresh_karix_session(account="custom_tenant", username=None, password=None)
        self.assertFalse(res["success"])
        self.assertTrue(res.get("requires_credentials"))
        self.assertIn("No portal username/password found", res.get("error", ""))

    def test_agent_session_refresh_intent(self):
        """Verify that natural language commands to the agent trigger the session refresh tool."""
        res = agent_instance.execute_instruction("Refresh session for bajaj", account="bajaj", channel="whatsapp")
        self.assertIn("reply", res)
        self.assertTrue(any(a.get("tool") == "refresh_karix_session" for a in res.get("actions_taken", [])))

    def test_api_auth_refresh_endpoint(self):
        """Verify POST /api/auth/refresh endpoint behavior."""
        client = TestClient(api.app)
        # Testing with missing credentials returns 400 with helpful message
        r = client.post("/api/auth/refresh", json={"account": "unknown_acc"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("No portal username/password found", r.json().get("detail", ""))

    @patch("submission_client.get_http_session")
    @patch("auth_refresher.refresh_karix_session")
    def test_401_triggers_self_healing_retry(self, mock_refresh, mock_get_session):
        """Verify that when Karix returns 401, submission_client calls refresh_karix_session and retries."""
        mock_refresh.return_value = {
            "success": True,
            "message": "Harvested fresh session",
        }

        # Mock first response as 401, second response as 200
        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.ok = False
        resp_401.text = "Unauthorized"
        resp_401.json.return_value = {"error": "Token expired"}
        resp_201 = MagicMock()
        resp_201.status_code = 201
        resp_201.ok = True
        resp_201.json.return_value = {"templateId": "999999"}

        mock_session_obj = MagicMock()
        mock_session_obj.post.side_effect = [resp_401, resp_201]
        mock_get_session.return_value = mock_session_obj

        sub = _row_to_submission(
            {
                "source_ref": "test_401_heal",
                "template_name": "test_auto_heal",
                "category": "UTILITY",
                "language": "en",
                "header_type": "IMAGE",
                "header_media_url": "https://example.com/banner.png",
                "body": "Hello {{1}}",
                "client": "bajaj",
            },
            client="bajaj",
        )

        with (
            patch("submission_client.get_portal_auth_headers") as mock_headers,
            patch("submission_client._resolve_header_media", return_value=[]),
            patch("submission_client._resolve_body_variables", return_value=[]),
        ):
            mock_headers.return_value = {
                "Authorization": "Bearer fresh_token",
                "Session": "fresh_sess",
                "User": "Op",
            }
            res = submit_template(sub, client="bajaj")

        # Verify refresh was triggered
        mock_refresh.assert_called_once()
        self.assertEqual(res.status, SubmissionStatus.SUBMITTED)


if __name__ == "__main__":
    unittest.main()
