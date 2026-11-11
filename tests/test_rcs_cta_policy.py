"""Account-isolated RCS destinations at import and serialization boundaries."""
import copy
import csv
import json
from dataclasses import replace

import openpyxl
import pytest

import rcs_client
import rcs_loader
from rcs_models import RcsTemplateSubmission


TATA_ACCOUNTS = ("tata", "tcl_promo", "tcl_trans", "tchfl", "wealth", "moneyfy")
ACCOUNTS = (*TATA_ACCOUNTS, "bajaj", "apparel")


@pytest.fixture(autouse=True)
def isolated_accounts(monkeypatch):
    for module in (rcs_loader, rcs_client):
        monkeypatch.setattr(module, "get_rcs_bot_id", lambda client: f"bot-{client}")
        monkeypatch.setattr(module, "get_rcs_esmeaddr", lambda client: "123456")
    monkeypatch.setattr(rcs_loader, "get_rcs_entity_id", lambda client: "")


@pytest.mark.parametrize("client", ACCOUNTS)
@pytest.mark.parametrize("source", ("csv", "excel", "json"))
@pytest.mark.parametrize("destination", (
    "https://loans.tatacapital.com/personal-loan?source=brief&id=",
    "https://teams.microsoft.com/l/meetup-join/meeting?id=",
    "https://example.test/offer?id=",
))
def test_import_and_direct_payload_share_destination_and_parameter_numbers(tmp_path, client, source, destination):
    actions = [
        {"suggestionType": "url_action", "text": "Open", "postbackData": "open-offer",
         "url": "https://u3.mnge.co/redirect?a={{tracking}}&b=[tail]"},
        {"suggestionType": "url_action", "text": "Apply", "postbackData": "apply-offer",
         "url": destination + "<loan>"},
        {"suggestionType": "reply", "text": "Confirm", "postbackData": "confirm-offer",
         "url": "https://u3.mnge.co/not-an-action"},
        {"suggestionType": "dialer_action", "text": "Call", "postbackData": "call-offer",
         "phoneNumber": "+919999999999", "url": "https://u3.mnge.co/not-a-link"},
    ]
    row = {
        "template_name": "account_cta_policy", "template_type": "richcard",
        "card_title": "Hello [name]", "body": "Offer #offer# https://u3.mnge.co/body",
        "media_url": "https://cdn.example.test/banner.png", "suggestions": json.dumps(actions),
    }
    if source == "csv":
        path = tmp_path / "templates.csv"
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
        submission = rcs_loader.load_rcs_from_csv(str(path), client=client)[0]
    elif source == "excel":
        path = tmp_path / "templates.xlsx"
        workbook = openpyxl.Workbook()
        workbook.active.append(list(row))
        workbook.active.append(list(row.values()))
        workbook.save(path)
        workbook.close()
        submission = rcs_loader.load_rcs_from_excel(str(path), client=client, upload_media=False)[0]
    else:
        submission = rcs_loader.load_rcs_from_list(json.loads(json.dumps([row])), client=client)[0]

    expected_prefix = "https://www.tatacapital.com/" if client in TATA_ACCOUNTS else "https://u3.mnge.co/redirect?a="
    expected_preview = (
        expected_prefix + "{{tracking}}[tail]" if client in TATA_ACCOUNTS
        else expected_prefix + "{{tracking}}&b=[tail]"
    )
    assert submission.suggestions[0]["url"] == expected_preview
    assert submission.suggestions[1:] == actions[1:]
    assert submission.card_description == row["body"]
    assert submission.media_url == row["media_url"]

    serialized = rcs_client._build_rcs_save_payload(submission, client=client)
    direct = replace(submission, suggestions=copy.deepcopy(actions))
    assert rcs_client._build_rcs_save_payload(direct, client=client) == serialized
    assert direct.suggestions == actions
    card = serialized["viTemplate"]["standaloneCard"]
    expected_url = (
        "https://www.tatacapital.com/[3][4]" if client in TATA_ACCOUNTS
        else "https://u3.mnge.co/redirect?a=[3]&b=[4]"
    )
    assert card["suggestions"][0]["url"] == expected_url
    assert card["suggestions"][1]["url"] == destination + "[5]"
    assert card["suggestions"][2] == {"suggestionType": "reply", "text": "Confirm", "postbackData": "confirm-offer"}
    assert card["suggestions"][3] == {
        "suggestionType": "dialer_action", "text": "Call", "postbackData": "call-offer", "phoneNumber": "+919999999999",
    }
    assert card["cardDescription"] == "Offer [2] https://u3.mnge.co/body"
    assert card["mediaUrl"] == row["media_url"]
    assert serialized["templateParamNames"] == ["1", "2", "3", "4", "5"]
    assert serialized["templatePlaceHolderCount"] == 5


