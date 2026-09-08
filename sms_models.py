"""
Data models for the Karix SMS JSON API integration.

Includes dataclasses and enums for message structures, submission requests/responses,
delivery reports (DLR), and click tracking reports.
"""
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from sms_crypto import encrypt_sms_pii


class SmsMessageType(StrEnum):
    """Karix SMS content types."""

    PLAIN = "PM"  # Plain Text
    UNICODE = "UC"  # Unicode (Hindi, regional scripts)
    FLASH = "FL"  # Flash Message
    BINARY = "BM"  # Binary Message
    FLASH_UNICODE = "FU"  # Flash Unicode
    SPECIFIC_PORT = "SP"  # Specific Port
    SPECIFIC_PORT_UNICODE = "SPU"  # Specific Port Unicode
    ADVANCE = "AD"  # Advance (requires DCS, UDHI)


class SmsDeliveryStatus(StrEnum):
    """Normalized SMS Delivery Status."""

    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    FAILED = "failed"
    REJECTED = "rejected"
    PENDING = "pending"
    CLICKED = "clicked"


# Comprehensive Karix API Status & Error Code Reference
SMS_ERROR_CODES: dict[str, str] = {
    "200": "Request accepted",
    "-101": "Invalid API version",
    "-102": "Invalid JSON",
    "-105": "IP restricted",
    "-106": "Account expired",
    "-107": "Account deactivated",
    "-108": "Invalid Credentials",
    "-109": "Invalid encryption option",
    "-110": "Scheduling feature disabled",
    "-111": "Invalid schedule time",
    "-112": "Schedule time is beyond the time bound",
    "-113": "Empty mobile number",
    "-114": "Invalid mobile number",
    "-115": "Empty message content",
    "-116": "Invalid message type",
    "-117": "Invalid Port",
    "-118": "Invalid DLR type",
    "-119": "Invalid Expiry Minutes",
    "-120": "Expiry time is beyond the time bound",
    "-121": "Invalid append country code option",
    "-122": "Invalid URL tracking option",
    "-123": "Invalid customer reference id",
    "-124": "Invalid customer reference id length",
    "-125": "Cannot send message in TRAI blockout time",
    "-126": "Cannot Schedule the message delivery time to TRAI blockout time",
    "-127": "Invalid DCS value",
    "-128": "Invalid UDHI",
    "-129": "Empty senderId",
    "-130": "Invalid senderId",
    "-131": "Invalid TemplateId",
    "-132": "Empty TemplateId",
    "-142": "Access violation",
    "-143": "Empty reporting key",
    "-144": "Invalid batch number",
    "-999": "Internal Error",
}


@dataclass
class SmsMessage:
    """One SMS message payload for a recipient or group of recipients."""

    dest: list[str]  # List of mobile numbers (e.g. ["919876543210"])
    text: str  # Message content
    send: str  # Sender ID / Header (max 15 chars)
    type: str = SmsMessageType.PLAIN  # Default PM
    dlt_entity_id: str | None = None
    dlt_template_id: str | None = None
    dcs: str | None = None
    udhi_inc: str | None = None
    port: str | None = None
    vp: str | None = None  # Validity period in minutes (1 to 1440)
    app_country: str | None = None  # "0" or "1"
    country_cd: str | None = None
    template_id: str | None = None
    template_values: list[str] | None = None
    cust_ref: str | None = None
    tag: str | None = None
    tag1: str | None = None
    tag2: str | None = None
    tag3: str | None = None
    tag4: str | None = None
    tag5: str | None = None

    def to_dict(self, encrypt: bool = False, encryption_key: str | None = None) -> dict:
        """Serialize into Karix JSON request format, applying PII encryption if requested."""
        if encrypt:
            if not encryption_key:
                raise ValueError("encryption_key is required when encrypt=True")
            # Encrypt each destination number
            encrypted_dest = [encrypt_sms_pii(d, encryption_key) for d in self.dest]
            # Encrypt message text
            encrypted_text = encrypt_sms_pii(self.text, encryption_key)
            dest_val = encrypted_dest
            text_val = encrypted_text
        else:
            dest_val = self.dest
            text_val = self.text

        msg_dict: dict = {
            "dest": dest_val,
            "text": text_val,
            "send": self.send,
            "type": self.type,
        }

        optional_fields = {
            "dlt_entity_id": self.dlt_entity_id,
            "dlt_template_id": self.dlt_template_id,
            "dcs": self.dcs,
            "udhi_inc": self.udhi_inc,
            "port": self.port,
            "vp": self.vp,
            "app_country": self.app_country,
            "country_cd": self.country_cd,
            "template_id": self.template_id,
            "template_values": self.template_values,
            "cust_ref": self.cust_ref,
            "tag": self.tag,
            "tag1": self.tag1,
            "tag2": self.tag2,
            "tag3": self.tag3,
            "tag4": self.tag4,
            "tag5": self.tag5,
        }

        for k, v in optional_fields.items():
            if v is not None:
                msg_dict[k] = v

        return msg_dict


