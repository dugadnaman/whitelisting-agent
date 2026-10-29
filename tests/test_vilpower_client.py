"""Sanitized VILPOWER contract fixtures; no live registrations or credentials."""

import json
from datetime import datetime
from urllib.parse import urlparse

import pytest
import requests
from fastapi.testclient import TestClient

import api
import portal_sessions
import vilpower_client as vilpower
from models import ApprovalStatus, SubmissionStatus

CREDENTIALS = {"cookie": "sessionid=fixture-only-session; csrftoken=fixture-only-csrf", "entity_id": vilpower.TATA_ENTITY_ID, "provider": "vilpower"}
PROFILE = f'<div class="account"><h4>Example Operator</h4><div>{vilpower.TATA_ENTITY_NAME} &nbsp;|&nbsp; {vilpower.TATA_ENTITY_ID} &nbsp;</div></div><a href="/logout/">Logout</a>'
FORM = '''<form id="contentAddForm" method="post">
<input type="hidden" name="csrfmiddlewaretoken" value="fixture-fresh-csrf">
<select name="iCategoryID"><option value="">Select Category</option><option value="fixture-category">Finance</option></select>
<input name="iContentTemplateType" value="1" type="radio">
<select name="iHeaderID[]" multiple></select>
<input name="vcTemplateName" maxlength="60"><textarea name="vcTemplateMessage" maxlength="2000"></textarea>
<input name="vcSampleMessage" type="hidden">
</form>'''
DRAFT = {"template_name": "example_loan_notice", "text": " Hi {#alp#},\r\namount {#num#}. T&Cs apply. ",
         "sample_message": " Hi Example,\r\namount 1200. T&Cs apply. ", "template_type": "1",
         "category_id": "fixture-category", "header_id": "fixture-header", "header": "TATAXX", "message_type": "1",
         "source_ref": "fixture-sheet:2", "source_file": "example.csv", "submitted_by": "Example Operator"}


def row(identifier="1177000000000000001", status="Pending", body=None):
    return {"iTemplateIDEn": identifier, "vcTemplateName": DRAFT["template_name"],
            "vcTemplateMessage": body if body is not None else '<span class="break-all"> Hi {#alp#},\r\namount {#num#}. T&amp;Cs apply. </span>',
            "vcSampleMessage": DRAFT["sample_message"], "vcHeader": "TATAXX", "CATEGORY": "Finance",
            "iApprovedStatus": f'<span class="badge">{status}</span>', "Entity": vilpower.TATA_ENTITY_NAME,
            "ContentTemplateType": "Promotional", "iTemplateMessageType": "Text", "STATUS_OTHER": "Active"}


def response(payload="", status=200, location=None):
    result = requests.Response()
    result.status_code = status
    result.encoding = "utf-8"
    result._content = (json.dumps(payload) if isinstance(payload, (dict, list)) else payload).encode()
    if location:
        result.headers["Location"] = location
    return result


