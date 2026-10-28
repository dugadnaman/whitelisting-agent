"""WhatsApp submission regressions using an actual, isolated HTTP provider."""
import io
import json
import socket
import threading
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest
import requests
from PIL import Image

import config
import portal_sessions
import submission_client as client
from models import SubmissionStatus, TemplateSubmission


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "_load_env_file", lambda: None)
    monkeypatch.setattr(portal_sessions, "load_settings", lambda *args: {})
    monkeypatch.setattr(config, "DEFAULT_WABA_AUTH_TOKENS", {})
    for key in list(config.os.environ):
        if any(word in key for word in ("WABA_AUTH_TOKEN", "KARIX_", "PORTAL_")):
            monkeypatch.delenv(key, raising=False)
    for account in ("TCL_PROMO", "TCHFL"):
        monkeypatch.setenv(f"{account}_WABA_AUTH_TOKEN", f"local-{account}-official")
        monkeypatch.setenv(f"{account}_WABA_ID", f"local-{account}-waba")
        monkeypatch.setenv(f"{account}_ESMEADDR", f"local-{account}-esme")
    monkeypatch.setattr(client, "_session", requests.Session())
    monkeypatch.setattr(client, "BACKOFF_SECONDS", 0)
    real_request = requests.Session.request

    def local_request(session, method, url, **kwargs):
        assert urlsplit(url).hostname == "127.0.0.1", "External network is forbidden"
        return real_request(session, method, url, **kwargs)

    monkeypatch.setattr(requests.Session, "request", local_request)
    yield
    client._session.close()


@pytest.fixture
def provider(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        routes = {
            "/official/local-TCL_PROMO-waba": (201, {"response": {"templateId": "provider-created-123"}}),
            "/official/local-TCHFL-waba": (201, {"response": {"templateId": "provider-created-456"}}),
            "/official/local-TCL_PROMO-waba/media": (200, {"response": {"fileHandle": "4::local-official-handle"}}),
            "/official/local-TCHFL-waba/media": (200, {"response": {"fileHandle": "4::local-tchfl-handle"}}),
            "/portal/mediaUpload": (200, {"Success": "4::local-portal-handle"}),
            "/portal/create": (200, {"status": "success", "templateId": "provider-portal-789"}),
            "/creative.jpg": (200, b""),
        }
        calls = []

        def respond(self, body=b""):
            self.calls.append((self.command, self.path, body, dict(self.headers)))
            status, payload = self.routes.get((self.command, self.path), self.routes.get(self.path, (404, {"error": "not found"})))
            if status is None:
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(payload if isinstance(payload, bytes) else json.dumps(payload).encode())

        def do_POST(self):
            self.respond(self.rfile.read(int(self.headers.get("Content-Length", 0))))

        def do_GET(self):
            self.respond()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    Handler.base = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(client, "OFFICIAL_TEMPLATE_BASE_URL", Handler.base + "/official")
    monkeypatch.setattr(client, "KARIX_BASE_URL", Handler.base + "/portal")
    try:
        yield Handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def portal_credentials(monkeypatch, account="TCL_PROMO"):
    monkeypatch.setenv(f"{account}_KARIX_BEARER_TOKEN", f"local-{account}-portal")
    monkeypatch.setenv(f"{account}_KARIX_SESSION", f"local-{account}-session")
    monkeypatch.setenv(f"{account}_KARIX_USER", f"local-{account}-user")


def submission(*components, account="tcl_promo", **overrides):
    return TemplateSubmission(**{
        "client": account, "channel": "whatsapp", "template_name": "boundary_campaign",
        "language": "en", "category": "MARKETING", "waba_id": "",
        "source_ref": "local-sheet:2", "components": list(components) or [{"type": "BODY", "text": "Your offer is ready."}],
        **overrides,
    })


def submit(payload):
    return client.submit_template(payload, client=payload.client, fix_grammar=False)


def multipart(call):
    _, _, raw, headers = call
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {headers['Content-Type']}\r\nMIME-Version: 1.0\r\n\r\n".encode() + raw
    )
    return {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}


