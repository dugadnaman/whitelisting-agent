"""Shared URL CTA policy for whitelisting imports."""

import re
from urllib.parse import urlsplit


TATA_CTA_URL = "https://www.tatacapital.com/"
_TATA_ACCOUNTS = {"tata", "tcl_promo", "tcl_trans", "tchfl", "wealth", "moneyfy"}


CTA_VARIABLE_PATTERN = re.compile(
    r"\{\{[^{}]+\}\}|<[^<>]+>|\[[^\[\]]+\]|\{[^{}]+\}|#[a-zA-Z0-9_\-]+#"
)


def resolve_cta_url(url: str, client: str) -> str:
    """Replace Tata's MoEngage CTAs, preserving explicit real destinations."""
    url = url.strip()
    if client.strip().lower() not in _TATA_ACCOUNTS:
        return url
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme in {"http", "https"} and host:
            if any(host == root or host.endswith("." + root) for root in ("mnge.co", "moengage.com")):
                return TATA_CTA_URL + "".join(CTA_VARIABLE_PATTERN.findall(url))
            return url
    except ValueError:
        return url
    if not url or CTA_VARIABLE_PATTERN.fullmatch(url):
        return TATA_CTA_URL + url
    return url


def ensure_dynamic_cta_url(url: str) -> str:
    """Keep the supplied destination prefix and require a runtime URL variable."""
    url = url.strip()
    if not url or CTA_VARIABLE_PATTERN.search(url):
        return url
    if re.fullmatch(r"https?://[^/?#]+", url):
        url += "/"
    return f"{url}{{{{1}}}}"


def normalize_whatsapp_cta_buttons(buttons: list, client: str) -> None:
    """Require account-matched dynamic URL buttons and concrete Meta samples."""
    for button in buttons:
        if isinstance(button, dict) and str(button.get("type") or "").upper() == "URL":
            raw_url = resolve_cta_url(str(button.get("url") or ""), client)
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
