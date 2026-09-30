"""
MoEngage Model Context Protocol (MCP) Client & OAuth 2.0 Connector.

Connects to MoEngage's hosted MCP server (`https://mcp.moengage.com`) using:
1. OAuth 2.0 Dynamic Client Registration (`https://moeauth.moengage.com/oauth2/register`)
   + Authorization Code with PKCE (`S256`) + 30-day Refresh Token rotation.
2. Direct MCP Bearer Token override (if pasted by an operator).
3. MCP Streamable HTTP / JSON-RPC 2.0 transport (`initialize`, `tools/list`, `tools/call`)
   supporting both `application/json` and `text/event-stream` (SSE) responses.

Also integrates with `moengage_ops_client.py` and Jira Briefs so campaigns, flows,
segments, analytics, and Email/Push campaign drafts can be managed via MCP.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.parse
from typing import Any

import requests

from config import _account_prefix, _load_env_file
from pathlib import Path

logger = logging.getLogger(__name__)


def update_env_vars(mapping: dict[str, str]) -> None:
    """Update live os.environ and credentials.json with MoEngage MCP keys."""
    for k, v in mapping.items():
        os.environ[k] = v
    try:
        cred_json_path = Path("credentials.json")
        saved_creds: dict[str, Any] = {}
        if cred_json_path.exists():
            try:
                saved_creds = json.loads(cred_json_path.read_text(encoding="utf-8"))
            except Exception:
                saved_creds = {}
        saved_creds.update(mapping)
        cred_json_path.write_text(json.dumps(saved_creds, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not write credentials.json: %s", exc)
logger = logging.getLogger(__name__)

MOENGAGE_MCP_URL = "https://mcp.moengage.com"
MOENGAGE_OAUTH_ISSUER = "https://moeauth.moengage.com"
MOENGAGE_OAUTH_REGISTER_URL = f"{MOENGAGE_OAUTH_ISSUER}/oauth2/register"
MOENGAGE_OAUTH_AUTHORIZE_URL = f"{MOENGAGE_OAUTH_ISSUER}/oauth2/authorize"
MOENGAGE_OAUTH_TOKEN_URL = f"{MOENGAGE_OAUTH_ISSUER}/oauth2/token"
MOENGAGE_MCP_SCOPES = "openid email profile offline_access campaigns:read"

_PENDING_OAUTH_STATES: dict[str, dict[str, Any]] = {}
_MCP_SESSIONS: dict[str, str] = {}


def _setting_key(account: str, suffix: str) -> str:
    prefix = _account_prefix(account or "tata")
    return f"{prefix}_MOENGAGE_MCP_{suffix}"


def get_mcp_config(account: str = "tata") -> dict[str, Any]:
    """Load MoEngage MCP server URL and OAuth/Bearer credentials for an account."""
    _load_env_file()
    prefix = _account_prefix(account or "tata")

    mcp_url = (
        os.environ.get(f"{prefix}_MOENGAGE_MCP_URL")
        or os.environ.get("MOENGAGE_MCP_URL")
        or MOENGAGE_MCP_URL
    ).rstrip("/")

    access_token = (
        os.environ.get(f"{prefix}_MOENGAGE_MCP_ACCESS_TOKEN")
        or os.environ.get("MOENGAGE_MCP_ACCESS_TOKEN")
        or ""
    ).strip()

    refresh_token = (
        os.environ.get(f"{prefix}_MOENGAGE_MCP_REFRESH_TOKEN")
        or os.environ.get("MOENGAGE_MCP_REFRESH_TOKEN")
        or ""
    ).strip()

    client_id = (
        os.environ.get(f"{prefix}_MOENGAGE_MCP_CLIENT_ID")
        or os.environ.get("MOENGAGE_MCP_CLIENT_ID")
        or ""
    ).strip()

    expires_at_raw = (
        os.environ.get(f"{prefix}_MOENGAGE_MCP_EXPIRES_AT")
        or os.environ.get("MOENGAGE_MCP_EXPIRES_AT")
        or "0"
    )
    try:
        expires_at = int(float(expires_at_raw))
    except Exception:
        expires_at = 0

    return {
        "account": account,
        "prefix": prefix,
        "mcp_url": mcp_url,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "client_id": client_id,
        "expires_at": expires_at,
    }


def save_mcp_tokens(
    account: str = "tata",
    access_token: str = "",
    refresh_token: str | None = None,
    client_id: str | None = None,
    expires_in: int | None = None,
    mcp_url: str | None = None,
) -> dict[str, Any]:
    """Persist MoEngage MCP access/refresh tokens to DB and .env."""
    prefix = _account_prefix(account or "tata")
    clean_access = access_token.strip()
    if clean_access.lower().startswith("bearer "):
        clean_access = clean_access[7:].strip()

    updates: dict[str, str] = {}
    if mcp_url:
        updates[f"{prefix}_MOENGAGE_MCP_URL"] = mcp_url.strip().rstrip("/")
        updates["MOENGAGE_MCP_URL"] = mcp_url.strip().rstrip("/")

    if clean_access:
        updates[f"{prefix}_MOENGAGE_MCP_ACCESS_TOKEN"] = clean_access
        updates["MOENGAGE_MCP_ACCESS_TOKEN"] = clean_access

    if refresh_token is not None and refresh_token.strip():
        updates[f"{prefix}_MOENGAGE_MCP_REFRESH_TOKEN"] = refresh_token.strip()
        updates["MOENGAGE_MCP_REFRESH_TOKEN"] = refresh_token.strip()

    if client_id is not None and client_id.strip():
        updates[f"{prefix}_MOENGAGE_MCP_CLIENT_ID"] = client_id.strip()
        updates["MOENGAGE_MCP_CLIENT_ID"] = client_id.strip()

    if expires_in:
        exp_ts = str(int(time.time()) + int(expires_in))
        updates[f"{prefix}_MOENGAGE_MCP_EXPIRES_AT"] = exp_ts
        updates["MOENGAGE_MCP_EXPIRES_AT"] = exp_ts

    if updates:
        for k, v in updates.items():
            os.environ[k] = v
        update_env_vars(updates)
    _MCP_SESSIONS.pop(prefix, None)
    return get_mcp_status(account)


def get_mcp_status(account: str = "tata") -> dict[str, Any]:
    """Return current MoEngage MCP configuration and connection state."""
    cfg = get_mcp_config(account)
    tok = cfg["access_token"]
    now = int(time.time())
    expires_at = cfg["expires_at"]

    # Also inspect JWT exp claim if present
    if tok and not expires_at:
        try:
            parts = tok.split(".")
            if len(parts) >= 2:
                b64 = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = json.loads(base64.urlsafe_b64decode(b64))
                if payload.get("exp"):
                    expires_at = int(payload["exp"])
        except Exception:
            pass

    expired = bool(expires_at and now >= expires_at and not cfg["refresh_token"])
    remaining_min = round(max(0, expires_at - now) / 60, 1) if expires_at else None

    return {
        "account": account,
        "mcp_url": cfg["mcp_url"],
        "has_token": bool(tok),
        "has_refresh_token": bool(cfg["refresh_token"]),
        "client_id": cfg["client_id"],
        "expired": expired,
        "expires_at": expires_at or None,
        "remaining_min": remaining_min,
        "mcp_config_json": {
            "mcpServers": {
                "moengage": {
                    "url": cfg["mcp_url"],
                }
            }
        },
    }


def start_mcp_oauth(
    redirect_uri: str,
    account: str = "tata",
    return_to: str = "/settings",
) -> dict[str, Any]:
    """
    Dynamically register an OAuth 2.0 public client with `https://moeauth.moengage.com/oauth2/register`
    and return the PKCE (`S256`) authorization URL for `https://mcp.moengage.com`.
    """
    reg_payload = {
        "client_name": "Karix Whitelisting Agent (MoEngage MCP)",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    resp = requests.post(MOENGAGE_OAUTH_REGISTER_URL, json=reg_payload, timeout=15)
    if not resp.ok:
        raise RuntimeError(f"MoEngage OAuth Dynamic Client Registration failed ({resp.status_code}): {resp.text[:300]}")

    reg_data = resp.json()
    client_id = reg_data.get("client_id")
    if not client_id:
        raise RuntimeError("MoEngage OAuth registration did not return a client_id.")

    # Generate PKCE code_verifier & S256 code_challenge
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    state = secrets.token_urlsafe(24)

    state_record = {
        "state": state,
        "client_id": client_id,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
        "account": account,
        "return_to": return_to,
        "created_at": int(time.time()),
    }
    _PENDING_OAUTH_STATES[state] = state_record
    try:
        update_env_vars({f"MOE_MCP_OAUTH_STATE_{state}": json.dumps(state_record)})
    except Exception:
        pass

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": MOENGAGE_MCP_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "resource": MOENGAGE_MCP_URL,
    }
    authorize_url = f"{MOENGAGE_OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    return {
        "ok": True,
        "authorize_url": authorize_url,
        "client_id": client_id,
        "state": state,
    }


def complete_mcp_oauth(code: str, state: str) -> dict[str, Any]:
    """Exchange OAuth 2.0 authorization code + PKCE verifier for MoEngage MCP access & refresh tokens."""
    state_record = _PENDING_OAUTH_STATES.pop(state, None)
    if not state_record:
        _load_env_file()
        raw = os.environ.get(f"MOE_MCP_OAUTH_STATE_{state}")
        if raw:
            try:
                state_record = json.loads(raw)
            except Exception:
                state_record = None
    if not state_record:
        raise RuntimeError("Invalid or expired OAuth state parameter. Please initiate Connect MoEngage MCP again.")

    token_data = {
        "grant_type": "authorization_code",
        "client_id": state_record["client_id"],
        "code": code,
        "redirect_uri": state_record["redirect_uri"],
        "code_verifier": state_record["code_verifier"],
        "resource": MOENGAGE_MCP_URL,
    }
    resp = requests.post(
        MOENGAGE_OAUTH_TOKEN_URL,
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        timeout=15,
    )
    if not resp.ok:
        raise RuntimeError(f"MoEngage OAuth token exchange failed ({resp.status_code}): {resp.text[:300]}")

    tok_json = resp.json()
    access_token = tok_json.get("access_token", "")
    refresh_token = tok_json.get("refresh_token", "")
    expires_in = tok_json.get("expires_in")
    account = state_record.get("account") or "tata"

    status = save_mcp_tokens(
        account=account,
        access_token=access_token,
        refresh_token=refresh_token,
        client_id=state_record["client_id"],
        expires_in=expires_in,
    )
    return {
        "ok": True,
        "account": account,
        "return_to": state_record.get("return_to") or "/settings",
        **status,
    }


def refresh_mcp_access_token(account: str = "tata") -> str | None:
    """Refresh the MoEngage MCP access token using the stored 30-day refresh_token."""
    cfg = get_mcp_config(account)
    if not cfg["refresh_token"] or not cfg["client_id"]:
        return None

    resp = requests.post(
        MOENGAGE_OAUTH_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": cfg["client_id"],
            "refresh_token": cfg["refresh_token"],
            "resource": cfg["mcp_url"],
        },
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        timeout=15,
    )
    if not resp.ok:
        logger.warning("MoEngage MCP token refresh failed (%d): %s", resp.status_code, resp.text[:200])
        return None

    tok_json = resp.json()
    new_access = tok_json.get("access_token", "")
    new_refresh = tok_json.get("refresh_token") or cfg["refresh_token"]
    expires_in = tok_json.get("expires_in")
    if new_access:
        save_mcp_tokens(
            account=account,
            access_token=new_access,
            refresh_token=new_refresh,
            client_id=cfg["client_id"],
            expires_in=expires_in,
        )
        return new_access
    return None


def _parse_mcp_http_response(resp: requests.Response) -> dict[str, Any]:
    """Parse either `application/json` or `text/event-stream` (SSE) JSON-RPC responses from MCP server."""
    ctype = (resp.headers.get("Content-Type") or "").lower()
    text = resp.text.strip()
    if "text/event-stream" in ctype or text.startswith("event:") or text.startswith("data:"):
        last_json: dict[str, Any] = {}
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("data:"):
                payload_str = s[5:].strip()
                if payload_str:
                    try:
                        parsed = json.loads(payload_str)
                        if isinstance(parsed, dict):
                            last_json = parsed
                    except Exception:
                        pass
        if last_json:
            return last_json
    try:
        return resp.json()
    except Exception:
        return {"raw": text}


def _mcp_rpc_request(
    method: str,
    params: dict[str, Any] | None = None,
    account: str = "tata",
    token_override: str | None = None,
    is_notification: bool = False,
) -> dict[str, Any]:
    """Send a JSON-RPC 2.0 request to `https://mcp.moengage.com` with automatic session & token refresh."""
    cfg = get_mcp_config(account)
    mcp_url = cfg["mcp_url"]
    token = (token_override or cfg["access_token"] or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    # Auto-refresh if expired and refresh_token is available
    now = int(time.time())
    if not token_override and cfg["expires_at"] and now >= (cfg["expires_at"] - 60) and cfg["refresh_token"]:
        refreshed = refresh_mcp_access_token(account)
        if refreshed:
            token = refreshed

    if not token:
        raise PermissionError(
            "MoEngage MCP is not authenticated yet. Click 'Connect MoEngage MCP (OAuth)' or paste an MCP token in Settings -> MoEngage."
        )

    prefix = cfg["prefix"]
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    session_id = _MCP_SESSIONS.get(prefix)
    if session_id and method != "initialize":
        headers["Mcp-Session-Id"] = session_id

    body: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if not is_notification:
        body["id"] = int(time.time() * 1000) % 1000000
    if params is not None:
        body["params"] = params

    resp = requests.post(mcp_url, headers=headers, json=body, timeout=25)

    # If 401 and we have a refresh_token, try refreshing once
    if resp.status_code == 401 and not token_override and cfg["refresh_token"]:
        refreshed = refresh_mcp_access_token(account)
        if refreshed:
            headers["Authorization"] = f"Bearer {refreshed}"
            resp = requests.post(mcp_url, headers=headers, json=body, timeout=25)

    if resp.status_code == 401:
        raise PermissionError(
            "MoEngage MCP token is unauthorized or expired (HTTP 401). Click 'Connect MoEngage MCP (OAuth)' in Settings -> MoEngage."
        )

    if not resp.ok:
        raise RuntimeError(f"MoEngage MCP HTTP {resp.status_code}: {resp.text[:300]}")

    new_sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
    if new_sid:
        _MCP_SESSIONS[prefix] = new_sid

    if is_notification or not resp.text.strip():
        return {"ok": True}

    parsed = _parse_mcp_http_response(resp)
    if "error" in parsed and parsed["error"]:
        err_obj = parsed["error"]
        msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj)
        raise RuntimeError(f"MoEngage MCP RPC error in {method}: {msg}")

    return parsed


def ensure_mcp_initialized(account: str = "tata", token_override: str | None = None) -> dict[str, Any]:
    """Perform the MCP `initialize` handshake with `https://mcp.moengage.com`."""
    init_res = _mcp_rpc_request(
        "initialize",
        params={
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {
                "name": "karix-whitelisting-agent",
                "version": "2.0.0",
            },
        },
        account=account,
        token_override=token_override,
    )
    try:
        _mcp_rpc_request(
            "notifications/initialized",
            params={},
            account=account,
            token_override=token_override,
            is_notification=True,
        )
    except Exception:
        pass
    return init_res.get("result", init_res)


def list_mcp_tools(account: str = "tata", token_override: str | None = None) -> list[dict[str, Any]]:
    """Return the list of tools exposed by `https://mcp.moengage.com`."""
    ensure_mcp_initialized(account=account, token_override=token_override)
    res = _mcp_rpc_request("tools/list", params={}, account=account, token_override=token_override)
    tools = res.get("result", {}).get("tools", [])
    return tools if isinstance(tools, list) else []


def test_mcp_connection(account: str = "tata", token_override: str | None = None) -> dict[str, Any]:
    """Test connectivity and authentication with `https://mcp.moengage.com` and list available tools."""
    try:
        init_info = ensure_mcp_initialized(account=account, token_override=token_override)
        tools = list_mcp_tools(account=account, token_override=token_override)
        tool_names = [t.get("name") for t in tools if isinstance(t, dict) and t.get("name")]
        return {
            "ok": True,
            "mcp_url": get_mcp_config(account)["mcp_url"],
            "server_info": init_info.get("serverInfo", {}),
            "tool_count": len(tool_names),
            "tools": tool_names,
            "message": f"Connected to MoEngage MCP ({len(tool_names)} tools available).",
        }
    except Exception as exc:
        return {
            "ok": False,
            "mcp_url": get_mcp_config(account)["mcp_url"],
            "error": str(exc),
        }


def call_mcp_tool(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    account: str = "tata",
) -> dict[str, Any]:
    """Invoke a tool on `https://mcp.moengage.com` via `tools/call` and unwrap its content."""
    Prefix = _account_prefix(account or "tata")
    if Prefix not in _MCP_SESSIONS:
        ensure_mcp_initialized(account=account)

    res = _mcp_rpc_request(
        "tools/call",
        params={
            "name": tool_name,
            "arguments": arguments or {},
        },
        account=account,
    )
    result = res.get("result", res)
    content_list = result.get("content", []) if isinstance(result, dict) else []
    parsed_items: list[Any] = []
    text_chunks: list[str] = []

    for item in content_list:
        if isinstance(item, dict) and item.get("type") == "text":
            txt = str(item.get("text", "")).strip()
            text_chunks.append(txt)
            try:
                parsed_items.append(json.loads(txt))
            except Exception:
                pass

    return {
        "ok": not bool(result.get("isError")) if isinstance(result, dict) else True,
        "tool": tool_name,
        "data": parsed_items[0] if len(parsed_items) == 1 else (parsed_items or result),
        "text": "\n".join(text_chunks),
        "raw": result,
    }


def mcp_search_campaigns(
    account: str = "tata",
    query: str | None = None,
    channel: str | None = None,
    status: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Search campaigns across channels via MoEngage MCP `search_campaigns` tool."""
    args: dict[str, Any] = {}
    if query:
        args["name"] = query
    # Per MoEngage MCP docs: channel filter accepts Push, Email, SMS, MMS only; omit to include WhatsApp
    if channel and channel.upper() in ("PUSH", "EMAIL", "SMS", "MMS"):
        args["channel"] = channel.upper()
    if status:
        args["status"] = [s.strip().upper() for s in status.split(",") if s.strip()]
    if limit:
        args["limit"] = limit
    return call_mcp_tool("search_campaigns", args, account=account)


def mcp_search_flows(
    account: str = "tata",
    query: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Search customer journey flows via MoEngage MCP `search_flows` tool."""
    args: dict[str, Any] = {}
    if query:
        args["name"] = query
    if status:
        args["status"] = status
    return call_mcp_tool("search_flows", args, account=account)


def mcp_list_segments(
    account: str = "tata",
    name: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Browse existing MoEngage segments via MCP `list_segments` tool."""
    args: dict[str, Any] = {"page": page, "page_size": page_size}
    if name:
        args["name"] = name
    return call_mcp_tool("list_segments", args, account=account)


def mcp_get_campaign_stats(
    campaign_ids: list[str],
    account: str = "tata",
) -> dict[str, Any]:
    """Fetch aggregate performance stats for up to 50 campaigns via MCP `get_campaign_stats`."""
    return call_mcp_tool("get_campaign_stats", {"campaign_ids": campaign_ids[:50]}, account=account)


def mcp_create_campaign_draft(
    payload: dict[str, Any],
    account: str = "tata",
) -> dict[str, Any]:
    """Create a Push or Email campaign draft in MoEngage via MCP `create_campaign_draft`."""
    return call_mcp_tool("create_campaign_draft", payload, account=account)
