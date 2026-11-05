"""RCS sync must never read, deduplicate or register in another destination."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import api
import moengage_sync as sync


@pytest.fixture
def portal(monkeypatch):
    anchor, target, foreign = "a" * 24, "b" * 24, "c" * 24
    config = {
        "base_url": "https://dashboard-03.moengage.com", "workspace_id": anchor,
        "bearer_token": "saved-apparel-session", "refresh_token": "saved-refresh",
        "cookie": "session=apparel", "sender_id": "anchor-sender",
    }
    apps = [
        {"id": anchor, "name": "AL_IN", "account_id": "apparel-org", "activated": True, "is_test": False},
        {"id": target, "name": "CROCS_IN", "account_id": "apparel-org", "activated": True, "is_test": False},
        {"id": foreign, "name": "Tata", "account_id": "tata-org", "activated": True, "is_test": False},
        {"id": "d" * 24, "name": "Inactive", "account_id": "apparel-org", "activated": False, "is_test": False},
        {"id": "e" * 24, "name": "Sandbox", "account_id": "apparel-org", "activated": True, "is_test": True},
    ]
    reads, writes = [], []
    bound_target = [None]

    def get(url, **kwargs):
        if url.endswith('/listApps'):
            payload = {"code": 200, "status": "success", "data": apps}
        elif url.endswith('/changeApp'):
            selected = kwargs['params']['app_id']
            payload = {"code": 200, "status": "success", "data": {
                "bearer": f"bound-{selected}", "refresh_token": f"refresh-{selected}",
                "app_access_details": "ALLOWED",
            }}
            bound_target[0] = selected
        else:
            reads.append((url, kwargs['headers'].copy()))
            if '/template_metadata' in url:
                payload = {"data": [{"name": "already_in_crocs", "meta_data": {"template_id": "existing"}}]}
            else:
                payload = {"rcs_sender_settings": {"karix": {
                    "crocs-sender-record": {"sender_id": "crocs-bot", "sender_name": "Crocs"},
                    "anchor-sender": {"sender_id": "anchor-bot", "sender_name": "Aldo"},
                }}}
        return SimpleNamespace(ok=True, status_code=200, json=lambda: payload)

    def post(url, **kwargs):
        writes.append((url, kwargs))
        return SimpleNamespace(ok=True, status_code=200, json=lambda: {"status": True, "data": {"id": "new-template"}})

    monkeypatch.setattr(sync, 'get_moengage_config', lambda account: config.copy())
    monkeypatch.setattr(sync.requests, 'get', get)
    monkeypatch.setattr(sync.requests, 'post', post)
    return SimpleNamespace(anchor=anchor, target=target, foreign=foreign, config=config,
                           apps=apps, reads=reads, writes=writes, bound_target=bound_target)


def register(portal, **changes):
    values = dict(template_name='new_offer', template_id='new_offer', card_title='Offer',
                  card_description='Shop the collection.', media_url='https://media.example/card.jpg',
                  account='apparel', workspace_id=portal.target, sender_id='crocs-bot',
                  cta_url='https://shop.example/offer')
    values.update(changes)
    return sync.create_moengage_rcs_template(**values)


def test_workspace_list_is_limited_to_active_apparel_organization(portal):
    assert sync.list_moengage_rcs_workspaces('apparel') == [
        {"id": portal.anchor, "name": "AL_IN"}, {"id": portal.target, "name": "CROCS_IN"},
    ]
    assert portal.bound_target[0] is None


@pytest.mark.parametrize('target', [None, '', 'c' * 24, 'd' * 24, 'e' * 24, 'f' * 24, 'invalid'])
def test_missing_foreign_inactive_test_or_unknown_destination_cannot_register(portal, target):
    with pytest.raises((ValueError, PermissionError)):
        register(portal, workspace_id=target)
    assert portal.writes == []
    assert portal.reads == []


@pytest.mark.parametrize('invalid_anchor', ['missing', 'inactive', 'test', 'duplicate'])
def test_invalid_account_anchor_cannot_authorize_other_workspaces(portal, invalid_anchor):
    if invalid_anchor == 'missing':
        portal.apps.pop(0)
    elif invalid_anchor == 'inactive':
        portal.apps[0]['activated'] = False
    elif invalid_anchor == 'test':
        portal.apps[0]['is_test'] = True
    else:
        portal.apps.append(portal.apps[0].copy())
    with pytest.raises((ValueError, PermissionError)):
        register(portal)
    assert portal.writes == []


def test_selected_destination_binds_auth_and_sender_without_mutating_saved_account(portal):
    before = portal.config.copy()
    result = register(portal)
    assert result['workspace_id'] == portal.target
    headers = portal.writes[0][1]['headers']
    assert headers['authorization'] == f'Bearer bound-{portal.target}'
    assert headers['refreshtoken'] == f'refresh-{portal.target}'
    assert portal.writes[0][1]['json']['meta_data']['sender_ids'] == ['crocs-sender-record']
    assert portal.config == before


def test_no_other_brand_cta_is_invented_for_selected_destination(portal):
    register(portal, cta_url=None)
    assert portal.writes[0][1]['json']['meta_data']['data']['suggestions'] == []


def test_sender_from_other_workspace_cannot_silently_fall_back(portal):
    with pytest.raises(ValueError, match='sender'):
        register(portal, sender_id='unregistered-bot')
    assert portal.writes == []


def test_bulk_duplicate_checks_and_creation_use_same_selected_workspace(portal, monkeypatch):
    import rcs_client
    monkeypatch.setattr(rcs_client, 'fetch_rcs_templates', lambda client: [
        {"templateId": name, "status": "APPROVED", "botId": "crocs-bot",
         "viTemplate": {"name": name, "standaloneCard": {"cardTitle": "Offer", "cardDescription": "Details"}}}
        for name in ('already_in_crocs', 'new_crocs')
    ])
    result = sync.sync_karix_rcs_to_moengage(account='apparel', workspace_id=portal.target,
                                           semantic_dedup=False, resolve_attributes=False)
    assert result['skipped'] == ['already_in_crocs']
    assert [row['template_name'] for row in result['created']] == ['new_crocs']
    assert result['workspace_id'] == portal.target
    assert all(headers['authorization'] == f'Bearer bound-{portal.target}' for _, headers in portal.reads)
    assert len(portal.writes) == 1
    assert portal.writes[0][1]['headers']['authorization'] == f'Bearer bound-{portal.target}'


@pytest.mark.parametrize('account', ['tata', 'bajaj'])
def test_other_accounts_cannot_select_an_apparel_destination(portal, account):
    with pytest.raises((ValueError, PermissionError)):
        register(portal, account=account)
    assert portal.writes == []


@pytest.mark.parametrize('path,method', [('/api/moengage/rcs/workspaces?account=apparel', 'get'),
                                       ('/api/moengage/rcs/sync-karix?account=apparel', 'post')])
def test_rcs_routes_do_not_contact_provider_for_foreign_tenants(provision_user, monkeypatch, path, method):
    _, headers = provision_user(tenant='tata', role='operator')
    provider = Mock()
    monkeypatch.setattr(sync.requests, 'get', provider)
    client = TestClient(api.app)
    response = getattr(client, method)(path, headers=headers)
    assert response.status_code == 403
    provider.assert_not_called()


@pytest.mark.parametrize('method,path,body', [
    ('post', '/api/moengage/rcs/sync-karix?account=apparel', None),
    ('get', '/api/moengage/rcs/templates?account=apparel', None),
    ('post', '/api/moengage/rcs/sync', {'account': 'apparel', 'template_name': 'Offer',
                                     'card_title': 'Offer', 'card_description': 'Details'}),
])
def test_api_requires_destination_before_provider_calls(provision_user, monkeypatch, method, path, body):
    _, headers = provision_user(tenant='apparel', role='operator')
    provider = Mock()
    monkeypatch.setattr(sync.requests, 'get', provider)
    client = TestClient(api.app)
    response = getattr(client, method)(path, headers=headers, **({'json': body} if body else {}))
    assert response.status_code == 400
    provider.assert_not_called()