def create_calls(provider):
    return [call for call in provider.calls if call[0] == "POST" and not call[1].endswith(("/media", "/mediaUpload", "/getAllTemplates"))]


@pytest.mark.parametrize("portal", [False, True])
@pytest.mark.parametrize("http,response", [
    (200, {}), (200, []), (200, {"status": "success"}), (200, {"success200": "ok"}),
    (201, {"success201": True}), (200, b"<html>login</html>"),
    (200, {"id": True}), (200, {"id": []}), (200, {"id": {"value": "123"}}),
    (200, {"id": "None"}), (200, {"id": "null"}), (200, {"id": 0}), (200, {"id": -1}),
    (200, {"id": 1.5}), (200, {"id": "one", "response": {"id": "two"}}),
    (200, {"status": "failure", "id": "not-created", "reason": "Invalid category"}),
    (200, {"success": False, "id": "not-created"}),
    (200, {"response": {"error": "Invalid template", "id": "not-created"}}),
    (400, {"error": "Invalid template"}), (401, {"error": "expired"}),
    (429, {"error": "rate limited"}), (500, {"error": "upstream failed"}),
    (None, {}),
])
def test_creation_failure_never_replays_or_claims_a_name_as_id(provider, monkeypatch, portal, http, response):
    if portal:
        portal_credentials(monkeypatch)
    path = "/portal/create" if portal else "/official/local-TCL_PROMO-waba"
    provider.routes[path] = (http, response)
    result = submit(submission())
    assert result.status == SubmissionStatus.FAILED
    assert result.provider_ref_id is None
    assert result.error
    assert len(create_calls(provider)) == 1


@pytest.mark.parametrize("portal", [False, True])
@pytest.mark.parametrize("http,response,ref", [
    (200, {"templateId": "real-123"}, "real-123"),
    (201, {"response": {"templateId": 123}}, "123"),
    (200, {"response": {"template_id": "real-456"}}, "real-456"),
    (201, {"id": "real-789"}, "real-789"),
    (200, {"status": "success200", "response": {"id": "real-200"}}, "real-200"),
])
def test_creation_accepts_only_actual_provider_reference(provider, monkeypatch, portal, http, response, ref):
    if portal:
        portal_credentials(monkeypatch)
    provider.routes["/portal/create" if portal else "/official/local-TCL_PROMO-waba"] = (http, response)
    result = submit(submission())
    assert result.status == SubmissionStatus.SUBMITTED
    assert result.provider_ref_id == ref
    assert len(create_calls(provider)) == 1


@pytest.mark.parametrize("account", ["tcl_promo", "tchfl"])
@pytest.mark.parametrize("fmt,filename,mime,raw", [
    ("IMAGE", "creative.png", "image/png", b"\x89PNG\r\n\x1a\noriginal-creative"),
    ("IMAGE", "creative.jpeg", "image/jpeg", b"\xff\xd8\xfforiginal-jpeg"),
    ("VIDEO", "creative.mp4", "video/mp4", b"\x00\x00\x00\x18ftypmp42original-video"),
    ("DOCUMENT", "creative.pdf", "application/pdf", b"%PDF-1.4 original-document"),
])
def test_official_media_preserves_bytes_mime_and_account_scope(provider, tmp_path, account, fmt, filename, mime, raw):
    media = tmp_path / filename
    media.write_bytes(raw)
    payload = submission({"type": "HEADER", "format": fmt, "media_file": str(media), "file_type": mime},
                         {"type": "BODY", "text": "Your offer is ready."}, account=account)
    result = submit(payload)
    assert result.status == SubmissionStatus.SUBMITTED
    upload, creation = provider.calls
    assert upload[1] == f"/official/local-{account.upper()}-waba/media"
    parts = multipart(upload)
    assert parts["file"].get_payload(decode=True) == raw
    assert parts["file"].get_content_type() == mime
    assert parts["file_type"].get_payload(decode=True).decode() == mime
    assert upload[3]["Authentication"] == f"Bearer local-{account.upper()}-official"
    assert creation[1] == f"/official/local-{account.upper()}-waba"
    body = json.loads(creation[2])
    assert "esmeaddr" not in body and "waba_id" not in body
    assert body["components"][0] == {"type": "HEADER", "format": fmt, "example": {"header_handle": ["4::local-official-handle" if account == "tcl_promo" else "4::local-tchfl-handle"]}}
    assert payload.components[0]["media_file"] == str(media)


