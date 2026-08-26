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


def lint_and_fix_body(text: str) -> tuple[str, list[dict]]:
    """
    Analyze text for grammatical mistakes, repeated words, spelling typos,
    punctuation spacing, and Meta automated rejection patterns.
    Returns (cleaned_text, list_of_warnings).
    """
    if not text or not text.strip():
        return text, []

    warnings = []
    cleaned = text

    # Protect URLs and Emails before punctuation and grammar linting
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

    # 1. Repeated adjacent words (e.g. 'the the', 'to to', 'you you')
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

    # 2. Common spelling typos
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

    # 3. Missing space after punctuation (e.g. "customer,you" -> "customer, you")
    def fix_missing_space(m):
        prev_char = m.group(1)
        punct = m.group(2)
        next_char = m.group(3)
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

    # 4. Multiple consecutive punctuation (e.g. "!!" -> "!", "??" -> "?")
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

    # 5. Sentence start capitalization (e.g. ". you have" -> ". You have")
    def fix_sentence_start(m):
        full = m.group(0)
        prefix = m.group(1)  # ". " or "\n"
        char = m.group(2)
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

    cleaned = re.sub(r"([.!?]\s+|\n+)([a-z])", fix_sentence_start, cleaned)

    # 6. Meta Compliance: Floating variable at end (e.g. "claim {{2}}")
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

    # 7. Meta Compliance: Adjacent variables (e.g. "{{1}}{{2}}")
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
    # Restore protected URLs and Emails
    for k, v in tokens.items():
        cleaned = cleaned.replace(k, v)

    return cleaned, warnings


def validate_meta_technical_compliance(
    body_text: str = "",
    header_text: str | None = None,
    footer_text: str | None = None,
    buttons: list | None = None,
    header_format: str | None = None,
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

    return compliance_warnings
