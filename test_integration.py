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
    if approval_status == ApprovalStatus.UNKNOWN:
        print("✗ FAIL: Got UNKNOWN — likely an auth/transport error.")
        print(f"  Raw response: {json.dumps(raw, indent=2, default=str)[:1000]}")
        return False

    if raw.get("template_name") != KNOWN_TEMPLATE_NAME:
        print(f"✗ FAIL: Expected template_name={KNOWN_TEMPLATE_NAME!r}, "
              f"got {raw.get('template_name')!r}")
        return False

    print(f"✓ check_status returned: {approval_status.value}")
    print(f"✓ Template name: {raw.get('template_name')}")
    print(f"✓ Status reason: {reason}")
    return True


def test_list_all_templates():
    """
    Bonus: dump a summary of all templates returned by getAllTemplates,
    so you can see what's on the account.
    """
    import requests
    from config import BAJAJ_WABA_ID, OFFICIAL_TEMPLATE_BASE_URL, get_official_auth_headers

    print("\n--- Listing all templates (summary via Official API) ---\n")

    try:
        headers = get_official_auth_headers()
        resp = requests.get(
            f"{OFFICIAL_TEMPLATE_BASE_URL}/{BAJAJ_WABA_ID}",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"✗ Failed to list templates: {e}")
        return False

    templates = data.get("response", {}).get("templates", [])

    print(f"  Total templates: {len(templates)}\n")
    for t in templates[:20]:  # Show first 20
        print(f"  sno={t.get('sno')}  fb_id={t.get('fb_template_id')}  name={t.get('template_name')!r:30s}  "
              f"status={t.get('template_create_status')}")

    if len(templates) > 20:
        print(f"  ... and {len(templates) - 20} more")

    print()
    return True


if __name__ == "__main__":
    # Check credentials are set
    if not os.environ.get("WABA_AUTH_TOKEN"):
        print("✗ Missing environment variable: WABA_AUTH_TOKEN")
        print("  Set it in .env or your environment with your official Karix API token.")
        sys.exit(1)

    ok = True
    ok = test_check_status() and ok
    ok = test_list_all_templates() and ok

    print()
    if ok:
        print("=== ALL TESTS PASSED ===")
    else:
        print("=== SOME TESTS FAILED ===")
        sys.exit(1)
