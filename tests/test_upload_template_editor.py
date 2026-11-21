"""Exercise the mounted upload editor with real React and the existing browser harness."""

import pytest
from playwright.sync_api import expect

from tests.test_upload_draft_storage import editable_upload, upload_modules, upload_page


def test_whatsapp_disclaimer_is_message_copy_and_original_buttons_are_readable(upload_page):
    page = upload_page
    original_bytes = editable_upload(page)
    card = page.get_by_test_id("upload-template-card")
    expect(card.get_by_test_id("upload-header")).to_contain_text("તમારી ઑફર")
    expect(card.get_by_test_id("upload-body")).not_to_contain_text("Destination URL")
    expect(card.get_by_test_id("upload-buttons")).to_contain_text("URL example: https://offers.example.test/offer/123")
    expect(card.get_by_test_id("upload-buttons").locator("a, pre, textarea")).to_have_count(0)
    card.get_by_role("button", name="Edit", exact=True).click()
    expect(page.get_by_label("Footer", exact=True)).to_have_count(0)
    expect(page.get_by_label("Message", exact=True)).to_have_value("નમસ્તે {{1}}\nતમારી મૂળ ઑફર અહીં છે.\n\nનિયમો લાગુ")
    expect(page.get_by_label("Header", exact=True)).to_have_attribute("dir", "auto")
    expect(page.get_by_label("Button label", exact=True)).to_have_attribute("dir", "auto")
    page.get_by_label("Message", exact=True).fill("سلام {{1}}\nشرائط لاگو ہیں")
    page.get_by_label("Sample {{1}}", exact=True).fill("آمنہ")
    page.get_by_label("Button label", exact=True).fill("پیشکش دیکھیں")
    destination = "https://u3.mnge.co/Offer/%2fCase?next=%2FHOME&ref={{1}}#Exact"
    example = "https://u3.mnge.co/Offer/%2fCase?next=%2FHOME&ref=123#Exact"
    page.get_by_label("Destination URL", exact=True).fill(destination)
    page.get_by_label("URL examples (one per line)", exact=True).fill(example + "\n" + example.replace("ref=123", "ref=456"))
    page.get_by_role("button", name="Save", exact=True).click()
    patch = page.evaluate("tabState.getTabState('submit_template_overrides', {})['Offers!D17']")
    body = next(item for item in patch["components"] if item["type"] == "BODY")
    assert body == {"type": "BODY", "text": "سلام {{1}}\nشرائط لاگو ہیں", "example": {"body_text": [["آمنہ"]]}}
    assert not any(item["type"] == "FOOTER" for item in patch["components"])
    buttons = next(item["buttons"] for item in patch["components"] if item["type"] == "BUTTONS")
    assert buttons == [{"type": "URL", "text": "پیشکش دیکھیں", "url": destination, "example": [example, example.replace("ref=123", "ref=456")]}]
    expect(card.get_by_test_id("upload-body").locator("pre")).to_have_attribute("dir", "auto")
    expect(card.get_by_test_id("upload-buttons")).to_contain_text(destination)
    card.locator("summary", has_text="Original source preview").click()
    source = card.locator("aside")
    expect(source).to_contain_text("Regional.xlsx")
    expect(source).to_contain_text("Offers!D17")
    expect(source.get_by_test_id("upload-footer")).to_contain_text("નિયમો લાગુ")
    expect(source.get_by_test_id("upload-buttons")).to_contain_text("https://offers.example.test/offer/{{1}}")
    assert page.evaluate("calls.previews[0].bytes") == list(original_bytes)
    assert page.evaluate("calls.posts.length") == 0