@pytest.fixture
def portal(monkeypatch):
    state = {"profile": PROFILE, "rows": [], "after_rows": [], "registered": False, "calls": [],
             "registration": response("", 302, vilpower._INDEX), "page_size": 500,
             "headers": [{"id": "fixture-header", "text": "TATAXX"}], "brands": [], "form": FORM}
    state["load_session"] = portal_sessions.load_session

    class Session:
        def __init__(self):
            self.headers = {}
            self.cookies = requests.cookies.RequestsCookieJar()

        def close(self):
            pass

        def request(self, method, url, **kwargs):
            assert kwargs["allow_redirects"] is False
            path = urlparse(url).path
            state["calls"].append((method, path, kwargs))
            if path == "/accountsettings/profile":
                return state["profile"] if isinstance(state["profile"], requests.Response) else response(state["profile"])
            if path == vilpower._ADD and method == "GET":
                return response(state["form"])
            if path == vilpower._ADD:
                state["registered"] = True
                if isinstance(state["registration"], Exception):
                    raise state["registration"]
                return state["registration"]
            if path == "/ajaxloadheaders/":
                return response(state["headers"])
            if path == "/ajaxloadbrand/":
                return response(state["brands"])
            assert path == vilpower._INVENTORY
            assert method == "POST"  # This is a read-only portal search, not registration.
            if "inventory_response" in state:
                return state["inventory_response"]
            params = kwargs["data"]
            from_date, to_date = params["data[from_date]"], params["data[to_date]"]
            items = state["after_rows"] if state["registered"] else state["rows"]
            items = [item for item in items if from_date <= datetime.strptime(item.get("RequestedDate", "29-Oct-2026").split()[0], "%d-%b-%Y").date().isoformat() <= to_date]
            start = int(params["start"])
            if start and state.get("unstable_offset"):
                start -= 1
            limit = min(int(params["length"]), state["page_size"])
            return response({"sEcho": params["draw"], "iTotalRecords": len(items), "iTotalDisplayRecords": len(items),
                             "aaData": items[start:start + limit]})

    monkeypatch.setattr(vilpower.requests, "Session", Session)
    monkeypatch.setattr(portal_sessions, "load_session", lambda account, integration: dict(CREDENTIALS) if (account, integration) == ("tata", "sms") else None)
    return state


def registration_calls(portal):
    return [call for call in portal["calls"] if call[:2] == ("POST", vilpower._ADD)]


def test_authenticated_session_put_get_accepts_nested_profile_without_exposing_cookie(portal, monkeypatch, provision_user):
    monkeypatch.setattr(portal_sessions, "load_session", portal["load_session"])
    _, headers = provision_user("tata")
    with TestClient(api.app, headers=headers) as client:
        saved = client.put("/api/sms-dlt/session", json={"account": "tata", "cookie": CREDENTIALS["cookie"], "entity_id": vilpower.TATA_ENTITY_ID})
        assert saved.status_code == 200
        current = client.get("/api/sms-dlt/session", params={"account": "tata"})
    assert current.status_code == 200
    assert current.json()["configured"] is True
    assert current.json()["entity_id"] == vilpower.TATA_ENTITY_ID
    assert "fixture-only-session" not in saved.text + current.text
    assert "cookie" not in saved.json() and "cookie" not in current.json()
    assert not registration_calls(portal)




@pytest.mark.parametrize("principal", ["OTHER FINANCE LIMITED | 1101000000000000000", f"OTHER FINANCE LIMITED | {vilpower.TATA_ENTITY_ID}", "TATA CAPITAL LIMITED | 1101000000000000000"])
def test_other_live_principal_refused_even_if_supplied_id_is_tata(portal, principal):
    portal["profile"] = f"<div>{principal}</div>"
    with pytest.raises(vilpower.VilpowerUnavailable, match="principal entity"):
        vilpower.validate_session(CREDENTIALS["cookie"], vilpower.TATA_ENTITY_ID)
    assert not registration_calls(portal)


def test_other_account_and_supplied_entity_refused_before_network(portal):
    with pytest.raises(ValueError):
        vilpower.fetch_sms_templates("bajaj", credentials=CREDENTIALS)
    with pytest.raises(ValueError):
        vilpower.submit_sms_template(DRAFT, "bajaj")
    with pytest.raises(ValueError):
        vilpower.validate_session(CREDENTIALS["cookie"], "1101000000000000000")
    assert portal["calls"] == []


@pytest.mark.parametrize("expired", [response("", 302, "/login/"), response('<form action="/login/"><input type="password" name="password"></form>'), response("Forbidden", 403)])
def test_authentication_redirect_or_login_html_is_not_http_200_success(portal, expired):
    portal["profile"] = expired
    with pytest.raises(vilpower.VilpowerAuthExpired):
        vilpower.fetch_sms_templates(credentials=CREDENTIALS)