def test_portal_upload_fallback_to_observed_official_file_handle(provider, monkeypatch):
    portal_credentials(monkeypatch)
    provider.routes["/portal/mediaUpload"] = (200, {"Success": "not-a-handle"})
    result = submit(submission({"type": "HEADER", "format": "IMAGE", "image_bytes": b"\x89PNG\r\n\x1a\noriginal"}))
    assert result.status == SubmissionStatus.SUBMITTED
    assert [call[1] for call in provider.calls] == ["/portal/mediaUpload", "/official/local-TCL_PROMO-waba/media", "/portal/create"]
    portal_body = json.loads(multipart(provider.calls[-1])["request"].get_payload(decode=True))
    assert portal_body["waba_id"] == "local-TCL_PROMO-waba"
    assert portal_body["esmeaddr"] == "local-TCL_PROMO-esme"
    assert portal_body["components"][0]["example"] == {"header_handle": ["4::local-official-handle"]}


@pytest.mark.parametrize("response", [
    {}, [], {"response": {}}, {"response": {"fileHandle": None}},
    {"response": {"fileHandle": "None"}}, {"fileHandle": "4::"},
    {"fileHandle": [None]}, {"fileHandle": [123]}, {"fileHandle": {"id": "4::bad"}},
    {"fileHandle": "4::bad handle"}, {"fileHandle": "4::valid", "status": "failed"},
    b"not json",
])
def test_malformed_upload_never_creates_or_returns_none_handle(provider, response):
    provider.routes["/official/local-TCL_PROMO-waba/media"] = (200, response)
    result = submit(submission({"type": "HEADER", "format": "IMAGE", "image_bytes": b"original"}))
    assert result.status == SubmissionStatus.FAILED
    assert "media" in result.error.lower()
    assert not create_calls(provider)


@pytest.mark.parametrize("component", [
    {"type": "HEADER", "format": "VIDEO", "media_file": "/nonexistent/creative.mp4"},
    {"type": "HEADER", "format": "DOCUMENT", "image_bytes": b""},
    {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["None"]}},
])
def test_missing_or_invalid_creative_never_uses_placeholder(provider, component):
    result = submit(submission(component))
    assert result.status == SubmissionStatus.FAILED
    assert "media" in result.error.lower()
    assert provider.calls == []



def test_image_header_without_attached_file_uses_sample_placeholder(provider):
    """WhatsApp templates with an IMAGE header upload a placeholder sample image for Meta review."""
    result = submit(submission({"type": "HEADER", "format": "IMAGE"}))
    assert result.status == SubmissionStatus.SUBMITTED
    assert len(provider.calls) == 2
    upload_call = provider.calls[0]
    assert upload_call[1].endswith("/media")
    parts = multipart(upload_call)
    assert parts["file"].get_content_type() == "image/png"
    assert len(create_calls(provider)) == 1


@pytest.mark.parametrize("portal", [False, True])
@pytest.mark.parametrize("dimensions", [(73, 181), (311, 47), (19, 19)])
def test_whatsapp_whitelisting_preserves_any_image_dimensions_and_ignores_stale_flags(
    provider, monkeypatch, portal, dimensions,
):
    if portal:
        portal_credentials(monkeypatch)
    raw = io.BytesIO()
    Image.new("RGB", dimensions, "navy").save(raw, format="PNG")
    result = submit(submission(
        {"type": "HEADER", "format": "IMAGE", "image_bytes": raw.getvalue()},
        aspect_ratio_blocked=True, aspect_ratio_error="Obsolete dimension restriction",
    ))
    assert result.status == SubmissionStatus.SUBMITTED
    assert multipart(provider.calls[0])["file"].get_payload(decode=True) == raw.getvalue()
    assert len(create_calls(provider)) == 1


