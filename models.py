"""
Shared data models for the Phase-2 (submission-only) pipeline.

Kept deliberately storage-agnostic: these are plain dataclasses, not tied to
a sheet, DB, or file format. The loader/tracker layers translate to/from
whatever storage you end up using.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SubmissionStatus(str, Enum):
    """Outcome of the SUBMIT attempt itself (did the API call succeed)."""
    SUBMITTED = "submitted"
    FAILED = "failed"


class ApprovalStatus(str, Enum):
    """
    Outcome of the actual template REVIEW (separate from submission).
    A template can be SUBMITTED successfully and still sit in PENDING for
    a while before Karix/Meta resolves it to APPROVED or REJECTED.
    """
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    UNKNOWN = "unknown"  # submission failed, or status check errored


@dataclass
class TemplateComponent:
    """One block of a template: HEADER, BODY, FOOTER, or BUTTONS."""
    type: str  # "HEADER" | "BODY" | "FOOTER" | "BUTTONS"
    text: str | None = None
    format: str | None = None
    variables: list | None = None
    buttons: list | None = None
    example: dict | None = None
    media_url: str | None = None
    media_file: str | None = None

@dataclass
class TemplateSubmission:
    """One template to be submitted for whitelisting."""
    client: str  # "bajaj" (kept explicit for when Tata Capital Phase 2 exists)
    channel: str  # "whatsapp" for now
    template_name: str
    language: str
    category: str
    waba_id: str
    components: list[TemplateComponent]
    source_ref: str  # traces back to wherever this row came from


@dataclass
class SubmissionResult:
    """
    Outcome of attempting to submit one template, plus its latest known
    review outcome (updated later by check_status / the poller).
    """
    source_ref: str
    template_name: str
    status: SubmissionStatus
    provider_ref_id: str | None = None
    provider_response: dict | None = None
    error: str | None = None
    retry_count: int = 0
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    approval_reason: str | None = None  # e.g. rejection reason from Karix
    client: str = "bajaj"
    channel: str = "whatsapp"
    submitted_by: str = "Anonymous Operator"
    source_file: str | None = None  # name of the uploaded spreadsheet, for dashboard attribution
    submitted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str | None = None  # set when check_status refreshes this
