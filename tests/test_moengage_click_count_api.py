"""HTTP-level click-count checks with real identities and an isolated portal simulator."""

from datetime import UTC, datetime, timedelta
from threading import Lock

import jwt
import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth
import moengage_click_count as count

WORKSPACE_ID = "6516b0db87ee0c3c4499dc68"
OTHER_WORKSPACE_ID = "62aad9735e6ff766f85bb0b8"
FOREIGN_WORKSPACE_ID = "6ab615b5762ad13d1b9b8999"
BASE_ID = "6ac6134b701a0236ad3a2926"
QUERY_ID = "6ac775ce963c53bf0610984b"
PREFIX = "/api/moengage/click-count"


class Portal:
    """Evaluate the requested segment against a tiny event corpus, not echoed counts."""

    def __init__(self):
        self.end = (datetime.now(UTC).date() - timedelta(days=2)).isoformat()
        self.start = (datetime.now(UTC).date() - timedelta(days=3)).isoformat()
        self.base = {"id": BASE_ID, "name": "Imported test cohort", "type": "FILE_V2",
                     "source": "IMPORT_USERS", "deleted": False, "archived": False,
                     "created_time": self.start + "T10:00:00.000000"}
        self.bases_by_workspace = {WORKSPACE_ID: [self.base], OTHER_WORKSPACE_ID: []}
        self.metadata_by_id = {BASE_ID: self.base}
        self.overrides = {}
        self.requests = []
        self.posts = 0
        self.queries = {}
        self.lock = Lock()
        self.states = ["queued", "running", "success"]
        self.query_database = None
        self.databases = {WORKSPACE_ID: "TataCapital", OTHER_WORKSPACE_ID: "WealthDB"}
        self.apps = [
            {"id": WORKSPACE_ID, "name": "Tata Capital", "account_id": count.TATA_PORTAL_ACCOUNT_ID,
             "activated": True, "is_test": False},
            {"id": OTHER_WORKSPACE_ID, "name": "Wealth", "account_id": count.TATA_PORTAL_ACCOUNT_ID,
             "activated": True, "is_test": False},
            {"id": FOREIGN_WORKSPACE_ID, "name": "Other organization", "account_id": "foreign-account",
             "activated": True, "is_test": False},
        ]
        self.users = [
            {"member": True, "reachable": True, "events": [
                ("MOE_SMS_CLICKED", self.start + "T00:00:00.000Z"),
                ("MOE_SMS_CLICKED", self.start + "T00:00:00.001Z"),
                ("MOE_WHATSAPP_CLICKED", self.end + "T10:00:00.000Z"),
                ("MOE_EMAIL_CLICK", self.end + "T11:00:00.000Z")]},
            {"member": True, "reachable": False, "events": [
                ("NOTIFICATION_CLICKED_IOS_MOE", self.end + "T23:59:59.999Z")]},
            {"member": False, "reachable": True, "events": [
                ("NOTIFICATION_CLICKED_MOE", self.end + "T12:00:00.000Z")]},
            {"member": True, "reachable": True, "events": [
                ("MOE_EMAIL_CLICK", (datetime.fromisoformat(self.end).date() + timedelta(days=1)).isoformat() + "T00:00:00.000Z")]},
            {"member": True, "reachable": True, "events": [
                ("EMAIL_OPENED", self.end + "T12:00:00.000Z")]},
        ]

    def matches(self, user, rule):
        if rule.get("filter_type") == "custom_segments":
            return user["member"] and rule["id"] in user.get("base_ids", {BASE_ID})
        if rule.get("filter_type") == "actions":
            bounds = rule["primary_time_range"]
            hits = sum(name == rule["action_name"] and bounds["value"] <= instant <= bounds["value1"]
                       for name, instant in user["events"])
            return hits >= rule["execution"]["count"]
        predicates = (self.matches(user, child) for child in rule["filters"])
        return all(predicates) if rule["filter_operator"] == "and" else any(predicates)

    def request(self, method, url, **kwargs):
        path = url.removeprefix("https://dashboard-03.moengage.com")
        self.requests.append((method, path))
        selected = kwargs["headers"]["authorization"].removeprefix("Bearer selected-")
        database = self.databases.get(selected, "TataCapital")
        if path == "/dash/auth/listApps":
            payload = {"data": self.apps}
        elif path == "/dash/auth/changeApp":
            payload = {"code": 200, "status": "success", "data": {
                "bearer": "selected-" + kwargs["params"]["app_id"], "app_access_details": "ALLOWED"}}
        elif path == "/appsettings":
            payload = {"data": {"time_zone": "Asia/Kolkata"}}
        elif path == "/getLoggedInUserData":
            payload = {"data": {"dbName": database, "account_id": count.TATA_PORTAL_ACCOUNT_ID}}
        elif path == "/v2/custom-segments/dashboard":
            payload = {"custom_segments": self.bases_by_workspace.get(selected, [])}
        elif path.startswith("/v2/custom-segments/dashboard/") and path.endswith("/meta"):
            base_id = path.rsplit("/", 2)[1]
            payload = {"cs_details": self.metadata_by_id.get(base_id)}
        elif path == "/segmentation/recent_query/count":
            with self.lock:
                self.posts += 1
                query_id = f"{int(QUERY_ID, 16) + self.posts - 1:024x}"
                self.queries[query_id] = {
                    "filters": kwargs["json"]["filters"]["included_filters"],
                    "states": self.states.copy(),
                    "database": database,
                }
            payload = {"success": True, "rq_id": query_id}
        elif path == "/segmentation/recent_query/get_bulk":
            assert kwargs["json"]["query_type"] == "filter"
            query_id, = kwargs["json"]["ids"]
            query = self.queries[query_id]
            states = query["states"]
            state = states.pop(0) if len(states) > 1 else states[0]
            matched = [user for user in self.users if self.matches(user, query["filters"])]
            payload = {"data": [{"_id": query_id, "db_name": self.query_database or query["database"], "status": state,
                                 "user_count": len(matched), "reachability_count": {
                                     "total_reachable_count": sum(user["reachable"] for user in matched)}}]}
        else:
            raise AssertionError(f"Unexpected portal request: {method} {path}")
        payload = self.overrides.get(path, payload)
        response = requests.Response()
        response.status_code = 200
        response.cookies = requests.cookies.RequestsCookieJar()
        response.json = lambda: payload
        return response


