from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from moengage_click_count import base_metadata, click_count_payload, query_result

BASE_ID = "6ab615b5762ad13d1b9b8969"
QUERY_ID = "6ac775ce963c53bf0610984b"
WORKSPACE = {"id": "6516b0db87ee0c3c4499dc68", "name": "Tata Capital", "timezone": "Asia/Kolkata"}


@pytest.fixture
def frozen_clock(monkeypatch):
    import jwt
    import moengage_click_count as module
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = cls(2026, 10, 9, 1, tzinfo=UTC)
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)
    monkeypatch.setattr(module, "datetime", Clock)
    monkeypatch.setattr(jwt.api_jwt, "datetime", Clock)


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


def test_inclusive_date_query_deduplicates_five_channels_and_requires_base(frozen_clock):
    base = {"id": BASE_ID, "name": "October base", "start_date": "2026-09-25", "timezone": WORKSPACE["timezone"]}
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
def test_invalid_end_range_is_rejected(end, frozen_clock):
    with pytest.raises(HTTPException) as error:
        click_count_payload({"id": BASE_ID, "name": "base", "start_date": "2026-09-25", "timezone": WORKSPACE["timezone"]}, end)
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


def test_signed_query_ticket_rejects_different_workspace_and_tampering(monkeypatch, frozen_clock):
    import moengage_click_count as module
    monkeypatch.setattr(module, "configured_jwt_secret", lambda: "test-click-count-signing-key-at-least-32-bytes")
    ticket = module.sign_query(QUERY_ID, WORKSPACE["id"], "TataCapital")
    assert module.read_query_ticket(ticket, WORKSPACE["id"])["db_name"] == "TataCapital"
    for token, workspace in [(ticket, "62aad9735e6ff766f85bb0b8"), ("invalid-ticket", WORKSPACE["id"])]:
        with pytest.raises(HTTPException) as error:
            module.read_query_ticket(token, workspace)
        assert error.value.status_code == 404


def test_signed_query_ticket_expires(monkeypatch, frozen_clock):
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


@pytest.mark.parametrize("created", [
    None, "", "2026-09-25", "20260925T063325", "2026-W39-5T06:33:25",
    "2026-09-25X06:33:25", "2026-02-30T00:00:00", "0000-01-01T00:00:00Z",
    "2026-09-25T24:00:00Z", "2026-09-25T00:00:00+24:00",
    "2026-09-25T00:00:00+00:60", "2026-09-25T00:00:00+00:00:30",
    "0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59",
])
def test_invalid_or_overflowing_creation_time_returns_sanitized_gateway_error(created):
    with pytest.raises(HTTPException) as error:
        base_metadata({"id": BASE_ID, "name": "base", "created_time": created}, WORKSPACE)
    assert error.value.status_code == 502
    if created:
        assert str(created) not in error.value.detail


@pytest.mark.parametrize("created,timezone,expected", [
    ("0001-01-01T00:00:00Z", "UTC", "0001-01-01"),
    ("9999-12-31T23:59:59Z", "UTC", "9999-12-31"),
    ("2026-09-25T00:00:00+23:59", "UTC", "2026-09-24"),
    ("2026-09-25T00:00:00-23:59", "UTC", "2026-09-25"),
    ("2024-02-29T23:59:59.123456Z", "Asia/Kolkata", "2024-03-01"),
    ("2026-03-08T09:59:59Z", "America/Los_Angeles", "2026-03-08"),
    ("2026-03-08T10:00:00Z", "America/Los_Angeles", "2026-03-08"),
    ("2026-11-01T08:59:59Z", "America/Los_Angeles", "2026-11-01"),
    ("2026-11-01T09:00:00Z", "America/Los_Angeles", "2026-11-01"),
])
def test_creation_calendar_boundaries(created, timezone, expected):
    base = base_metadata({"id": BASE_ID, "name": "base", "created_time": created},
                         {**WORKSPACE, "timezone": timezone})
    assert base["start_date"] == expected
    assert datetime.fromisoformat(base["created_at"]).tzinfo == UTC


