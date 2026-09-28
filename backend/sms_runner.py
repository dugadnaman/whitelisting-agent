"""
SMS Runner: orchestrates loading -> client submission -> tracker logging.

Entry point for sending single or bulk SMS campaigns via Karix SMS JSON API.
"""

import logging
from pathlib import Path
from typing import Any

from activity_tracker import log_activity
from sms_client import send_sms
from sms_loader import load_sms_from_csv, load_sms_from_excel, load_sms_from_list
from sms_models import SmsSubmissionResult
from sms_tracker import log_sms_submission

logger = logging.getLogger(__name__)


def run_sms(
    messages_raw: list[dict[str, Any]],
    client: str = "bajaj",
    user: str = "Anonymous Operator",
    encrypt_pii: bool = False,
    schedule_at: str | None = None,
    log_path: str = "sms_submission_log.jsonl",
    source_file: str | None = None,
) -> SmsSubmissionResult:
    """
    Load raw message dictionaries, submit them via Karix SMS API, and log the outcome.
    """
    messages = load_sms_from_list(messages_raw, client=client)
    total_recipients = sum(len(m.dest) for m in messages)
    logger.info(
        "Loaded %d SMS message payload(s) with %d total recipient(s) for client '%s' by user '%s'",
        len(messages),
        total_recipients,
        client,
        user,
    )

    if not messages:
        res = SmsSubmissionResult(
            client=client,
            channel="sms",
            ackid="N/A",
            status="failed",
            status_code="-113",
            status_desc="No valid messages to send",
            dest_count=0,
            submitted_by=user,
            error="No valid messages parsed from input",
            source_file=source_file,
        )
        log_sms_submission(res, log_path=log_path)
        return res

    resp = send_sms(
        messages=messages,
        client=client,
        encrypt_pii=encrypt_pii,
        schedule_at=schedule_at,
    )

    all_dests = []
    for m in messages:
        all_dests.extend(m.dest)

    preview_text = messages[0].text if messages else ""
    if len(preview_text) > 100:
        preview_text = preview_text[:97] + "..."

    status_str = "accepted" if resp.success else "failed"

    res = SmsSubmissionResult(
        client=client,
        channel="sms",
        ackid=resp.ackid,
        status=status_str,
        status_code=resp.status_code,
        status_desc=resp.status_desc,
        dest_count=len(all_dests),
        recipients=all_dests[:20],  # keep preview list
        sender_id=messages[0].send if messages else "",
        message_preview=preview_text,
        dlt_entity_id=messages[0].dlt_entity_id if messages else None,
        dlt_template_id=messages[0].dlt_template_id if messages else None,
        submitted_by=user,
        encrypted_pii=encrypt_pii,
        scheduled_at=schedule_at,
        error=resp.error_message,
        source_file=source_file,
        raw_response=resp.raw,
    )

    log_sms_submission(res, log_path=log_path)

    # Log to unified activity tracker
    try:
        log_activity(
            user=user,
            action="submit_sms",
            account=client,
            channel="sms",
            status=status_str,
            details={
                "ackid": resp.ackid,
                "status_code": resp.status_code,
                "recipient_count": len(all_dests),
                "sender_id": res.sender_id,
                "source_file": source_file,
                "encrypted": encrypt_pii,
            },
        )
    except Exception as exc:
        logger.warning("Failed to record SMS activity: %s", exc)

    return res


def run_sms_file(
    file_path: str | Path,
    client: str = "bajaj",
    user: str = "Anonymous Operator",
    encrypt_pii: bool = False,
    schedule_at: str | None = None,
    log_path: str = "sms_submission_log.jsonl",
) -> SmsSubmissionResult:
    """
    Load SMS messages from CSV or Excel file, submit them, and log the outcome.
    """
    path_str = str(file_path)
    if path_str.lower().endswith((".xlsx", ".xls")):
        messages = load_sms_from_excel(path_str, client=client)
    else:
        messages = load_sms_from_csv(path_str, client=client)

    # Convert to dicts for run_sms
    raw_dicts = [
        {
            "dest": m.dest,
            "text": m.text,
            "send": m.send,
            "type": m.type,
            "dlt_entity_id": m.dlt_entity_id,
            "dlt_template_id": m.dlt_template_id,
            "cust_ref": m.cust_ref,
            "tag": m.tag,
        }
        for m in messages
    ]

    return run_sms(
        raw_dicts,
        client=client,
        user=user,
        encrypt_pii=encrypt_pii,
        schedule_at=schedule_at,
        log_path=log_path,
        source_file=Path(file_path).name,
    )
