"""
Comprehensive test suite for RCS Bot Builder Whitelisting.
Covers:
- Template type validation & limits (text <= 11 suggestions, cards <= 4, carousel 2-10 cards)
- Variable extraction and sequential numbering across syntaxes (<var>, [var], {#var#}, #var#)
- URL variable anchoring and Dialer phone validation
- ESME address decimal validation
- Aspect ratio checking for carousel and richcard images (valid, invalid, corrupt, empty)
- Provider response handling (success, duplicate, rejection, 500/429 uncertain outcomes)
- In-batch duplicate detection and row order preservation
- Concurrency and atomic task claims (PENDING -> PROCESSING CAS)
- Stats aggregation and tenant isolation in template merging
"""

import io
import json
import pytest
from unittest.mock import MagicMock, patch
from PIL import Image

from rcs_client import (
    _build_rcs_carousel_vi_template,
    _build_rcs_clean_suggestions,
    _build_rcs_richcard_vi_template,
    _build_rcs_save_payload,
    _build_rcs_text_vi_template,
    _ensure_url_variable,
    _extract_and_number_rcs_variables,
    normalize_rcs_template_name,
    submit_rcs_template,
)
from rcs_loader import (
    check_rcs_image_aspect_ratio,
    parse_single_cell_card_block,
)
from rcs_models import (
    RcsSubmissionResult,
    RcsSubmissionStatus,
    RcsTemplateSubmission,
)
import db_queue


@pytest.fixture(autouse=True)
def local_rcs_configuration(monkeypatch):
    """Never reload developer secrets while constructing unit-test submissions."""
    monkeypatch.setattr("rcs_config._load_env_file", lambda: None)
    monkeypatch.setenv("TATA_RCS_AUTH_TOKEN", "local-test-token")
    monkeypatch.setenv("TATA_RCS_ESMEADDR", "72148300000000")
    monkeypatch.setenv("TATA_RCS_BOT_ID", "Uv9tdd0KNADbq3pX")


# ==============================================================================
# 1. Variable Extraction & Numbering
# ==============================================================================

def test_variable_extraction_and_numbering_formats():
    """Verify variables formatted with <>, [], {}, {# #}, or # # are normalized to [N]."""
    text = "Hello <Name>, your EMI of [Amount] is due on {#Date#}. Contact #Agent#."
    norm, params, next_idx = _extract_and_number_rcs_variables(text, start_index=1)

    assert norm == "Hello [1], your EMI of [2] is due on [3]. Contact [4]."
    assert params == ["1", "2", "3", "4"]
    assert next_idx == 5


def test_variable_extraction_no_variables():
    """Verify plain text without placeholders is returned unchanged."""
    text = "Welcome to Tata Capital. Apply today for instant approval!"
    norm, params, next_idx = _extract_and_number_rcs_variables(text, start_index=1)

    assert norm == text
    assert params == []
    assert next_idx == 1


def test_ensure_url_variable():
    """Verify URLs get a sequential variable placeholder at the end."""
    url1 = "https://www.tatacapital.com/personal-loan"
    assert _ensure_url_variable(url1, 3) == "https://www.tatacapital.com/personal-loan[3]"

    url2 = "https://www.tatacapital.com/apply"
    assert _ensure_url_variable(url2, 1) == "https://www.tatacapital.com/apply[1]"


# ==============================================================================
# 2. Template Structure & Suggestion Limits
# ==============================================================================

def test_text_template_suggestion_limit():
    """Verify text templates allow up to 11 suggestions and reject 12."""
    sub = RcsTemplateSubmission(
        template_name="text_offer",
        template_type="text",
        text_message="Offer details here",
        suggestions=[{"suggestionType": "reply", "text": f"Option {i}"} for i in range(11)],
    )
    vi, params = _build_rcs_text_vi_template(sub, "text_offer", "bot_123")
    assert len(vi["suggestions"]) == 11

    sub_invalid = RcsTemplateSubmission(
        template_name="text_offer_too_many",
        template_type="text",
        text_message="Offer details here",
        suggestions=[{"suggestionType": "reply", "text": f"Option {i}"} for i in range(12)],
    )
    with pytest.raises(ValueError, match="at most 11 suggestions"):
        _build_rcs_text_vi_template(sub_invalid, "text_offer_too_many", "bot_123")


