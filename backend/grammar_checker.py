"""
Grammar, Spelling & Meta Template Quality Linter.
Detects repeated words, spelling typos, punctuation spacing, capitalization,
and Meta rejection rules (floating end variables, adjacent variable tokens).
Provides automatic, compliant suggested corrections before submission.
"""

import re

URL_PATTERN = re.compile(
    r"https?://[^\s]+"
    r"|www\.[^\s]+"
    r"|\b[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*\.(?:com|in|org|net|co|io|biz|info|ai|app|gov|edu)(?:/[^\s]*)?",
    re.IGNORECASE,
)
EMAIL_PATTERN = re.compile(
    r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",
    re.IGNORECASE,
)

COMMON_FINANCIAL_TYPOS = {
    "recieved": "received",
    "recieve": "receive",
    "definately": "definitely",
    "seperate": "separate",
    "applicaiton": "application",
    "applicaion": "application",
    "aplication": "application",
    "eligibile": "eligible",
    "eligibilty": "eligibility",
    "disbursment": "disbursement",
    "disbursed": "disbursed",
    "acount": "account",
    "accout": "account",
    "succesfully": "successfully",
    "succesful": "successful",
    "congratualtions": "congratulations",
    "congrats": "congratulations",
    "intrest": "interest",
    "availible": "available",
    "avalable": "available",
    "messsage": "message",
    "mesage": "message",
    "verifcation": "verification",
    "instanly": "instantly",
    "preapproved": "pre-approved",
    "pre-approvd": "pre-approved",
    "repayment": "repayment",
    "re-payment": "repayment",
    "dont": "don't",
    "cant": "can't",
    "wont": "won't",
    "teh": "the",
    "adn": "and",
    "thier": "their",
    "occured": "occurred",
    "reccomend": "recommend",
    "reccommend": "recommend",
}


def _lint_repeated_and_typos(cleaned: str, warnings: list[dict]) -> str:
    def fix_repeated_words(m):
        word = m.group(1)
        warnings.append(
            {
                "type": "REPEATED_WORD",
                "issue": f'Repeated word: "{m.group(0)}"',
                "suggestion": f'Change to "{word}"',
                "original": m.group(0),
                "replacement": word,
            }
        )
        return word

    cleaned = re.sub(r"\b([a-zA-Z]{2,})\s+\1\b", fix_repeated_words, cleaned, flags=re.IGNORECASE)

    for typo, correction in COMMON_FINANCIAL_TYPOS.items():
        pattern = rf"\b{typo}\b"
        if re.search(pattern, cleaned, flags=re.IGNORECASE):

            def repl_typo(m, corr=correction):
                orig = m.group(0)
                repl = corr.upper() if orig.isupper() else (corr.capitalize() if orig.istitle() else corr)
                warnings.append(
                    {
                        "type": "SPELLING_TYPO",
                        "issue": f'Spelling typo: "{orig}"',
                        "suggestion": f'Change to "{repl}"',
                        "original": orig,
                        "replacement": repl,
                    }
                )
                return repl

            cleaned = re.sub(pattern, repl_typo, cleaned, flags=re.IGNORECASE)
    return cleaned


