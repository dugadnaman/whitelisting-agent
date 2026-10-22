"""Real HTTP boundary tests: only a loopback provider and temporary local media."""
import csv
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import requests
from PIL import Image

import rcs_client
import rcs_config
from rcs_loader import (
    _build_carousel_cards_from_row,
    _build_suggestions_from_row,
    _upload_and_bind_rcs_images,
    check_rcs_image_aspect_ratio,
    load_rcs_from_excel,
    load_rcs_from_list,
    parse_single_cell_card_block,
)
from rcs_models import RcsSubmissionStatus, RcsTemplateSubmission

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "rcs_templates_sample.csv"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rcs_config, "_load_env_file", lambda: None)
    monkeypatch.setenv("TCL_PROMO_RCS_AUTH_TOKEN", "local-test-token")
    monkeypatch.setenv("TCL_PROMO_RCS_BOT_ID", "Uv9tdd0KNADbq3pX")
    monkeypatch.setenv("TCL_PROMO_RCS_ESMEADDR", "72434700000000")
    real_request = requests.Session.request

    def local_request(session, method, url, **kwargs):
        assert urlsplit(url).hostname == "127.0.0.1", "External network is forbidden"
        return real_request(session, method, url, **kwargs)

    monkeypatch.setattr(requests.Session, "request", local_request)


