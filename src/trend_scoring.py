"""Hard eligibility gates and transparent advisory opportunity ranking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from trend_catalog import CatalogMatch
from trend_models import (
    ArchiveBridge,
    RecommendedAction,
    ScoreComponent,
    TrendCluster,
    TrendOpportunity,
)


@dataclass(frozen=True)
class TrendPolicy:
    minimum_cross_source_count: int = 2
    minimum_opportunity_score: float = 75
    minimum_archive_fit_score: float = 80
    minimum_sourceability_score: float = 70
    estimated_production_hours: float = 4


POSITIVE_WEIGHTS = {
    "trend_velocity": 12,
    "cross_source_confirmation": 10,
    "search_intent": 8,
    "news_confirmation": 8,
    "freshness": 8,
    "archive_fit": 15,
    "absurd_contradiction": 8,
    "sourceability": 12,
    "visual_potential": 5,
    "related_channel_performance": 6,
    "production_lifetime_margin": 8,
}

PENALTY_WEIGHTS = {
    "competition": 10,
    "duplicate_risk": 25,
    "sensitivity_risk": 30,
}

HARD_RISKS = {
    "active_tragedy",
    "living_person_allegation",
    "exploitative_victims",
    "unverified_breaking_claim",
    "dangerous_misinformation",
    "copyright_dependent",
    "outside_brand_policy",
    "suspected_manipulation",
    "insufficient_lifetime",
    "forced_connection",
}


def _component(name: str, score: float | None, confidence: float, source: str, unknown: str = "") -> ScoreComponent:
    return ScoreComponent.from_dict(
        {"name": name, "score": score, "confidence": confidence, "source": source, "unknown_reason": unknown}
    )


def _source_domains(urls: list[str]) -> set[str]:
    return {urlparse(url).netloc.lower() for url in urls if urlparse(url).netloc}


def build_components(cluster: TrendCluster, bridge: ArchiveBridge, expires_at: str, now: str) -> list[ScoreComponent]:
    provider_confidence = min(1.0, 0.35 + cluster.cross_source_count * 0.2)
    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    lifetime_hours = max((expiry - current).total_seconds() / 3600, 0)
    contradiction = 90.0 if bridge.specific_number and bridge.absurd_contradiction else 50.0
    sensitivity = min(100.0, len(bridge.risk_flags) * 35.0)
    cross_score = min(100.0, cluster.cross_source_count / 3 * 100)
    return [
        _component("trend_velocity", cluster.trend_velocity_score, provider_confidence, "trend_cluster", "velocity unavailable"),
        _component("cross_source_confirmation", cross_score, provider_confidence, "provider_count"),
        _component("search_intent", cluster.search_intent_score, provider_confidence, "search_providers", "search intent unavailable"),
        _component("news_confirmation", cluster.news_confirmation_score, provider_confidence, "news_providers", "news confirmation unavailable"),
        _component("freshness", cluster.freshness_score, cluster.confidence, "collection_time", "freshness unavailable"),
        _component("archive_fit", bridge.archive_fit_score, 0.9, "validated_bridge"),
        _component("absurd_contradiction", contradiction, 0.8, "bridge_structure"),
        _component("sourceability", bridge.sourceability_score, 0.9, "historical_research"),
        _component("visual_potential", bridge.visual_potential_score, 0.7, "bridge_assessment", "visual potential unavailable"),
        _component("related_channel_performance", None, 0, "analytics", "no comparable package attribution"),
        _component("production_lifetime_margin", min(100.0, lifetime_hours / 24 * 100), 0.9, "expiration_and_production_estimate"),
        _component("competition", bridge.competition_score, 0.65, "youtube_competition", "competition unavailable"),
        _component("duplicate_risk", bridge.duplicate_similarity, 0.9, "catalog_similarity", "duplicate similarity unavailable"),
        _component("sensitivity_risk", sensitivity, 1.0, "policy_flags"),
    ]


def advisory_score(components: list[ScoreComponent]) -> float:
    by_name = {component.name: component for component in components}
    known_positive = [
        (by_name[name], weight)
        for name, weight in POSITIVE_WEIGHTS.items()
        if name in by_name and by_name[name].score is not None
    ]
    weight_total = sum(weight for _, weight in known_positive)
    positive = (
        sum(component.score * component.confidence * weight for component, weight in known_positive) / weight_total
        if weight_total
        else 0.0
    )
    penalty = sum(
        (by_name[name].score or 0) * by_name[name].confidence * weight / 100
        for name, weight in PENALTY_WEIGHTS.items()
        if name in by_name and by_name[name].score is not None
    )
    return round(max(0.0, min(100.0, positive - penalty)), 2)


def eligibility_failures(
    cluster: TrendCluster,
    bridge: ArchiveBridge,
    catalog_match: CatalogMatch,
    expires_at: str,
    now: str,
    policy: TrendPolicy,
) -> list[str]:
    failures = []
    direct_high_confidence = cluster.cross_source_count == 1 and cluster.confidence >= 0.85 and cluster.news_confirmation_score is not None
    if cluster.cross_source_count < policy.minimum_cross_source_count and not direct_high_confidence:
        failures.append("insufficient independent trend confirmation")
    if bridge.archive_fit_score < policy.minimum_archive_fit_score:
        failures.append("archive fit below threshold")
    if bridge.sourceability_score < policy.minimum_sourceability_score:
        failures.append("historical sourceability below threshold")
    if len(_source_domains(bridge.historical_sources)) < 2:
        failures.append("fewer than two independent historical source domains")
    if cluster.competing_interpretations:
        failures.append("entity resolution remains ambiguous")
    if set(bridge.risk_flags) & HARD_RISKS:
        failures.append("hard safety or policy risk")
    current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    if (expiry - current).total_seconds() / 3600 <= policy.estimated_production_hours:
        failures.append("trend expires before production can complete")
    if catalog_match.decision.value in {"skip", "resurface_existing"}:
        failures.append("catalog decision does not permit new production")
    return failures


def build_opportunity(
    cluster: TrendCluster,
    bridge: ArchiveBridge,
    brand_id: str,
    catalog_match: CatalogMatch,
    expires_at: str,
    now: str,
    policy: TrendPolicy | None = None,
) -> TrendOpportunity:
    policy = policy or TrendPolicy()
    components = build_components(cluster, bridge, expires_at, now)
    score = advisory_score(components)
    failures = eligibility_failures(cluster, bridge, catalog_match, expires_at, now, policy)
    eligible = not failures and score >= policy.minimum_opportunity_score
    if score < policy.minimum_opportunity_score:
        failures.append("advisory opportunity score below threshold")
    action = RecommendedAction(catalog_match.decision.value)
    if failures and action in {RecommendedAction.NEW_VIDEO, RecommendedAction.ALTERNATE_ANGLE}:
        action = RecommendedAction.SKIP
    unknowns = list(dict.fromkeys([
        *cluster.unknowns,
        *bridge.unknowns,
        *(component.unknown_reason for component in components if component.score is None and component.unknown_reason),
    ]))
    return TrendOpportunity.from_dict(
        {
            "trend": cluster,
            "bridge": bridge,
            "opportunity_score": score,
            "recommended_action": action.value,
            "existing_video_match": catalog_match.to_dict(),
            "expires_at": expires_at,
            "reasoning": [catalog_match.reason, *failures],
            "observed_facts": [
                f"{cluster.cross_source_count} independent provider(s) observed",
                f"{len(_source_domains(bridge.historical_sources))} historical source domain(s)",
            ],
            "inferences": [bridge.relationship_explanation],
            "unknowns": unknowns,
            "components": components,
            "eligible": eligible,
            "eligibility_failures": failures,
            "brand_id": brand_id,
        }
    )