def test_complete_inventory_survives_unstable_offset_ordering_and_preserves_status_text(portal):
    portal["rows"] = [dict(row("1177000000000000001", "Pending"), RequestedDate="29-Oct-2026 10:00:00"),
                      dict(row("1177000000000000002", "Approved"), RequestedDate="28-Oct-2026 10:00:00"),
                      dict(row("1177000000000000003", "Disapproved"), RequestedDate="28-Oct-2026 10:00:00")]
    portal["page_size"] = 2
    portal["unstable_offset"] = True
    result = vilpower.fetch_sms_templates()
    assert [item["status"] for item in result] == ["pending", "approved", "rejected"]
    assert result[0]["template_message"] == DRAFT["text"]
    assert [item["template_id"] for item in result] == [item["iTemplateIDEn"] for item in portal["rows"]]


def test_content_preserves_literals_and_explicit_line_breaks():
    assert vilpower._content('<span class="break-all"> A &lt;b&gt;<br/>B &amp; C\r\n </span>') == " A <b>\nB & C\r\n "
    assert vilpower._content("Literal <name> stays") == "Literal <name> stays"


@pytest.mark.parametrize("payload", [{"iTotalDisplayRecords": 0, "aaData": [], "error_text": "Failed to load data"},
                                     {"iTotalDisplayRecords": 2, "aaData": []}, {"aaData": []}, {"iTotalDisplayRecords": 1, "aaData": [{}]}])
def test_incomplete_or_failed_inventory_is_never_empty_success(portal, payload):
    portal["inventory_response"] = response(payload)
    with pytest.raises(vilpower.VilpowerUnavailable):
        vilpower.fetch_sms_templates()


def test_unavailable_service_subtype_is_refused_instead_of_guessed(portal):
    with pytest.raises(ValueError, match="service type"):
        vilpower.fetch_sms_options(template_type="3", category_id="fixture-category", service_type="guessed-value")


def test_validation_is_pure_and_preserves_exact_message():
    draft = dict(DRAFT)
    assert vilpower.validate_sms_template(draft) == []
    assert vilpower.validate_sms_template({**draft, "text": "Hi {#VAR#}"})
    assert vilpower.validate_sms_template({**draft, "sample_message": "Different static text"})
    assert vilpower.validate_sms_template({**draft, "sample_message": ""})
    assert vilpower.validate_sms_template({**draft, "text": "नमस्ते", "sample_message": "नमस्ते"})
    assert vilpower.validate_sms_template({**draft, "text": "नमस्ते", "sample_message": "नमस्ते", "message_type": "2"}) == []
    assert vilpower.validate_sms_template({**draft, "template_type": [], "message_type": {}})


@pytest.mark.parametrize("kind,example,valid", [("num", "123", True), ("num", "abc", False), ("cbn", "1234567890", True),
    ("cbn", "12", False), ("urg", "https://example.test", True), ("uro", "www.example.test", True),
    ("urg", "example.test", False), ("eml", "hello@example.test", True), ("alp", "https://example.test", False)])
def test_typed_sample_examples_follow_observed_portal_rules(kind, example, valid):
    errors = vilpower.validate_sms_template({**DRAFT, "text": f"Example {{#{kind}#}}.", "sample_message": f"Example {example}."})
    assert bool(errors) is not valid


