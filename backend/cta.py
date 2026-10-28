"""Shared URL CTA policy for whitelisting imports."""

import re


CTA_VARIABLE_PATTERN = re.compile(
    r"\{\{[^{}]+\}\}|<[^<>]+>|\[[^\[\]]+\]|\{[^{}]+\}|#[a-zA-Z0-9_\-]+#"
)


def ensure_dynamic_cta_url(url: str) -> str:
    """Keep the supplied destination prefix and require a runtime URL variable."""
    url = url.strip()
    if not url or CTA_VARIABLE_PATTERN.search(url):
        return url
    if re.fullmatch(r"https?://[^/?#]+", url):
        url += "/"
    return f"{url}{{{{1}}}}"


def normalize_whatsapp_cta_buttons(buttons: list) -> None:
    """Require dynamic URL buttons and concrete, destination-matched Meta samples."""
    for button in buttons:
        if isinstance(button, dict) and str(button.get("type") or "").upper() == "URL":
            raw_url = str(button.get("url") or "").strip()
            if not raw_url:
                continue
            was_dynamic = bool(CTA_VARIABLE_PATTERN.search(raw_url))
            url = CTA_VARIABLE_PATTERN.sub("{{1}}", ensure_dynamic_cta_url(raw_url))
            button["url"] = url
            examples = button.get("example")
            prefix = url.split("{{1}}", 1)[0]
            if not (
                was_dynamic
                and isinstance(examples, list)
                and examples
                and all(
                    isinstance(example, str)
                    and example.startswith(("https://", "http://"))
                    and example.startswith(prefix)
                    and not CTA_VARIABLE_PATTERN.search(example)
                    for example in examples
                )
            ):
                button["example"] = [url.replace("{{1}}", "sample")]
