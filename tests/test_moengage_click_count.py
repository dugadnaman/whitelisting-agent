from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from moengage_click_count import base_metadata, click_count_payload, query_result

BASE_ID = "6ab615b5762ad13d1b9b8969"
QUERY_ID = "6ac775ce963c53bf0610984b"
WORKSPACE = {"id": "6516b0db87ee0c3c4499dc68", "name": "Tata Capital", "timezone": "Asia/Kolkata"}


@pytest.mark.parametrize("created,start", [
    ("2026-09-25T06:33:25.015000", "2026-09-25"),
    ("2026-09-24T23:59:59Z", "2026-09-25"),
    ("2026-09-25T00:00:00+00:00", "2026-09-25"),
])
def test_creation_date_uses_workspace_timezone(created, start):
    base = base_metadata({"id": BASE_ID, "name": "October base", "created_time": created}, WORKSPACE)
    assert base["start_date"] == start
    assert datetime.fromisoformat(base["created_at"]).tzinfo == UTC
    assert base["timezone"] == "Asia/Kolkata"


def test_inclusive_date_query_deduplicates_five_channels_and_requires_base():
    base = {"id": BASE_ID, "name": "October base", "start_date": "2026-09-25"}
    payload = click_count_payload(base, "2026-09-25")
    included = payload["filters"]["included_filters"]
    assert included["filter_operator"] == "and"
    channels, membership = included["filters"]
    assert channels["filter_operator"] == "or"
    assert {action["action_name"] for action in channels["filters"]} == {
        "MOE_WHATSAPP_CLICKED", "MOE_EMAIL_CLICK", "MOE_SMS_CLICKED",
        "NOTIFICATION_CLICKED_MOE", "NOTIFICATION_CLICKED_IOS_MOE",
    }
    for action in channels["filters"]:
        assert action["execution"] == {"count": 1, "type": "atleast"}
        assert action["primary_time_range"]["value"] == "2026-09-25T00:00:00.000Z"
        assert action["primary_time_range"]["value1"] == "2026-09-25T23:59:59.999Z"
    assert membership == {"filter_type": "custom_segments", "id": BASE_ID, "name": "October base"}


@pytest.mark.parametrize("end", ["2026-09-24", "2026-02-30", "2026-9-25", "not-a-date"])
def test_invalid_end_range_is_rejected(end):
    with pytest.raises(HTTPException) as error:
        click_count_payload({"id": BASE_ID, "name": "base", "start_date": "2026-09-25"}, end)
    assert error.value.status_code == 400


@pytest.mark.parametrize("unique,reachable", [(0, 0), (5426, 5423)])
def test_unique_count_and_reachable_count_are_distinct(unique, reachable):
    result = query_result({"_id": QUERY_ID, "db_name": "TataCapital", "status": "success",
                           "user_count": unique, "reachability_count": {"total_reachable_count": reachable}},
                          QUERY_ID, "TataCapital")
    assert result["user_count"] == unique
    assert result["reachable_users"] == reachable


@pytest.mark.parametrize("count", [None, "0", False, -1])
def test_missing_or_malformed_unique_count_is_not_zero(count):
    with pytest.raises(HTTPException) as error:
        query_result({"_id": QUERY_ID, "db_name": "TataCapital", "status": "success",
                      "user_count": count, "reachability_count": {"total_reachable_count": 0}}, QUERY_ID, "TataCapital")
    assert error.value.status_code == 502


def test_query_for_other_workspace_is_not_disclosed():
    with pytest.raises(HTTPException) as error:
        query_result({"_id": QUERY_ID, "db_name": "OtherTenant", "status": "success", "user_count": 5}, QUERY_ID, "TataCapital")
    assert error.value.status_code == 404


def test_failed_query_is_explicit_and_does_not_leak_upstream_reason():
    result = query_result({"_id": QUERY_ID, "db_name": "TataCapital", "status": "failed",
                           "failure_reason": "Authorization: secret-token Cookie: secret-cookie"}, QUERY_ID, "TataCapital")
    assert result["status"] == "failed"
    assert result["user_count"] is None
    assert "secret" not in result["error"]


