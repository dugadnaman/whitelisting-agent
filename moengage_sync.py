"""
MoEngage RCS Template Management Synchronization Service.
Automates template registration directly into MoEngage Settings:
https://dashboard-03.moengage.com/v4/settings-v2/channels/sms-and-rcs/rcs-template-management
Registers Karix approved RCS templates with provider='karix', sender, card title,
body, media URL, and open URL suggestions.
"""

import logging
import os
import re
from typing import Any

import requests
from config import _load_env_file
logger = logging.getLogger(__name__)

MOENGAGE_API_BASE = "https://dashboard-03.moengage.com"

# Default sender ID for TCFSL Promotional in MoEngage
DEFAULT_TCFSL_PROMO_SENDER_ID = "68888420892e852255fca466"


def get_moengage_auth_headers() -> dict[str, str]:
    """Load MoEngage dashboard Bearer authorization token and cookies."""
    _load_env_file()
    token = (
        os.environ.get("MOENGAGE_BEARER_TOKEN")
        or os.environ.get("MOE_AUTH_TOKEN")
        or ""
    ).strip()
    cookie = os.environ.get("MOENGAGE_COOKIE") or ""

    if not token:
        raise OSError(
            "Missing MoEngage Bearer token. Configure MOENGAGE_BEARER_TOKEN in Settings or .env."
        )

    auth_val = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    headers = {
        "authorization": auth_val,
        "content-type": "application/json",
        "origin": MOENGAGE_API_BASE,
        "page": "settings-v2/channels/sms-and-rcs/rcs-template-management/create",
        "accept": "application/json",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    }
    if cookie:
        headers["cookie"] = cookie
    return headers


def list_moengage_rcs_templates() -> list[dict[str, Any]]:
    """Fetch existing registered RCS templates from MoEngage settings."""
    headers = get_moengage_auth_headers()
    url = f"{MOENGAGE_API_BASE}/template_metadata?template_type=rcs"
    resp = requests.get(url, headers=headers, timeout=20)
    if not resp.ok:
        raise RuntimeError(f"MoEngage template_metadata list failed ({resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    return data.get("data", [])


def create_moengage_rcs_template(
    template_name: str,
    template_id: str,
    card_title: str,
    card_description: str,
    media_url: str | None = None,
    cta_text: str = "Explore Now",
    cta_url: str = "https://www.tatacapital.com",
    sender_id: str = DEFAULT_TCFSL_PROMO_SENDER_ID,
) -> dict[str, Any]:
    """
    Register an RCS template directly into MoEngage RCS Template Management:
    POST https://dashboard-03.moengage.com/template_metadata
    """
    clean_name = re.sub(r"[^\w\-.]", "_", template_name.strip()).strip("_")
    clean_id = str(template_id or clean_name).strip()

    suggestions = []
    if cta_url:
        suggestions.append({
            "type": "OPEN_URL",
            "text": (cta_text or "Check Offer")[:25],
            "postback_data": (cta_text or "Check Offer")[:120],
            "url": cta_url.strip(),
            "application": "BROWSER",
            "webview_view_mode": "",
        })

    # Default fallback media if none supplied
    clean_media_url = media_url.strip() if media_url else "https://rm.virbm.com/Uv9tdd0KNADbq3pX/816429043c23458ab9edc04a903251d8.jpg"

    payload = {
        "template_type": "rcs",
        "name": clean_name,
        "display_name": clean_name,
        "description": "",
        "meta_data": {
            "rcs_template_type": "card",
            "template_id": clean_id,
            "sender_ids": [sender_id],
            "provider": "karix",
            "is_multi_button": False,
            "data": {
                "orientation": "VERTICAL",
                "height": "MEDIUM",
                "title": (card_title or clean_name)[:200],
                "description": card_description[:2000],
                "media": {
                    "content_type": "contenttype",
                    "type": "IMAGE",
                    "source": "URL",
                    "media_type": "STATIC",
                    "media_url": clean_media_url,
                },
                "suggestions": suggestions,
            },
        },
    }

    headers = get_moengage_auth_headers()
    url = f"{MOENGAGE_API_BASE}/template_metadata"

    logger.info("Registering RCS template '%s' (ID: %s) to MoEngage Settings...", clean_name, clean_id)
    resp = requests.post(url, headers=headers, json=payload, timeout=25)

    if not resp.ok:
        logger.error("MoEngage create template failed (%d): %s", resp.status_code, resp.text[:300])
        raise RuntimeError(f"MoEngage template creation HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    if not data.get("status"):
        err_reason = data.get("reason") or str(data)
        raise RuntimeError(f"MoEngage template creation rejected: {err_reason}")

    moe_id = data.get("data", {}).get("id")
    logger.info("RCS template '%s' successfully created in MoEngage (ID: %s)", clean_name, moe_id)
    return {
        "ok": True,
        "name": clean_name,
        "template_id": clean_id,
        "moengage_id": moe_id,
        "created_at": data.get("data", {}).get("created_at"),
    }
