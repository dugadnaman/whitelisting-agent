"""Exercise WhatsApp's real HTTP transport against a deterministic local provider."""

import copy
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

import db
import moengage_whatsapp_worker as transport
from moengage_draft_creation import DraftCreation
from moengage_draft_batches import DraftBatchQueue
from moengage_preview import prepare_batch
from tests.test_apparel_whatsapp_content import USER as APPAREL_USER, catalog_for, row_for
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
             "meta_data": {"sender_ids": [SENDER_ID], "provider": "Karix", "state": "APPROVED",
                           "content": {"body": "Hello {{1}}, your {{2}} is ready."}}},
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
            override = state.get("responses", {}).get((method, parsed.path))
            if override is not None:
                status, document = override
                self.send_document(status, document)
                return
            if method == "GET" and parsed.path == "/whatsapp/settings":
                result = {"sender_settings": state["senders"]}
            elif method == "GET" and parsed.path == "/template_metadata":
                result = {"data": state.get("template_summaries", state["templates"])}
            elif method == "GET" and parsed.path.startswith("/template_meta/"):
                result = {"data": next(template for template in state["templates"]
                                        if template["id"] == parsed.path.rsplit("/", 1)[1])}
            elif method == "POST" and parsed.path == "/v1.0/campaigns/draft":
                if body["campaign_data"].get("delivery") not in ("later", "soon", "periodic", "trigger"):
                    self.send_document(400, {"status": "error", "message": "Campaign delivery is required"})
                    return
                selected = body["campaign_data"]["whatsapp_data"]
                if selected.get("sender") not in state["senders"]:
                    self.send_error(400, "Unknown sender provider")
                    return
                state["created"] = copy.deepcopy(body["campaign_data"])
                state["created"]["c_cr_t"] = datetime.now(timezone.utc).isoformat()
                result = {"data": {"id": CAMPAIGN_ID}}
            elif method == "GET" and parsed.path == f"/draft/campaigns/get/{CAMPAIGN_ID}":
                draft = {**copy.deepcopy(state["created"]), "_id": INNER_ID}
                draft.update(copy.deepcopy(state["saved_overrides"]))
                result = {"data": {"campaign_draft": {"draft": draft}}}
            elif method == "POST" and parsed.path == "/draft/campaigns":
                campaigns = ([{"_id": {"$oid": CAMPAIGN_ID}, "name": state["created"]["campaignName"],
                               "channel": "WHATSAPP", "delivery_type": "ONE_TIME"}]
                             if state["membership"] and state["created"] is not None else [])
                result = {"data": {"campaigns": campaigns}}
            else:
                self.send_error(404)
                return
            self.send_document(200, {"status": "success", **result})

        def send_document(self, status, document):
            encoded = document if isinstance(document, bytes) else json.dumps(document).encode()
            self.send_response(status)
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


@pytest.mark.parametrize("status,document", [
    (401, {"status": "success", "data": {"id": CAMPAIGN_ID}}),
    (403, {"status": "success", "data": {"id": CAMPAIGN_ID}}),
    (429, {"status": "success", "data": {"id": CAMPAIGN_ID}}),
    (500, {"status": "success", "data": {"id": CAMPAIGN_ID}}),
    (503, {"status": "success", "data": {"id": CAMPAIGN_ID}}),
    (200, b"not-json"),
    (200, []),
    (200, {"status": "success", "success": False, "data": {"id": CAMPAIGN_ID}}),
    (200, {"status": 1, "data": {"id": CAMPAIGN_ID}}),
    (200, {"status": "success", "code": 401, "data": {"id": CAMPAIGN_ID}}),
    (200, {"status": "success", "code": 403, "data": {"id": CAMPAIGN_ID}}),
    (200, {"status": "success", "code": 429, "data": {"id": CAMPAIGN_ID}}),
    (200, {"status": "success", "code": 500, "data": {"id": CAMPAIGN_ID}}),
    (200, {"status": "success", "data": None}),
])
def test_failed_create_response_is_durable_uncertain_without_second_post(provider, status, document):
    state, writer = provider
    state["responses"] = {("POST", "/v1.0/campaigns/draft"): (status, document)}
    worker = DraftCreation("tata", USER, CATALOG_WA, writer, allow_sqlite_for_tests=True)
    first = worker.create(ROW_WA)
    assert first["state"] == "UNCERTAIN"
    assert first["campaign_id"] is None
    assert worker.create(ROW_WA)["state"] == "UNCERTAIN"
    assert len(writes(state)) == 1