@pytest.mark.parametrize("created,timezone", [
    ("0001-01-01T00:00:00Z", "America/Los_Angeles"),
    ("9999-12-31T23:59:59Z", "Asia/Kolkata"),
    ("2026-01-01T00:00:00Z", "not/a/real-zone"),
    ("2026-01-01T00:00:00Z", "../UTC"),
    ("2026-01-01T00:00:00Z", None),
])
def test_workspace_conversion_overflow_or_bad_timezone_is_not_internal_error(created, timezone):
    with pytest.raises(HTTPException) as error:
        base_metadata({"id": BASE_ID, "name": "base", "created_time": created},
                      {**WORKSPACE, "timezone": timezone})
    assert error.value.status_code == 502


@pytest.mark.parametrize("timezone,today,tomorrow", [
    ("Asia/Kolkata", "2026-10-09", "2026-10-10"),
    ("America/Los_Angeles", "2026-10-08", "2026-10-09"),
    ("Pacific/Kiritimati", "2026-10-09", "2026-10-10"),
])
def test_end_date_is_capped_by_workspace_today_not_server_today(frozen_clock, timezone, today, tomorrow):
    base = {"id": BASE_ID, "name": "base", "start_date": "2026-10-01", "timezone": timezone}
    payload = click_count_payload(base, today)
    assert payload["filters"]["included_filters"]["filters"][0]["filters"][0]["primary_time_range"]["value1"] == today + "T23:59:59.999Z"
    with pytest.raises(HTTPException) as error:
        click_count_payload(base, tomorrow)
    assert error.value.status_code == 400


@pytest.mark.parametrize("end", [None, True, 20261009, " 2026-10-09", "2026-10-09\n",
                                     "２０２６-１０-０９", "2026-10-09T00:00:00Z", "0000-01-01"])
def test_end_date_requires_an_exact_ascii_calendar_date(end, frozen_clock):
    with pytest.raises(HTTPException) as error:
        click_count_payload({"id": BASE_ID, "name": "base", "start_date": "2026-09-25",
                             "timezone": "UTC"}, end)
    assert error.value.status_code == 400


def test_leap_day_range_and_action_time_ranges_are_independent(frozen_clock):
    payload = click_count_payload({"id": BASE_ID, "name": "base", "start_date": "2024-02-29",
                                   "timezone": "UTC"}, "2024-02-29")
    actions = payload["filters"]["included_filters"]["filters"][0]["filters"]
    assert len(actions) == 5
    assert all(action["executed"] is True for action in actions)
    assert all(action["attributes"] == {"filter_operator": "and", "filters": []} for action in actions)
    assert all(action["primary_time_range"]["value1"] == "2024-02-29T23:59:59.999Z" for action in actions)
    actions[0]["primary_time_range"]["value1"] = "changed"
    assert all(action["primary_time_range"]["value1"] != "changed" for action in actions[1:])


@pytest.mark.parametrize("status", ["queued", "running"])
def test_pending_query_does_not_publish_stale_counts(status):
    result = query_result({"_id": QUERY_ID, "db_name": "TataCapital", "status": status,
                           "user_count": 99, "reachability_count": {"total_reachable_count": 98}},
                          QUERY_ID, "TataCapital")
    assert result == {"query_id": QUERY_ID, "status": status, "user_count": None, "reachable_users": None}


@pytest.mark.parametrize("status", [None, "", "pending", "cancelled", "SUCCESS", True, [], {}])
def test_unknown_lifecycle_states_fail_closed(status):
    with pytest.raises(HTTPException) as error:
        query_result({"_id": QUERY_ID, "db_name": "TataCapital", "status": status}, QUERY_ID, "TataCapital")
    assert error.value.status_code == 502


@pytest.mark.parametrize("count,reachable", [
    (9007199254740991, 9007199254740991), (2**40, 0),
])
def test_large_safe_integer_counts_are_exact(count, reachable):
    result = query_result({"_id": QUERY_ID, "db_name": "TataCapital", "status": "success",
                           "user_count": count, "reachability_count": {"total_reachable_count": reachable}},
                          QUERY_ID, "TataCapital")
    assert result["user_count"] == count
    assert result["reachable_users"] == reachable


