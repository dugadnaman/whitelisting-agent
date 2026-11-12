import pytest

import api


@pytest.mark.parametrize("channel", ["whatsapp", "rcs"])
def test_ambiguous_creative_mapping_blocks_preview_without_guessing_or_placeholder(channel):
    draft = {
        "template_name": "att_image_review", "body": "Dear Customer, your Tata Capital statement is ready for review using our official customer channels.",
        "header_type": "IMAGE", "template_type": "richcard", "media_pairing_ambiguous": True,
        "button_type": "NONE", "action_type": "NONE",
    }
    actual = api._jira_draft_input(draft, channel, "tcl_promo")
    preview = api._inspect_single_submission(actual, set(), {}, "tcl_promo", channel, use_ai=False)
    assert preview["aspect_ratio_blocked"] is True
    assert "ambiguous" in preview["aspect_ratio_block_reason"].lower()
