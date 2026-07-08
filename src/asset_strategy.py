"""Per-shot asset tier policy.

Decides, per shot, whether to spend on a premium still image or a premium
AI-generated video clip instead of the default ("standard") still image.

This is brand-configurable (via the brand manifest's `production.asset_strategy`)
rather than hardcoded by brand name or id — consistent with `content_styles.py`.

Pilot scope (intentional): only the "hook" shot — the first shot of a Short,
the highest-leverage 3-5 seconds for retention — is eligible for escalation
today. Everything else stays "standard". Expand the set of recognized shot
roles once this pilot proves worth it in the weekly analytics review (see
`analytics.py`).

A brand opts in explicitly in its manifest, e.g.:

    "production": {
      "asset_strategy": {
        "hook": "premium_video"
      }
    }

Nothing changes for brands that don't set this — the engine default for
every shot role is "standard", so this feature is zero-risk until a brand
manifest explicitly turns it on.
"""

from brand_switcher import get_production_setting

VALID_TIERS = {"standard", "premium_image", "premium_video"}

DEFAULT_ASSET_STRATEGY = {
    "hook": "standard",
    "default": "standard",
}


def get_asset_strategy() -> dict:
    """Brand-configured asset strategy, merged over the engine defaults."""
    configured = get_production_setting("asset_strategy", {}) or {}
    if not isinstance(configured, dict):
        configured = {}

    merged = dict(DEFAULT_ASSET_STRATEGY)
    for role, tier in configured.items():
        if isinstance(tier, str) and tier in VALID_TIERS:
            merged[role] = tier
    return merged


def tier_for_shot_role(role: str) -> str:
    """
    Resolve the asset tier for a given shot role.

    Args:
        role (str): "hook" for the first shot of a Short; "default" for
            every other shot (the only roles recognized today).

    Returns:
        tier (str): "standard" | "premium_image" | "premium_video"
    """
    strategy = get_asset_strategy()
    return strategy.get(role, strategy["default"])


def shot_role_for_index(index: int) -> str:
    """Map a shot's position in the prompt list to a role. Pilot only
    distinguishes the very first shot ("hook") from everything else."""
    return "hook" if index == 0 else "default"