@pytest.mark.parametrize("count,reachability", [
    (9007199254740992, {"total_reachable_count": 0}),
    (1.0, {"total_reachable_count": 0}), (float("nan"), {"total_reachable_count": 0}),
    (1, None), (1, []), (1, {}), (1, {"total_reachable_count": 0.0}),
    (0, {"total_reachable_count": 1}),
])
def test_completed_query_never_returns_imprecise_or_missing_counts(count, reachability):
    with pytest.raises(HTTPException) as error:
        query_result({"_id": QUERY_ID, "db_name": "TataCapital", "status": "success",
                      "user_count": count, "reachability_count": reachability}, QUERY_ID, "TataCapital")
    assert error.value.status_code == 502


@pytest.mark.parametrize("field", ["workspace_id", "base_id", "end_date"])
@pytest.mark.parametrize("value", [None, True, 1, 1.0, [], {}, b"2026-10-09"])
def test_request_model_never_coerces_non_string_input(field, value):
    from pydantic import ValidationError
    from moengage_click_count import ClickCountQueryRequest
    body = {"workspace_id": WORKSPACE["id"], "base_id": BASE_ID, "end_date": "2026-10-09"}
    with pytest.raises(ValidationError):
        ClickCountQueryRequest(**{**body, field: value})


@pytest.mark.parametrize("changes", [
    {"aud": ["tata-click-count"]}, {"aud": "other"}, {"purpose": "other"},
    {"rq_id": None}, {"rq_id": True}, {"rq_id": "invalid"},
    {"workspace_id": None}, {"workspace_id": "62aad9735e6ff766f85bb0b8"},
    {"db_name": ""}, {"db_name": True}, {"db_name": "Other Tenant"}, {"db_name": "x" * 129},
    {"iat": "1791507600"}, {"exp": "1791594000"}, {"iat": 1791507600.0},
    {"exp": 1791594000.0}, {"iat": False}, {"exp": True},
    {"iat": float("inf")}, {"exp": float("inf")}, {"iat": float("nan")},
    {"iat": 1791507601}, {"exp": 1791507600}, {"exp": 1791594001},
])
def test_signed_ticket_claim_shapes_and_lifetime_are_strict(monkeypatch, frozen_clock, changes):
    import jwt
    import moengage_click_count as module
    secret = "test-click-count-signing-key-at-least-32-bytes"
    monkeypatch.setattr(module, "configured_jwt_secret", lambda: secret)
    now = int(datetime(2026, 10, 9, 1, tzinfo=UTC).timestamp())
    claims = {"aud": "tata-click-count", "purpose": "tata-click-count", "rq_id": QUERY_ID,
              "workspace_id": WORKSPACE["id"], "db_name": "TataCapital", "iat": now, "exp": now + 86400}
    ticket = jwt.encode({**claims, **changes}, secret, algorithm="HS256")
    with pytest.raises(HTTPException) as error:
        module.read_query_ticket(ticket, WORKSPACE["id"])
    assert error.value.status_code == 404
    assert error.value.detail == "Query ID is invalid, expired, or belongs to another workspace."


@pytest.mark.parametrize("missing", ["aud", "purpose", "rq_id", "workspace_id", "db_name", "iat", "exp"])
def test_signed_ticket_requires_every_binding_claim(monkeypatch, frozen_clock, missing):
    import jwt
    import moengage_click_count as module
    secret = "test-click-count-signing-key-at-least-32-bytes"
    monkeypatch.setattr(module, "configured_jwt_secret", lambda: secret)
    now = int(datetime(2026, 10, 9, 1, tzinfo=UTC).timestamp())
    claims = {"aud": "tata-click-count", "purpose": "tata-click-count", "rq_id": QUERY_ID,
              "workspace_id": WORKSPACE["id"], "db_name": "TataCapital", "iat": now, "exp": now + 86400}
    del claims[missing]
    with pytest.raises(HTTPException) as error:
        module.read_query_ticket(jwt.encode(claims, secret, algorithm="HS256"), WORKSPACE["id"])
    assert error.value.status_code == 404


@pytest.mark.parametrize("ticket", [None, True, 1, [], {}, b"invalid", "", "x" * 4097])
def test_untrusted_ticket_types_and_lengths_never_raise_internal_errors(ticket):
    from moengage_click_count import read_query_ticket
    with pytest.raises(HTTPException) as error:
        read_query_ticket(ticket, WORKSPACE["id"])
    assert error.value.status_code == 404


