"""Exercise real RCS registration/sync payload construction without provider access."""
import copy
from types import SimpleNamespace

import pytest

import moengage_sync
import rcs_client


TATA_ACCOUNTS = ("tata", "tcl_promo", "tcl_trans", "tchfl", "wealth", "moneyfy")
ACCOUNTS = (*TATA_ACCOUNTS, "bajaj", "apparel")
API_BASE = "https://dashboard-03.moengage.com"
MEDIA_URL = "https://cdn.example.test/banner.png"


@pytest.fixture
def registration(monkeypatch):
    calls = []
    context = ({"base_url": API_BASE, "workspace_id": "workspace-1"}, {"Authorization": "test-token"})
    monkeypatch.setattr(moengage_sync, "_rcs_workspace_context", lambda *args, **kwargs: context)
    monkeypatch.setattr(moengage_sync, "_resolve_rcs_sender", lambda *args, **kwargs: "sender-1")

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(ok=True, json=lambda: {"status": True, "data": {"id": "registered-1"}})

    monkeypatch.setattr(moengage_sync.requests, "post", post)
    return calls


def source_actions():
    return [
        {"suggestionType": "url_action", "text": "Open", "postbackData": "open-offer",
         "url": "https://u3.mnge.co/offer?tracking=[2]"},
        {"type": "OPEN_URL", "text": "Join", "postback_data": "join-meeting",
         "url": "https://teams.microsoft.com/l/meetup-join/meeting"},
        {"suggestionType": "dialer_action", "text": "Call", "postbackData": "call-offer",
         "phoneNumber": "+919999999999", "url": "https://u3.mnge.co/not-a-phone-action"},
        {"type": "REPLY", "text": "Confirm", "postback_data": "confirm-offer",
         "url": "https://u3.mnge.co/not-a-reply-action"},
    ]


def assert_actions(actions, account):
    assert len(actions) == 4
    expected_url = (
        "https://www.tatacapital.com/{{2}}" if account in TATA_ACCOUNTS
        else "https://u3.mnge.co/offer?tracking={{2}}"
    )
    assert actions[0] == {
        "type": "OPEN_URL", "text": "Open", "postback_data": "open-offer", "url": expected_url,
        "application": "BROWSER", "webview_view_mode": "",
    }
    assert actions[1]["url"] == "https://teams.microsoft.com/l/meetup-join/meeting"
    assert actions[1]["postback_data"] == "join-meeting"
    assert actions[2] == {
        "type": "DIAL_PHONE", "text": "Call", "postback_data": "call-offer", "phone_number": "+919999999999",
    }
    assert actions[3] == {"type": "REPLY", "text": "Confirm", "postback_data": "confirm-offer"}


@pytest.mark.parametrize("account", ACCOUNTS)
@pytest.mark.parametrize("template_type", ("card", "carousel"))
def test_registration_resolves_every_url_without_touching_other_action_types(registration, account, template_type):
    actions = source_actions()
    original = copy.deepcopy(actions)
    cards = [{
        "cardTitle": f"Card {index} [1]", "cardDescription": "Copy https://u3.mnge.co/body",
        "mediaUrl": MEDIA_URL, "suggestions": copy.deepcopy(actions),
    } for index in (1, 2)]
    result = moengage_sync.create_moengage_rcs_template(
        template_name="account_cta_policy", template_id="account_cta_policy", card_title="Hello [1]",
        card_description="Copy https://u3.mnge.co/body", account=account, media_url=MEDIA_URL,
        template_type=template_type, carousel_cards=cards if template_type == "carousel" else None,
        suggestions=actions,
    )
    assert result["ok"]
    assert actions == original
    assert len(registration) == 1
    url, request = registration[0]
    assert url == f"{API_BASE}/template_metadata"
    payload = request["json"]
    assert payload["meta_data"]["sender_ids"] == ["sender-1"]
    content = payload["meta_data"]["data"]
    for card in content.get("cards", [content]):
        assert_actions(card["suggestions"], account)
        assert card["description"] == "Copy https://u3.mnge.co/body"
        assert card["media"]["media_url"] == MEDIA_URL
        assert "{{1}}" in card["title"]


@pytest.mark.parametrize("url,expected", (
    ("", "https://www.tatacapital.com/"),
    ("https://u3.mnge.co/offer?a=[2]&b={{tracking}}", "https://www.tatacapital.com/{{2}}{{tracking}}"),
    ("https://www.tatacapital.com/personal-loan?source=brief", "https://www.tatacapital.com/personal-loan?source=brief"),
    ("https://teams.microsoft.com/l/meetup-join/meeting", "https://teams.microsoft.com/l/meetup-join/meeting"),
    ("https://example.test/offer", "https://example.test/offer"),
))
def test_scalar_standalone_tata_cta_uses_destination_policy(registration, url, expected):
    moengage_sync.create_moengage_rcs_template(
        template_name="scalar_cta", template_id="scalar_cta", card_title="Title", card_description="Body",
        cta_url=url, account="tata", media_url=MEDIA_URL,
    )
    action = registration[0][1]["json"]["meta_data"]["data"]["suggestions"][0]
    assert action["url"] == expected


@pytest.mark.parametrize("account", ("tata", "bajaj", "apparel"))
@pytest.mark.parametrize("template_type", ("card", "carousel"))
def test_inventory_sync_preserves_all_actions_and_skips_registered_templates(registration, monkeypatch, account, template_type):
    card = {"cardTitle": "Hello [1]", "cardDescription": "Copy https://u3.mnge.co/body",
            "mediaUrl": MEDIA_URL, "suggestions": source_actions()}
    vi = {"name": "new_template", "type": "carousel" if template_type == "carousel" else "richcard", "botId": "bot-1"}
    if template_type == "carousel":
        vi["carouselCard"] = [copy.deepcopy(card), copy.deepcopy(card)]
    else:
        vi["standaloneCard"] = card
    approved = {"templateId": "approved-1", "status": "APPROVED", "viTemplate": vi}
    existing = {"name": "already_registered", "meta_data": {"template_id": "existing-1", "url": "https://u3.mnge.co/existing"}}
    original_existing = copy.deepcopy(existing)
    monkeypatch.setattr(rcs_client, "fetch_rcs_templates", lambda **kwargs: [
        approved, {"templateId": "existing-1", "viTemplate": {"name": "already_registered"}},
    ])
    monkeypatch.setattr(moengage_sync, "list_moengage_rcs_templates", lambda *args, **kwargs: [existing])
    result = moengage_sync.sync_karix_rcs_to_moengage(account=account, semantic_dedup=False, resolve_attributes=False)
    assert result["created_count"] == 1
    assert result["skipped"] == ["already_registered"]
    assert result["error_count"] == 0
    assert existing == original_existing
    assert len(registration) == 1
    content = registration[0][1]["json"]["meta_data"]["data"]
    for registered_card in content.get("cards", [content]):
        assert_actions(registered_card["suggestions"], account)
        assert registered_card["media"]["media_url"] == MEDIA_URL