@dataclass
class SmsSendResponse:
    """Outcome of sending an SMS request to Karix."""

    ackid: str
    time: str
    status_code: str
    status_desc: str
    success: bool
    raw: dict = field(default_factory=dict)
    error_message: str | None = None


@dataclass
class SmsSubmissionResult:
    """Recorded log entry for an SMS submission."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    client: str = "bajaj"
    channel: str = "sms"
    ackid: str = ""
    status: str = "accepted"
    status_code: str = "200"
    status_desc: str = "Request accepted"
    dest_count: int = 0
    recipients: list[str] = field(default_factory=list)
    sender_id: str = ""
    message_preview: str = ""
    dlt_entity_id: str | None = None
    dlt_template_id: str | None = None
    submitted_by: str = "Operator"
    submitted_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    encrypted_pii: bool = False
    scheduled_at: str | None = None
    error: str | None = None
    source_file: str | None = None
    raw_response: dict = field(default_factory=dict)


@dataclass
class SmsDlrReport:
    """Delivery report payload received from Karix Webhook."""

    acode: str | None = None
    pcode: str | None = None
    ackid: str | None = None
    mid: str | None = None
    dest: str | None = None
    send: str | None = None
    stime: str | None = None
    dtime: str | None = None
    status: str | None = None
    status_flag: str | None = None  # "Success", "Failed", "Rejected"
    reason: str | None = None  # "Delivered", "Network Failed", "DLT Failed", etc.
    type: str | None = None
    msg: str | None = None
    split_msg_no: str | None = None
    split_msg_parts: str | None = None
    operator: str | None = None
    circle: str | None = None
    cust_mid: str | None = None
    tags: dict = field(default_factory=dict)
    raw_payload: dict = field(default_factory=dict)
    received_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    client: str = "bajaj"

    def is_delivered(self) -> bool:
        """Check if message was successfully delivered."""
        flag = (self.status_flag or "").strip().lower()
        reason = (self.reason or "").strip().lower()
        return flag == "success" or reason == "delivered"

    def is_failed(self) -> bool:
        """Check if message failed or was rejected."""
        flag = (self.status_flag or "").strip().lower()
        return flag in ("failed", "rejected")


@dataclass
class SmsClickReport:
    """SMS Click report payload received from Karix Webhook."""

    mobile_number: str
    mid: str | None = None
    clicked_date: str | None = None
    clicked_time: str | None = None
    shorturl: str | None = None
    longurl: str | None = None
    device_type: str | None = None
    operating_system: str | None = None
    browser_name: str | None = None
    browser_version: str | None = None
    platform_version: str | None = None
    campaign_name: str | None = None
    campaign_type: str | None = None
    senderid: str | None = None
    operator: str | None = None
    circle: str | None = None
    raw_payload: dict = field(default_factory=dict)
    received_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    client: str = "bajaj"