def test_base_from_another_workspace_is_rejected_before_reading_metadata(monkeypatch):
    from moengage_click_count import ClickCountClient
    client = object.__new__(ClickCountClient)
    calls = []
    def request(method, path, **kwargs):
        calls.append(path)
        return {"custom_segments": [{"id": "6ab615b5762ad13d1b9b8999", "name": "selected workspace base",
                                    "type": "FILE_V2", "source": "IMPORT_USERS", "deleted": False}]}
    monkeypatch.setattr(client, "request", request)
    with pytest.raises(HTTPException) as error:
        client.base(BASE_ID)
    assert error.value.status_code == 404
    assert calls == ["/v2/custom-segments/dashboard"]


def test_only_active_imported_file_bases_are_offered(monkeypatch):
    from moengage_click_count import ClickCountClient
    client = object.__new__(ClickCountClient)
    imported = {"id": BASE_ID, "name": "imported", "type": "FILE_V2", "source": "IMPORT_USERS", "deleted": False}
    rows = [imported, {**imported, "source": "CSV_UPLOAD"}, {**imported, "source": "ANALYTICS"},
            {**imported, "deleted": True}, {**imported, "archived": True}]
    monkeypatch.setattr(client, "request", lambda *args, **kwargs: {"custom_segments": rows})
    assert client.bases() == [{"id": BASE_ID, "name": "imported"}]


def test_imported_base_without_count_metadata_uses_creation_date(monkeypatch):
    from moengage_click_count import ClickCountClient, TATA_PORTAL_ACCOUNT_ID
    client = object.__new__(ClickCountClient)
    client.account_id = TATA_PORTAL_ACCOUNT_ID
    base = {"id": BASE_ID, "name": "HLBT_InternalMart_01_Oct", "type": "FILE_V2",
            "source": "IMPORT_USERS", "deleted": False, "archived": False,
            "created_time": "2026-10-07T09:39:23.186000"}
    responses = {
        "/v2/custom-segments/dashboard": {"custom_segments": [base]},
        f"/v2/custom-segments/dashboard/{BASE_ID}/meta": {"cs_details": base},
        "/getLoggedInUserData": {"data": {"dbName": "TataCapital", "account_id": TATA_PORTAL_ACCOUNT_ID}},
    }
    monkeypatch.setattr(client, "request", lambda method, path, **kwargs: responses[path])
    details, database = client.base(BASE_ID)
    assert base_metadata(details, WORKSPACE)["start_date"] == "2026-10-07"
    assert database == "TataCapital"


@pytest.mark.parametrize("profile", [
    None,
    {"dbName": "OtherTenant", "account_id": "other-account"},
    {"dbName": None, "account_id": "6399ced48c5fa78ad1eb39ea"},
    {"dbName": "", "account_id": "6399ced48c5fa78ad1eb39ea"},
])
def test_base_rejects_missing_or_foreign_workspace_database(monkeypatch, profile):
    from moengage_click_count import ClickCountClient, TATA_PORTAL_ACCOUNT_ID
    client = object.__new__(ClickCountClient)
    client.account_id = TATA_PORTAL_ACCOUNT_ID
    base = {"id": BASE_ID, "name": "imported", "type": "FILE_V2",
            "source": "IMPORT_USERS", "deleted": False, "archived": False}
    responses = {
        "/v2/custom-segments/dashboard": {"custom_segments": [base]},
        f"/v2/custom-segments/dashboard/{BASE_ID}/meta": {"cs_details": base},
        "/getLoggedInUserData": {"data": profile},
    }
    monkeypatch.setattr(client, "request", lambda method, path, **kwargs: responses[path])
    with pytest.raises(HTTPException) as error:
        client.base(BASE_ID)
    assert error.value.status_code == 502


def test_signed_query_ticket_rejects_different_workspace_and_tampering(monkeypatch):
    import moengage_click_count as module
    monkeypatch.setattr(module, "configured_jwt_secret", lambda: "test-click-count-signing-key-at-least-32-bytes")
    ticket = module.sign_query(QUERY_ID, WORKSPACE["id"], "TataCapital")
    assert module.read_query_ticket(ticket, WORKSPACE["id"])["db_name"] == "TataCapital"
    for token, workspace in [(ticket, "62aad9735e6ff766f85bb0b8"), ("invalid-ticket", WORKSPACE["id"])]:
        with pytest.raises(HTTPException) as error:
            module.read_query_ticket(token, workspace)
        assert error.value.status_code == 404