@pytest.mark.parametrize("status,document", [
    (401, {}),
    (403, {}),
    (429, {}),
    (503, {}),
    (200, b"not-json"),
    (200, {"status": "success", "success": False, "sender_settings": {}}),
    (200, {"status": "success", "code": 429, "sender_settings": {}}),
])
def test_failed_metadata_response_blocks_before_reserving_or_posting(provider, status, document):
    state, writer = provider
    state["responses"] = {("GET", "/whatsapp/settings"): (status, document)}
    worker = DraftCreation("tata", USER, CATALOG_WA, writer, allow_sqlite_for_tests=True)
    result = worker.create(ROW_WA)
    assert result["state"] == "BLOCKED"
    assert not writes(state)
    state["responses"].clear()
    assert worker.create(ROW_WA)["state"] == "VERIFIED"
    assert len(writes(state)) == 1


@pytest.mark.parametrize("method,path,status,document", [
    ("GET", f"/draft/campaigns/get/{CAMPAIGN_ID}", 200, {"status": "success", "data": None}),
    ("GET", f"/draft/campaigns/get/{CAMPAIGN_ID}", 200, {"status": "success", "data": {"campaign_draft": []}}),
    ("GET", f"/draft/campaigns/get/{CAMPAIGN_ID}", 503, {}),
    ("POST", "/draft/campaigns", 429, {}),
    ("POST", "/draft/campaigns", 200, {"status": "success", "data": {"campaigns": None}}),
])
def test_partial_readback_failure_resumes_only_reads(provider, method, path, status, document):
    state, writer = provider
    state["responses"] = {(method, path): (status, document)}
    worker = DraftCreation("tata", USER, CATALOG_WA, writer, allow_sqlite_for_tests=True)
    first = worker.create(ROW_WA)
    assert first["state"] == "CREATED"
    assert first["campaign_id"] == CAMPAIGN_ID
    state["responses"].clear()
    resumed = DraftCreation("tata", USER, CATALOG_WA, writer, allow_sqlite_for_tests=True).create(ROW_WA)
    assert resumed["state"] == "VERIFIED"
    assert resumed["campaign_id"] == CAMPAIGN_ID
    assert len(writes(state)) == 1


@pytest.mark.parametrize("stage", ["metadata", "create_after_acceptance", "readback"])
def test_request_timeout_never_retries_an_ambiguous_create(provider, monkeypatch, stage):
    state, writer = provider
    original_request = requests.request
    timed_out = []
    def request(method, url, **kwargs):
        path = urlsplit(url).path
        target = {
            "metadata": ("GET", "/whatsapp/settings"),
            "create_after_acceptance": ("POST", "/v1.0/campaigns/draft"),
            "readback": ("GET", f"/draft/campaigns/get/{CAMPAIGN_ID}"),
        }[stage]
        if (method, path) == target and not timed_out:
            timed_out.append(target)
            if stage == "create_after_acceptance":
                original_request(method, url, **kwargs)
            raise requests.Timeout("offline provider timeout")
        return original_request(method, url, **kwargs)
    monkeypatch.setattr(requests, "request", request)
    worker = DraftCreation("tata", USER, CATALOG_WA, writer, allow_sqlite_for_tests=True)
    first = worker.create(ROW_WA)
    assert first["state"] == {"metadata": "BLOCKED", "create_after_acceptance": "UNCERTAIN", "readback": "CREATED"}[stage]
    second = worker.create(ROW_WA)
    assert second["state"] == ("UNCERTAIN" if stage == "create_after_acceptance" else "VERIFIED")
    assert len(writes(state)) == 1


@pytest.mark.parametrize("change", ["approval", "association", "provider", "sender_name"])
def test_selection_changed_after_prepare_is_rechecked_before_write(provider, change):
    state, writer = provider
    prepared = writer.prepare(payload())
    if change == "approval":
        state["templates"][1]["meta_data"]["state"] = "REJECTED"
    elif change == "association":
        state["templates"][1]["meta_data"]["sender_ids"] = [OTHER_SENDER_ID]
    elif change == "provider":
        state["templates"][1]["meta_data"]["provider"] = "Other"
    else:
        state["senders"]["Karix"][SENDER_ID]["sender_name"] = "Renamed sender"
    with pytest.raises(ValueError):
        writer.create(prepared, idempotency_key="no-retry")
    assert not writes(state)


