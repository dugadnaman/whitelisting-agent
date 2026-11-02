"""
MoEngage RCS Template Management Synchronization Service.
Automates template registration directly into MoEngage Settings:
https://dashboard-03.moengage.com/v4/settings-v2/channels/sms-and-rcs/rcs-template-management
Registers Karix approved RCS templates with provider='karix', sender, card title,
body, media URL, and open URL suggestions.

Supports multiple workspaces with credentials resolved per account from encrypted
Auth Sync snapshots and settings, or exact account-specific environment defaults.
There is no cross-account credential fallback.
"""

import base64
import json
import logging
import os
import re
import time
from typing import Any

import requests

from config import _account_prefix, _load_env_file

logger = logging.getLogger(__name__)

MOENGAGE_API_BASE = "https://dashboard-03.moengage.com"



def get_moengage_config(account: str = "tata") -> dict[str, str]:
    """Resolve only this account's configured workspace and complete session snapshot."""
    from portal_sessions import load_session, load_settings

    _load_env_file()
    acc = account.strip().lower()
    prefix = _account_prefix(acc)
    settings = load_settings(acc, "moengage")
    snapshot = load_session(acc, "moengage")

    def value(suffix: str) -> str:
        key = f"{prefix}_MOENGAGE_{suffix}"
        return settings.get(key, os.environ.get(key, "")).strip()

    base_url = value("BASE_URL").rstrip("/")
    workspace_id = value("WORKSPACE_ID")
    token, cookie, refresh = value("BEARER_TOKEN"), value("COOKIE"), value("REFRESH_TOKEN")
    if snapshot:
        token = snapshot["bearer_token"]
        cookie = snapshot.get("cookie", "")
        refresh = snapshot.get("refresh_token", "")
    return {
        "base_url": base_url, "workspace_id": workspace_id,
        "bearer_token": token, "cookie": cookie, "refresh_token": refresh,
        "sender_id": value("SENDER_ID"), "prefix": prefix,
    }


def check_moengage_session(
    account: str, *, bearer_token: str, refresh_token: str, cookie: str,
    base_url: str, workspace_id: str, bind_workspace: bool = True,
) -> dict[str, str]:
    """Authorize the configured workspace, then bind the saved bearer to that exact app."""
    if not re.fullmatch(r"https://dashboard(?:-\d+)?\.moengage\.com", base_url):
        raise ValueError("A configured MoEngage dashboard HTTPS origin is required.")
    if not re.fullmatch(r"[A-Za-z0-9]{24}", workspace_id):
        raise ValueError("Configure the MoEngage dashboard workspace's exact 24-character alphanumeric ID.")
    headers = {
        "authorization": f"Bearer {bearer_token}", "refreshtoken": refresh_token,
        "cookie": cookie, "accept": "application/json", "origin": base_url,
    }
    try:
        response = requests.get(
            base_url + "/dash/auth/listApps", headers=headers, timeout=15, allow_redirects=False,
        )
        if not response.ok or 300 <= response.status_code < 400:
            raise ValueError("MoEngage refused the captured session.")
        data = response.json()
        if not isinstance(data, dict) or data.get("success") is False or data.get("status") in ("failed", "failure", "error"):
            raise ValueError("MoEngage rejected the captured session.")
        code = data.get("code")
        if code is not None and str(code) != "200":
            raise ValueError("MoEngage rejected the captured session.")
        if data.get("loggedIn") is False and not (str(code) == "200" and data.get("status") == "success"):
            raise ValueError("MoEngage session is not logged in.")
        apps = data.get("data")
        if not isinstance(apps, list):
            raise ValueError("MoEngage returned an unrecognized workspace inventory.")
        matches = [app for app in apps if isinstance(app, dict) and app.get("id") == workspace_id
                   and app.get("activated") is True and app.get("is_test") is False]
        if len(matches) != 1:
            raise ValueError("The configured workspace is not active and authorized by this MoEngage session.")
        if not bind_workspace:
            return {
                "bearer_token": bearer_token, "refresh_token": refresh_token, "cookie": cookie,
                "base_url": base_url, "workspace_id": workspace_id,
            }
        switched = requests.get(
            base_url + "/dash/auth/changeApp", headers=headers,
            params={"sls_enabled": "true", "app_id": workspace_id},
            timeout=15, allow_redirects=False,
        )
        if not switched.ok or 300 <= switched.status_code < 400:
            raise ValueError("MoEngage refused access to the configured workspace.")
        result = switched.json()
        if not isinstance(result, dict):
            raise ValueError("MoEngage returned an invalid workspace authorization.")
        selected = result.get("data") if isinstance(result, dict) else None
        token = selected.get("bearer") if isinstance(selected, dict) else None
        renewed = selected.get("refresh_token") if isinstance(selected, dict) else None
        if (result.get("code") != 200 or result.get("status") != "success"
                or not isinstance(token, str) or not token.strip()
                or selected.get("app_access_details") != "ALLOWED"):
            raise ValueError("MoEngage did not grant access to the configured workspace.")
        token = re.sub(r"^Bearer\s+", "", token.strip(), flags=re.IGNORECASE)
        if not token or any(ord(character) < 32 or ord(character) == 127 for character in token):
            raise ValueError("MoEngage returned invalid workspace credentials.")
        if renewed is not None and (not isinstance(renewed, str) or not renewed.strip()
                or any(ord(character) < 32 or ord(character) == 127 for character in renewed)):
            raise ValueError("MoEngage returned an invalid workspace refresh token.")
        return {
            "bearer_token": token, "refresh_token": renewed or refresh_token, "cookie": cookie,
            "base_url": base_url, "workspace_id": workspace_id,
        }
    except requests.RequestException as exc:
        raise ValueError("MoEngage session verification failed; reconnect this workspace.") from exc


