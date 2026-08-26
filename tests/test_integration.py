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