def test_signed_query_ticket_expires(monkeypatch):
    import jwt
    import moengage_click_count as module
    monkeypatch.setattr(module, "configured_jwt_secret", lambda: "test-click-count-signing-key-at-least-32-bytes")
    ticket = jwt.encode({"aud": "tata-click-count", "purpose": "tata-click-count", "rq_id": QUERY_ID,
                         "workspace_id": WORKSPACE["id"], "db_name": "TataCapital", "iat": 0, "exp": 1},
                        module.configured_jwt_secret(), algorithm="HS256")
    with pytest.raises(HTTPException) as error:
        module.read_query_ticket(ticket, WORKSPACE["id"])
    assert error.value.status_code == 404


def test_query_timeout_is_not_retried_and_does_not_leak_session(monkeypatch):
    import requests
    import moengage_click_count as module
    client = object.__new__(module.ClickCountClient)
    client.base_url = "https://dashboard-03.moengage.com"
    client.headers = {"authorization": "secret-token", "cookie": "secret-cookie"}
    attempts = []
    def timeout(*args, **kwargs):
        attempts.append(kwargs)
        raise requests.Timeout("secret-token secret-cookie")
    monkeypatch.setattr(module.requests, "request", timeout)
    with pytest.raises(HTTPException) as error:
        client.request("POST", "/segmentation/recent_query/count", body={})
    assert error.value.status_code == 504
    assert len(attempts) == 1
    assert "secret" not in error.value.detail
    assert "may already be queued" in error.value.detail


@pytest.mark.parametrize("user", [
    {"id": "bajaj-user", "tenant_id": "bajaj", "role": "user"},
    {"id": "apparel-user", "tenant_id": "apparel", "role": "admin"},
    {"tenant_id": "tata", "role": "anonymous"},
])
def test_non_tata_or_anonymous_users_cannot_access_counts(user):
    from moengage_click_count import require_click_count_user
    with pytest.raises(HTTPException) as error:
        require_click_count_user(user)
    assert error.value.status_code in (401, 403)


def test_missing_refresh_token_has_actionable_configuration_error(monkeypatch):
    import moengage_click_count as module
    monkeypatch.setattr(module, "get_moengage_config", lambda account: {
        "base_url": "https://dashboard-03.moengage.com", "bearer_token": "present",
        "cookie": "present", "refresh_token": "",
    })
    with pytest.raises(HTTPException) as error:
        module.ClickCountClient()
    assert error.value.status_code == 503
    assert "refresh token is missing" in error.value.detail


def test_http_200_bad_refresh_token_is_not_treated_as_success(monkeypatch):
    import moengage_click_count as module
    client = object.__new__(module.ClickCountClient)
    client.base_url = "https://dashboard-03.moengage.com"
    client.headers = {}
    class Response:
        status_code = 200
        ok = True
        cookies = module.requests.cookies.RequestsCookieJar()
        def json(self):
            return {"code": 400, "status": "failure", "loggedIn": True,
                    "reason": "Bad refresh token provided secret-session"}
    monkeypatch.setattr(module.requests, "request", lambda *args, **kwargs: Response())
    with pytest.raises(HTTPException) as error:
        client.request("GET", "/dash/auth/changeApp")
    assert error.value.status_code == 503
    assert "refresh token" in error.value.detail
    assert "secret-session" not in error.value.detail


@pytest.mark.parametrize("reachable", [None, "0", False, -1, 2])
def test_malformed_reachability_does_not_replace_unique_user_count(reachable):
    with pytest.raises(HTTPException) as error:
        query_result({"_id": QUERY_ID, "db_name": "TataCapital", "status": "success", "user_count": 1,
                      "reachability_count": {"total_reachable_count": reachable}}, QUERY_ID, "TataCapital")
    assert error.value.status_code == 502


