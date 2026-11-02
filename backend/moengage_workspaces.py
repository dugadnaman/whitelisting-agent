"""Explicit, account-owned WhatsApp workspace discovery and isolated portal sessions."""

from __future__ import annotations

import re
from typing import Any

import requests

from moengage_drafts import authorize_draft_account
from moengage_sync import check_moengage_session, get_moengage_config

_PORTAL_ID = re.compile(r"[a-fA-F0-9]{24}\Z")
_ACCOUNT_ID = re.compile(r"[a-z][a-z0-9_]*\Z")


def _workspace_registry(account: str) -> list[dict[str, str]]:
    # DraftCreation imports this module for row routing; keep catalog loading lazy.
    from moengage_draft_creation import load_server_catalog

    if not isinstance(account, str) or not _ACCOUNT_ID.fullmatch(account):
        raise ValueError("Invalid canonical account ID")
    catalog = load_server_catalog(account)
    if catalog.get("account") != account:
        raise PermissionError("Workspace registry does not belong to this account")
    rows = catalog.get("whatsapp_workspaces", [])
    if not isinstance(rows, list):
        raise ValueError("Invalid account WhatsApp workspace registry")
    choices = []
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                or not _PORTAL_ID.fullmatch(row["id"])
                or not isinstance(row.get("name"), str) or not row["name"].strip()):
            raise ValueError("Invalid account WhatsApp workspace registry")
        choices.append({"id": row["id"], "name": row["name"]})
    if (len({row["id"] for row in choices}) != len(choices)
            or len({row["name"] for row in choices}) != len(choices)):
        raise ValueError("Ambiguous account WhatsApp workspace registry")
    return choices


def list_workspace_choices(account: str, user: dict[str, Any]) -> list[dict[str, str]]:
    authorize_draft_account(account, user)
    return _workspace_registry(account)


def _select_workspace(choices: list[dict[str, str]], selector: str) -> dict[str, str]:
    if not isinstance(selector, str) or not selector.strip():
        raise ValueError("WhatsApp requires an explicit workspace_id or exact workspace name")
    matches = [row for row in choices if selector in (row["id"], row["name"])]
    if len(matches) != 1:
        raise PermissionError("WhatsApp workspace is not registered for this account")
    return matches[0]


def _workspace_selector(row: dict[str, Any]) -> str:
    workspace_id, workspace = row.get("workspace_id"), row.get("workspace")
    if workspace_id is not None and not isinstance(workspace_id, str):
        raise ValueError("WhatsApp workspace_id must be a portal workspace ID")
    if workspace is not None and not isinstance(workspace, str):
        raise ValueError("WhatsApp workspace must be an exact workspace name")
    if workspace_id:
        if not _PORTAL_ID.fullmatch(workspace_id):
            raise ValueError("WhatsApp workspace_id must be a portal workspace ID")
        return workspace_id
    if workspace:
        return workspace
    raise ValueError("WhatsApp requires an explicit workspace_id or exact workspace name")


def portal_session(account: str, workspace_id: str) -> dict[str, Any]:
    """Bind an account snapshot to one authorized portal ID without saving mutations."""
    choices = _workspace_registry(account)
    if (not isinstance(workspace_id, str) or not _PORTAL_ID.fullmatch(workspace_id)
            or not any(row["id"] == workspace_id for row in choices)):
        raise PermissionError("WhatsApp workspace is not registered for this account")
    config = get_moengage_config(account)
    token = str(config.get("bearer_token") or "").strip()
    token = re.sub(r"^Bearer\s+", "", token, flags=re.IGNORECASE)
    if not token:
        raise PermissionError("Account-specific MoEngage portal session required")
    try:
        bound = check_moengage_session(
            account, bearer_token=token, refresh_token=str(config.get("refresh_token") or ""),
            cookie=str(config.get("cookie") or ""), base_url=str(config.get("base_url") or "").rstrip("/"),
            workspace_id=workspace_id,
        )
    except (ValueError, requests.RequestException):
        raise PermissionError("MoEngage could not authorize this account's selected workspace; reconnect its session") from None
    if bound.get("workspace_id") != workspace_id or not bound.get("bearer_token"):
        raise PermissionError("MoEngage session does not match the selected workspace")
    base_url = bound["base_url"].rstrip("/")
    headers = {
        "authorization": "Bearer " + bound["bearer_token"],
        "content-type": "application/json", "accept": "application/json",
        "origin": base_url, "page": "whatsapp/create/one-time/",
    }
    if bound.get("cookie"):
        headers["cookie"] = bound["cookie"]
    if bound.get("refresh_token"):
        headers["refreshtoken"] = bound["refresh_token"]
    return {"base_url": base_url, "headers": headers}


