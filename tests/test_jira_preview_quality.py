"""Consumer-visible Jira warning parity and creative authorization regressions."""

from dataclasses import asdict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import api
from briefing_parser import ParsedJiraBrief, WhatsAppTemplateDraft


@pytest.fixture
def preview_case(tmp_path, monkeypatch, provision_user):
    import jira_client

    cache = tmp_path / "media_cache"
    cache.mkdir()
    monkeypatch.setattr(jira_client, "MEDIA_CACHE_DIR", cache)
    creative = cache / "portrait.png"
    Image.new("RGB", (400, 800), "navy").save(creative)
    draft = asdict(WhatsAppTemplateDraft(
        template_name="jira_sparse_portrait",
        category="MARKETING",
        body="Hi {{1}} {{2}}",
        header_type="IMAGE",
        media_file=str(creative),
        media_filename=creative.name,
        button_type="URL",
        button_text="This button label is much too long",
        button_url="https://example.com/offer",
    ))
    brief = ParsedJiraBrief(
        issue_key="TCN-999", summary="WhatsApp campaign", account="tcl_promo",
        status="Open", assignee="Operator", reporter="Requester", duedate=None,
        whatsapp_templates=[draft],
    )
    _, headers = provision_user("tata")
    return TestClient(api.app, headers=headers), brief, creative, headers


def test_jira_brief_exposes_sparse_copy_warnings_without_dimension_blocking(preview_case):
    client, brief, _, _ = preview_case
    with (
        patch("jira_client.fetch_jira_issue", return_value={"key": brief.issue_key}),
        patch("briefing_parser.parse_jira_brief", return_value=brief),
        patch("submission_client.fetch_template_list", return_value=([], None)),
    ):
        response = client.get(f"/api/jira/brief/{brief.issue_key}")
    assert response.status_code == 200, response.text
    draft = response.json()["brief"]["whatsapp_templates"][0]
    warning_types = {warning["type"] for warning in draft.get("compliance_warnings", [])}
    assert "META_WORD_RATIO" in warning_types
    assert "BUTTON_LENGTH_LIMIT" in warning_types
    assert draft["aspect_ratio_blocked"] is False
    assert draft["aspect_ratio_warnings"] == []


def test_jira_edited_preview_rechecks_replacement_image_and_copy(preview_case):
    client, brief, creative, _ = preview_case
    draft = brief.whatsapp_templates[0]
    payload = {"account": "tcl_promo",
               "whatsapp_templates": [draft], "rcs_templates": []}
    with patch("submission_client.fetch_template_list", return_value=([], None)):
        initial = client.post("/api/jira/preview", json=payload)
        assert initial.status_code == 200, initial.text
        assert initial.json()["whatsapp_templates"][0]["aspect_ratio_blocked"] is False
        Image.new("RGB", (1280, 720), "navy").save(creative)
        draft["body"] = "Dear {{1}}, your loan application {{2}} is ready for review today."
        draft["button_text"] = "Review offer"
        fixed = client.post("/api/jira/preview", json=payload)
    assert fixed.status_code == 200, fixed.text
    updated = fixed.json()["whatsapp_templates"][0]
    assert updated["aspect_ratio_blocked"] is False
    assert not any(w["severity"] == "error" for w in updated["compliance_warnings"])


def test_jira_creatives_require_header_auth_and_preserve_original_image(preview_case):
    client, _, creative, headers = preview_case
    params = {"path": str(creative), "inline": "true"}
    response = client.get("/api/jira/creative/download", params=params)
    assert response.status_code == 200
    assert response.content == creative.read_bytes()
    assert response.headers["content-type"].startswith("image/png")
    unauthenticated = TestClient(api.app)
    query_only = unauthenticated.get("/api/jira/creative/download", params={
        **params, "token": headers["Authorization"].removeprefix("Bearer "),
    })
    assert query_only.status_code == 401


@pytest.mark.parametrize("dimensions,blocked", [((400, 800), True), ((1280, 720), False)])
def test_jira_rcs_preview_reports_actual_standalone_image_ratio(preview_case, dimensions, blocked):
    from briefing_parser import RcsTemplateDraft

    client, _, creative, _ = preview_case
    Image.new("RGB", dimensions, "navy").save(creative)
    rcs = asdict(RcsTemplateDraft(
        template_name="jira_rcs_ratio", card_title="Your loan offer",
        body="Hi [1]", media_file=str(creative), media_filename=creative.name,
    ))
    with patch("api._fetch_rcs_inventory", return_value=[]):
        response = client.post("/api/jira/preview", json={
            "account": "tcl_promo", "whatsapp_templates": [], "rcs_templates": [rcs],
        })
    assert response.status_code == 200, response.text
    preview = response.json()["rcs_templates"][0]
    assert preview["aspect_ratio_blocked"] is blocked
    assert not any(w["type"] == "META_WORD_RATIO" for w in preview["compliance_warnings"])


