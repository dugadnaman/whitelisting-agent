import csv
import json
from dataclasses import asdict

import openpyxl
import pytest

from loader import load_from_csv, load_from_excel, load_from_json, load_from_list


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
    assert button["url"] == "https://example.com/apply{{1}}"
    assert button["example"] == ["https://example.com/applysample"]


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


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
@pytest.mark.parametrize("schema", ["flat", "semantic", "components"])
@pytest.mark.parametrize("variable", ["", "{{1}}", "{{offer}}", "<offer>", "[offer]", "{offer}", "{#offer#}", "#offer#"])
def test_sheet_url_ctas_are_dynamic_with_samples_and_reimport_is_idempotent(tmp_path, extension, schema, variable):
    url = f"https://example.test/offers/{variable}"
    sample = "https://example.test/offers/customer-offer"
    body = "Your monthly statement is ready for review."
    if schema == "semantic":
        row = {
            "Campaign Name": "monthly_statement", "Message Copy": body,
            "Action Link": url, "Action Label": "View", "button_url_example": sample,
        }
    elif schema == "flat":
        row = {
            "template_name": "monthly_statement", "body": body,
            "button_text": "View", "button_url": url, "button_url_example": sample,
        }
    else:
        row = {
            "template_name": "monthly_statement",
            "components": json.dumps([
                {"type": "BODY", "text": body},
                {"type": "BUTTONS", "buttons": [
                    {"type": "URL", "text": "View", "url": url, "example": [sample]},
                    {"type": "QUICK_REPLY", "text": "Not now"},
                    {"type": "PHONE_NUMBER", "text": "Call", "phone_number": "+911234567890"},
                ]},
            ]),
        }
    path = tmp_path / f"campaign.{extension}"
    if extension == "csv":
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
        submissions = load_from_csv(str(path), client="tcl_promo")
    else:
        workbook = openpyxl.Workbook()
        workbook.active.append(list(row))
        workbook.active.append(list(row.values()))
        workbook.save(path)
        workbook.close()
        submissions = load_from_excel(str(path), client="tcl_promo")

    assert len(submissions) == 1
    submission = submissions[0]
    buttons = _component(submission, "BUTTONS").buttons
    assert buttons[0] == {
        "type": "URL", "text": "View", "url": "https://example.test/offers/{{1}}",
        "example": [sample if variable else "https://example.test/offers/sample"],
    }
    if schema == "components":
        assert buttons[1:] == [
            {"type": "QUICK_REPLY", "text": "Not now"},
            {"type": "PHONE_NUMBER", "text": "Call", "phone_number": "+911234567890"},
        ]
    reimported = load_from_list([asdict(submission)], client="tcl_promo")[0]
    assert asdict(reimported) == asdict(submission)


@pytest.mark.parametrize("source", ["json", "list"])
def test_component_import_makes_only_url_buttons_dynamic(tmp_path, source):
    rows = [{
        "template_name": "component_campaign",
        "components": [
            {"type": "BODY", "text": "Your monthly statement is ready."},
            {"type": "BUTTONS", "buttons": [
                {"type": "URL", "text": "View", "url": " https://example.test/statement "},
                {"type": "QUICK_REPLY", "text": "Not now"},
            ]},
        ],
    }, {
        "template_name": "body_only",
        "components": [{"type": "BODY", "text": "Your monthly statement is ready."}],
    }]
    if source == "json":
        path = tmp_path / "campaign.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        submissions = load_from_json(str(path))
    else:
        submissions = load_from_list(rows)
    buttons = _component(submissions[0], "BUTTONS").buttons
    assert buttons == [
        {"type": "URL", "text": "View", "url": "https://example.test/statement{{1}}", "example": ["https://example.test/statementsample"]},
        {"type": "QUICK_REPLY", "text": "Not now"},
    ]
    assert [component.type for component in submissions[1].components] == ["BODY"]


def test_bare_host_cta_keeps_the_hostname_static():
    submission = load_from_list([{
        "template_name": "homepage_offer",
        "components": [
            {"type": "BODY", "text": "Your offer is ready."},
            {"type": "BUTTONS", "buttons": [
                {"type": "URL", "text": "View", "url": "https://example.test"},
            ]},
        ],
    }])[0]
    assert _component(submission, "BUTTONS").buttons == [{
        "type": "URL", "text": "View", "url": "https://example.test/{{1}}",
        "example": ["https://example.test/sample"],
    }]