def _lint_punctuation_and_caps(cleaned: str, warnings: list[dict]) -> str:
    def fix_missing_space(m):
        prev_char, punct, next_char = m.group(1), m.group(2), m.group(3)
        warnings.append(
            {
                "type": "PUNCTUATION_SPACING",
                "issue": f'Missing space after punctuation: "{prev_char}{punct}{next_char}"',
                "suggestion": f'Change to "{prev_char}{punct} {next_char}"',
                "original": f"{prev_char}{punct}{next_char}",
                "replacement": f"{prev_char}{punct} {next_char}",
            }
        )
        return f"{prev_char}{punct} {next_char}"

    cleaned = re.sub(r"([a-zA-Z])([.,!?:;])([a-zA-Z])", fix_missing_space, cleaned)

    def fix_multi_punct(m):
        char = m.group(1)[0]
        warnings.append(
            {
                "type": "PUNCTUATION_REDUNDANT",
                "issue": f'Multiple punctuation: "{m.group(0)}"',
                "suggestion": f'Change to "{char}"',
                "original": m.group(0),
                "replacement": char,
            }
        )
        return char

    cleaned = re.sub(r"([!?]){2,}", fix_multi_punct, cleaned)

    def fix_sentence_start(m):
        full, prefix, char = m.group(0), m.group(1), m.group(2)
        capitalized = char.upper()
        if char != capitalized:
            warnings.append(
                {
                    "type": "CAPITALIZATION",
                    "issue": f'Sentence begins with lowercase letter: "{char}"',
                    "suggestion": f'Capitalize to "{prefix}{capitalized}"',
                    "original": full,
                    "replacement": f"{prefix}{capitalized}",
                }
            )
            return f"{prefix}{capitalized}"
        return full

    return re.sub(r"([.!?]\s+|\n+)([a-z])", fix_sentence_start, cleaned)


def _lint_meta_variable_rules(cleaned: str, warnings: list[dict]) -> str:
    if re.search(r"\{\{\d+\}\}\s*$", cleaned.strip()):
        warnings.append(
            {
                "type": "META_FLOATING_VARIABLE",
                "issue": "Floating dynamic variable at the end of body without closing punctuation.",
                "suggestion": "Add a period after the variable (e.g. '{{2}}.') to prevent Meta automated rejection.",
                "original": cleaned.strip()[-6:],
                "replacement": cleaned.strip()[-6:] + ".",
            }
        )
        cleaned = cleaned.strip() + "."

    if re.search(r"\{\{\d+\}\}\s*\{\{\d+\}\}", cleaned):
        warnings.append(
            {
                "type": "META_ADJACENT_VARIABLES",
                "issue": "Adjacent variables without separating space (e.g. {{1}}{{2}}).",
                "suggestion": "Separate variables (e.g. '{{1}} of {{2}}') to avoid Meta automated rejection.",
                "original": "{{1}}{{2}}",
                "replacement": "{{1}} {{2}}",
            }
        )
        cleaned = re.sub(r"(\{\{\d+\}\})\s*(\{\{\d+\}\})", r"\1 \2", cleaned)
    return cleaned


def lint_and_fix_body(text: str) -> tuple[str, list[dict]]:
    """
    Analyze text for grammatical mistakes, repeated words, spelling typos,
    punctuation spacing, and Meta automated rejection patterns.
    Returns (cleaned_text, list_of_warnings).
    """
    if not text or not text.strip():
        return text, []

    warnings: list[dict] = []
    cleaned = text
    tokens: dict[str, str] = {}

    def repl_email(m: re.Match) -> str:
        raw = m.group(0)
        key = f"__PRT_EML_{len(tokens)}__"
        tokens[key] = raw
        return key

    cleaned = EMAIL_PATTERN.sub(repl_email, cleaned)

    def repl_url(m: re.Match) -> str:
        raw = m.group(0)
        trailing = ""
        while raw and raw[-1] in ".,!?;:)":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        key = f"__PRT_URL_{len(tokens)}__"
        tokens[key] = raw
        return key + trailing

    cleaned = URL_PATTERN.sub(repl_url, cleaned)
    cleaned = _lint_repeated_and_typos(cleaned, warnings)
    cleaned = _lint_punctuation_and_caps(cleaned, warnings)
    cleaned = _lint_meta_variable_rules(cleaned, warnings)

    for k, v in tokens.items():
        cleaned = cleaned.replace(k, v)

    return cleaned, warnings