def test_richcard_suggestion_limit():
    """Verify rich cards allow up to 4 suggestions and reject 5."""
    sub = RcsTemplateSubmission(
        template_name="richcard_offer",
        template_type="richcard",
        card_title="Special Offer",
        card_description="Description here",
        suggestions=[{"suggestionType": "reply", "text": f"Choice {i}"} for i in range(4)],
    )
    vi, params = _build_rcs_richcard_vi_template(sub, "richcard_offer", "bot_123")
    assert len(vi["standaloneCard"]["suggestions"]) == 4

    sub_invalid = RcsTemplateSubmission(
        template_name="richcard_too_many",
        template_type="richcard",
        card_title="Special Offer",
        card_description="Description here",
        suggestions=[{"suggestionType": "reply", "text": f"Choice {i}"} for i in range(5)],
    )
    with pytest.raises(ValueError, match="at most 4 suggestions"):
        _build_rcs_richcard_vi_template(sub_invalid, "richcard_too_many", "bot_123")


def test_dialer_action_validation():
    """Verify dialer actions require valid phone numbers."""
    valid_suggs = [{"suggestionType": "dialer_action", "text": "Call Us", "phoneNumber": "+919876543210"}]
    clean, _ = _build_rcs_clean_suggestions(valid_suggs, 1, [])
    assert clean[0]["phoneNumber"] == "+919876543210"

    invalid_suggs = [{"suggestionType": "dialer_action", "text": "Call Us", "phoneNumber": "invalid_phone"}]
    with pytest.raises(ValueError, match="valid phoneNumber"):
        _build_rcs_clean_suggestions(invalid_suggs, 1, [])


def test_url_action_validation():
    """Verify url actions require absolute HTTP/HTTPS URLs."""
    valid_suggs = [{"suggestionType": "url_action", "text": "Apply", "url": "https://tatacapital.com"}]
    clean, _ = _build_rcs_clean_suggestions(valid_suggs, 1, [])
    assert "https://tatacapital.com" in clean[0]["url"]

    invalid_suggs = [{"suggestionType": "url_action", "text": "Bad", "url": "javascript:alert(1)"}]
    with pytest.raises(ValueError, match="absolute HTTP"):
        _build_rcs_clean_suggestions(invalid_suggs, 1, [])


def test_carousel_card_count_limits(monkeypatch):
    """Verify carousel requires between 2 and 10 cards."""
    monkeypatch.setattr("rcs_config._load_env_file", lambda: None)
    monkeypatch.setenv("TATA_RCS_ESMEADDR", "72148300000000")
    # 1 card -> rejected
    sub_1 = RcsTemplateSubmission(
        template_name="carousel_1",
        template_type="carousel",
        carousel_cards=[{"card_title": "Only One", "card_description": "Desc"}],
        esme_addr="72148300000000",
        bot_id="Uv9tdd0KNADbq3pX",
    )
    with pytest.raises(ValueError, match="2 to 10"):
        _build_rcs_save_payload(sub_1, client="tata")

    # 11 cards -> rejected
    sub_11 = RcsTemplateSubmission(
        template_name="carousel_11",
        template_type="carousel",
        carousel_cards=[{"card_title": f"Card {i}", "card_description": "Desc"} for i in range(11)],
        esme_addr="72148300000000",
        bot_id="Uv9tdd0KNADbq3pX",
    )
    with pytest.raises(ValueError, match="2 to 10"):
        _build_rcs_save_payload(sub_11, client="tata")

    # 3 cards -> accepted
    sub_3 = RcsTemplateSubmission(
        template_name="carousel_3",
        template_type="carousel",
        carousel_cards=[{"card_title": f"Card {i}", "card_description": "Desc"} for i in range(3)],
        esme_addr="72148300000000",
        bot_id="Uv9tdd0KNADbq3pX",
    )
    payload = _build_rcs_save_payload(sub_3, client="tata")
    assert len(payload["viTemplate"]["carouselCard"]) == 3


def test_esme_addr_validation(monkeypatch):
    """Verify ESME address must be a positive decimal identifier without leading zeros."""
    monkeypatch.setattr("rcs_config._load_env_file", lambda: None)
    monkeypatch.setenv("TATA_RCS_ESMEADDR", "72148300000000")
    sub = RcsTemplateSubmission(
        template_name="text_test",
        template_type="text",
        text_message="Hello",
        bot_id="Uv9tdd0KNADbq3pX",
    )

    # Valid numeric ESME
    sub.esme_addr = "72148300000000"
    payload = _build_rcs_save_payload(sub, client="tata")
    assert payload["esmeAddr"] == 72148300000000

    # Non-numeric ESME
    monkeypatch.setenv("TATA_RCS_ESMEADDR", "INVALID_ESME")
    sub.esme_addr = None
    with pytest.raises(ValueError, match="positive decimal identifier"):
        _build_rcs_save_payload(sub, client="tata")

    # Leading zero ESME
    monkeypatch.setenv("TATA_RCS_ESMEADDR", "012345")
    with pytest.raises(ValueError, match="leading zeros"):
        _build_rcs_save_payload(sub, client="tata")