@pytest.fixture
def portal_transport(monkeypatch):
    import moengage_click_count as module
    client = object.__new__(module.ClickCountClient)
    client.base_url = "https://dashboard-03.moengage.com"
    client.headers = {"authorization": "secret-token", "cookie": "session=secret-cookie"}
    client.account_id = module.TATA_PORTAL_ACCOUNT_ID
    attempts = []
    class Response:
        def __init__(self, payload=None, status=200, cookies=None, json_error=False):
            self.status_code = status
            self.ok = status < 400
            self.cookies = module.requests.cookies.cookiejar_from_dict(cookies or {})
            self.payload = payload
            self.json_error = json_error
        def json(self):
            if self.json_error:
                raise ValueError("secret-token secret-cookie")
            return self.payload
    def install(payload=None, status=200, cookies=None, json_error=False, exception=None):
        def request(*args, **kwargs):
            attempts.append((args, kwargs))
            if exception is not None:
                raise exception
            return Response(payload, status, cookies, json_error)
        monkeypatch.setattr(module.requests, "request", request)
    return client, install, attempts


@pytest.mark.parametrize("status,expected", [
    (301, 503), (302, 503), (307, 503), (308, 503), (401, 503), (403, 503),
    (404, 502), (429, 503), (500, 502), (503, 502),
])
def test_upstream_http_failures_are_sanitized_and_never_redirect_or_retry(portal_transport, status, expected):
    client, install, attempts = portal_transport
    install({"reason": "secret-token secret-cookie"}, status=status)
    with pytest.raises(HTTPException) as error:
        client.request("POST", "/segmentation/recent_query/count", body={})
    assert error.value.status_code == expected
    assert "secret" not in error.value.detail
    assert len(attempts) == 1
    assert attempts[0][1]["allow_redirects"] is False
    assert attempts[0][1]["timeout"] == (10, 45)


@pytest.mark.parametrize("payload,json_error", [
    (None, False), ([], False), ("secret-token secret-cookie", False), ({}, True),
])
def test_non_json_and_non_object_responses_fail_without_leaking_body(portal_transport, payload, json_error):
    client, install, attempts = portal_transport
    install(payload, json_error=json_error)
    with pytest.raises(HTTPException) as error:
        client.request("POST", "/segmentation/recent_query/count", body={})
    assert error.value.status_code == 502
    assert "secret" not in error.value.detail
    assert len(attempts) == 1


@pytest.mark.parametrize("path,envelope,expected", [
    ("/dash/auth/changeApp", {"code": "400", "status": "success"}, 503),
    ("/dash/auth/changeApp", {"code": "401"}, 503),
    ("/segmentation/recent_query/count", {"code": "500", "success": True, "rq_id": QUERY_ID}, 502),
    ("/segmentation/recent_query/count", {"success": False, "rq_id": QUERY_ID}, 502),
    ("/appsettings", {"code": 200.0, "status": "success"}, 502),
    ("/appsettings", {"code": True, "status": "success"}, 502),
    ("/appsettings", {"code": [], "status": "success"}, 502),
    ("/appsettings", {"status": "error"}, 502),
])
def test_error_envelopes_cannot_be_masked_by_success_data(portal_transport, path, envelope, expected):
    client, install, _ = portal_transport
    install({**envelope, "reason": "secret-token secret-cookie"})
    with pytest.raises(HTTPException) as error:
        client.request("POST", path, body={})
    assert error.value.status_code == expected
    assert "secret" not in error.value.detail


def test_numeric_string_success_code_preserves_explicit_legacy_success(portal_transport):
    client, install, _ = portal_transport
    install({"code": "200", "status": "success", "loggedIn": False, "data": {"time_zone": "UTC"}})
    assert client.request("GET", "/appsettings")["data"]["time_zone"] == "UTC"


