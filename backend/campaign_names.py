"""Canonical names for new campaigns and whitelisting drafts, not provider readbacks."""

CAMPAIGN_PREFIX = "att_"


def normalize_campaign_name(value: str) -> str:
    name = value.strip()
    if not name:
        return ""
    if name[:len(CAMPAIGN_PREFIX)].lower() == CAMPAIGN_PREFIX:
        return CAMPAIGN_PREFIX + name[len(CAMPAIGN_PREFIX):]
    return CAMPAIGN_PREFIX + name


def require_campaign_name(value: object) -> str:
    if (not isinstance(value, str) or value != value.strip()
            or not value.startswith(CAMPAIGN_PREFIX) or not value[len(CAMPAIGN_PREFIX):].strip()):
        raise ValueError("Campaign name must start with att_ and include a non-empty name")
    return value
