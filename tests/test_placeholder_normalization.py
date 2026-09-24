"""
Unit tests for placeholder normalization in briefing_parser.py.
Verifies:
1. Full square bracket support ([Loan Amount], [ROI], [Tenure], [EMI], [Client Name]).
2. Sequential variable renumbering without collisions when existing {{1}} variables are mixed with <name>.
3. Out-of-order and duplicate variables are resolved to strict Meta sequential numbering.
4. Markdown links and CTA keywords in brackets are preserved.
"""

from briefing_parser import normalize_placeholders


def test_square_bracket_normalization():
    """Verify various square bracket parameters are converted to sequential {{1}}, {{2}}..."""
    text = (
        "Dear [Client Name], your pre-approved loan of ₹[Loan Amount] is ready at "
        "[ROI] ROI for a tenure of [Tenure]. EMI is ₹[EMI]. Visit [Branch] branch in [City]."
    )
    normalized, samples = normalize_placeholders(text)
    assert normalized == (
        "Dear {{1}}, your pre-approved loan of ₹{{2}} is ready at "
        "{{3}} ROI for a tenure of {{4}}. EMI is ₹{{5}}. Visit {{6}} branch in {{7}}."
    )
    assert len(samples) == 7
    assert samples[0] == "Rahul"
    assert samples[1] == "5,00,000"
    assert samples[2] == "8.5%"
    assert samples[3] == "24 months"
    assert samples[4] == "15,000"
    assert samples[5] == "Andheri"
    assert samples[6] == "Mumbai"


def test_mixed_existing_variables_and_informal_placeholders():
    """Verify that existing {{1}} placeholders mixed with <name> do not produce collisions."""
    text = "Dear <name>, your loan of Rs. {{1}} is approved at {{2}} interest."
    normalized, samples = normalize_placeholders(text)
    assert normalized == "Dear {{1}}, your loan of Rs. {{2}} is approved at {{3}} interest."
    assert len(samples) == 3
    assert samples[0] == "Rahul"
    assert samples[1] == "5,00,000"
    assert samples[2] == "8.5%"


def test_duplicate_and_out_of_order_placeholders():
    """Verify duplicate and out-of-order placeholders are re-indexed strictly 1..N."""
    text = "Dear {{2}}, congratulations {{2}}! Your loan of Rs. {{1}} is ready."
    normalized, samples = normalize_placeholders(text)
    assert normalized == "Dear {{1}}, congratulations {{2}}! Your loan of Rs. {{3}} is ready."
    assert len(samples) == 3


def test_markdown_links_and_cta_brackets_preserved():
    """Verify markdown links and CTA keywords in brackets are not replaced with {{1}}."""
    text = (
        "Dear <name>, apply now at [Tata Capital Portal](https://www.tatacapital.com) "
        "or [Click Here] to view your [Loan Amount]."
    )
    normalized, samples = normalize_placeholders(text)
    assert "https://www.tatacapital.com" in normalized
    assert "[Tata Capital Portal](https://www.tatacapital.com)" in normalized
    assert "[Click Here]" in normalized
    assert "{{1}}" in normalized
    assert "{{2}}" in normalized
    # Only <name> and [Loan Amount] should become variables
    assert len(samples) == 2
    assert samples[0] == "Rahul"
    assert samples[1] == "5,00,000"