def test_whatsapp_button_type_changes_clear_incompatible_fields_and_cancel_restores(upload_page):
    page = upload_page
    editable_upload(page)
    page.get_by_role("button", name="Edit", exact=True).click()
    page.get_by_label("Action type", exact=True).select_option("PHONE_NUMBER")
    expect(page.get_by_label("Destination URL", exact=True)).to_have_count(0)
    expect(page.get_by_label("URL examples (one per line)", exact=True)).to_have_count(0)
    page.get_by_label("Phone number", exact=True).fill("+919876543210")
    page.get_by_label("Action type", exact=True).select_option("QUICK_REPLY")
    expect(page.get_by_label("Phone number", exact=True)).to_have_count(0)
    page.get_by_label("Button label", exact=True).fill("હા")
    page.get_by_role("button", name="+ Add button", exact=True).click()
    page.get_by_label("Button label", exact=True).nth(1).fill("Remove me")
    page.get_by_role("button", name="Remove button 2", exact=True).click()
    page.get_by_role("button", name="Cancel", exact=True).click()
    expect(page.get_by_test_id("upload-buttons")).to_contain_text("https://offers.example.test/offer/{{1}}")
    assert page.evaluate("tabState.getTabState('submit_template_overrides', {})") == {}
    page.get_by_role("button", name="Edit", exact=True).click()
    page.get_by_label("Action type", exact=True).select_option("PHONE_NUMBER")
    page.get_by_label("Phone number", exact=True).fill("+919876543210")
    page.get_by_role("button", name="Save", exact=True).click()
    patch = page.evaluate("tabState.getTabState('submit_template_overrides', {})['Offers!D17']")
    assert next(item["buttons"] for item in patch["components"] if item["type"] == "BUTTONS") == [
        {"type": "PHONE_NUMBER", "text": "મારી ઑફર જુઓ", "phone_number": "+919876543210"},
    ]
    page.get_by_role("button", name="Edit", exact=True).click()
    page.get_by_label("Action type", exact=True).select_option("URL")
    expect(page.get_by_label("Destination URL", exact=True)).to_have_value("")
    expect(page.get_by_label("URL examples (one per line)", exact=True)).to_have_value("")
    page.get_by_role("button", name="Cancel", exact=True).click()
    expect(page.get_by_test_id("upload-buttons")).to_contain_text("Phone: +919876543210")


@pytest.mark.parametrize("url", ["http://offers.example.test/", "https://localhost/", "https://127.0.0.1/", "https://user:pass@offers.example.test/"])
def test_whatsapp_invalid_destination_does_not_save_or_normalize_url(upload_page, url):
    page = upload_page
    editable_upload(page)
    page.get_by_role("button", name="Edit", exact=True).click()
    page.get_by_label("Destination URL", exact=True).fill(url)
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("group", name="Edit uploaded template", exact=True).get_by_role("alert")).to_be_visible()
    expect(page.get_by_label("Destination URL", exact=True)).to_have_value(url)
    assert page.evaluate("tabState.getTabState('submit_template_overrides', {})") == {}
    assert page.evaluate("calls.posts.length") == 0


def test_whatsapp_embedded_header_is_retained_without_readonly_fields_and_removable(upload_page):
    page = upload_page
    page.evaluate("""() => {
        previews = [{template_name: 'att_creative', source_ref: 'Creative!B3', category: 'UTILITY', language: 'en',
            inventory_status: 'verified', submission_ready: true, components: [
                {type: 'HEADER', format: 'IMAGE', text: null, media_url: null, media_file: '/server/creative.png',
                 image_bytes: null, file_type: 'image/png', thumbnail_url: null,
                 example: {header_handle: ['original-source-handle']}},
                {type: 'BODY', text: 'Original message', format: null, buttons: null}]}];
        mountUpload();
    }""")
    page.locator('input[type="file"]').first.set_input_files({"name": "Creative.xlsx", "mimeType": "application/octet-stream", "buffer": b"original creative workbook"})
    page.get_by_role("button", name="Edit", exact=True).click()
    expect(page.get_by_label("Header media URL", exact=True)).to_have_value("")
    expect(page.get_by_text("Original creative reference: original-source-handle", exact=True)).to_be_visible()
    page.get_by_label("Message", exact=True).fill("Reviewed creative message")
    page.get_by_role("button", name="Save", exact=True).click()
    patch = page.evaluate("tabState.getTabState('submit_template_overrides', {})['Creative!B3']")
    assert next(item for item in patch["components"] if item["type"] == "HEADER") == {"type": "HEADER", "format": "IMAGE"}
    assert next(item for item in patch["components"] if item["type"] == "BODY") == {"type": "BODY", "text": "Reviewed creative message"}
    page.get_by_role("button", name="Edit", exact=True).click()
    page.get_by_label("Header format", exact=True).select_option("NONE")
    page.get_by_role("button", name="Save", exact=True).click()
    assert [item["type"] for item in page.evaluate("tabState.getTabState('submit_template_overrides', {})['Creative!B3'].components")] == ["BODY"]
    page.get_by_role("button", name="Edit", exact=True).click()
    page.get_by_label("Header format", exact=True).select_option("IMAGE")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("group", name="Edit uploaded template", exact=True).get_by_role("alert")).to_be_visible()
    exact_url = "https://cdn.example.test/Creative%2fORIGINAL.png?token=CaseSensitive"
    page.get_by_label("Header media URL", exact=True).fill(exact_url)
    page.get_by_role("button", name="Save", exact=True).click()
    assert next(item for item in page.evaluate("tabState.getTabState('submit_template_overrides', {})['Creative!B3'].components") if item["type"] == "HEADER")["media_url"] == exact_url


