"""Turn tracked video metrics into topic-generation guidance.

Reads the deduped video log (analytics.py) and, once a brand has enough
videos with real view counts, produces a small few-shot block that gets
appended to the topic prompt: titles that performed best, titles that
flopped. Brand-agnostic — the data does the steering, not the engine.

Guard rails:
- Requires MIN_SAMPLE videos with metrics before saying anything.
- Ignores videos younger than MIN_AGE_HOURS (early metrics are noise).
- Shorts only: longform view counts on a small channel reflect the format's
  missing distribution, not topic quality — a great topic that flopped as
  longform must not teach the topic LLM to avoid that subject.
- Ranks by views blended with retention (`avg_view_pct`, 0-100, filled
  manually from Studio via `python src/analytics.py retention ...`) when
  present — views alone can't tell a great video with weak packaging from
  a weak video the feed happened to seed harder.
"""

from datetime import datetime, timedelta

import analytics

MIN_SAMPLE = 5
MIN_AGE_HOURS = 48
TOP_N = 3
BOTTOM_N = 2
# Retention assumed for videos without a recorded avg_view_pct, so known
# values shift the ranking in either direction instead of only rewarding.
NEUTRAL_VIEW_PCT = 65.0


def _video_age_ok(entry: dict, now: datetime | None = None) -> bool:
    published = analytics._parse_date(entry.get("date", ""))
    if published is None:
        return True
    return published <= (now or datetime.now()) - timedelta(hours=MIN_AGE_HOURS)


def _performance_score(entry: dict) -> float:
    views = float(entry.get("views") or 0)
    pct = entry.get("avg_view_pct")
    try:
        pct = float(pct) if pct is not None else NEUTRAL_VIEW_PCT
    except (TypeError, ValueError):
        pct = NEUTRAL_VIEW_PCT
    return views * max(min(pct, 100.0), 0.0) / 100.0


def get_brand_performance(brand_id: str, now: datetime | None = None) -> list[dict]:
    """Uploaded Shorts for a brand with view counts, best first."""
    videos = analytics.dedupe_videos()
    scored = [
        v
        for v in videos
        if v.get("brand_id") == brand_id
        and v.get("views") is not None
        and v.get("url")
        and v.get("format") != "longform"
        and _video_age_ok(v, now=now)
    ]
    scored.sort(key=_performance_score, reverse=True)
    return scored


def _metrics_label(entry: dict) -> str:
    label = f"{entry.get('views', 0)} views"
    pct = entry.get("avg_view_pct")
    if pct is not None:
        label += f", {float(pct):.0f}% avg viewed"
    return label


def build_topic_insights_block(brand_id: str, now: datetime | None = None) -> str:
    """Prompt block steering topics toward what actually performed.

    Returns "" when there isn't enough data yet, so callers can append
    it unconditionally.
    """
    scored = get_brand_performance(brand_id, now=now)
    if len(scored) < MIN_SAMPLE:
        return ""

    top = scored[:TOP_N]
    bottom = [v for v in scored[TOP_N:][-BOTTOM_N:]]

    lines = [
        "",
        "PERFORMANCE DATA from this channel (use it to steer topic choice):",
        "These past videos performed BEST — favor topics with similar energy,",
        "specificity, and subject matter:",
    ]
    for v in top:
        lines.append(f'- "{v.get("title", "")[:90]}" ({_metrics_label(v)})')

    if bottom and _performance_score(bottom[-1]) < _performance_score(top[0]):
        lines.append("These performed WORST — avoid topics like these:")
        for v in bottom:
            lines.append(f'- "{v.get("title", "")[:90]}" ({_metrics_label(v)})')

    lines.append(
        "Do NOT reuse or lightly rephrase any of the above topics — generate "
        "a NEW topic that shares what made the winners work."
    )
    return "\n".join(lines)


def get_insights_summary(brand_id: str) -> dict:
    """Structured summary for dashboards: sample size, top/bottom performers."""
    scored = get_brand_performance(brand_id)
    return {
        "brand_id": brand_id,
        "sample_size": len(scored),
        "active": len(scored) >= MIN_SAMPLE,
        "min_sample": MIN_SAMPLE,
        "top": [
            {
                "title": v.get("title", ""),
                "views": v.get("views"),
                "avg_view_pct": v.get("avg_view_pct"),
                "url": v.get("url"),
            }
            for v in scored[:TOP_N]
        ],
        "bottom": [
            {
                "title": v.get("title", ""),
                "views": v.get("views"),
                "avg_view_pct": v.get("avg_view_pct"),
                "url": v.get("url"),
            }
            for v in scored[TOP_N:][-BOTTOM_N:]
        ],
    }