def test_whatsapp_runner_ignores_stale_dimension_block(provider, monkeypatch):
    from dataclasses import asdict

    import runner

    raw = io.BytesIO()
    Image.new("RGB", (73, 181), "navy").save(raw, format="PNG")
    payload = submission(
        {"type": "HEADER", "format": "IMAGE", "image_bytes": raw.getvalue()},
        aspect_ratio_blocked=True, aspect_ratio_error="Obsolete dimension restriction",
    )
    monkeypatch.setattr(runner, "load_from_list", lambda *args, **kwargs: [payload])
    monkeypatch.setattr(runner, "log_result", lambda result, *args, **kwargs: asdict(result))
    monkeypatch.setattr(client._GOVERNOR, "get_pacing_delay", lambda: 0)
    results = runner.run([asdict(payload)], client=payload.client, fix_grammar=False)
    assert results[0]["status"] == SubmissionStatus.SUBMITTED
    assert multipart(provider.calls[0])["file"].get_payload(decode=True) == raw.getvalue()
    assert len(create_calls(provider)) == 1


@pytest.mark.parametrize("dimensions", [(73, 181), (311, 47), (19, 19)])
def test_whatsapp_shared_preview_accepts_any_dimensions_and_clears_stale_ratio_block(dimensions):
    import api

    raw = io.BytesIO()
    Image.new("RGB", dimensions, "navy").save(raw, format="PNG")
    original = {
        "template_name": "preview_any_dimensions", "category": "MARKETING",
        "components": [{"type": "HEADER", "format": "IMAGE", "image_bytes": raw.getvalue()}],
        "aspect_ratio_blocked": True, "aspect_ratio_error": "Obsolete restriction",
        "aspect_ratio_block_reason": "Obsolete restriction",
    }
    preview = api._inspect_single_submission(original, set(), {}, "tcl_promo", "whatsapp")
    assert preview["aspect_ratio_blocked"] is False
    assert preview["aspect_ratio_warnings"] == []
    assert "aspect_ratio_block_reason" not in preview
    assert "aspect_ratio_error" not in preview
    assert preview["components"][0]["thumbnail_url"].startswith("data:image/png;base64,")
    assert original["components"][0]["image_bytes"] == raw.getvalue()

def test_failed_download_does_not_upload_default_or_expose_signed_url(provider):
    secret = "private-signed-query"
    result = submit(submission({"type": "HEADER", "format": "IMAGE", "media_url": provider.base + "/missing?token=" + secret}))
    assert result.status == SubmissionStatus.FAILED
    assert secret not in result.error
    assert [call[0] for call in provider.calls] == ["GET"]


def test_remote_jpeg_keeps_original_bytes_and_mime(provider):
    raw = io.BytesIO()
    Image.new("RGB", (160, 90), "blue").save(raw, format="JPEG")
    provider.routes["/creative.jpg"] = (200, raw.getvalue())
    result = submit(submission({"type": "HEADER", "format": "IMAGE", "media_url": provider.base + "/creative.jpg"}))
    assert result.status == SubmissionStatus.SUBMITTED
    assert multipart(provider.calls[1])["file"].get_payload(decode=True) == raw.getvalue()
    assert multipart(provider.calls[1])["file"].get_content_type() == "image/jpeg"


