"""Apparel WhatsApp brief preparation; all remote writes use the existing draft queue."""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from apparel_whatsapp_brief import read_brief, tracking_window

NO_GOALS = frozenset({"Crocs", "AGIPL", "R&B", "CK"})
OVERRIDES = frozenset({"campaign_name", "segment_name", "exclude_segment_name", "scheduled_at", "whatsapp_template_id", "whatsapp_placeholders", "whatsapp_image_url", "whatsapp_cta_links"})


def brand_info(brand: str) -> dict[str, Any]:
    from moengage_draft_creation import load_server_catalog
    matches = [entry for entry in load_server_catalog("apparel").get("brands", []) if entry.get("brand") == brand]
    if len(matches) != 1:
        raise ValueError("Select a supported Apparel brand")
    return matches[0]


def https_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.port not in (None, 443):
            return False
        host = url.hostname.casefold().rstrip(".")
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return "." in host
    except ValueError:
        return False


def _segment(value: str, catalog: dict) -> dict:
    rows = catalog.get("segments", [])
    exact = [row for row in rows if row["name"] == value]
    normalized = lambda text: re.sub(r"[\s_]+", "_", text.strip()).casefold()
    matches = exact or [row for row in rows if normalized(row["name"]) == normalized(value)]
    if not value or len(matches) != 1:
        raise ValueError("Audience segment is missing or ambiguous: " + value)
    row = matches[0]
    return {"filter_type": "custom_segments", "name": row["name"], "id": row["id"]}


def prepare_audience(row: dict, catalog: dict, errors: list[str]) -> dict | None:
    try:
        result = {"included_filters": {"filter_operator": "and", "filters": [_segment(row.get("segment_name", ""), catalog)]}}
        excluded = row.get("exclude_segment_name", "").strip()
        if excluded:
            denied = _segment(excluded, catalog)
            if denied["id"] == result["included_filters"]["filters"][0]["id"]:
                raise ValueError("The same audience cannot be included and excluded")
            result["excluded_filters"] = {"filter_operator": "and", "filters": [denied]}
        return result
    except ValueError as exc:
        errors.append(str(exc))
        return None


def prepare_row(row: dict, catalog: dict, errors: list[str]) -> dict:
    result = dict(row)
    for field in ("brand", "whatsapp_sender", "whatsapp_template_id", "whatsapp_name_attribute",
                  "whatsapp_name_fallback", "whatsapp_image_url", "whatsapp_cta_links",
                  "existing_campaign_id", "allow_existing_campaign_copy", "global_control_group",
                  "tracking_goal", "scheduled_at", "segment_name", "exclude_segment_name",
                  "template_type"):
        if field in result and not isinstance(result[field], str):
            errors.append(field + " must be a string")
            result[field] = ""
    row = result
    try:
        brand = row.get("brand", "")
        info = brand_info(brand)
        if catalog["workspace_id"] != info["workspace_id"]:
            raise ValueError("Apparel brand and selected workspace disagree")
        if row.get("existing_campaign_id") and row.get("allow_existing_campaign_copy") != "true":
            errors.append("This brief already has a campaign ID; explicitly approve a new draft copy before creating")
        requested = row.get("whatsapp_sender", "").strip()
        digits = re.sub(r"\D", "", requested)
        possible = []
        for sender in catalog.get("whatsapp_senders", []):
            phone = re.sub(r"\D", "", sender.get("number", ""))
            if requested in (sender.get("sender_id"), sender.get("name")) or (digits and (digits == phone or len(digits) == 10 and phone == "91" + digits)):
                possible.append(sender)
        if len(possible) != 1:
            raise ValueError("Brief sender number must resolve to exactly one approved workspace sender")
        result["whatsapp_sender"] = possible[0]["name"]
        result["whatsapp_sender_id"] = possible[0]["sender_id"]
        templates = [item for item in catalog.get("whatsapp_templates", []) if row.get("whatsapp_template_id") in (item.get("id"), item.get("name"), item.get("display_name"))]
        if len(templates) == 1:
            result["whatsapp_template_id"] = templates[0]["id"]
            result["whatsapp_template_name"] = templates[0]["name"]
        if len(templates) == 1 and not row.get("whatsapp_placeholders"):
            slots = set(re.findall(r"\{\{(\d+)\}\}", templates[0].get("body", "")))
            if slots == {"1"} and row.get("whatsapp_name_fallback"):
                name = row.get("whatsapp_name_attribute", "")
                if name not in catalog.get("user_attributes", []):
                    raise ValueError("Choose the workspace's actual customer-name attribute for personalization")
                fallback = row["whatsapp_name_fallback"]
                expression = "{{ UserAttribute[" + json.dumps(name) + "] | default(" + json.dumps(fallback) + ", true) }}"
                result["whatsapp_placeholders"] = json.dumps({"{{1}}": expression}, ensure_ascii=False)
    except (KeyError, ValueError) as exc:
        errors.append(str(exc))
    return result


