"""Reviewed upload edits reach dispatch without trusting client identity or metadata."""
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api
import config
from models import TemplateComponent, TemplateSubmission
from upload_review import apply_template_overrides, parse_template_overrides


@pytest.fixture
def client(provision_user, monkeypatch):
    _, headers = provision_user("tata")
    monkeypatch.setattr(api, "_fetch_whatsapp_inventory", lambda client: ([], None))
    monkeypatch.setattr(config, "_load_env_file", lambda: None)
    return TestClient(api.app, headers=headers)


UPLOAD = ("original.csv", "template_name,body_text,language\noriginal,मूळ संदेश आहे.,mr\n".encode())
QUERY = "account=tcl_promo&channel=whatsapp&expected_account=tcl_promo&expected_channel=whatsapp"


def test_reviewed_payload_is_dispatched_and_original_upload_unchanged(client, monkeypatch):
    original = client.post("/api/preview?" + QUERY, files={"file": UPLOAD}).json()[0]
    body = "नमस्कार! तुमचा अर्ज तयार आहे.\nअचूक मराठी मजकूर."
    patch = {"template_name": "reviewed_marathi", "category": "UTILITY", "language": "mr", "components": [
        {"type": "BODY", "text": body},
        {"type": "FOOTER", "text": "अटी लागू"},
        {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "होय"}]},
    ]}
    data = {"template_overrides": json.dumps({original["source_ref"]: patch})}
    reviewed = client.post("/api/preview?" + QUERY, files={"file": UPLOAD}, data=data)
    assert reviewed.status_code == 200, reviewed.text
    row = reviewed.json()[0]
    reviewed_components = row["components"]
    reviewed_body = next(c["text"] for c in reviewed_components if c["type"] == "BODY")
    reviewed_buttons = next(c["buttons"] for c in reviewed_components if c["type"] == "BUTTONS")
    assert reviewed_body == body + "\n\nअटी लागू"
    assert reviewed_buttons[0]["text"] == "होय"
    assert all(c["type"] != "FOOTER" for c in reviewed_components)
    assert row["review_edits_active"] and not row["grammar_autofix_enabled"]
    assert row["source_ref"] == original["source_ref"]
    dispatched = []
    def runner(rows, log_path, *, task_ids, fix_grammar, **kwargs):
        from db_queue import record_task_result
        assert fix_grammar is False
        dispatched.extend(rows)
        for task_id in task_ids:
            record_task_result(task_id, "submitted", "pending", "reviewed-ref")
        return rows
    monkeypatch.setattr(api, "run", runner)
    response = client.post("/api/submit?" + QUERY + "&fix_grammar=true", files={"file": UPLOAD}, data=data)
    assert response.status_code == 200, response.text
    assert dispatched[0]["template_name"] == row["template_name"]
    assert dispatched[0]["category"] == "UTILITY"
    assert dispatched[0]["language"] == "mr"
    assert dispatched[0]["source_ref"] == original["source_ref"]
    assert next(c["text"] for c in dispatched[0]["components"] if c["type"] == "BODY") == reviewed_body
    assert next(c["buttons"] for c in dispatched[0]["components"] if c["type"] == "BUTTONS") == reviewed_buttons
    from submission_client import _resolve_body_variables, _template_components
    canonical = _resolve_body_variables(_template_components(TemplateSubmission(
        **{key: value for key, value in dispatched[0].items() if key != "components"},
        components=[TemplateComponent(**c) for c in dispatched[0]["components"]],
    )), client="tcl_promo", fix_grammar=False)
    assert next(c["text"] for c in canonical if c["type"] == "BODY") == reviewed_body
    unchanged = client.post("/api/preview?" + QUERY, files={"file": UPLOAD}).json()[0]
    assert unchanged["components"] == original["components"]
    assert unchanged["template_name"] == original["template_name"]


@pytest.mark.parametrize("endpoint", ["preview", "submit"])
@pytest.mark.parametrize("patch", [
    {"client": "other"}, {"channel": "rcs"}, {"waba_id": "other"}, {"source_ref": "other"},
    {"submission_ready": True}, {"aspect_ratio_blocked": False},
    {"components": [{"type": "BODY", "text": "copy"}, {"type": "HEADER", "format": "IMAGE", "media_file": "/etc/passwd"}]},
    {"components": [{"type": "BODY", "text": "copy"}, {"type": "BUTTONS", "buttons": [{"type": "URL", "text": "Open", "url": "file:///etc/passwd"}]}]},
    {"components": [{"type": "BODY", "text": "copy"}, {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "label": "not text"}]}]},
])
def test_untrusted_fields_never_queue(client, endpoint, patch):
    row = client.post("/api/preview?" + QUERY, files={"file": UPLOAD}).json()[0]
    response = client.post("/api/" + endpoint + "?" + QUERY, files={"file": UPLOAD},
                           data={"template_overrides": json.dumps({row["source_ref"]: patch})})
    assert response.status_code == 400, response.text
    from db import get_db
    with get_db() as connection:
        assert connection.execute("SELECT COUNT(*) AS n FROM ingestion_jobs").fetchone()["n"] == 0


