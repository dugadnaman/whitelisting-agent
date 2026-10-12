"""
RCS Runner: wires rcs_loader -> rcs_client -> rcs_tracker together.

Entry point for submitting RCS DLT templates for configuration on Karix Lounge.
"""

import base64
import json
import logging
import os
import re
import sys
from pathlib import Path
from dataclasses import asdict, fields

from db_queue import claim_task, create_job_with_tasks, get_job, get_job_task, validate_task_scope

from rcs_client import submit_rcs_template
from rcs_loader import load_rcs_from_csv, load_rcs_from_excel, load_rcs_from_list
from rcs_models import RcsSubmissionResult, RcsSubmissionStatus, RcsTemplateSubmission
from rcs_tracker import _row_to_entry_dict, log_rcs_result

logger = logging.getLogger(__name__)


def rcs_submission_payload(submission: RcsTemplateSubmission) -> dict:
    """Persist the real submission, including embedded media, for queue consumers."""
    payload = asdict(submission)
    for item in [payload, *payload.get("carousel_cards", [])]:
        image = item.pop("image_bytes", None)
        if image is not None:
            item["image_bytes_base64"] = base64.b64encode(image).decode("ascii")
    return payload


def rcs_submission_from_payload(payload: dict) -> RcsTemplateSubmission:
    values = {field.name: payload[field.name] for field in fields(RcsTemplateSubmission) if field.name in payload}
    values["carousel_cards"] = [dict(card) for card in values.get("carousel_cards", [])]
    for item, source in [(values, payload), *zip(values["carousel_cards"], payload.get("carousel_cards", []), strict=True)]:
        if source.get("image_bytes_base64") is not None:
            item["image_bytes"] = base64.b64decode(source["image_bytes_base64"], validate=True)
        item.pop("image_bytes_base64", None)
    return RcsTemplateSubmission(**values)


def is_definitive_auth_refusal(result) -> bool:
    """Retry only a definitive RCS refusal flag or the established WhatsApp HTTP auth response."""
    return (
        str(result.status).lower() == "failed"
        and not getattr(result, "outcome_uncertain", False)
        and (
            (result.channel == "rcs" and getattr(result, "auth_refused", False))
            or (result.channel == "whatsapp" and bool(re.match(
                r"(?:Session expired \(401\)|HTTP (?:401|403):)", str(result.error or "")
            )))
        )
    )