@pytest.mark.parametrize("placeholders", [
    {"1": "Naman"},
    {"1": "Naman", "2": "Offer", "3": "Unexpected"},
    {"1": "Naman", "{{1}}": "Conflicting", "2": "Offer"},
    {"1": "", "2": "Offer"},
])
def test_live_template_placeholders_must_cover_numbered_variables(provider, placeholders):
    state, writer = provider
    state["templates"][1]["meta_data"]["content"] = {"body": "Hello {{1}}, {{2}}"}
    requested = payload()
    requested["campaign_content"]["content"]["whatsapp"]["body_placeholders"] = placeholders
    with pytest.raises(ValueError, match="placeholder"):
        writer.prepare(requested)
    assert not writes(state)


@pytest.mark.parametrize("placeholders", [
    {"1": "Naman", "2": "Offer"},
    {"{{1}}": "Naman", "{{2}}": "Offer"},
])
def test_live_template_accepts_existing_placeholder_key_conventions(provider, placeholders):
    state, writer = provider
    state["templates"][1]["meta_data"]["content"] = {"body": "Hello {{1}}, {{2}}"}
    requested = payload()
    requested["campaign_content"]["content"]["whatsapp"]["body_placeholders"] = placeholders
    assert writer.prepare(requested)["campaign_content"]["content"]["whatsapp"]["body_placeholders"] == placeholders


@pytest.mark.parametrize("field,value", [("channel", "EMAIL"), ("delivery_type", "PERIODIC")])
def test_saved_scope_must_not_contradict_draft_membership(provider, field, value):
    state, writer = provider
    state["saved_overrides"][field] = value
    worker = DraftCreation("tata", USER, CATALOG_WA, writer, allow_sqlite_for_tests=True)
    first = worker.create(ROW_WA)
    assert first["state"] != "VERIFIED"
    assert first["campaign_id"] == CAMPAIGN_ID
    assert len(writes(state)) == 1


@pytest.mark.parametrize("preflight_change", ["live_approval", "catalog_template"])
def test_created_readback_resume_preserves_id_when_preflight_changes(provider, preflight_change):
    state, writer = provider
    state["responses"] = {("GET", f"/draft/campaigns/get/{CAMPAIGN_ID}"): (503, {})}
    catalog = copy.deepcopy(CATALOG_WA)
    worker = DraftCreation("tata", USER, catalog, writer, allow_sqlite_for_tests=True)
    assert worker.create(ROW_WA)["state"] == "CREATED"
    state["responses"].clear()
    if preflight_change == "live_approval":
        state["templates"][1]["meta_data"]["state"] = "REJECTED"
    else:
        catalog["whatsapp_templates"] = []
    blocked_resume = worker.create(ROW_WA)
    assert blocked_resume["state"] == "CREATED"
    assert blocked_resume["campaign_id"] == CAMPAIGN_ID
    assert blocked_resume["issue"] == "readback_preflight_unavailable"
    state["templates"][1]["meta_data"]["state"] = "APPROVED"
    catalog["whatsapp_templates"] = copy.deepcopy(CATALOG_WA["whatsapp_templates"])
    assert worker.create(ROW_WA)["state"] == "VERIFIED"
    assert len(writes(state)) == 1


def test_same_name_with_another_draft_id_does_not_prove_membership(provider):
    state, writer = provider
    state["responses"] = {("POST", "/draft/campaigns"): (200, {
        "status": "success", "data": {"campaigns": [{
            "_id": {"$oid": INNER_ID}, "name": ROW_WA["campaign_name"],
            "channel": "WHATSAPP", "delivery_type": "ONE_TIME",
        }]},
    })}
    worker = DraftCreation("tata", USER, CATALOG_WA, writer, allow_sqlite_for_tests=True)
    result = worker.create(ROW_WA)
    assert result["state"] == "CREATED"
    assert result["campaign_id"] == CAMPAIGN_ID
    assert worker.create(ROW_WA)["state"] == "CREATED"
    assert len(writes(state)) == 1


@pytest.fixture
def apparel_provider(provider, monkeypatch, request):
    state, original_writer = provider
    catalog = catalog_for(getattr(request, "param", "VS"))
    sender = catalog["whatsapp_senders"][0]
    template = catalog["whatsapp_templates"][0]
    state["senders"] = {"Karix": {
        sender["sender_id"]: {"sender_name": sender["name"], "whatsapp_business_no": sender["number"]},
    }}
    state["templates"] = [{
        "id": template["id"], "name": template["name"], "status": "ACTIVE",
        "meta_data": {"sender_ids": [sender["sender_id"]], "provider": "Karix", "state": "APPROVED",
                      "content": copy.deepcopy(template["template_content"])},
    }]

    def portal_session(account, workspace_id):
        assert account == "apparel" and workspace_id == catalog["workspace_id"]
        return {"base_url": original_writer.base_url, "headers": original_writer.headers.copy()}

    monkeypatch.setattr(transport, "portal_session", portal_session)
    return state, transport.WhatsAppDraftWriter("apparel", catalog["workspace_id"]), catalog


