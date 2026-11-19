"""Only explicit account-matched inventories can authorize duplicate decisions."""

import pytest

import submission_client as client
from tests.test_whatsapp_media_transport import isolated, provider, portal_credentials


@pytest.mark.parametrize('payload', [
    {}, {'response': {}}, {'Success': {}}, {'response': {'error': 'Session expired'}},
    {'Success': {'templates': None}}, {'templates': 'not a list'}, {'templates': [None]},
    {'templates': [{'waba_id': 'another-account'}]},
    {'templates': [{'wabaId': 'local-TCL_PROMO-waba', 'waba_id': 'another-account'}]},
    {'templates': [], 'response': {'templates': [{'template_name': 'conflicting'}]}},
])
def test_bad_provider_catalog_never_becomes_verified_empty(provider, monkeypatch, payload):
    portal_credentials(monkeypatch)
    provider.routes['/portal/getAllTemplates'] = (200, payload)
    provider.routes['/official/local-TCL_PROMO-waba'] = (200, payload)
    rows, error = client.fetch_template_list('tcl_promo')
    assert rows == []
    assert error, 'A failed or ambiguous inventory cannot authorize a missing-template decision'


@pytest.mark.parametrize('payload', [[], {'templates': []}, {'Success': {'templates': []}},
                                     {'response': {'templates': []}}, {'Failed': 'No Records Found'}])
def test_explicit_empty_catalog_is_not_misclassified_as_disconnection(provider, monkeypatch, payload):
    portal_credentials(monkeypatch)
    provider.routes['/portal/getAllTemplates'] = (200, payload)
    assert client.fetch_template_list('tcl_promo') == ([], None)
    assert len(provider.calls) == 1


def test_valid_catalog_for_selected_account_preserves_provider_rows(provider, monkeypatch):
    portal_credentials(monkeypatch)
    rows = [{'template_name': 'existing_campaign', 'waba_id': 'local-TCL_PROMO-waba',
             'esmeaddr': '0', 'language': 'hi', 'template_create_status': 'PENDING'}]
    provider.routes['/portal/getAllTemplates'] = (200, {'Success': {'templates': rows}})
    assert client.fetch_template_list('tcl_promo') == (rows, None)