@pytest.mark.parametrize("transport", ["portal", "official"])
@pytest.mark.parametrize("variable", ["{{offer}}", "<offer>", "[offer]", "{offer}", "{#offer#}", "#offer#"])
def test_outgoing_url_buttons_are_dynamic_and_explicit_samples_survive(provider, monkeypatch, transport, variable):
    if transport == "portal":
        portal_credentials(monkeypatch)
    payload = submission(
        {"type": "HEADER", "format": "TEXT", "text": "Hello {{1}}", "example": {"header_text": ["Asha"]}},
        {"type": "BODY", "text": "Dear {{1}}, your offer {{2}} is ready.", "example": {"body_text": [["Asha", "special"]]}},
        {"type": "BUTTONS", "buttons": [
            {"type": "URL", "text": "View", "url": "https://example.test/offers", "example": ["https://unrelated.test/default"]},
            {"type": "URL", "text": "Personal offer", "url": f"https://example.test/{variable}", "example": ["https://example.test/my-offer"]},
            {"type": "PHONE_NUMBER", "text": "Call", "phone_number": "+911234567890"},
            {"type": "QUICK_REPLY", "text": "Not now"},
        ]},
    )
    assert submit(payload).status == SubmissionStatus.SUBMITTED
    call = create_calls(provider)[0]
    body = json.loads(
        multipart(call)["request"].get_payload(decode=True)
        if transport == "portal" else call[2]
    )
    assert call[1] == ("/portal/create" if transport == "portal" else "/official/local-TCL_PROMO-waba")
    assert body["components"][:2] == payload.components[:2]
    buttons = body["components"][2]["buttons"]
    assert buttons[:2] == [
        {"type": "URL", "text": "View", "url": "https://example.test/offers{{1}}", "example": ["https://example.test/offerssample"]},
        {"type": "URL", "text": "Personal offer", "url": "https://example.test/{{1}}", "example": ["https://example.test/my-offer"]},
    ]
    assert buttons[2:] == payload.components[2]["buttons"][2:]
    assert payload.components[2]["buttons"][0]["url"] == "https://example.test/offers"


def test_selected_account_cannot_be_overridden_by_payload_waba(provider):
    result = submit(submission(waba_id="local-TCHFL-waba"))
    assert result.status == SubmissionStatus.FAILED
    assert "account" in result.error.lower()
    assert provider.calls == []


def test_whatsapp_carousel_fails_explicitly_without_dropping_cards(provider):
    result = submit(submission({"type": "CAROUSEL", "cards": [{"components": [{"type": "HEADER", "format": "IMAGE", "image_bytes": b"original"}]}]}))
    assert result.status == SubmissionStatus.FAILED
    assert "carousel" in result.error.lower()
    assert provider.calls == []