@pytest.mark.parametrize("exception,method,path,expected", [
    ("timeout", "GET", "/appsettings", 504),
    ("timeout", "POST", "/segmentation/recent_query/count", 504),
    ("connection", "POST", "/segmentation/recent_query/count", 502),
    ("invalid_header", "POST", "/segmentation/recent_query/count", 503),
])
def test_transport_failures_never_leak_credentials_or_retry(portal_transport, exception, method, path, expected):
    import requests
    client, install, attempts = portal_transport
    classes = {"timeout": requests.Timeout, "connection": requests.ConnectionError,
               "invalid_header": requests.exceptions.InvalidHeader}
    install(exception=classes[exception]("secret-token secret-cookie"))
    with pytest.raises(HTTPException) as error:
        client.request(method, path)
    assert error.value.status_code == expected
    assert "secret" not in error.value.detail
    assert len(attempts) == 1


def test_merged_cookie_header_contains_pairs_not_set_cookie_attributes(portal_transport):
    client, install, _ = portal_transport
    client.headers["cookie"] = "session=old; Path=/; Secure"
    install({"success": True}, cookies={"session": "new", "other": "kept"})
    client.request("GET", "/appsettings")
    assert client.headers["cookie"] == "session=new; other=kept"


def test_malformed_upstream_cookie_name_is_a_sanitized_gateway_error(portal_transport):
    client, install, _ = portal_transport
    install({"success": True}, cookies={"path": "secret-cookie"})
    with pytest.raises(HTTPException) as error:
        client.request("GET", "/appsettings")
    assert error.value.status_code == 502
    assert "secret" not in error.value.detail


@pytest.mark.parametrize("value", ["Bearer test-only-\u2603", "Bearer test-only-\n", "Bearer test-only-\r"])
def test_native_header_encoding_failures_are_controlled_and_make_no_network_connection(monkeypatch, value):
    from urllib3.connection import HTTPConnection
    from moengage_click_count import ClickCountClient
    def forbidden_connection(_self):
        pytest.fail("Malformed copied headers must not open a network connection.")
    monkeypatch.setattr(HTTPConnection, "connect", forbidden_connection)
    monkeypatch.setenv("no_proxy", "*")
    client = object.__new__(ClickCountClient)
    client.base_url = "http://127.0.0.1:0"
    client.headers = {"authorization": value}
    with pytest.raises(HTTPException) as error:
        client.request("POST", "/segmentation/recent_query/count", body={})
    assert error.value.status_code == 503
    assert "test-only" not in error.value.detail


def test_workspace_list_excludes_foreign_inactive_and_test_apps(monkeypatch):
    from moengage_click_count import ClickCountClient, TATA_PORTAL_ACCOUNT_ID
    client = object.__new__(ClickCountClient)
    client.account_id = TATA_PORTAL_ACCOUNT_ID
    app = {"id": WORKSPACE["id"], "name": WORKSPACE["name"], "account_id": TATA_PORTAL_ACCOUNT_ID,
           "activated": True, "is_test": False}
    rows = [app, {**app, "account_id": "foreign"}, {**app, "activated": False},
            {**app, "is_test": True}, {**app, "activated": 1}, {**app, "is_test": 0}]
    monkeypatch.setattr(client, "request", lambda *args, **kwargs: {"data": rows})
    assert client.authorized_apps() == [app]


@pytest.mark.parametrize("changes,duplicate", [
    ({"id": "invalid"}, False), ({"name": " "}, False), ({}, True),
])
def test_workspace_list_rejects_ambiguous_or_malformed_identity(monkeypatch, changes, duplicate):
    from moengage_click_count import ClickCountClient, TATA_PORTAL_ACCOUNT_ID
    client = object.__new__(ClickCountClient)
    client.account_id = TATA_PORTAL_ACCOUNT_ID
    app = {"id": WORKSPACE["id"], "name": WORKSPACE["name"], "account_id": TATA_PORTAL_ACCOUNT_ID,
           "activated": True, "is_test": False, **changes}
    monkeypatch.setattr(client, "request", lambda *args, **kwargs: {"data": [app, app] if duplicate else [app]})
    with pytest.raises(HTTPException) as error:
        client.authorized_apps()
    assert error.value.status_code == 502