def test_jira_carousel_preview_checks_every_card(preview_case):
    from briefing_parser import RcsTemplateDraft

    client, _, creative, _ = preview_case
    valid = creative.with_name("landscape.png")
    Image.new("RGB", (1280, 720), "teal").save(valid)
    rcs = asdict(RcsTemplateDraft(
        template_name="jira_carousel_ratio", card_title="Your offers", body="Review your offers.",
        template_type="carousel",
        carousel_cards=[
            {"card_title": "First offer", "card_description": "Valid image", "media_url": str(valid)},
            {"card_title": "Second offer", "card_description": "Invalid image", "media_url": str(creative)},
        ],
    ))
    with patch("api._fetch_rcs_inventory", return_value=[]):
        response = client.post("/api/jira/preview", json={
            "account": "tcl_promo", "whatsapp_templates": [], "rcs_templates": [rcs],
        })
    assert response.status_code == 200, response.text
    preview = response.json()["rcs_templates"][0]
    assert preview["aspect_ratio_blocked"] is True
    assert any(w["component"] == "Card 2 Image" and w["blocked"] for w in preview["aspect_ratio_warnings"])


@pytest.mark.parametrize("missing", [False, True])
def test_jira_unreadable_creatives_are_not_reported_as_valid(preview_case, missing):
    client, brief, creative, _ = preview_case
    if missing:
        creative.unlink()
    else:
        creative.write_bytes(b"not an image")
    with patch("submission_client.fetch_template_list", return_value=([], None)):
        response = client.post("/api/jira/preview", json={
            "account": "tcl_promo", "whatsapp_templates": brief.whatsapp_templates, "rcs_templates": [],
        })
    assert response.status_code == 200, response.text
    preview = response.json()["whatsapp_templates"][0]
    assert preview["aspect_ratio_blocked"] is True
    assert preview["aspect_ratio_block_reason"]


def test_jira_submission_rechecks_media_and_preserves_valid_siblings(preview_case):
    from models import SubmissionResult, SubmissionStatus

    client, brief, creative, _ = preview_case
    creative.write_bytes(b"not an image")
    blocked = {**brief.whatsapp_templates[0], "aspect_ratio_blocked": False, "aspect_ratio_warnings": []}
    valid = {**blocked, "template_name": "valid_text_sibling", "header_type": "NONE", "media_file": None,
             "body": "Your loan application is ready for review today.", "variables": [], "button_type": "NONE"}
    submitted_names = []

    def submit(submission, client):
        submitted_names.append(submission.template_name)
        return SubmissionResult(
            source_ref=submission.source_ref, template_name=submission.template_name,
            status=SubmissionStatus.SUBMITTED, provider_ref_id="confirmed-local-reference", client=client,
        )

    with (
        patch("jira_client.fetch_jira_issue", return_value={"key": brief.issue_key}),
        patch("briefing_parser.parse_jira_brief", return_value=brief),
        patch("config.get_waba_id", return_value="local-test-waba"),
        patch("submission_client.fetch_template_list", return_value=([], None)),
        patch("submission_client.submit_template", side_effect=submit),
        patch("tracker.log_result"),
    ):
        response = client.post(f"/api/jira/submit/{brief.issue_key}", json={
            "account": "tcl_promo", "channels": ["whatsapp"], "whatsapp_templates": [blocked, valid],
        })
    assert response.status_code == 200, response.text
    results = {row["template_name"]: row for row in response.json()["whatsapp_submitted"]}
    assert results[blocked["template_name"]]["status"] in {"blocked", "blocked_aspect_ratio"}
    assert results[valid["template_name"]]["status"] == "submitted"
    assert submitted_names == ["valid_text_sibling"]


@pytest.mark.parametrize("placeholder", [False, True])
def test_jira_submission_accepts_portrait_or_placeholder_despite_stale_ratio_flag(preview_case, placeholder):
    from models import SubmissionResult, SubmissionStatus

    client, brief, _, _ = preview_case
    draft = {
        **brief.whatsapp_templates[0], "aspect_ratio_blocked": True,
        "aspect_ratio_error": "Old dimension restriction",
        "body": "Your loan application is ready for review today.", "variables": [],
        "button_type": "NONE",
    }
    if placeholder:
        draft.update(media_file=None, media_filename=None)
    submitted = []

    def submit(submission, client):
        submitted.append(submission)
        return SubmissionResult(
            source_ref=submission.source_ref, template_name=submission.template_name,
            status=SubmissionStatus.SUBMITTED, provider_ref_id="real-created-id", client=client,
        )

    with (
        patch("jira_client.fetch_jira_issue", return_value={"key": brief.issue_key}),
        patch("briefing_parser.parse_jira_brief", return_value=brief),
        patch("config.get_waba_id", return_value="local-test-waba"),
        patch("submission_client.fetch_template_list", return_value=([], None)),
        patch("submission_client.submit_template", side_effect=submit),
        patch("tracker.log_result"),
    ):
        preview = client.post("/api/jira/preview", json={
            "account": "tcl_promo", "whatsapp_templates": [draft], "rcs_templates": [],
        })
        response = client.post(f"/api/jira/submit/{brief.issue_key}", json={
            "account": "tcl_promo", "channels": ["whatsapp"], "whatsapp_templates": [draft],
        })
    assert preview.status_code == 200, preview.text
    assert preview.json()["whatsapp_templates"][0]["aspect_ratio_blocked"] is False
    assert response.status_code == 200, response.text
    assert response.json()["whatsapp_submitted"][0]["status"] == "submitted"
    assert len(submitted) == 1
    header = next(component for component in submitted[0].components if component.type == "HEADER")
    assert bool(header.image_bytes) is not placeholder