def test_rejected_handle_does_not_replace_creative_and_recreate(provider, monkeypatch):
    portal_credentials(monkeypatch)
    provider.routes["/portal/create"] = (200, {"status": "failure", "reason": "Uploaded media handle is invalid (2494102)"})
    result = submit(submission({"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["4::user-supplied-handle"]}}))
    assert result.status == SubmissionStatus.FAILED
    assert [call[1] for call in provider.calls] == ["/portal/create"]


@pytest.mark.parametrize("account", ["tcl_promo", "tchfl"])
@pytest.mark.parametrize("fmt,mime,raw", [
    ("IMAGE", "image/jpeg", b"\xff\xd8\xfforiginal"),
    ("VIDEO", "video/mp4", b"\x00\x00\x00\x18ftypmp42original"),
    ("DOCUMENT", "application/pdf", b"%PDF-1.4 original"),
])
def test_portal_media_scope_and_embedded_bytes(provider, monkeypatch, account, fmt, mime, raw):
    portal_credentials(monkeypatch, account.upper())
    result = submit(submission({"type": "HEADER", "format": fmt, "image_bytes": raw}, account=account))
    assert result.status == SubmissionStatus.SUBMITTED
    upload, create = provider.calls
    assert upload[1] == "/portal/mediaUpload"
    parts = multipart(upload)
    assert parts["file"].get_payload(decode=True) == raw
    assert parts["file"].get_content_type() == mime
    assert parts["waba_id"].get_payload(decode=True).decode() == f"local-{account.upper()}-waba"
    assert parts["esmeaddr"].get_payload(decode=True).decode() == f"local-{account.upper()}-esme"
    assert upload[3]["Authorization"] == f"Bearer local-{account.upper()}-portal"
    body = json.loads(multipart(create)["request"].get_payload(decode=True))
    assert body["waba_id"] == f"local-{account.upper()}-waba"
    assert body["components"][0] == {"type": "HEADER", "format": fmt, "example": {"header_handle": ["4::local-portal-handle"]}}


def test_named_and_repeated_placeholders_get_one_sample_per_variable(provider):
    result = submit(submission({"type": "BODY", "text": "Dear <name>, <name> can claim {offer}."}))
    assert result.status == SubmissionStatus.SUBMITTED
    body = json.loads(create_calls(provider)[0][2])["components"][0]
    assert body["text"] == "Dear {{1}}, {{1}} can claim {{2}}."
    assert len(body["example"]["body_text"][0]) == 2
    assert body["example"]["body_text"][0][0] == "John"


@pytest.mark.parametrize("response,accepted", [
    ([], True), ({"templates": []}, True), ({"Success": {"templates": []}}, True),
    ({"response": {"templates": []}}, True), ({"Failed": "No Records Found"}, True),
    ({"Success": []}, True), ({"response": []}, True),
    ({}, False), ({"Success": {}}, False), ({"response": {}}, False),
    ({"status": "success"}, False), ({"Success": {"message": "ok"}}, False),
    ({"templates": [None]}, False), ({"templates": [], "success": False}, False),
    ({"response": {"templates": [], "error": "expired"}}, False),
    ({"Success": {"templates": [], "status": "failed"}}, False),
    ({"Failed": "No Records Found", "error": "expired"}, False),
    ([{"waba_id": "local-TCHFL-waba", "esmeaddr": "0"}], False),
    ([{"waba_id": "local-TCL_PROMO-waba", "esmeaddr": "0"}], True),
    ({"response": {"templates": [], "wabaId": "local-TCHFL-waba"}}, False),
    ([{"wabaId": "local-TCL_PROMO-waba", "esmeaddr": "other-esme"}], False),
])
def test_portal_validation_requires_inventory_and_matching_identity(provider, response, accepted):
    provider.routes["/portal/getAllTemplates"] = (200, response)
    valid, message = client.check_portal_credentials(
        "tcl_promo", bearer_token="local-private-bearer", session_id="local-private-session",
        portal_user="local-user",
    )
    assert valid is accepted
    assert message
    assert len(provider.calls) == 1
    request = json.loads(provider.calls[0][2])
    assert request["wabaId"] == "local-TCL_PROMO-waba"
    assert request["esmeaddr"] == "local-TCL_PROMO-esme"


@pytest.mark.parametrize("portal", [False, True])
@pytest.mark.parametrize("http", [200, 400, 409])
def test_duplicate_does_not_fabricate_provider_identity_or_approval(provider, monkeypatch, portal, http):
    if portal:
        portal_credentials(monkeypatch)
    provider.routes["/portal/create" if portal else "/official/local-TCL_PROMO-waba"] = (
        http, {"Failed": "Template already exists"},
    )
    result = submit(submission())
    assert result.status == SubmissionStatus.DUPLICATE
    assert result.provider_ref_id is None
    assert result.approval_status.value == "unknown"
    assert len(create_calls(provider)) == 1


@pytest.mark.parametrize("approval", ["APPROVED", "PENDING", "REJECTED"])
def test_duplicate_reconciles_only_verified_live_provider_record(provider, approval):
    provider.routes["/official/local-TCL_PROMO-waba"] = (409, {"Failed": "Template already exists"})
    provider.routes[("GET", "/official/local-TCL_PROMO-waba")] = (200, {"response": {"templates": [{
        "template_name": "boundary_campaign", "language": "en", "waba_id": "local-TCL_PROMO-waba",
        "esmeaddr": 0, "fb_template_id": "existing-verified-id", "template_create_status": approval,
    }]}})
    result = submit(submission())
    assert result.status == SubmissionStatus.DUPLICATE
    assert result.provider_ref_id == "existing-verified-id"
    assert result.approval_status.value == approval.lower()
    assert len(create_calls(provider)) == 1


@pytest.mark.parametrize("different", [
    {"template_name": "other_campaign"}, {"language": "hi"}, {"waba_id": "local-TCHFL-waba"},
    {"esmeaddr": "other-account"}, {"fb_template_id": None},
])
def test_duplicate_cannot_adopt_an_unrelated_or_unverifiable_record(provider, different):
    provider.routes["/official/local-TCL_PROMO-waba"] = (409, {"Failed": "Template already exists"})
    row = {"template_name": "boundary_campaign", "language": "en", "waba_id": "local-TCL_PROMO-waba",
           "esmeaddr": 0, "fb_template_id": "existing-verified-id", "template_create_status": "APPROVED", **different}
    provider.routes[("GET", "/official/local-TCL_PROMO-waba")] = (200, {"response": {"templates": [row]}})
    result = submit(submission())
    assert result.status == SubmissionStatus.DUPLICATE
    assert result.provider_ref_id is None
    assert result.approval_status.value == "unknown"
    assert len(create_calls(provider)) == 1


@pytest.mark.parametrize("header_type,http,status,job_status,reference", [
    ("", 201, "submitted", "COMPLETED", "real-batch-id"),
    ("", 400, "failed", "FAILED", None),
    ("IMAGE", 201, "submitted", "COMPLETED", "real-batch-id"),
])
def test_batch_records_provider_outcomes_on_its_own_rows(
    provider, provision_user, header_type, http, status, job_status, reference,
):
    """A failed legacy history insert must not strand an already-submitted batch."""
    import api
    import db
    from fastapi.testclient import TestClient

    _, headers = provision_user(tenant="tata")
    # Reproduce the zero-results path: the old tracker swallowed this write error.
    with db.get_db() as conn:
        conn.execute("""
            CREATE TRIGGER reject_shared_history BEFORE INSERT ON ingestion_jobs
            WHEN NEW.id = 'job_direct_submissions'
            BEGIN SELECT RAISE(ABORT, 'shared history unavailable'); END
        """)
    provider.routes["/official/local-TCHFL-waba"] = (
        http, {"response": {"templateId": "real-batch-id"}} if http == 201 else {"error": "Invalid template"},
    )
    response = TestClient(api.app).post(
        "/api/submit?account=tchfl&channel=whatsapp&expected_account=tchfl&expected_channel=whatsapp&skip_duplicates=false&fix_grammar=false",
        headers=headers,
        files={"file": ("batch.csv", f"template_name,header_type,body_text\nbatch_offer,{header_type},Your offer is ready.\n", "text/csv")},
    )
    assert response.status_code == 200, response.text
    batch = response.json()
    assert batch["status"] == job_status, batch
    assert [(row["template_name"], row["status"], row["provider_ref_id"]) for row in batch["results"]] == [
        ("batch_offer", status, reference),
    ]
    snapshot = TestClient(api.app).get(f"/api/jobs/{batch['job_id']}", headers=headers).json()
    assert snapshot["job"]["total_count"] == 1
    assert snapshot["job"]["submitted_count"] == (status == "submitted")
    assert snapshot["job"]["failed_count"] == (status == "failed")
    assert snapshot["tasks"][0]["status"] == status.upper()
    assert batch["results"][0]["task_id"] == snapshot["tasks"][0]["id"]
    assert len(create_calls(provider)) == (1 if status == "submitted" else 1)


def test_reviewed_upload_stays_on_selected_account_despite_detection(provider, provision_user):
    import api
    from fastapi.testclient import TestClient

    _, headers = provision_user(tenant="tata")
    http = TestClient(api.app)
    csv = (
        "template_name,header_type,header_text,body_text\n"
        "wealth_portfolio,TEXT,WEALTH TATAWL TATA_WEALTH,Explore your wealth securities portfolio demat trading options.\n"
    )
    upload = {"file": ("review.csv", csv, "text/csv")}
    preview = http.post("/api/preview", params={"account": "tcl_promo", "channel": "whatsapp"},
                        headers=headers, files=upload)
    assert preview.status_code == 200, preview.text
    suggestion = preview.json()[0]["account_detection"]
    assert suggestion["detected_account_id"] == "wealth"
    assert suggestion["is_mismatch"] is True
    result = http.post("/api/submit", params={
        "account": "tcl_promo", "channel": "whatsapp",
        "expected_account": "tcl_promo", "expected_channel": "whatsapp",
        "skip_duplicates": "false", "fix_grammar": "false",
    }, headers=headers, files=upload)
    assert result.status_code == 200, result.text
    batch = result.json()
    assert (batch["account"], batch["channel"]) == ("tcl_promo", "whatsapp")
    assert [(row["client"], row["channel"], row["status"]) for row in batch["results"]] == [
        ("tcl_promo", "whatsapp", "submitted"),
    ]
    assert [call[1] for call in create_calls(provider)] == ["/official/local-TCL_PROMO-waba"]
    snapshot = http.get(f"/api/jobs/{batch['job_id']}", headers=headers).json()
    assert (snapshot["job"]["tenant_id"], snapshot["job"]["channel"]) == ("tcl_promo", "whatsapp")


@pytest.mark.parametrize("account,channel,expected_account,expected_channel,status", [
    ("wealth", "rcs", "tcl_promo", "whatsapp", 409),
    ("tchfl", "whatsapp", "tcl_promo", "whatsapp", 409),
    ("tcl_promo", "rcs", "tcl_promo", "whatsapp", 409),
    ("all", "whatsapp", "all", "whatsapp", 400),
    ("tcl_promo", "other", "tcl_promo", "other", 400),
])
def test_submit_rejects_destination_changed_since_review(
    provider, provision_user, account, channel, expected_account, expected_channel, status,
):
    import api
    import db
    from fastapi.testclient import TestClient

    _, headers = provision_user(tenant="all", role="superadmin")
    response = TestClient(api.app).post("/api/submit", params={
        "account": account, "channel": channel, "expected_account": expected_account,
        "expected_channel": expected_channel,
    }, headers=headers, files={"file": ("review.csv", "template_name,body_text\nreview,Hello", "text/csv")})
    assert response.status_code == status, response.text
    assert not create_calls(provider)
    with db.get_db() as connection:
        assert connection.execute("SELECT COUNT(*) FROM ingestion_jobs").fetchone()[0] == 0


@pytest.mark.parametrize("field,value", [
    ("client", "wealth"), ("account", "wealth"), ("channel", "rcs"), ("waba_id", "another-waba"),
])
@pytest.mark.parametrize("extension", ["csv", "xlsx"])
@pytest.mark.parametrize("endpoint", ["preview", "submit"])
def test_spreadsheet_cannot_override_selected_destination(
    provider, provision_user, field, value, extension, endpoint,
):
    import api
    from fastapi.testclient import TestClient

    _, headers = provision_user(tenant="tata")
    rows = [["template_name", "body_text", field], ["review", "Your offer is ready.", value]]
    if extension == "xlsx":
        import openpyxl
        workbook = openpyxl.Workbook()
        for row in rows:
            workbook.active.append(row)
        content = io.BytesIO()
        workbook.save(content)
        payload = content.getvalue()
    else:
        payload = "\n".join(",".join(row) for row in rows).encode()
    response = TestClient(api.app).post(f"/api/{endpoint}", params={
        "account": "tcl_promo", "channel": "whatsapp",
        "expected_account": "tcl_promo", "expected_channel": "whatsapp",
    }, headers=headers, files={"file": (f"review.{extension}", payload, "application/octet-stream")})
    assert response.status_code == 400, response.text
    assert not create_calls(provider)


def test_submit_requires_explicit_review_scope(provider, provision_user):
    import api
    from fastapi.testclient import TestClient

    _, headers = provision_user(tenant="tata")
    http = TestClient(api.app)
    files = {"file": ("review.csv", "template_name,body_text\nreview,Hello", "text/csv")}
    for params in ({}, {"account": "tcl_promo", "channel": "whatsapp"}):
        response = http.post("/api/submit", params=params, headers=headers, files=files)
        assert response.status_code == 422, response.text
    assert not create_calls(provider)


def test_all_accounts_is_not_a_preview_destination(provider, provision_user):
    import api
    from fastapi.testclient import TestClient

    _, headers = provision_user(tenant="all", role="superadmin")
    response = TestClient(api.app).post("/api/preview", params={"account": "all", "channel": "whatsapp"},
        headers=headers, files={"file": ("review.csv", "template_name,body_text\nreview,Hello", "text/csv")})
    assert response.status_code == 400, response.text
    assert not create_calls(provider)