def prepare_details(row: dict, catalog: dict, content: dict, errors: list[str]) -> dict:
    """Complete the approved template without changing its body, static buttons or opt-in policy."""
    details: dict[str, Any] = {}
    try:
        wa = content["campaign_content"]["content"]["whatsapp"]
        templates = [t for t in catalog.get("whatsapp_templates", []) if t.get("id") == wa.get("template_id")]
        if len(templates) != 1:
            return details
        template = templates[0].get("template_content", {})
        header = template.get("header") or {}
        image = row.get("whatsapp_image_url", "").strip()
        if header.get("type") in ("IMAGE", "VIDEO", "DOCUMENT"):
            if not https_url(image) or urlsplit(image).hostname in ("drive.google.com", "docs.google.com"):
                raise ValueError("Resolve the brief's Drive creative to a durable image URL, or enter the exact public image URL")
            wa["header_placeholders"] = {"dynamic": {"url": image, "file_name": "", "source": "URL"}}
        elif image and header.get("type") not in (None, "NONE", "TEXT"):
            raise ValueError("The approved template requires a supported media header")
        raw_links = row.get("whatsapp_cta_links", "")
        links = json.loads(raw_links) if raw_links else {}
        if not isinstance(links, dict) or any(not isinstance(key, str) or not https_url(value) for key, value in links.items()):
            raise ValueError("CTA links must be a JSON object of button labels to public HTTPS URLs")
        buttons = (template.get("buttons") or {}).get("call_to_action", [])
        placeholders, tracking = {}, []
        consumed = set()
        slot = len(set(re.findall(r"\{\{(\d+)\}\}", templates[0].get("body", ""))))
        for button in buttons:
            if button.get("action") != "NAVIGATION" or button.get("action_type") not in ("DYNAMIC_LINK_TRACKING", "DYNAMIC"):
                continue
            slot += 1
            label = button.get("button_text", "").strip().casefold()
            matches = [(key, value) for key, value in links.items() if key.strip().casefold() == label]
            if len(matches) != 1:
                raise ValueError("Brief must provide exactly one URL for template button: " + button.get("button_text", ""))
            key, value = matches[0]
            consumed.add(key)
            placeholders["{{" + str(slot) + "}}"] = value
            tracking.append({"trackingEnabled": True, "url": value})
        if set(links) != consumed:
            raise ValueError("Brief has CTA links that do not match this approved template's dynamic buttons")
        wa["button_placeholders"], wa["linksTrackingList"] = placeholders, tracking
        goals = {}
        window = {"tracking_value": "0", "tracking_unit": "days"}
        if row.get("brand") not in NO_GOALS:
            reference = catalog.get("goal_reference")
            if not reference or reference.get("id") != row.get("goal_reference_id"):
                raise ValueError("Choose and review this brand's existing WhatsApp conversion-goal reference")
            goals = copy.deepcopy(reference["conversion"])
            primary = goals.get("primary") if isinstance(goals, dict) else None
            if not isinstance(primary, dict) or not primary.get("action") or not isinstance(goals.get("secondary", []), list):
                raise ValueError("The reference has no usable conversion goals")
            window = tracking_window(row.get("tracking_goal", ""), row.get("scheduled_at", ""))
        details = {"conversion_goals": goals, "goal_tracking": {"value": int(window["tracking_value"]), "unit": window["tracking_unit"]},
                   "personalization_enabled": True, "bypass_opt_in_preference": False}
        controls = row.get("global_control_group", "").strip().casefold()
        if controls:
            if controls not in ("yes", "no", "true", "false", "enabled", "disabled"):
                raise ValueError("Global control group must be explicitly Yes or No")
            details["global_control_enabled"] = controls in ("yes", "true", "enabled")
        if template.get("cards") or row.get("template_type", "").strip().casefold() not in ("", "simple", "simple_type"):
            raise ValueError("This brief must identify every card of its approved WhatsApp carousel before creation")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    return details