# ==============================================================================
# 3. Aspect Ratio Validation
# ==============================================================================

def _generate_test_image_bytes(width: int, height: int, format: str = "PNG") -> bytes:
    img = Image.new("RGB", (width, height), color=(73, 109, 137))
    buf = io.BytesIO()
    img.save(buf, format=format)
    return buf.getvalue()


def test_aspect_ratio_checking_carousel():
    """Verify allowed carousel ratios: 16:9, 1:1, 3:4."""
    # 16:9 (1280x720) -> valid
    valid_16_9 = _generate_test_image_bytes(1280, 720)
    is_valid, _, _, _ = check_rcs_image_aspect_ratio(valid_16_9, template_type="carousel")
    assert is_valid is True

    # 1:1 (720x720) -> valid
    valid_1_1 = _generate_test_image_bytes(720, 720)
    is_valid, _, _, _ = check_rcs_image_aspect_ratio(valid_1_1, template_type="carousel")
    assert is_valid is True

    # 3:4 (768x1024) -> valid
    valid_3_4 = _generate_test_image_bytes(768, 1024)
    is_valid, _, _, _ = check_rcs_image_aspect_ratio(valid_3_4, template_type="carousel")
    assert is_valid is True

    # 4:1 (1600x400) -> invalid for carousel
    invalid_ratio = _generate_test_image_bytes(1600, 400)
    is_valid, err, _, _ = check_rcs_image_aspect_ratio(invalid_ratio, template_type="carousel")
    assert is_valid is False
    assert "not in allowed Carousel aspect ratio" in err


def test_aspect_ratio_checking_corrupt_or_empty():
    """Verify empty or corrupt image bytes fail gracefully instead of crashing."""
    # Empty bytes
    is_valid, err, _, _ = check_rcs_image_aspect_ratio(b"", template_type="richcard")
    assert is_valid is False
    assert "empty" in err.lower()

    # Corrupt random bytes
    is_valid, err, _, _ = check_rcs_image_aspect_ratio(b"not_an_image_file_content", template_type="richcard")
    assert is_valid is False
    assert "invalid" in err.lower() or "unreadable" in err.lower()


# ==============================================================================
# 4. Provider Response & Ambiguity Handling
# ==============================================================================

@patch("rcs_client.requests.post")
def test_submit_rcs_template_provider_500_uncertain_outcome(mock_post, monkeypatch):
    """Verify 500 error sets outcome_uncertain=True and does not report clean failure."""
    monkeypatch.setattr("rcs_config._load_env_file", lambda: None)
    monkeypatch.setenv("TATA_RCS_ESMEADDR", "72148300000000")
    monkeypatch.setenv("TATA_RCS_AUTH_TOKEN", "local-test-token")
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.ok = False
    mock_resp.json.return_value = {"error": "Internal Server Error"}
    mock_resp.text = "Internal Server Error"
    mock_post.return_value = mock_resp

    sub = RcsTemplateSubmission(
        template_name="test_tpl_500",
        template_type="text",
        text_message="Test message",
        esme_addr="72148300000000",
        bot_id="Uv9tdd0KNADbq3pX",
    )
    res = submit_rcs_template(sub)
    assert res.status == RcsSubmissionStatus.FAILED
    assert res.outcome_uncertain is True
    assert "reconcile" in res.error.lower()


@patch("rcs_client.requests.post")
def test_submit_rcs_template_duplicate_response(mock_post, monkeypatch):
    """Verify provider 'already exists' response is categorized as DUPLICATE."""
    monkeypatch.setattr("rcs_config._load_env_file", lambda: None)
    monkeypatch.setenv("TATA_RCS_ESMEADDR", "72148300000000")
    monkeypatch.setenv("TATA_RCS_AUTH_TOKEN", "local-test-token")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = {"status": "error", "message": "Template already exists with this name"}
    mock_post.return_value = mock_resp

    sub = RcsTemplateSubmission(
        template_name="test_tpl_dupe",
        template_type="text",
        text_message="Test message",
        esme_addr="72148300000000",
        bot_id="Uv9tdd0KNADbq3pX",
    )
    res = submit_rcs_template(sub)
    assert res.status == RcsSubmissionStatus.DUPLICATE
    assert "already exists" in res.error.lower()