@pytest.fixture
def portal(monkeypatch):
    portal = Portal()
    token = jwt.encode({"exp": datetime.now(UTC) + timedelta(hours=2)},
                       "test-portal-signing-key-0123456789abcdef", algorithm="HS256")
    monkeypatch.setattr(count, "get_moengage_config", lambda account: {
        "base_url": "https://dashboard-03.moengage.com", "bearer_token": token,
        "refresh_token": "test-refresh", "cookie": "moe_uuid=test-browser",
    })
    monkeypatch.setenv("TATA_MOENGAGE_ACCOUNT_ID", count.TATA_PORTAL_ACCOUNT_ID)
    monkeypatch.setattr(count.requests, "request", portal.request)
    return portal


@pytest.fixture
def client(portal):
    app = FastAPI()
    app.include_router(count.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def submission(portal):
    return {"workspace_id": WORKSPACE_ID, "base_id": BASE_ID, "end_date": portal.end}


@pytest.mark.parametrize("method,path", [
    ("GET", "/workspaces"), ("GET", "/bases"), ("GET", f"/bases/{BASE_ID}"),
    ("POST", "/queries"), ("GET", "/queries/not-a-ticket"),
])
@pytest.mark.parametrize("authorization", [None, "Bearer malformed-token", "Basic not-a-bearer"])
def test_all_count_routes_require_real_authentication(client, portal, method, path, authorization):
    headers = {"Authorization": authorization} if authorization else {}
    kwargs = {"json": submission(portal)} if method == "POST" else {"params": {"workspace_id": WORKSPACE_ID}}
    response = client.request(method, PREFIX + path, headers=headers, **kwargs)
    assert response.status_code == 401
    assert portal.requests == []


@pytest.mark.parametrize("tenant,role,expected", [
    ("tata", "operator", 200), ("tata", "admin", 200), ("all", "superadmin", 200),
    ("bajaj", "admin", 403), ("apparel", "operator", 403),
])
def test_workspace_access_uses_database_tenant_and_role(client, portal, provision_user, tenant, role, expected):
    _, headers = provision_user(tenant=tenant, role=role)
    response = client.get(PREFIX + "/workspaces", headers=headers)
    assert response.status_code == expected
    if expected == 200:
        assert {row["id"] for row in response.json()["workspaces"]} == {WORKSPACE_ID, OTHER_WORKSPACE_ID}
    else:
        assert portal.requests == []


@pytest.mark.parametrize("mutation,expected", [
    ("disabled", 401), ("deleted", 401), ("tenant", 403),
])
def test_existing_tokens_do_not_override_revoked_or_changed_users(client, portal, provision_user, mutation, expected):
    user, headers = provision_user(tenant="tata")
    with auth._auth_db() as database:
        if mutation == "disabled":
            database.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user["id"],))
        elif mutation == "deleted":
            database.execute("DELETE FROM users WHERE id = ?", (user["id"],))
        else:
            database.execute("UPDATE users SET tenant_id = 'bajaj' WHERE id = ?", (user["id"],))
    response = client.post(PREFIX + "/queries", json=submission(portal), headers=headers)
    assert response.status_code == expected
    assert portal.posts == 0


