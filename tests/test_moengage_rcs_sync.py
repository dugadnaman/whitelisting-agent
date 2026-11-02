"""RCS registrations must use MoEngage sender records and placeholder syntax."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from moengage_sync import create_moengage_rcs_template


@pytest.fixture
def registration(monkeypatch):
    import moengage_sync

    config = {"base_url": "https://workspace.example", "sender_id": ""}
    monkeypatch.setattr(moengage_sync, "get_moengage_config", lambda account: config)
    monkeypatch.setattr(moengage_sync, "get_moengage_auth_headers", lambda account: {})
    settings = {"rcs_sender_settings": {"karix": {
        "moe-promo": {"sender_id": "karix-promo", "sender_name": "Promotional"},
        "moe-trans": {"sender_id": "karix-trans", "sender_name": "Transactional"},
    }}}
    get = Mock(return_value=SimpleNamespace(ok=True, json=lambda: settings))
    post = Mock(return_value=SimpleNamespace(
        ok=True, json=lambda: {"status": True, "data": {"id": "registered-template"}},
    ))
    monkeypatch.setattr(moengage_sync.requests, "get", get)
    monkeypatch.setattr(moengage_sync.requests, "post", post)
    return config, settings, get, post


def register(**overrides):
    params = dict(
        template_name="loan_offer", template_id="loan_offer",
        card_title="Offer", card_description="Your offer is ready.",
        media_url="https://media.example/card.jpg", sender_id="karix-promo", account="tata",
    )
    return create_moengage_rcs_template(**(params | overrides))


@pytest.mark.parametrize("sender", ["karix-trans", "Transactional", "moe-trans"])
def test_sender_is_resolved_to_workspace_record(registration, sender):
    _, _, _, post = registration
    register(sender_id=sender)
    assert post.call_args.kwargs["json"]["meta_data"]["sender_ids"] == ["moe-trans"]


@pytest.mark.parametrize("carousel", [False, True])
def test_square_placeholders_are_converted_without_damaging_personalization(registration, carousel):
    _, _, _, post = registration
    body = "Hi [1], [1] gets [offer]. Existing {{UserAttribute['name']}} and [guide](https://example.com)."
    cards = [{"cardTitle": "For [1]", "cardDescription": body,
              "suggestions": [{"type": "OPEN_URL", "text": "View [offer]", "url": "https://example.com/[1]"}]},
             {"cardTitle": "Next [2]", "cardDescription": "Save [amount]"}]
    register(card_title="For [1]", card_description=body,
             cta_text="View [offer]", cta_url="https://example.com/[1]",
             template_type="carousel" if carousel else "card", carousel_cards=cards if carousel else None)
    data = post.call_args.kwargs["json"]["meta_data"]["data"]
    card = data["cards"][0] if carousel else data
    assert card["title"] == "For {{1}}"
    assert card["description"] == (
        "Hi {{1}}, {{1}} gets {{offer}}. Existing {{UserAttribute['name']}} and [guide](https://example.com)."
    )
    assert card["suggestions"][0]["text"] == "View {{offer}}"
    assert card["suggestions"][0]["url"] == "https://example.com/{{1}}"
    if carousel:
        assert data["cards"][1]["description"] == "Save {{amount}}"
        assert cards[0]["cardDescription"] == body


def test_configured_moengage_sender_overrides_provider_bot(registration):
    config, _, _, post = registration
    config["sender_id"] = "Transactional"
    register()
    assert post.call_args.kwargs["json"]["meta_data"]["sender_ids"] == ["moe-trans"]


@pytest.mark.parametrize("ambiguous", [False, True])
def test_unresolved_or_ambiguous_sender_never_registers(registration, ambiguous):
    _, settings, _, post = registration
    if ambiguous:
        settings["rcs_sender_settings"]["karix"]["second-promo"] = {
            "sender_id": "karix-promo", "sender_name": "Another promotional sender",
        }
    with pytest.raises(ValueError, match="sender"):
        register(sender_id="karix-promo" if ambiguous else "unregistered-bot")
    post.assert_not_called()


def test_sender_lookup_failure_never_registers(registration):
    _, _, get, post = registration
    get.return_value = SimpleNamespace(ok=False, status_code=401)
    with pytest.raises(RuntimeError, match="sender lookup failed"):
        register()
    post.assert_not_called()


@pytest.mark.parametrize("resolve_attributes", [False, True])
def test_inventory_sync_converts_provider_brackets(registration, monkeypatch, resolve_attributes):
    import moengage_sync
    import rcs_client

    _, _, _, post = registration
    monkeypatch.setattr(rcs_client, "fetch_rcs_templates", lambda client: [{
        "templateId": "provider-template", "botId": "karix-trans", "status": "APPROVED",
        "viTemplate": {"name": "new_offer", "standaloneCard": {
            "cardTitle": "Hello [1]", "cardDescription": "Your loan [2] is ready.",
        }},
    }])
    monkeypatch.setattr(moengage_sync, "list_moengage_rcs_templates", lambda account: [])
    result = moengage_sync.sync_karix_rcs_to_moengage(resolve_attributes=resolve_attributes)
    assert result["created_count"] == 1
    meta = post.call_args.kwargs["json"]["meta_data"]
    assert meta["sender_ids"] == ["moe-trans"]
    assert meta["data"]["title"] == "Hello {{1}}"
    assert meta["data"]["description"] == "Your loan {{2}} is ready."


def test_sender_override_is_account_scoped(monkeypatch):
    import moengage_sync

    monkeypatch.setattr(moengage_sync, "_load_env_file", lambda: None)
    for key in list(moengage_sync.os.environ):
        if key.endswith("MOENGAGE_SENDER_ID"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("MOENGAGE_BEARER_TOKEN", "offline")
    for prefix in ("TATA", "APPAREL", "BAJAJ"):
        monkeypatch.setenv(f"{prefix}_MOENGAGE_BEARER_TOKEN", "offline")
    monkeypatch.setenv("MOENGAGE_SENDER_ID", "tata-global")
    monkeypatch.setenv("TCL_TRANS_MOENGAGE_SENDER_ID", "transactional-override")
    assert moengage_sync.get_moengage_config("tcl_trans")["sender_id"] == "transactional-override"
    assert moengage_sync.get_moengage_config("apparel")["sender_id"] == ""
    assert moengage_sync.get_moengage_config("bajaj")["sender_id"] == ""


@pytest.fixture
def workspace_portal(monkeypatch):
    import moengage_sync

    aldo, crocs, foreign = "a" * 24, "b" * 24, "c" * 24
    config = {
        "base_url": "https://dashboard-03.moengage.com", "workspace_id": aldo,
        "bearer_token": "saved-session", "refresh_token": "refresh", "cookie": "session=apparel",
        "sender_id": "aldo-record",
    }
    monkeypatch.setattr(moengage_sync, "get_moengage_config", lambda account: config.copy())
    apps = [
        {"id": aldo, "name": "AL_IN", "account_id": "apparel", "activated": True, "is_test": False},
        {"id": crocs, "name": "CROCS_IN", "account_id": "apparel", "activated": True, "is_test": False},
        {"id": foreign, "name": "Tata", "account_id": "tata", "activated": True, "is_test": False},
        {"id": "d" * 24, "name": "Disabled", "account_id": "apparel", "activated": False, "is_test": False},
    ]
    writes = []
    reads = []

    def get(url, **kwargs):
        if url.endswith("/listApps"):
            payload = {"data": apps}
        elif url.endswith("/changeApp"):
            target = kwargs["params"]["app_id"]
            payload = {"code": 200, "status": "success", "data": {
                "bearer": f"bound-{target}", "refresh_token": f"refresh-{target}",
                "app_access_details": "ALLOWED",
            }}
        else:
            token = kwargs["headers"]["authorization"]
            reads.append((url, token))
            if "/template_metadata" in url:
                payload = {"data": [{"name": "already_in_crocs"}] if token == f"Bearer bound-{crocs}" else []}
            else:
                payload = {"rcs_sender_settings": {"karix": {
                    "crocs-record": {"sender_id": "crocs-bot", "sender_name": "Crocs"},
                    "aldo-record": {"sender_id": "aldo-bot", "sender_name": "Aldo"},
                }}}
        return SimpleNamespace(ok=True, status_code=200, json=lambda: payload)

    def post(url, **kwargs):
        writes.append(kwargs)
        return SimpleNamespace(ok=True, json=lambda: {"status": True, "data": {"id": "created"}})

    monkeypatch.setattr(moengage_sync.requests, "get", get)
    monkeypatch.setattr(moengage_sync.requests, "post", post)
    return SimpleNamespace(aldo=aldo, crocs=crocs, foreign=foreign, config=config,
                           apps=apps, writes=writes, reads=reads)


def test_workspace_inventory_excludes_other_organizations_and_inactive_apps(workspace_portal):
    from moengage_sync import list_moengage_rcs_workspaces

    assert list_moengage_rcs_workspaces("apparel") == [
        {"id": workspace_portal.aldo, "name": "AL_IN"},
        {"id": workspace_portal.crocs, "name": "CROCS_IN"},
    ]


@pytest.mark.parametrize("target", ["foreign", "unknown", "inactive"])
def test_unauthorized_workspace_cannot_write(workspace_portal, target):
    workspace_id = {"foreign": workspace_portal.foreign, "unknown": "e" * 24, "inactive": "d" * 24}[target]
    with pytest.raises(ValueError, match="active workspace"):
        register(account="apparel", workspace_id=workspace_id)
    assert workspace_portal.writes == []


def test_selected_workspace_uses_bound_token_and_local_sender_without_mutating_saved_session(workspace_portal):
    portal = workspace_portal
    result = register(account="apparel", workspace_id=portal.crocs, sender_id="crocs-bot")
    assert result["workspace_id"] == portal.crocs
    assert portal.writes[0]["headers"]["authorization"] == f"Bearer bound-{portal.crocs}"
    assert portal.writes[0]["headers"]["refreshtoken"] == f"refresh-{portal.crocs}"
    assert portal.writes[0]["json"]["meta_data"]["sender_ids"] == ["crocs-record"]
    assert portal.config["bearer_token"] == "saved-session"
    assert portal.config["workspace_id"] == portal.aldo


def test_bulk_dedup_and_creation_share_selected_workspace(workspace_portal, monkeypatch):
    import moengage_sync
    import rcs_client

    monkeypatch.setattr(rcs_client, "fetch_rcs_templates", lambda client: [
        {"templateId": name, "botId": "crocs-bot", "status": "APPROVED",
         "viTemplate": {"name": name, "standaloneCard": {"cardDescription": "Offer"}}}
        for name in ("already_in_crocs", "new_crocs")
    ])
    portal = workspace_portal
    result = moengage_sync.sync_karix_rcs_to_moengage(
        account="apparel", workspace_id=portal.crocs, semantic_dedup=False, resolve_attributes=False,
    )
    assert result["skipped"] == ["already_in_crocs"]
    assert [row["template_name"] for row in result["created"]] == ["new_crocs"]
    assert all(token == f"Bearer bound-{portal.crocs}" for _, token in portal.reads)
    assert portal.writes[0]["json"]["name"] == "new_crocs"
    assert portal.writes[0]["headers"]["authorization"] == f"Bearer bound-{portal.crocs}"


def test_other_accounts_cannot_select_apparel_workspaces(workspace_portal):
    with pytest.raises(ValueError, match="Apparel RCS sync only"):
        register(account="tata", workspace_id=workspace_portal.crocs)
    assert workspace_portal.writes == []