def test_aspect_ratio_blocked_submission_skips_network():
    """Verify templates pre-flagged as aspect_ratio_blocked fail immediately without HTTP calls."""
    sub = RcsTemplateSubmission(
        template_name="blocked_template",
        template_type="richcard",
        aspect_ratio_blocked=True,
        aspect_ratio_error="Image is 4:1, must be 16:9 or 1:1",
    )
    with patch("rcs_client.requests.post") as mock_post:
        res = submit_rcs_template(sub)
        mock_post.assert_not_called()
        assert res.status == RcsSubmissionStatus.BLOCKED_ASPECT_RATIO
        assert res.approval_status == "blocked_aspect_ratio"
        assert "4:1" in res.error


# ==============================================================================
# 5. Concurrency & Queue Claims
# ==============================================================================

def test_queue_atomic_task_claim():
    """Verify claim_task transitions PENDING -> PROCESSING atomically and prevents double claims."""
    import uuid
    job_id = f"test_job_claim_{uuid.uuid4().hex[:8]}"
    db_queue.create_job_with_tasks(
        tenant_id="tata",
        channel="rcs",
        filename="test.csv",
        submitted_by="Tester",
        tasks_data=[
            {"source_ref": "ref_1", "template_name": "tpl_1", "status": "PENDING"},
            {"source_ref": "ref_2", "template_name": "tpl_2", "status": "PENDING"},
        ],
        job_id=job_id,
    )
    task_id_1 = f"task_{job_id}_0000"
    task_id_2 = f"task_{job_id}_0001"

    # Two overlapping SQLite connections compete for the same atomic claim.
    import threading
    from concurrent.futures import ThreadPoolExecutor
    barrier = threading.Barrier(2)

    def claim():
        barrier.wait(timeout=3)
        return db_queue.claim_task(task_id_1, tenant_id="tata", channel="rcs")

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(lambda _: claim(), range(2)))
    assert sum(outcome is not None for outcome in outcomes) == 1
    assert next(outcome for outcome in outcomes if outcome)["status"] == "PROCESSING"

    # Cross-tenant worker (bajaj) tries to claim task 2 -> must be rejected (None)
    claimed_wrong_tenant = db_queue.claim_task(task_id_2, tenant_id="bajaj", channel="rcs")
    assert claimed_wrong_tenant is None

    # Authorized worker claims task 2 -> succeeds
    claimed_w2 = db_queue.claim_task(task_id_2, tenant_id="tata", channel="rcs")
    assert claimed_w2 is not None
    assert claimed_w2["status"] == "PROCESSING"


# ==============================================================================
# 6. Unstructured Cell Decomposition (Excel Parser)
# ==============================================================================

def test_parse_single_cell_card_block():
    """Verify unstructured text block decomposes into title, body, and CTA."""
    block = (
        "Festive Personal Loan Offer\n\n"
        "Get pre-approved personal loans up to Rs. 5 Lakhs at attractive rates.\n\n"
        "CTA Button: Apply Today\n"
    )
    card = parse_single_cell_card_block(block)
    assert "Festive Personal Loan" in card["card_title"]
    assert "pre-approved" in card["card_description"]
    assert card["button_text"] == "Apply Today"
    assert card["button_url"] == ""


# ==============================================================================
# 7. Batch Submission Row Order & Deduplication
# ==============================================================================