def draft_permissions(session: dict) -> dict:
    from moengage_workspaces import _metadata_request
    role = _metadata_request(session, "GET", "/gatekeeper/v1/currentRole").get("data")
    if not isinstance(role, dict) or not isinstance(role.get("permissions"), dict):
        return {"verified": False}

    def permission(group, action):
        section = role["permissions"].get(group)
        entries = section.get("value") if isinstance(section, dict) else None
        matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("value") == action] if isinstance(entries, list) else []
        return matches[0].get("hasPermission") if len(matches) == 1 else None

    can_create = role.get("active") is True and permission("drafts", "create_manage") is True and permission("campaigns", "create_manage") is True
    publish_disabled = permission("campaigns", "create_manage_publish") is False
    return {"verified": role.get("active") is True and can_create and publish_disabled,
            "role": role.get("name", ""), "can_create": can_create, "publish_disabled": publish_disabled}


def draft_access_allowed(catalog: dict, *, privileged_agipl_approved: bool = False) -> bool:
    permissions = catalog.get("draft_permissions", {})
    if permissions.get("verified") is True:
        return True
    return (privileged_agipl_approved is True and permissions.get("can_create") is True
            and catalog.get("workspace_id") == brand_info("AGIPL")["workspace_id"])


def enrich_catalog(catalog: dict, session: dict, reference_id: str | None = None) -> dict:
    from moengage_workspaces import _metadata_request
    result = dict(catalog)
    result["draft_permissions"] = draft_permissions(session)
    attributes = _metadata_request(session, "POST", "/v1/segmentation/metadata/user-attrs", {"include_meta_fields": True}).get("filter_dropdown")
    if not isinstance(attributes, dict):
        raise ValueError("Workspace user-attribute metadata unavailable")
    result["user_attributes"] = sorted({info.get("readable_name", key) for key, info in attributes.items() if isinstance(info, dict) and "string" in info.get("data_types", []) and info.get("hidden") is not True})
    candidates = []
    published = _metadata_request(session, "POST", "/campaigns?api=1", {"limit": 100, "filter_block": "all", "request_type": "campaigns", "get_test_campaigns": False, "get_archived_campaigns": False}).get("data", {}).get("campaigns")
    drafts = _metadata_request(session, "POST", "/draft/campaigns?api=1", {"limit": 100, "filter_block": "drafts", "request_type": "campaigns", "get_test_campaigns": False, "get_archived_campaigns": False}).get("data", {}).get("campaigns")
    if not isinstance(published, list) or not isinstance(drafts, list):
        raise ValueError("Existing WhatsApp goal-reference inventory unavailable")
    for source, rows in (("campaign", published), ("draft", drafts)):
        for item in rows:
            if item.get("channel") != "WHATSAPP":
                continue
            identity = item.get("id") if source == "campaign" else item.get("_id")
            identity = identity.get("$oid") if isinstance(identity, dict) else identity
            if not isinstance(identity, str) or not re.fullmatch(r"[a-fA-F0-9]{24}", identity):
                raise ValueError("Invalid existing WhatsApp campaign identity")
            has_goals = bool(item.get("conversion_goal")) if source == "campaign" else bool((item.get("conversion") or {}).get("primary"))
            candidates.append({"id": source + ":" + identity, "name": item.get("name") or item.get("campaignName") or identity, "status": str(item.get("status") or "Draft"), "has_goals": has_goals})
    result["reference_campaigns"] = candidates
    if reference_id:
        match = re.fullmatch(r"(campaign|draft):([a-fA-F0-9]{24})", reference_id)
        if not match or reference_id not in {item["id"] for item in candidates}:
            raise ValueError("Choose an existing WhatsApp goal reference in this workspace")
        source, identity = match.groups()
        if source == "draft":
            data = _metadata_request(session, "GET", f"/draft/campaigns/get/{identity}?api=1").get("data", {}).get("campaign_draft", {}).get("draft")
        else:
            envelope = _metadata_request(session, "GET", f"/campaign/info/{identity}?api=1").get("data", {})
            if envelope.get("campaign", {}).get("channel") != "WHATSAPP":
                raise ValueError("Reference is not a WhatsApp campaign")
            data = envelope.get("campaign_data")
        if not isinstance(data, dict) or data.get("campaignType") != "whatsapp" or not isinstance(data.get("conversion"), dict):
            raise ValueError("Reference has no verified WhatsApp conversion-goal configuration")
        result["goal_reference"] = {"id": reference_id, "name": data.get("campaignName", identity), "conversion": copy.deepcopy(data["conversion"])}
    return result


