"""Offline end-to-end workspace selection against independently scoped portal stores."""

import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

import db
import moengage_draft_batches as batches
import moengage_draft_creation as creation
import moengage_whatsapp_worker as transport
import moengage_workspaces as workspaces
from moengage_draft_batches import BatchAccessDenied, DraftBatchQueue
from moengage_draft_creation import DraftCreation
from moengage_preview import rows_from_jira_brief
from tests.test_moengage_whatsapp_bulk import ROW_WA, USER

SERVICES = "62aad9b5fb3e82178aac76a3"
CAPITAL = "6516b0db87ee0c3c4499dc68"
FOREIGN = "aaaaaaaaaaaaaaaaaaaaaaaa"
V5_KEY = "0KYUNUW5WODKX5ZFVAGPVL0U"
TEMPLATE_BODY = "Dear {{1}}, {{2}} is ready. Thank you {{1}}."
INVENTORIES = {
    SERVICES: {"name": "Services_TC", "sender": "111111111111111111111111",
               "template": "222222222222222222222222", "segment": "333333333333333333333333"},
    CAPITAL: {"name": "Tata Capital", "sender": "444444444444444444444444",
              "template": "555555555555555555555555", "segment": "666666666666666666666666"},
}
BASE_CATALOG = {
    "account": "tata", "workspace_id": V5_KEY,
    "whatsapp_workspaces": [{"id": key, "name": value["name"]} for key, value in INVENTORIES.items()],
    # Intentionally unusable as portal metadata: falling back to the root must fail.
    "segments": [], "whatsapp_senders": [], "whatsapp_templates": [],
}


def row(workspace_id=None, *, workspace=None, row_id="route-1"):
    result = {**ROW_WA, "row_id": row_id, "source_ref": "workspace-brief.csv",
              "segment_name": "Shared Audience", "whatsapp_sender": "Shared Sender",
              "whatsapp_template_id": "shared_template", "whatsapp_template_name": "shared_template"}
    for key in ("workspace_id", "segment_id", "whatsapp_sender_id"):
        result.pop(key, None)
    if workspace_id is not None:
        result["workspace_id"] = workspace_id
    if workspace is not None:
        result["workspace"] = workspace
    return result


