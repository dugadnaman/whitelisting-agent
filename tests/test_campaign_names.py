"""Canonical campaign names are idempotent and strict at provider boundaries."""

import pytest

from campaign_names import normalize_campaign_name, require_campaign_name


@pytest.mark.parametrize("name,expected", [
    ("Diwali Loan", "att_Diwali Loan"),
    ("  Diwali Loan  ", "att_Diwali Loan"),
    ("att_Diwali Loan", "att_Diwali Loan"),
    ("ATT_Diwali Loan", "att_Diwali Loan"),
    ("AtT_Loan_2026", "att_Loan_2026"),
    ("att_att_Loan", "att_att_Loan"),
    ("attendance", "att_attendance"),
])
def test_campaign_prefix_is_applied_once_and_preserves_suffix(name, expected):
    assert normalize_campaign_name(name) == expected
    assert normalize_campaign_name(expected) == expected
    assert require_campaign_name(expected) == expected


@pytest.mark.parametrize("name", [None, 123, {}, "", " ", "Launch", "ATT_Launch", "att_", "att_  ", " att_Launch", "att_Launch "])
def test_writer_guard_rejects_noncanonical_or_empty_names(name):
    with pytest.raises(ValueError, match="att_"):
        require_campaign_name(name)


@pytest.mark.parametrize("name", ["", "  "])
def test_normalization_does_not_fabricate_a_missing_campaign_name(name):
    assert normalize_campaign_name(name) == ""
