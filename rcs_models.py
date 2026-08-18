"""
Data models for Karix RCS Bot Builder & DLT template submissions.

Storage-agnostic dataclasses for text messages, rich cards, suggestions, and submission outcomes.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class RcsSubmissionStatus(str, Enum):
    """Outcome of the RCS template submission attempt."""
    SUBMITTED = "submitted"
    FAILED = "failed"
    DUPLICATE = "duplicate"


@dataclass
class RcsSuggestion:
    """One suggested reply or action for an RCS template."""
    suggestion_type: str  # "reply" | "url_action" | "dialer_action"
    text: str
    postback_data: str = ""
    url: str | None = None
    phone_number: str | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "suggestionType": self.suggestion_type,
            "text": self.text,
            "postbackData": self.postback_data or self.text.lower().replace(" ", "_"),
        }
        if self.suggestion_type == "url_action" and self.url:
            d["url"] = self.url
        elif self.suggestion_type == "dialer_action" and self.phone_number:
            d["phoneNumber"] = self.phone_number
        return d


@dataclass
class RcsTemplateSubmission:
    """One RCS template to be submitted to Karix RCS Bot Builder."""
    template_name: str
    bot_id: str = ""
    template_type: str = "text"  # "text" | "richcard" | "carousel" | "Transactional" | "Promotional"
    text_message: str = ""
    card_title: str | None = None
    card_description: str | None = None
    media_url: str | None = None
    orientation: str = "VERTICAL"  # "VERTICAL" | "HORIZONTAL"
    height: str = "MEDIUM"  # "SHORT" | "MEDIUM" | "TALL"
    width: str = "MEDIUM"  # "SMALL" | "MEDIUM" (for carousel cards)
    suggestions: list[dict] = field(default_factory=list)
    carousel_cards: list[dict] = field(default_factory=list)
    template_category: str = "TRANSACTIONAL"
    entity_id: str = ""
    template_id: str = ""  # DLT ID if applicable
    sender_ids: list[str] = field(default_factory=list)
    template_message_type: str = "Text"
    client: str = "tata"
    channel: str = "rcs"
    source_ref: str = ""

    def __post_init__(self):
        if not self.source_ref:
            self.source_ref = self.template_name


@dataclass
class RcsSubmissionResult:
    """Outcome of attempting to submit one RCS template."""
    source_ref: str
    template_name: str
    template_id: str | None
    status: RcsSubmissionStatus
    provider_response: dict | None = None
    error: str | None = None
    retry_count: int = 0
    client: str = "tata"
    channel: str = "rcs"
    submitted_by: str = "Anonymous Operator"
    source_file: str | None = None  # name of the uploaded spreadsheet, for dashboard attribution
    submitted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