@pytest.mark.parametrize("changes,duplicate", [
    ({"name": " "}, False), ({"deleted": "false"}, False), ({"archived": 0}, False),
    ({"deleted": None}, False), ({}, True),
])
def test_base_list_rejects_invalid_lifecycle_or_ambiguous_identity(monkeypatch, changes, duplicate):
    from moengage_click_count import ClickCountClient
    client = object.__new__(ClickCountClient)
    base = {"id": BASE_ID, "name": "base", "source": "IMPORT_USERS", "type": "FILE_V2",
            "deleted": False, "archived": False, **changes}
    monkeypatch.setattr(client, "request", lambda *args, **kwargs: {"custom_segments": [base, base] if duplicate else [base]})
    with pytest.raises(HTTPException) as error:
        client.bases()
    assert error.value.status_code == 502


@pytest.mark.parametrize("changes", [
    {"id": QUERY_ID}, {"source": "ANALYTICS"}, {"type": "FILE"},
    {"deleted": True}, {"archived": True}, {"deleted": 0}, {"archived": None}, {"name": " "},
])
def test_metadata_must_still_describe_selected_active_imported_base(monkeypatch, changes):
    from moengage_click_count import ClickCountClient
    client = object.__new__(ClickCountClient)
    base = {"id": BASE_ID, "name": "base", "source": "IMPORT_USERS", "type": "FILE_V2",
            "deleted": False, "archived": False}
    monkeypatch.setattr(client, "bases", lambda: [{"id": BASE_ID, "name": "base"}])
    monkeypatch.setattr(client, "request", lambda *args, **kwargs: {"cs_details": {**base, **changes}})
    with pytest.raises(HTTPException) as error:
        client.base(BASE_ID)
    assert error.value.status_code == 502


@pytest.mark.parametrize("db_name", ["bad database", "x" * 129, 0, True, []])
def test_workspace_database_identifier_is_strict(monkeypatch, db_name):
    from moengage_click_count import ClickCountClient, TATA_PORTAL_ACCOUNT_ID
    client = object.__new__(ClickCountClient)
    client.account_id = TATA_PORTAL_ACCOUNT_ID
    monkeypatch.setattr(client, "request", lambda *args, **kwargs: {
        "data": {"account_id": TATA_PORTAL_ACCOUNT_ID, "dbName": db_name}})
    with pytest.raises(HTTPException) as error:
        client.workspace_database()
    assert error.value.status_code == 502


@pytest.mark.parametrize("algorithm,secret", [
    ("HS384", "test-click-count-signing-key-at-least-32-bytes"),
    ("HS256", "different-click-count-signing-key-at-least-32-bytes"),
])
def test_valid_looking_tickets_require_expected_signature_and_algorithm(monkeypatch, frozen_clock, algorithm, secret):
    import jwt
    import moengage_click_count as module
    monkeypatch.setattr(module, "configured_jwt_secret", lambda: "test-click-count-signing-key-at-least-32-bytes")
    now = int(datetime(2026, 10, 9, 1, tzinfo=UTC).timestamp())
    claims = {"aud": "tata-click-count", "purpose": "tata-click-count", "rq_id": QUERY_ID,
              "workspace_id": WORKSPACE["id"], "db_name": "TataCapital", "iat": now, "exp": now + 86400}
    with pytest.raises(HTTPException) as error:
        module.read_query_ticket(jwt.encode(claims, secret, algorithm=algorithm), WORKSPACE["id"])
    assert error.value.status_code == 404


def test_creation_start_recomputes_from_same_utc_instant_when_workspace_timezone_changes():
    raw = {"id": BASE_ID, "name": "base", "created_time": "2026-09-25T00:30:00"}
    india = base_metadata(raw, WORKSPACE)
    west = base_metadata(raw, {**WORKSPACE, "timezone": "America/Los_Angeles"})
    assert india["created_at"] == west["created_at"] == "2026-09-25T00:30:00+00:00"
    assert india["start_date"] == "2026-09-25"
    assert west["start_date"] == "2026-09-24"


def test_deeply_nested_untrusted_jwt_header_is_not_an_internal_error(monkeypatch):
    from jwt.utils import base64url_encode
    import moengage_click_count as module
    monkeypatch.setattr(module, "configured_jwt_secret", lambda: "test-click-count-signing-key-at-least-32-bytes")
    header = b'{"alg":"HS256","extra":' + b"[" * 1100 + b"0" + b"]" * 1100 + b"}"
    ticket = base64url_encode(header).decode() + ".e30.aW52YWxpZA"
    assert len(ticket) < 4096
    with pytest.raises(HTTPException) as error:
        module.read_query_ticket(ticket, WORKSPACE["id"])
    assert error.value.status_code == 404


