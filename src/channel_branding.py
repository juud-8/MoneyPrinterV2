"""Load per-channel branding, niche, and funnel configuration."""

from brand_switcher import load_active_brand


def load_channel_config() -> dict:
    """Load the active brand manifest."""
    return load_active_brand()


def get_channel_niche() -> str:
    cfg = load_channel_config()
    return cfg.get("niche", "")


def get_channel_funnel() -> dict:
    cfg = load_channel_config()
    return cfg.get("funnel", {})


def get_channel_name() -> str:
    cfg = load_channel_config()
    return cfg.get("channel_name", "")


def get_publishing_config() -> dict:
    cfg = load_channel_config()
    return cfg.get("publishing", {"review_before_upload": True})
