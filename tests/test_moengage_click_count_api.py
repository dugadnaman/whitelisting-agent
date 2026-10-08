"""HTTP-level click-count checks with real identities and an isolated portal simulator."""

from datetime import UTC, datetime, timedelta

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
        self.requests = []
        self.posts = 0
        self.filters = None
        self.states = ["queued", "running", "success"]
        self.query_database = "TataCapital"
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
            return user["member"] and rule["id"] == BASE_ID
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
            payload = {"custom_segments": [self.base] if database == "TataCapital" else []}
        elif path == f"/v2/custom-segments/dashboard/{BASE_ID}/meta":
            payload = {"cs_details": self.base}
        elif path == "/segmentation/recent_query/count":
            self.posts += 1
            self.filters = kwargs["json"]["filters"]["included_filters"]
            payload = {"success": True, "rq_id": QUERY_ID}
        elif path == "/segmentation/recent_query/get_bulk":
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            matched = [user for user in self.users if self.matches(user, self.filters)]
            payload = {"data": [{"_id": QUERY_ID, "db_name": self.query_database, "status": state,
                                 "user_count": len(matched), "reachability_count": {
                                     "total_reachable_count": sum(user["reachable"] for user in matched)}}]}
        else:
            raise AssertionError(f"Unexpected portal request: {method} {path}")
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
    portal.states = ["running", "failure"]
    accepted = client.post(PREFIX + "/queries", json=submission(portal), headers=headers).json()
    path = PREFIX + "/queries/" + accepted["query_id"]
    running = client.get(path, params={"workspace_id": WORKSPACE_ID}, headers=headers)
    failed = client.get(path, params={"workspace_id": WORKSPACE_ID}, headers=headers)
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
