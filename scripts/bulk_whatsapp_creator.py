"""Create WhatsApp drafts through the authenticated, verified campaign queue.

Set KARIX_AUTH_TOKEN to a signed-in operator's JWT, then run:
    python scripts/bulk_whatsapp_creator.py campaigns.csv --account tata --api-url https://your-app

The server owns workspace selection, exact sender/template resolution and durable
claims. This CLI never drives Chrome or reports unverified drafts as created.
"""

import argparse
import csv
import os
import sys
from pathlib import Path

import requests


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


def main():
    parser = argparse.ArgumentParser(description="Verified WhatsApp draft batch creator")
    parser.add_argument("file", help="CSV or XLSX spreadsheet with campaigns")
    parser.add_argument("--account", choices=("tata", "bajaj"), required=True)
    parser.add_argument("--api-url", required=True, help="Whitelisting app origin (not the MoEngage portal)")
    args = parser.parse_args()
    token = os.environ.get("KARIX_AUTH_TOKEN", "").strip()
    if not token:
        parser.error("Set KARIX_AUTH_TOKEN to your signed-in operator JWT")
    campaigns = parse_spreadsheet(args.file)
    if not campaigns:
        print("No WhatsApp rows found; no drafts created.")
        return
    headers = {"Authorization": f"Bearer {token}"}
    base_url = args.api_url.rstrip("/")
    with open(args.file, "rb") as source:
        staged = requests.post(
            f"{base_url}/api/moengage/drafts/batches", headers=headers,
            data={"account": args.account}, files={"file": (Path(args.file).name, source)}, timeout=60,
        )
    staged.raise_for_status()
    batch = staged.json()
    print(f"Batch {batch['batch_id']} staged for {args.account}; {batch['blocked']} blocked rows.")
    result = requests.post(
        f"{base_url}/api/moengage/drafts/batches/{batch['batch_id']}/automate-whatsapp",
        headers=headers, data={"account": args.account}, timeout=3600,
    )
    result.raise_for_status()
    outcome = result.json()
    print(f"Read-back verified: {outcome['created']}; not verified: {outcome['failed']}.")
    for row in outcome["results"]:
        print(f"Row {row['row_id']}: {row['status']} — {row.get('id') or row.get('error') or 'inspect batch'}")
    if outcome["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