def test_single_registration_uses_portal_form_transport_and_verifies_created_record(monkeypatch):
    import threading
    from email import policy
    from email.parser import BytesParser
    from html import escape
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    records = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, value, status=200, location=None):
            self.send_response(status)
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write((json.dumps(value) if isinstance(value, (dict, list)) else value).encode())

        def do_GET(self):
            if self.headers.get("Cookie") != CREDENTIALS["cookie"]:
                return self.respond("Expired session", 403)
            self.respond(PROFILE if self.path == "/accountsettings/profile" else FORM)

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            if self.path == vilpower._INVENTORY:
                return self.respond({"iTotalDisplayRecords": len(records), "aaData": records})
            if self.path == "/ajaxloadheaders/":
                return self.respond([{"id": "fixture-header", "text": "TATAXX"}])
            if self.path == "/ajaxloadbrand/":
                return self.respond([])
            if self.path != vilpower._ADD:
                return self.respond("Not found", 404)
            message = BytesParser(policy=policy.default).parsebytes(
                b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body)
            fields = {
                part.get_param("name", header="content-disposition"): part.get_payload(decode=True).decode()
                for part in message.iter_parts()
            } if message.is_multipart() else {}
            if not {"iConsentTemplateID", "iLobID", "vcReason"} <= fields.keys():
                return self.respond('<ul class="errorlist"><li>Incomplete content registration form</li></ul>')
            if fields.get("vcTemplateName") != DRAFT["template_name"] or not fields.get("vcTemplateMessage"):
                return self.respond('<ul class="errorlist"><li>Template name and message are required</li></ul>')
            records.append({
                **row(), "vcTemplateName": fields["vcTemplateName"],
                "vcTemplateMessage": escape(fields["vcTemplateMessage"]),
                "vcSampleMessage": fields["vcSampleMessage"],
            })
            self.respond("", 302, vilpower._INDEX)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setattr(vilpower, "BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(portal_sessions, "load_session", lambda *args: dict(CREDENTIALS))
    try:
        result = vilpower.submit_sms_template(DRAFT)
        assert result.status == SubmissionStatus.SUBMITTED
        assert result.approval_status == ApprovalStatus.PENDING
        assert result.provider_ref_id == "1177000000000000001"
        assert vilpower.fetch_sms_templates()[0]["template_message"] == DRAFT["text"]
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize("outcome", [requests.Timeout("fixture ambiguous timeout"), response("Accepted"), response("", 302, vilpower._INDEX)])
def test_ambiguous_registration_never_replayed_or_called_success_without_inventory(portal, outcome):
    portal["registration"] = outcome
    result = vilpower.submit_sms_template(DRAFT)
    assert result.status == SubmissionStatus.FAILED
    assert result.provider_response["outcome"] == "unknown"
    assert result.provider_response["retry_safe"] is False
    assert "reconcile" in result.error
    assert len(registration_calls(portal)) == 1


def test_timeout_can_be_proved_registered_by_exact_inventory_without_replay(portal):
    portal["registration"] = requests.Timeout("fixture ambiguous timeout")
    portal["after_rows"] = [row()]
    assert vilpower.submit_sms_template(DRAFT).status == SubmissionStatus.SUBMITTED
    assert len(registration_calls(portal)) == 1


def test_same_name_different_body_does_not_prove_registration(portal):
    portal["after_rows"] = [row(body="Different text")]
    assert vilpower.submit_sms_template(DRAFT).status == SubmissionStatus.FAILED
    assert len(registration_calls(portal)) == 1


def test_form_errors_and_expired_post_session_fail_without_replay(portal):
    portal["registration"] = response('<ul class="errorlist"><li>Template name already registered</li></ul>')
    result = vilpower.submit_sms_template(DRAFT)
    assert result.status == SubmissionStatus.FAILED
    assert "Template name already registered" in result.error
    assert len(registration_calls(portal)) == 1
    portal["calls"] = []
    portal["registration"] = response("", 302, "/login/")
    result = vilpower.submit_sms_template(DRAFT)
    assert result.status == SubmissionStatus.FAILED
    assert "session expired" in result.error
    assert len(registration_calls(portal)) == 1


def test_existing_exact_template_is_duplicate_and_invalid_header_never_dispatches(portal):
    portal["rows"] = [row()]
    result = vilpower.submit_sms_template(DRAFT)
    assert result.status == SubmissionStatus.DUPLICATE
    assert result.approval_status == ApprovalStatus.PENDING
    assert not registration_calls(portal)
    portal["rows"] = []
    portal["headers"] = [{"id": "other-id", "text": "OTHER"}]
    result = vilpower.submit_sms_template(DRAFT)
    assert result.status == SubmissionStatus.FAILED
    assert "Header does not match" in result.error
    assert not registration_calls(portal)