def run_rcs(
    templates_raw: list,
    log_path: str = "rcs_submission_log.jsonl",
    client: str = "bajaj",
    user: str = "Anonymous Operator",
    source_file: str | None = None,
    *,
    task_ids: list[str] | None = None,
) -> list[dict]:
    """Submit each row and return its persisted result in input order."""
    if templates_raw and isinstance(templates_raw[0], RcsTemplateSubmission):
        submissions = templates_raw
    else:
        submissions = load_rcs_from_list(templates_raw, client=client)
    if task_ids is not None and len(task_ids) != len(submissions):
        raise ValueError("RCS task IDs must correspond one-to-one with input rows")
    client = str(client or "").lower().strip()
    if not client:
        raise ValueError("RCS submissions require an explicit tenant")
    if task_ids is None and submissions:
        job = create_job_with_tasks(client, "rcs", source_file or "direct_submission_rcs", user,
                                    [rcs_submission_payload(submission) for submission in submissions])
        task_ids = [f"task_{job['id']}_{index:04d}" for index in range(len(submissions))]
    results = []
    print(f"Loaded {len(submissions)} RCS template(s) for {client} to submit (by {user}).")

    for index, submission in enumerate(submissions):
        task_id = task_ids[index]
        existing = get_job_task(task_id)
        job = get_job(existing["job_id"]) if existing else None
        if not existing or not job or job["tenant_id"] != client or job["channel"] != "rcs":
            raise ValueError("RCS submission task/job does not belong to the selected tenant/channel")
        claimed = claim_task(task_id, client, "rcs")
        if claimed is None:
            results.append(_row_to_entry_dict(get_job_task(task_id)))
            continue
        task_payload = {}
        dispatched = False
        try:
            task_payload = json.loads(claimed["payload_json"])
            validate_task_scope(claimed, task_payload, client, "rcs")
            if str(submission.client or "").lower().strip() != client or submission.channel != "rcs":
                raise ValueError("RCS submission payload does not belong to the selected tenant/channel")
            if submission.source_ref != claimed["source_ref"] or submission.template_name != claimed["template_name"]:
                raise ValueError("RCS submission does not match its owning task row")
            dispatched = True
            result = submit_rcs_template(submission, client=client)
            if str(result.client or "").lower().strip() != client or result.channel != "rcs":
                raise ValueError("RCS provider result does not match its owning tenant/channel")
        except Exception as exc:
            result = RcsSubmissionResult(
                source_ref=claimed["source_ref"], template_name=claimed["template_name"],
                status=RcsSubmissionStatus.FAILED, approval_status="unknown",
                error=(f"RCS submission interrupted; reconcile unknown provider outcome: {exc}"
                       if dispatched else f"RCS submission rejected before dispatch: {exc}"),
                client=client, outcome_uncertain=dispatched,
            )
        if is_definitive_auth_refusal(result):
            from db_queue import release_task_for_auth, update_job_status
            update_job_status(claimed["job_id"], "PAUSED_FOR_AUTH", result.error)
            release_task_for_auth(task_id)
            results.append(_row_to_entry_dict(get_job_task(task_id)))
            continue
        # Provider names may be normalized; attribution always belongs to this row.
        result.source_ref = claimed["source_ref"]
        result.template_name = claimed["template_name"]
        result.client = client
        result.channel = "rcs"
        result.bot_id = (task_payload.get("bot_id") if isinstance(task_payload, dict) else None) or submission.bot_id
        result.submitted_by = user
        result.source_file = source_file or result.source_file
        results.append(log_rcs_result(result, log_path, task_id=task_id))

        # Record template failures into central error log & feed learning engine
        if result.status == RcsSubmissionStatus.FAILED or (
            result.error and result.status != RcsSubmissionStatus.SUBMITTED
        ):
            try:
                from error_tracker import log_error

                log_error(
                    message=f"RCS template '{result.template_name}' creation failed: {result.error}",
                    account=client,
                    channel="rcs",
                    severity="ERROR" if result.status == RcsSubmissionStatus.FAILED else "WARNING",
                    category="TEMPLATE_CREATION_FAILED"
                    if result.status == RcsSubmissionStatus.FAILED
                    else "DUPLICATE_TEMPLATE",
                    module="rcs_client.py",
                    function="submit_rcs_template",
                    context={
                        "template_name": result.template_name,
                        "template_id": result.template_id,
                        "status": result.status.value,
                        "error": result.error,
                        "provider_response": result.provider_response,
                    },
                    remediation_hint=(
                        "Check image URL reachability or shorten template name to <= 25 characters to prevent collision."
                        if "already exists" in str(result.error).lower() or "read data" in str(result.error).lower()
                        else "Check Karix Bot Builder parameters."
                    ),
                )
            except Exception as log_ex:
                logger.warning("Failed to record template failure in error_tracker: %s", log_ex)

        note = f" ({result.retry_count} retries)" if result.retry_count else ""
        print(f"  {result.template_name} (ID: {result.template_id}): {result.status.value}{note}")

    print(f"Done. Results appended to {log_path}")
    return results


def run_rcs_file(
    file_path: str,
    log_path: str = "rcs_submission_log.jsonl",
    client: str = "bajaj",
    user: str = "Anonymous Operator",
) -> list[dict]:
    """Load a file and delegate to the same row-isolated submission path."""
    if file_path.lower().endswith((".xlsx", ".xls")):
        submissions = load_rcs_from_excel(file_path, client=client, upload_media=False)
    else:
        submissions = load_rcs_from_csv(file_path, client=client)
    return run_rcs(submissions, log_path, client=client, user=user, source_file=Path(file_path).name)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and not args[0].startswith("-"):
        target_file = " ".join(args)
        if not os.path.exists(target_file) and os.path.exists(args[0]):
            target_file = args[0]
        run_rcs_file(target_file)
    else:
        print("Usage:")
        print("  python3 rcs_runner.py samples/rcs_templates_sample.csv")
        print("  python3 rcs_runner.py rcs_templates.xlsx")