def catalog(brand: str | None, user: dict, reference_id: str | None = None) -> dict:
    from moengage_draft_creation import load_server_catalog
    from moengage_workspaces import workspace_catalog
    from apparel_whatsapp_google import service_account_email
    base = load_server_catalog("apparel")
    result = dict(base)
    if brand:
        info = brand_info(brand)
        result = workspace_catalog("apparel", user, info["workspace_id"], reference_id=reference_id)
        result.update(brand=brand, no_goals=info["no_goals"])
    result["brands"] = base["brands"]
    result["google_service_account_email"] = service_account_email()
    return result


def prepare_source(filename: str | None, data: bytes | None, spreadsheet_url: str | None, options: dict, user: dict, *, stage: bool = False) -> dict:
    from apparel_whatsapp_google import read_google_brief
    from moengage_draft_batches import DraftBatchQueue, prepare_routed_batch
    from moengage_draft_creation import load_server_catalog
    allowed = {"brand", "columns", "reference_campaign_id", "name_attribute", "allow_existing_campaign_copy", "overrides", "expected_source_digest"}
    if not isinstance(options, dict) or set(options) - allowed:
        raise ValueError("Invalid Apparel WhatsApp review options")
    info = brand_info(options.get("brand", ""))
    columns = options.get("columns")
    if columns is not None and (not isinstance(columns, list) or not columns or len(columns) > 100 or any(not isinstance(col, str) or not re.fullmatch(r"[A-Z]{1,3}", col) for col in columns)):
        raise ValueError("Select up to 100 physical campaign columns")
    if bool(data) == bool(spreadsheet_url):
        raise ValueError("Choose one uploaded workbook or Google Sheet URL")
    rows = read_google_brief(spreadsheet_url, info["brand"], columns=columns) if spreadsheet_url else read_brief(filename or "", data or b"", info["brand"], columns=columns)
    if not rows or len(rows) > 100:
        raise ValueError("Select between 1 and 100 campaign columns before previewing")
    overrides = options.get("overrides", {})
    if not isinstance(overrides, dict) or set(overrides) - {row["row_id"] for row in rows}:
        raise ValueError("Overrides must identify selected physical campaign columns")
    for row in rows:
        values = overrides.get(row["row_id"], {})
        if not isinstance(values, dict) or set(values) - OVERRIDES or any(not isinstance(value, str) or len(value) > 20000 for value in values.values()):
            raise ValueError("Only supported string-valued campaign fields can be reviewed")
        row.update(values, workspace_id=info["workspace_id"], goal_reference_id=str(options.get("reference_campaign_id") or ""), whatsapp_name_attribute=str(options.get("name_attribute") or ""), allow_existing_campaign_copy="true" if options.get("allow_existing_campaign_copy") is True else "false")
    base = load_server_catalog("apparel")
    result = prepare_routed_batch(rows, "apparel", user, base, source_type="apparel_whatsapp_brief")
    digest = hashlib.sha256(json.dumps(
        {"rows": rows, "candidates": [item["candidate_v5_payload"] for item in result["items"]]},
        sort_keys=True, ensure_ascii=False, allow_nan=False,
    ).encode()).hexdigest()
    if stage:
        if options.get("expected_source_digest") != digest:
            raise ValueError("The source or reviewed configuration changed; preview again before staging")
        return DraftBatchQueue("apparel", user, base).stage(rows, rows[0]["source_ref"])
    result["source_digest"] = digest
    return result