def decode_moengage_token_expiry(token: str | None) -> dict[str, Any]:
    """Decode MoEngage JWT exp/iat claims into a human-readable expiry summary."""
    clean = (token or "").strip()
    if not clean:
        return {"present": False, "expired": True, "expires_at": None, "remaining_sec": 0}
    if clean.lower().startswith("bearer "):
        clean = clean[7:].strip()

    try:
        payload_b64 = clean.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = int(payload.get("exp", 0))
        now = int(time.time())
        return {
            "present": True,
            "expired": now >= exp,
            "expires_at": exp,
            "iat": int(payload.get("iat", 0)),
            "remaining_sec": max(0, exp - now),
            "remaining_min": round(max(0, exp - now) / 60, 1),
        }
    except Exception:
        # Token not in standard JWT form — treat as present but unknown expiry
        return {"present": True, "expired": False, "expires_at": None, "remaining_sec": None, "remaining_min": None}


def get_moengage_credentials(account: str = "tata") -> dict[str, Any]:
    """Return the current MoEngage credential state for an account including token expiry."""
    cfg = get_moengage_config(account)
    token = cfg["bearer_token"]
    expiry = decode_moengage_token_expiry(token)
    return {
        "account": account,
        "base_url": cfg["base_url"],
        "sender_id": cfg["sender_id"],
        "workspace_id": cfg["workspace_id"],
        "bearer_token": token,
        "cookie": cfg["cookie"],
        "refresh_token": cfg["refresh_token"],
        "has_token": bool(token),
        "has_cookie": bool(cfg["cookie"]),
        "has_refresh_token": bool(cfg["refresh_token"]),
        **expiry,
    }


def test_moengage_connection(
    account: str = "tata",
    token_override: str | None = None,
    cookie_override: str | None = None,
    base_url_override: str | None = None,
    sender_id_override: str | None = None,
) -> dict[str, Any]:
    """Verify MoEngage token validity for an account by querying MoEngage template metadata."""
    clean_token = (token_override or "").strip()
    if clean_token:
        expiry = decode_moengage_token_expiry(clean_token)
        cfg = get_moengage_config(account)
        creds = {
            "account": account,
            "base_url": (base_url_override or cfg["base_url"]).rstrip("/"),
            "sender_id": (sender_id_override or cfg["sender_id"]).strip(),
            "bearer_token": clean_token,
            "cookie": (cookie_override or cfg["cookie"]).strip(),
            "has_token": True,
            "has_cookie": bool(cookie_override or cfg["cookie"]),
            **expiry,
        }
        if expiry.get("expired") is True:
            return {
                "ok": False,
                "error": f"MoEngage Bearer token expired for {account}. Paste a fresh token (Settings -> MoEngage).",
                **creds,
            }
        auth_val = clean_token if clean_token.lower().startswith("bearer ") else f"Bearer {clean_token}"
        headers = {
            "authorization": auth_val,
            "content-type": "application/json",
            "origin": creds["base_url"],
            "page": "whatsapp/create/one-time",
            "accept": "application/json",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
        }
        if creds["cookie"]:
            headers["cookie"] = creds["cookie"]
        try:
            url = f"{creds['base_url']}/template_metadata?template_type=whatsapp"
            resp = requests.get(url, headers=headers, timeout=15)
            if not resp.ok:
                raise RuntimeError(f"MoEngage API rejected credentials ({resp.status_code}): {resp.text[:150]}")
            templates = resp.json().get("data", [])
            return {
                "ok": True,
                "template_count": len(templates),
                **creds,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                **creds,
            }

    creds = get_moengage_credentials(account)
    if creds.get("expired") is True:
        return {
            "ok": False,
            "error": f"MoEngage Bearer token expired for {account}. Paste a fresh token (Settings -> MoEngage).",
            **creds,
        }
    if not creds.get("has_token"):
        return {
            "ok": False,
            "error": f"Missing MoEngage Bearer token for {account}. Configure it in Settings -> MoEngage.",
            **creds,
        }

    try:
        templates = list_moengage_rcs_templates(account)
        return {
            "ok": True,
            "template_count": len(templates),
            **creds,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            **creds,
        }