@pytest.mark.parametrize("url", ("", "{{destination}}"))
@pytest.mark.parametrize("client", TATA_ACCOUNTS)
def test_explicit_blank_or_placeholder_tata_url_uses_default_without_extra_parameter(url, client):
    submission = RcsTemplateSubmission(
        template_name="default_destination", client=client, text_message="Dear [name]",
        suggestions=[{"suggestionType": "url_action", "text": "Open", "url": url}],
    )
    loaded = rcs_loader.load_rcs_from_list([{
        "template_name": "default_destination", "body": "Dear [name]", "suggestions": submission.suggestions,
    }], client=client)[0]
    result = rcs_client._build_rcs_save_payload(submission, client=client)
    assert rcs_client._build_rcs_save_payload(loaded, client=client) == result
    assert result["viTemplate"]["suggestions"][0]["url"] == "https://www.tatacapital.com/[2]"
    assert result["templateParamNames"] == ["1", "2"]


@pytest.mark.parametrize("url", (
    "javascript:alert(1)", "not-a-url", "https://user:password@u3.mnge.co/offer",
    "https://u3.mnge.co/offer with spaces", "https://u3.mnge.co/" + "x" * 2048,
))
@pytest.mark.parametrize("client", ("tcl_promo", "bajaj"))
def test_invalid_action_input_is_not_hidden_by_destination_rewrite(url, client):
    action = {"suggestionType": "url_action", "text": "Open", "url": url}
    with pytest.raises(ValueError, match="RCS action URL"):
        rcs_loader.load_rcs_from_list([{"template_name": "invalid", "body": "Copy", "suggestions": [action]}], client=client)
    submission = RcsTemplateSubmission(template_name="invalid", client=client, text_message="Copy", suggestions=[action])
    with pytest.raises(ValueError, match="RCS action URL"):
        rcs_client._build_rcs_save_payload(submission, client=client)


@pytest.mark.parametrize("client", ACCOUNTS)
def test_carousel_import_and_direct_cards_keep_account_and_global_parameter_scope(client):
    cards = [
        {
            "cardTitle": "Hello [name]", "cardDescription": "Offer <offer>",
            "mediaUrl": "https://cdn.example.test/first.png",
            "suggestions": [{"suggestionType": "url_action", "text": "Open", "postbackData": "open-offer",
                             "url": "https://u3.mnge.co/offer?a={{tracking}}&b=[tail]"}],
        },
        {
            "card_title": "Next [plan]", "body": "Amount #amount#",
            "media_url": "https://cdn.example.test/second.png",
            "button_type": "URL", "button_text": "Apply",
            "button_url": "https://www.tatacapital.com/personal-loan?id={{loan}}",
        },
    ]
    loaded = rcs_loader.load_rcs_from_list([{
        "template_name": "carousel_policy", "template_type": "carousel", "carousel_cards": json.dumps(cards),
    }], client=client)[0]
    original = copy.deepcopy(cards)
    direct = replace(loaded, carousel_cards=cards)
    result = rcs_client._build_rcs_save_payload(loaded, client=client)
    assert rcs_client._build_rcs_save_payload(direct, client=client) == result
    assert cards == original
    emitted = result["viTemplate"]["carouselCard"]
    expected_url = (
        "https://www.tatacapital.com/[3][4]" if client in TATA_ACCOUNTS
        else "https://u3.mnge.co/offer?a=[3]&b=[4]"
    )
    assert emitted[0]["suggestions"][0]["url"] == expected_url
    assert emitted[0]["suggestions"][0]["postbackData"] == "open-offer"
    assert emitted[1]["suggestions"][0]["url"] == "https://www.tatacapital.com/personal-loan?id=[7]"
    assert emitted[0]["mediaUrl"] == cards[0]["mediaUrl"]
    assert emitted[1]["mediaUrl"] == cards[1]["media_url"]
    assert result["templateParamNames"] == [str(index) for index in range(1, 8)]
    assert result["templatePlaceHolderCount"] == 7