@pytest.fixture
def apparel_queue(apparel_provider, monkeypatch):
    state, writer, catalog = apparel_provider
    # The live writer enriches this optional catalog field. Review hashes must
    # cover the V5 candidate, not that later transport preparation.
    catalog["whatsapp_senders"][0].pop("phone_number")
    monkeypatch.setattr("moengage_draft_batches.catalog_for_row", lambda *args: catalog)
    creator = DraftCreation("apparel", APPAREL_USER, catalog, writer, allow_sqlite_for_tests=True)
    queue = DraftBatchQueue("apparel", APPAREL_USER, catalog, allow_sqlite_for_tests=True, creator=creator)
    return state, writer, catalog, queue


def reviewed_candidate_hash(row, catalog):
    item = prepare_batch([row], "apparel", catalog, APPAREL_USER["email"],
                         source_type="server_catalog")["items"][0]
    assert item["status"] == "preview_ready", item["issues"]
    return hashlib.sha256(json.dumps(
        item["candidate_v5_payload"], sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def stored_attempt(row, catalog):
    with db.get_db() as conn:
        return dict(conn.execute(
            "SELECT * FROM moengage_draft_attempts "
            "WHERE account=? AND workspace_id=? AND source_ref=? AND row_id=?",
            ("apparel", catalog["workspace_id"], row["source_ref"], row["row_id"]),
        ).fetchone())


def stored_retry_history(row, catalog):
    with db.get_db() as conn:
        return [dict(item) for item in conn.execute(
            "SELECT * FROM moengage_draft_retry_history "
            "WHERE account=? AND workspace_id=? AND source_ref=? AND row_id=?",
            ("apparel", catalog["workspace_id"], row["source_ref"], row["row_id"]),
        ).fetchall()]


@pytest.mark.parametrize("placeholders", [{}, {"1": "Customer"}])
def test_incomplete_apparel_draft_is_verified_without_audience_or_schedule(apparel_provider, placeholders):
    state, writer, catalog = apparel_provider
    template = catalog["whatsapp_templates"][0]
    template["body"] = template["template_content"]["body"] = "Hello {{1}}, your {{2}} is ready."
    state["templates"][0]["meta_data"]["content"]["body"] = template["body"]
    row = {key: value for key, value in row_for().items() if key in (
        "account", "brand", "workspace_id", "source_ref", "row_id", "channel", "campaign_name",
        "whatsapp_sender", "whatsapp_template_id",
    )}
    row["whatsapp_placeholders"] = json.dumps(placeholders)
    worker = DraftCreation("apparel", APPAREL_USER, catalog, writer, allow_sqlite_for_tests=True)
    result = worker.create(row)
    assert result["state"] == "VERIFIED"
    assert worker.create(row) == result
    assert len(writes(state)) == 1
    draft = state["created"]
    assert not set(draft) & {
        "new_segmentation_data", "dt", "laterDate", "time", "timezone", "timezoneName",
        "conversion", "clickTrackHours", "impTrackHours",
    }
    wa = draft["whatsapp_data"]
    assert wa["body_placeholders"] == placeholders
    assert not set(wa) & {"header_placeholders", "button_placeholders", "linksTrackingList", "cards"}
    saved = writer.get(CAMPAIGN_ID)
    assert not set(saved) & {"segmentation_details", "scheduling_details", "conversion_goals", "goal_tracking"}


@pytest.mark.parametrize("placeholders", [
    {"3": "Unexpected"}, {"1": "Customer", "{{1}}": "Alias"}, {"customer": "Customer"},
    {"1": ""}, {"1": 42}, [], None,
])
def test_apparel_partial_values_still_require_live_numbered_slots(apparel_provider, placeholders):
    state, writer, _ = apparel_provider
    requested = payload()
    wa = requested["campaign_content"]["content"]["whatsapp"]
    template = state["templates"][0]
    sender_id, sender = next(iter(state["senders"]["Karix"].items()))
    wa.update(sender_id=sender_id, sender_name=sender["sender_name"], template_id=template["id"],
              body_placeholders=placeholders)
    with pytest.raises(ValueError, match="placeholder"):
        writer.prepare(requested)
    assert not writes(state)


@pytest.mark.parametrize("changed", [
    None, "body_placeholders", "header_placeholders", "button_placeholders", "linksTrackingList",
    "audience", "schedule", "goals", "tracking",
])
def test_apparel_supplied_fields_round_trip_or_require_review(apparel_provider, changed):
    state, writer, catalog = apparel_provider
    if changed in ("body_placeholders", "header_placeholders", "button_placeholders", "linksTrackingList"):
        requested = prepare_batch([row_for()], "apparel", catalog, APPAREL_USER["email"],
                                  source_type="apparel_whatsapp_brief")["items"][0]["candidate_v5_payload"]
        prepared = writer.prepare(requested)
        wa = copy.deepcopy(prepared["campaign_content"]["content"]["whatsapp"])
        wa["sender"] = "Karix"
        wa[changed] = [] if changed == "linksTrackingList" else {"different": "changed"}
        state["saved_overrides"]["whatsapp_data"] = wa
    elif changed == "audience":
        state["saved_overrides"]["new_segmentation_data"] = {"included_filters": {}}
    elif changed == "schedule":
        state["saved_overrides"].update(dt="2026-10-30T13:00:00.000Z", laterDate="10/30/2026", time="06:30 pm")
    elif changed == "goals":
        goals = copy.deepcopy(catalog["goal_reference"]["conversion"])
        goals["primary"]["rc"] = "USD"
        state["saved_overrides"]["conversion"] = goals
    elif changed == "tracking":
        state["saved_overrides"].update(clickTrackHours=9, impTrackHours=9)
    worker = DraftCreation("apparel", APPAREL_USER, catalog, writer, allow_sqlite_for_tests=True)
    result = worker.create(row_for())
    assert result["state"] == ("VERIFIED" if changed is None else "NEEDS_REVIEW")
    assert worker.create(row_for()) == result
    assert len(writes(state)) == 1


@pytest.mark.parametrize("action_type,action_value,expected", [
    ("STATIC", "https://www.example.com/shop?category=tili&utm_source=whatsapp", None),
    ("DYNAMIC", "{{7}}", {"{{7}}": "https://www.example.com/shop?category=tili&utm_source=whatsapp"}),
    ("DYNAMIC", "https://www.example.com/{{7}}", {"{{7}}": "shop?category=tili&utm_source=whatsapp"}),
    ("DYNAMIC_LINK_TRACKING", "", {"{{1}}": "https://www.example.com/shop?category=tili&utm_source=whatsapp"}),
])
def test_yearless_client_brief_uses_full_template_cta_without_sheet_edits(apparel_provider, monkeypatch, action_type, action_value, expected):
    import apparel_whatsapp as apparel
    import moengage_workspaces as workspaces
    from apparel_whatsapp_brief import read_sheet_values
    from tests.test_apparel_whatsapp_content import SHOP

    state, writer, base = apparel_provider
    template = state["templates"][0]
    template["meta_data"]["content"] = {
        "body": "Hey there,\nYour Fall 2026 wardrobe starts here.",
        "buttons": {"call_to_action": [
            {"action": "NAVIGATION", "action_type": action_type, "button_text": "Shop Now", "action_value": action_value},
        ]},
    }
    state["template_summaries"] = copy.deepcopy(state["templates"])
    state["template_summaries"][0]["meta_data"]["content"] = {"body": template["meta_data"]["content"]["body"]}
    state["responses"] = {("POST", "/v2/custom-segments/dashboard"): (200, {
        "status": "success", "custom_segments": [],
    })}
    monkeypatch.setattr(workspaces, "list_workspace_choices", lambda *args: [
        {"id": base["workspace_id"], "name": "VS"},
    ])
    monkeypatch.setattr(workspaces, "portal_session", lambda *args: {
        "base_url": writer.base_url, "headers": writer.headers,
    })
    monkeypatch.setattr(apparel, "enrich_catalog", lambda catalog, *args: {**base, **catalog})
    values = [
        ["Brief Date", "", "26th Aug"], ["Send Date and Day", "", "29th Aug"],
        ["Send Time", "", "9:00 AM"], ["Campaign Name", "", "Fall new arrivals"],
        ["SenderID", "", base["whatsapp_senders"][0]["number"]],
        ["TemplateID", "", template["id"]], ["CTALink", "", SHOP],
    ]
    row = read_sheet_values(values, "VS", "client-sheet")[0]
    catalog = workspaces.workspace_catalog("apparel", APPAREL_USER, base["workspace_id"], template_ref=template["id"])
    row["workspace_id"] = catalog["workspace_id"]
    worker = DraftCreation("apparel", APPAREL_USER, catalog, writer, allow_sqlite_for_tests=True)
    result = worker.create(row)
    assert result["state"] == "VERIFIED", result
    assert len(writes(state)) == 1
    saved = state["created"]
    assert saved["dt"] == "2026-08-29T03:30:00.000Z"
    wa = saved["whatsapp_data"]
    assert wa["template_id"] == template["id"]
    if expected is not None:
        assert wa["button_placeholders"] == expected
    else:
        assert "button_placeholders" not in wa
    assert row["cta_raw"] == SHOP and row["send_date"] == "29th Aug"


@pytest.mark.parametrize("change,expected", [
    ("unchanged", "verified"), ("audience", "mismatch"),
    ("older_draft", "mismatch"), ("missing", "not_found"),
])
def test_uncertain_apparel_create_reconciles_read_only_without_duplicate_posts(apparel_provider, monkeypatch, change, expected):
    from moengage_draft_batches import DraftBatchQueue
    state, writer, catalog = apparel_provider
    original_request = requests.request

    def lost_ack(method, url, **kwargs):
        result = original_request(method, url, **kwargs)
        if method == "POST" and urlsplit(url).path == "/v1.0/campaigns/draft":
            raise requests.Timeout("Acknowledgement lost after provider accepted the draft")
        return result

    monkeypatch.setattr(requests, "request", lost_ack)
    worker = DraftCreation("apparel", APPAREL_USER, catalog, writer, allow_sqlite_for_tests=True)
    row = row_for()
    monkeypatch.setattr("moengage_draft_batches.catalog_for_row", lambda *args: catalog)
    queue = DraftBatchQueue("apparel", APPAREL_USER, catalog, allow_sqlite_for_tests=True, creator=worker)
    batch = queue.stage([row], row["source_ref"])
    assert queue.create_row(batch["batch_id"], row["row_id"])["items"][0]["status"] == "UNCERTAIN"
    monkeypatch.setattr(requests, "request", original_request)
    if change == "audience":
        state["saved_overrides"]["new_segmentation_data"] = {"included_filters": {}}
    elif change == "older_draft":
        state["saved_overrides"]["c_cr_t"] = "2020-01-01T00:00:00+00:00"
    elif change == "missing":
        state["membership"] = False
    result = queue.reconcile_row(batch["batch_id"], row["row_id"])
    assert result["reconciliation"]["state"] == expected
    after = queue.create_row(batch["batch_id"], row["row_id"])["items"][0]
    assert after["status"] == ("VERIFIED" if expected == "verified" else "UNCERTAIN")
    assert after["campaign_id"] == (CAMPAIGN_ID if expected == "verified" else None)
    assert len(writes(state)) == 1


def test_rejected_save_preserves_safe_provider_reason_without_exposing_session(apparel_provider):
    state, writer, catalog = apparel_provider
    state["responses"] = {("POST", "/v1.0/campaigns/draft"): (400, {
        "status": "error", "message": "Missing delivery. Authorization: offline-test",
    })}
    worker = DraftCreation("apparel", APPAREL_USER, catalog, writer, allow_sqlite_for_tests=True)
    result = worker.create(row_for())
    assert result["state"] == "UNCERTAIN"
    assert "HTTP 400" in result["issue"] and "Missing delivery" in result["issue"]
    assert "offline-test" not in result["issue"]
    worker.create(row_for())
    assert len(writes(state)) == 1


@pytest.mark.parametrize("apparel_provider", ["CK"], indirect=True)
def test_approved_retry_preserves_rejected_attempt_and_replays_without_third_post(apparel_queue):
    state, _, catalog, queue = apparel_queue
    worker = queue.creator
    original_row = row_for("CK", row_id="WhatsApp!DJ")
    state["responses"] = {("POST", "/v1.0/campaigns/draft"): (400, {
        "status": "error", "message": "Campaign delivery is required",
    })}
    assert worker.create(original_row)["state"] == "UNCERTAIN"
    original_attempt = stored_attempt(original_row, catalog)
    assert original_attempt["state"] == "UNCERTAIN"
    assert original_attempt["campaign_id"] is None
    assert state["created"] is None and len(writes(state)) == 1
    assert worker.create(original_row)["state"] == "UNCERTAIN"
    assert len(writes(state)) == 1

    state["responses"].clear()
    reviewed_row = {**original_row, "scheduled_at": "2026-11-08T09:00:00+05:30"}
    digest = reviewed_candidate_hash(reviewed_row, catalog)
    retried = worker.retry_once(original_row, reviewed_row, digest)
    assert retried["state"] == "VERIFIED"
    assert retried["campaign_id"] == CAMPAIGN_ID
    assert len(writes(state)) == 2
    assert state["created"]["dt"] == "2026-11-08T03:30:00.000Z"
    assert writes(state)[0][3]["campaign_data"]["dt"] == "2026-10-29T13:00:00.000Z"

    retry_attempt = stored_attempt(reviewed_row, catalog)
    assert retry_attempt["idempotency_key"] != original_attempt["idempotency_key"]
    assert retry_attempt["attempted_at"] >= original_attempt["attempted_at"]
    history, = stored_retry_history(original_row, catalog)
    assert json.loads(history["original_attempt_json"]) == original_attempt
    assert json.loads(history["original_row_json"]) == original_row
    assert history["original_attempted_at"] == original_attempt["attempted_at"]
    assert history["approved_by"] in (APPAREL_USER["sub"], APPAREL_USER["email"])
    assert history["approved_at"] >= original_attempt["attempted_at"]
    assert history["retry_idempotency_key"] == retry_attempt["idempotency_key"]
    assert history["retry_payload_hash"] == digest

    restarted = DraftCreation("apparel", APPAREL_USER, catalog, queue.creator.writer,
                              allow_sqlite_for_tests=True)
    replay = restarted.retry_once(original_row, reviewed_row, digest)
    assert (replay["state"], replay["campaign_id"]) == ("VERIFIED", CAMPAIGN_ID)
    assert restarted.create(reviewed_row)["campaign_id"] == CAMPAIGN_ID
    assert stored_retry_history(original_row, catalog) == [history]
    assert stored_attempt(reviewed_row, catalog) == retry_attempt
    assert len(writes(state)) == 2


@pytest.mark.parametrize("apparel_provider", ["CK"], indirect=True)
def test_approved_retry_recovers_lost_ack_using_original_schedule_without_history(apparel_queue, monkeypatch):
    state, writer, catalog, queue = apparel_queue
    original_row = row_for("CK", row_id="WhatsApp!DJ")
    original_request = requests.request

    def lost_ack(method, url, **kwargs):
        response = original_request(method, url, **kwargs)
        if method == "POST" and urlsplit(url).path == "/v1.0/campaigns/draft":
            raise requests.Timeout("Acknowledgement lost after provider accepted the draft")
        return response

    monkeypatch.setattr(requests, "request", lost_ack)
    assert queue.creator.create(original_row)["state"] == "UNCERTAIN"
    original_attempt = stored_attempt(original_row, catalog)
    monkeypatch.setattr(requests, "request", original_request)
    # An earlier empty search is not authorization to skip a fresh check.
    state["membership"] = False
    assert queue.creator.reconcile(original_row)["state"] == "not_found"
    state["membership"] = True
    reviewed_row = {**original_row, "scheduled_at": "2026-11-08T09:00:00+05:30"}
    digest = reviewed_candidate_hash(reviewed_row, catalog)
    recovered = queue.creator.retry_once(original_row, reviewed_row, digest)
    assert (recovered["state"], recovered["campaign_id"]) == ("VERIFIED", CAMPAIGN_ID)
    assert recovered["recovered_existing"] is True
    assert writer.get(CAMPAIGN_ID)["scheduling_details"]["start_time"] == "2026-10-29T18:30:00"
    assert stored_retry_history(original_row, catalog) == []
    after = stored_attempt(original_row, catalog)
    assert after["idempotency_key"] == original_attempt["idempotency_key"]
    assert after["attempted_at"] == original_attempt["attempted_at"]
    assert after["state"] == "VERIFIED" and after["campaign_id"] == CAMPAIGN_ID
    assert len(writes(state)) == 1


@pytest.mark.parametrize("apparel_provider", ["CK"], indirect=True)
def test_active_maybe_sent_cannot_be_rearmed_by_an_approved_retry(apparel_queue, monkeypatch):
    state, _, catalog, queue = apparel_queue
    original_row = row_for("CK", row_id="WhatsApp!DJ")
    reviewed_row = {**original_row, "scheduled_at": "2026-11-08T09:00:00+05:30"}
    digest = reviewed_candidate_hash(reviewed_row, catalog)
    original_request = requests.request
    entered, release = threading.Event(), threading.Event()

    def paused_create(method, url, **kwargs):
        if method == "POST" and urlsplit(url).path == "/v1.0/campaigns/draft":
            entered.set()
            if not release.wait(5):
                raise requests.Timeout("Test did not release the original create")
        return original_request(method, url, **kwargs)

    monkeypatch.setattr(requests, "request", paused_create)
    with ThreadPoolExecutor(max_workers=1) as pool:
        active = pool.submit(queue.creator.create, original_row)
        try:
            assert entered.wait(5)
            reservation = stored_attempt(original_row, catalog)
            assert reservation["state"] == "MAYBE_SENT"
            try:
                queue.creator.retry_once(original_row, reviewed_row, digest)
            except (ValueError, PermissionError):
                pass
            assert stored_attempt(original_row, catalog) == reservation
            assert stored_retry_history(original_row, catalog) == []
            assert not writes(state)
        finally:
            release.set()
        assert active.result(timeout=5)["state"] == "VERIFIED"
    assert len(writes(state)) == 1


@pytest.mark.parametrize("apparel_provider", ["CK"], indirect=True)
def test_overlapping_retry_approvals_do_not_dispatch_a_second_retry_post(apparel_queue, monkeypatch):
    state, _, catalog, queue = apparel_queue
    original_row = row_for("CK", row_id="WhatsApp!DJ")
    state["responses"] = {("POST", "/v1.0/campaigns/draft"): (400, {"status": "error"})}
    assert queue.creator.create(original_row)["state"] == "UNCERTAIN"
    original_attempt = stored_attempt(original_row, catalog)
    state["responses"].clear()
    reviewed_row = {**original_row, "scheduled_at": "2026-11-08T09:00:00+05:30"}
    digest = reviewed_candidate_hash(reviewed_row, catalog)
    original_request = requests.request
    accepted, release = threading.Event(), threading.Event()

    def paused_ack(method, url, **kwargs):
        response = original_request(method, url, **kwargs)
        if method == "POST" and urlsplit(url).path == "/v1.0/campaigns/draft":
            accepted.set()
            if not release.wait(5):
                raise requests.Timeout("Test did not release the retry acknowledgement")
        return response

    monkeypatch.setattr(requests, "request", paused_ack)
    with ThreadPoolExecutor(max_workers=1) as pool:
        retry = pool.submit(queue.creator.retry_once, original_row, reviewed_row, digest)
        try:
            assert accepted.wait(5)
            try:
                queue.creator.retry_once(original_row, reviewed_row, digest)
            except (ValueError, PermissionError):
                pass
            assert len(writes(state)) == 2
            history, = stored_retry_history(original_row, catalog)
            assert json.loads(history["original_attempt_json"]) == original_attempt
            assert history["retry_idempotency_key"] == stored_attempt(reviewed_row, catalog)["idempotency_key"]
        finally:
            release.set()
        assert retry.result(timeout=5)["state"] == "VERIFIED"
    assert queue.creator.retry_once(original_row, reviewed_row, digest)["campaign_id"] == CAMPAIGN_ID
    assert len(writes(state)) == 2
    assert stored_retry_history(original_row, catalog) == [history]


@pytest.mark.parametrize("apparel_provider", ["CK"], indirect=True)
def test_approved_retry_accepts_source_aliases_that_resolve_to_the_same_template_and_sender(apparel_queue):
    state, _, catalog, queue = apparel_queue
    original = row_for("CK", row_id="WhatsApp!DJ")
    state["responses"] = {("POST", "/v1.0/campaigns/draft"): (400, {"status": "error"})}
    assert queue.creator.create(original)["state"] == "UNCERTAIN"
    state["responses"].clear()
    reviewed = {
        **original, "scheduled_at": "2026-08-29T09:00:00+05:30",
        "whatsapp_template_id": catalog["whatsapp_templates"][0]["id"],
        "whatsapp_sender": catalog["whatsapp_senders"][0]["name"],
    }
    result = queue.creator.retry_once(original, reviewed, reviewed_candidate_hash(reviewed, catalog))
    assert (result["state"], result["campaign_id"]) == ("VERIFIED", CAMPAIGN_ID)
    assert state["created"]["whatsapp_data"]["template_id"] == catalog["whatsapp_templates"][0]["id"]
    assert len(writes(state)) == 2
    history, = stored_retry_history(original, catalog)
    assert json.loads(history["original_row_json"]) == original