def validate_meta_technical_compliance(
    body_text: str = "",
    header_text: str | None = None,
    footer_text: str | None = None,
    buttons: list | None = None,
    header_format: str | None = None,
    declared_category: str | None = None,
    use_ai: bool = False,
    client: str = "bajaj",
) -> list[dict]:
    """
    Validate technical Meta WhatsApp and RCS compliance rules (Semantic Memory).
    Checks:
    1. Word-to-variable ratio limit (Meta Error 2388293)
    2. Variable formatting (sequential index {{1}}, {{2}})
    3. Consecutive line breaks (max 2)
    4. Header text length (max 60)
    5. Footer text length (max 60)
    6. Button text length (max 25) and URL validation
    7. TypeSafe AI semantic category & policy compliance (optional when use_ai=True)
    """
    compliance_warnings = []

    # 1. Word-to-Variable Ratio Check (Meta Error 2388293)
    if body_text and body_text.strip():
        var_matches = re.findall(r"\{\{\d+\}\}", body_text)
        var_count = len(var_matches)
        if var_count > 0:
            # Strip variable tags to count fixed words
            text_without_vars = re.sub(r"\{\{\d+\}\}", " ", body_text)
            words = [w for w in re.findall(r"\b\w+\b", text_without_vars) if len(w) > 0]
            word_count = len(words)
            ratio = word_count / var_count if var_count > 0 else 0

            if word_count < 3 or ratio < 2.5:
                compliance_warnings.append(
                    {
                        "type": "META_WORD_RATIO",
                        "severity": "error",
                        "issue": (
                            f"Parameters words ratio too low ({word_count} fixed words for {var_count} variable{'s' if var_count > 1 else ''}, ratio {ratio:.1f}:1). "
                            "Meta rejects templates with error 2388293 when text is too sparse relative to variables."
                        ),
                        "recommendation": f"Add at least {max(3, int(var_count * 3) - word_count)} more fixed explanatory words around the variables.",
                    }
                )

        # 2. Sequential Indexing Check
        indexes = [int(m.strip("{}")) for m in var_matches]
        if indexes:
            expected = list(range(1, len(indexes) + 1))
            if indexes != expected:
                compliance_warnings.append(
                    {
                        "type": "NON_SEQUENTIAL_VARIABLES",
                        "severity": "warning",
                        "issue": f"Variables are non-sequential ({[f'{{{{{i}}}}}' for i in indexes]}). Expected: {[f'{{{{{i}}}}}' for i in expected]}.",
                        "recommendation": "The system will auto-normalize variable indices sequentially during submission.",
                    }
                )

        # 3. Consecutive Line Breaks (Meta Rule: max 2 newlines)
        if "\n\n\n" in body_text or "\r\n\r\n\r\n" in body_text:
            compliance_warnings.append(
                {
                    "type": "EXCESSIVE_LINEBREAKS",
                    "severity": "warning",
                    "issue": "Body contains 3 or more consecutive line breaks.",
                    "recommendation": "Meta enforces a maximum of 2 consecutive line breaks (auto-compacted on submit).",
                }
            )

    # 4. Header length limit (max 60 chars)
    if header_text and header_format == "TEXT":
        h_len = len(header_text.strip())
        if h_len > 60:
            compliance_warnings.append(
                {
                    "type": "HEADER_LENGTH_LIMIT",
                    "severity": "error",
                    "issue": f"Header text exceeds Meta limit of 60 characters ({h_len} chars).",
                    "recommendation": f"Shorten header text by {h_len - 60} characters.",
                }
            )

    # 5. Footer length limit (max 60 chars)
    if footer_text:
        f_len = len(footer_text.strip())
        if f_len > 60:
            compliance_warnings.append(
                {
                    "type": "FOOTER_LENGTH_LIMIT",
                    "severity": "error",
                    "issue": f"Footer text exceeds Meta limit of 60 characters ({f_len} chars).",
                    "recommendation": f"Shorten footer text by {f_len - 60} characters.",
                }
            )

    # 6. Button text length (max 25 chars) and URL validation
    if buttons and isinstance(buttons, list):
        for idx, btn in enumerate(buttons):
            b_text = btn.get("text", "") if isinstance(btn, dict) else getattr(btn, "text", "")
            if b_text and len(str(b_text).strip()) > 25:
                compliance_warnings.append(
                    {
                        "type": "BUTTON_LENGTH_LIMIT",
                        "severity": "error",
                        "issue": f"Button #{idx + 1} text exceeds 25 characters ({len(str(b_text).strip())} chars: '{b_text}').",
                        "recommendation": "Shorten button text to 25 characters or fewer.",
                    }
                )
            b_url = btn.get("url", "") if isinstance(btn, dict) else getattr(btn, "url", "")
            if b_url and " " in str(b_url).strip():
                compliance_warnings.append(
                    {
                        "type": "BUTTON_URL_INVALID",
                        "severity": "error",
                        "issue": f"Button #{idx + 1} URL contains spaces ('{b_url}').",
                        "recommendation": "Remove spaces or URL-encode the destination link.",
                    }
                )

    # 7. TypeSafe AI Semantic Validation (Category mismatch, rejection risk, floating variables)
    if use_ai and body_text and body_text.strip():
        try:
            from template_validator import validate_template_semantic_quality

            ai_rep = validate_template_semantic_quality(
                body_text=body_text,
                declared_category=declared_category or "MARKETING",
                header_text=header_text,
                footer_text=footer_text,
                buttons=buttons,
                client=client,
                allow_ai=True,
            )
            if ai_rep.ai_checked and ai_rep.warnings:
                compliance_warnings.extend(ai_rep.warnings)
        except Exception:
            # Gracefully ignore AI errors to avoid failing rule-based compliance
            pass

    return compliance_warnings


