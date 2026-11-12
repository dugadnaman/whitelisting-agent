"""Jira message variants remain separate before CTA/placeholder extraction."""

from briefing_parser import parse_jira_brief
from jira_client import adf_to_text


def issue(description, **overrides):
    return {
        "key": "TCN-999", "summary": "Whitelisting WA - utility content",
        "description_text": description, "attachments": [], "comments": [], **overrides,
    }


def test_standalone_option_headings_produce_fifteen_independent_messages():
    copies = [
        f"Dear Customer,\nSafety message {i}: please verify communications claiming to be from Tata Capital. "
        "Always use official channels and do not share personal information with unverified callers.\nTata Capital Limited"
        for i in range(1, 16)
    ]
    description = "Please whitelist these utility options.\n\u00a0\n" + "\n\u00a0\n".join(
        f"Option {i}\n{copy}" for i, copy in enumerate(copies, 1)
    )
    parsed = parse_jira_brief(issue(description), download_creatives=False)
    assert [draft["body"] for draft in parsed.whatsapp_templates] == copies
    assert parsed.channel_counts["whatsapp"] == 15
    assert len({draft["template_name"] for draft in parsed.whatsapp_templates}) == 15
    assert all(draft["template_name"].startswith("att_") for draft in parsed.whatsapp_templates)


def test_restarted_adf_numbering_keeps_four_messages_and_shared_creative(tmp_path):
    creative = tmp_path / "app-download.jpg"
    creative.write_bytes(b"local-creative-reference")
    copies = [
        f"Hi {{#Name#}},\nApp message {i}: your available funds can be accessed using the Tata Capital App. "
        "Check your loan balance, manage payments and review your account whenever you need it.\n"
        "Download Now: <link>\nT&Cs Apply <link>"
        for i in range(1, 5)
    ]
    content = [{"type": "paragraph", "content": [{"type": "text", "text": "Please whitelist the attached image with the content below."}]}]
    for index, copy in enumerate(copies):
        content.append({"type": "orderedList", "attrs": {"order": 1}, "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": (
                [] if index < 2 else [{"type": "text", "text": copy.split("\n", 1)[0]}]
            )}]}
        ]})
        rest = copy if index < 2 else copy.split("\n", 1)[1]
        content.extend({"type": "paragraph", "content": [{"type": "text", "text": line}]} for line in rest.splitlines())
    adf = {"type": "doc", "version": 1, "content": content}
    parsed = parse_jira_brief(issue(adf_to_text(adf), description_raw=adf, attachments=[{
        "id": "local-image", "filename": creative.name, "local_path": str(creative), "mimeType": "image/jpeg",
    }]), download_creatives=False)
    drafts = parsed.whatsapp_templates
    assert len(drafts) == 4
    assert [draft["raw_source"].split() for draft in drafts] == [copy.split() for copy in copies]
    for index, draft in enumerate(drafts, 1):
        assert f"App message {index}:" in draft["body"]
        assert draft["body"].startswith("Hi {{1}}")
        assert draft["button_url"] == "https://www.tatacapital.com/{{1}}"
        assert draft["header_type"] == "IMAGE"
        assert draft["media_file"] == str(creative)
        assert draft["media_attachment_id"] == "local-image"


def test_numbered_features_inside_one_message_do_not_create_templates():
    copy = (
        "Hi Customer, your Tata Capital loan can be managed in the app whenever you need it.\n"
        "1. Check the available balance and view the latest statement for your account.\n"
        "2. Make payments and review your account details with secure access.\n"
        "Download Now: <link>"
    )
    parsed = parse_jira_brief(issue(copy), download_creatives=False)
    assert len(parsed.whatsapp_templates) == 1
    assert parsed.whatsapp_templates[0]["raw_source"] == copy
