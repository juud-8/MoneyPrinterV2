"""Turn optional brand manifest strategy into generation prompt guidance."""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Uploads within this many days count toward the near-duplicate topic check
# unless the manifest sets `content_strategy.recent_topic_days` (0 disables
# the time window and falls back to entry-count lookback only).
DEFAULT_RECENT_TOPIC_DAYS = 30
_MAX_DEDUPE_LABELS = 600


def _strategy(manifest: dict) -> dict:
    production = manifest.get("production") or {}
    value = production.get("content_strategy") or {}
    return value if isinstance(value, dict) else {}


def _recent_videos(manifest: dict) -> list[dict]:
    brand_id = manifest.get("brand_id", "")
    if not brand_id:
        return []
    try:
        import analytics

        return [
            video
            for video in analytics.dedupe_videos()
            if video.get("brand_id") == brand_id and video.get("status") == "uploaded"
        ]
    except Exception:
        return []


def recent_topic_labels(manifest: dict, limit: int | None = None) -> list[str]:
    """Return recent unique subjects AND titles for near-duplicate checks.

    A video counts as recent if it is inside the entry-count lookback
    (`recent_topic_lookback`) OR was uploaded within the last
    `recent_topic_days` days (default 30). Both windows exist because
    entry-count alone let the Emu War / Liechtenstein double-ups through:
    at 3 uploads/day, 12 entries is only ~4 days of history.
    """
    strategy = _strategy(manifest)
    configured = max(int(strategy.get("recent_topic_lookback") or 0), 0)
    lookback = configured if limit is None else max(int(limit), 0)
    days_raw = strategy.get("recent_topic_days", DEFAULT_RECENT_TOPIC_DAYS)
    days = max(int(days_raw if days_raw is not None else DEFAULT_RECENT_TOPIC_DAYS), 0)
    if lookback <= 0 and days <= 0:
        return []

    cutoff = (
        (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        if days > 0
        else ""
    )
    labels: list[str] = []
    for index, video in enumerate(_recent_videos(manifest)):
        in_lookback = lookback > 0 and index < lookback
        in_window = bool(cutoff) and (video.get("date") or "") >= cutoff
        if not in_lookback and not in_window:
            break  # _recent_videos is sorted newest-first
        for field in ("subject", "title"):
            if len(labels) >= _MAX_DEDUPE_LABELS:
                break
            label = (video.get(field) or "").strip()
            if label and label[:180] not in labels:
                labels.append(label[:180])
        if len(labels) >= _MAX_DEDUPE_LABELS:
            break
    if len(labels) >= _MAX_DEDUPE_LABELS:
        logger.warning(
            "Dedupe corpus at cap (%d) — older episodes are no longer "
            "protected from republication.",
            _MAX_DEDUPE_LABELS,
        )
    return labels


def build_topic_avoid_block(
    published: list[str],
    rejected_this_call: list[str] | None = None,
    max_published: int = 20,
    max_rejected: int = 8,
) -> str:
    """Prompt block listing stories the topic LLM must not pitch again.

    `published` labels were previously only used to reject candidates after
    generation, which let the LLM burn every attempt re-pitching the channel's
    existing catalog. Showing them in the prompt prevents the loop at the
    source. `rejected_this_call` adds within-run feedback so an idea rejected
    on attempt 1 isn't regenerated verbatim on attempts 2-7.
    """
    parts: list[str] = []
    published_clean = [p for p in (published or []) if p][:max_published]
    if published_clean:
        parts.append(
            "ALREADY PUBLISHED on this channel — do NOT pitch any of these "
            "events again, or reworded versions of them:\n"
            + "\n".join(f"- {p}" for p in published_clean)
        )
    rejected_clean = [r for r in (rejected_this_call or []) if r]
    if rejected_clean:
        parts.append(
            "These pitches were just REJECTED as near-duplicates of the list "
            "above — pick a COMPLETELY different historical incident, not "
            "another rewording:\n"
            + "\n".join(f"- {r}" for r in rejected_clean[-max_rejected:])
        )
    return "\n\n".join(parts)


def _choose_lane(lanes: list[dict], rng=None) -> dict | None:
    usable = [lane for lane in lanes if isinstance(lane, dict) and lane.get("name")]
    if not usable:
        return None
    weights = [max(float(lane.get("weight") or 0), 0.0) for lane in usable]
    if not any(weights):
        weights = [1.0] * len(usable)
    chooser = rng or random
    return chooser.choices(usable, weights=weights, k=1)[0]


def build_topic_strategy_block(manifest: dict, recent_videos: list[dict] | None = None, rng=None) -> str:
    """Return a prompt block for lane mix, novelty, and interaction intent."""
    strategy = _strategy(manifest)
    if not strategy:
        return ""

    lines = ["CONTENT STRATEGY FOR THIS RUN:"]
    lane = _choose_lane(strategy.get("topic_mix") or [], rng=rng)
    if lane:
        lines.append(f"- Selected lane: {lane['name']}.")
        if lane.get("guidance"):
            lines.append(f"  {lane['guidance']}")

    lookback = max(int(strategy.get("recent_topic_lookback") or 0), 0)
    recent = (recent_videos if recent_videos is not None else _recent_videos(manifest))[:lookback]
    labels = []
    for video in recent:
        label = (video.get("subject") or video.get("title") or "").strip()
        if label and label not in labels:
            labels.append(label[:120])
    if labels:
        lines.append(
            f"- Novelty guardrail: do not cover the same event, person-event pairing, "
            f"or incident as any of the last {len(labels)} uploads:"
        )
        lines.extend(f'  - "{label}"' for label in labels)

    interaction = strategy.get("interaction_intent")
    if interaction:
        lines.append(f"- Interaction intent: {interaction}")
    return "\n".join(lines) if len(lines) > 1 else ""


def script_engagement_instruction(manifest: dict) -> str:
    value = _strategy(manifest).get("script_engagement_instruction")
    return str(value).strip() if value else ""