def portal_details(payload: dict) -> dict:
    scheduled = payload["scheduling_details"]
    zone = scheduled["timezone"]
    if zone != "Asia/Kolkata":
        raise ValueError("Apparel briefs require explicit Asia/Kolkata scheduling")
    local = datetime.fromisoformat(scheduled["start_time"] + "+05:30")
    goals = payload["conversion_goals"]
    tracking = payload["goal_tracking"]
    result = {"dt": local.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"), "laterDate": local.strftime("%m/%d/%Y"), "time": local.strftime("%I:%M %p").lower(), "timezone": [zone, "+0530"], "timezoneName": zone, "goal": goals.get("primary", {}).get("action", ""), "conversion": goals, "clickTrackHours": tracking["value"], "impTrackHours": tracking["value"], "attributionMultiplier": 24 if tracking["unit"] == "days" else 1, "is_jinja": True, "bypass_opt_in_preference": False}
    if "global_control_enabled" in payload:
        result["global_control_enabled"] = payload["global_control_enabled"]
    return result


def saved_details(draft: dict) -> dict:
    stamp = datetime.fromisoformat(draft["dt"].replace("Z", "+00:00"))
    if (stamp.utcoffset() is None or draft.get("timezone") != ["Asia/Kolkata", "+0530"]
            or draft.get("timezoneName", "Asia/Kolkata") != "Asia/Kolkata"
            or type(draft.get("clickTrackHours")) is not int or draft["clickTrackHours"] < 0
            or type(draft.get("impTrackHours")) is not int
            or draft.get("clickTrackHours") != draft.get("impTrackHours")
            or type(draft.get("attributionMultiplier")) is not int
            or draft.get("attributionMultiplier") not in (1, 24)):
        raise ValueError("Saved schedule or goal tracking differs from the requested configuration")
    from zoneinfo import ZoneInfo
    conversion = draft.get("conversion") or {}
    if (not isinstance(conversion, dict)
            or (draft.get("goal") or "") != (conversion.get("primary") or {}).get("action", "")):
        raise ValueError("Saved conversion goals are inconsistent")
    local = stamp.astimezone(ZoneInfo("Asia/Kolkata"))
    if (datetime.strptime(draft["laterDate"], "%m/%d/%Y").date() != local.date()
            or datetime.strptime(draft["time"].upper(), "%I:%M %p").time() != local.time().replace(microsecond=0)):
        raise ValueError("Saved local schedule differs from its delivery timestamp")
    return {"scheduling_details": {"delivery_type": "AT_FIXED_TIME", "start_time": local.strftime("%Y-%m-%dT%H:%M:%S"), "timezone": "Asia/Kolkata"},
            "conversion_goals": conversion,
            "goal_tracking": {"value": draft.get("clickTrackHours"), "unit": "days" if draft.get("attributionMultiplier") == 24 else "hours"},
            "personalization_enabled": draft.get("is_jinja"),
            "bypass_opt_in_preference": draft.get("bypass_opt_in_preference") or draft.get("whatsapp_data", {}).get("bypass_opt_in_preference", False),
            **({"global_control_enabled": draft["global_control_enabled"]} if "global_control_enabled" in draft else {})}


def upload_image(brand: str, *, content: bytes | None = None, filename: str = "",
                 drive_url: str | None = None) -> dict:
    """Move an explicitly selected creative to this brand's durable MoEngage CDN."""
    import io
    import requests
    from PIL import Image
    from moengage_workspaces import portal_session
    from apparel_whatsapp_google import download_google_image, list_google_images
    info = brand_info(brand)
    if (content is not None) == (drive_url is not None):
        raise ValueError("Choose one uploaded image or Drive creative")
    if drive_url:
        images = list_google_images(drive_url)
        if len(images) != 1:
            if not images:
                raise ValueError("No supported image was found in this Drive source")
            return {"files": images}
        content, filename, _ = download_google_image(images[0]["id"])
    if not content or len(content) > 5 * 1024 * 1024:
        raise ValueError("Choose a JPEG or PNG image of at most 5 MiB")
    try:
        with Image.open(io.BytesIO(content)) as image:
            kind = image.format
            if kind not in ("JPEG", "PNG") or image.width * image.height > 40_000_000:
                raise ValueError("Unsupported creative image")
            image.verify()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ValueError("Choose a valid JPEG or PNG image") from None
    from pathlib import Path
    name = re.sub(r"[^\w.-]", "_", Path(filename or "creative").name)
    name = Path(name).stem[:100] + (".jpg" if kind == "JPEG" else ".png")
    session = portal_session("apparel", info["workspace_id"])
    headers = {key: value for key, value in session["headers"].items() if key.lower() != "content-type"}
    try:
        response = requests.post(
            session["base_url"] + "/campaign/mediaupload", headers=headers,
            data={"filename": name, "media_type": "images"},
            files={"file": (name, content, "image/jpeg" if kind == "JPEG" else "image/png")},
            timeout=(10, 45), allow_redirects=False,
        )
        result = response.json()
        url = result.get("url")
        if (response.status_code != 200 or result.get("status") is not True or not https_url(url)
                or not urlsplit(url).hostname.endswith(".moengage.com")):
            raise ValueError("MoEngage did not confirm the uploaded creative")
    except (requests.RequestException, ValueError):
        raise ValueError("Creative upload was not confirmed; inspect the result before retrying") from None
    return {"url": url}
