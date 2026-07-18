"""Turn tracked video metrics into topic-generation guidance.

Reads the deduped video log (analytics.py) and, once a brand has enough
videos with real view counts, produces a small few-shot block that gets
appended to the topic prompt: titles that performed best, titles that
flopped, plus structural winning/flop DNA derived from that brand's data.
Brand-agnostic — the data does the steering, not the engine.

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

from __future__ import annotations

import re
from datetime import datetime, timedelta

import analytics

MIN_SAMPLE = 5
MIN_AGE_HOURS = 48
TOP_N = 3
BOTTOM_N = 2
# Retention assumed for videos without a recorded avg_view_pct, so known
# values shift the ranking in either direction instead of only rewarding.
NEUTRAL_VIEW_PCT = 65.0

# Emit a favor/avoid rule only when winner-rate − flop-rate clears this.
DNA_DELTA_THRESHOLD = 0.25
_YEAR_RE = re.compile(r"\b(?:1[0-9]{3}|20[0-2][0-9])\b")
_NUMBER_RE = re.compile(r"\b\d[\d,]*\b")
_HOW_OPEN_RE = re.compile(r"^\s*How\b", re.IGNORECASE)

# Always appended once a brand has enough sample — packaging shape, not niche.
_FIXED_DNA_RULES = (
    "Favor a tiny specific cause that produces an outsized ironic effect.",
    "Put a punchline number in the hook (a count, quantity, or paradoxical total).",
    "Do not rephrase the listed winners or flops — invent a NEW incident with the same energy.",
)

_FEATURE_SPECS: tuple[tuple[str, str, str], ...] = (
    (
        "how_open",
        'Prefer titles that open with "How".',
        'Avoid titles that do not open with "How" when a How-hook fits the story.',
    ),
    (
        "has_year",
        "Prefer hooks that include a specific year.",
        "Avoid hooks that omit a specific year when the incident is dated.",
    ),
    (
        "has_number",
        "Prefer a concrete countable number in the hook.",
        "Avoid hooks with no concrete number.",
    ),
    (
        "compact_title",
        "Prefer compact hooks (about 14 words or fewer before hashtags).",
        "Avoid long, multi-clause titles that bury the punchline.",
    ),
)


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


def _title_core(title: str) -> str:
    """Strip channel suffix and leading hashtag clutter for structural checks."""
    text = (title or "").strip()
    if " | " in text:
        text = text.rsplit(" | ", 1)[0].strip()
    # Drop trailing hashtag runs so word-count reflects the hook.
    text = re.sub(r"(?:\s+#\w+)+\s*$", "", text).strip()
    return text


def _structural_features(entry: dict) -> dict[str, bool]:
    title = _title_core(entry.get("title") or "")
    subject = (entry.get("subject") or "").strip()
    text = f"{title} {subject}".strip()
    return {
        "how_open": bool(_HOW_OPEN_RE.search(title)),
        "has_year": bool(_YEAR_RE.search(text)),
        "has_number": bool(_NUMBER_RE.search(text)),
        "compact_title": len(title.split()) <= 14 if title else False,
    }


def _feature_rate(entries: list[dict], key: str) -> float:
    if not entries:
        return 0.0
    return sum(1 for e in entries if _structural_features(e).get(key)) / len(entries)


def _tercile_cohorts(scored: list[dict]) -> tuple[list[dict], list[dict]]:
    """Top and bottom terciles; require at least 2 videos each."""
    n = len(scored)
    size = max(2, n // 3)
    winners = scored[:size]
    flops = scored[-size:]
    # If overlap (tiny sample), shrink until disjoint when possible.
    if n >= 4 and winners[-1] is flops[0]:
        size = max(2, size - 1)
        winners = scored[:size]
        flops = scored[-size:]
    return winners, flops


def derive_dna_rules(scored: list[dict]) -> list[str]:
    """Structural favor/avoid rules from winner vs flop deltas, plus fixed rules.

    Returns [] when there is not enough sample. Feature rules are only emitted
    when |winner_rate - flop_rate| >= DNA_DELTA_THRESHOLD.
    """
    if len(scored) < MIN_SAMPLE:
        return []

    winners, flops = _tercile_cohorts(scored)
    rules: list[str] = []
    for key, favor_text, avoid_text in _FEATURE_SPECS:
        delta = _feature_rate(winners, key) - _feature_rate(flops, key)
        if delta >= DNA_DELTA_THRESHOLD:
            rules.append(favor_text)
        elif delta <= -DNA_DELTA_THRESHOLD:
            rules.append(avoid_text)

    rules.extend(_FIXED_DNA_RULES)
    return rules


def _format_dna_section(rules: list[str]) -> list[str]:
    if not rules:
        return []
    lines = [
        "WINNING DNA from this channel's data (structural patterns — follow these):",
    ]
    for rule in rules:
        lines.append(f"- {rule}")
    return lines


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

    dna_rules = derive_dna_rules(scored)
    lines.extend(_format_dna_section(dna_rules))

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
        "dna_rules": derive_dna_rules(scored),
    }
