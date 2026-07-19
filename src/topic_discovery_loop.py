"""Opt-in trending-topic injection into Shorts topic generation.

Design (brand-agnostic):
- Default OFF — generation is unchanged unless a brand or env opts in.
- When enabled, fetch trend candidates via ``trend_discovery`` and blend them
  into the topic prompt / candidate pool, then reuse ``topic_scoring.pick_best``.
- Failures degrade to normal LLM topic generation (never block a run).

Opt-in (any one):
- Brand ``production.use_trending_topics: true``
- Env ``MPV2_USE_TRENDING_TOPICS=1``
"""

from __future__ import annotations

import os
from typing import Callable

from topic_scoring import pick_best, score_title


def trending_topics_enabled(
    production: dict | None = None,
    *,
    env: dict | None = None,
) -> bool:
    """True when brand production or env opts into trend-seeded topics."""
    env_map = env if env is not None else os.environ
    if str(env_map.get("MPV2_USE_TRENDING_TOPICS") or "").strip() == "1":
        return True
    if isinstance(production, dict) and production.get("use_trending_topics") is True:
        return True
    return False


def build_trend_seed_block(topics: list[str], *, max_topics: int = 5) -> str:
    """Format trend candidates for injection into a topic prompt."""
    cleaned = [t.strip() for t in topics if t and str(t).strip()][:max_topics]
    if not cleaned:
        return ""
    listing = "\n".join(f"- {t}" for t in cleaned)
    return (
        "Current niche-relevant search trends (optional inspiration — do not "
        "force a trend if none fit a historically grounded story):\n"
        f"{listing}\n"
        "Prefer a specific real event over a vague trend phrase."
    )


def select_topic_from_pools(
    llm_candidates: list[str],
    trend_candidates: list[str] | None = None,
    *,
    scorer: Callable[[str], float] = score_title,
) -> str:
    """Pick the best topic across LLM drafts and optional trend phrases.

    Trend phrases are scored with a small penalty so a strong LLM candidate
    still wins over a generic rising query, while a sharp trend can surface.
    """
    scored: list[tuple[float, str]] = []
    for text in llm_candidates or []:
        clean = (text or "").strip()
        if clean:
            scored.append((scorer(clean), clean))
    for text in trend_candidates or []:
        clean = (text or "").strip()
        if clean:
            scored.append((scorer(clean) - 8.0, clean))
    if not scored:
        return pick_best(list(llm_candidates or []) + list(trend_candidates or []))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def fetch_trend_seeds_for_niche(
    niche: str,
    *,
    fetcher: Callable[[str], list[str]] | None = None,
) -> list[str]:
    """Fetch trend seeds; never raises — returns [] on failure."""
    fetch = fetcher
    if fetch is None:
        from trend_discovery import fetch_trending_topics

        fetch = fetch_trending_topics
    try:
        return list(fetch(niche) or [])
    except Exception:
        return []