def _sender_inventory(settings: Any) -> list[dict[str, str]]:
    if not isinstance(settings, dict):
        raise ValueError("MoEngage WhatsApp sender inventory unavailable")
    senders = []
    for provider, entries in settings.items():
        if not isinstance(provider, str) or not provider or not isinstance(entries, dict):
            raise ValueError("MoEngage returned invalid WhatsApp sender settings")
        for sender_id, sender in entries.items():
            if (not isinstance(sender, dict) or not isinstance(sender_id, str)
                    or not sender_id or not isinstance(sender.get("sender_name"), str)
                    or not sender["sender_name"].strip()):
                raise ValueError("MoEngage returned invalid WhatsApp sender settings")
            number = str(sender.get("whatsapp_business_no") or "")
            # Only public selection fields survive the provider's credential-bearing settings.
            senders.append({"sender_id": sender_id, "name": sender["sender_name"],
                            "number": number, "provider": provider.upper(),
                            "sender_name": sender["sender_name"], "phone_number": number, "portal_provider": provider})
    if len({row["sender_id"] for row in senders}) != len(senders):
        raise ValueError("MoEngage returned ambiguous WhatsApp sender identities")
    return senders


def _approved_templates(items: Any, senders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("MoEngage WhatsApp template inventory unavailable")
    templates = []
    for item in items:
        metadata = item.get("meta_data")
        if (not isinstance(metadata, dict) or item.get("status") != "ACTIVE"
                or metadata.get("state") != "APPROVED"
                or not isinstance(metadata.get("sender_ids"), list)
                or not isinstance(metadata.get("provider"), str)):
            continue
        provider = metadata["provider"].upper()
        sender_ids = [sender["sender_id"] for sender in senders
                      if sender["provider"].upper() == provider
                      and sender["sender_id"] in metadata["sender_ids"]]
        if not sender_ids:
            continue
        identity, name = item.get("id"), item.get("name") or item.get("display_name")
        if (not isinstance(identity, str) or not _PORTAL_ID.fullmatch(identity)
                or not isinstance(name, str) or not name.strip()):
            raise ValueError("MoEngage returned invalid WhatsApp template metadata")
        content = metadata.get("content")
        body = content.get("body") if isinstance(content, dict) else None
        templates.append({"id": identity, "name": name,
                          "display_name": item["display_name"] if isinstance(item.get("display_name"), str) else name,
                          "body": body if isinstance(body, str) else "",
                          "sender_ids": sender_ids, "provider": provider})
    if len({row["id"] for row in templates}) != len(templates):
        raise ValueError("MoEngage returned ambiguous WhatsApp template identities")
    return templates


def _metadata_request(session: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    try:
        response = requests.request(
            method, session["base_url"] + path, headers=session["headers"].copy(),
            json={} if method == "POST" else None, timeout=25, allow_redirects=False,
        )
        if response.status_code != 200:
            raise ValueError("MoEngage workspace metadata unavailable")
        data = response.json()
    except (requests.RequestException, ValueError):
        raise ValueError("MoEngage workspace metadata unavailable; reconnect this workspace session") from None
    if (not isinstance(data, dict) or data.get("success") is False
            or data.get("status") in ("failure", "failed", "error")
            or ("code" in data and str(data["code"]) != "200")
            or (data.get("loggedIn") is False and not (
                str(data.get("code")) == "200" and data.get("status") == "success"))):
        raise ValueError("MoEngage returned invalid workspace metadata")
    return data


def workspace_catalog(account: str, user: dict[str, Any], selector: str) -> dict[str, Any]:
    workspace = _select_workspace(list_workspace_choices(account, user), selector)
    session = portal_session(account, workspace["id"])
    senders = _sender_inventory(_metadata_request(session, "GET", "/whatsapp/settings").get("sender_settings"))
    templates = _approved_templates(
        _metadata_request(session, "GET", "/template_metadata?template_type=whatsapp").get("data"), senders,
    )
    rows = _metadata_request(session, "POST", "/v2/custom-segments/dashboard?archived=false").get("custom_segments")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("MoEngage saved segment inventory unavailable")
    segments = []
    for row in rows:
        if row.get("deleted") is True or row.get("archived") is True:
            continue
        if (any(flag in row and type(row[flag]) is not bool for flag in ("deleted", "archived"))
                or not isinstance(row.get("id"), str) or not _PORTAL_ID.fullmatch(row["id"])
                or not isinstance(row.get("name"), str) or not row["name"].strip()):
            raise ValueError("MoEngage returned invalid saved segment metadata")
        segments.append({"id": row["id"], "name": row["name"]})
    if len({row["id"] for row in segments}) != len(segments):
        raise ValueError("MoEngage returned ambiguous saved segment identities")
    return {"account": account, "workspace_id": workspace["id"], "workspace_name": workspace["name"],
            "segments": segments, "whatsapp_senders": senders, "whatsapp_templates": templates}


def catalog_for_row(account: str, user: dict[str, Any], row: dict[str, Any],
                    default_catalog: dict[str, Any]) -> dict[str, Any]:
    authorize_draft_account(account, user)
    if str(row.get("channel") or "").strip().upper() != "WHATSAPP":
        return default_catalog
    selector = _workspace_selector(row)
    if row.get("workspace_id") and row.get("workspace"):
        workspace = _select_workspace(list_workspace_choices(account, user), selector)
        if row["workspace"] != workspace["name"]:
            raise ValueError("WhatsApp workspace_id and workspace name disagree")
    return workspace_catalog(account, user, selector)