def test_deeply_nested_upstream_json_is_sanitized(monkeypatch, portal_transport):
    import moengage_click_count as module
    client, _, _ = portal_transport
    class Response:
        status_code = 200
        ok = True
        cookies = module.requests.cookies.RequestsCookieJar()
        def json(self):
            raise RecursionError("secret-token secret-cookie")
    monkeypatch.setattr(module.requests, "request", lambda *args, **kwargs: Response())
    with pytest.raises(HTTPException) as error:
        client.request("POST", "/segmentation/recent_query/count")
    assert error.value.status_code == 502
    assert "secret" not in error.value.detail


@pytest.mark.parametrize("seconds,valid", [(86399, True), (86400, False), (86401, False)])
def test_signed_query_ticket_expires_at_exact_24_hour_boundary(monkeypatch, frozen_clock, seconds, valid):
    import jwt
    import moengage_click_count as module
    from datetime import timedelta
    monkeypatch.setattr(module, "configured_jwt_secret", lambda: "test-click-count-signing-key-at-least-32-bytes")
    ticket = module.sign_query(QUERY_ID, WORKSPACE["id"], "TataCapital")
    class LaterClock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 10, 9, 1, tzinfo=UTC) + timedelta(seconds=seconds)
            return instant.astimezone(tz)
    monkeypatch.setattr(jwt.api_jwt, "datetime", LaterClock)
    if valid:
        assert module.read_query_ticket(ticket, WORKSPACE["id"])["rq_id"] == QUERY_ID
    else:
        with pytest.raises(HTTPException) as error:
            module.read_query_ticket(ticket, WORKSPACE["id"])
        assert error.value.status_code == 404


@pytest.mark.parametrize("end", ["2026-02-30", "2026-10-09T00:00:00Z", "not-a-date"])
def test_malformed_query_date_is_rejected_before_initializing_portal(monkeypatch, end):
    import moengage_click_count as module
    def forbidden_client():
        pytest.fail("Malformed user dates must not initialize a portal session.")
    monkeypatch.setattr(module, "ClickCountClient", forbidden_client)
    with pytest.raises(HTTPException) as error:
        module.create_query(module.ClickCountQueryRequest(workspace_id=WORKSPACE["id"], base_id=BASE_ID, end_date=end))
    assert error.value.status_code == 400


def test_future_query_date_is_rejected_before_base_listing_or_count_submission(monkeypatch, frozen_clock):
    import moengage_click_count as module
    class Client:
        def select_workspace(self, workspace_id):
            return {**WORKSPACE, "timezone": "America/Los_Angeles"}
        def base(self, base_id):
            pytest.fail("Future workspace dates must not list bases or submit a count.")
    monkeypatch.setattr(module, "ClickCountClient", Client)
    with pytest.raises(HTTPException) as error:
        module.create_query(module.ClickCountQueryRequest(workspace_id=WORKSPACE["id"], base_id=BASE_ID, end_date="2026-10-09"))
    assert error.value.status_code == 400


@pytest.mark.parametrize("endpoint,kwargs", [
    ("get_bases", {"workspace_id": "invalid"}),
    ("get_base", {"workspace_id": "invalid", "base_id": BASE_ID}),
    ("get_base", {"workspace_id": WORKSPACE["id"], "base_id": "invalid"}),
])
def test_invalid_list_or_metadata_identifiers_are_rejected_before_portal_access(monkeypatch, endpoint, kwargs):
    import moengage_click_count as module
    def forbidden_client():
        pytest.fail("Invalid identifiers must not initialize a portal session.")
    monkeypatch.setattr(module, "ClickCountClient", forbidden_client)
    with pytest.raises(HTTPException) as error:
        getattr(module, endpoint)(**kwargs)
    assert error.value.status_code == 400


def test_extra_query_input_fields_are_rejected():
    from pydantic import ValidationError
    from moengage_click_count import ClickCountQueryRequest
    with pytest.raises(ValidationError):
        ClickCountQueryRequest(workspace_id=WORKSPACE["id"], base_id=BASE_ID, end_date="2026-10-09",
                               db_name="OtherTenant")
