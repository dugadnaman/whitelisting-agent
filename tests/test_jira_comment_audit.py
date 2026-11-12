"""Explicit additional WhatsApp copy in Jira comments must not be ignored."""

from briefing_parser import parse_jira_brief


def test_additional_whatsapp_comment_keeps_unnumbered_first_copy_and_variants():
    copies = [
        f"Dear {{{{1}}}},\nService update {i}: please use Tata Capital's official channels to review your account details. "
        "You can find information about your existing account and contact customer support through the official website."
        for i in range(1, 4)
    ]
    comment = "PFB a few more WhatsApp templates for whitelisting.\n\n" + copies[0] + "\n\n" + "\n\n".join(
        "1.\n\n" + copy for copy in copies[1:]
    )
    parsed = parse_jira_brief({
        "key": "TCN-999", "summary": "WA utility whitelisting", "description_text": "Please see additional copy in comments.",
        "attachments": [], "comments": [{"id": "revision-1", "author": "Copy reviewer", "body_text": comment}],
    }, download_creatives=False)
    drafts = [draft for draft in parsed.whatsapp_templates if draft["source_origin"].startswith("comment")]
    assert [draft["body"] for draft in drafts] == copies
    assert all(draft["template_name"].startswith("att_") for draft in drafts)


def test_status_comment_without_customer_copy_does_not_create_template():
    parsed = parse_jira_brief({
        "key": "TCN-999", "summary": "WA utility whitelisting", "description_text": "Please check the ticket status.",
        "attachments": [], "comments": [{"id": "status-1", "author": "Reviewer", "body_text": "Please whitelist the pending WhatsApp templates after approval. There are three variants in the original attachment."}],
    }, download_creatives=False)
    assert not [draft for draft in parsed.whatsapp_templates if draft["source_origin"].startswith("comment")]


def test_replacement_comment_does_not_append_old_and_new_copy_as_additional():
    parsed = parse_jira_brief({
        "key": "TCN-999", "summary": "WA utility whitelisting", "description_text": "Please see the attached copy.",
        "attachments": [], "comments": [{
            "id": "replacement-1", "body_text": "Please whitelist this WhatsApp copy instead and delete the former.\nDear Customer, please use Tata Capital's official channels to review your account information and contact customer support for help with your existing loan."
        }],
    }, download_creatives=False)
    assert not [draft for draft in parsed.whatsapp_templates if draft["source_origin"].startswith("comment")]