@pytest.mark.parametrize("endpoint", ["preview", "submit"])
@pytest.mark.parametrize("payload", ["null", "[]", "bad", '{"unknown":{"template_name":"valid"}}', '{"x":{},"x":{}}'])
def test_malformed_or_unknown_sources_rejected(client, endpoint, payload):
    response = client.post("/api/" + endpoint + "?" + QUERY, files={"file": UPLOAD},
                           data={"template_overrides": payload})
    assert response.status_code == 400, response.text


def test_embedded_creative_preserved_until_header_removed():
    header = TemplateComponent("HEADER", format="IMAGE", image_bytes=b"original image", media_file="private-cache/image.png")
    submission = TemplateSubmission("tata", "whatsapp", "original", "mr", "MARKETING", "waba", [header, TemplateComponent("BODY", text="मूळ")], "file:row")
    apply_template_overrides([submission], {"file:row": {"components": [{"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "सुधारित"}]}}, "whatsapp", "tata")
    assert submission.components[0].image_bytes == b"original image"
    assert submission.components[0].media_file == "private-cache/image.png"
    apply_template_overrides([submission], {"file:row": {"components": [{"type": "BODY", "text": "सुधारित"}]}}, "whatsapp", "tata")
    assert [c.type for c in submission.components] == ["BODY"]


def test_override_size_is_bounded():
    with pytest.raises(HTTPException):
        parse_template_overrides(" " * 262145, "whatsapp")


def test_rcs_review_preserves_creative_and_rejects_provider_identity():
    from rcs_models import RcsTemplateSubmission
    submission = RcsTemplateSubmission("original", client="tata", source_ref="sheet:row",
                                       template_type="richcard", image_bytes=b"creative")
    patch = {"template_name": "edited", "card_description": "अचूक संदेश", "suggestions": [
        {"suggestionType": "reply", "text": "होय"},
    ]}
    apply_template_overrides([submission], {"sheet:row": patch}, "rcs", "tata")
    assert submission.card_description == "अचूक संदेश"
    assert submission.image_bytes == b"creative"
    assert submission.suggestions == patch["suggestions"]
    for field in ("bot_id", "esme_addr", "entity_id", "template_id", "file_name", "image_bytes"):
        with pytest.raises(HTTPException):
            parse_template_overrides(json.dumps({"sheet:row": {field: "untrusted"}}), "rcs")
    for suggestion in ({"type": "url", "label": "Open"}, {"suggestionType": [], "text": "Open"}):
        with pytest.raises(HTTPException):
            apply_template_overrides([submission], {"sheet:row": {"suggestions": [suggestion]}}, "rcs", "tata")


def test_review_shows_canonical_text_and_samples_before_provider_dispatch():
    from submission_client import _resolve_body_variables, _template_components

    source = TemplateSubmission(
        "tcl_promo", "whatsapp", "original", "mr", "MARKETING", "waba",
        [TemplateComponent("BODY", text="मूळ संदेश")], "sheet!B2",
    )
    patch = {"components": [
        {"type": "HEADER", "format": "TEXT", "text": "नमस्कार <name>"},
        {"type": "BODY", "text": "प्रिय <name> ,\r\n\r\n\r\nतुमची ऑफर तयार आहे !"},
        {"type": "BUTTONS", "buttons": [{
            "type": "URL", "text": "ऑफर पहा", "url": "https://example.com/offer/{{id}}",
        }]},
    ]}
    apply_template_overrides([source], {"sheet!B2": patch}, "whatsapp", "tcl_promo")
    before = _template_components(source)
    wire = _resolve_body_variables(_template_components(source), client="tcl_promo", fix_grammar=False)
    assert wire == before
    body = next(c for c in before if c["type"] == "BODY")
    assert body["text"] == "प्रिय {{1}},\n\nतुमची ऑफर तयार आहे!"
    assert body["example"]["body_text"]
    assert next(c for c in before if c["type"] == "BUTTONS")["buttons"][0]["text"] == "ऑफर पहा"


def test_edit_cannot_change_two_templates_sharing_a_source_reference():
    source = TemplateSubmission(
        "tcl_promo", "whatsapp", "original", "mr", "MARKETING", "waba",
        [TemplateComponent("BODY", text="मूळ संदेश")], "duplicate-source",
    )
    with pytest.raises(HTTPException, match="exactly one template"):
        apply_template_overrides([source, source], {"duplicate-source": {"language": "hi"}}, "whatsapp", "tcl_promo")


def test_explicit_rcs_media_removal_clears_embedded_asset_but_omission_preserves_it():
    from rcs_models import RcsTemplateSubmission

    submission = RcsTemplateSubmission(
        "original", client="tata", source_ref="sheet:row", template_type="richcard",
        image_bytes=b"original creative", file_name="source.png",
    )
    apply_template_overrides(
        [submission], {"sheet:row": {"card_description": "अचूक मजकूर"}}, "rcs", "tata",
    )
    assert submission.image_bytes == b"original creative"
    apply_template_overrides([submission], {"sheet:row": {"media_url": ""}}, "rcs", "tata")
    assert submission.image_bytes is None
    assert submission.file_name is None
    assert submission.media_url == ""


def test_carousel_media_removal_does_not_restore_original_creative():
    from rcs_models import RcsTemplateSubmission

    submission = RcsTemplateSubmission(
        "original", client="tata", source_ref="sheet:row", template_type="carousel",
        carousel_cards=[
            {"cardTitle": "A", "image_bytes": b"first creative", "fileName": "a.png"},
            {"cardTitle": "B", "image_bytes": b"second creative", "fileName": "b.png"},
        ],
    )
    apply_template_overrides([submission], {"sheet:row": {"carousel_cards": [
        {"cardTitle": "Edited A", "media_url": ""}, {"cardTitle": "Edited B"},
    ]}}, "rcs", "tata")
    assert submission.carousel_cards[0] == {"cardTitle": "Edited A", "media_url": ""}
    assert submission.carousel_cards[1]["image_bytes"] == b"second creative"
    assert submission.carousel_cards[1]["fileName"] == "b.png"


def test_rcs_file_edits_are_rechecked_and_dispatched_with_canonical_actions(client, monkeypatch):
    import rcs_loader
    from db_queue import record_task_result

    monkeypatch.setattr(api, "get_rcs_bot_id", lambda account: "review-bot")
    monkeypatch.setattr(rcs_loader, "get_rcs_bot_id", lambda account: "review-bot")
    monkeypatch.setattr(rcs_loader, "get_rcs_esmeaddr", lambda account: "12345")
    monkeypatch.setattr(rcs_loader, "get_rcs_entity_id", lambda account: "review-entity")
    monkeypatch.setattr(api, "_fetch_rcs_inventory", lambda account: [])
    query = "account=tcl_promo&channel=rcs&expected_account=tcl_promo&expected_channel=rcs"
    upload = ("rcs.csv", b"template_name,template_type,text_message\noriginal,text,Original message.\n")
    initial = client.post("/api/preview?" + query, files={"file": upload})
    assert initial.status_code == 200, initial.text
    original = initial.json()[0]
    edits = {"template_overrides": json.dumps({original["source_ref"]: {
        "template_name": "reviewed_rcs", "text_message": "आपला अर्ज तयार आहे.",
        "suggestions": [{"suggestionType": "url_action", "text": "ऑफर पहा", "url": "https://example.com/offer/"}],
    }})}
    reviewed = client.post("/api/preview?" + query, files={"file": upload}, data=edits)
    assert reviewed.status_code == 200, reviewed.text
    preview = reviewed.json()[0]
    dispatched = []

    def runner(rows, log_path, *, task_ids, **kwargs):
        entries = []
        for row, task_id in zip(rows, task_ids, strict=True):
            dispatched.append(row)
            record_task_result(task_id, "submitted", "pending", "review-rcs")
            entries.append({**api.rcs_submission_payload(row), "status": "submitted", "approval_status": "pending", "error": None})
        return entries

    monkeypatch.setattr(api, "run_rcs", runner)
    submitted = client.post("/api/submit?" + query, files={"file": upload}, data=edits)
    assert submitted.status_code == 200, submitted.text
    assert len(dispatched) == 1
    assert dispatched[0].template_name == preview["template_name"] == "att_reviewed_rcs"
    assert dispatched[0].text_message == preview["text_message"] == "आपला अर्ज तयार आहे."
    assert dispatched[0].suggestions == preview["suggestions"]
    assert dispatched[0].suggestions[0]["url"] == "https://example.com/offer/{{1}}"
    assert dispatched[0].source_ref == original["source_ref"]