def test_jira_preview_rejects_another_tenant_account(preview_case):
    client, brief, _, _ = preview_case
    response = client.post("/api/jira/preview", json={
        "account": "bajaj", "whatsapp_templates": brief.whatsapp_templates, "rcs_templates": [],
    })
    assert response.status_code == 403


def test_jira_validation_comment_requires_review_and_explicit_confirmation(preview_case):
    client, brief, _, _ = preview_case
    payload = {"account": "tcl_promo", "whatsapp_templates": brief.whatsapp_templates, "rcs_templates": []}
    writes = []

    def post_comment(issue_key, text):
        writes.append((issue_key, text))
        return {"ok": True, "comment_id": "confirmed-comment"}

    with (
        patch("jira_client.fetch_jira_issue", return_value={"key": brief.issue_key}),
        patch("jira_client.add_jira_comment", side_effect=post_comment),
        patch("submission_client.fetch_template_list", return_value=([], None)),
    ):
        preview = client.post(f"/api/jira/validation-comment/{brief.issue_key}", json=payload)
        assert preview.status_code == 200, preview.text
        review = preview.json()
        assert review["posted"] is False
        assert brief.whatsapp_templates[0]["template_name"] in review["comment_text"]
        assert writes == []
        declined = client.post(f"/api/jira/validation-comment/{brief.issue_key}", json={**payload, "confirmed": False})
        assert declined.status_code == 200
        assert writes == []
        missing_review = client.post(f"/api/jira/validation-comment/{brief.issue_key}", json={**payload, "confirmed": True})
        assert missing_review.status_code in {400, 409}
        assert writes == []
        approved = client.post(f"/api/jira/validation-comment/{brief.issue_key}", json={
            **payload, "confirmed": True, "expected_comment": review["comment_text"],
        })
    assert approved.status_code == 200, approved.text
    assert approved.json()["posted"] is True
    assert approved.json()["comment_id"] == "confirmed-comment"
    assert writes == [(brief.issue_key, review["comment_text"])]


def test_jira_validation_comment_rejects_changed_errors(preview_case):
    client, brief, _, _ = preview_case
    payload = {"account": "tcl_promo", "whatsapp_templates": brief.whatsapp_templates, "rcs_templates": []}
    with (
        patch("jira_client.fetch_jira_issue", return_value={"key": brief.issue_key}),
        patch("jira_client.add_jira_comment") as writer,
        patch("submission_client.fetch_template_list", return_value=([], None)),
    ):
        review = client.post(f"/api/jira/validation-comment/{brief.issue_key}", json=payload)
        assert review.status_code == 200, review.text
        brief.whatsapp_templates[0]["body"] = "Dear {{1}}, your application {{2}} is ready for review today."
        response = client.post(f"/api/jira/validation-comment/{brief.issue_key}", json={
            **payload, "confirmed": True, "expected_comment": review.json()["comment_text"],
        })
    assert response.status_code == 409
    writer.assert_not_called()


def test_jira_validation_comment_rejects_other_tenants_and_clean_drafts(preview_case):
    client, brief, creative, _ = preview_case
    payload = {"account": "bajaj", "whatsapp_templates": brief.whatsapp_templates, "rcs_templates": []}
    with patch("jira_client.add_jira_comment") as writer:
        denied = client.post(f"/api/jira/validation-comment/{brief.issue_key}", json=payload)
        assert denied.status_code == 403
        Image.new("RGB", (1280, 720), "teal").save(creative)
        brief.whatsapp_templates[0].update(body="Your loan application is ready for review today.", button_text="Review offer")
        clean = client.post(f"/api/jira/validation-comment/{brief.issue_key}", json={**payload, "account": "tcl_promo"})
    assert clean.status_code == 400
    writer.assert_not_called()