def validate_template_pre_submission(
    body_text: str = "",
    declared_category: str = "MARKETING",
    header_text: str | None = None,
    footer_text: str | None = None,
    buttons: list | None = None,
    header_format: str | None = None,
    use_ai: bool = True,
    client: str = "bajaj",
) -> dict:
    """
    Complete pre-submission audit combining:
    1. Grammar & spelling linter with auto-corrections
    2. Technical rule-based Meta compliance
    3. TypeSafe AI category classification, rejection risk scoring, and policy checks
    """
    cleaned_body, grammar_warnings = lint_and_fix_body(body_text) if body_text else ("", [])

    tech_warnings = validate_meta_technical_compliance(
        body_text=cleaned_body or body_text,
        header_text=header_text,
        footer_text=footer_text,
        buttons=buttons,
        header_format=header_format,
        declared_category=declared_category,
        use_ai=False,  # Checked separately below for full report visibility
        client=client,
    )

    ai_report_dict = None
    ai_warnings: list[dict] = []
    category_mismatch = False
    predicted_cat = (declared_category or "MARKETING").strip().upper()
    rejection_risk_lvl = "SAFE"

    if use_ai and (cleaned_body or body_text):
        try:
            from template_validator import validate_template_semantic_quality

            ai_rep = validate_template_semantic_quality(
                body_text=cleaned_body or body_text,
                declared_category=declared_category,
                header_text=header_text,
                footer_text=footer_text,
                buttons=buttons,
                client=client,
                allow_ai=True,
            )
            ai_report_dict = ai_rep.to_dict()
            ai_warnings = ai_rep.warnings
            category_mismatch = ai_rep.category_mismatch
            predicted_cat = ai_rep.predicted_category
            rejection_risk_lvl = ai_rep.rejection_risk_level
        except Exception:
            pass

    # Ensure all grammar warnings have a severity for uniform consumption
    for gw in grammar_warnings:
        if "severity" not in gw:
            gw["severity"] = "warning"

    all_warnings = grammar_warnings + tech_warnings + ai_warnings
    is_safe = not any(w.get("severity") == "error" for w in all_warnings)
    return {
        "original_body": body_text,
        "cleaned_body": cleaned_body,
        "declared_category": (declared_category or "MARKETING").strip().upper(),
        "predicted_category": predicted_cat,
        "category_mismatch": category_mismatch,
        "rejection_risk_level": rejection_risk_lvl,
        "grammar_warnings": grammar_warnings,
        "technical_warnings": tech_warnings,
        "ai_warnings": ai_warnings,
        "all_warnings": all_warnings,
        "is_safe_to_submit": is_safe,
        "ai_report": ai_report_dict,
    }
