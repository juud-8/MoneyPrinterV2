"""Validated contracts for the Trend-to-Archive intelligence engine.

The trend pipeline handles external API responses and LLM-generated bridge
proposals.  Both are untrusted input, so objects enter the engine only through
the explicit ``from_dict`` validators in this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4


SCHEMA_VERSION = 1


class ValidationError(ValueError):
    """Raised when an external or generated payload violates its contract."""


class RelationshipType(str, Enum):
    EXACT_ENTITY = "exact_entity"
    SAME_PERSON = "same_person"
    SAME_PLACE = "same_place"
    SAME_SPECIES = "same_species"
    SAME_INSTITUTION = "same_institution"
    HISTORICAL_PRECEDENT = "historical_precedent"
    IRONIC_PARALLEL = "ironic_parallel"
    ANNIVERSARY = "anniversary"
    ALTERNATE_ANGLE = "alternate_angle"


class RecommendedAction(str, Enum):
    NEW_VIDEO = "new_video"
    ALTERNATE_ANGLE = "alternate_angle"
    RESURFACE_EXISTING = "resurface_existing"
    SKIP = "skip"


class TrendMode(str, Enum):
    OFF = "off"
    SUGGEST = "suggest"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CatalogDecision(str, Enum):
    NEW_VIDEO = "new_video"
    ALTERNATE_ANGLE = "alternate_angle"
    RESURFACE_EXISTING = "resurface_existing"
    SKIP = "skip"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"{name} is required")
    return text


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any, name: str, *, required: bool = False) -> list[str]:
    if value is None:
        value = []
    if not isinstance(value, list):
        raise ValidationError(f"{name} must be a list")
    result = list(dict.fromkeys(_text(item) for item in value if _text(item)))
    if required and not result:
        raise ValidationError(f"{name} must not be empty")
    return result


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValidationError(f"{name} must be an object")
    return dict(value)


def _number(value: Any, name: str, *, minimum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be numeric") from exc
    if minimum is not None and result < minimum:
        raise ValidationError(f"{name} must be >= {minimum}")
    return result


def _optional_number(value: Any, name: str) -> float | None:
    if value is None or value == "":
        return None
    return _number(value, name)


def _score(value: Any, name: str) -> float:
    result = _number(value, name)
    if not 0 <= result <= 100:
        raise ValidationError(f"{name} must be between 0 and 100")
    return result


def _timestamp(value: Any, name: str) -> str:
    text = _require_text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _urls(value: Any, name: str) -> list[str]:
    urls = _string_list(value, name)
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValidationError(f"{name} contains an invalid HTTP(S) URL")
    return urls


def _enum(enum_type: type[Enum], value: Any, name: str):
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ValidationError(f"{name} must be one of: {allowed}") from exc


@dataclass(frozen=True)
class ScoreComponent:
    name: str
    score: float | None
    confidence: float
    source: str
    unknown_reason: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScoreComponent":
        score = data.get("score")
        confidence = _number(data.get("confidence", 0), "confidence")
        if not 0 <= confidence <= 1:
            raise ValidationError("confidence must be between 0 and 1")
        return cls(
            name=_require_text(data.get("name"), "component name"),
            score=None if score is None else _score(score, "component score"),
            confidence=confidence,
            source=_require_text(data.get("source"), "component source"),
            unknown_reason=_text(data.get("unknown_reason")),
        )


@dataclass(frozen=True)
class TrendSignal:
    provider: str
    provider_signal_id: str
    collected_at: str
    term: str
    normalized_entity: str
    aliases: list[str] = field(default_factory=list)
    entity_type: str = "unknown"
    geography: str = "WORLDWIDE"
    language: str = "und"
    window_hours: float = 0
    rank: float | None = None
    volume: float | None = None
    volume_is_absolute: bool = False
    velocity: float | None = None
    related_terms: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    signal_id: str = field(default_factory=lambda: new_id("sig"))
    schema_version: int = SCHEMA_VERSION
    metric_type: str = "unspecified"
    expires_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrendSignal":
        raw = _mapping(data.get("raw_metadata"), "raw_metadata")
        if len(str(raw)) > 50_000:
            raise ValidationError("raw_metadata exceeds the 50KB safety limit")
        provider = _require_text(data.get("provider"), "provider").lower()
        metric_type = _require_text(data.get("metric_type", "unspecified"), "metric_type")
        absolute = bool(data.get("volume_is_absolute", False))
        if provider == "google_trends" and absolute:
            raise ValidationError("Google Trends interest is relative, not absolute volume")
        expires_at = _text(data.get("expires_at"))
        return cls(
            signal_id=_text(data.get("signal_id")) or new_id("sig"),
            provider=provider,
            provider_signal_id=_require_text(data.get("provider_signal_id"), "provider_signal_id"),
            collected_at=_timestamp(data.get("collected_at"), "collected_at"),
            term=_require_text(data.get("term"), "term"),
            normalized_entity=_require_text(data.get("normalized_entity"), "normalized_entity"),
            aliases=_string_list(data.get("aliases"), "aliases"),
            entity_type=_text(data.get("entity_type")) or "unknown",
            geography=_text(data.get("geography")) or "WORLDWIDE",
            language=_text(data.get("language")) or "und",
            window_hours=_number(data.get("window_hours", 0), "window_hours", minimum=0),
            rank=_optional_number(data.get("rank"), "rank"),
            volume=_optional_number(data.get("volume"), "volume"),
            volume_is_absolute=absolute,
            velocity=_optional_number(data.get("velocity"), "velocity"),
            related_terms=_string_list(data.get("related_terms"), "related_terms"),
            source_urls=_urls(data.get("source_urls"), "source_urls"),
            raw_metadata=raw,
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            metric_type=metric_type,
            expires_at=_timestamp(expires_at, "expires_at") if expires_at else "",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrendCluster:
    cluster_id: str
    canonical_entity: str
    aliases: list[str]
    entity_type: str
    first_seen: str
    last_seen: str
    geographies: list[str]
    languages: list[str]
    signals: list[TrendSignal]
    cross_source_count: int
    trend_velocity_score: float | None
    search_intent_score: float | None
    news_confirmation_score: float | None
    freshness_score: float | None
    confidence: float
    competing_interpretations: list[dict[str, Any]] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrendCluster":
        signals_raw = data.get("signals") or []
        if not isinstance(signals_raw, list) or not signals_raw:
            raise ValidationError("signals must contain at least one TrendSignal")
        signals = [
            item if isinstance(item, TrendSignal) else TrendSignal.from_dict(item)
            for item in signals_raw
        ]
        first_seen = _timestamp(data.get("first_seen"), "first_seen")
        last_seen = _timestamp(data.get("last_seen"), "last_seen")
        if datetime.fromisoformat(first_seen.replace("Z", "+00:00")) > datetime.fromisoformat(last_seen.replace("Z", "+00:00")):
            raise ValidationError("first_seen must not be after last_seen")
        confidence = _number(data.get("confidence", 0), "confidence")
        if not 0 <= confidence <= 1:
            raise ValidationError("confidence must be between 0 and 1")
        providers = {signal.provider for signal in signals}
        cross_source_count = int(data.get("cross_source_count", len(providers)))
        if cross_source_count > len(providers):
            raise ValidationError("cross_source_count cannot exceed independent providers")

        def optional_score(name: str) -> float | None:
            value = data.get(name)
            return None if value is None else _score(value, name)

        interpretations = data.get("competing_interpretations") or []
        if not isinstance(interpretations, list):
            raise ValidationError("competing_interpretations must be a list")
        return cls(
            cluster_id=_text(data.get("cluster_id")) or new_id("cluster"),
            canonical_entity=_require_text(data.get("canonical_entity"), "canonical_entity"),
            aliases=_string_list(data.get("aliases"), "aliases"),
            entity_type=_text(data.get("entity_type")) or "unknown",
            first_seen=first_seen,
            last_seen=last_seen,
            geographies=_string_list(data.get("geographies"), "geographies"),
            languages=_string_list(data.get("languages"), "languages"),
            signals=signals,
            cross_source_count=cross_source_count,
            trend_velocity_score=optional_score("trend_velocity_score"),
            search_intent_score=optional_score("search_intent_score"),
            news_confirmation_score=optional_score("news_confirmation_score"),
            freshness_score=optional_score("freshness_score"),
            confidence=confidence,
            competing_interpretations=[dict(item) for item in interpretations if isinstance(item, dict)],
            unknowns=_string_list(data.get("unknowns"), "unknowns"),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["signals"] = [signal.to_dict() for signal in self.signals]
        return payload


@dataclass(frozen=True)
class ArchiveBridge:
    trend_cluster_id: str
    current_trigger_summary: str
    historical_event: str
    relationship_type: RelationshipType
    relationship_explanation: str
    specific_number: str
    absurd_contradiction: str
    first_spoken_sentence: str
    first_frame_text: str
    working_titles: list[str]
    central_payoff: str
    target_seconds: float
    archive_fit_score: float
    sourceability_score: float
    visual_potential_score: float | None
    competition_score: float | None
    duplicate_similarity: float | None
    risk_flags: list[str]
    supporting_sources: list[str]
    bridge_id: str = field(default_factory=lambda: new_id("bridge"))
    current_news_sources: list[str] = field(default_factory=list)
    historical_sources: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArchiveBridge":
        explanation = _require_text(data.get("relationship_explanation"), "relationship_explanation")
        if len(explanation) > 400:
            raise ValidationError("relationship_explanation must be explainable in one concise sentence")

        def optional_score(name: str) -> float | None:
            value = data.get(name)
            return None if value is None else _score(value, name)

        supporting = _urls(data.get("supporting_sources"), "supporting_sources")
        current_sources = _urls(data.get("current_news_sources"), "current_news_sources")
        historical_sources = _urls(data.get("historical_sources"), "historical_sources")
        return cls(
            bridge_id=_text(data.get("bridge_id")) or new_id("bridge"),
            trend_cluster_id=_require_text(data.get("trend_cluster_id"), "trend_cluster_id"),
            current_trigger_summary=_require_text(data.get("current_trigger_summary"), "current_trigger_summary"),
            historical_event=_require_text(data.get("historical_event"), "historical_event"),
            relationship_type=_enum(RelationshipType, data.get("relationship_type"), "relationship_type"),
            relationship_explanation=explanation,
            specific_number=_text(data.get("specific_number")),
            absurd_contradiction=_require_text(data.get("absurd_contradiction"), "absurd_contradiction"),
            first_spoken_sentence=_require_text(data.get("first_spoken_sentence"), "first_spoken_sentence"),
            first_frame_text=_require_text(data.get("first_frame_text"), "first_frame_text"),
            working_titles=_string_list(data.get("working_titles"), "working_titles"),
            central_payoff=_require_text(data.get("central_payoff"), "central_payoff"),
            target_seconds=_number(data.get("target_seconds"), "target_seconds", minimum=1),
            archive_fit_score=_score(data.get("archive_fit_score"), "archive_fit_score"),
            sourceability_score=_score(data.get("sourceability_score"), "sourceability_score"),
            visual_potential_score=optional_score("visual_potential_score"),
            competition_score=optional_score("competition_score"),
            duplicate_similarity=optional_score("duplicate_similarity"),
            risk_flags=_string_list(data.get("risk_flags"), "risk_flags"),
            supporting_sources=supporting,
            current_news_sources=current_sources or supporting,
            historical_sources=historical_sources,
            unknowns=_string_list(data.get("unknowns"), "unknowns"),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["relationship_type"] = self.relationship_type.value
        return payload


@dataclass(frozen=True)
class TrendOpportunity:
    trend: TrendCluster
    bridge: ArchiveBridge
    opportunity_score: float
    recommended_action: RecommendedAction
    existing_video_match: dict[str, Any] | None
    expires_at: str
    reasoning: list[str]
    observed_facts: list[str]
    inferences: list[str]
    unknowns: list[str]
    components: list[ScoreComponent]
    opportunity_id: str = field(default_factory=lambda: new_id("opp"))
    eligible: bool = False
    eligibility_failures: list[str] = field(default_factory=list)
    brand_id: str = ""
    status: ApprovalStatus = ApprovalStatus.PENDING
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrendOpportunity":
        trend_raw = data.get("trend")
        bridge_raw = data.get("bridge")
        trend = trend_raw if isinstance(trend_raw, TrendCluster) else TrendCluster.from_dict(trend_raw or {})
        bridge = bridge_raw if isinstance(bridge_raw, ArchiveBridge) else ArchiveBridge.from_dict(bridge_raw or {})
        if bridge.trend_cluster_id != trend.cluster_id:
            raise ValidationError("bridge must reference the opportunity trend cluster")
        match = data.get("existing_video_match")
        if match is not None and not isinstance(match, dict):
            raise ValidationError("existing_video_match must be an object or null")
        components_raw = data.get("components") or []
        if not isinstance(components_raw, list):
            raise ValidationError("components must be a list")
        return cls(
            opportunity_id=_text(data.get("opportunity_id")) or new_id("opp"),
            trend=trend,
            bridge=bridge,
            opportunity_score=_score(data.get("opportunity_score"), "opportunity_score"),
            recommended_action=_enum(RecommendedAction, data.get("recommended_action"), "recommended_action"),
            existing_video_match=dict(match) if match else None,
            expires_at=_timestamp(data.get("expires_at"), "expires_at"),
            reasoning=_string_list(data.get("reasoning"), "reasoning"),
            observed_facts=_string_list(data.get("observed_facts"), "observed_facts"),
            inferences=_string_list(data.get("inferences"), "inferences"),
            unknowns=_string_list(data.get("unknowns"), "unknowns"),
            components=[item if isinstance(item, ScoreComponent) else ScoreComponent.from_dict(item) for item in components_raw],
            eligible=bool(data.get("eligible", False)),
            eligibility_failures=_string_list(data.get("eligibility_failures"), "eligibility_failures"),
            brand_id=_require_text(data.get("brand_id"), "brand_id"),
            status=_enum(ApprovalStatus, data.get("status", ApprovalStatus.PENDING.value), "status"),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["trend"] = self.trend.to_dict()
        payload["bridge"] = self.bridge.to_dict()
        payload["recommended_action"] = self.recommended_action.value
        payload["status"] = self.status.value
        return payload


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    opportunity_id: str
    brand_id: str
    status: ApprovalStatus
    decided_at: str
    operator: str
    reason: str
    content_mix_override: bool = False
    override_reason: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApprovalRecord":
        override = bool(data.get("content_mix_override", False))
        override_reason = _text(data.get("override_reason"))
        if override and not override_reason:
            raise ValidationError("content-mix override requires a recorded reason")
        return cls(
            approval_id=_text(data.get("approval_id")) or new_id("approval"),
            opportunity_id=_require_text(data.get("opportunity_id"), "opportunity_id"),
            brand_id=_require_text(data.get("brand_id"), "brand_id"),
            status=_enum(ApprovalStatus, data.get("status"), "status"),
            decided_at=_timestamp(data.get("decided_at"), "decided_at"),
            operator=_require_text(data.get("operator"), "operator"),
            reason=_require_text(data.get("reason"), "reason"),
            content_mix_override=override,
            override_reason=override_reason,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass(frozen=True)
class TopicSeed:
    seed_id: str
    brand_id: str
    primary_entity: str
    primary_keyword: str
    keyword_aliases: list[str]
    related_search_terms: list[str]
    current_trigger_summary: str
    current_news_source_references: list[str]
    trend_geographies: list[str]
    detected_at: str
    expires_at: str
    historical_event: str
    historical_source_references: list[str]
    relationship_type: RelationshipType
    relationship_explanation: str
    specific_number_date: str
    absurd_contradiction: str
    suggested_first_spoken_sentence: str
    suggested_first_frame_text: str
    description_context_sentence: str
    catalog_decision: CatalogDecision
    existing_video_match: dict[str, Any] | None
    component_scores: list[ScoreComponent]
    confidence: float
    unknowns: list[str]
    approval_record: ApprovalRecord
    attribution_metadata: dict[str, Any]
    created_at: str
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TopicSeed":
        approval_raw = data.get("approval_record")
        approval = approval_raw if isinstance(approval_raw, ApprovalRecord) else ApprovalRecord.from_dict(approval_raw or {})
        if approval.status != ApprovalStatus.APPROVED:
            raise ValidationError("TopicSeed requires an approved approval record")
        brand_id = _require_text(data.get("brand_id"), "brand_id")
        if approval.brand_id != brand_id:
            raise ValidationError("approval brand does not match TopicSeed brand")
        decision = _enum(CatalogDecision, data.get("catalog_decision"), "catalog_decision")
        if decision not in {CatalogDecision.NEW_VIDEO, CatalogDecision.ALTERNATE_ANGLE}:
            raise ValidationError("only new-video or alternate-angle opportunities may create TopicSeed")
        confidence = _number(data.get("confidence", 0), "confidence")
        if not 0 <= confidence <= 1:
            raise ValidationError("confidence must be between 0 and 1")
        match = data.get("existing_video_match")
        if match is not None and not isinstance(match, dict):
            raise ValidationError("existing_video_match must be an object or null")
        components = data.get("component_scores") or []
        if not isinstance(components, list):
            raise ValidationError("component_scores must be a list")
        return cls(
            seed_id=_text(data.get("seed_id")) or new_id("seed"),
            brand_id=brand_id,
            primary_entity=_require_text(data.get("primary_entity"), "primary_entity"),
            primary_keyword=_require_text(data.get("primary_keyword"), "primary_keyword"),
            keyword_aliases=_string_list(data.get("keyword_aliases"), "keyword_aliases"),
            related_search_terms=_string_list(data.get("related_search_terms"), "related_search_terms"),
            current_trigger_summary=_require_text(data.get("current_trigger_summary"), "current_trigger_summary"),
            current_news_source_references=_urls(data.get("current_news_source_references"), "current_news_source_references"),
            trend_geographies=_string_list(data.get("trend_geographies"), "trend_geographies", required=True),
            detected_at=_timestamp(data.get("detected_at"), "detected_at"),
            expires_at=_timestamp(data.get("expires_at"), "expires_at"),
            historical_event=_require_text(data.get("historical_event"), "historical_event"),
            historical_source_references=_urls(data.get("historical_source_references"), "historical_source_references"),
            relationship_type=_enum(RelationshipType, data.get("relationship_type"), "relationship_type"),
            relationship_explanation=_require_text(data.get("relationship_explanation"), "relationship_explanation"),
            specific_number_date=_require_text(data.get("specific_number_date"), "specific_number_date"),
            absurd_contradiction=_require_text(data.get("absurd_contradiction"), "absurd_contradiction"),
            suggested_first_spoken_sentence=_require_text(data.get("suggested_first_spoken_sentence"), "suggested_first_spoken_sentence"),
            suggested_first_frame_text=_require_text(data.get("suggested_first_frame_text"), "suggested_first_frame_text"),
            description_context_sentence=_require_text(data.get("description_context_sentence"), "description_context_sentence"),
            catalog_decision=decision,
            existing_video_match=dict(match) if match else None,
            component_scores=[item if isinstance(item, ScoreComponent) else ScoreComponent.from_dict(item) for item in components],
            confidence=confidence,
            unknowns=_string_list(data.get("unknowns"), "unknowns"),
            approval_record=approval,
            attribution_metadata=_mapping(data.get("attribution_metadata"), "attribution_metadata"),
            created_at=_timestamp(data.get("created_at"), "created_at"),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["relationship_type"] = self.relationship_type.value
        payload["catalog_decision"] = self.catalog_decision.value
        payload["approval_record"] = self.approval_record.to_dict()
        return payload
