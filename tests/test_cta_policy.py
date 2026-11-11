"""Tata CTA defaults replace MoEngage trackers without breaking real destinations."""

from copy import deepcopy

import pytest

from cta import normalize_whatsapp_cta_buttons, resolve_cta_url


@pytest.mark.parametrize("client", ["tata", "tcl_promo", "tcl_trans", "tchfl", "wealth", "moneyfy"])
@pytest.mark.parametrize("url,expected", [
    ("https://u3.mnge.co/campaign", "https://www.tatacapital.com/"),
    ("https://u3.mnge.co/{{offer}}", "https://www.tatacapital.com/{{offer}}"),
    ("https://offers.mnge.co/offer/[3]", "https://www.tatacapital.com/[3]"),
    ("https://links.moengage.com/campaign", "https://www.tatacapital.com/"),
    ("", "https://www.tatacapital.com/"),
])
def test_tata_destination_replaces_trackers_without_losing_variables(client, url, expected):
    assert resolve_cta_url(url, client) == expected


@pytest.mark.parametrize("url", [
    "https://www.tatacapital.com/personal-loan.html?campaign=offer#apply",
    "https://tatacapital.com/wealth/{{offer}}",
    "https://customer.tatacapital.com/offers/[offer]",
    "https://teams.microsoft.com/meet/12345",
    "https://brand.example/offer/[3]",
    "https://mnge.co.evil.example/offer",
])
def test_explicit_product_and_other_real_destinations_are_preserved(url):
    assert resolve_cta_url(url, "tcl_promo") == url


@pytest.mark.parametrize("client", ["bajaj", "apparel"])
def test_other_accounts_keep_their_customer_destinations(client):
    for url in ("https://u3.mnge.co/other-brand/{{1}}", "https://brand.example/offers", ""):
        assert resolve_cta_url(url, client) == url


@pytest.mark.parametrize("url", ["ftp://brand.example/offer", "not a URL", "https://[broken"])
def test_destination_policy_does_not_hide_malformed_input(url):
    assert resolve_cta_url(url, "tata") == url


def test_whatsapp_replaces_tracker_samples_and_keeps_other_actions():
    buttons = [
        {"type": "URL", "text": "Apply", "url": "https://u3.mnge.co/{{1}}",
         "example": ["https://u3.mnge.co/old-campaign"]},
        {"type": "URL", "text": "Learn", "url": "https://www.tatacapital.com/loans/{{1}}",
         "example": ["https://www.tatacapital.com/loans/personal"]},
        {"type": "PHONE_NUMBER", "text": "Call", "phone_number": "+911234567890"},
        {"type": "QUICK_REPLY", "text": "Later"},
    ]
    original = deepcopy(buttons)
    normalize_whatsapp_cta_buttons(buttons, "tcl_promo")
    assert buttons[0]["url"] == "https://www.tatacapital.com/{{1}}"
    assert buttons[0]["example"] == ["https://www.tatacapital.com/sample"]
    assert buttons[1:] == original[1:]
    normalized = deepcopy(buttons)
    normalize_whatsapp_cta_buttons(buttons, "tcl_promo")
    assert buttons == normalized


def test_jira_preview_and_whatsapp_final_payload_agree_on_destination():
    from api import _jira_whatsapp_components
    from submission_client import _resolve_body_variables

    draft = {"body": "Your offer is ready.", "buttons": [
        {"type": "URL", "text": "Apply", "url": "https://u3.mnge.co/campaign/{{1}}",
         "example": ["https://u3.mnge.co/campaign/customer"]},
    ]}
    original = deepcopy(draft)
    preview = _jira_whatsapp_components(draft, "tcl_promo")
    payload = _resolve_body_variables(deepcopy(preview), client="tcl_promo", fix_grammar=False)
    assert preview == payload
    assert preview[-1]["buttons"][0]["url"] == "https://www.tatacapital.com/{{1}}"
    assert draft == original


def test_tata_submission_boundary_normalizes_direct_components_without_touching_body():
    from submission_client import _resolve_body_variables

    body = "Read https://u3.mnge.co/body-reference for details."
    components = [
        {"type": "BODY", "text": body},
        {"type": "BUTTONS", "buttons": [{"type": "URL", "text": "Apply", "url": "https://u3.mnge.co/campaign"}]},
    ]
    result = _resolve_body_variables(deepcopy(components), client="tata", fix_grammar=False)
    assert result[0]["text"] == body
    assert result[1]["buttons"][0]["url"] == "https://www.tatacapital.com/{{1}}"
    other = _resolve_body_variables(deepcopy(components), client="bajaj", fix_grammar=False)
    assert other[1]["buttons"][0]["url"] == "https://u3.mnge.co/campaign{{1}}"


def test_jira_rcs_carousel_submit_resolves_card_ctas_on_selected_account(provision_user, monkeypatch, tmp_path):
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from PIL import Image
    import api
    import jira_client
    from briefing_parser import ParsedJiraBrief
    from rcs_models import RcsSubmissionResult, RcsSubmissionStatus

    _, headers = provision_user(tenant="tata")
    cache = tmp_path / "media_cache"
    cache.mkdir()
    monkeypatch.setattr(jira_client, "MEDIA_CACHE_DIR", cache)
    creative = cache / "card.png"
    Image.new("RGB", (600, 600), "white").save(creative)
    submitted = []
    carousel = {
        "template_name": "jira_carousel_cta", "card_title": "Offers", "body": "Choose offer.",
        "template_type": "carousel",
        "carousel_cards": [
            {"card_title": "First", "body": "Card one", "media_url": str(creative), "button_text": "Apply", "button_url": "https://u3.mnge.co/one/{{1}}"},
            {"card_title": "Second", "body": "Card two", "media_url": str(creative), "button_text": "Join", "button_url": "https://teams.microsoft.com/meet/2"},
        ],
    }
    parsed = ParsedJiraBrief(issue_key="TCN-999", summary="Carousel", account="tcl_promo", status="To Do",
                             assignee="Op", reporter="Rep", duedate=None, rcs_templates=[carousel])

    def fake_submit(sub, client):
        submitted.append((sub, client))
        return RcsSubmissionResult(source_ref=sub.source_ref, template_name=sub.template_name, template_id="rcs-1",
                                   status=RcsSubmissionStatus.SUBMITTED, approval_status="pending", client=client)

    with (
        patch("jira_client.fetch_jira_issue", return_value={"key": "TCN-999", "fields": {}}),
        patch("briefing_parser.parse_jira_brief", return_value=parsed),
        patch("api.get_rcs_bot_id", return_value="bot-1"),
        patch("rcs_client.submit_rcs_template", side_effect=fake_submit),
        patch("rcs_tracker.log_rcs_result"),
    ):
        resp = TestClient(api.app, headers=headers).post("/api/jira/submit/TCN-999", json={
            "account": "tcl_promo", "channels": ["rcs"], "rcs_templates": [carousel], "expected_rcs_bot_id": "bot-1",
        })
    assert resp.status_code == 200, resp.text
    cards = submitted[0][0].carousel_cards
    assert cards[0]["button_url"] == "https://www.tatacapital.com/{{1}}"
    assert cards[1]["button_url"] == "https://teams.microsoft.com/meet/2"