def get_moengage_auth_headers(account: str = "tata") -> dict[str, str]:
    """Build MoEngage request headers for an account's workspace."""
    cfg = get_moengage_config(account)
    token = cfg["bearer_token"]

    if not token:
        raise OSError(f"Missing MoEngage Bearer token for {account}. Configure it in Settings -> MoEngage.")

    expiry = decode_moengage_token_expiry(token)
    if expiry.get("expired") is True:
        raise OSError(f"MoEngage Bearer token for {account} has expired. Paste a fresh token (Settings -> MoEngage).")

    auth_val = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    headers = {
        "authorization": auth_val,
        "content-type": "application/json",
        "origin": cfg["base_url"],
        "page": "settings-v2/channels/sms-and-rcs/rcs-template-management/create",
        "accept": "application/json",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    }
    if cfg["cookie"]:
        headers["cookie"] = cfg["cookie"]
    if cfg["refresh_token"]:
        headers["refreshtoken"] = cfg["refresh_token"]
    return headers


def list_moengage_rcs_templates(account: str = "tata") -> list[dict[str, Any]]:
    """Fetch existing registered RCS templates from an account's MoEngage workspace."""
    cfg = get_moengage_config(account)
    headers = get_moengage_auth_headers(account)
    url = f"{cfg['base_url']}/template_metadata?template_type=rcs"
    resp = requests.get(url, headers=headers, timeout=20)
    if not resp.ok:
        raise RuntimeError(f"MoEngage template_metadata list failed ({resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    return data.get("data", [])


def _resolve_rcs_sender(
    account: str, cfg: dict[str, str], headers: dict[str, str], sender_id: str | None,
) -> str:
    """Resolve a bot ID, sender name or record ID against this workspace's Karix senders."""
    from rcs_config import get_rcs_bot_id

    selected = (cfg["sender_id"] or sender_id or get_rcs_bot_id(account)).strip()
    resp = requests.get(f"{cfg['base_url']}/v2/settings/sms?api=1", headers=headers, timeout=20)
    if not resp.ok:
        raise RuntimeError(f"MoEngage RCS sender lookup failed (HTTP {resp.status_code})")
    senders = resp.json().get("rcs_sender_settings", {}).get("karix", {})
    if not isinstance(senders, dict):
        raise ValueError("MoEngage returned invalid Karix RCS sender settings")
    if selected in senders:
        return selected
    matches = [
        record_id for record_id, sender in senders.items()
        if isinstance(sender, dict) and (
            sender.get("sender_id") == selected
            or str(sender.get("sender_name") or "").casefold() == selected.casefold()
        )
    ]
    if len(matches) != 1:
        raise ValueError(
            f"MoEngage RCS sender '{selected}' is missing or ambiguous for '{account}'. "
            "Configure this account's MOENGAGE_SENDER_ID with a sender name or record ID."
        )
    return matches[0]


def _normalize_rcs_placeholders(text: str) -> str:
    """Convert Karix [variables], preserving existing MoEngage tags and Markdown links."""
    return re.sub(
        r"\{\{[\s\S]*?\}\}|\[([^\[\]\r\n]+)\](?!\()",
        lambda match: "{{" + match[1].strip() + "}}" if match[1] is not None else match[0],
        text,
    )


def create_moengage_rcs_template(
    template_name: str,
    template_id: str,
    card_title: str,
    card_description: str,
    media_url: str | None = None,
    cta_text: str = "Explore Now",
    cta_url: str = "https://www.tatacapital.com",
    sender_id: str | None = None,
    account: str = "tata",
    template_type: str = "card",
    carousel_cards: list[dict[str, Any]] | None = None,
    width: str = "MEDIUM",
    height: str = "MEDIUM",
) -> dict[str, Any]:
    """
    Register an RCS template into an account's MoEngage RCS Template Management:
    POST {base_url}/template_metadata
    """
    cfg = get_moengage_config(account)
    clean_name = re.sub(r"[^\w\-.]", "_", template_name.strip()).strip("_")
    # In MoEngage, template ID and template name are always the exact same
    clean_id = clean_name

    headers = get_moengage_auth_headers(account)
    resolved_sender = _resolve_rcs_sender(account, cfg, headers, sender_id)

    resolved_cta_url = (cta_url or "").strip()
    if not resolved_cta_url or resolved_cta_url in ("https://u3.mnge.co/", "https://www.tatacapital.com"):
        if account.lower() == "apparel":
            resolved_cta_url = "https://www.randbfashion.in/randbfashion-Store-Locater.html"
        else:
            resolved_cta_url = "https://www.tatacapital.com"

    suggestions = []
    if resolved_cta_url:
        resolved_cta_text = (cta_text or ("Visit Store" if account.lower() == "apparel" else "Explore Now"))[:25]
        suggestions.append(
            {
                "type": "OPEN_URL",
                "text": resolved_cta_text,
                "postback_data": resolved_cta_text[:120],
                "url": resolved_cta_url.strip(),
                "application": "BROWSER",
                "webview_view_mode": "",
            }
        )

    clean_media_url = (media_url or "").strip()
    if not clean_media_url:
        if account.lower() == "apparel":
            bot_tag = sender_id or "P7hzkqCcW3x96I6T"
            clean_media_url = f"https://rm.virbm.com/{bot_tag}/d11c5b30238a401da9d653e48936045e.jpeg"
        else:
            clean_media_url = "https://rm.virbm.com/Uv9tdd0KNADbq3pX/816429043c23458ab9edc04a903251d8.jpg"

    is_carousel = (template_type or "").lower() == "carousel" or bool(carousel_cards and len(carousel_cards) >= 2)

    if is_carousel and carousel_cards:
        cards_payload = []
        for idx, card in enumerate(carousel_cards, 1):
            c_title = (card.get("cardTitle") or card.get("title") or card.get("card_title") or f"{clean_name} {idx}")[:200]
            c_desc = (card.get("cardDescription") or card.get("description") or card.get("card_description") or card.get("body") or "")[:2000]
            c_media = card.get("mediaUrl") or card.get("media_url") or clean_media_url

            card_suggs = []
            raw_suggs = card.get("suggestions", [])
            if raw_suggs and isinstance(raw_suggs, list):
                for s in raw_suggs:
                    s_type = s.get("suggestionType") or s.get("type", "url_action")
                    s_text = (s.get("text") or s.get("postbackData") or s.get("postback_data") or "Explore")[:25]
                    s_url = s.get("url") or resolved_cta_url
                    if s_type in ("url_action", "OPEN_URL") or s.get("url"):
                        card_suggs.append({
                            "type": "OPEN_URL",
                            "text": s_text,
                            "postback_data": s.get("postbackData") or s_text,
                            "url": s_url.strip(),
                            "application": "BROWSER",
                            "webview_view_mode": "",
                        })
                    elif s_type in ("dialer_action", "DIAL_PHONE") or s.get("phoneNumber"):
                        card_suggs.append({
                            "type": "DIAL_PHONE",
                            "text": s_text,
                            "postback_data": s.get("postbackData") or s_text,
                            "phone_number": s.get("phoneNumber") or s.get("phone_number") or "+919999999999",
                        })
                    else:
                        card_suggs.append({
                            "type": "REPLY",
                            "text": s_text,
                            "postback_data": s.get("postbackData") or s_text,
                        })

            if not card_suggs and resolved_cta_url:
                card_suggs.append({
                    "type": "OPEN_URL",
                    "text": resolved_cta_text,
                    "postback_data": resolved_cta_text[:120],
                    "url": resolved_cta_url.strip(),
                    "application": "BROWSER",
                    "webview_view_mode": "",
                })

            card_obj = {
                "title": c_title,
                "card_title": c_title,
                "cardTitle": c_title,
                "description": c_desc,
                "card_description": c_desc,
                "cardDescription": c_desc,
                "media": {
                    "content_type": "contenttype",
                    "type": "IMAGE",
                    "source": "URL",
                    "media_type": "STATIC",
                    "media_url": c_media,
                },
                "suggestions": card_suggs[:4],
            }
            cards_payload.append(card_obj)

        payload = {
            "template_type": "rcs",
            "name": clean_name,
            "display_name": clean_name,
            "description": "",
            "meta_data": {
                "rcs_template_type": "carousel",
                "template_id": clean_id,
                "sender_ids": [resolved_sender],
                "provider": "karix",
                "is_multi_button": False,
                "data": {
                    "width": width or "MEDIUM",
                    "card_width": width or "MEDIUM",
                    "height": height or "MEDIUM",
                    "media_height": height or "MEDIUM",
                    "cards": cards_payload,
                    "carouselCard": cards_payload,
                },
            },
        }
    else:
        payload = {
            "template_type": "rcs",
            "name": clean_name,
            "display_name": clean_name,
            "description": "",
            "meta_data": {
                "rcs_template_type": "card",
                "template_id": clean_id,
                "sender_ids": [resolved_sender],
                "provider": "karix",
                "is_multi_button": False,
                "data": {
                    "orientation": "VERTICAL",
                    "height": height or "MEDIUM",
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

    # All entrypoints (single, selected and inventory sync) share this conversion.
    content = payload["meta_data"]["data"]
    for card in content.get("cards", [content]):
        for field in ("title", "card_title", "cardTitle", "description", "card_description", "cardDescription"):
            if field in card:
                card[field] = _normalize_rcs_placeholders(card[field])
        for suggestion in card.get("suggestions", []):
            for field in ("text", "postback_data", "url"):
                if field in suggestion:
                    suggestion[field] = _normalize_rcs_placeholders(suggestion[field])
    url = f"{cfg['base_url']}/template_metadata"

    logger.info("Registering RCS template '%s' (ID: %s) to MoEngage [%s]...", clean_name, clean_id, account)
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


def _extract_rcs_media_url(vi_template: dict[str, Any]) -> str | None:
    """Pull the media URL from a Karix viTemplate standalone/carousel card."""
    card = vi_template.get("standaloneCard") or {}
    if not card and vi_template.get("carouselCard"):
        cards = vi_template.get("carouselCard", [])
        card = cards[0] if cards else {}
    if card.get("mediaUrl"):
        return str(card["mediaUrl"])
    if card.get("media_url"):
        return str(card["media_url"])
    if vi_template.get("mediaUrl"):
        return str(vi_template["mediaUrl"])
    if vi_template.get("media_url"):
        return str(vi_template["media_url"])
    return None

def sync_karix_rcs_to_moengage(
    account: str = "tata",
    semantic_dedup: bool = True,
    resolve_attributes: bool = True,
) -> dict[str, Any]:
    """
    Pull already-approved RCS templates from Karix for an account and register
    them in that account's MoEngage workspace.
    Features:
    - Semantic Duplicate Detection: Skips templates already in MoEngage even if name differs slightly.
    - MoEngage Attribute Resolver: Maps positional {{1}}, {{2}} to verified MoEngage personalization tags.
    """
    from rcs_client import fetch_rcs_templates

    try:
        karix_templates = fetch_rcs_templates(client=account)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Could not read Karix RCS templates for '{account}': {exc}",
            "account": account,
        }

    if not karix_templates:
        return {
            "ok": False,
            "error": f"No RCS templates found in Karix for account '{account}'. Check RCS bot ID / auth token.",
            "account": account,
        }

    existing = list_moengage_rcs_templates(account)
    existing_names = {str(t.get("name", "")).strip().lower() for t in existing}
    existing_ids = {str(t.get("meta_data", {}).get("template_id", "")).strip().lower() for t in existing}

    created: list[dict[str, Any]] = []
    skipped: list[str] = []
    errors: list[dict[str, Any]] = []

    for lt in karix_templates:
        vi = lt.get("viTemplate", {})
        name = str(vi.get("name") or lt.get("templateId", "")).strip()
        template_id = str(lt.get("templateId", "")).strip()
        status = str(lt.get("status", "")).upper()

        # Only sync approved/active templates
        if status in ("REJECTED", "FAILED", "INACTIVE", "REVOKED"):
            skipped.append(f"{name} ({status})")
            continue

        # 1. Skip if exact name/ID already present in MoEngage
        if name.lower() in existing_names or (template_id and template_id.lower() in existing_ids):
            skipped.append(name)
            continue

        carousel_cards = vi.get("carouselCard", [])
        is_carousel = vi.get("type") == "carousel" or (bool(carousel_cards) and len(carousel_cards) >= 2)

        card = vi.get("standaloneCard") or {}
        if not card and carousel_cards:
            card = carousel_cards[0]

        card_title = card.get("cardTitle") or vi.get("textMessage", "")[:100] or name
        card_description = card.get("cardDescription") or vi.get("textMessage", "") or ""
        media_url = _extract_rcs_media_url(vi)
        # 2. Semantic Duplicate Detection via TypeSafe Noul
        if semantic_dedup and existing:
            try:
                from moengage_resolver import find_semantic_duplicate

                dup_res = find_semantic_duplicate(
                    candidate_name=name,
                    candidate_body=card_description,
                    existing_templates=existing,
                    threshold=0.85,
                    allow_ai=True,
                )
                if dup_res.is_duplicate:
                    logger.info(
                        "Skipping RCS template '%s' - semantic duplicate of MoEngage template '%s' (prob: %.2f)",
                        name,
                        dup_res.matched_template_name,
                        dup_res.probability,
                    )
                    skipped.append(f"{name} (Duplicate of '{dup_res.matched_template_name}')")
                    continue
            except Exception as ex:
                logger.debug("Semantic duplicate check bypassed: %s", ex)

        # 3. MoEngage Attribute Personalization Tag Resolver via TypeSafe Choice
        if resolve_attributes:
            if is_carousel and carousel_cards:
                for c in carousel_cards:
                    c_desc = c.get("cardDescription", "")
                    if re.search(r"\{\{\d+\}\}", c_desc) or re.search(r"\[\d+\]", c_desc):
                        try:
                            from moengage_resolver import resolve_moengage_attributes

                            trans = resolve_moengage_attributes(c_desc, allow_ai=True)
                            c["cardDescription"] = trans.translated_text
                        except Exception as ex:
                            logger.debug("MoEngage attribute resolution bypassed: %s", ex)
            elif re.search(r"\{\{\d+\}\}", card_description):
                try:
                    from moengage_resolver import resolve_moengage_attributes

                    trans = resolve_moengage_attributes(card_description, allow_ai=True)
                    card_description = trans.translated_text
                except Exception as ex:
                    logger.debug("MoEngage attribute resolution bypassed: %s", ex)

        # CTA from first suggestion if present
        suggestions = card.get("suggestions", []) or vi.get("suggestions", []) or []
        first_sugg = suggestions[0] if (suggestions and isinstance(suggestions, list)) else {}
        cta_text = str(
            first_sugg.get("text")
            or first_sugg.get("postbackData")
            or first_sugg.get("postback_data")
            or ("Visit Store" if account.lower() == "apparel" else "Explore Now")
        )
        cta_url = str(first_sugg.get("url") or "")

        try:
            res = create_moengage_rcs_template(
                template_name=name,
                template_id=name,
                card_title=card_title,
                card_description=card_description,
                media_url=media_url,
                cta_text=cta_text,
                cta_url=cta_url,
                account=account,
                sender_id=lt.get("botId") or vi.get("botId"),
                template_type="carousel" if is_carousel else "card",
                carousel_cards=carousel_cards if is_carousel else None,
                width=vi.get("width") or "MEDIUM",
                height=vi.get("height") or "MEDIUM",
            )
            created.append({
                    "template_name": name,
                    "template_id": template_id,
                    "moengage_id": res.get("moengage_id"),
                    "resolved_description": card_description,
                }
            )
        except Exception as exc:
            logger.warning("Failed to sync RCS template %s to MoEngage: %s", name, exc)
            errors.append({"template_name": name, "error": str(exc)})

    return {
        "ok": True,
        "account": account,
        "karix_total": len(karix_templates),
        "created": created,
        "created_count": len(created),
        "skipped": skipped,
        "skipped_count": len(skipped),
        "errors": errors,
        "error_count": len(errors),
    }