@pytest.fixture
def portal(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_SQLITE_PATH", tmp_path / "workspace-routing.db")
    for name in ("DATABASE_URL", "POSTGRES_URL", "POSTGRESQL_URL"):
        monkeypatch.delenv(name, raising=False)
    db.init_database()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    state = {"requests": [], "sessions": [], "drafts": {SERVICES: {}, CAPITAL: {}}}
    state["templates"] = {
        workspace_id: [{"id": inventory["template"], "name": "shared_template", "status": "ACTIVE",
                        "meta_data": {"sender_ids": [inventory["sender"]], "provider": "Karix",
                                      "state": "APPROVED", "content": {"body": TEMPLATE_BODY}}}]
        for workspace_id, inventory in INVENTORIES.items()
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.respond("GET")

        def do_POST(self):
            self.respond("POST")

        def respond(self, method):
            workspace_id = self.headers.get("Authorization", "").removeprefix("Bearer offline-")
            if workspace_id not in INVENTORIES:
                self.send_error(403)
                return
            inventory = INVENTORIES[workspace_id]
            drafts = state["drafts"][workspace_id]
            path = urlsplit(self.path).path
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length)) if length else None
            state["requests"].append((workspace_id, method, path, copy.deepcopy(body)))
            if method == "GET" and path == "/whatsapp/settings":
                result = {"sender_settings": {"Karix": {
                    "999999999999999999999999": {"sender_name": "Other Sender",
                                                 "whatsapp_business_no": "+910000000000"},
                    inventory["sender"]: {"sender_name": "Shared Sender",
                                           "whatsapp_business_no": "+919876543210"},
                }}}
            elif method == "GET" and path == "/template_metadata":
                # Live metadata carries loggedIn=false even on a successful authenticated response.
                result = {"data": state["templates"][workspace_id], "status": True, "code": 200, "loggedIn": False}
            elif method == "POST" and path == "/v2/custom-segments/dashboard":
                result = {"custom_segments": [{"id": inventory["segment"], "name": "Shared Audience",
                                               "deleted": False, "archived": False}]}
            elif method == "POST" and path == "/v1.0/campaigns/draft":
                selected = body["campaign_data"]["whatsapp_data"]
                if (selected.get("sender_id") != inventory["sender"]
                        or selected.get("template_id") != inventory["template"]
                        or selected.get("sender") != "Karix"):
                    self.send_error(400, "Selection does not belong to this workspace")
                    return
                campaign_id = ("a" if workspace_id == SERVICES else "b") + f"{len(drafts) + 1:023x}"
                drafts[campaign_id] = copy.deepcopy(body["campaign_data"])
                result = {"data": {"id": campaign_id}}
            elif method == "GET" and path.startswith("/draft/campaigns/get/"):
                campaign_id = path.rsplit("/", 1)[1]
                if campaign_id not in drafts:
                    self.send_error(404)
                    return
                result = {"data": {"campaign_draft": {"draft": {**copy.deepcopy(drafts[campaign_id]),
                                                                "_id": "eeeeeeeeeeeeeeeeeeeeeeee"}}}}
            elif method == "POST" and path == "/draft/campaigns":
                result = {"data": {"campaigns": [{"_id": {"$oid": campaign_id}, "channel": "WHATSAPP",
                                                   "delivery_type": "ONE_TIME"} for campaign_id in drafts]}}
            else:
                self.send_error(404)
                return
            encoded = json.dumps({"status": "success", **result, **state.get("envelope", {})}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = {"workspace_id": V5_KEY, "base_url": f"http://127.0.0.1:{server.server_address[1]}",
              "bearer_token": "offline-account", "refresh_token": "offline-refresh", "cookie": ""}
    state["config"] = config

    def load_catalog(account):
        if account == "tata":
            return copy.deepcopy(BASE_CATALOG)
        return {"account": account, "workspace_id": "other-v5-key",
                "whatsapp_workspaces": [{"id": FOREIGN, "name": "Other Account"}]}

    def bind_session(account, *, workspace_id, **snapshot):
        assert account == "tata"
        assert snapshot["bearer_token"] == "offline-account"
        state["sessions"].append(workspace_id)
        return {**snapshot, "workspace_id": workspace_id, "bearer_token": "offline-" + workspace_id}

    monkeypatch.setattr(creation, "load_server_catalog", load_catalog)
    monkeypatch.setattr(workspaces, "get_moengage_config", lambda account: config)
    monkeypatch.setattr(workspaces, "check_moengage_session", bind_session)
    monkeypatch.setattr(batches, "catalog_for_row", workspaces.catalog_for_row)
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def creator(workspace_id):
    catalog = workspaces.workspace_catalog("tata", USER, workspace_id)
    return DraftCreation("tata", USER, catalog, transport.WhatsAppDraftWriter("tata", workspace_id),
                         allow_sqlite_for_tests=True)


def queue(creators=None, catalog=None):
    return DraftBatchQueue("tata", USER, catalog or copy.deepcopy(BASE_CATALOG),
                           allow_sqlite_for_tests=True, creator=creators)


def writes(portal):
    return [request for request in portal["requests"] if request[1:3] == ("POST", "/v1.0/campaigns/draft")]


@pytest.mark.parametrize("selector", [{}, {"workspace_id": ""}, {"workspace": ""},
                                      {"workspace_id": V5_KEY}, {"workspace": "services_tc"},
                                      {"workspace": "Unknown"}, {"workspace_id": FOREIGN},
                                      {"workspace_id": SERVICES, "workspace": "Tata Capital"}])
def test_missing_unknown_or_conflicting_workspace_blocks_before_any_write(portal, selector):
    brief = {**row(), **selector}
    batch_queue = queue()
    batch = batch_queue.stage([brief], brief["source_ref"])
    assert batch["ready"] == 0
    assert batch["blocked"] == 1
    assert batch["items"][0]["candidate_v5_payload"] is None
    batch_queue.create_row(batch["batch_id"], brief["row_id"])
    assert not writes(portal)
    assert portal["requests"] == []


def test_catalogs_resolve_overlapping_names_to_each_workspaces_actual_ids(portal):
    assert workspaces.list_workspace_choices("tata", USER) == BASE_CATALOG["whatsapp_workspaces"]
    for workspace_id, expected in INVENTORIES.items():
        catalog = workspaces.workspace_catalog("tata", USER, expected["name"])
        assert catalog["workspace_id"] == workspace_id
        assert catalog["workspace_name"] == expected["name"]
        assert catalog["segments"] == [{"id": expected["segment"], "name": "Shared Audience"}]
        assert [(sender["sender_id"], sender["name"]) for sender in catalog["whatsapp_senders"]] == [
            ("999999999999999999999999", "Other Sender"), (expected["sender"], "Shared Sender")]
        assert catalog["whatsapp_templates"] == [{"id": expected["template"], "name": "shared_template",
                                                  "sender_ids": [expected["sender"]], "provider": "KARIX",
                                                  "display_name": "shared_template", "body": TEMPLATE_BODY}]
    assert set(portal["sessions"]) == {SERVICES, CAPITAL}
    assert portal["config"]["workspace_id"] == V5_KEY
    assert portal["config"]["bearer_token"] == "offline-account"
    assert not writes(portal)


def test_mixed_workspace_batch_writes_and_verifies_in_independent_remote_stores(portal):
    batch_queue = queue({workspace_id: creator(workspace_id) for workspace_id in INVENTORIES})
    briefs = [row(workspace="Services_TC", row_id="services"), row(CAPITAL, row_id="capital")]
    batch = batch_queue.stage(briefs, briefs[0]["source_ref"])
    assert (batch["ready"], batch["blocked"]) == (2, 0)
    assert [item["workspace_id"] for item in batch["items"]] == [SERVICES, CAPITAL]
    for brief in briefs:
        batch = batch_queue.create_row(batch["batch_id"], brief["row_id"])
    assert [item["status"] for item in batch["items"]] == ["VERIFIED", "VERIFIED"]
    assert len(writes(portal)) == 2
    for item, workspace_id in zip(batch["items"], (SERVICES, CAPITAL), strict=True):
        assert item["campaign_id"] in portal["drafts"][workspace_id]
        assert item["campaign_id"] not in portal["drafts"][CAPITAL if workspace_id == SERVICES else SERVICES]
        saved = portal["drafts"][workspace_id][item["campaign_id"]]
        assert saved["whatsapp_data"]["sender_id"] == INVENTORIES[workspace_id]["sender"]
        assert saved["whatsapp_data"]["template_id"] == INVENTORIES[workspace_id]["template"]
        assert INVENTORIES[workspace_id]["segment"] in json.dumps(saved)


def test_same_source_identity_is_idempotent_within_actual_workspace_not_across_workspaces(portal):
    creators = {workspace_id: creator(workspace_id) for workspace_id in INVENTORIES}
    batch_queue = queue(creators)
    staged = []
    for workspace_id in (SERVICES, CAPITAL):
        brief = row(workspace_id)
        batch = batch_queue.stage([brief], brief["source_ref"])
        first = batch_queue.create_row(batch["batch_id"], brief["row_id"])
        assert first["items"][0]["status"] == "VERIFIED"
        repeated = batch_queue.create_row(batch["batch_id"], brief["row_id"])
        assert repeated["items"][0]["campaign_id"] == first["items"][0]["campaign_id"]
        assert creators[workspace_id].create(brief)["campaign_id"] == first["items"][0]["campaign_id"]
        staged.append(batch)
    duplicate = batch_queue.stage([row(SERVICES)], row(SERVICES)["source_ref"])
    with pytest.raises(ValueError):
        batch_queue.create_row(duplicate["batch_id"], "route-1")
    assert len(writes(portal)) == 2
    assert [len(portal["drafts"][key]) for key in (SERVICES, CAPITAL)] == [1, 1]
    with db.get_db() as conn:
        attempts = conn.execute("SELECT workspace_id,state FROM moengage_draft_attempts ORDER BY workspace_id").fetchall()
    assert {attempt["workspace_id"]: attempt["state"] for attempt in attempts} == {
        SERVICES: "VERIFIED", CAPITAL: "VERIFIED"}


def test_persisted_batch_cannot_be_retargeted_by_reconstructed_queue_or_changed_input(portal):
    services = creator(SERVICES)
    capital = creator(CAPITAL)
    brief = row(SERVICES)
    batch = queue(services).stage([brief], brief["source_ref"])
    brief["workspace_id"] = CAPITAL
    with pytest.raises(PermissionError):
        queue(capital).create_row(batch["batch_id"], brief["row_id"])
    with pytest.raises(BatchAccessDenied):
        queue(capital, {**BASE_CATALOG, "workspace_id": CAPITAL}).get(batch["batch_id"])
    assert not writes(portal)
    result = queue(services).create_row(batch["batch_id"], brief["row_id"])
    assert result["items"][0]["status"] == "VERIFIED"
    assert result["items"][0]["workspace_id"] == SERVICES
    assert len(portal["drafts"][SERVICES]) == 1
    assert not portal["drafts"][CAPITAL]


@pytest.mark.parametrize("selector", [{}, {"workspace_id": CAPITAL}, {"workspace_id": FOREIGN},
                                      {"workspace": "Tata Capital"}])
def test_bound_creator_refuses_missing_or_different_workspace_without_reserving(portal, selector):
    service = creator(SERVICES)
    result = service.create({**row(), **selector})
    assert result["state"] == "BLOCKED"
    assert result["campaign_id"] is None
    assert not writes(portal)
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM moengage_draft_attempts").fetchone()["n"] == 0


def test_cross_account_registry_is_not_bypassed_by_superadmin_or_portal_session(portal):
    superadmin = {**USER, "tenant_id": "all", "role": "superadmin"}
    for account, selector in (("tata", FOREIGN), ("other", SERVICES)):
        with pytest.raises(PermissionError):
            workspaces.workspace_catalog(account, superadmin, selector)
        with pytest.raises(PermissionError):
            workspaces.portal_session(account, selector)
    with pytest.raises(PermissionError):
        workspaces.workspace_catalog("other", USER, FOREIGN)
    assert portal["sessions"] == []
    assert portal["requests"] == []


def test_uninjected_queue_constructs_and_binds_production_creator_for_each_row(portal, monkeypatch):
    for suffix in ("ZERO_CHARGE_CONFIRMED", "NO_PUBLISH_SCOPE_CONFIRMED", "LIVE_ENABLED",
                   "ALLOW_SQLITE", "ALLOW_ALL_ROWS"):
        monkeypatch.setenv("MOENGAGE_DRAFT_TATA_" + suffix, "true")
    monkeypatch.setenv("MOENGAGE_DRAFT_TATA_LIVE_TEST_OPERATOR_EMAIL", USER["email"])
    for suffix in ("LIVE_TEST_ROWS_JSON", "LIVE_TEST_SOURCE_REF", "LIVE_TEST_ROW_ID", "LIVE_TEST_SEGMENT_ID"):
        monkeypatch.delenv("MOENGAGE_DRAFT_TATA_" + suffix, raising=False)
    batch_queue = queue()
    briefs = [row(SERVICES, row_id="first"), row(CAPITAL, row_id="second")]
    batch = batch_queue.stage(briefs, briefs[0]["source_ref"])
    for brief in briefs:
        batch = batch_queue.create_row(batch["batch_id"], brief["row_id"])
    assert [item["status"] for item in batch["items"]] == ["VERIFIED", "VERIFIED"]
    assert [request[0] for request in writes(portal)] == [SERVICES, CAPITAL]
    for item, workspace_id in zip(batch["items"], (SERVICES, CAPITAL), strict=True):
        assert item["campaign_id"] in portal["drafts"][workspace_id]


def body_row(workspace_id=SERVICES, body="Dear Naman, your offer is ready. Thank you Naman."):
    brief = {**row(workspace_id), "body": body}
    for key in ("whatsapp_sender", "whatsapp_template_id", "whatsapp_template_name", "whatsapp_placeholders"):
        brief.pop(key, None)
    return brief


@pytest.mark.parametrize("workspace_id", [SERVICES, CAPITAL])
def test_rendered_body_selects_only_target_template_and_extracts_repeated_placeholders(portal, workspace_id):
    batch_queue = queue(creator(workspace_id))
    brief = body_row(workspace_id)
    staged = batch_queue.stage([brief], brief["source_ref"])
    assert staged["ready"] == 1
    selected = staged["items"][0]["candidate_v5_payload"]["campaign_content"]["content"]["whatsapp"]
    assert selected["sender_id"] == INVENTORIES[workspace_id]["sender"]
    assert selected["template_id"] == INVENTORIES[workspace_id]["template"]
    assert selected["body_placeholders"] == {"{{1}}": "Naman", "{{2}}": "your offer"}
    result = batch_queue.create_row(staged["batch_id"], brief["row_id"])
    assert result["items"][0]["status"] == "VERIFIED"
    saved = portal["drafts"][workspace_id][result["items"][0]["campaign_id"]]["whatsapp_data"]
    assert saved["body_placeholders"] == {"{{1}}": "Naman", "{{2}}": "your offer"}
    other = CAPITAL if workspace_id == SERVICES else SERVICES
    assert not portal["drafts"][other]


@pytest.mark.parametrize("failure", ["ambiguous_body", "repeated_value_disagrees", "no_body_or_template",
                                    "foreign_sender", "foreign_template"])
def test_body_matching_never_guesses_ambiguous_missing_or_foreign_selection(portal, failure):
    brief = body_row()
    if failure == "ambiguous_body":
        duplicate = copy.deepcopy(portal["templates"][SERVICES][0])
        duplicate.update(id="777777777777777777777777", name="same_body_different_template")
        portal["templates"][SERVICES].append(duplicate)
    elif failure == "repeated_value_disagrees":
        brief["body"] = "Dear Naman, your offer is ready. Thank you Different."
    elif failure == "no_body_or_template":
        brief.pop("body")
    elif failure == "foreign_sender":
        brief["whatsapp_sender_id"] = INVENTORIES[CAPITAL]["sender"]
    else:
        brief["whatsapp_template_id"] = INVENTORIES[CAPITAL]["template"]
    batch_queue = queue()
    staged = batch_queue.stage([brief], brief["source_ref"])
    assert staged["blocked"] == 1
    assert staged["items"][0]["candidate_v5_payload"] is None
    batch_queue.create_row(staged["batch_id"], brief["row_id"])
    assert not writes(portal)


def test_jira_workspace_metadata_survives_adaptation_and_routes_rendered_copy(portal):
    brief = {"issue_key": "SWCM-ROUTING", "account": "tata", "summary": "Reviewed WhatsApp brief",
             "description_text": "Campaign Name | Routed offer\nMoEngage workspace | Services_TC",
             "whatsapp_templates": [{"body": "Dear Naman, your offer is ready. Thank you Naman."}]}
    overrides = {"segment_name": "Shared Audience", "scheduled_at": ROW_WA["scheduled_at"],
                 "timezone": ROW_WA["timezone"]}
    rows = rows_from_jira_brief(brief, overrides, "tata")
    assert rows[0]["workspace"] == "Services_TC"
    batch_queue = queue(creator(SERVICES))
    staged = batch_queue.stage(rows, "SWCM-ROUTING")
    assert staged["ready"] == 1
    assert staged["items"][0]["workspace_id"] == SERVICES
    result = batch_queue.create_row(staged["batch_id"], "whatsapp:1")
    assert result["items"][0]["status"] == "VERIFIED"
    assert result["items"][0]["campaign_id"] in portal["drafts"][SERVICES]
    assert not portal["drafts"][CAPITAL]


def test_email_and_push_keep_base_catalog_even_when_brief_names_whatsapp_workspace(portal):
    catalog = {**copy.deepcopy(BASE_CATALOG), "segments": [{"id": "base-segment", "name": "Base audience"}],
               "subscription_categories": ["Offers"],
               "email_senders": [{"from_address": "mail@example.com", "sender_name": "Tata",
                                  "connector_type": "SENDGRID", "connector_name": "Primary"}],
               "push_platforms": [{"platform": "ANDROID", "notification_channel": "promotions"}]}
    common = {"account": "tata", "source_ref": "email-push.csv", "workspace": "Services_TC",
              "segment_id": "base-segment", "scheduled_at": ROW_WA["scheduled_at"],
              "timezone": ROW_WA["timezone"]}
    email = {**common, "row_id": "email", "channel": "EMAIL", "campaign_name": "Existing Email",
             "content_type": "PROMOTIONAL", "subscription_category": "Offers",
             "from_address": "mail@example.com", "subject": "Offer", "html_content": "<p>Reviewed copy</p>"}
    push = {**common, "row_id": "push", "channel": "PUSH", "campaign_name": "Existing Push",
            "push_platform": "ANDROID", "push_title": "Reviewed title", "push_message": "Reviewed message",
            "click_url": "https://example.com/offer"}
    staged = queue(catalog=catalog).stage([email, push], "email-push.csv")
    assert staged["ready"] == 2
    assert [item["workspace_id"] for item in staged["items"]] == [V5_KEY, V5_KEY]
    assert [item["candidate_v5_payload"]["channel"] for item in staged["items"]] == ["EMAIL", "PUSH"]
    assert all("base-segment" in json.dumps(item["candidate_v5_payload"]) for item in staged["items"])
    assert portal["sessions"] == []
    assert portal["requests"] == []


def test_workspace_display_names_survive_stage_reload_and_create(portal):
    creators = {workspace_id: creator(workspace_id) for workspace_id in INVENTORIES}
    batch_queue = queue(creators)
    briefs = [row(SERVICES, row_id="services"), row(CAPITAL, row_id="capital")]
    staged = batch_queue.stage(briefs, briefs[0]["source_ref"])
    expected = [INVENTORIES[key]["name"] for key in (SERVICES, CAPITAL)]
    assert [item["workspace_name"] for item in staged["items"]] == expected
    reloaded = queue(creators).get(staged["batch_id"])
    assert [item["workspace_name"] for item in reloaded["items"]] == expected
    created = batch_queue.create_row(staged["batch_id"], "services")
    assert [item["workspace_name"] for item in created["items"]] == expected
    assert created["workspace_id"] == V5_KEY


def test_padded_whatsapp_channel_still_routes_explicit_portal_workspace(portal):
    brief = {**row(SERVICES), "channel": " whatsapp "}
    batch_queue = queue(creator(SERVICES))
    staged = batch_queue.stage([brief], brief["source_ref"])
    assert staged["ready"] == 1
    assert staged["items"][0]["workspace_id"] == SERVICES
    result = batch_queue.create_row(staged["batch_id"], brief["row_id"])
    assert result["items"][0]["status"] == "VERIFIED"
    assert [request[0] for request in writes(portal)] == [SERVICES]


def test_duplicate_row_ids_across_destinations_are_not_ambiguously_selectable(portal):
    batch_queue = queue({workspace_id: creator(workspace_id) for workspace_id in INVENTORIES})
    briefs = [row(SERVICES), row(CAPITAL)]
    staged = batch_queue.stage(briefs, briefs[0]["source_ref"])
    assert (staged["ready"], staged["blocked"]) == (0, 2)
    with pytest.raises(ValueError, match="Duplicate row_id"):
        batch_queue.create_row(staged["batch_id"], briefs[0]["row_id"])
    assert not writes(portal)


def _created_batch(portal, monkeypatch):
    service = creator(SERVICES)
    batch_queue = queue(service)
    brief = row(SERVICES)
    staged = batch_queue.stage([brief], brief["source_ref"])
    original_get = service.writer.get

    def unavailable(campaign_id):
        raise TimeoutError("Draft readback temporarily unavailable")

    monkeypatch.setattr(service.writer, "get", unavailable)
    created = batch_queue.create_row(staged["batch_id"], brief["row_id"])
    assert created["items"][0]["status"] == "CREATED"
    assert created["items"][0]["campaign_id"] in portal["drafts"][SERVICES]
    monkeypatch.setattr(service.writer, "get", original_get)
    return batch_queue, service, brief, created


def test_created_row_recheck_is_readonly_and_preserves_real_id(portal, monkeypatch):
    batch_queue, service, brief, created = _created_batch(portal, monkeypatch)
    result = batch_queue.create_row(created["batch_id"], brief["row_id"])
    assert result["items"][0]["status"] == "VERIFIED"
    assert result["items"][0]["campaign_id"] == created["items"][0]["campaign_id"]
    assert len(writes(portal)) == 1
    assert len(portal["drafts"][SERVICES]) == 1


@pytest.mark.parametrize("failure", ["preflight_blocked", "unexpected_error", "rate_limit"])
def test_created_recheck_failure_never_loses_known_draft_or_reposts(portal, monkeypatch, failure):
    batch_queue, service, brief, created = _created_batch(portal, monkeypatch)
    if failure == "preflight_blocked":
        service.catalog = {**service.catalog, "segments": []}
    else:
        error = creation.RateLimitError("local cap") if failure == "rate_limit" else RuntimeError("recheck failed")

        def fail(row):
            raise error

        monkeypatch.setattr(service, "create", fail)
    if failure == "rate_limit":
        with pytest.raises(creation.RateLimitError):
            batch_queue.create_row(created["batch_id"], brief["row_id"])
        result = batch_queue.get(created["batch_id"])
    else:
        result = batch_queue.create_row(created["batch_id"], brief["row_id"])
    assert result["items"][0]["status"] == "CREATED"
    assert result["items"][0]["campaign_id"] == created["items"][0]["campaign_id"]
    assert len(writes(portal)) == 1


def test_created_row_without_matching_durable_attempt_cannot_post_again(portal, monkeypatch):
    batch_queue, service, brief, created = _created_batch(portal, monkeypatch)
    with db.get_db() as conn:
        conn.execute("DELETE FROM moengage_draft_attempts")
    result = batch_queue.create_row(created["batch_id"], brief["row_id"])
    assert result["items"][0]["status"] == "CREATED"
    assert result["items"][0]["campaign_id"] == created["items"][0]["campaign_id"]
    assert len(writes(portal)) == 1


def test_stale_preview_click_cannot_claim_a_newer_created_result(portal, monkeypatch):
    service = creator(SERVICES)
    active_queue = queue(service)
    brief = row(SERVICES)
    staged = active_queue.stage([brief], brief["source_ref"])
    entered, release = threading.Event(), threading.Event()
    calls = []
    real_create = service.create

    def track(row):
        calls.append(row["row_id"])
        return real_create(row)

    monkeypatch.setattr(service, "create", track)

    class PausedCreators(dict):
        def __getitem__(self, key):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("Test did not release creator selection")
            return super().__getitem__(key)

    stale_queue = queue(PausedCreators({SERVICES: service}))
    results = []
    errors = []

    def stale_click():
        try:
            results.append(stale_queue.create_row(staged["batch_id"], brief["row_id"]))
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=stale_click)
    thread.start()
    try:
        assert entered.wait(5)

        def unavailable(campaign_id):
            raise TimeoutError("Readback unavailable")

        monkeypatch.setattr(service.writer, "get", unavailable)
        created = active_queue.create_row(staged["batch_id"], brief["row_id"])
        assert created["items"][0]["status"] == "CREATED"
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert errors == []
    assert results[0]["items"][0]["status"] == "CREATED"
    assert calls == [brief["row_id"]]
    assert len(writes(portal)) == 1


