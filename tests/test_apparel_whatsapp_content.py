"""Offline consumer regressions for reviewed Apparel WhatsApp draft content."""

import copy
import csv
import io
import json

import pytest

import apparel_whatsapp as apparel
import db
import moengage_draft_batches as batches
import moengage_draft_creation as creation
from moengage_preview import prepare_batch


USER = {"sub": "apparel-content-owner", "tenant_id": "apparel", "role": "operator", "email": "apparel@example.invalid"}
BRAND_WORKSPACES = {
    "VS": "67ebafa122bb69cb92112742",
    "Aldo": "6821a8b69962306efba6184c",
    "CIS": "6821a8b69962306efba6184c",
    "BBW": "67ebafed33cdecd0d631c806",
    "Crocs": "6811d693e69ce694037fd5ed",
    "AGIPL": "67ffab29c409bbb571499a16",
    "R&B": "6811d59d5be93388c11a1f3e",
    "CK": "6821acfb94497fabc316fd1b",
}
SENDER_ID = "111111111111111111111111"
TEMPLATE_ID = "222222222222222222222222"
REFERENCE_ID = "campaign:333333333333333333333333"
BODY = "Hello {{1}},\nYour Tili favourites are waiting.  Shop now! ✨\nTerms apply."
IMAGE = "https://cdn.example.com/creative/tili.png?version=2"
SHOP = "https://www.example.com/shop?category=tili&utm_source=whatsapp"
APP = "https://www.example.com/app?platform=all"
NAME_EXPRESSION = '{{ UserAttribute["First Name"] | default("Gorgeous", true) }}'
CONVERSION = {
    "primary": {
        "action": "purchase", "goal_name": "Goal1",
        "attributes": {"filter_operator": "and", "filters": []},
        "filter_type": "actions", "r_track": True, "ra": "value", "rc": "INR",
    },
    "secondary": [{
        "action": "add_to_cart", "goal_name": "Goal2",
        "attributes": {"filter_operator": "and", "filters": []},
        "filter_type": "actions", "r_track": False,
    }],
}


def catalog_for(brand="VS"):
    return {
        "account": "apparel", "brand": brand, "workspace_id": BRAND_WORKSPACES[brand],
        "segments": [
            {"id": "seg-include", "name": "VS_ON_ATC_91D_No_Pr"},
            {"id": "seg-exclude", "name": "AGIPL Internal"},
        ],
        "user_attributes": ["First Name", "Last Name", "Email"],
        "whatsapp_senders": [{
            "id": SENDER_ID, "sender_id": SENDER_ID,
            "name": "VS India", "sender_name": "VS India", "number": "+918657864167",
            "phone_number": "+918657864167", "provider": "KARIX",
        }],
        "whatsapp_templates": [{
            "id": TEMPLATE_ID, "name": "vs_tili_on_atc", "display_name": "Tili approved",
            "sender_ids": [SENDER_ID], "provider": "KARIX", "body": BODY,
            "template_content": {
                "body": BODY, "header": {"type": "IMAGE"},
                "buttons": {"call_to_action": [
                    {"action": "NAVIGATION", "action_type": "DYNAMIC_LINK_TRACKING", "button_text": "Shop Now"},
                    {"action": "NAVIGATION", "action_type": "STATIC", "button_text": "Terms", "url": "https://www.example.com/terms"},
                    {"action": "NAVIGATION", "action_type": "DYNAMIC", "button_text": "Download App"},
                ]},
            },
        }],
        "goal_reference": {"id": REFERENCE_ID, "name": brand + " reviewed goal reference", "conversion": copy.deepcopy(CONVERSION)},
    }


