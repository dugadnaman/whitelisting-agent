"""
Tests for Autonomous AI Copilot Auto-Remediation Engine and Meta Policy Compliance.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent import agent_instance, remediate_template_rejection, tool_diagnose_and_fix
from db_queue import get_job, get_job_tasks, init_queue_db
from models import ApprovalStatus, SubmissionResult, SubmissionStatus


def setup_module():
    init_queue_db()


def test_remediate_variable_ratio_violation():
    """Verify word-to-variable ratio remediation (Meta Error 2388293)."""
    # 2 variables with only 2 words -> ratio = 1.0 (Meta requires >= 2.5:1)
    bad_body = "Hello {{1}}, {{2}}."
    res = remediate_template_rejection(
        template_name="ratio_test",
        body_text=bad_body,
        account="bajaj",
    )
    assert any(i["policy"] == "META_VARIABLE_RATIO" for i in res["issues_detected"])
    assert "official service notification" in res["fixed_body"].lower()
    # Check that new ratio satisfies >= 2.5:1
    import re
    words = re.findall(r"\b\w+\b", re.sub(r"\{\{\d+\}\}", " ", res["fixed_body"]))
    vars_found = re.findall(r"\{\{\d+\}\}", res["fixed_body"])
    assert len(words) / len(vars_found) >= 2.5


def test_remediate_header_length_limit():
    """Verify header text exceeding 60 characters is trimmed to compliant length."""
    long_header = "Important Announcement Regarding Your Bajaj Finserv Loan Account Repayment Schedule Today"
    assert len(long_header) > 60

    res = remediate_template_rejection(
        template_name="header_test",
        body_text="Your payment of {{1}} is confirmed.",
        header_text=long_header,
        account="bajaj",
    )
    assert any(i["policy"] == "META_HEADER_LENGTH" for i in res["issues_detected"])
    assert len(res["fixed_header"]) <= 60
    assert res["fixed_header"].endswith("...")


def test_remediate_promotional_in_utility():
    """Verify templates with marketing language in UTILITY category are re-categorized to MARKETING."""
    body_with_promo = "Dear {{1}}, enjoy an exclusive 50% discount and festive cashback offer on your loan disbursement of {{2}}."
    res = remediate_template_rejection(
        template_name="cat_test",
        body_text=body_with_promo,
        category="UTILITY",
        account="tata",
    )
    assert any(i["policy"] == "META_CATEGORY_MISMATCH" for i in res["issues_detected"])
    assert res["fixed_category"] == "MARKETING"


def test_remediate_non_sequential_variables():
    """Verify non-sequential variable indices are normalized to {{1}}, {{2}}, ..."""
    non_seq_body = "Hello {{2}}, your reference code {{1}} is confirmed. Total amount is {{5}}."
    res = remediate_template_rejection(
        template_name="seq_test",
        body_text=non_seq_body,
        account="bajaj",
    )
    assert any(i["policy"] == "META_VARIABLE_ORDER" for i in res["issues_detected"])
    assert "{{1}}" in res["fixed_body"]
    assert "{{2}}" in res["fixed_body"]
    assert "{{3}}" in res["fixed_body"]
    assert "{{5}}" not in res["fixed_body"]


def test_copilot_diagnose_and_auto_resubmit_integration():
    """
    Verify full diagnose and auto-resubmit workflow:
    - Enqueues into ingestion_jobs & job_tasks
    - Submits remediated template
    - Returns job_id and new version name
    """
    mock_inspection = {
        "found": True,
        "template": {
            "template_name": "emic_check_wa_07aug",
            "approval_status": "rejected",
            "reason": "Word to variable ratio is too low (Error 2388293)",
            "body": "Hi {{1}}, code {{2}}.",
            "category": "UTILITY",
            "language": "en_US",
        },
    }

    mock_submit_result = SubmissionResult(
        source_ref="copilot_fix_emic_check_wa_07aug_v2",
        template_name="emic_check_wa_07aug_v2",
        status=SubmissionStatus.SUBMITTED,
        provider_ref_id="fb_998877",
        approval_status=ApprovalStatus.PENDING,
        client="bajaj",
    )

    with patch("agent.tool_inspect_template", return_value=mock_inspection), patch(
        "agent.submit_template", return_value=mock_submit_result
    ):
        result = tool_diagnose_and_fix(
            template_name="emic_check_wa_07aug",
            account="bajaj",
            channel="whatsapp",
            auto_resubmit=True,
            user="Tester",
        )

    assert result["success"] is True
    d = result["diagnosis"]
    assert d["original_template"] == "emic_check_wa_07aug"
    assert d["new_version_name"] == "emic_check_wa_07aug_v2"
    assert d["resubmitted"] is True
    assert d["job_id"] is not None

    # Verify task and job in SQLite database
    job = get_job(d["job_id"])
    assert job is not None
    assert job["tenant_id"] == "bajaj"

    tasks = get_job_tasks(d["job_id"])
    assert len(tasks) == 1
    assert tasks[0]["template_name"] == "emic_check_wa_07aug_v2"
    assert tasks[0]["status"] == "SUBMITTED"


def test_copilot_chat_conversational_remediation():
    """Verify conversational chat interaction for rejection diagnosis and 1-click action suggestions."""
    mock_inspection = {
        "found": True,
        "template": {
            "template_name": "festive_loan_promo",
            "approval_status": "rejected",
            "reason": "Header exceeds 60 character limit",
            "header_text": "Exclusive Grand Festive Loan Offer Available Only for Bajaj Finserv Prime Customers Today",
            "body": "Dear {{1}}, your pre-approved loan of {{2}} is ready for disbursal.",
            "category": "MARKETING",
            "language": "en_US",
        },
    }

    with patch("agent.tool_inspect_template", return_value=mock_inspection):
        chat_resp = agent_instance.handle_message(
            message="Check why template festive_loan_promo was rejected and fix it",
            account="bajaj",
            channel="whatsapp",
            user="Operator",
        )

    assert "festive_loan_promo" in chat_resp["reply"]
    assert "META_HEADER_LENGTH" in chat_resp["reply"]
    assert "festive_loan_promo_v2" in chat_resp["reply"]
    # Check 1-click suggested action is offered
    assert any("festive_loan_promo_v2" in sug for sug in chat_resp["suggested_actions"])
