"""
Unit tests for Universal Unstructured Spreadsheet Decomposition Engine ("Arrive Anyhow" Engine).
Verifies:
1. Everything in one cell: Header, Body, Footer, and CTA are cleanly decomposed.
2. Arbitrary grid layouts: A1 has template 1, A2 has template 2, B1 has template 3, B2 has template 4.
3. Neighbor CTA extraction: CTA in adjacent right cell (B1) or bottom cell (A2) is attached to the body.
4. Multiple template copies across columns in a single row.
5. All decomposed templates arrive with clean body, footer, button, language, and category.
"""

from pathlib import Path
import openpyxl
from briefing_parser import (
    decompose_content,
    extract_templates_from_excel_file,
)


def test_everything_in_one_cell_decomposition():
    """Verify that a single cell containing Header, Body, T&C, and CTA is decomposed."""
    cell_text = (
        "Diwali Festive Loan Mela\n\n"
        "Dear Customer, get pre-approved Personal Loan of Rs. 50,000 at 8.5% interest rate from Tata Capital.\n\n"
        "👉 Apply Now: https://u3.mnge.co/offer\n\n"
        "T&C apply."
    )

    res = decompose_content(cell_text)

    # 1. Header extracted
    assert res["header_text"] == "Diwali Festive Loan Mela"

    # 2. Body stripped of CTA and T&C
    assert "👉 Apply Now:" not in res["body"]
    assert "https://u3.mnge.co/offer" not in res["body"]
    assert "T&C apply" not in res["body"]
    assert "pre-approved Personal Loan" in res["body"]

    # 3. Button populated
    assert res["button_text"] == "Apply Now"
    assert res["button_url"] == "https://u3.mnge.co/offer"

    # 4. Footer populated
    assert res["footer_text"] == "T&C apply"

    # 5. Language & Category
    assert res["language"] == "en"
    assert res["category"] == "MARKETING"


def test_unformatted_grid_of_templates(tmp_path: Path):
    """Verify arbitrary grid with no headers (A1, A2, B1, B2) extracts all templates."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Unformatted Grid"

    # A1 has template 1, A2 has template 2
    ws["A1"] = "Dear Customer, pre-approved loan of Rs. 25,000 is ready for you from Tata Capital. Apply: https://u3.mnge.co/a1"
    ws["A2"] = "Hi Customer, festive loan offer with zero processing fee is available. Apply: https://u3.mnge.co/a2"

    # B1 has template 3, B2 has template 4
    ws["B1"] = "Special Diwali business loan offer up to Rs. 10 Lakhs is live from Tata Capital. Apply: https://u3.mnge.co/b1"
    ws["B2"] = "Upgrade your dream vehicle with Tata Capital Auto Loan starting 8.75% ROI. Apply: https://u3.mnge.co/b2"

    fpath = tmp_path / "arbitrary_grid.xlsx"
    wb.save(fpath)

    items = extract_templates_from_excel_file(fpath)
    assert len(items) == 4, f"Expected 4 templates from A1, A2, B1, B2, got {len(items)}"

    bodies = [i["text"] for i in items]
    assert any("Rs. 25,000" in b for b in bodies)
    assert any("zero processing fee" in b for b in bodies)
    assert any("Rs. 10 Lakhs" in b for b in bodies)
    assert any("Auto Loan" in b for b in bodies)


def test_neighbor_cell_cta_attachment(tmp_path: Path):
    """Verify CTA in a separate adjacent cell (B1 or A2) is attached to the body in A1."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Neighbor CTA Layout"

    # Row 1: A1 has body copy, B1 has the CTA!
    ws["A1"] = "Thinking about getting more from your Loan Against Property? Switch to Tata Capital today."
    ws["B1"] = "👉 Check Your Offer: https://u3.mnge.co/lap_special"

    # Row 2: A2 has body copy, B2 has the CTA!
    ws["A2"] = "Transfer your existing loan and enjoy lower EMI and exclusive top-up funds."
    ws["B2"] = "👉 Apply Now: https://u3.mnge.co/transfer"

    fpath = tmp_path / "neighbor_cta.xlsx"
    wb.save(fpath)

    items = extract_templates_from_excel_file(fpath)
    assert len(items) == 2, f"Expected exactly 2 templates, got {len(items)}"

    item1 = next(i for i in items if "Loan Against Property" in i["text"])
    assert item1["button_text"] == "Check Your Offer"
    assert item1["button_url"] == "https://u3.mnge.co/lap_special"
    assert "https://u3.mnge.co" not in item1["text"]  # Stripped from body!

    item2 = next(i for i in items if "lower EMI" in i["text"])
    assert item2["button_text"] == "Apply Now"
    assert item2["button_url"] == "https://u3.mnge.co/transfer"
