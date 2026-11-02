"""Exercise WhatsApp's real HTTP transport against a deterministic local provider."""

import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

import moengage_whatsapp_worker as transport
from moengage_draft_creation import DraftCreation
from moengage_preview import prepare_batch
from tests.test_moengage_whatsapp_bulk import (
    CATALOG_WA,
    ROW_WA,
    SENDER_ID,
    TEMPLATE_ID,
    USER,
)

CAMPAIGN_ID = "1234567890abcdef12345678"
INNER_ID = "abcdefabcdefabcdefabcdef"
OTHER_SENDER_ID = "111111111111111111111111"
OTHER_TEMPLATE_ID = "222222222222222222222222"


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    state = {
        "requests": [], "created": None, "membership": True, "saved_overrides": {},
        "senders": {"Karix": {
            OTHER_SENDER_ID: {"sender_name": "Other sender", "whatsapp_business_no": "+910000000000"},
            SENDER_ID: {"sender_name": "Tata Capital", "whatsapp_business_no": "+919876543210"},
        }},
        "templates": [
            {"id": OTHER_TEMPLATE_ID, "name": "other_template", "status": "ACTIVE",
             "meta_data": {"sender_ids": [OTHER_SENDER_ID], "provider": "Karix", "state": "APPROVED"}},
            {"id": TEMPLATE_ID, "name": "pl_diwali_promo", "status": "ACTIVE",
             "meta_data": {"sender_ids": [SENDER_ID], "provider": "Karix", "state": "APPROVED"}},
        ],
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.respond("GET")

        def do_POST(self):
            self.respond("POST")

        def respond(self, method):
            parsed = urlsplit(self.path)
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length)) if length else None
            state["requests"].append((method, parsed.path, parse_qs(parsed.query), body))
            if method == "GET" and parsed.path == "/whatsapp/settings":
                result = {"sender_settings": state["senders"]}
            elif method == "GET" and parsed.path == "/template_metadata":
                result = {"data": state["templates"]}
            elif method == "POST" and parsed.path == "/v1.0/campaigns/draft":
                selected = body["campaign_data"]["whatsapp_data"]
                if selected.get("sender") not in state["senders"]:
                    self.send_error(400, "Unknown sender provider")
                    return
                state["created"] = copy.deepcopy(body["campaign_data"])
                result = {"data": {"id": CAMPAIGN_ID}}
            elif method == "GET" and parsed.path == f"/draft/campaigns/get/{CAMPAIGN_ID}":
                draft = {**copy.deepcopy(state["created"]), "_id": INNER_ID}
                draft.update(copy.deepcopy(state["saved_overrides"]))
                result = {"data": {"campaign_draft": {"draft": draft}}}
            elif method == "POST" and parsed.path == "/draft/campaigns":
                campaigns = ([{"_id": {"$oid": CAMPAIGN_ID}, "channel": "WHATSAPP", "delivery_type": "ONE_TIME"}]
                             if state["membership"] else [])
                result = {"data": {"campaigns": campaigns}}
            else:
                self.send_error(404)
                return
            encoded = json.dumps({"status": "success", **result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def portal_session(account, workspace_id):
        assert account == "tata"
        assert workspace_id == CATALOG_WA["workspace_id"]
        return {
            "base_url": f"http://127.0.0.1:{server.server_address[1]}",
            "headers": {"Authorization": "offline-test"},
        }

    monkeypatch.setattr(transport, "portal_session", portal_session)
    try:
        yield state, transport.WhatsAppDraftWriter("tata", CATALOG_WA["workspace_id"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def payload():
    return prepare_batch([ROW_WA], "tata", CATALOG_WA, USER["email"], source_type="rows")["items"][0]["candidate_v5_payload"]


def writes(state):
    return [request for request in state["requests"] if request[:2] == ("POST", "/v1.0/campaigns/draft")]


def test_exact_nonfirst_names_resolve_and_real_route_id_is_verified(provider):
    state, writer = provider
    requested = payload()
    wa = requested["campaign_content"]["content"]["whatsapp"]
    wa.pop("sender_id")
    wa["template_id"] = "pl_diwali_promo"
    prepared = writer.prepare(requested)
    resolved = prepared["campaign_content"]["content"]["whatsapp"]
    assert resolved["sender_id"] == SENDER_ID
    assert resolved["template_id"] == TEMPLATE_ID
    assert resolved["provider"] == "KARIX"
    assert not writes(state)
    template_queries = [request[2] for request in state["requests"] if request[1] == "/template_metadata"]
    assert template_queries == [{"template_type": ["whatsapp"], "sender_id": [SENDER_ID]}]

    result = DraftCreation("tata", USER, CATALOG_WA, writer, allow_sqlite_for_tests=True).create(ROW_WA)
    assert result["state"] == "VERIFIED"
    assert result["campaign_id"] == CAMPAIGN_ID != INNER_ID
    assert len(writes(state)) == 1
    saved = state["created"]
    assert saved["campaignName"] == ROW_WA["campaign_name"]
    list_queries = [request[3] for request in state["requests"] if request[1] == "/draft/campaigns"]
    assert list_queries
    assert all(query["filter_block"] == "drafts" and query["get_archived_campaigns"] is False for query in list_queries)


@pytest.mark.parametrize("selection", ["missing_sender", "ambiguous_sender", "unknown_sender_id", "missing_template", "ambiguous_template", "unknown_template_id"])
def test_inventory_rejects_unresolved_exact_selection_before_create(provider, selection):
    state, writer = provider
    requested = payload()
    wa = requested["campaign_content"]["content"]["whatsapp"]
    if selection == "missing_sender":
        wa.pop("sender_id")
        wa["sender_name"] = "Not configured"
    elif selection == "ambiguous_sender":
        wa.pop("sender_id")
        state["senders"]["Karix"][OTHER_SENDER_ID]["sender_name"] = "Tata Capital"
    elif selection == "unknown_sender_id":
        wa["sender_id"] = "ffffffffffffffffffffffff"
    elif selection == "missing_template":
        wa["template_id"] = "Not configured"
    elif selection == "ambiguous_template":
        wa["template_id"] = "pl_diwali_promo"
        state["templates"][0]["name"] = "pl_diwali_promo"
        state["templates"][0]["meta_data"]["sender_ids"] = [SENDER_ID]
    else:
        wa["template_id"] = "ffffffffffffffffffffffff"
    with pytest.raises(ValueError):
        writer.prepare(requested)
    assert not writes(state)


@pytest.mark.parametrize("changes", [
    {"sender_ids": [OTHER_SENDER_ID]},
    {"provider": "Gupshup"},
    {"state": "PENDING"},
    {"state": "REJECTED"},
])
def test_template_ownership_and_approval_override_untrusted_list_filter(provider, changes):
    state, writer = provider
    template = state["templates"][1]
    template["status"] = "ACTIVE"
    template["meta_data"] = {"sender_ids": [SENDER_ID], "provider": "Karix", "state": "APPROVED", **changes}
    worker = DraftCreation("tata", USER, CATALOG_WA, writer, allow_sqlite_for_tests=True)
    result = worker.create(ROW_WA)
    assert result["state"] == "BLOCKED"
    assert result["campaign_id"] is None
    assert not writes(state)


def test_inactive_template_blocks_even_when_approved_for_sender(provider):
    state, writer = provider
    state["templates"][1].update(status="INACTIVE", meta_data={
        "sender_ids": [SENDER_ID], "provider": "Karix", "state": "APPROVED",
    })
    with pytest.raises(ValueError):
        writer.prepare(payload())
    assert not writes(state)


def test_saved_payload_without_draft_membership_is_not_success(provider):
    state, writer = provider
    state["membership"] = False
    worker = DraftCreation("tata", USER, CATALOG_WA, writer, allow_sqlite_for_tests=True)
    result = worker.create(ROW_WA)
    assert result["state"] != "VERIFIED"
    assert result["campaign_id"] == CAMPAIGN_ID
    assert len(writes(state)) == 1
    worker.create(ROW_WA)
    assert len(writes(state)) == 1
    with pytest.raises(ValueError, match="not confirmed"):
        writer.get(CAMPAIGN_ID)


@pytest.mark.parametrize("field,value", [
    ("sender_id", OTHER_SENDER_ID),
    ("sender", "OTHER"),
    ("template_id", OTHER_TEMPLATE_ID),
    ("body_placeholders", {"1": "Different customer"}),
])
def test_real_transport_readback_misselection_requires_review(provider, field, value):
    state, writer = provider
    state["saved_overrides"]["whatsapp_data"] = {
        "sender_id": SENDER_ID, "sender": "Karix", "template_id": TEMPLATE_ID,
        "body_placeholders": json.loads(ROW_WA["whatsapp_placeholders"]), field: value,
    }
    worker = DraftCreation("tata", USER, CATALOG_WA, writer, allow_sqlite_for_tests=True)
    first = worker.create(ROW_WA)
    assert first["state"] == "NEEDS_REVIEW"
    assert first["campaign_id"] == CAMPAIGN_ID
    assert worker.create(ROW_WA)["state"] == "NEEDS_REVIEW"
    assert len(writes(state)) == 1
