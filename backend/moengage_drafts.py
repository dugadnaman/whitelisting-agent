"""Restricted MoEngage V5 draft transport, independent of legacy MCP credentials.

No HTTP call is possible until a workspace owner provisions account-specific
credentials and explicitly enables this account after the cost/permission gate.
This module has no generic URL, HTTP-method, MCP-tool, or publish interface.
"""

from __future__ import annotations

import os
import re
from typing import Any
from uuid import UUID

import requests

_ACCOUNT_ID = re.compile(r"[a-z][a-z0-9_]*\Z")
_CAMPAIGN_ID = re.compile(r"[0-9a-fA-F]{24}\Z")
_CREATE_FIELDS = frozenset({
    "channel", "campaign_delivery_type", "created_by", "basic_details",
    "campaign_content", "segmentation_details", "connector", "scheduling_details",
})
_DATA_CENTERS = frozenset({"01", "02", "03", "04", "05", "06", "101"})


def authorize_draft_account(account: str, user: dict[str, Any]) -> None:
    """Only an authenticated exact-tenant user or platform superadmin may select an account."""
    if not _ACCOUNT_ID.fullmatch(account):
        raise ValueError("Invalid canonical account ID")
    tenant = str(user.get("tenant_id", "")).lower().strip()
    authenticated = user.get("sub") and user.get("sub") != "usr_anon"
    privileged = tenant == "all" and user.get("role") == "superadmin"
    if not authenticated or not (tenant == account or privileged):
        raise PermissionError("Draft account access denied")


class DraftWriter:
    """Only V5 one-time Email/Push drafts for the authenticated user's account.

    Caller supplies one persisted UUIDv4 per create operation; never
    regenerate it on retries. No auto-retry of ambiguous provider failures.
    Complete the draft on create: PATCH can race another operator's publish.
    """

    def __init__(
        self,
        account: str,
        user: dict[str, Any],
        *,
        transport: Any = requests,
    ) -> None:
        authorize_draft_account(account, user)

        prefix = f"MOENGAGE_DRAFT_{account.upper()}_"
        # Never call _load_env_file or read shared MOENGAGE_* / MCP / legacy keys.
        if os.environ.get(prefix + "LIVE_ENABLED") != "true":
            raise PermissionError("Live draft access requires account owner approval")
        workspace = os.environ.get(prefix + "WORKSPACE_ID", "").strip()
        key = os.environ.get(prefix + "API_KEY", "").strip()
        dc = os.environ.get(prefix + "DATA_CENTER", "").strip()
        if not workspace or not key or dc not in _DATA_CENTERS:
            raise ValueError("Account-specific draft credentials and data center required")

        self._base_url = f"https://api-{dc}.moengage.com/v5/campaigns"
        self._auth = (workspace, key)
        self._transport = transport

    def _request(
        self, method: str, path: str = "", *,
        payload: dict[str, Any] | None = None, idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        response = self._transport.request(
            method, self._base_url + path, auth=self._auth, headers=headers,
            json=payload, timeout=25, allow_redirects=False,
        )
        if response.status_code not in (200, 201):
            raise ValueError(f"MoEngage draft request failed (HTTP {response.status_code})")
        envelope = response.json()
        if not isinstance(envelope, dict) or not isinstance(envelope.get("data"), dict):
            raise ValueError("MoEngage returned no campaign data")
        return envelope["data"]

    @staticmethod
    def _operation_key(key: str) -> str:
        try:
            parsed = UUID(key)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Idempotency key must be UUIDv4") from exc
        if parsed.version != 4 or str(parsed) != key:
            raise ValueError("Idempotency key must be UUIDv4")
        return key

    @staticmethod
    def _campaign_path(campaign_id: str) -> str:
        if not isinstance(campaign_id, str) or not _CAMPAIGN_ID.fullmatch(campaign_id):
            raise ValueError("Invalid campaign ID")
        return f"/{campaign_id}"

    def create(self, payload: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        if not isinstance(payload, dict) or not set(payload) <= _CREATE_FIELDS:
            raise ValueError("Unsupported draft create fields")
        if (payload.get("channel") not in ("EMAIL", "PUSH")
                or payload.get("campaign_delivery_type") != "ONE_TIME"
                or not isinstance(payload.get("created_by"), str)
                or not payload["created_by"].strip()):
            raise ValueError("One-time Email/Push and creator are required")
        key = self._operation_key(idempotency_key)
        data = self._request("POST", payload=payload, idempotency_key=key)
        if data.get("status") != "DRAFT":
            raise ValueError("Created campaign is not confirmed DRAFT")
        return data

    def get(self, campaign_id: str) -> dict[str, Any]:
        return self._request("GET", self._campaign_path(campaign_id))


    def validate(self, campaign_id: str) -> dict[str, Any]:
        path = self._campaign_path(campaign_id)
        if self.get(campaign_id).get("status") != "DRAFT":
            raise PermissionError("Only confirmed drafts may be validated")
        return self._request("POST", path + "/validate")