def test_refresh_token_can_be_cleared_without_affecting_omitted_updates(monkeypatch, tmp_path):
    import json
    import os
    import api
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(api, "log_activity", lambda **kwargs: None)
    for key in ("TATA_MOENGAGE_REFRESH_TOKEN", "MOENGAGE_REFRESH_TOKEN"):
        monkeypatch.setenv(key, "stored-refresh-token")
    user = {"sub": "tata-admin", "tenant_id": "tata", "role": "admin", "name": "Admin"}
    omitted = api.update_moengage_credentials_endpoint(api.MoEngageCredentialUpdate(account="tata"), user)
    assert omitted["updated_keys"] == []
    assert os.environ["TATA_MOENGAGE_REFRESH_TOKEN"] == "stored-refresh-token"
    cleared = api.update_moengage_credentials_endpoint(
        api.MoEngageCredentialUpdate(account="tata", refresh_token=""), user)
    assert set(cleared["updated_keys"]) == {"MOENGAGE_REFRESH_TOKEN", "TATA_MOENGAGE_REFRESH_TOKEN"}
    persisted = json.loads((tmp_path / "credentials.json").read_text())
    for key in cleared["updated_keys"]:
        assert os.environ[key] == ""
        assert persisted[key] == ""
        assert f"{key}=" in (tmp_path / ".env").read_text().splitlines()


def test_switch_cookies_are_used_for_selected_workspace_and_reset_for_next_switch(monkeypatch):
    import moengage_click_count as module
    client = object.__new__(module.ClickCountClient)
    client.base_url = "https://dashboard-03.moengage.com"
    client.source_headers = {"authorization": "Bearer original", "refreshtoken": "original-refresh",
                             "cookie": "moe_uuid=original-browser"}
    client.headers = client.source_headers.copy()
    selected_cookies = []
    class Response:
        status_code = 200
        ok = True
        def __init__(self, payload, cookies=None):
            self.payload = payload
            self.cookies = module.requests.cookies.cookiejar_from_dict(cookies or {})
        def json(self):
            return self.payload
    def request(method, url, **kwargs):
        if url.endswith("/dash/auth/changeApp"):
            assert kwargs["headers"] == client.source_headers
            app_id = kwargs["params"]["app_id"]
            return Response({"loggedIn": True, "status": "success", "code": 200,
                             "data": {"app_access_details": "ALLOWED", "bearer": f"selected-{app_id}",
                                      "refresh_token": f"refresh-{app_id}"}},
                            {"loggedIn": f"selected-cookie-{app_id}"})
        assert url.endswith("/appsettings")
        cookie = kwargs["headers"]["cookie"]
        selected_cookies.append(cookie)
        assert "moe_uuid=original-browser" in cookie
        expected = kwargs["headers"]["authorization"].removeprefix("Bearer selected-")
        assert f"loggedIn=selected-cookie-{expected}" in cookie
        return Response({"loggedIn": True, "code": 200, "status": "success",
                         "data": {"time_zone": "Asia/Kolkata"}})
    monkeypatch.setattr(module.requests, "request", request)
    client.activate({"id": WORKSPACE["id"], "name": "Tata Capital"})
    client.activate({"id": "62aad9735e6ff766f85bb0b8", "name": "Wealth_TC"})
    assert len(selected_cookies) == 2
    assert WORKSPACE["id"] not in selected_cookies[1]
    assert client.source_headers["cookie"] == "moe_uuid=original-browser"


@pytest.mark.parametrize("envelope,allowed", [
    ({"code": 200, "status": "success", "loggedIn": False}, True),
    ({"loggedIn": False}, False),
    ({"code": 200, "loggedIn": False}, False),
    ({"status": "success", "loggedIn": False}, False),
    ({"code": 400, "status": "failure", "loggedIn": False}, False),
])
def test_legacy_session_flag_requires_explicit_success_envelope(monkeypatch, envelope, allowed):
    import moengage_click_count as module
    client = object.__new__(module.ClickCountClient)
    client.base_url = "https://dashboard-03.moengage.com"
    client.headers = {}
    class Response:
        status_code = 200
        ok = True
        cookies = module.requests.cookies.RequestsCookieJar()
        def json(self):
            return {**envelope, "data": {"time_zone": "Asia/Kolkata"}}
    monkeypatch.setattr(module.requests, "request", lambda *args, **kwargs: Response())
    if allowed:
        assert client.request("GET", "/appsettings")["data"]["time_zone"] == "Asia/Kolkata"
    else:
        with pytest.raises(HTTPException) as error:
            client.request("GET", "/appsettings")
        assert error.value.status_code in (502, 503)
