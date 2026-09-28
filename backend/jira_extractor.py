"""
TypeSafe AI Semantic Jira Brief & Template Extractor.
Analyzes free-form Jira issue descriptions, campaign briefs, and ticket comments:
1. Channel & Purpose Routing (Choice primitive): Routes to WHATSAPP, RCS, or SMS.
2. Structured Component Extraction (Choice / Noul primitives): Segments Header, Body, Footer, and CTA.
3. Calibrated Sample Variable Generation (Choice primitive): Generates Meta-compliant sample values.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from config import _load_env_file

logger = logging.getLogger(__name__)

_load_env_file()

# Standard compliant sample values by semantic type for Meta WhatsApp / Karix
META_COMPLIANT_SAMPLES: dict[str, str] = {
    "CUSTOMER_NAME": "Rahul Sharma",
    "CURRENCY_AMOUNT": "25,000",
    "PERCENTAGE_RATE": "9.99",
    "CALENDAR_DATE": "15th Oct 2026",
    "ACCOUNT_NUMBER": "TCF12345678",
    "TENURE_COUNT": "24",
    "URL_LINK": "https://www.tatacapital.com",
    "GENERIC_TEXT": "SAMPLE_VAL",
}

VARIABLE_TYPE_CRITERIA: dict[str, str] = {
    "CUSTOMER_NAME": "Name of an individual customer, client, or person (e.g. Rahul, Priya)",
    "CURRENCY_AMOUNT": "Monetary value, price, EMI amount, loan limit, or fee (e.g. 15,000, 5,00,000)",
    "PERCENTAGE_RATE": "Interest rate, discount percentage, cashback percentage, or ROI (e.g. 10.5, 9.99)",
    "CALENDAR_DATE": "Date, month, day, or deadline (e.g. 10th Oct, 25/12/2026, tomorrow)",
    "ACCOUNT_NUMBER": "Account number, masked bank account, or loan ID (e.g. XX1234, TCL987654)",
    "TENURE_COUNT": "Number of installments, months, years, or counts (e.g. 24, 36, 12)",
    "URL_LINK": "Website link, secure portal URL, or web destination",
    "GENERIC_TEXT": "General code, branch name, or text",
}


@dataclass
class JiraRoutingDecision:
    """Channel and purpose routing determination for a Jira brief."""

    target_channel: str = "WHATSAPP"  # WHATSAPP, RCS, SMS, MULTI_CHANNEL
    channel_confidence: float = 1.0
    campaign_purpose: str = (
        "LOAN_OFFER"  # LOAN_OFFER, EMI_COLLECTION, TRANSACTION_SERVICE, AUTHENTICATION, GENERAL_ANNOUNCEMENT
    )
    purpose_confidence: float = 1.0
    has_header: bool = False
    has_footer: bool = False
    has_cta: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedTemplateComponent:
    """Structured components extracted from a Jira description."""

    header_text: str | None = None
    header_format: str = "TEXT"  # TEXT, IMAGE, VIDEO, DOCUMENT, NONE
    body_text: str = ""
    footer_text: str | None = None
    button_text: str | None = None
    button_url: str | None = None
    button_type: str | None = None  # URL, PHONE_NUMBER, QUICK_REPLY

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JiraExtractionResult:
    """Complete result of semantic Jira brief extraction."""

    routing: JiraRoutingDecision = field(default_factory=JiraRoutingDecision)
    template: ExtractedTemplateComponent = field(default_factory=ExtractedTemplateComponent)
    variables: list[str] = field(default_factory=list)
    sample_values: list[str] = field(default_factory=list)
    raw_text: str = ""
    ai_extracted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "routing": self.routing.to_dict(),
            "template": self.template.to_dict(),
            "variables": self.variables,
            "sample_values": self.sample_values,
            "raw_text": self.raw_text,
            "ai_extracted": self.ai_extracted,
        }


def _segment_text_components(raw_text: str) -> ExtractedTemplateComponent:
    """
    Parse free-form text into Header, Body, Footer, and Button components using structural patterns.
    Handles explicit labels ('Header:', 'Body:', 'Footer:', 'Button:') and bulleted structures.
    """
    header_text: str | None = None
    footer_text: str | None = None
    button_text: str | None = None
    button_url: str | None = None
    button_type: str | None = None

    text = raw_text.strip()

    # 1. Look for explicit Header block
    h_match = re.search(
        r"(?:^|\n)\s*(?:Header|Title|Headline)\s*[:\-–]\s*(.+?)(?=\n\s*(?:Body|Message|Content|Footer|Button|CTA)|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if h_match:
        header_text = h_match.group(1).strip()
        header_text = re.sub(r"\n+", " ", header_text).strip()

    # 2. Look for explicit Footer block
    f_match = re.search(
        r"(?:^|\n)\s*(?:Footer|Disclaimer|T&C)\s*[:\-–]\s*(.+?)(?=\n\s*(?:Button|CTA|Action)|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if f_match:
        footer_text = f_match.group(1).strip()
        footer_text = re.sub(r"\n+", " ", footer_text).strip()

    # 3. Look for explicit Button / CTA block
    b_match = re.search(r"(?:^|\n)\s*(?:Button|CTA|Action|Link)\s*[:\-–]\s*(.+?)$", text, re.IGNORECASE | re.DOTALL)
    if b_match:
        b_content = b_match.group(1).strip()
        # Parse 'Text -> URL' or 'Text | URL' or URL
        url_match = re.search(r"https?://[^\s]+", b_content)
        if url_match:
            button_url = url_match.group(0).rstrip(".,)")
            parts = re.split(r"\s*(?:->|\||–|-|:)\s*", b_content.replace(button_url, ""))
            parts = [p.strip() for p in parts if p.strip()]
            button_text = parts[0] if parts else "Visit Website"
            button_type = "URL"
        else:
            button_text = b_content[:25]
            button_type = "QUICK_REPLY"

    # 4. Extract Body block
    b_body_match = re.search(
        r"(?:^|\n)\s*(?:Body|Message|Content|Text)\s*[:\-–]\s*(.+?)(?=\n\s*(?:Footer|Disclaimer|T&C|Button|CTA)|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if b_body_match:
        body_text = b_body_match.group(1).strip()
    else:
        # Strip out detected Header, Footer, and Button blocks from full text
        remaining = text
        if h_match:
            remaining = remaining.replace(h_match.group(0), "")
        if f_match:
            remaining = remaining.replace(f_match.group(0), "")
        if b_match:
            remaining = remaining.replace(b_match.group(0), "")

        # Remove polite introductory lines (e.g. 'Hi Team, please whitelist...')
        lines = remaining.strip().split("\n")
        filtered_lines = []
        for line in lines:
            llow = line.lower().strip()
            if llow.startswith(
                ("hi ", "hello ", "dear team", "please find", "please whitelist", "campaign:", "channel:")
            ):
                continue
            filtered_lines.append(line)
        body_text = "\n".join(filtered_lines).strip() or text

    return ExtractedTemplateComponent(
        header_text=header_text,
        header_format="TEXT" if header_text else "NONE",
        body_text=body_text,
        footer_text=footer_text,
        button_text=button_text,
        button_url=button_url,
        button_type=button_type,
    )


def route_jira_brief(
    raw_text: str,
    summary: str = "",
    allow_ai: bool = True,
) -> JiraRoutingDecision:
    """
    Determine target channel (WHATSAPP, RCS, SMS, MULTI_CHANNEL) and campaign purpose using TypeSafe System One.
    """
    full_context = f"Summary: {summary}\nDescription: {raw_text}".strip()
    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()

    # Rule-based fallback if offline or no key
    if not allow_ai or not api_key:
        lower = full_context.lower()
        if "rcs" in lower:
            chan = "RCS"
        elif "sms" in lower and "whatsapp" not in lower:
            chan = "SMS"
        elif "whatsapp" in lower or "wa" in lower:
            chan = "WHATSAPP"
        else:
            chan = "WHATSAPP"

        purpose = (
            "LOAN_OFFER" if any(w in lower for w in ("loan", "offer", "emi", "disburs")) else "GENERAL_ANNOUNCEMENT"
        )
        has_header = bool(re.search(r"\bheader\b", lower))
        has_footer = bool(re.search(r"\bfooter\b", lower))
        has_cta = bool(re.search(r"\b(button|cta|link)\b", lower))
        return JiraRoutingDecision(
            target_channel=chan,
            channel_confidence=0.8,
            campaign_purpose=purpose,
            purpose_confidence=0.8,
            has_header=has_header,
            has_footer=has_footer,
            has_cta=has_cta,
        )

    try:
        from typesafe_sdk import Choice, Noul, TypeSafeClient

        with TypeSafeClient(api_key=api_key) as client:
            res = client.system_one(
                state={"jira_brief": full_context},
                questions={
                    "target_channel": Choice(
                        instructions="Identify the primary messaging channel requested in the Jira brief.",
                        criteria={
                            "WHATSAPP": "WhatsApp template (WABA) with header, body, footer, or buttons",
                            "RCS": "RCS rich card or carousel messaging",
                            "SMS": "Standard SMS / DLT text message",
                            "MULTI_CHANNEL": "Explicitly mentions multiple channels (e.g. both WhatsApp and SMS)",
                        },
                    ),
                    "campaign_purpose": Choice(
                        instructions="Identify the business purpose of this messaging campaign.",
                        criteria={
                            "LOAN_OFFER": "Pre-approved loan offers, personal/home loan sales promotions",
                            "EMI_COLLECTION": "EMI due date reminders, overdue collection, payment alerts",
                            "TRANSACTION_SERVICE": "Account updates, disbursement confirmation, receipts",
                            "AUTHENTICATION": "OTP, login verification codes",
                            "GENERAL_ANNOUNCEMENT": "Brand updates, policy changes, general announcements",
                        },
                    ),
                    "has_header": Noul(instructions="Does the brief specify an explicit header line or banner?"),
                    "has_footer": Noul(instructions="Does the brief specify an explicit footer or disclaimer?"),
                    "has_cta": Noul(
                        instructions="Does the brief specify a call-to-action (CTA) button or action link?"
                    ),
                },
            )

        chan_choice = res.choices["target_channel"]
        purpose_choice = res.choices["campaign_purpose"]

        return JiraRoutingDecision(
            target_channel=str(chan_choice.choice).upper(),
            channel_confidence=float(chan_choice.confidence),
            campaign_purpose=str(purpose_choice.choice).upper(),
            purpose_confidence=float(purpose_choice.confidence),
            has_header=res.nouls["has_header"].noul >= 0.5,
            has_footer=res.nouls["has_footer"].noul >= 0.5,
            has_cta=res.nouls["has_cta"].noul >= 0.5,
        )
    except Exception as err:
        logger.warning("TypeSafe Jira brief routing failed, using rule-based fallback: %s", err)
        return route_jira_brief(raw_text, summary, allow_ai=False)


def generate_compliant_variable_samples(
    body_text: str,
    variables: list[str],
    allow_ai: bool = True,
) -> list[str]:
    """
    Generate calibrated, Meta-compliant sample values for variables ({{1}}, {{2}}, etc.)
    using TypeSafe Choice classification over surrounding sentence context in a single request.
    """
    if not variables:
        return []

    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()

    # Rule-based fallback if offline or no key
    if not allow_ai or not api_key:
        samples = []
        for v in variables:
            idx = int(re.sub(r"[^\d]", "", v) or "1")
            samples.append(f"Sample_{idx}")
        return samples

    try:
        from typesafe_sdk import Choice, TypeSafeClient

        # Build batched Choice questions for all variables in the template
        questions = {}
        for idx, var_name in enumerate(variables, start=1):
            q_key = f"var_{idx}"
            questions[q_key] = Choice(
                instructions=f"What semantic data type belongs in variable placeholder {var_name} given its surrounding context in the message?",
                criteria=VARIABLE_TYPE_CRITERIA,
            )

        with TypeSafeClient(api_key=api_key) as client:
            res = client.system_one(
                state={"template_text": body_text},
                questions=questions,
            )

        samples = []
        for idx in range(1, len(variables) + 1):
            q_key = f"var_{idx}"
            if q_key in res.choices:
                choice_val = str(res.choices[q_key].choice).upper()
                sample_val = META_COMPLIANT_SAMPLES.get(choice_val, f"Sample_{idx}")
                samples.append(sample_val)
            else:
                samples.append(f"Sample_{idx}")

        return samples

    except Exception as err:
        logger.warning("TypeSafe variable sample generation failed, using fallback: %s", err)
        return generate_compliant_variable_samples(body_text, variables, allow_ai=False)


def extract_template_from_jira_text(
    raw_text: str,
    summary: str = "",
    allow_ai: bool = True,
) -> JiraExtractionResult:
    """
    Extract structured template components, routing decision, and variable samples
    from free-form Jira description text.
    """
    if not raw_text or not raw_text.strip():
        return JiraExtractionResult(raw_text=raw_text)

    # 1. Structural Component Segmentation (Header, Body, Footer, Button)
    component = _segment_text_components(raw_text)

    # 2. Variable Normalization (convert <name>, [amount], etc. into {{1}}, {{2}})
    from briefing_parser import normalize_placeholders

    norm_body, _ = normalize_placeholders(component.body_text)
    component.body_text = norm_body
    var_tokens = re.findall(r"\{\{\d+\}\}", norm_body)

    # 3. Channel & Purpose Routing
    routing = route_jira_brief(raw_text, summary=summary, allow_ai=allow_ai)

    # 4. Calibrated Variable Sampling with TypeSafe
    sample_values = generate_compliant_variable_samples(norm_body, var_tokens, allow_ai=allow_ai)

    return JiraExtractionResult(
        routing=routing,
        template=component,
        variables=var_tokens,
        sample_values=sample_values,
        raw_text=raw_text,
        ai_extracted=allow_ai and bool(os.getenv("TYPESAFE_API_KEY")),
    )