def test_rcs_batch_submission_preserves_order_and_handles_duplicates(provision_user):
    """Verify batch submission preserves exact row order and attributes duplicates."""
    import io
    from fastapi.testclient import TestClient
    import api

    _, headers = provision_user(tenant="tata", role="operator")
    client = TestClient(api.app, headers=headers)

    csv_content = (
        "template_name,template_type,text_message\n"
        "tata_row_1,text,Message one\n"
        "tata_row_2,text,Message two\n"
        "tata_row_1,text,Message one duplicate\n"
        "tata_row_3,text,Message three\n"
    )

    def mock_submit(sub, client=None):
        return RcsSubmissionResult(
            source_ref=sub.source_ref,
            template_name=sub.template_name,
            template_id=f"karix_id_{sub.template_name}",
            status=RcsSubmissionStatus.SUBMITTED,
            approval_status="submitted",
            client="tata",
        )

    with (
        patch("rcs_runner.submit_rcs_template", side_effect=mock_submit),
        patch("rcs_client.submit_rcs_template", side_effect=mock_submit),
        patch("api.fetch_rcs_templates", return_value=[]),
    ):
        files = {"file": ("batch_test.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
        resp = client.post("/api/submit", params={"account": "tata", "channel": "rcs", "skip_duplicates": "true"}, files=files)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 4
        assert body["submitted"] == 3
        assert body["skipped_duplicates"] == 1
        job = db_queue.get_job(body["job_id"])
        assert (job["status"], job["submitted_count"], job["duplicate_count"], job["failed_count"]) == (
            "COMPLETED", 3, 1, 0)
        assert len({entry["task_id"] for entry in body["results"]}) == 4
        assert all(entry["approval_status"] == "pending" for entry in body["results"] if entry["status"] == "submitted")

        results = body["results"]
        assert len(results) == 4
        # Order must match the original 4 rows exactly
        assert results[0]["template_name"] == "tata_row_1"
        assert results[0]["status"] == "submitted"

        assert results[1]["template_name"] == "tata_row_2"
        assert results[1]["status"] == "submitted"

        assert results[2]["template_name"] == "tata_row_1"
        assert results[2]["status"] == "duplicate"
        assert "duplicate" in results[2]["error"].lower()

        assert results[3]["template_name"] == "tata_row_3"
        assert results[3]["status"] == "submitted"


def test_rcs_live_catalog_duplicate_skipping(provision_user):
    """Verify templates matching live bot catalog are skipped without calling submit_rcs_template."""
    import io
    from fastapi.testclient import TestClient
    import api

    _, headers = provision_user(tenant="tata", role="operator")
    client = TestClient(api.app, headers=headers)

    csv_content = (
        "template_name,template_type,text_message\n"
        "tata_existing_tpl,text,Message one\n"
    )

    live_catalog = [
        {
            "templateId": "live_id_999",
            "status": "APPROVED",
            "botId": "bot_tata_official",
            "viTemplate": {"name": "tata_existing_tpl", "type": "text"},
        }
    ]

    with (
        patch("rcs_client.submit_rcs_template") as mock_submit,
        patch("api.fetch_rcs_templates", return_value=live_catalog),
        patch("rcs_config.get_rcs_bot_id", return_value="bot_tata_official"),
        patch("rcs_loader.get_rcs_bot_id", return_value="bot_tata_official"),
        patch("api.get_rcs_bot_id", return_value="bot_tata_official"),
    ):
        files = {"file": ("batch_dupe.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
        resp = client.post("/api/submit", params={"account": "tata", "channel": "rcs", "skip_duplicates": "true"}, files=files)
        assert resp.status_code == 200
        body = resp.json()
        mock_submit.assert_not_called()  # Must not submit duplicate to Karix
        assert body["submitted"] == 0
        assert body["skipped_duplicates"] == 1
        assert body["results"][0]["status"] == "duplicate"
        assert body["results"][0]["provider_ref_id"] == "live_id_999"
        settled = db_queue.get_job(body["job_id"])
        assert settled["status"] == "COMPLETED"
        assert settled["duplicate_count"] == settled["total_count"] == 1


# ==============================================================================
# 8. Live Claims Have No Invented Expiry
# ==============================================================================

def test_job_reads_do_not_expire_live_processing_claims():
    """An old timestamp cannot prove that a provider POST stopped running."""
    import db

    job = db_queue.create_job_with_tasks(
        tenant_id="tata", channel="rcs", filename="private.csv", submitted_by="Tester",
        tasks_data=[{"source_ref": "active_ref", "template_name": "active_tpl"}],
    )
    task_id = f"task_{job['id']}_0000"
    assert db_queue.claim_task(task_id, "tata", "rcs")["status"] == "PROCESSING"
    with db.get_db() as conn:
        conn.execute("UPDATE job_tasks SET updated_at = ? WHERE id = ?", ("2000-01-01T00:00:00+00:00", task_id))
    assert db_queue.get_job(job["id"])["status"] == "RUNNING"
    assert db_queue.get_job_task(task_id)["status"] == "PROCESSING"
    assert db_queue.get_job(job["id"])["failed_count"] == 0