@pytest.fixture
def rcs_editor(upload_page):
    page = upload_page
    page.evaluate("""() => {
        app.channel = 'rcs';
        previews = [{template_name: 'att_rcs', source_ref: 'RCS!B7', source_file: 'RCS.xlsx',
            template_type: 'richcard', card_title: 'मूळ शीर्षक', card_description: 'मूळ संदेश', text_message: null,
            media_url: 'https://cdn.example.test/original.png', image_bytes: null, file_name: 'server-only.png',
            orientation: 'HORIZONTAL', height: 'MEDIUM', width: 'SMALL', template_category: 'PROMOTIONAL',
            inventory_status: 'verified', submission_ready: true, carousel_cards: null,
            suggestions: [{suggestionType: 'url_action', text: 'पहा', url: 'https://offers.example.test/Case',
                postbackData: null, phoneNumber: null, id: 'server-only-action'}]}];
        mountUpload();
    }""")
    page.locator('input[type="file"]').first.set_input_files({"name": "RCS.xlsx", "mimeType": "application/octet-stream", "buffer": b"exact original RCS bytes"})
    expect(page.get_by_test_id("upload-template-card")).to_be_visible()
    page.get_by_role("button", name="Edit", exact=True).click()
    return page


def test_rcs_richcard_layout_actions_and_patch_match_backend_contract(rcs_editor):
    page = rcs_editor
    page.get_by_label("Title", exact=True).fill("नवे शीर्षक")
    page.get_by_label("Message", exact=True).fill("नवा प्रादेशिक संदेश")
    page.get_by_label("Orientation", exact=True).select_option("VERTICAL")
    page.get_by_label("Height", exact=True).select_option("TALL")
    expect(page.get_by_label("Width", exact=True)).to_have_count(0)
    page.get_by_label("Template category", exact=True).select_option("TRANSACTIONAL")
    page.get_by_label("Action type", exact=True).select_option("dialer_action")
    page.get_by_label("Phone number", exact=True).fill("+912212345678")
    page.get_by_label("Postback data (optional)", exact=True).fill("regional-dial")
    page.get_by_role("button", name="Save", exact=True).click()
    patch = page.evaluate("tabState.getTabState('submit_template_overrides', {})['RCS!B7']")
    assert patch == {"template_name": "att_rcs", "template_type": "richcard", "card_title": "नवे शीर्षक",
                     "card_description": "नवा प्रादेशिक संदेश", "media_url": "https://cdn.example.test/original.png",
                     "orientation": "VERTICAL", "height": "TALL", "template_category": "TRANSACTIONAL",
                     "suggestions": [{"suggestionType": "dialer_action", "text": "पहा", "phoneNumber": "+912212345678", "postbackData": "regional-dial"}]}
    expect(page.get_by_test_id("upload-buttons")).to_contain_text("Phone: +912212345678")
    expect(page.get_by_test_id("upload-buttons")).to_contain_text("Postback data: regional-dial")
    assert page.evaluate("calls.posts.length") == 0