def test_live_template_disappearing_after_stage_blocks_without_consuming_identity(portal):
    service = creator(SERVICES)
    batch_queue = queue(service)
    brief = row(SERVICES)
    first = batch_queue.stage([brief], brief["source_ref"])
    assert first["ready"] == 1
    templates = portal["templates"][SERVICES]
    portal["templates"][SERVICES] = []
    rejected = batch_queue.create_row(first["batch_id"], brief["row_id"])
    assert rejected["items"][0]["status"] == "blocked"
    assert rejected["items"][0]["candidate_v5_payload"] is None
    assert not writes(portal)
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM moengage_draft_attempts").fetchone()["n"] == 0
    portal["templates"][SERVICES] = templates
    second = batch_queue.stage([brief], brief["source_ref"])
    result = batch_queue.create_row(second["batch_id"], brief["row_id"])
    assert result["items"][0]["status"] == "VERIFIED"
    assert len(writes(portal)) == 1


@pytest.mark.parametrize("envelope", [{"status": False}, {"status": 1}, {"success": False}])
def test_http_success_with_failed_metadata_envelope_cannot_stage_a_live_row(portal, envelope):
    portal["envelope"] = envelope
    brief = row(CAPITAL)
    staged = queue().stage([brief], brief["source_ref"])
    assert staged["ready"] == 0
    assert staged["items"][0]["status"] == "blocked"
    assert staged["items"][0]["candidate_v5_payload"] is None
    assert not writes(portal)
