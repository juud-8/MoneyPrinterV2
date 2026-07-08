"""Description funnel builder and affiliate/lead-magnet injection."""

from channel_branding import get_channel_funnel, load_channel_config
from config import get_channel_funnel_config


def _merge_funnel_sources() -> dict:
    """Merge config.json funnel with active brand funnel (brand wins when key is set)."""
    cfg_funnel = get_channel_funnel_config()
    channel_funnel = get_channel_funnel()
    merged = {}
    for key in set(cfg_funnel) | set(channel_funnel):
        if key in channel_funnel:
            value = channel_funnel[key]
            if value:
                merged[key] = value
        elif cfg_funnel.get(key):
            merged[key] = cfg_funnel[key]
    return merged


def build_description(
    script_description: str,
    subject: str = "",
    format_type: str = "short",
    include_affiliate: bool = True,
) -> str:
    """
    Build a monetization-optimized YouTube description.

    Affiliate link goes on line 1 per plan; disclosure and lead magnet follow.

    Note: YouTube Shorts description links have not been clickable since
    August 2023 — viewers can't tap through from a Short's description at
    all, only from the channel's "Links" panel or a long-form video's
    description. URLs are still included here for compliance (FTC/Amazon
    Associates disclosure must be present regardless of clickability) and
    searchability, but Shorts copy is worded to point viewers at the channel
    Links panel instead of implying the description link itself is tappable.
    """
    funnel = _merge_funnel_sources()
    parts = []

    affiliate = funnel.get("affiliate_link", "").strip()
    disclosure = funnel.get("affiliate_disclosure", "#ad").strip()
    lead_url = funnel.get("lead_magnet_url", "").strip()
    lead_cta = funnel.get("lead_magnet_cta", "Get the free toolkit").strip()
    product_url = funnel.get("digital_product_url", "").strip()
    product_cta = funnel.get("digital_product_cta", "").strip()

    is_short = format_type != "longform"
    link_note = " (tap the link in my channel bio — not clickable here on Shorts)" if is_short else ""

    if include_affiliate and affiliate:
        parts.append(f"🔗 {affiliate}{link_note}")
        if disclosure:
            parts.append(disclosure)

    parts.append("")
    parts.append(script_description.strip())

    if lead_url:
        parts.append("")
        parts.append(f"📥 {lead_cta}: {lead_url}{link_note}")

    if product_url and product_cta:
        parts.append(f"🛒 {product_cta}: {product_url}{link_note}")

    channel = load_channel_config()
    tagline = channel.get("tagline", "")
    if tagline:
        parts.append("")
        parts.append(f"— {channel.get('channel_name', 'This channel')}: {tagline}")

    if format_type == "longform" and subject:
        parts.append("")
        parts.append("📑 Chapters:")
        parts.append("(Auto-generated — edit timestamps after upload)")

    tags = channel.get("default_hashtags", "#Shorts")
    parts.append("")
    parts.append(tags.strip())

    return "\n".join(parts)
