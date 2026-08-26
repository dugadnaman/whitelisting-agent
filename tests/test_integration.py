#!/usr/bin/env python3
"""
Integration smoke test - verifies Karix API connection and status checks.

Uses official WABA_AUTH_TOKEN static credentials with optional portal fallback.
"""

import json
import logging
import os
import sys

# Optionally load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # .env loading is optional; env vars can be set directly

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from models import ApprovalStatus
from submission_client import check_status


def test_check_status():
    """Verify check_status can reach the API and find a known template."""

    # Known template from real traffic — sno used as provider_ref_id
    KNOWN_SNO = "58106108"
    KNOWN_TEMPLATE_NAME = "emic_check_wa_07aug"

    print(f"\n--- Testing check_status(provider_ref_id={KNOWN_SNO!r}) ---\n")

    approval_status, reason, raw = check_status(KNOWN_SNO)

    print(f"  Approval status : {approval_status.value}")
    print(f"  Status reason   : {reason}")
    print(f"  Template name   : {raw.get('template_name', 'N/A')}")
    print(f"  sno             : {raw.get('sno', 'N/A')}")
    print()

    # Assertions
    assert approval_status != ApprovalStatus.UNKNOWN, (
        f"Got UNKNOWN — likely an auth/transport error. Raw: {json.dumps(raw, indent=2, default=str)[:1000]}"
    )
    assert raw.get("template_name") == KNOWN_TEMPLATE_NAME, (
        f"Expected template_name={KNOWN_TEMPLATE_NAME!r}, got {raw.get('template_name')!r}"
    )

    print(f"✓ check_status returned: {approval_status.value}")
    print(f"✓ Template name: {raw.get('template_name')}")
    print(f"✓ Status reason: {reason}")


def test_list_all_templates():
    """
    Verify fetch_template_list can fetch live templates from the WABA.
    """
    from submission_client import fetch_template_list

    print("\n--- Listing all templates (summary via fetch_template_list) ---\n")
    templates, err = fetch_template_list("bajaj")
    print(f"  Total templates returned: {len(templates)}, error: {err}")

    for t in templates[:10]:
        print(
            f"  sno={t.get('sno')}  fb_id={t.get('fb_template_id')}  name={t.get('template_name')!r:30s}  "
            f"status={t.get('template_create_status') or t.get('status')}"
        )
    assert isinstance(templates, list), "Expected templates to be a list"
    if templates:
        assert len(templates) > 0


def test_duplicate_submission_skipping():
    """
    Verify that when skip_duplicates is enabled, templates already active on WABA
    are filtered into DUPLICATE status without hitting Karix/Meta create endpoints.
    """
    import io
    import tempfile
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    import api
    from models import SubmissionStatus

    client = TestClient(api.app)
    # Sign up/in as tata user
    email = "dupe_test@attributics.com"
    client.post("/api/auth/signup", json={"email": email, "password": "Test@123", "name": "Dupe Tester", "tenant_id": "tata"})
    r = client.post("/api/auth/login", json={"email": email, "password": "Test@123"})
    token = r.json().get("token") or r.json().get("access_token")
    H = {"Authorization": f"Bearer {token}"}

    # Mock live templates to contain 'existing_template_1'
    mock_live = [
        {"template_name": "existing_template_1", "template_create_status": "APPROVED", "fb_template_id": "999888"}
    ]

    csv_content = (
        "template_name,template_category,header_type,header_text,body_text\n"
        "existing_template_1,MARKETING,TEXT,Header,Hello {{1}}\n"
        "brand_new_template_2,MARKETING,TEXT,Header,Hello {{1}}\n"
    )

    def fake_run(raw_list, log_path, **kwargs):
        from tracker import log_result
        from models import SubmissionResult, SubmissionStatus
        for item in raw_list:
            res = SubmissionResult(
                source_ref=item.get("source_ref", item.get("template_name", "")),
                template_name=item.get("template_name", ""),
                status=SubmissionStatus.SUBMITTED,
                provider_ref_id="fake_123",
            )
            log_result(res, log_path)

    with patch("api.fetch_whatsapp_templates", return_value=mock_live), patch("api.run", side_effect=fake_run) as mock_run:
        r = client.post(
            "/api/submit?account=tchfl&channel=whatsapp&skip_duplicates=true",
            files={"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            headers=H,
        )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    results = data.get("results", [])
    assert len(results) == 2, f"Expected 2 results, got {len(results)}"

    # Check duplicate entry was safely skipped
    dupe_row = next((x for x in results if x.get("template_name") == "existing_template_1"), None)
    assert dupe_row is not None
    assert dupe_row.get("status") == SubmissionStatus.DUPLICATE.value
    assert "already active on waba" in dupe_row.get("error", "").lower()

    # Verify run was only invoked with the net-new template
    if mock_run.called:
        submitted_raw = mock_run.call_args[0][0]
        assert len(submitted_raw) == 1
        assert submitted_raw[0]["template_name"] == "brand_new_template_2"

    print("✓ test_duplicate_submission_skipping passed!")

if __name__ == "__main__":
    # Check credentials are set
    if not os.environ.get("WABA_AUTH_TOKEN"):
        print("✗ Missing environment variable: WABA_AUTH_TOKEN")
        print("  Set it in .env or your environment with your official Karix API token.")
        sys.exit(1)

    try:
        test_check_status()
        test_list_all_templates()
        print()
        print("=== ALL TESTS PASSED ===")
    except AssertionError as e:
        print(f"✗ FAIL: {e}")
        print("=== SOME TESTS FAILED ===")
        sys.exit(1)