def test_jira_validation_comment_does_not_claim_success_after_provider_failure(preview_case):
    client, brief, _, _ = preview_case
    payload = {"account": "tcl_promo", "whatsapp_templates": brief.whatsapp_templates, "rcs_templates": []}
    with (
        patch("jira_client.fetch_jira_issue", return_value={"key": brief.issue_key}),
        patch("jira_client.add_jira_comment", return_value={"ok": False, "error": "Jira refused the comment"}) as writer,
        patch("submission_client.fetch_template_list", return_value=([], None)),
    ):
        review = client.post(f"/api/jira/validation-comment/{brief.issue_key}", json=payload)
        assert review.status_code == 200, review.text
        failed = client.post(f"/api/jira/validation-comment/{brief.issue_key}", json={
            **payload, "confirmed": True, "expected_comment": review.json()["comment_text"],
        })
    assert failed.status_code == 502
    assert writer.call_count == 1


def test_jira_brief_loads_catalogs_concurrently_and_preserves_cached_copy(preview_case):
    import threading
    from briefing_parser import RcsTemplateDraft

    client, brief, creative, _ = preview_case
    brief.rcs_templates = [asdict(RcsTemplateDraft(
        template_name="jira_rcs_cached", card_title="Your offer", body="Review your loan offer.",
        media_file=str(creative), media_filename=creative.name,
    ))]
    rcs_started = threading.Event()
    simultaneous = []

    def wa_inventory(client):
        simultaneous.append(rcs_started.wait(2))
        return [], "Provider inventory unavailable"

    def rcs_inventory(client):
        rcs_started.set()
        return []

    with (
        patch("api._PARSED_BRIEF_CACHE", {}),
        patch("jira_client.fetch_jira_issue", return_value={"key": brief.issue_key, "updated": "cache-test-revision"}),
        patch("briefing_parser.parse_jira_brief", return_value=brief) as parser,
        patch("submission_client.fetch_template_list", side_effect=wa_inventory),
        patch("api._fetch_rcs_inventory", side_effect=rcs_inventory),
    ):
        first = client.get(f"/api/jira/brief/{brief.issue_key}")
        rcs_started.clear()
        second = client.get(f"/api/jira/brief/{brief.issue_key}")
    assert simultaneous == [True, True]
    assert parser.call_count == 1
    assert first.status_code == second.status_code == 200
    for response in (first, second):
        loaded = response.json()["brief"]
        assert loaded["whatsapp_templates"][0]["body"] == brief.whatsapp_templates[0]["body"]
        assert loaded["rcs_templates"][0]["body"] == "Review your loan offer."
        assert loaded["whatsapp_templates"][0]["aspect_ratio_blocked"] is False
        assert loaded["rcs_templates"][0]["aspect_ratio_blocked"] is True
        assert any(
            warning["type"] == "LIVE_INVENTORY_UNAVAILABLE"
            for warning in loaded["whatsapp_templates"][0]["compliance_warnings"]
        )
    assert "compliance_warnings" not in brief.whatsapp_templates[0]


def test_jira_rcs_preview_revalidates_edited_name_with_shared_karix_validator(preview_case):
    from briefing_parser import RcsTemplateDraft

    client, _, _, _ = preview_case
    draft = asdict(RcsTemplateDraft(
        template_name="x" * 26, card_title="", body="Your loan application is ready.",
        template_type="text",
    ))
    with patch("api._fetch_rcs_inventory", return_value=[]):
        initial = client.post("/api/jira/preview", json={
            "account": "tcl_promo", "whatsapp_templates": [], "rcs_templates": [draft],
        })
        assert initial.status_code == 200
        initial_draft = initial.json()["rcs_templates"][0]
        assert any(w["component"] == "Template name" for w in initial_draft["compliance_warnings"])
        initial_draft["template_name"] = "t551_01_13oct26"
        corrected = client.post("/api/jira/preview", json={
            "account": "tcl_promo", "whatsapp_templates": [], "rcs_templates": [initial_draft],
        })
    assert corrected.status_code == 200
    assert not any(w["severity"] == "error" for w in corrected.json()["rcs_templates"][0]["compliance_warnings"])


def test_jira_attachment_download_failure_is_explicit_not_a_blank_brief(preview_case):
    client, _, _, _ = preview_case
    with (
        patch("jira_client.fetch_jira_issue", return_value={
            "key": "TCN-557", "summary": "PQPL Bulls Eye", "description_text": "",
            "attachments": [{"id": "38175", "filename": "PL Bulls Eye.xlsx"}],
        }),
        patch("briefing_parser.download_jira_attachment", side_effect=TimeoutError("download timed out")),
        patch("submission_client.fetch_template_list") as inventory,
    ):
        response = client.get("/api/jira/brief/TCN-557")
    assert response.status_code == 500
    assert "38175" in response.json()["detail"]
    assert "download timed out" in response.json()["detail"]
    inventory.assert_not_called()
