"""Conservative entity normalization and cross-provider clustering."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from statistics import mean

from trend_models import TrendCluster, TrendSignal, new_id


KNOWN_ALIASES = {
    "american bison": {
        "american bison",
        "bison",
        "buffalo",
        "bisonte americano",
        "bison d'amérique",
    },
    "dance": {"dance", "dancing", "dance challenge"},
}


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold().strip()
    text = re.sub(r"(?<!\w)#", "", text)
    text = re.sub(r"[^\w\s-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 4 and text.endswith("s") and not text.endswith("ss"):
        text = text[:-1]
    return text


def resolve_entity(signal: TrendSignal) -> tuple[str, list[dict]]:
    combined = " ".join([signal.term, signal.normalized_entity, *signal.aliases, *signal.related_terms])
    normalized = normalize_text(signal.normalized_entity or signal.term)
    context = normalize_text(combined)

    if normalized == "buffalo" or "buffalo" in context:
        city_markers = {"new york", "ny", "bill", "sabre", "city"}
        animal_markers = {"bison", "animal", "species", "preservation", "mammal", "herd"}
        city_hits = [marker for marker in city_markers if marker in context]
        animal_hits = [marker for marker in animal_markers if marker in context]
        if city_hits and not animal_hits:
            return "buffalo, new york", []
        if animal_hits and not city_hits:
            return "american bison", []
        return "buffalo", [
            {"entity": "american bison", "reason": "Buffalo is a common animal alias", "confidence": 0.45},
            {"entity": "buffalo, new york", "reason": "Buffalo is also a city name", "confidence": 0.45},
        ]

    for canonical, aliases in KNOWN_ALIASES.items():
        if normalized in {normalize_text(alias) for alias in aliases}:
            return canonical, []
    return normalized, []


def _average_known(values: list[float | None]) -> float | None:
    known = [float(value) for value in values if value is not None]
    return mean(known) if known else None


def cluster_signals(signals: list[TrendSignal], now: str | None = None) -> list[TrendCluster]:
    groups: dict[str, list[tuple[TrendSignal, list[dict]]]] = {}
    for signal in signals:
        canonical, interpretations = resolve_entity(signal)
        groups.setdefault(canonical, []).append((signal, interpretations))

    current = datetime.fromisoformat((now or datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00"))
    clusters = []
    for canonical, members in groups.items():
        group_signals = [item[0] for item in members]
        times = [datetime.fromisoformat(signal.collected_at.replace("Z", "+00:00")) for signal in group_signals]
        providers = {signal.provider for signal in group_signals}
        velocity = _average_known([signal.velocity for signal in group_signals])
        search_signals = [signal for signal in group_signals if signal.provider in {"wikimedia", "youtube", "google_trends"}]
        search_score = _average_known([signal.velocity for signal in search_signals])
        news_signals = [signal for signal in group_signals if signal.provider == "gdelt"]
        news_score = min(100.0, sum(float(signal.raw_metadata.get("unique_domains") or 0) for signal in news_signals) * 15) if news_signals else None
        age_hours = max((current - max(times)).total_seconds() / 3600, 0)
        freshness = max(0.0, 100.0 - (age_hours / max(group_signals[0].window_hours, 1) * 100))
        interpretations = [value for _, values in members for value in values]
        unknowns = []
        if velocity is None:
            unknowns.append("trend velocity unavailable")
        if search_score is None:
            unknowns.append("search intent unavailable")
        if news_score is None:
            unknowns.append("news confirmation unavailable")
        if interpretations:
            unknowns.append("entity interpretation is ambiguous")
        confidence = min(1.0, 0.25 + 0.2 * len(providers) + 0.1 * sum(value is not None for value in (velocity, search_score, news_score)))
        known_velocities = [float(signal.velocity) for signal in group_signals if signal.velocity is not None]
        if len(known_velocities) >= 2 and max(known_velocities) - min(known_velocities) >= 50:
            unknowns.append("provider velocity signals materially disagree")
            confidence = max(0.0, confidence - 0.2)
        clusters.append(
            TrendCluster.from_dict(
                {
                    "cluster_id": new_id("cluster"),
                    "canonical_entity": canonical,
                    "aliases": list(dict.fromkeys(alias for signal in group_signals for alias in [signal.term, *signal.aliases])),
                    "entity_type": group_signals[0].entity_type,
                    "first_seen": min(times).isoformat(),
                    "last_seen": max(times).isoformat(),
                    "geographies": list(dict.fromkeys(signal.geography for signal in group_signals)),
                    "languages": list(dict.fromkeys(signal.language for signal in group_signals)),
                    "signals": group_signals,
                    "cross_source_count": len(providers),
                    "trend_velocity_score": velocity,
                    "search_intent_score": search_score,
                    "news_confirmation_score": news_score,
                    "freshness_score": freshness,
                    "confidence": confidence,
                    "competing_interpretations": interpretations,
                    "unknowns": unknowns,
                }
            )
        )
    return clusters
