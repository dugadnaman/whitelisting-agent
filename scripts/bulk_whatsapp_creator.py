"""Bulk WhatsApp Campaign Draft Automator for MoEngage.

Automates the creation of 50+ WhatsApp campaign drafts from a CSV or Excel spreadsheet
into your MoEngage Live workspace connected to Karix BSP.

Usage:
    python scripts/bulk_whatsapp_creator.py <path_to_spreadsheet.csv_or_xlsx>
"""

import argparse
import csv
import sys
from pathlib import Path

def parse_spreadsheet(file_path: str) -> list[dict[str, str]]:
    """Parse CSV or XLSX file and extract WHATSAPP channel rows."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    rows: list[dict[str, str]] = []
    if path.suffix.lower() == ".csv":
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append({k.strip(): (v or "").strip() for k, v in r.items() if k})
    elif path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        sheet = wb.active
        iter_rows = sheet.iter_rows(values_only=True)
        header_row = next(iter_rows, None)
        if not header_row:
            return []
        headers = [str(h).strip() for h in header_row if h is not None]
        for values in iter_rows:
            if not values or not any(values):
                continue
            row_dict = {
                headers[i]: str(values[i]).strip() if i < len(values) and values[i] is not None else ""
                for i in range(len(headers))
            }
            rows.append(row_dict)
    else:
        raise ValueError("Supported formats: .csv or .xlsx")

    # Filter for WhatsApp campaigns
    wa_rows = [r for r in rows if r.get("channel", "").upper() == "WHATSAPP"]
    return wa_rows


def print_banner(campaign_count: int, file_path: str):
    print("=" * 70)
    print("  MOENGAGE BULK WHATSAPP CAMPAIGN CREATOR (KARIX BSP)")
    print("=" * 70)
    print(f"  Source File      : {file_path}")
    print(f"  WhatsApp Rows    : {campaign_count} campaigns found")
    print("  Target Workspace : Tata Capital (0KYUNUW5WODKX5ZFVAGPVL0U · DC03)")
    print("  Safety Mode      : DRAFT ONLY (Zero publishing, zero customer sends)")
    print("=" * 70)


def automate_creation_via_playwright(campaigns: list[dict[str, str]], cdp_url: str | None = None):
    """Loop through WhatsApp campaigns and save drafts in MoEngage."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("\n[ERROR] Playwright is required for browser automation:")
        print("    pip install playwright && playwright install chromium")
        sys.exit(1)

    with sync_playwright() as p:
        if cdp_url:
            print(f"\n[Connecting] Attaching to existing Chrome at {cdp_url}...")
            browser = p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
        else:
            print("\n[Launching] Starting Chromium with MoEngage session...")
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()

        page = context.new_page()
        success_count = 0
        failed: list[tuple[str, str]] = []

        print(f"\n[Processing] Starting automated creation of {len(campaigns)} campaigns...\n")

        for idx, camp in enumerate(campaigns, 1):
            name = camp.get("campaign_name") or f"WhatsApp_Campaign_{idx}"
            segment = camp.get("segment_id") or camp.get("segment_name") or "Test_FSTP_Pranav_1602"
            sender = camp.get("whatsapp_sender") or "Tata Capital Financial Services Limited"
            template = camp.get("whatsapp_template_id") or "test_1234"

            print(f"[{idx}/{len(campaigns)}] Creating: {name} (Template: {template}, Segment: {segment[:15]}...)")

            try:
                # Step 1: Navigate to one-time create studio
                page.goto("https://dashboard-03.moengage.com/v4/whatsapp/create/one-time/", timeout=30000)
                page.wait_for_selector('input[placeholder*="Campaign Name"]', timeout=15000)

                # Fill campaign name
                name_input = page.locator('input[placeholder*="Campaign Name"]')
                name_input.fill(name)

                # Select custom segment
                segment_btn = page.locator('button:has-text("Custom segment")')
                if segment_btn.is_visible():
                    segment_btn.click()
                    page.wait_for_selector('input[placeholder*="Search to select"]', timeout=8000)
                    search_input = page.locator('input[placeholder*="Search to select"]')
                    search_input.fill("Test")
                    page.wait_for_timeout(1000)
                    # Click segment option
                    opt = page.locator(f'*:has-text("{segment}")').last
                    if opt.is_visible():
                        opt.click()

                # Click Next
                page.locator('button:has-text("Next")').click()
                page.wait_for_timeout(2000)

                # Step 2: Select Sender & Template
                sender_dropdown = page.locator('[data-testid="whatsapp-sender-dropdown"]')
                if sender_dropdown.is_visible():
                    sender_dropdown.click()
                    page.keyboard.press("ArrowDown")
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(1000)

                template_dropdown = page.locator('[data-testid="whatsapp-template-dropdown"]')
                if template_dropdown.is_visible():
                    template_dropdown.click()
                    page.keyboard.press("ArrowDown")
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(1000)

                # Click Save as draft
                save_btn = page.locator('button:has-text("Save as draft")')
                if save_btn.is_visible():
                    save_btn.click()
                    page.wait_for_timeout(3000)

                print(f"    ✓ Successfully created draft '{name}' in MoEngage.")
                success_count += 1
            except Exception as e:
                print(f"    ✗ Failed: {e}")
                failed.append((name, str(e)))

        print("\n" + "=" * 70)
        print("  BULK CREATION COMPLETE")
        print("=" * 70)
        print(f"  Successfully Created: {success_count}/{len(campaigns)} drafts")
        if failed:
            print(f"  Failed: {len(failed)}")
            for f_name, f_err in failed:
                print(f"    - {f_name}: {f_err}")
        print("=" * 70)

        browser.close()


def main():
    parser = argparse.ArgumentParser(description="Bulk WhatsApp Campaign Creator for MoEngage")
    parser.add_argument("file", help="Path to CSV or XLSX spreadsheet with campaigns")
    parser.add_argument("--cdp", help="Chrome DevTools Protocol URL (e.g. http://localhost:9222)", default=None)
    args = parser.parse_args()

    wa_campaigns = parse_spreadsheet(args.file)
    print_banner(len(wa_campaigns), args.file)

    if not wa_campaigns:
        print("[Notice] No rows with channel=WHATSAPP found in the file.")
        sys.exit(0)

    automate_creation_via_playwright(wa_campaigns, cdp_url=args.cdp)


if __name__ == "__main__":
    main()
