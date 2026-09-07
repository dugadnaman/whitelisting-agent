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
from collections.abc import AsyncGenerator

from config import get_waba_id
from db_queue import (
    get_job,
    get_job_tasks,
    list_paused_jobs,
    record_task_result,
    resume_paused_jobs_for_tenant,
    update_job_status,
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

    def get_bucket_for_tenant(self, tenant_id: str) -> WabaTokenBucket:
        """Get or initialize the isolated token bucket for a tenant's WABA."""
        clean_tenant = (tenant_id or "bajaj").lower().strip()
        try:
            waba_id = get_waba_id(clean_tenant)
        except Exception:
            waba_id = f"waba_{clean_tenant}"

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
        resumed_count = resume_paused_jobs_for_tenant(clean_tenant)

        # Wake up any workers waiting on the resume event
        event = self._resume_events.get(clean_tenant)
        if event:
            event.set()

        logger.info(
            "Auto-resume triggered for %s: resumed %d paused job(s)",
            clean_tenant,
            resumed_count,
        )

        # Broadcast auth_resumed event
        for j in list_paused_jobs(clean_tenant):
            self.broadcast_event(
                j["id"],
                event="auth_resumed",
                data={"job_id": j["id"], "tenant_id": clean_tenant},
            )

        return resumed_count

    def subscribe_job(self, job_id: str) -> asyncio.Queue[str]:
        """Subscribe an SSE connection to live job events."""
        q: asyncio.Queue[str] = asyncio.Queue()
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

        payload = f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
        for q in list(listeners):
            try:
                q.put_nowait(payload)
            except Exception:
                pass

    async def sse_event_stream(self, job_id: str) -> AsyncGenerator[str, None]:
        """Yield Server-Sent Events for a job until it settles or client disconnects."""
        q = self.subscribe_job(job_id)
        try:
            # Emit initial snapshot event
            initial_job = get_job(job_id)
            if initial_job:
                yield f"event: job_status\ndata: {json.dumps(initial_job, default=str)}\n\n"

            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=20.0)
                    yield payload
                except TimeoutError:
                    # Keep-alive heartbeat
                    yield ": ping\n\n"
                    # Check if job settled while waiting
                    job = get_job(job_id)
                    if job and job.get("status") in ("COMPLETED", "PARTIALLY_COMPLETED", "FAILED"):
                        yield f"event: job_status\ndata: {json.dumps(job, default=str)}\n\n"
                        break
        finally:
            self.unsubscribe_job(job_id, q)

    def start_job_execution(self, job_id: str, tenant_id: str, channel: str = "whatsapp") -> asyncio.Task:
        """Spawn asynchronous background task to execute all pending tasks in the job."""
        task = asyncio.create_task(self._process_job_tasks(job_id, tenant_id, channel))
        self._active_worker_tasks.add(task)
        task.add_done_callback(self._active_worker_tasks.discard)
        return task

    async def _process_job_tasks(self, job_id: str, tenant_id: str, channel: str) -> None:
        """
        Background worker processing tasks through fair-share rate limiter
        and handling circuit-breaker pause / resume logic.
        """
        clean_tenant = tenant_id.lower().strip()
        bucket = self.get_bucket_for_tenant(clean_tenant)
        update_job_status(job_id, "RUNNING")
        self.broadcast_event(job_id, "job_status", {"job_id": job_id, "status": "RUNNING"})

        tasks = get_job_tasks(job_id)
        for task_row in tasks:
            task_id = task_row["id"]
            if task_row["status"] != "PENDING":
                # Already resolved (e.g. duplicate during upload ingestion)
                continue

            # Check if circuit breaker is tripped; if so, wait for auto-resume event
            while self.is_auth_tripped(clean_tenant):
                event = self._resume_events.setdefault(clean_tenant, asyncio.Event())
                logger.info("Worker paused on %s waiting for credential resume event...", clean_tenant)
                await event.wait()

            # Acquire rate limit token from WABA bucket
            await bucket.acquire(1.0)

            # Re-check circuit breaker after token wait
            if self.is_auth_tripped(clean_tenant):
                continue

            # Execute submission
            payload_dict = json.loads(task_row["payload_json"])
            result = await self._execute_task_submission(task_row, payload_dict, clean_tenant, channel)

            # Check if execution triggered a 401 Session Expiration
            err_str = str(result.error or "")
            if "401" in err_str or "session expired" in err_str.lower() or "unauthorised" in err_str.lower():
                self.trip_auth_circuit(clean_tenant, job_id, err_str)
                # Keep task PENDING so it re-executes cleanly on resume
                continue

            # Check if carrier returned a 429 rate limit
            if "429" in err_str or "too many requests" in err_str.lower():
                bucket.record_429(backoff_sec=45.0)

            # Record final task result in database
            updated_task = record_task_result(
                task_id=task_id,
                status=result.status.value,
                approval_status=result.approval_status.value,
                provider_ref_id=result.provider_ref_id,
                error=result.error,
                approval_reason=result.approval_reason,
            )

            # Broadcast row progress to SSE clients
            if updated_task:
                self.broadcast_event(job_id, "task_update", updated_task)

        # Final job status check & broadcast
        final_job = get_job(job_id)
        if final_job:
            self.broadcast_event(job_id, "job_status", final_job)

    async def _execute_task_submission(
        self,
        task_row: dict[str, Any],
        payload_dict: dict[str, Any],
        clean_tenant: str,
        channel: str,
    ) -> SubmissionResult:
        """Run single template submission in threadpool to avoid blocking event loop."""
        if channel == "rcs":
            # RCS template submission
            from rcs_client import submit_rcs_template
            from rcs_models import RcsSubmissionStatus, RcsTemplateSubmission

            rcs_sub = RcsTemplateSubmission(
                client=clean_tenant,
                template_name=task_row["template_name"],
                template_type=payload_dict.get("template_type", "RICH_CARD_STANDALONE"),
                source_ref=task_row["source_ref"] or task_row["template_name"],
                content_message=payload_dict.get("content_message", {}),
            )
            rcs_res = await asyncio.to_thread(submit_rcs_template, rcs_sub, client=clean_tenant)
            status_map = {
                RcsSubmissionStatus.SUBMITTED: SubmissionStatus.SUBMITTED,
                RcsSubmissionStatus.DUPLICATE: SubmissionStatus.DUPLICATE,
                RcsSubmissionStatus.FAILED: SubmissionStatus.FAILED,
            }
            return SubmissionResult(
                source_ref=rcs_res.source_ref,
                template_name=rcs_res.template_name,
                status=status_map.get(rcs_res.status, SubmissionStatus.FAILED),
                provider_ref_id=rcs_res.template_id,
                error=rcs_res.error,
                approval_status=ApprovalStatus.APPROVED if rcs_res.status == RcsSubmissionStatus.SUBMITTED else ApprovalStatus.UNKNOWN,
                client=clean_tenant,
                channel="rcs",
            )

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

        has_media = any(c.type == "HEADER" and (c.format or "").upper() in ("IMAGE", "VIDEO", "DOCUMENT") for c in components)
        if has_media:
            return await asyncio.to_thread(_submit_portal_template, wa_sub, client=clean_tenant)
        else:
            return await asyncio.to_thread(submit_template, wa_sub, client=clean_tenant)


# Global singleton instance
QUEUE_MANAGER = QueueManager()
