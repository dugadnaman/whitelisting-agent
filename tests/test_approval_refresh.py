"""Automatic reconciliation reads once per scope and only updates matching durable approvals."""
import asyncio

import pytest

import api
import db_queue
import email_notifier
import sms_dlt
import submission_client
import rcs_client
import vilpower_client


def seed(account, channel, name, *, approval="pending", ref="provider-1", status="SUBMITTED", **fields):
    row = {"template_name": name, "source_ref": f"source:{name}", "client": account, "channel": channel,
           "status": status, "approval_status": approval, "provider_ref_id": ref, **fields}
    job = db_queue.create_job_with_tasks(account, channel, "source.xlsx", "Tester", [row])
    return db_queue.get_job_tasks(job["id"])[0]["id"]


def task(task_id):
    return db_queue.get_job_task(task_id)


def no_registration(*args, **kwargs):
    pytest.fail("Approval refresh must never register or resubmit")


def test_scheduler_refreshes_pending_wa_rcs_sms_without_registration(monkeypatch):
    wa = seed("tcl_promo", "whatsapp", "wa_offer")
    rcs = seed("tcl_promo", "rcs", "rcs_offer", bot_id="bot-one")
    sms = seed("tata", "sms", "sms_offer", ref="sms-id", text="Exact SMS copy", header="TATAXX")
    mismatch = seed("tcl_promo", "rcs", "not_the_same_template", ref="other-id", bot_id="bot-one")
    calls = []

    def wa_inventory(account):
        calls.append((account, "whatsapp"))
        return [{"template_name": "wa_offer", "fb_template_id": "provider-1", "template_create_status": "APPROVED"}], None

    def rcs_inventory(account, *, bot_id=None):
        calls.append((account, "rcs", bot_id))
        return [{"templateId": "provider-1", "botId": "bot-one", "status": "rejected", "reason": "Correct your title",
                 "viTemplate": {"name": "rcs_offer"}},
                {"templateId": "other-id", "botId": "another-bot", "status": "approved"}]

    def sms_inventory(account, search="", from_date=None):
        calls.append((account, "sms"))
        return [{"template_name": "sms_offer", "template_id": "sms-id", "template_message": "Exact SMS copy",
                 "header": "TATAXX", "status": "approved", "entity_id": vilpower_client.TATA_ENTITY_ID,
                 "provider": "vilpower", "approval_reason": "Reviewed"}]

    monkeypatch.setattr(api, "_fetch_whatsapp_inventory", wa_inventory)
    monkeypatch.setattr(api, "_fetch_rcs_inventory", rcs_inventory)
    monkeypatch.setattr(api, "get_rcs_bot_ids", lambda account: ["bot-one"])
    monkeypatch.setattr(sms_dlt, "_inventory", sms_inventory)
    monkeypatch.setattr(submission_client, "submit_template", no_registration)
    monkeypatch.setattr(rcs_client, "submit_rcs_template", no_registration)
    monkeypatch.setattr(vilpower_client, "submit_sms_template", no_registration)
    result = api.refresh_pending_approvals()
    assert result["checked_scopes"] == 3
    assert sorted(calls) == sorted([("tcl_promo", "whatsapp"), ("tcl_promo", "rcs", "bot-one"), ("tata", "sms")])
    assert task(wa)["approval_status"] == "approved"
    assert task(rcs)["approval_status"] == "rejected"
    assert task(rcs)["approval_reason"] == "Correct your title"
    assert task(sms)["approval_status"] == "approved"
    assert task(sms)["approval_reason"] == "Reviewed"
    assert task(mismatch)["approval_status"] == "pending"
    assert all(task(identifier)["status"] == "SUBMITTED" for identifier in (wa, rcs, sms, mismatch))


def test_unknown_or_missing_provider_states_never_become_failed_or_replayed(monkeypatch):
    unknown = seed("tcl_promo", "whatsapp", "unknown_offer", approval="unknown")
    mismatched_id = seed("tcl_promo", "whatsapp", "same_name", ref="original-id")
    duplicate_match = seed("tcl_promo", "whatsapp", "ambiguous", ref="")
    approved = seed("tcl_promo", "whatsapp", "already_approved", approval="approved")
    monkeypatch.setattr(api, "_fetch_whatsapp_inventory", lambda account: ([
        {"template_name": "unknown_offer", "fb_template_id": "provider-1", "template_create_status": "UNRECOGNIZED"},
        {"template_name": "same_name", "fb_template_id": "different-id", "template_create_status": "APPROVED"},
        {"template_name": "ambiguous", "fb_template_id": "one", "template_create_status": "APPROVED"},
        {"template_name": "ambiguous", "fb_template_id": "two", "template_create_status": "APPROVED"},
        {"template_name": "already_approved", "fb_template_id": "provider-1", "template_create_status": "REJECTED"},
    ], None))
    monkeypatch.setattr(submission_client, "submit_template", no_registration)
    api.refresh_pending_approvals()
    assert task(unknown)["approval_status"] == "unknown"
    assert task(mismatched_id)["approval_status"] == "pending"
    assert task(duplicate_match)["approval_status"] == "pending"
    assert task(approved)["approval_status"] == "approved"
    assert all(task(identifier)["status"] == "SUBMITTED" for identifier in (unknown, mismatched_id, duplicate_match, approved))


def test_provider_outage_preserves_pending_and_unknown_outcomes(monkeypatch):
    pending = seed("tcl_promo", "whatsapp", "pending_offer")
    unknown = seed("tcl_promo", "whatsapp", "unknown_offer", approval="unknown")
    monkeypatch.setattr(api, "_fetch_whatsapp_inventory", lambda account: ([], "Provider unavailable"))
    api.refresh_pending_approvals()
    assert task(pending)["approval_status"] == "pending"
    assert task(unknown)["approval_status"] == "unknown"


def test_refresh_skips_queued_failed_and_terminal_outcomes(monkeypatch):
    seed("tcl_promo", "whatsapp", "queued", status="PENDING")
    seed("tcl_promo", "rcs", "failed", status="FAILED", approval="unknown")
    seed("tata", "sms", "terminal", approval="rejected")
    monkeypatch.setattr(api, "_poll_scoped_approvals", no_registration)
    assert api.refresh_pending_approvals()["checked_scopes"] == 0


def test_approval_refresh_and_scope_poll_do_not_overlap(monkeypatch):
    api._approval_refresh_lock.acquire()
    try:
        assert api.refresh_pending_approvals()["skipped"] == "already_running"
    finally:
        api._approval_refresh_lock.release()
    api._approval_poll_locks[("tata", "sms")] = lock = __import__("threading").Lock()
    lock.acquire()
    try:
        monkeypatch.setattr(sms_dlt, "poll_approvals", no_registration)
        assert api._poll_scoped_approvals("tata", "sms", "Tester")["skipped"] == "already_running"
    finally:
        lock.release()
        api._approval_poll_locks.pop(("tata", "sms"))


def test_existing_scheduler_refreshes_approvals_even_with_email_alerts_disabled(monkeypatch):
    called = []
    monkeypatch.setattr(email_notifier.SCHEDULER_STATE, "enabled", False)
    monkeypatch.setattr(api, "refresh_pending_approvals", lambda: called.append("refresh"))

    async def stop_after_iteration(seconds):
        assert seconds == 30
        raise asyncio.CancelledError

    monkeypatch.setattr(email_notifier.asyncio, "sleep", stop_after_iteration)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(email_notifier.run_scheduler_loop())
    assert called == ["refresh"]
