import csv

import openpyxl

from loader import load_from_csv, load_from_excel


def _component(submission, kind):
    return next(component for component in submission.components if component.type == kind)


def test_csv_without_standard_template_columns_is_loaded_dynamically(tmp_path):
    path = tmp_path / "campaign_upload.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Campaign Name", "Message Copy", "Action Link"])
        writer.writeheader()
        writer.writerow(
            {
                "Campaign Name": "Festive Personal Loan",
                "Message Copy": "Dear Customer, enjoy a special personal loan offer with easy approval.",
                "Action Link": "https://example.com/apply",
            }
        )

    submissions = load_from_csv(str(path), client="tcl_promo")

    assert len(submissions) == 1
    submission = submissions[0]
    assert submission.template_name == "festive_personal_loan"
    assert _component(submission, "BODY").text.startswith("Dear Customer")
    button = _component(submission, "BUTTONS").buttons[0]
    assert button["url"] == "https://example.com/apply"


def test_excel_without_standard_template_columns_is_loaded_dynamically(tmp_path):
    path = tmp_path / "loan_brief.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Copy ID", "Message Text"])
    sheet.append(["offer-a", "Get a pre-approved loan today. Apply online for a quick decision."])
    workbook.save(path)

    submissions = load_from_excel(str(path), client="tcl_promo")

    assert len(submissions) == 1
    submission = submissions[0]
    assert submission.template_name == "offer_a"
    assert _component(submission, "BODY").text.startswith("Get a pre-approved loan")
    assert submission.category == "MARKETING"


def test_dynamic_loader_ignores_customer_data_without_message_content(tmp_path):
    path = tmp_path / "customer_export.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Name", "Address", "Phone"])
        writer.writeheader()
        writer.writerow(
            {
                "Name": "John Doe",
                "Address": "123 Main Street, Mumbai, Maharashtra",
                "Phone": "9999999999",
            }
        )

    assert load_from_csv(str(path), client="tcl_promo") == []
