"""
Queue Manager, Per-WABA Rate Limiter, Circuit Breaker, and SSE Event Hub.

Provides:
- Per-WABA Token Bucket with dynamic 429 backoff
- PAUSED_FOR_AUTH Circuit Breaker with event-bus auto-resume
- Asynchronous Job Execution Worker
- Real-time Server-Sent Events (SSE) dispatcher for live UI updates
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import time
from dataclasses import asdict
from collections.abc import AsyncGenerator
from typing import Any

from config import get_waba_id
from db_queue import (
    JOB_TERMINAL_STATUSES,
    claim_task,
    fail_unfinished_job,
    get_job,
    get_job_tasks,
    list_paused_jobs,
    record_task_result,
    release_task_for_auth,
    resume_paused_jobs_for_tenant,
    update_job_status,
    validate_task_scope,
)
from models import (
    ApprovalStatus,
    SubmissionResult,
    SubmissionStatus,
    TemplateComponent,
    TemplateSubmission,
)
from submission_client import _submit_portal_template, submit_template

logger = logging.getLogger(__name__)


class WabaTokenBucket:
    """
    Token bucket rate limiter isolated per WABA ID.
    Enforces requests/sec quota and applies dynamic backoff on HTTP 429 responses.
    """

    def __init__(self, waba_id: str, rate_per_sec: float = 10.0, capacity: float = 15.0) -> None:
        self.waba_id = waba_id
        self.rate_per_sec = rate_per_sec
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self.throttled_until: float = 0.0
        self._lock = asyncio.Lock()

    def record_429(self, backoff_sec: float = 60.0) -> None:
        """Throttle this WABA bucket upon carrier 429 rate limit notification."""
        self.throttled_until = time.monotonic() + backoff_sec
        self.tokens = 0.0
        logger.warning(
            "WABA %s received HTTP 429: dynamic backoff applied for %.1fs",
            self.waba_id,
            backoff_sec,
        )

    async def acquire(self, cost: float = 1.0) -> None:
        """Asynchronously wait until tokens are available under the WABA quota."""
        while True:
            async with self._lock:
                now = time.monotonic()

                # If under dynamic 429 backoff, sleep remaining backoff time
                if now < self.throttled_until:
                    sleep_time = self.throttled_until - now
                else:
                    # Refill tokens based on elapsed time
                    elapsed = now - self.last_refill
                    self.last_refill = now
                    self.tokens = min(self.capacity, self.tokens + elapsed * self.rate_per_sec)

                    if self.tokens >= cost:
                        self.tokens -= cost
                        return
                    sleep_time = (cost - self.tokens) / self.rate_per_sec

            await asyncio.sleep(max(0.05, sleep_time))


class QueueManager:
    """
    Central coordinator for multi-tenant rate limits, circuit breakers,
    asynchronous background workers, and Server-Sent Event (SSE) streams.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, WabaTokenBucket] = {}
        self._auth_circuits: dict[str, bool] = {}  # tenant_id -> is_tripped
        self._resume_events: dict[str, asyncio.Event] = {}  # tenant_id -> Event
        self._sse_listeners: dict[str, set[asyncio.Queue[str]]] = collections.defaultdict(set)
        self._active_worker_tasks: set[asyncio.Task] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def get_bucket_for_tenant(self, tenant_id: str) -> WabaTokenBucket:
        """Get or initialize the isolated token bucket for a tenant's WABA."""
        clean_tenant = str(tenant_id or "").lower().strip()
        if not clean_tenant:
            raise ValueError("Queue rate limits require an explicit tenant")
        waba_id = get_waba_id(clean_tenant)

        if waba_id not in self._buckets:
            # Default to 10 req/s, burst capacity 15
            self._buckets[waba_id] = WabaTokenBucket(waba_id=waba_id, rate_per_sec=10.0, capacity=15.0)
        return self._buckets[waba_id]

    def is_auth_tripped(self, tenant_id: str) -> bool:
        """Check if tenant's circuit breaker is currently active (paused on 401)."""
        return self._auth_circuits.get(tenant_id.lower().strip(), False)

    def trip_auth_circuit(self, tenant_id: str, job_id: str, error_msg: str) -> None:
        """
        Trip the circuit breaker on 401 Session Expired:
        - Halts tenant's queue
        - Flips job status to PAUSED_FOR_AUTH
        - Emits auth_paused event to SSE streams
        """
        clean_tenant = tenant_id.lower().strip()
        self._auth_circuits[clean_tenant] = True
        if clean_tenant not in self._resume_events:
            self._resume_events[clean_tenant] = asyncio.Event()
        else:
            self._resume_events[clean_tenant].clear()

        update_job_status(job_id, "PAUSED_FOR_AUTH", error_message=error_msg)
        logger.warning(
            "Auth circuit tripped for %s on job %s: %s",
            clean_tenant,
            job_id,
            error_msg,
        )

        self.broadcast_event(
            job_id,
            event="auth_paused",
            data={
                "job_id": job_id,
                "tenant_id": clean_tenant,
                "message": (
                    f"Karix session expired for {clean_tenant.upper()}. "
                    "Open Settings, paste fresh credentials, and click Save to auto-resume."
                ),
            },
        )

    def notify_credentials_updated(self, tenant_id: str) -> int:
        """
        Event-bus auto-resume trigger called when operator updates/tests credentials in Settings.
        Clears circuit breaker and seamlessly resumes all paused batches for the tenant.
        """
        clean_tenant = tenant_id.lower().strip()
        self._auth_circuits[clean_tenant] = False
        paused_jobs = list_paused_jobs(clean_tenant)
        resumed_count = resume_paused_jobs_for_tenant(clean_tenant)

        # Wake up any workers waiting on the resume event
        event = self._resume_events.get(clean_tenant)
        if event and self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(event.set)

        logger.info(
            "Auto-resume triggered for %s: resumed %d paused job(s)",
            clean_tenant,
            resumed_count,
        )

        # Broadcast auth_resumed event
        for j in paused_jobs:
            self.broadcast_event(j["id"], event="auth_resumed", data={"job_id": j["id"], "tenant_id": clean_tenant})
            if self._loop and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self.start_job_execution, j["id"], clean_tenant, j["channel"])
        return resumed_count

    def subscribe_job(self, job_id: str) -> asyncio.Queue[str]:
        """Subscribe an SSE connection to live job events."""
        self.bind_event_loop()
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=128)
        self._sse_listeners[job_id].add(q)
        return q

    def unsubscribe_job(self, job_id: str, q: asyncio.Queue[str]) -> None:
        """Remove an SSE connection subscriber."""
        listeners = self._sse_listeners.get(job_id)
        if listeners:
            listeners.discard(q)
            if not listeners:
                self._sse_listeners.pop(job_id, None)

    def broadcast_event(self, job_id: str, event: str, data: dict[str, Any]) -> None:
        """Broadcast an SSE event payload to all active client listeners."""
        listeners = self._sse_listeners.get(job_id)
        if not listeners:
            return
        if self._loop and not self._loop.is_closed():
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            if current_loop is not self._loop:
                self._loop.call_soon_threadsafe(self.broadcast_event, job_id, event, data)
                return

        if event == "task_update" and "payload_json" in data:
            data = {key: value for key, value in data.items() if key != "payload_json"}
        payload = f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
        for q in list(listeners):
            if q.full():
                q.get_nowait()
            q.put_nowait(payload)

    async def sse_event_stream(self, job_id: str) -> AsyncGenerator[str, None]:
        """Yield Server-Sent Events for a job until it settles or client disconnects."""
        q = self.subscribe_job(job_id)
        try:
            # Emit initial snapshot event
            initial_job = get_job(job_id)
            if initial_job:
                yield f"event: job_status\ndata: {json.dumps(initial_job, default=str)}\n\n"
                if initial_job.get("status") in JOB_TERMINAL_STATUSES:
                    return
            else:
                return

            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=20.0)
                    yield payload
                    event_data = json.loads(payload.split("\ndata: ", 1)[1].strip())
                    if event_data.get("status") in JOB_TERMINAL_STATUSES:
                        return
                    job = get_job(job_id)
                    if job and job.get("status") in JOB_TERMINAL_STATUSES:
                        yield f"event: job_status\ndata: {json.dumps(job, default=str)}\n\n"
                        return
                except TimeoutError:
                    # Keep-alive heartbeat
                    yield ": ping\n\n"
                    # Check if job settled while waiting
                    job = get_job(job_id)
                    if job and job.get("status") in JOB_TERMINAL_STATUSES:
                        yield f"event: job_status\ndata: {json.dumps(job, default=str)}\n\n"
                        break
        finally:
            self.unsubscribe_job(job_id, q)

    def bind_event_loop(self) -> None:
        self._loop = asyncio.get_running_loop()

    def start_job_execution(self, job_id: str, tenant_id: str, channel: str = "whatsapp") -> asyncio.Task:
        """Spawn asynchronous background task to execute all pending tasks in the job."""
        self.bind_event_loop()
        task = asyncio.create_task(self._process_job_tasks(job_id, tenant_id, channel))
        self._active_worker_tasks.add(task)
        task.add_done_callback(self._active_worker_tasks.discard)
        return task

    async def _process_job_tasks(self, job_id: str, tenant_id: str, channel: str) -> None:
        """Claim every row before dispatch; an interrupted POST is never replayed."""
        clean_tenant = str(tenant_id or "").lower().strip()
        channel = str(channel or "").lower().strip()
        job = get_job(job_id)
        if not job or job["tenant_id"] != clean_tenant or job["channel"] != channel:
            raise ValueError("Queue job does not belong to the selected tenant/channel")
        if job["status"] in JOB_TERMINAL_STATUSES:
            self.broadcast_event(job_id, "job_status", job)
            return
        try:
            if channel in {"rcs", "sms"}:
                key = f"{channel}:{clean_tenant}"
                bucket = self._buckets.setdefault(key, WabaTokenBucket(key, rate_per_sec=1.0 if channel == "sms" else 10.0, capacity=1.0 if channel == "sms" else 15.0))
            else:
                bucket = self.get_bucket_for_tenant(clean_tenant)
            if job["status"] == "QUEUED":
                update_job_status(job_id, "RUNNING")
            for task_row in get_job_tasks(job_id):
                if task_row["status"] != "PENDING":
                    continue
                observed_pause = False
                while True:
                    job = get_job(job_id)
                    if not job or job["status"] in JOB_TERMINAL_STATUSES:
                        return
                    if channel != "sms" and (job["status"] == "PAUSED_FOR_AUTH" or (self.is_auth_tripped(clean_tenant) and not observed_pause)):
                        observed_pause = True
                        if job["status"] != "PAUSED_FOR_AUTH":
                            update_job_status(job_id, "PAUSED_FOR_AUTH", "Tenant credentials require refresh before dispatch.")
                        event = self._resume_events.setdefault(clean_tenant, asyncio.Event())
                        try:
                            await asyncio.wait_for(event.wait(), timeout=1.0)
                        except TimeoutError:
                            pass
                        continue
                    if channel != "sms":
                        self._auth_circuits[clean_tenant] = False
                    await bucket.acquire()
                    claimed = claim_task(task_row["id"], clean_tenant, channel)
                    if claimed is None:
                        if (get_job(job_id) or {}).get("status") == "PAUSED_FOR_AUTH":
                            continue
                        break
                    cancelled = False
                    try:
                        payload = json.loads(claimed["payload_json"])
                        validate_task_scope(claimed, payload, clean_tenant, channel)
                        execution = asyncio.create_task(self._execute_task_submission(claimed, payload, clean_tenant, channel))
                        while True:
                            try:
                                result = await asyncio.shield(execution)
                                break
                            except asyncio.CancelledError:
                                # Repeated caller cancellation must not cancel the provider thread.
                                cancelled = True
                                if execution.cancelled():
                                    raise RuntimeError("Submission operation cancelled; provider outcome unknown.") from None
                        if str(result.client or "").lower().strip() != clean_tenant or result.channel != channel:
                            raise ValueError("Provider result does not belong to the claimed tenant/channel")
                    except Exception as exc:
                        result = SubmissionResult(
                            source_ref=claimed["source_ref"], template_name=claimed["template_name"],
                            status=SubmissionStatus.FAILED, approval_status=ApprovalStatus.UNKNOWN,
                            error=f"Submission interrupted; provider outcome may be unknown: {exc}",
                            client=clean_tenant, channel=channel,
                        )
                    from rcs_runner import is_definitive_auth_refusal
                    if channel != "sms" and is_definitive_auth_refusal(result) and not cancelled:
                        self.trip_auth_circuit(clean_tenant, job_id, str(result.error))
                        release_task_for_auth(claimed["id"])
                        continue
                    if "429" in str(result.error or ""):
                        bucket.record_429(backoff_sec=45.0)
                    result_payload = asdict(result)
                    result_payload.update(source_ref=claimed["source_ref"], template_name=claimed["template_name"])
                    updated = record_task_result(
                        claimed["id"], str(result.status), str(result.approval_status or "unknown"),
                        provider_ref_id=result.provider_ref_id, error=result.error,
                        approval_reason=result.approval_reason, result_payload=result_payload,
                        retry_count=getattr(result, "retry_count", 0),
                    )
                    if updated:
                        self.broadcast_event(job_id, "task_update", updated)
                    if cancelled:
                        raise asyncio.CancelledError
                    break
        except (Exception, asyncio.CancelledError) as exc:
            fail_unfinished_job(job_id, str(exc) or "Submission worker cancelled before dispatch.")
            raise
        finally:
            final_job = get_job(job_id)
            if final_job:
                self.broadcast_event(job_id, "job_status", final_job)

    async def _execute_task_submission(
        self,
        task_row: dict[str, Any],
        payload_dict: dict[str, Any],
        clean_tenant: str,
        channel: str,
    ) -> Any:
        """Run single template submission in threadpool to avoid blocking event loop."""
        if channel == "sms":
            from vilpower_client import submit_sms_template
            result = await asyncio.to_thread(submit_sms_template, payload_dict, client=clean_tenant)
            result.submitted_by = payload_dict.get("submitted_by") or result.submitted_by
            result.source_file = payload_dict.get("source_file") or result.source_file
            return result

        if channel == "rcs":
            from rcs_client import submit_rcs_template
            from rcs_runner import rcs_submission_from_payload

            rcs_sub = rcs_submission_from_payload(payload_dict)
            rcs_res = await asyncio.to_thread(submit_rcs_template, rcs_sub, client=clean_tenant)
            rcs_res.source_ref = task_row["source_ref"]
            rcs_res.template_name = task_row["template_name"]
            rcs_res.submitted_by = payload_dict.get("submitted_by") or rcs_res.submitted_by
            rcs_res.source_file = payload_dict.get("source_file") or rcs_res.source_file
            return rcs_res

        # WhatsApp template submission
        # Build TemplateSubmission object
        components = []
        for c in payload_dict.get("components", []):
            if isinstance(c, dict):
                components.append(
                    TemplateComponent(
                        type=c.get("type", "BODY"),
                        text=c.get("text"),
                        format=c.get("format"),
                        variables=c.get("variables"),
                        buttons=c.get("buttons"),
                        example=c.get("example"),
                        media_url=c.get("media_url"),
                        media_file=c.get("media_file"),
                        file_type=c.get("file_type"),
                    )
                )

        wa_sub = TemplateSubmission(
            client=clean_tenant,
            channel="whatsapp",
            template_name=task_row["template_name"],
            language=payload_dict.get("language", "en_US"),
            category=payload_dict.get("category", "MARKETING"),
            waba_id=payload_dict.get("waba_id") or get_waba_id(clean_tenant),
            components=components,
            source_ref=task_row["source_ref"] or task_row["template_name"],
        )

        has_media = any(
            c.type == "HEADER" and (c.format or "").upper() in ("IMAGE", "VIDEO", "DOCUMENT") for c in components
        )
        if has_media:
            return await asyncio.to_thread(_submit_portal_template, wa_sub, client=clean_tenant)
        else:
            return await asyncio.to_thread(submit_template, wa_sub, client=clean_tenant)


# Global singleton instance
QUEUE_MANAGER = QueueManager()
