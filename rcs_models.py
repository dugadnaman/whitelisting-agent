"""
Data models for RCS / DLT template submission.

Storage-agnostic dataclasses for DLT templates and submission outcomes.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class RcsSubmissionStatus(str, Enum):
    """Outcome of the DLT template registration attempt."""
    SUBMITTED = "submitted"
    FAILED = "failed"
    DUPLICATE = "duplicate"


@dataclass
class RcsTemplateSubmission:
    """One RCS DLT template to be registered/configured on Karix Lounge."""
    template_name: str
    template_id: str
    template_type: str  # "Promotional" | "Transactional" | "Service - Implicit" | "Service - Explicit"
    sender_ids: list[str]  # e.g. ["BFDLPS", "BFDLTS"] (max 5)
    template_message_type: str  # "Text" | "Unicode"
    template_message: str  # DLT content with {#var#} syntax
    entity_id: str = "110100001654"
    source_ref: str = ""

    def __post_init__(self):
        if not self.source_ref:
            self.source_ref = self.template_name


@dataclass
class RcsSubmissionResult:
    """Outcome of attempting to register one RCS DLT template."""
    source_ref: str
    template_name: str
    template_id: str
    status: RcsSubmissionStatus
    provider_response: dict | None = None
    error: str | None = None
    retry_count: int = 0
    submitted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