@pytest.fixture
def provider(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        routes = {
            "/save": (200, {"status": "success", "templateId": "local-provider-ref"}),
            "/upload": (200, {"fileName": "local-provider-media.png"}),
            "/inventory": (200, {"templateInfo": []}),
        }
        calls = []
        def do_GET(self):
            self.send_response(405)
            self.end_headers()


        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.calls.append((self.path, body, dict(self.headers)))
            status, payload = self.routes[self.path]
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload if isinstance(payload, bytes) else json.dumps(payload).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(rcs_client, "KARIX_RCS_SAVE_URL", base + "/save")
    monkeypatch.setattr(rcs_client, "KARIX_RCS_MEDIA_UPLOAD_URL", base + "/upload")
    monkeypatch.setattr(rcs_client, "KARIX_RCS_FETCH_TEMPLATES_URL", base + "/inventory")
    monkeypatch.setattr(rcs_client, "KARIX_RCS_FETCH_URL", base + "/inventory")
    try:
        yield Handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def text_submission():
    with SAMPLE.open(newline="") as stream:
        row = list(csv.DictReader(stream))[1]
    return load_rcs_from_list([row], client="tcl_promo")[0]


def image_bytes(color="red"):
    stream = io.BytesIO()
    Image.new("RGB", (160, 90), color).save(stream, format="PNG")
    return stream.getvalue()


@pytest.mark.parametrize("response", [
    {}, {"status": "success", "message": "Template Added"}, [], b"<html>login</html>",
    {"id": True}, {"id": []}, {"id": {}}, {"id": "  "}, {"id": "null"},
    {"id": 0}, {"id": "0"}, {"id": -1}, {"id": 1.2},
    {"id": "one", "data": {"templateId": "two"}},
])
def test_no_provider_reference_never_reports_submission(provider, response):
    provider.routes["/save"] = (200, response)
    submission = text_submission()
    submission.template_id = "DLT-id-is-not-a-provider-reference"
    result = rcs_client.submit_rcs_template(submission)
    assert result.status == RcsSubmissionStatus.FAILED
    assert result.outcome_uncertain
    assert result.provider_ref_id is None
    assert len(provider.calls) == 1


@pytest.mark.parametrize("response,reference", [
    ({"templateId": "actual-ref"}, "actual-ref"),
    ({"data": {"id": 123}}, "123"),
])
def test_real_reference_is_required_and_preserved(provider, response, reference):
    provider.routes["/save"] = (200, response)
    result = rcs_client.submit_rcs_template(text_submission())
    assert result.status == RcsSubmissionStatus.SUBMITTED
    assert result.provider_ref_id == reference
    body = json.loads(provider.calls[0][1])
    assert body["esmeAddr"] == 72434700000000
    assert body["viTemplate"]["botId"] == "Uv9tdd0KNADbq3pX"
    assert body["viTemplate"]["textMessage"].startswith("Dear [1]")


@pytest.mark.parametrize("http,response,expected,uncertain", [
    (200, {"status": "error", "message": "Template already exists"}, "duplicate", False),
    (409, {"error": "Duplicate template"}, "duplicate", False),
    (401, {"error": "Duplicate authentication session"}, "failed", False),
    (403, {"message": "Template already exists"}, "failed", False),
    (500, {"error": "Duplicate upstream request"}, "failed", True),
    (429, {"error": "Rate limited"}, "failed", True),
    (200, {"success": False, "templateId": "not-accepted"}, "failed", False),
    (200, {"id": "not-accepted", "data": {"errorCode": "AUTH"}}, "failed", False),
    (302, {}, "failed", False),
])
def test_provider_failures_never_replay_save(provider, http, response, expected, uncertain):
    provider.routes["/save"] = (http, response)
    result = rcs_client.submit_rcs_template(text_submission())
    assert str(result.status) == expected
    assert result.outcome_uncertain is uncertain
    assert result.provider_ref_id is None
    assert len(provider.calls) == 1


def test_request_timeout_is_ambiguous_not_retried(monkeypatch):
    calls = []

    def timeout(*args, **kwargs):
        calls.append(args)
        raise requests.ReadTimeout("simulated interrupted response")

    monkeypatch.setattr(rcs_client.requests, "post", timeout)
    result = rcs_client.submit_rcs_template(text_submission())
    assert result.status == RcsSubmissionStatus.FAILED
    assert result.outcome_uncertain
    assert len(calls) == 1


@pytest.mark.parametrize("http,response", [
    (401, {}), (500, {}), (200, {}), (200, b"bad json"),
    (200, {"templateInfo": [None]}), (200, {"success": False, "templateInfo": []}),
])
def test_unavailable_inventory_is_not_an_empty_inventory(provider, http, response):
    provider.routes["/inventory"] = (http, response)
    with pytest.raises(rcs_client.RcsInventoryUnavailable):
        rcs_client.fetch_rcs_templates(client="tcl_promo")


def test_valid_empty_inventory_is_empty(provider):
    assert rcs_client.fetch_rcs_templates(client="tcl_promo") == []
    assert len(provider.calls) == 1


@pytest.mark.parametrize("override", [
    {"client": "bajaj"}, {"bot_id": "af2vdbyFh3RX8eee"}, {"esme_addr": "72148300000000"},
])
def test_row_cannot_select_another_account(override):
    with pytest.raises(ValueError, match="selected account"):
        load_rcs_from_list([{"template_name": "safe", "body": "Copy", **override}], client="tcl_promo")


def test_payload_cannot_override_selected_account(provider):
    submission = text_submission()
    submission.bot_id = "af2vdbyFh3RX8eee"
    result = rcs_client.submit_rcs_template(submission)
    assert result.status == RcsSubmissionStatus.FAILED
    assert not provider.calls


def test_credentials_are_explicit_not_another_channel_or_sanitized_account(monkeypatch):
    monkeypatch.delenv("TCL_PROMO_RCS_AUTH_TOKEN")
    monkeypatch.delenv("TCL_PROMO_KARIX_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("TCL_PROMO_WABA_AUTH_TOKEN", "not-rcs")
    monkeypatch.setenv("TCL_PROMO_AUTH_TOKEN", "not-rcs")
    monkeypatch.setenv("BAJAJ_RCS_AUTH_TOKEN", "other-account")
    with pytest.raises(OSError):
        rcs_config.get_rcs_auth_headers("tcl_promo")
    with pytest.raises(ValueError):
        rcs_config.get_rcs_auth_headers("tcl-promo")
    with pytest.raises(ValueError):
        rcs_config.get_rcs_bot_id("")


@pytest.mark.parametrize("column,value", [
    ("suggestions", "{broken"), ("suggestions", '{"text":"bad"}'),
    ("suggestions", '["bad"]'), ("carousel_cards", "[broken"),
    ("carousel_cards", '[null]'),
])
def test_malformed_json_is_not_silently_replaced(column, value):
    with pytest.raises(ValueError):
        load_rcs_from_list([{"template_name": "bad_json", "body": "Copy", column: value}], client="tcl_promo")


def test_carousel_blanks_and_cta_types_stay_with_their_card():
    cards = _build_carousel_cards_from_row({
        "card_title": "First||Third", "body": "One|Two|Three", "media_url": "|https://example.test/two.png|",
        "button_text": "Reply|Call|Open", "button_type": "REPLY|DIALER|URL",
        "button_phone": "|+919999999999|", "button_url": "||https://example.test/three",
    })
    assert [card["cardTitle"] for card in cards] == ["First", "", "Third"]
    assert [card["mediaUrl"] for card in cards] == ["", "https://example.test/two.png", ""]
    assert [card["suggestions"][0]["suggestionType"] for card in cards] == ["reply", "dialer_action", "url_action"]
    assert cards[1]["suggestions"][0]["phoneNumber"] == "+919999999999"
    assert cards[2]["suggestions"][0]["url"] == "https://example.test/three"


def test_copy_and_cta_are_not_invented_or_removed():
    card = parse_single_cell_card_block("Dear [Name]\nTap below to apply\nCTA Button: See Offer\nCTA URL: https://example.test/offer")
    assert card["card_title"] == "Dear [Name]"
    assert card["card_description"] == "Dear [Name]\n\nTap below to apply"
    assert card["button_url"] == "https://example.test/offer"
    plain = parse_single_cell_card_block("Home loan copy without CTA")
    assert plain["button_text"] == plain["button_url"] == ""
    assert _build_suggestions_from_row(plain) == []


def test_truncated_image_header_is_not_a_valid_image(provider):
    data = image_bytes()[:50]
    assert not check_rcs_image_aspect_ratio(data, "carousel")[0]
    submission = RcsTemplateSubmission(template_name="truncated", template_type="richcard", client="tcl_promo", image_bytes=data)
    result = rcs_client.submit_rcs_template(submission)
    assert result.status == RcsSubmissionStatus.BLOCKED_ASPECT_RATIO
    assert not provider.calls


def test_excel_embedded_media_uploads_once_not_a_local_provider_filename(provider, tmp_path):
    import openpyxl
    from openpyxl.drawing.image import Image as SheetImage

    with SAMPLE.open(newline="") as stream:
        sample_rows = list(csv.DictReader(stream))
    row = sample_rows[0]
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(list(row))
    row["media_url"] = ""
    sheet.append(list(row.values()))
    for cell in ("E2", "F2"):
        sheet.add_image(SheetImage(io.BytesIO(image_bytes())), cell)
    path = tmp_path / "actual_sample_embedded.xlsx"
    workbook.save(path)
    submissions = load_rcs_from_excel(str(path), client="tcl_promo", upload_media=False)
    submission = submissions[0]
    assert len(submission.carousel_cards) == 2
    assert not provider.calls
    assert all(not card.get("fileName") for card in submission.carousel_cards)
    assert all(card["image_bytes"] == image_bytes() for card in submission.carousel_cards)
    result = rcs_client.submit_rcs_template(submission)
    assert result.status == RcsSubmissionStatus.SUBMITTED
    assert [call[0] for call in provider.calls] == ["/upload", "/save"]
    save = json.loads(provider.calls[-1][1])
    assert all(card["fileName"] == "local-provider-media.png" for card in save["viTemplate"]["carouselCard"])
    assert all("mediaUrl" not in card for card in save["viTemplate"]["carouselCard"])


def test_cached_previews_do_not_collide_for_same_template_name():
    submissions = []
    for color in ("red", "blue"):
        sub = RcsTemplateSubmission(template_name="identical", template_type="richcard", client="tcl_promo")
        _upload_and_bind_rcs_images([("source.png", image_bytes(color))], [sub], client="tcl_promo", upload_now=False)
        submissions.append(sub)
    assert submissions[0].media_url != submissions[1].media_url
    assert all(sub.file_name is None for sub in submissions)
    assert len(list(Path("media_cache").iterdir())) == 2


def test_spatial_media_is_not_reassigned_to_another_row():
    first = RcsTemplateSubmission(template_name="first", template_type="richcard", client="tcl_promo")
    first._excel_row = 2
    second = RcsTemplateSubmission(template_name="second", template_type="richcard", client="tcl_promo")
    second._excel_row = 3
    _upload_and_bind_rcs_images([("image.png", image_bytes())], [first, second], client="tcl_promo", spatial_images={2: [("image.png", image_bytes())]}, upload_now=False)
    assert first.image_bytes
    assert second.image_bytes is None


@pytest.mark.parametrize("response", [
    {"status": "success"}, {"fileName": 123}, {"fileName": "null"},
    {"fileName": {}}, {"fileName": "  "}, {"status": "failed", "fileName": "not-accepted"},
])
def test_upload_failure_has_no_save_or_guessed_media_fallback(provider, response):
    provider.routes["/upload"] = (200, response)
    sub = RcsTemplateSubmission(template_name="upload_failure", template_type="richcard", client="tcl_promo", image_bytes=image_bytes())
    result = rcs_client.submit_rcs_template(sub)
    assert result.status == RcsSubmissionStatus.FAILED
    assert [call[0] for call in provider.calls] == ["/upload"]
    assert sub.file_name is None


@pytest.mark.parametrize("dimensions", [(1160, 720), (1800, 720)])
def test_documented_short_carousel_dimensions_are_accepted(dimensions):
    stream = io.BytesIO()
    Image.new("RGB", dimensions).save(stream, format="PNG")
    assert check_rcs_image_aspect_ratio(stream.getvalue(), "carousel")[0]


def test_explicit_cta_type_is_not_overridden_by_unrelated_fields():
    reply = _build_suggestions_from_row({"button_type": "REPLY", "button_text": "Confirm", "button_url": "https://example.test", "button_phone": "+919999999999"})
    assert reply == [{"suggestionType": "reply", "text": "Confirm", "postbackData": "Confirm"}]
    link = _build_suggestions_from_row({"button_type": "URL", "button_text": "Open", "button_url": "https://example.test", "button_phone": "+919999999999"})
    assert link[0]["suggestionType"] == "url_action"


def test_http200_auth_error_cannot_be_misclassified_as_duplicate(provider):
    provider.routes["/save"] = (200, {"status": "error", "errorCode": "401", "message": "Duplicate authentication session"})
    result = rcs_client.submit_rcs_template(text_submission())
    assert result.status == RcsSubmissionStatus.FAILED
    assert not result.outcome_uncertain
    assert result.auth_refused
    assert len(provider.calls) == 1


@pytest.mark.parametrize("response", [
    {"id": "not-enough", "status": {}},
    {"id": "not-enough", "success": "maybe"},
    {"id": "not-enough", "data": []},
])
def test_malformed_success_envelope_is_ambiguous(provider, response):
    provider.routes["/save"] = (200, response)
    result = rcs_client.submit_rcs_template(text_submission())
    assert result.status == RcsSubmissionStatus.FAILED
    assert result.outcome_uncertain
    assert result.provider_ref_id is None


@pytest.mark.parametrize("kind", ["rich_card", "RICH_CARD_STANDALONE", "richcard"])
def test_rich_card_type_aliases_do_not_silently_become_text(kind):
    submission = load_rcs_from_list([{
        "template_name": "explicit_card", "template_type": kind,
        "card_title": "Offer", "body": "Customer offer",
    }], client="tcl_promo")[0]
    assert submission.template_type == "richcard"


def test_unknown_template_type_is_rejected_before_submission(provider):
    with pytest.raises(ValueError, match="Unsupported RCS template type"):
        load_rcs_from_list([{
            "template_name": "wrong_type", "template_type": "richcrad", "body": "Customer offer",
        }], client="tcl_promo")
    assert provider.calls == []


@pytest.mark.parametrize("http_status", [401, 403, 500])
def test_upload_only_definitive_auth_decline_sets_refusal(provider, http_status):
    provider.routes["/upload"] = (http_status, {"error": "Provider declined request"})
    sub = RcsTemplateSubmission(template_name="upload_auth", template_type="richcard", client="tcl_promo", image_bytes=image_bytes())
    result = rcs_client.submit_rcs_template(sub)
    assert result.status == RcsSubmissionStatus.FAILED
    assert result.auth_refused is (http_status in (401, 403))
    assert not result.outcome_uncertain
    assert [call[0] for call in provider.calls] == ["/upload"]


@pytest.fixture
def authenticated_provider(provider, monkeypatch):
    import jwt

    key = "local-rcs-credential-regression-only-signing-key-0123456789abcdef"
    token = jwt.encode({"sub": "tcl_promo", "exp": 4000000000}, key, algorithm="HS256")
    original_post = provider.do_POST

    def authenticated_post(handler):
        authorization = handler.headers.get("Authorization", "")
        try:
            scheme, supplied_token = authorization.split(" ", 1)
            claims = jwt.decode(supplied_token, key, algorithms=["HS256"])
            authorized = scheme.lower() == "bearer" and claims.get("sub") == "tcl_promo"
        except (ValueError, jwt.InvalidTokenError):
            authorized = False
        if authorized:
            return original_post(handler)
        handler.rfile.read(int(handler.headers.get("Content-Length", 0)))
        handler.send_response(401)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()
        handler.wfile.write(b'{"error": "Invalid credentials"}')

    monkeypatch.setattr(provider, "do_POST", authenticated_post)
    provider.routes["/inventory"] = (200, {"templateInfo": [{"name": "Authenticated offer"}]})
    return provider, token


@pytest.mark.parametrize("paste_format", ["{}", "Bearer {}", "Authorization: Bearer {}"])
def test_valid_rcs_token_copied_from_devtools_authenticates(authenticated_provider, monkeypatch, paste_format):
    provider, token = authenticated_provider
    monkeypatch.setenv("TCL_PROMO_RCS_AUTH_TOKEN", paste_format.format(token))
    templates = rcs_client.fetch_rcs_templates(client="tcl_promo")
    assert templates == [{"name": "Authenticated offer"}]
    assert [call[0] for call in provider.calls] == ["/inventory"]


@pytest.mark.parametrize("valid", [True, False])
def test_rcs_connection_checks_entered_token_without_replacing_saved_credentials(
    authenticated_provider, monkeypatch, provision_user, valid,
):
    import os
    import api
    from fastapi.testclient import TestClient

    _, token = authenticated_provider
    _, headers = provision_user(tenant="tata")
    monkeypatch.setattr(api, "_load_env_file", lambda: None)
    supplied = f"Authorization: Bearer {token}" if valid else "invalid-entered-token"
    response = TestClient(api.app, headers=headers).post("/api/test-credentials", json={
        "account": "tcl_promo", "channel": "rcs",
        "rcs_auth_token": supplied, "rcs_bot_id": "Uv9tdd0KNADbq3pX",
    })
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is valid, result["message"]
    if valid:
        assert result["template_count"] == 1
    else:
        assert "401" in result["message"]
    assert os.environ["TCL_PROMO_RCS_AUTH_TOKEN"] == "local-test-token"

def test_rcs_connection_accepts_token_in_lounge_cookie_field(
    authenticated_provider, monkeypatch, provision_user,
):
    import os
    import api
    from fastapi.testclient import TestClient

    _, token = authenticated_provider
    _, headers = provision_user(tenant="tata")
    monkeypatch.setattr(api, "_load_env_file", lambda: None)
    response = TestClient(api.app, headers=headers).post("/api/test-credentials", json={
        "account": "tcl_promo", "channel": "rcs",
        "lounge_cookie": f"Bearer {token}", "rcs_bot_id": "Uv9tdd0KNADbq3pX",
    })
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is True
    assert result["template_count"] == 1


def test_rcs_connection_refuses_cross_tenant_credentials_before_contacting_provider(
    authenticated_provider, monkeypatch, provision_user,
):
    import api
    from fastapi.testclient import TestClient

    provider, token = authenticated_provider
    _, headers = provision_user(tenant="bajaj")
    monkeypatch.setattr(api, "_load_env_file", lambda: None)
    response = TestClient(api.app, headers=headers).post("/api/test-credentials", json={
        "account": "tcl_promo", "channel": "rcs", "rcs_auth_token": token,
    })
    assert response.status_code == 403
    assert provider.calls == []


def test_saved_rcs_header_paste_authenticates_inventory_without_changing_another_company(
    authenticated_provider, monkeypatch, provision_user,
):
    import os
    import api
    from fastapi.testclient import TestClient

    _, token = authenticated_provider
    _, headers = provision_user(tenant="tata")
    monkeypatch.setenv("BAJAJ_RCS_AUTH_TOKEN", "bajaj-only-synthetic-token")
    response = TestClient(api.app, headers=headers).put("/api/credentials", json={
        "account": "tcl_promo", "channel": "rcs",
        "rcs_auth_token": f"Authorization: Bearer {token}",
    })
    assert response.status_code == 200
    assert rcs_client.fetch_rcs_templates(client="tcl_promo") == [{"name": "Authenticated offer"}]
    assert os.environ["BAJAJ_RCS_AUTH_TOKEN"] == "bajaj-only-synthetic-token"
    from portal_sessions import load_session
    assert load_session("tcl_promo", "rcs")["bearer_token"] == token
    assert load_session("bajaj", "rcs") is None


def test_apparel_all_ten_sender_ids_configured():
    from rcs_config import APPAREL_ALL_RCS_BOT_IDS, get_rcs_bot_ids, get_rcs_bot_id
    assert len(APPAREL_ALL_RCS_BOT_IDS) == 10
    assert "P7hzkqCcW3x96I6T" in APPAREL_ALL_RCS_BOT_IDS
    assert "6aa232b4734aa52ea966d1b4" in APPAREL_ALL_RCS_BOT_IDS
    assert "6aa23696b110433d2a28c793" in APPAREL_ALL_RCS_BOT_IDS
    assert "6aa2396e734aa52ea966d23f" in APPAREL_ALL_RCS_BOT_IDS
    assert "6aa23c2d734aa52ea966d26f" in APPAREL_ALL_RCS_BOT_IDS
    assert "axf2bekeNANA8h90" in APPAREL_ALL_RCS_BOT_IDS
    assert "pp6wKCHJhdAlvEP6" in APPAREL_ALL_RCS_BOT_IDS
    assert "Wk4lAtdRnQmXTHXF" in APPAREL_ALL_RCS_BOT_IDS
    assert "Wk4lBploJGyg1Dlr" in APPAREL_ALL_RCS_BOT_IDS
    assert "Wk5ESRsm6mAwxjZo" in APPAREL_ALL_RCS_BOT_IDS
    assert get_rcs_bot_ids("apparel") == APPAREL_ALL_RCS_BOT_IDS
    assert get_rcs_bot_id("apparel") == "P7hzkqCcW3x96I6T"