def row_for(brand="VS", **changes):
    return {
        "account": "apparel", "brand": brand, "workspace_id": BRAND_WORKSPACES[brand],
        "source_ref": "October WhatsApp.xlsx", "row_id": "WhatsApp!ON", "channel": "WHATSAPP",
        "campaign_name": brand + " Tili reviewed offer", "segment_name": "VS_ON_ATC_91D_No_Pr",
        "exclude_segment_name": "AGIPL Internal", "scheduled_at": "2026-10-29T18:30:00+05:30",
        "timezone": "Asia/Kolkata", "tracking_goal": "29th October-1st November2026",
        "whatsapp_sender": "8657864167", "whatsapp_template_id": "vs_tili_on_atc",
        "whatsapp_name_attribute": "First Name", "whatsapp_name_fallback": "Gorgeous",
        "whatsapp_image_url": IMAGE,
        "whatsapp_cta_links": json.dumps({"Shop Now": SHOP, "Download App": APP}),
        "goal_reference_id": REFERENCE_ID, "global_control_group": "No", **changes,
    }


@pytest.fixture(autouse=True)
def offline_catalog_and_no_writes(monkeypatch):
    base = {
        "account": "apparel", "workspace_id": BRAND_WORKSPACES["Aldo"],
        "brands": [
            {"brand": brand, "workspace_id": workspace, "no_goals": brand in {"Crocs", "AGIPL", "R&B", "CK"}}
            for brand, workspace in BRAND_WORKSPACES.items()
        ],
    }

    def load_catalog(account):
        assert account == "apparel"
        return copy.deepcopy(base)

    def network_forbidden(*args, **kwargs):
        pytest.fail("Pure Apparel preparation must not contact a provider")

    monkeypatch.setattr(creation, "load_server_catalog", load_catalog)
    monkeypatch.setattr("requests.sessions.Session.request", network_forbidden)
    yield
    with db.get_db() as connection:
        for table in ("moengage_draft_attempts", "moengage_draft_batches", "moengage_draft_batch_rows"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def preview(row=None, catalog=None):
    return prepare_batch(
        [row if row is not None else row_for()], "apparel",
        catalog if catalog is not None else catalog_for(), USER["email"], source_type="apparel_whatsapp_brief",
    )


def ready(row=None, catalog=None):
    result = preview(row, catalog)
    assert (result["ready"], result["blocked"], result["write_eligible"]) == (1, 0, False)
    item = result["items"][0]
    assert item["issues"] == []
    return item["candidate_v5_payload"]


def blocked(row=None, catalog=None):
    result = preview(row, catalog)
    assert (result["ready"], result["blocked"], result["write_eligible"]) == (0, 1, False)
    item = result["items"][0]
    assert item["status"] == "blocked"
    assert item["candidate_v5_payload"] is None
    assert item["issues"]


def test_source_display_alias_and_whitespace_template_type_resolve_to_approved_identity():
    catalog = catalog_for()
    catalog["whatsapp_templates"][0].update(name="vs_tili_on_atc_en", display_name="vs_tili_on_atc")
    payload = ready(row_for(whatsapp_template_id="vs_tili_on_atc", template_type=" Simple "), catalog)
    assert payload["campaign_content"]["content"]["whatsapp"]["template_id"] == TEMPLATE_ID
    assert "Gorgeous" in payload["campaign_content"]["content"]["whatsapp"]["body_placeholders"]["{{1}}"]


def test_reviewed_body_audiences_media_buttons_and_exact_schedule_are_preserved():
    row, catalog = row_for(), catalog_for()
    original_row, original_catalog = copy.deepcopy(row), copy.deepcopy(catalog)
    payload = ready(row, catalog)
    assert payload["channel"] == "WHATSAPP"
    assert payload["campaign_delivery_type"] == "ONE_TIME"
    assert payload["created_by"] == USER["email"]
    assert payload["basic_details"]["name"] == "VS Tili reviewed offer"
    assert payload["segmentation_details"] == {
        "included_filters": {"filter_operator": "and", "filters": [
            {"filter_type": "custom_segments", "name": "VS_ON_ATC_91D_No_Pr", "id": "seg-include"},
        ]},
        "excluded_filters": {"filter_operator": "and", "filters": [
            {"filter_type": "custom_segments", "name": "AGIPL Internal", "id": "seg-exclude"},
        ]},
    }
    assert payload["scheduling_details"] == {
        "delivery_type": "AT_FIXED_TIME", "start_time": "2026-10-29T18:30:00", "timezone": "Asia/Kolkata",
    }
    wa = payload["campaign_content"]["content"]["whatsapp"]
    assert (wa["sender_id"], wa["sender_name"], wa["provider"], wa["template_id"]) == (
        SENDER_ID, "VS India", "KARIX", TEMPLATE_ID,
    )
    assert set(wa["body_placeholders"]) == {"{{1}}"}
    personalization = wa["body_placeholders"]["{{1}}"]
    assert "UserAttribute" in personalization
    assert "First Name" in personalization
    assert "Gorgeous" in personalization
    assert "default" in personalization
    assert wa["header_placeholders"] == {"dynamic": {"url": IMAGE, "file_name": "", "source": "URL"}}
    assert wa["button_placeholders"] == {"{{2}}": SHOP, "{{3}}": APP}
    assert wa["linksTrackingList"] == [
        {"trackingEnabled": True, "url": SHOP}, {"trackingEnabled": True, "url": APP},
    ]
    assert payload["conversion_goals"] == CONVERSION
    assert payload["goal_tracking"] == {"value": 3, "unit": "days"}
    assert payload["global_control_enabled"] is False
    assert row == original_row and catalog == original_catalog


@pytest.mark.parametrize("tracking,value,unit,multiplier", [
    ("29th October-1st November2026", 3, "days", 24),
    ("3 days", 3, "days", 24),
    ("36 hours", 36, "hours", 1),
])
def test_elapsed_days_and_explicit_hours_have_distinct_portal_attribution(tracking, value, unit, multiplier):
    payload = ready(row_for(tracking_goal=tracking))
    assert payload["goal_tracking"] == {"value": value, "unit": unit}
    portal = apparel.portal_details(payload)
    assert (portal["clickTrackHours"], portal["impTrackHours"], portal["attributionMultiplier"]) == (value, value, multiplier)


@pytest.mark.parametrize("brand,index", [("VS", 1), ("Aldo", 2), ("CIS", 3), ("BBW", 4)])
def test_each_goal_enabled_brand_uses_its_reviewed_reference_not_a_vs_default(brand, index):
    catalog = catalog_for(brand)
    reference_id = "campaign:" + f"{index + 40:024x}"
    catalog["goal_reference"]["id"] = reference_id
    catalog["goal_reference"]["conversion"]["primary"]["goal_name"] = brand + " purchase"
    catalog["goal_reference"]["conversion"]["primary"]["ra"] = "net_value_" + brand.lower()
    payload = ready(row_for(brand, goal_reference_id=reference_id), catalog)
    assert payload["conversion_goals"]["primary"]["goal_name"] == brand + " purchase"
    assert payload["conversion_goals"]["primary"]["ra"] == "net_value_" + brand.lower()
    assert payload["conversion_goals"]["secondary"] == CONVERSION["secondary"]
    payload["conversion_goals"]["primary"]["goal_name"] = "Edited preview"
    assert catalog["goal_reference"]["conversion"]["primary"]["goal_name"] == brand + " purchase"


def test_rendered_brief_copy_matches_the_approved_body_without_rewriting_static_text():
    rendered = "Hello Ananya,\nYour Tili favourites are waiting.  Shop now! ✨\nTerms apply."
    row = row_for(
        whatsapp_message=rendered, whatsapp_placeholders='{"{{1}}": "Ananya"}',
        whatsapp_name_fallback="",
    )
    result = preview(row)
    assert (result["ready"], result["blocked"]) == (1, 0)
    item = result["items"][0]
    assert item["source_fields"]["whatsapp_message"] == rendered
    assert item["candidate_v5_payload"]["campaign_content"]["content"]["whatsapp"]["body_placeholders"] == {"{{1}}": "Ananya"}
    blocked({**row, "whatsapp_message": rendered.replace("Terms apply.", "Offer guaranteed.")})
    blocked({**row, "whatsapp_placeholders": '{"{{1}}": "Someone else"}'})


@pytest.mark.parametrize("brand", ["Crocs", "AGIPL", "R&B", "CK"])
def test_all_four_no_goal_brands_remove_goals_even_if_inventory_has_a_reference(brand):
    payload = ready(row_for(brand, tracking_goal="", goal_reference_id=""), catalog_for(brand))
    assert payload["conversion_goals"] == {}
    assert payload["goal_tracking"]["value"] == 0
    portal = apparel.portal_details(payload)
    assert portal["goal"] == "" and portal["conversion"] == {}
    assert portal["clickTrackHours"] == portal["impTrackHours"] == 0


def test_existing_campaign_is_reference_only_and_a_new_draft_can_be_prepared():
    payload = ready(row_for(existing_campaign_id="444444444444444444444444"))
    assert "444444444444444444444444" not in json.dumps(payload)
    assert payload["basic_details"]["name"] == "VS Tili reviewed offer"


@pytest.mark.parametrize("change", [
    {"workspace_id": BRAND_WORKSPACES["BBW"]}, {"account": "tata"}, {"brand": "TATA"},
    {"whatsapp_sender": "9999999999"}, {"whatsapp_name_attribute": "first_name"},
    {"goal_reference_id": "campaign:ffffffffffffffffffffffff"},
    {"scheduled_at": "2026-10-29T18:30:00"}, {"timezone": "UTC"},
    {"global_control_group": "maybe"},
])
def test_unreviewed_identity_audience_personalization_and_schedule_are_blocked(change):
    blocked({**row_for(), **change})


@pytest.mark.parametrize("selection", ["workspace", "sender_alias", "template_alias", "template_sender"])
def test_wrong_workspace_or_ambiguous_inventory_never_selects_the_first_match(selection):
    catalog, row = catalog_for(), row_for()
    if selection == "workspace":
        catalog["workspace_id"] = BRAND_WORKSPACES["Aldo"]
    elif selection == "sender_alias":
        catalog["whatsapp_senders"].append({**catalog["whatsapp_senders"][0], "id": "555555555555555555555555", "sender_id": "555555555555555555555555"})
    elif selection == "template_alias":
        catalog["whatsapp_templates"].append({**catalog["whatsapp_templates"][0], "id": "666666666666666666666666"})
    else:
        catalog["whatsapp_templates"][0]["sender_ids"] = ["777777777777777777777777"]
    blocked(row, catalog)


@pytest.mark.parametrize("placeholders", [
    {"{{2}}": "Ananya"}, {"{{1}}": "Ananya", "{{2}}": "extra"},
    {"{{1}}": "Ananya", "1": "Alias collision"}, {"name": "Ananya"},
    {"{{1}}": ""}, {"{{1}}": 123}, ["Ananya"], "invalid JSON",
])
def test_missing_extra_ambiguous_or_mistyped_body_variables_are_blocked(placeholders):
    raw = placeholders if isinstance(placeholders, str) else json.dumps(placeholders)
    blocked(row_for(whatsapp_placeholders=raw, whatsapp_name_fallback=""))


@pytest.mark.parametrize("links", [
    {"Shop Now": SHOP, " shop now ": SHOP, "Download App": APP},
    {"Shop Now": SHOP, "Download App": 123}, [SHOP, APP], None,
])
def test_ambiguous_or_mistyped_cta_slots_are_blocked(links):
    blocked(row_for(whatsapp_cta_links=json.dumps(links)))

@pytest.mark.parametrize("url", [
    "http://cdn.example.com/image.png", "https://localhost/image.png", "https://127.0.0.1/image.png",
    "https://169.254.169.254/latest/meta-data", "https://[::1]/image.png",
    "https://host.internal/image.png", "https://user:secret@cdn.example.com/image.png",
    "https://cdn.example.com:8443/image.png", "javascript:alert(1)", "//cdn.example.com/image.png",
])
@pytest.mark.parametrize("field", ["whatsapp_image_url", "whatsapp_cta_links"])
def test_unsafe_media_and_button_urls_cannot_be_saved(field, url):
    value = url if field == "whatsapp_image_url" else json.dumps({"Shop Now": url, "Download App": APP})
    blocked(row_for(**{field: value}))


@pytest.mark.parametrize("url", [
    "https://drive.google.com/drive/folders/images", "https://docs.google.com/document/d/shared/edit",
])
def test_drive_sharing_pages_are_not_media_assets(url):
    payload = ready(row_for(whatsapp_image_url=url))
    assert "header_placeholders" not in payload["campaign_content"]["content"]["whatsapp"]


@pytest.mark.parametrize("field,value", [
    ("whatsapp_sender", 8657864167), ("whatsapp_image_url", [IMAGE]),
    ("segment_name", {"id": "seg-include"}), ("exclude_segment_name", ["AGIPL Internal"]),
    ("global_control_group", False), ("template_type", ["Simple"]),
])
def test_invalid_source_field_types_block_the_row_instead_of_crashing(field, value):
    blocked(row_for(**{field: value}))


def test_incomplete_campaign_preserves_source_content_without_inventing_launch_settings():
    row = row_for(
        scheduled_at="", segment_name="CK_NewLaunch_Active_OnOff", exclude_segment_name="",
        whatsapp_image_url="", whatsapp_cta_links="", whatsapp_name_fallback="",
        tracking_goal="7 days", goal_reference_id="",
        existing_campaign_id="444444444444444444444444", template_type="Carousel",
    )
    catalog = catalog_for()
    cards = [{"header": {"type": "IMAGE"}, "body": "Original card copy", "buttons": {"call_to_action": []}}]
    catalog["whatsapp_templates"][0]["template_content"]["cards"] = copy.deepcopy(cards)
    result = preview(row, catalog)
    item = result["items"][0]
    assert result["ready"] == 1 and result["blocked"] == 0
    assert item["warnings"] and not item["issues"]
    payload = item["candidate_v5_payload"]
    assert "scheduling_details" not in payload
    assert "segmentation_details" not in payload
    assert "conversion_goals" not in payload
    assert payload["goal_tracking"] == {"value": 7, "unit": "days"}
    wa = payload["campaign_content"]["content"]["whatsapp"]
    assert wa["cards"] == cards
    assert wa["body_placeholders"] == {}
    assert "header_placeholders" not in wa and "button_placeholders" not in wa
    assert item["source_fields"]["segment_name"] == "CK_NewLaunch_Active_OnOff"
    assert item["source_fields"]["existing_campaign_id"] == "444444444444444444444444"
    assert "444444444444444444444444" not in json.dumps(payload)
    portal = apparel.portal_details(payload)
    assert "dt" not in portal and "conversion" not in portal


def test_partial_dynamic_buttons_keep_supplied_link_and_slot_number():
    payload = ready(row_for(whatsapp_cta_links=json.dumps({"Download App": APP})))
    wa = payload["campaign_content"]["content"]["whatsapp"]
    assert wa["button_placeholders"] == {"{{3}}": APP}
    assert wa["linksTrackingList"] == [{"trackingEnabled": True, "url": APP}]


def test_unresolved_exclusion_does_not_save_a_broader_audience():
    payload = ready(row_for(exclude_segment_name="Unknown exclusion"))
    assert "segmentation_details" not in payload


def provider_saved_draft():
    """Independent MoEngage-shaped fixture; deliberately not built with portal_details."""
    return {
        "_id": "888888888888888888888888", "campaignName": "VS Tili reviewed offer",
        "channel": "WHATSAPP", "campaignType": "whatsapp", "delivery_type": "ONE_TIME",
        "delivery": "later", "dt": "2026-10-29T13:00:00.000Z", "laterDate": "10/29/2026",
        "time": "06:30 pm", "timezone": ["Asia/Kolkata", "+0530"], "timezoneName": "Asia/Kolkata",
        "goal": "purchase", "conversion": copy.deepcopy(CONVERSION),
        "clickTrackHours": 3, "impTrackHours": 3, "attributionMultiplier": 24,
        "global_control_enabled": False, "is_jinja": True,
        "whatsapp_data": {
            "sender_id": SENDER_ID, "sender": "Karix", "template_id": TEMPLATE_ID,
            "body_placeholders": {"{{1}}": NAME_EXPRESSION},
            "button_placeholders": {"{{2}}": SHOP, "{{3}}": APP},
            "header_placeholders": {"dynamic": {"url": IMAGE, "file_name": "", "source": "URL"}},
            "linksTrackingList": [{"trackingEnabled": True, "url": SHOP}, {"trackingEnabled": True, "url": APP}],
            "bypass_opt_in_preference": False,
        },
    }


def test_portal_schedule_and_goals_match_independent_saved_provider_data():
    portal = apparel.portal_details(ready())
    saved = provider_saved_draft()
    for field in (
        "dt", "laterDate", "time", "timezone", "timezoneName", "goal", "conversion",
        "clickTrackHours", "impTrackHours", "attributionMultiplier", "global_control_enabled", "is_jinja",
    ):
        assert portal[field] == saved[field]


def test_saved_provider_schedule_and_goals_normalize_to_independent_reviewed_values():
    saved = provider_saved_draft()
    original = copy.deepcopy(saved)
    actual = apparel.saved_details(saved)
    assert actual["scheduling_details"] == {
        "delivery_type": "AT_FIXED_TIME", "start_time": "2026-10-29T18:30:00", "timezone": "Asia/Kolkata",
    }
    assert actual["conversion_goals"] == CONVERSION
    assert actual["goal_tracking"] == {"value": 3, "unit": "days"}
    assert actual["global_control_enabled"] is False
    assert actual["personalization_enabled"] is True
    assert actual["bypass_opt_in_preference"] is False
    assert saved == original


@pytest.mark.parametrize("change", [
    {"laterDate": "10/30/2026"}, {"time": "07:30 pm"},
    {"timezone": ["UTC", "+0000"]}, {"timezoneName": "UTC"},
    {"dt": "2026-10-29T13:00:00"}, {"impTrackHours": 72},
    {"attributionMultiplier": 7}, {"clickTrackHours": "3"},
    {"goal": "add_to_cart"}, {"goal": ""}, {"conversion": {}},
])
def test_internally_inconsistent_saved_schedule_or_goals_cannot_verify(change):
    saved = provider_saved_draft()
    saved.update(change)
    with pytest.raises(ValueError):
        apparel.saved_details(saved)


@pytest.mark.parametrize("field,value,expected", [
    ("dt", "2026-10-30T13:00:00.000Z", "2026-10-30T18:30:00"),
    ("clickTrackHours", 4, 4),
])
def test_consistent_provider_changes_are_observable_not_replaced_by_requested_values(field, value, expected):
    saved = provider_saved_draft()
    saved[field] = value
    if field == "dt":
        saved["laterDate"] = "10/30/2026"
    else:
        saved["impTrackHours"] = value
    actual = apparel.saved_details(saved)
    assert actual != apparel.saved_details(provider_saved_draft())
    assert (actual["scheduling_details"]["start_time"] if field == "dt" else actual["goal_tracking"]["value"]) == expected


def test_changed_saved_goals_are_observable_and_explicit_hours_are_not_days():
    saved = provider_saved_draft()
    saved["conversion"]["primary"]["rc"] = "USD"
    saved.update(clickTrackHours=36, impTrackHours=36, attributionMultiplier=1)
    actual = apparel.saved_details(saved)
    assert actual["conversion_goals"]["primary"]["rc"] == "USD"
    assert actual["conversion_goals"] != CONVERSION
    assert actual["goal_tracking"] == {"value": 36, "unit": "hours"}


def brief_csv(*, send_time="6:30PM", notes="Reviewed creative"):
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows([
        ["Campaign", "", "Reviewed"], ["Brief Date", "", "27th October2026"],
        ["Send Date and Day", "", "29th October|Thursday"], ["Send Time", "", send_time],
        ["Campaign Name", "", "VS Tili reviewed offer"],
        ["Track the Goal for No.ofHours/Days", "", "29th October-1st November2026"],
        ["SenderID/WhatsApp Number", "", "8657864167"], ["TemplateID", "", "vs_tili_on_atc"],
        ["TemplateType", "", "Simple"], ["TargetAudience/Include", "", "VS_ON_ATC_91D_No_Pr"],
        ["Exclude", "", "AGIPL Internal"], ["BodyCopy/IfVariables", "", 'Use customer name; "Gorgeous" as fallback'],
        ["ImageURL", "", IMAGE], ["CTALink", "", "Shop Now: " + SHOP + "\nDownload App: " + APP],
        ["GlobalControlGroup", "", "No"], ["Notes", "", notes],
    ])
    return stream.getvalue().encode()


def source_options(**changes):
    return {"brand": "VS", "columns": ["C"], "reference_campaign_id": REFERENCE_ID, "name_attribute": "First Name", **changes}


@pytest.fixture
def routed_catalog(monkeypatch):
    def resolve(account, user, row, base):
        assert account == "apparel" and user == USER
        assert row["workspace_id"] == BRAND_WORKSPACES["VS"]
        return catalog_for()

    monkeypatch.setattr(batches, "catalog_for_row", resolve)


def test_uploaded_source_preview_uses_real_parser_and_applies_only_reviewed_overrides(routed_catalog):
    data = brief_csv()
    original = apparel.prepare_source("brief.csv", data, None, source_options(), USER)
    assert (original["ready"], original["blocked"], original["write_eligible"]) == (1, 0, False)
    assert original["items"][0]["row_id"] == "WhatsApp!C"
    assert original["items"][0]["candidate_v5_payload"]["goal_tracking"] == {"value": 3, "unit": "days"}
    reviewed = apparel.prepare_source("brief.csv", data, None, source_options(overrides={
        "WhatsApp!C": {"campaign_name": "Reviewed new campaign", "whatsapp_image_url": "https://cdn.example.com/reviewed.png"},
    }), USER)
    assert reviewed["items"][0]["candidate_v5_payload"]["basic_details"]["name"] == "Reviewed new campaign"
    assert reviewed["items"][0]["candidate_v5_payload"]["campaign_content"]["content"]["whatsapp"]["header_placeholders"]["dynamic"]["url"] == "https://cdn.example.com/reviewed.png"
    assert original["items"][0]["candidate_v5_payload"]["basic_details"]["name"] == "VS Tili reviewed offer"


@pytest.mark.parametrize("changed", [brief_csv(send_time="7:30PM"), brief_csv(notes="Changed source copy")])
def test_changed_source_cannot_stage_using_a_stale_preview_digest(routed_catalog, changed):
    result = apparel.prepare_source("brief.csv", brief_csv(), None, source_options(), USER)
    with pytest.raises(ValueError):
        apparel.prepare_source("brief.csv", changed, None, source_options(expected_source_digest=result["source_digest"]), USER, stage=True)


@pytest.mark.parametrize("options", [
    {"overrides": {"WhatsApp!D": {"campaign_name": "Wrong column"}}},
    {"overrides": {"WhatsApp!C": {"brand": "BBW"}}},
    {"overrides": {"WhatsApp!C": {"goal_reference_id": "campaign:ffffffffffffffffffffffff"}}},
    {"overrides": {"WhatsApp!C": {"campaign_name": 123}}},
    {"overrides": []}, {"columns": [3]}, {"columns": "C"},
])
def test_unselected_columns_and_unapproved_or_mistyped_overrides_are_rejected(options):
    with pytest.raises(ValueError):
        apparel.prepare_source("brief.csv", brief_csv(), None, source_options(**options), USER)


def test_staging_without_a_preview_digest_is_rejected_before_any_queue_write():
    with pytest.raises(ValueError):
        apparel.prepare_source("brief.csv", brief_csv(), None, source_options(), USER, stage=True)


@pytest.mark.parametrize("change,verified", [
    ("draft_only", True), ("publish_enabled", False), ("publish_unknown", False),
    ("publish_duplicate", False), ("draft_denied", False), ("inactive", False),
    ("malformed", False),
])
def test_live_permission_policy_requires_explicit_draft_access_and_publish_denial(monkeypatch, change, verified):
    import moengage_workspaces
    role = {"name": "Marketer", "active": True, "permissions": {
        "campaigns": {"value": [
            {"value": "create_manage", "hasPermission": True},
            {"value": "create_manage_publish", "hasPermission": False},
        ]},
        "drafts": {"value": [{"value": "create_manage", "hasPermission": True}]},
    }}
    if change == "publish_enabled":
        role["permissions"]["campaigns"]["value"][1]["hasPermission"] = True
    elif change == "publish_unknown":
        role["permissions"]["campaigns"]["value"].pop()
    elif change == "publish_duplicate":
        role["permissions"]["campaigns"]["value"].append({"value": "create_manage_publish", "hasPermission": False})
    elif change == "draft_denied":
        role["permissions"]["drafts"]["value"][0]["hasPermission"] = False
    elif change == "inactive":
        role["active"] = False
    elif change == "malformed":
        role["permissions"] = []
    monkeypatch.setattr(moengage_workspaces, "_metadata_request", lambda *args: {"data": role})
    assert apparel.draft_permissions({})["verified"] is verified


def test_owner_flags_do_not_override_a_publish_capable_live_workspace(monkeypatch):
    import os
    import moengage_workspaces
    prefix = "MOENGAGE_DRAFT_APPAREL_"
    for name in list(os.environ):
        if name.startswith(prefix):
            monkeypatch.delenv(name)
    for name in ("ZERO_CHARGE_CONFIRMED", "NO_PUBLISH_SCOPE_CONFIRMED", "LIVE_ENABLED", "ALLOW_SQLITE"):
        monkeypatch.setenv(prefix + name, "true")
    live = catalog_for()
    live["draft_permissions"] = {"verified": False, "can_create": True, "publish_disabled": False}
    monkeypatch.setattr(creation, "load_server_catalog", lambda account: live)
    monkeypatch.setattr(moengage_workspaces, "workspace_catalog", lambda *args, **kwargs: live)
    with pytest.raises(PermissionError):
        creation.DraftCreation.from_environment("apparel", USER, workspace_id=live["workspace_id"])


@pytest.mark.parametrize("brand", ["AGIPL", "VS"])
@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("can_create", [False, True])
def test_privileged_session_approval_is_agipl_only_and_never_grants_missing_draft_access(brand, approved, can_create):
    catalog = catalog_for(brand)
    catalog["draft_permissions"] = {"verified": False, "can_create": can_create}
    assert apparel.draft_access_allowed(catalog, privileged_agipl_approved=approved) is (
        brand == "AGIPL" and approved and can_create
    )
