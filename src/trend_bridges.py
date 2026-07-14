"""Historical bridge prompting, validation, and source separation."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Callable

from trend_models import ArchiveBridge, TrendCluster, ValidationError


BridgeCompletion = Callable[[str], str]
HistoricalResearch = Callable[[str], list[dict]]


def build_bridge_prompt(cluster: TrendCluster, brand: dict) -> str:
    signal_summary = "\n".join(
        f"- {signal.provider}: {signal.term}; sources={', '.join(signal.source_urls[:3]) or 'none'}"
        for signal in cluster.signals
    )
    niche = str(brand.get("niche") or "")
    return f"""Generate 3 materially different historical bridges for a trend-assisted video suggestion.

Brand niche: {niche}
Trend entity: {cluster.canonical_entity}
Entity type: {cluster.entity_type}
Trend evidence:
{signal_summary}

Each bridge must connect directly to the entity or concept, stand alone after the trend fades,
contain a concrete number/date, and explain the relationship in one concise sentence. Reject
forced relevance. Do not exploit recent deaths, disasters, victims, living-person allegations,
political bait, unverified breaking claims, or copyrighted media.

Return ONLY a JSON array. Every item must contain:
historical_event, relationship_type, relationship_explanation, specific_number,
absurd_contradiction, first_spoken_sentence, first_frame_text, working_titles,
central_payoff, target_seconds, archive_fit_score, sourceability_score,
visual_potential_score, competition_score, duplicate_similarity, risk_flags,
unknowns. Scores are 0-100; duplicate_similarity is also expressed 0-100 here.
"""


def parse_bridge_candidates(raw: str, cluster: TrendCluster) -> list[ArchiveBridge]:
    clean = re.sub(r"^```(?:json)?\s*", "", (raw or "").strip(), flags=re.IGNORECASE)
    clean = re.sub(r"\s*```$", "", clean)
    start = clean.find("[")
    end = clean.rfind("]")
    if start < 0 or end <= start:
        raise ValidationError("Bridge response did not contain a JSON array")
    try:
        payload = json.loads(clean[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValidationError("Bridge response was malformed JSON") from exc
    if not isinstance(payload, list):
        raise ValidationError("Bridge response must be a list")
    current_sources = list(dict.fromkeys(url for signal in cluster.signals for url in signal.source_urls))
    candidates = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        enriched = {
            **item,
            "trend_cluster_id": cluster.cluster_id,
            "current_trigger_summary": item.get("current_trigger_summary") or f"Public attention around {cluster.canonical_entity}",
            "supporting_sources": current_sources,
            "current_news_sources": current_sources,
            "historical_sources": item.get("historical_sources") or [],
        }
        candidates.append(ArchiveBridge.from_dict(enriched))
    if not candidates:
        raise ValidationError("Bridge response contained no valid candidates")
    return candidates


def verify_historical_sources(bridge: ArchiveBridge, research: HistoricalResearch) -> ArchiveBridge:
    sources = research(bridge.historical_event)
    urls = list(dict.fromkeys(str(source.get("url") or "") for source in sources if source.get("url")))
    payload = bridge.to_dict()
    payload["historical_sources"] = urls
    payload["supporting_sources"] = list(dict.fromkeys([*bridge.current_news_sources, *urls]))
    return ArchiveBridge.from_dict(payload)


def detect_hard_risks(cluster: TrendCluster, bridge: ArchiveBridge) -> list[str]:
    risks = set(bridge.risk_flags)
    combined = " ".join(
        [cluster.canonical_entity, bridge.current_trigger_summary, bridge.historical_event]
    ).lower()
    if any(bool(signal.raw_metadata.get("active_tragedy")) for signal in cluster.signals):
        risks.add("active_tragedy")
    if cluster.entity_type in {"active_disaster", "recent_death"}:
        risks.add("active_tragedy")
    if any(term in combined for term in ("victims still", "ongoing rescue", "recent death")):
        risks.add("exploitative_victims")
    return sorted(risks)


def with_detected_risks(cluster: TrendCluster, bridge: ArchiveBridge) -> ArchiveBridge:
    return replace(bridge, risk_flags=detect_hard_risks(cluster, bridge))
