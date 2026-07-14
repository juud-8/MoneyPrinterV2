"""Human approval and production-boundary adapter for trend opportunities."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from research_brief import research_quality_issues
from topic_similarity import find_near_duplicate, topic_similarity
from trend_models import (
    ApprovalRecord,
    ApprovalStatus,
    CatalogDecision,
    RecommendedAction,
    TopicSeed,
    TrendMode,
    TrendOpportunity,
    ValidationError,
    new_id,
    utc_now,
)
from trend_store import TrendStore


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@dataclass(frozen=True)
class TrendStrategy:
    enabled: bool = False
    mode: TrendMode = TrendMode.OFF
    max_trend_assisted_share: float = 0.20
    recent_window_days: int = 30
    evergreen_target_share: float = 0.70
    experiment_target_share: float = 0.10


@dataclass(frozen=True)
class ContentMixStatus:
    recent_total: int
    recent_trend_assisted: int
    current_share: float
    projected_share: float
    maximum_share: float
    at_limit: bool


def load_trend_strategy(manifest: dict[str, Any]) -> TrendStrategy:
    raw = (manifest.get("production") or {}).get("trend_strategy") or {}
    if not isinstance(raw, dict):
        raise ValidationError("production.trend_strategy must be an object")
    mode_text = str(raw.get("mode", "off")).lower()
    if mode_text == "priority":
        raise ValidationError("PRIORITY mode is not implemented in the MVP")
    try:
        mode = TrendMode(mode_text)
    except ValueError as error:
        raise ValidationError(f"unsupported trend mode: {mode_text}") from error
    maximum = float(raw.get("max_trend_assisted_share", 0.20))
    if not 0 <= maximum <= 1:
        raise ValidationError("max_trend_assisted_share must be between 0 and 1")
    return TrendStrategy(
        enabled=bool(raw.get("enabled", False)),
        mode=mode,
        max_trend_assisted_share=maximum,
        recent_window_days=max(1, int(raw.get("recent_window_days", 30))),
        evergreen_target_share=float(raw.get("evergreen_target_share", 0.70)),
        experiment_target_share=float(raw.get("experiment_target_share", 0.10)),
    )


def content_mix_status(
    brand_id: str,
    strategy: TrendStrategy,
    store: TrendStore,
    *,
    now: str | None = None,
    videos: list[dict] | None = None,
) -> ContentMixStatus:
    current = _parse_time(now or utc_now())
    cutoff = current - timedelta(days=strategy.recent_window_days)
    cutoff_display = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    cutoff_iso = cutoff.isoformat().replace("+00:00", "Z")
    if videos is None:
        try:
            import analytics

            videos = analytics.dedupe_videos()
        except Exception:
            videos = []
    recent = [
        item
        for item in videos
        if item.get("brand_id") == brand_id
        and item.get("status") == "uploaded"
        and (item.get("date") or "") >= cutoff_display
    ]
    uploaded_trend = sum(
        1 for item in recent if (item.get("production") or {}).get("trend_attribution")
    )
    approved = store.count_approved_since(brand_id, cutoff_iso)
    # Approved-but-not-yet-uploaded seeds reserve capacity so repeated approvals
    # cannot silently exceed the configured production mix.
    reserved = max(approved - uploaded_trend, 0)
    trend_count = uploaded_trend + reserved
    total = len(recent) + reserved
    current_share = trend_count / total if total else 0.0
    projected_share = (trend_count + 1) / (total + 1)
    return ContentMixStatus(
        recent_total=total,
        recent_trend_assisted=trend_count,
        current_share=current_share,
        projected_share=projected_share,
        maximum_share=strategy.max_trend_assisted_share,
        at_limit=projected_share > strategy.max_trend_assisted_share,
    )


def create_topic_seed(opportunity: TrendOpportunity, approval: ApprovalRecord) -> TopicSeed:
    known_confidence = [component.confidence for component in opportunity.components if component.score is not None]
    confidence = sum(known_confidence) / len(known_confidence) if known_confidence else 0.0
    bridge = opportunity.bridge
    trend = opportunity.trend
    related_terms = list(
        dict.fromkeys(term for signal in trend.signals for term in signal.related_terms)
    )
    return TopicSeed.from_dict(
        {
            "seed_id": new_id("seed"),
            "brand_id": opportunity.brand_id,
            "primary_entity": trend.canonical_entity,
            "primary_keyword": trend.canonical_entity,
            "keyword_aliases": trend.aliases,
            "related_search_terms": related_terms,
            "current_trigger_summary": bridge.current_trigger_summary,
            "current_news_source_references": bridge.current_news_sources,
            "trend_geographies": trend.geographies,
            "detected_at": trend.first_seen,
            "expires_at": opportunity.expires_at,
            "historical_event": bridge.historical_event,
            "historical_source_references": bridge.historical_sources,
            "relationship_type": bridge.relationship_type.value,
            "relationship_explanation": bridge.relationship_explanation,
            "specific_number_date": bridge.specific_number,
            "absurd_contradiction": bridge.absurd_contradiction,
            "suggested_first_spoken_sentence": bridge.first_spoken_sentence,
            "suggested_first_frame_text": bridge.first_frame_text,
            "description_context_sentence": bridge.current_trigger_summary,
            "catalog_decision": opportunity.recommended_action.value,
            "existing_video_match": opportunity.existing_video_match,
            "component_scores": [asdict(component) for component in opportunity.components],
            "confidence": confidence,
            "unknowns": opportunity.unknowns,
            "approval_record": approval.to_dict(),
            "attribution_metadata": {
                "opportunity_id": opportunity.opportunity_id,
                "cluster_id": trend.cluster_id,
                "trend_assisted": True,
            },
            "created_at": approval.decided_at,
        }
    )


def approve_opportunity(
    store: TrendStore,
    opportunity_id: str,
    manifest: dict[str, Any],
    *,
    operator: str,
    reason: str,
    override_reason: str = "",
    now: str | None = None,
    videos: list[dict] | None = None,
) -> tuple[ApprovalRecord, TopicSeed, ContentMixStatus]:
    opportunity = store.get_opportunity(opportunity_id)
    if not opportunity:
        raise ValidationError(f"unknown opportunity: {opportunity_id}")
    strategy = load_trend_strategy(manifest)
    if not strategy.enabled or strategy.mode != TrendMode.SUGGEST:
        raise ValidationError("trend SUGGEST mode is not enabled for this brand")
    brand_id = str(manifest.get("brand_id") or "")
    if not brand_id or brand_id != opportunity.brand_id:
        raise ValidationError("active brand does not match opportunity brand")
    if opportunity.status != ApprovalStatus.PENDING:
        raise ValidationError("opportunity has already been decided")
    if not opportunity.eligible:
        raise ValidationError("ineligible opportunity cannot be approved")
    if opportunity.recommended_action not in {RecommendedAction.NEW_VIDEO, RecommendedAction.ALTERNATE_ANGLE}:
        raise ValidationError("this catalog decision cannot create a TopicSeed")
    decided_at = now or utc_now()
    if _parse_time(opportunity.expires_at) <= _parse_time(decided_at):
        raise ValidationError("expired opportunity cannot be approved")
    mix = content_mix_status(brand_id, strategy, store, now=decided_at, videos=videos)
    if mix.at_limit and not override_reason.strip():
        raise ValidationError("trend-assisted content share would exceed its configured maximum")
    approval = ApprovalRecord.from_dict(
        {
            "approval_id": new_id("approval"),
            "opportunity_id": opportunity.opportunity_id,
            "brand_id": brand_id,
            "status": "approved",
            "decided_at": decided_at,
            "operator": operator,
            "reason": reason,
            "content_mix_override": bool(override_reason.strip()),
            "override_reason": override_reason,
        }
    )
    seed = create_topic_seed(opportunity, approval)
    store.save_approval(approval)
    store.save_topic_seed(seed, opportunity.opportunity_id)
    store.save_opportunity(replace(opportunity, status=ApprovalStatus.APPROVED))
    return approval, seed, mix


def reject_opportunity(
    store: TrendStore,
    opportunity_id: str,
    *,
    operator: str,
    reason: str,
    now: str | None = None,
) -> ApprovalRecord:
    opportunity = store.get_opportunity(opportunity_id)
    if not opportunity:
        raise ValidationError(f"unknown opportunity: {opportunity_id}")
    if opportunity.status != ApprovalStatus.PENDING:
        raise ValidationError("opportunity has already been decided")
    approval = ApprovalRecord.from_dict(
        {
            "approval_id": new_id("approval"),
            "opportunity_id": opportunity_id,
            "brand_id": opportunity.brand_id,
            "status": "rejected",
            "decided_at": now or utc_now(),
            "operator": operator,
            "reason": reason,
        }
    )
    store.save_approval(approval)
    store.save_opportunity(replace(opportunity, status=ApprovalStatus.REJECTED))
    return approval


def validate_topic_seed_for_brand(seed: TopicSeed, manifest: dict[str, Any]) -> None:
    if seed.brand_id != str(manifest.get("brand_id") or ""):
        raise ValidationError("TopicSeed brand does not match the active brand")
    if _parse_time(seed.expires_at) <= datetime.now(timezone.utc):
        raise ValidationError("TopicSeed has expired")
    if not bool((manifest.get("publishing") or {}).get("review_before_upload", True)):
        raise ValidationError("trend-assisted production requires review_before_upload")


def validate_topic_seed_research(seed: TopicSeed, brief: dict[str, Any]) -> None:
    issues = research_quality_issues(brief)
    if issues:
        raise ValidationError("TopicSeed research gate failed: " + "; ".join(issues))
    topic = str(brief.get("topic") or "")
    if topic_similarity(seed.historical_event, topic) < 0.25:
        raise ValidationError("research brief does not materially match the approved historical event")


def validate_topic_seed_script(seed: TopicSeed, script: str) -> None:
    text = (script or "").strip()
    if not text:
        raise ValidationError("trend-assisted script is empty")
    anchors = [seed.historical_event, seed.specific_number_date, seed.absurd_contradiction]
    if not any(topic_similarity(anchor, text) >= 0.20 for anchor in anchors if anchor):
        raise ValidationError("script does not preserve the approved historical bridge")


def validate_seed_duplicate(seed: TopicSeed, recent_labels: list[str]) -> None:
    duplicate = find_near_duplicate(seed.historical_event, recent_labels)
    if duplicate:
        raise ValidationError(
            f'TopicSeed duplicates recent topic "{duplicate[0]}" ({duplicate[1]:.0%} similar)'
        )
