"""Account-bound WhatsApp draft transport and gated batch creation.

Portal create acknowledgements are not proof of a draft. The lifecycle persists
real IDs, then reads the saved fields and confirms membership in the Drafts list.
There is no browser fallback after an ambiguous POST and no synthetic ID path.
"""

from __future__ import annotations

import copy
import re
from typing import Any

import requests

from moengage_draft_batches import DraftBatchQueue
from moengage_draft_creation import RateLimitError, load_server_catalog
from moengage_drafts import authorize_draft_account
from moengage_preview import _whatsapp_placeholder_values
from moengage_workspaces import _approved_templates, _sender_inventory, portal_session

_CAMPAIGN_ID = re.compile(r"[0-9a-fA-F]{24}\Z")


def _exact(items: list[dict[str, Any]], value: str, fields: tuple[str, ...], label: str) -> dict[str, Any]:
    clean = str(value or "").strip()
    matches = [item for item in items if clean and any(str(item.get(field, "")).strip() == clean for field in fields)]
    if len(matches) != 1:
        raise ValueError(f"Requested WhatsApp {label} is missing or ambiguous")
    return matches[0]


class WhatsAppDraftWriter:
    """Only create and read WhatsApp drafts in an explicitly bound account workspace."""

    def __init__(self, account: str, workspace_id: str) -> None:
        self.account = account
        self.workspace_id = workspace_id
        session = portal_session(account, workspace_id)
        self.base_url = session["base_url"]
        self.headers = session["headers"].copy()

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = self.headers.copy()
        headers["page"] = "whatsapp/create/one-time/"
        headers["origin"] = self.base_url
        try:
            response = requests.request(
                method, self.base_url + path, headers=headers, json=payload,
                timeout=25, allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise RuntimeError("MoEngage WhatsApp request outcome unconfirmed") from exc
        if response.status_code not in (200, 201):
            raise ValueError(f"MoEngage WhatsApp request failed (HTTP {response.status_code})")
        try:
            data = response.json()
        except ValueError as exc:
            raise ValueError("MoEngage WhatsApp response unconfirmed") from exc
        if (not isinstance(data, dict) or (data.get("status") != "success" and data.get("status") is not True)
                or data.get("success") is False
                or ("code" in data and str(data["code"]) not in ("200", "201"))):
            raise ValueError("MoEngage WhatsApp response unconfirmed")
        return data

    def _senders(self) -> list[dict[str, Any]]:
        return [
            {"id": sender["sender_id"], "sender_name": sender["name"],
             "phone_number": sender["number"], "provider": sender["portal_provider"]}
            for sender in _sender_inventory(self._request("GET", "/whatsapp/settings").get("sender_settings"))
        ]

    def _templates(self, sender: dict[str, Any]) -> list[dict[str, Any]]:
        from urllib.parse import urlencode

        query = urlencode({"template_type": "whatsapp", "sender_id": sender["id"]})
        templates = self._request("GET", f"/template_metadata?{query}").get("data")
        return _approved_templates(templates, [{"sender_id": sender["id"], "provider": sender["provider"]}])

    def prepare(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Resolve exact live selections before reserving or attempting a write."""
        prepared = copy.deepcopy(payload)
        wa = prepared["campaign_content"]["content"]["whatsapp"]
        sender = _exact(self._senders(), wa.get("sender_id") or wa.get("sender_name"),
                        ("id", "sender_name"), "sender")
        if ((wa.get("sender_name") and wa["sender_name"] != sender["sender_name"])
                or (wa.get("provider") and wa["provider"].upper() != sender["provider"].upper())):
            raise ValueError("Requested WhatsApp sender ID, name and provider disagree")
        template = _exact(self._templates(sender), wa.get("template_id"),
                          ("id", "name", "display_name"), "template")
        if not _CAMPAIGN_ID.fullmatch(str(template.get("id") or "")):
            raise ValueError("MoEngage returned no real WhatsApp template ID")
        _whatsapp_placeholder_values(
            wa.get("body_placeholders", {}) if self.account == "apparel" else wa.get("body_placeholders"),
            template.get("body"), allow_partial=self.account == "apparel",
        )
        if self.account == "apparel" and "cards" in wa:
            approved_cards = template.get("template_content", {}).get("cards")
            if not isinstance(wa["cards"], list) or wa["cards"] != approved_cards:
                raise ValueError("WhatsApp cards must match the live approved template")
        wa.update(sender_id=sender["id"], sender_name=sender["sender_name"],
                  provider=sender["provider"].upper(), phone_number=sender["phone_number"],
                  template_id=template["id"], template_name=template.get("name") or template.get("display_name"))
        return prepared

    def create(self, payload: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        # The portal has no documented idempotency guarantee. DraftCreation's durable
        # reservation, not a speculative retry header, prevents a second POST.
        if self.prepare(payload) != payload:
            raise ValueError("WhatsApp selections changed before draft creation")
        wa = payload["campaign_content"]["content"]["whatsapp"]
        sender = _exact(self._senders(), wa["sender_id"], ("id",), "sender")
        body = {"campaign_data": {
            "campaignName": payload["basic_details"]["name"], "action": "create",
            "channel": "WHATSAPP", "channel_type": "MESSAGING", "delivery_type": "ONE_TIME",
            "campaignType": "whatsapp",
            "whatsapp_data": {"sender_id": wa["sender_id"], "sender": sender["provider"],
                              "template_id": wa["template_id"],
                              "bypass_opt_in_preference": False},
            "stepStatus": True, "is_react": True, "c_s_is_new": True,
            "delivery": "later", "triggerDelayType": "delay", "utm_params": {"is_enabled": False},
        }}
        if self.account != "apparel" or "segmentation_details" in payload:
            body["campaign_data"]["new_segmentation_data"] = payload["segmentation_details"]
        if self.account != "apparel" or "body_placeholders" in wa:
            body["campaign_data"]["whatsapp_data"]["body_placeholders"] = copy.deepcopy(wa["body_placeholders"])
        if self.account == "apparel":
            from apparel_whatsapp import portal_details
            body["campaign_data"].update(portal_details(payload))
            if "scheduling_details" not in payload:
                body["campaign_data"].pop("delivery")
                body["campaign_data"].pop("triggerDelayType")
            for key in ("header_placeholders", "button_placeholders", "linksTrackingList", "cards"):
                if key in wa:
                    body["campaign_data"]["whatsapp_data"][key] = copy.deepcopy(wa[key])
        data = self._request("POST", "/v1.0/campaigns/draft", body).get("data")
        campaign_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(campaign_id, str) or not _CAMPAIGN_ID.fullmatch(campaign_id):
            raise ValueError("MoEngage returned no real WhatsApp draft ID")
        return {"id": campaign_id}

    def get(self, campaign_id: str) -> dict[str, Any]:
        if not isinstance(campaign_id, str) or not _CAMPAIGN_ID.fullmatch(campaign_id):
            raise ValueError("Invalid WhatsApp campaign ID")
        envelope = self._request("GET", f"/draft/campaigns/get/{campaign_id}?api=1")
        data = envelope.get("data")
        saved = data.get("campaign_draft") if isinstance(data, dict) else None
        draft = saved.get("draft") if isinstance(saved, dict) else None
        if not isinstance(draft, dict) or not draft.get("campaignName"):
            raise ValueError("MoEngage returned no saved WhatsApp draft")
        # The GET response's inner _id differs from the route's draft ID, and it
        # contains no status. Confirm that route ID in the non-archived Drafts list.
        listed = None
        for test_campaigns in (False, True):
            data = self._request("POST", "/draft/campaigns?api=1", {
                "c_name": draft["campaignName"], "limit": 25, "filter_block": "drafts",
                "request_type": "campaigns", "get_test_campaigns": test_campaigns,
                "get_archived_campaigns": False,
            }).get("data", {})
            campaigns = data.get("campaigns") if isinstance(data, dict) else None
            if not isinstance(campaigns, list):
                raise ValueError("MoEngage draft membership unavailable")
            for item in campaigns:
                identity = item.get("_id") if isinstance(item, dict) else None
                identity = identity.get("$oid") if isinstance(identity, dict) else identity
                if identity == campaign_id:
                    listed = item
                    break
            if listed is not None:
                break
        if listed is None:
            raise ValueError("Campaign is not confirmed in MoEngage Drafts; reconcile manually")
        if (("channel" in draft and draft["channel"] != listed.get("channel"))
                or ("delivery_type" in draft and draft["delivery_type"] != listed.get("delivery_type"))):
            raise ValueError("Saved WhatsApp draft scope differs from Drafts membership")
        wa = draft.get("whatsapp_data")
        if not isinstance(wa, dict):
            raise ValueError("MoEngage returned no saved WhatsApp content")
        sender = _exact(self._senders(), wa.get("sender_id"), ("id",), "saved sender")
        result = {
            "id": campaign_id, "status": "DRAFT", "channel": listed.get("channel"),
            "campaign_delivery_type": listed.get("delivery_type"),
            "basic_details": {"name": draft["campaignName"]},
            **({"segmentation_details": draft.get("new_segmentation_data")}
               if self.account != "apparel" or "new_segmentation_data" in draft else {}),
            "campaign_content": {"content": {"whatsapp": {
                "sender_id": wa.get("sender_id"), "sender_name": sender["sender_name"],
                "provider": str(wa.get("sender") or "").upper(),
                "template_id": wa.get("template_id"),
            }}},
        }
        if self.account != "apparel":
            result["campaign_content"]["content"]["whatsapp"]["body_placeholders"] = wa.get("body_placeholders") or {}
        if self.account == "apparel":
            from apparel_whatsapp import saved_details
            result.update(saved_details(draft))
            for key in ("body_placeholders", "header_placeholders", "button_placeholders", "linksTrackingList", "cards"):
                if key in wa:
                    result["campaign_content"]["content"]["whatsapp"][key] = copy.deepcopy(wa[key])
        return result


def automate_whatsapp_draft_batch(batch_id: str, account: str, user: dict[str, Any]) -> dict[str, Any]:
    """Use the same account-owned claims and verification as single-row creation."""
    authorize_draft_account(account, user)
    queue = DraftBatchQueue(account, user, load_server_catalog(account))
    batch = queue.get(batch_id)
    rows = [row for row in batch["items"] if row["channel"] == "WHATSAPP" and (
        row["status"] == "preview_ready"
        or (row["status"] == "CREATED" and _CAMPAIGN_ID.fullmatch(row.get("campaign_id") or ""))
    )]
    if not rows:
        return {"ok": False, "total": 0, "created": 0, "failed": 0, "results": [],
                "error": "No eligible WhatsApp draft rows"}
    results = []
    rate_limited = False
    for index, row in enumerate(rows):
        try:
            updated = queue.create_row(batch_id, row["row_id"])
            result = next(item for item in updated["items"] if item["row_id"] == row["row_id"])
            results.append({"row_id": row["row_id"], "status": result["status"],
                            "id": result.get("campaign_id"), "error": result.get("issue")})
        except RateLimitError as exc:
            # This is the local pre-POST cap, not an ambiguous provider response.
            # Stop this run; retain every remaining row for deliberate later action.
            rate_limited = True
            results.append({"row_id": row["row_id"], "status": "RATE_LIMITED", "error": str(exc)})
            results.extend({"row_id": pending["row_id"], "status": "NOT_ATTEMPTED",
                            "error": "Not attempted after workspace draft-create rate cap"}
                           for pending in rows[index + 1:])
            break
        except (PermissionError, ValueError) as exc:
            results.append({"row_id": row["row_id"], "status": "BLOCKED", "error": str(exc)})
        except Exception:
            # A failed response/persistence step can follow a successful POST.
            results.append({"row_id": row["row_id"], "status": "UNCERTAIN", "error": "Draft state unavailable; reconcile manually"})
        if (results[-1]["status"] != "VERIFIED"
                or not _CAMPAIGN_ID.fullmatch(results[-1].get("id") or "")):
            results.extend({"row_id": pending["row_id"], "status": "NOT_ATTEMPTED",
                            "error": "Stopped after an unverified result; inspect stored state before continuing"}
                           for pending in rows[index + 1:])
            break
    created = sum(row["status"] == "VERIFIED" and bool(_CAMPAIGN_ID.fullmatch(row.get("id") or "")) for row in results)
    return {"ok": created == len(rows), "total": len(rows), "created": created,
            "failed": len(rows) - created, "results": results, "rate_limited": rate_limited}