def test_rcs_removing_richcard_creative_requires_replacement_or_text_mode(rcs_editor):
    page = rcs_editor
    page.get_by_role("button", name="Remove creative", exact=True).click()
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("group", name="Edit uploaded template", exact=True).get_by_role("alert")).to_be_visible()
    assert page.evaluate("tabState.getTabState('submit_template_overrides', {})") == {}
    page.get_by_label("Template type", exact=True).select_option("text")
    expect(page.get_by_label("Message", exact=True)).to_have_value("मूळ संदेश")
    page.get_by_label("Message", exact=True).fill("उर्दू اور مراٹھی کی نئی عبارت")
    page.get_by_role("button", name="Save", exact=True).click()
    patch = page.evaluate("tabState.getTabState('submit_template_overrides', {})['RCS!B7']")
    assert patch["template_type"] == "text"
    assert patch["text_message"] == "उर्दू اور مراٹھی کی نئی عبارت"
    assert patch["media_url"] == ""
    assert not {"carousel_cards", "card_title", "card_description", "text_message_type"} & patch.keys()
    expect(page.get_by_test_id("upload-body")).to_contain_text(patch["text_message"])


def test_rcs_carousel_card_actions_samples_and_minimum_card_validation(rcs_editor):
    page = rcs_editor
    page.get_by_label("Template type", exact=True).select_option("carousel")
    page.get_by_role("button", name="+ Add card", exact=True).click()
    first = page.get_by_role("group", name="Card 1", exact=True)
    first.get_by_label("Card title", exact=True).fill("पहिले कार्ड")
    first.get_by_label("Card message", exact=True).fill("पहिल्या कार्डाचा संदेश")
    first.get_by_label("Card media URL", exact=True).fill("https://cdn.example.test/Card%2fOne.png")
    first.get_by_role("button", name="+ Add button", exact=True).click()
    first.get_by_label("Button label", exact=True).fill("अधिक पहा")
    url = "https://u3.mnge.co/Card?next=%2fKeepCase"
    first.get_by_label("Destination URL", exact=True).fill(url)
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("group", name="Edit uploaded template", exact=True).get_by_role("alert")).to_be_visible()
    page.get_by_role("button", name="+ Add card", exact=True).click()
    second = page.get_by_role("group", name="Card 2", exact=True)
    second.get_by_label("Card title", exact=True).fill("دوسرا کارڈ")
    second.get_by_label("Card message", exact=True).fill("دوسرے کارڈ کا پیغام")
    expect(second.get_by_label("Card message", exact=True)).to_have_attribute("dir", "auto")
    second.get_by_label("Card media URL", exact=True).fill("https://cdn.example.test/CardTwo.png")
    second.get_by_role("button", name="+ Add button", exact=True).click()
    second.get_by_label("Action type", exact=True).select_option("reply")
    second.get_by_label("Button label", exact=True).fill("جی ہاں")
    second.get_by_label("Postback data (optional)", exact=True).fill("second-reply")
    page.get_by_role("button", name="Save", exact=True).click()
    patch = page.evaluate("tabState.getTabState('submit_template_overrides', {})['RCS!B7']")
    assert patch["carousel_cards"] == [
        {"card_title": "पहिले कार्ड", "card_description": "पहिल्या कार्डाचा संदेश", "media_url": "https://cdn.example.test/Card%2fOne.png",
         "suggestions": [{"suggestionType": "url_action", "text": "अधिक पहा", "url": url}]},
        {"card_title": "دوسرا کارڈ", "card_description": "دوسرے کارڈ کا پیغام", "media_url": "https://cdn.example.test/CardTwo.png",
         "suggestions": [{"suggestionType": "reply", "text": "جی ہاں", "postbackData": "second-reply"}]},
    ]
    expect(page.get_by_test_id("upload-template-card")).to_contain_text("دوسرے کارڈ کا پیغام")
    expect(page.get_by_test_id("upload-template-card").locator("a[href^='https://u3.mnge.co']")).to_have_count(0)
    assert page.evaluate("calls.posts.length") == 0