def test_expired_access_token_is_rejected_before_portal_calls(client, portal, provision_user):
    user, _ = provision_user(tenant="tata")
    token = auth.create_access_token(user["id"], user["email"], user["tenant_id"], user["role"],
                                     user["name"], expires_delta=timedelta(seconds=-1))
    response = client.get(PREFIX + "/workspaces", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 401
    assert portal.requests == []


def test_deeply_nested_unauthenticated_jwt_is_rejected_without_server_error(client, portal):
    import base64
    header = '{"alg":"HS256","nested":' + "[" * 1200 + "0" + "]" * 1200 + "}"
    encoded = base64.urlsafe_b64encode(header.encode()).decode().rstrip("=")
    token = encoded + ".eyJzdWIiOiJ1bnRydXN0ZWQifQ.invalid-signature"
    response = client.get(PREFIX + "/workspaces", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 401
    assert portal.requests == []


@pytest.mark.parametrize("claim,value", [
    ("exp", []), ("exp", None), ("exp", float("inf")),
    ("iat", []), ("iat", None), ("iat", float("inf")), ("nbf", None),
])
def test_malformed_signed_authentication_claims_are_unauthorized_not_server_errors(client, portal, provision_user, claim, value):
    _, headers = provision_user(tenant="tata")
    claims = jwt.decode(headers["Authorization"][7:], auth.configured_jwt_secret(), algorithms=["HS256"])
    claims[claim] = value
    token = jwt.encode(claims, auth.configured_jwt_secret(), algorithm="HS256")
    response = client.get(PREFIX + "/workspaces", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 401
    assert portal.requests == []


def test_http_lifecycle_deduplicates_repeated_cross_channel_clicks_and_requires_membership(client, portal, provision_user):
    _, headers = provision_user(tenant="tata")
    accepted = client.post(PREFIX + "/queries", json=submission(portal), headers=headers)
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["start_date"] == portal.start
    assert body["end_date"] == portal.end
    observed = []
    for _ in range(3):
        result = client.get(PREFIX + "/queries/" + body["query_id"],
                            params={"workspace_id": WORKSPACE_ID}, headers=headers)
        assert result.status_code == 200
        observed.append(result.json())
    assert [row["status"] for row in observed] == ["queued", "running", "success"]
    assert observed[-1]["user_count"] == 2
    assert observed[-1]["reachable_users"] == 1
    assert portal.posts == 1


def test_http_completed_empty_cohort_is_zero_not_pending(client, portal, provision_user):
    _, headers = provision_user(tenant="tata")
    portal.users = []
    portal.states = ["success"]
    accepted = client.post(PREFIX + "/queries", json=submission(portal), headers=headers).json()
    result = client.get(PREFIX + "/queries/" + accepted["query_id"],
                        params={"workspace_id": WORKSPACE_ID}, headers=headers)
    assert result.status_code == 200
    assert result.json()["status"] == "success"
    assert result.json()["user_count"] == 0
    assert result.json()["reachable_users"] == 0


def test_http_native_provider_failure_is_terminal_without_a_false_zero_or_resubmission(client, portal, provision_user):
    _, headers = provision_user(tenant="tata")
    portal.states = ["received", "running", "failure"]
    accepted = client.post(PREFIX + "/queries", json=submission(portal), headers=headers).json()
    path = PREFIX + "/queries/" + accepted["query_id"]
    queued = client.get(path, params={"workspace_id": WORKSPACE_ID}, headers=headers)
    running = client.get(path, params={"workspace_id": WORKSPACE_ID}, headers=headers)
    failed = client.get(path, params={"workspace_id": WORKSPACE_ID}, headers=headers)
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued"
    assert queued.json()["user_count"] is None
    assert queued.json()["reachable_users"] is None
    assert running.status_code == 200
    assert running.json()["status"] == "running"
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert failed.json()["user_count"] is None
    assert failed.json()["reachable_users"] is None
    assert "error" in failed.json()
    assert portal.posts == 1


@pytest.mark.parametrize("updates,expected", [
    ({"workspace_id": FOREIGN_WORKSPACE_ID}, 403),
    ({"workspace_id": OTHER_WORKSPACE_ID}, 404),
    ({"base_id": "../../other"}, 400),
    ({"end_date": "2026-02-30"}, 400),
    ({"end_date": ""}, 400),
    ({"end_date": 123}, 422),
    ({"start_date": "2000-01-01"}, 422),
])
def test_invalid_submission_never_creates_an_upstream_query(client, portal, provision_user, updates, expected):
    _, headers = provision_user(tenant="tata")
    response = client.post(PREFIX + "/queries", json={**submission(portal), **updates}, headers=headers)
    assert response.status_code == expected
    assert portal.posts == 0


@pytest.mark.parametrize("boundary", ["before_creation", "future"])
def test_invalid_calendar_bounds_do_not_submit_queries(client, portal, provision_user, boundary):
    _, headers = provision_user(tenant="tata")
    end = (datetime.fromisoformat(portal.start).date() - timedelta(days=1)).isoformat() if boundary == "before_creation" else (datetime.now(UTC).date() + timedelta(days=3)).isoformat()
    response = client.post(PREFIX + "/queries", json={**submission(portal), "end_date": end}, headers=headers)
    assert response.status_code == 400
    assert portal.posts == 0


@pytest.mark.parametrize("event", [
    "MOE_WHATSAPP_CLICKED", "MOE_EMAIL_CLICK", "MOE_SMS_CLICKED",
    "NOTIFICATION_CLICKED_MOE", "NOTIFICATION_CLICKED_IOS_MOE",
])
def test_each_channel_counts_a_repeated_clicker_once(client, portal, provision_user, event):
    _, headers = provision_user(tenant="tata")
    portal.users = [{"member": True, "reachable": True, "events": [
        (event, portal.end + "T12:00:00.000Z"), (event, portal.end + "T12:00:01.000Z")]}]
    portal.states = ["success"]
    accepted = client.post(PREFIX + "/queries", json=submission(portal), headers=headers).json()
    result = client.get(PREFIX + "/queries/" + accepted["query_id"],
                        params={"workspace_id": WORKSPACE_ID}, headers=headers)
    assert result.status_code == 200
    assert result.json()["user_count"] == 1


def test_query_ticket_cannot_cross_workspaces_or_be_used_as_access_token(client, portal, provision_user):
    _, headers = provision_user(tenant="tata")
    accepted = client.post(PREFIX + "/queries", json=submission(portal), headers=headers).json()
    ticket = accepted["query_id"]
    response = client.get(PREFIX + "/queries/" + ticket,
                          params={"workspace_id": OTHER_WORKSPACE_ID}, headers=headers)
    assert response.status_code == 404
    response = client.get(PREFIX + "/workspaces", headers={"Authorization": "Bearer " + ticket})
    assert response.status_code == 401
    response = client.get(PREFIX + "/queries/" + headers["Authorization"].removeprefix("Bearer "),
                          params={"workspace_id": WORKSPACE_ID}, headers=headers)
    assert response.status_code == 404


def test_completed_query_from_another_database_is_not_disclosed(client, portal, provision_user):
    _, headers = provision_user(tenant="tata")
    accepted = client.post(PREFIX + "/queries", json=submission(portal), headers=headers).json()
    portal.query_database = "AnotherOrganization"
    result = client.get(PREFIX + "/queries/" + accepted["query_id"],
                        params={"workspace_id": WORKSPACE_ID}, headers=headers)
    assert result.status_code == 404
    assert "user_count" not in result.json()


def test_database_reassignment_invalidates_existing_query_before_reading_results(client, portal, provision_user):
    _, headers = provision_user(tenant="tata")
    accepted = client.post(PREFIX + "/queries", json=submission(portal), headers=headers).json()
    portal.databases[WORKSPACE_ID] = "ReassignedDatabase"
    result = client.get(PREFIX + "/queries/" + accepted["query_id"],
                        params={"workspace_id": WORKSPACE_ID}, headers=headers)
    assert result.status_code == 404
    assert not any(path == "/segmentation/recent_query/get_bulk" for _, path in portal.requests)


def test_provider_request_budgets_preserve_workspace_checks_and_avoid_metadata_profile(client, portal, provision_user):
    _, headers = provision_user(tenant="tata")
    listed = client.get(PREFIX + "/bases", params={"workspace_id": WORKSPACE_ID}, headers=headers)
    assert listed.status_code == 200
    assert listed.json()["bases"][0]["start_date"] == portal.start
    assert portal.requests == [
        ("GET", "/dash/auth/listApps"), ("GET", "/dash/auth/changeApp"),
        ("GET", "/appsettings"), ("POST", "/v2/custom-segments/dashboard"),
    ]
    portal.requests.clear()
    details = client.get(PREFIX + f"/bases/{BASE_ID}", params={"workspace_id": WORKSPACE_ID}, headers=headers)
    assert details.status_code == 200
    assert len(portal.requests) == 5
    assert ("POST", "/v2/custom-segments/dashboard") in portal.requests
    assert ("GET", f"/v2/custom-segments/dashboard/{BASE_ID}/meta") in portal.requests
    assert not any(path == "/getLoggedInUserData" for _, path in portal.requests)
    portal.requests.clear()
    accepted = client.post(PREFIX + "/queries", json=submission(portal), headers=headers)
    assert accepted.status_code == 200
    assert len(portal.requests) == 7
    assert portal.requests[-1] == ("POST", "/segmentation/recent_query/count")
    portal.requests.clear()
    polled = client.get(PREFIX + "/queries/" + accepted.json()["query_id"],
                        params={"workspace_id": WORKSPACE_ID}, headers=headers)
    assert polled.status_code == 200
    assert len(portal.requests) == 5
    assert portal.requests[-1] == ("POST", "/segmentation/recent_query/get_bulk")


def test_ten_thousand_bases_are_enriched_by_one_list_without_per_base_requests(client, portal, provision_user):
    _, headers = provision_user(tenant="tata")
    portal.bases_by_workspace[WORKSPACE_ID] = [
        {**portal.base, "id": f"{index:024x}", "name": f"Imported base {index}"}
        for index in range(10000)
    ]
    response = client.get(PREFIX + "/bases", params={"workspace_id": WORKSPACE_ID}, headers=headers)
    assert response.status_code == 200
    rows = response.json()["bases"]
    assert len(rows) == 10000
    assert all(row["start_date"] == portal.start for row in rows)
    assert all(row["created_at"].endswith("+00:00") for row in rows)
    assert len(portal.requests) == 4
    assert portal.requests.count(("POST", "/v2/custom-segments/dashboard")) == 1
    assert not any(path.endswith("/meta") for _, path in portal.requests)


@pytest.mark.parametrize("created", [None, "", False, 1, "not-a-timestamp", "2026-02-30T00:00:00Z"])
def test_http_invalid_optional_timestamp_can_fall_back_to_authoritative_metadata(client, portal, provision_user, created):
    _, headers = provision_user(tenant="tata")
    portal.bases_by_workspace[WORKSPACE_ID] = [{**portal.base, "created_time": created}]
    listed = client.get(PREFIX + "/bases", params={"workspace_id": WORKSPACE_ID}, headers=headers)
    assert listed.status_code == 200
    assert listed.json()["bases"] == [{"id": BASE_ID, "name": portal.base["name"]}]
    details = client.get(PREFIX + f"/bases/{BASE_ID}", params={"workspace_id": WORKSPACE_ID}, headers=headers)
    assert details.status_code == 200
    assert details.json()["start_date"] == portal.start
    accepted = client.post(PREFIX + "/queries", json=submission(portal), headers=headers)
    assert accepted.status_code == 200
    assert accepted.json()["start_date"] == portal.start
    assert portal.posts == 1


@pytest.mark.parametrize("created", [
    None, "", False, 1, "not-a-timestamp", "2026-02-30T00:00:00Z",
    "0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59Z",
])
def test_http_invalid_authoritative_timestamp_returns_no_date_or_query(client, portal, provision_user, created):
    _, headers = provision_user(tenant="tata")
    portal.metadata_by_id[BASE_ID] = {**portal.base, "created_time": created}
    details = client.get(PREFIX + f"/bases/{BASE_ID}", params={"workspace_id": WORKSPACE_ID}, headers=headers)
    assert details.status_code == 502
    assert "created_at" not in details.json()
    assert "start_date" not in details.json()
    accepted = client.post(PREFIX + "/queries", json=submission(portal), headers=headers)
    assert accepted.status_code == 502
    assert portal.posts == 0


def test_http_future_base_creation_cannot_be_silently_replaced_by_selected_end_date(client, portal, provision_user):
    _, headers = provision_user(tenant="tata")
    future = (datetime.now(UTC).date() + timedelta(days=3)).isoformat()
    portal.metadata_by_id[BASE_ID] = {**portal.base, "created_time": future + "T00:00:00Z"}
    response = client.post(PREFIX + "/queries", json=submission(portal), headers=headers)
    assert response.status_code == 400
    assert "before" in response.json()["detail"]
    assert portal.posts == 0


def test_http_earliest_calendar_year_uses_zero_padded_query_bounds(client, portal, provision_user):
    _, headers = provision_user(tenant="tata")
    portal.overrides["/appsettings"] = {"data": {"time_zone": "UTC"}}
    portal.metadata_by_id[BASE_ID] = {**portal.base, "created_time": "0001-01-01T00:00:00Z"}
    response = client.post(PREFIX + "/queries", json={**submission(portal), "end_date": "0001-01-01"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["start_date"] == "0001-01-01"
    query = next(iter(portal.queries.values()))
    actions = query["filters"]["filters"][0]["filters"]
    assert all(action["primary_time_range"]["value"] == "0001-01-01T00:00:00.000Z" for action in actions)
    assert all(action["primary_time_range"]["value1"] == "0001-01-01T23:59:59.999Z" for action in actions)


def test_metadata_for_foreign_workspace_is_rejected_even_if_detail_endpoint_returns_it(client, portal, provision_user):
    _, headers = provision_user(tenant="tata")
    response = client.get(PREFIX + f"/bases/{BASE_ID}", params={"workspace_id": OTHER_WORKSPACE_ID}, headers=headers)
    assert response.status_code == 404
    assert not any(path.endswith("/meta") for _, path in portal.requests)
    assert not any(path == "/getLoggedInUserData" for _, path in portal.requests)


@pytest.mark.parametrize("acknowledgement", [
    {}, {"success": False, "rq_id": QUERY_ID}, {"success": 1, "rq_id": QUERY_ID},
    {"success": True}, {"success": True, "rq_id": None}, {"success": True, "rq_id": 123},
    {"success": True, "rq_id": "invalid"}, {"success": True, "rq_id": QUERY_ID + "0"},
])
def test_unconfirmed_query_submission_is_never_retried_or_given_a_ticket(client, portal, provision_user, acknowledgement):
    _, headers = provision_user(tenant="tata")
    portal.overrides["/segmentation/recent_query/count"] = acknowledgement
    response = client.post(PREFIX + "/queries", json=submission(portal), headers=headers)
    assert response.status_code == 502
    assert "query_id" not in response.json()
    assert portal.posts == 1
    assert portal.requests.count(("POST", "/segmentation/recent_query/count")) == 1


@pytest.mark.parametrize("field,value", [
    ("user_count", None), ("user_count", True), ("user_count", -1), ("user_count", "2"),
    ("user_count", 9007199254740992), ("reachability_count", None),
    ("reachability_count", {"total_reachable_count": False}),
    ("reachability_count", {"total_reachable_count": -1}),
    ("reachability_count", {"total_reachable_count": 3}),
])
def test_http_invalid_completed_counts_never_return_false_zero(client, portal, provision_user, field, value):
    _, headers = provision_user(tenant="tata")
    accepted = client.post(PREFIX + "/queries", json=submission(portal), headers=headers).json()
    row = {"_id": QUERY_ID, "db_name": "TataCapital", "status": "success", "user_count": 2,
           "reachability_count": {"total_reachable_count": 1}}
    portal.overrides["/segmentation/recent_query/get_bulk"] = {"data": [{**row, field: value}]}
    response = client.get(PREFIX + "/queries/" + accepted["query_id"],
                          params={"workspace_id": WORKSPACE_ID}, headers=headers)
    assert response.status_code == 502
    assert "user_count" not in response.json()
    assert "reachable_users" not in response.json()
    assert portal.posts == 1


@pytest.mark.parametrize("rows,expected", [
    (None, 502), ({}, 502), ([None], 502), ([], 404),
    ([{"_id": QUERY_ID + "0", "db_name": "TataCapital", "status": "success", "user_count": 999}], 404),
    ([{"_id": QUERY_ID}, {"_id": QUERY_ID}], 404),
])
def test_malformed_or_ambiguous_query_rows_do_not_supply_counts(client, portal, provision_user, rows, expected):
    _, headers = provision_user(tenant="tata")
    accepted = client.post(PREFIX + "/queries", json=submission(portal), headers=headers).json()
    portal.overrides["/segmentation/recent_query/get_bulk"] = {"data": rows}
    response = client.get(PREFIX + "/queries/" + accepted["query_id"],
                          params={"workspace_id": WORKSPACE_ID}, headers=headers)
    assert response.status_code == expected
    assert "user_count" not in response.json()


def test_simultaneous_queries_keep_dates_bases_counts_and_workspace_tickets_isolated(client, portal, provision_user, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    _, headers = provision_user(tenant="tata")
    second_id = "6ac6134b701a0236ad3a2927"
    second_base = {**portal.base, "id": second_id, "name": "Other workspace cohort"}
    portal.bases_by_workspace[OTHER_WORKSPACE_ID] = [second_base]
    portal.metadata_by_id[second_id] = second_base
    portal.states = ["success"]
    portal.users = [
        {"member": True, "reachable": True, "base_ids": {BASE_ID},
         "events": [("MOE_SMS_CLICKED", portal.start + "T00:00:00.000Z")]},
        {"member": True, "reachable": False, "base_ids": {BASE_ID, second_id},
         "events": [("MOE_SMS_CLICKED", portal.end + "T23:59:59.999Z")]},
        {"member": True, "reachable": True, "base_ids": {second_id},
         "events": [("MOE_EMAIL_CLICK", portal.start + "T00:00:00.000Z")]},
        {"member": True, "reachable": True, "base_ids": {second_id},
         "events": [("MOE_EMAIL_CLICK", portal.end + "T23:59:59.999Z")]},
    ]
    cases = [(WORKSPACE_ID, BASE_ID, portal.start, 1, 1),
             (WORKSPACE_ID, BASE_ID, portal.end, 2, 1),
             (OTHER_WORKSPACE_ID, second_id, portal.start, 1, 1),
             (OTHER_WORKSPACE_ID, second_id, portal.end, 3, 2)]
    barrier = Barrier(len(cases))
    def simultaneous_request(method, url, **kwargs):
        if url.endswith("/segmentation/recent_query/count"):
            barrier.wait(timeout=10)
        return portal.request(method, url, **kwargs)
    monkeypatch.setattr(count.requests, "request", simultaneous_request)
    def submit(case):
        workspace_id, base_id, end, _, _ = case
        response = client.post(PREFIX + "/queries", json={
            "workspace_id": workspace_id, "base_id": base_id, "end_date": end,
        }, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["workspace_id"] == workspace_id
        assert body["base_id"] == base_id
        assert body["end_date"] == end
        return body["query_id"]
    with ThreadPoolExecutor(max_workers=len(cases)) as executor:
        tickets = list(executor.map(submit, cases))
    assert len(set(tickets)) == len(cases)
    assert portal.posts == len(cases)
    for case, ticket in reversed(list(zip(cases, tickets))):
        workspace_id, base_id, end, unique, reachable = case
        claims = count.read_query_ticket(ticket, workspace_id)
        query = portal.queries[claims["rq_id"]]
        assert claims["db_name"] == portal.databases[workspace_id]
        assert query["filters"]["filters"][1]["id"] == base_id
        assert all(action["primary_time_range"]["value1"] == end + "T23:59:59.999Z"
                   for action in query["filters"]["filters"][0]["filters"])
        result = client.get(PREFIX + "/queries/" + ticket,
                            params={"workspace_id": workspace_id}, headers=headers)
        assert result.status_code == 200
        assert result.json()["user_count"] == unique
        assert result.json()["reachable_users"] == reachable
        other_workspace = OTHER_WORKSPACE_ID if workspace_id == WORKSPACE_ID else WORKSPACE_ID
        request_count = len(portal.requests)
        rejected = client.get(PREFIX + "/queries/" + ticket,
                              params={"workspace_id": other_workspace}, headers=headers)
        assert rejected.status_code == 404
        assert len(portal.requests) == request_count


@pytest.mark.parametrize("invalid_metadata", [False, True])
def test_invalid_base_dates_do_not_fetch_database_metadata_before_rejection(client, portal, provision_user, invalid_metadata):
    _, headers = provision_user(tenant="tata")
    if invalid_metadata:
        portal.metadata_by_id[BASE_ID] = {**portal.base, "created_time": "invalid"}
        end = portal.end
    else:
        end = (datetime.fromisoformat(portal.start).date() - timedelta(days=1)).isoformat()
    response = client.post(PREFIX + "/queries", json={**submission(portal), "end_date": end}, headers=headers)
    assert response.status_code == (502 if invalid_metadata else 400)
    assert portal.posts == 0
    assert not any(path == "/getLoggedInUserData" for _, path in portal.requests)
    assert len(portal.requests) == 5


def test_deterministic_randomized_payload_matches_independent_click_membership_oracle():
    from random import Random
    from zoneinfo import ZoneInfo
    random = Random(20261009)
    simulator = Portal()
    supported = ("MOE_WHATSAPP_CLICKED", "MOE_EMAIL_CLICK", "MOE_SMS_CLICKED",
                 "NOTIFICATION_CLICKED_MOE", "NOTIFICATION_CLICKED_IOS_MOE")
    unrelated = ("EMAIL_OPENED", "MOE_SMS_SENT", "MOE_WHATSAPP_DELIVERED")
    other_base_id = "6ac6134b701a0236ad3a2927"
    origin = datetime(2024, 3, 1, 1, 30, tzinfo=UTC)
    def encoded(instant):
        return instant.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    for scenario in range(75):
        base_id = BASE_ID if scenario % 2 == 0 else other_base_id
        timezone = ("Asia/Kolkata", "America/Los_Angeles", "Pacific/Kiritimati")[scenario % 3]
        created = origin + timedelta(days=scenario % 7, milliseconds=random.randrange(1000))
        start = created.astimezone(ZoneInfo(timezone)).date()
        end = start + timedelta(days=random.randrange(7))
        lower = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
        upper = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=UTC) - timedelta(milliseconds=1)
        raw_base = {"id": base_id, "name": "Randomized cohort", "created_time": encoded(created)}
        metadata = count.base_metadata(raw_base, {"timezone": timezone})
        payload = count.click_count_payload(metadata, end.isoformat())
        boundaries = (lower - timedelta(milliseconds=1), lower, upper, upper + timedelta(milliseconds=1))
        users = []
        for index in range(250):
            events = []
            oracle_events = []
            for _ in range(random.randrange(13)):
                channel = random.choice(supported + unrelated)
                instant = (random.choice(boundaries) if random.randrange(3) == 0 else
                           lower + timedelta(milliseconds=random.randrange(-86400000, 8 * 86400000)))
                events.append((channel, encoded(instant)))
                oracle_events.append((channel, instant))
                if random.randrange(3) == 0:
                    events.append((channel, encoded(instant)))
                    oracle_events.append((channel, instant))
            users.append({
                "member": bool(random.randrange(2)), "reachable": bool(random.randrange(2)),
                "base_ids": {candidate for candidate in (BASE_ID, other_base_id) if random.randrange(2)},
                "events": events, "oracle_events": oracle_events,
            })
        # Every scenario exercises all five channels and both inclusive endpoints,
        # as well as one-millisecond exclusions, independently of random sampling.
        for channel in supported:
            for instant in boundaries:
                users.append({"member": True, "reachable": True, "base_ids": {base_id},
                              "events": [(channel, encoded(instant)), (channel, encoded(instant))],
                              "oracle_events": [(channel, instant), (channel, instant)]})
        expected = {
            index for index, user in enumerate(users)
            if user["member"] and base_id in user["base_ids"]
            and any(channel in supported and lower <= instant <= upper
                    for channel, instant in user["oracle_events"])
        }
        observed = {index for index, user in enumerate(users)
                    if simulator.matches(user, payload["filters"]["included_filters"])}
        assert observed == expected, f"Distinct clickers differed in randomized scenario {scenario}."
        reachable = sum(users[index]["reachable"] for index in observed)
        response = count.query_result({
            "_id": QUERY_ID, "db_name": "TataCapital", "status": "success",
            "user_count": len(observed), "reachability_count": {"total_reachable_count": reachable},
        }, QUERY_ID, "TataCapital")
        assert response["user_count"] == len(expected)
        assert response["reachable_users"] == sum(users[index]["reachable"] for index in expected)
