"""Read-only catalog adapter and trend opportunity duplicate decisions."""

from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from config import ROOT_DIR
from topic_similarity import topic_similarity
from trend_models import ArchiveBridge, CatalogDecision, StructuredEventClaims, ValidationError


@dataclass(frozen=True)
class CatalogEntry:
    catalog_id: str
    brand_id: str
    title: str
    subject: str
    status: str
    youtube_video_id: str = ""
    entities: list[str] = field(default_factory=list)
    research_topic: str = ""
    event_identity: str = ""
    period: str = ""
    consequence: str = ""
    central_claim: str = ""
    source_claim_ids: list[str] = field(default_factory=list)
    source: str = "analytics"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def searchable_text(self) -> str:
        return " ".join(
            value for value in [self.title, self.subject, self.research_topic, self.event_identity, *self.entities] if value
        )


@dataclass(frozen=True)
class CatalogMatch:
    decision: CatalogDecision
    similarity: float
    entry: CatalogEntry | None
    reason: str

    def to_dict(self) -> dict[str, Any] | None:
        if not self.entry:
            return None
        return {
            "catalog_id": self.entry.catalog_id,
            "youtube_video_id": self.entry.youtube_video_id,
            "title": self.entry.title,
            "subject": self.entry.subject,
            "event_identity": self.entry.event_identity,
            "period": self.entry.period,
            "consequence": self.entry.consequence,
            "central_claim": self.entry.central_claim,
            "source_claim_ids": self.entry.source_claim_ids,
            "similarity": round(self.similarity, 4),
            "reason": self.reason,
        }


def _youtube_id(url: str) -> str:
    match = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{6,})", url or "")
    return match.group(1) if match else ""


def _entity_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(token) >= 4 and token not in {"with", "from", "that", "this", "were", "history"}
    }


def _without_years(text: str) -> str:
    return re.sub(r"\b(?:1[0-9]{3}|20[0-9]{2})\b", " ", text or "").strip()


def _material_differences(bridge: ArchiveBridge, entry: CatalogEntry) -> list[str]:
    """Return differences supported by persisted structured catalog fields."""
    differences: list[str] = []
    existing_event = entry.event_identity
    if existing_event and topic_similarity(
        _without_years(bridge.historical_event), _without_years(existing_event)
    ) < 0.45:
        differences.append("historical event")
    comparisons = (
        ("consequence", bridge.central_payoff, entry.consequence),
        ("sourced central claim", bridge.absurd_contradiction, entry.central_claim),
    )
    for dimension, candidate, existing in comparisons:
        if existing and topic_similarity(candidate, str(existing)) < 0.35:
            differences.append(dimension)
    return differences


def _structured_claims_from_video(video: dict[str, Any]) -> dict[str, Any]:
    production = video.get("production") or {}
    attribution = (production.get("trend_attribution") or {}) if isinstance(production, dict) else {}
    claims = attribution.get("structured_claims") or video.get("structured_claims") or {}
    return _validated_structured_claims(claims)


def _validated_structured_claims(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    try:
        return StructuredEventClaims.from_dict(value).to_dict()
    except (ValidationError, TypeError, ValueError):
        return {}


class TrendCatalog:
    def __init__(self, entries: list[CatalogEntry]):
        self.entries = entries

    @classmethod
    def from_repository(cls, brand_id: str) -> "TrendCatalog":
        entries: list[CatalogEntry] = []
        try:
            import analytics

            for index, video in enumerate(analytics.dedupe_videos()):
                if video.get("brand_id") != brand_id:
                    continue
                claims = _structured_claims_from_video(video)
                sourced = claims.get("sourced_claims") or []
                entries.append(
                    CatalogEntry(
                        catalog_id=f"video:{_youtube_id(video.get('url', '')) or index}",
                        brand_id=brand_id,
                        title=str(video.get("title") or ""),
                        subject=str(video.get("subject") or ""),
                        status=str(video.get("status") or "generated"),
                        youtube_video_id=_youtube_id(video.get("url", "")),
                        entities=list(video.get("historical_entities") or claims.get("primary_entities") or []),
                        event_identity=str(claims.get("event_identity") or ""),
                        period=str(claims.get("period") or ""),
                        consequence=str(claims.get("consequence") or ""),
                        central_claim=str(claims.get("central_contradiction") or ""),
                        source_claim_ids=[
                            str(item.get("claim_id")) for item in sourced
                            if isinstance(item, dict) and item.get("claim_id")
                        ],
                        source="analytics",
                        metadata={"url": video.get("url", ""), "date": video.get("date", "")},
                    )
                )
            data = analytics._load()
            for index, rejected in enumerate(data.get("topic_rejections", [])):
                if rejected.get("brand_id") not in {brand_id, ""}:
                    continue
                entries.append(
                    CatalogEntry(
                        catalog_id=f"rejected:{index}",
                        brand_id=brand_id,
                        title="",
                        subject=str(rejected.get("candidate") or ""),
                        status="rejected",
                        source="topic_rejection",
                        metadata={"matched": rejected.get("matched", "")},
                    )
                )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

        pattern = os.path.join(ROOT_DIR, ".mp", "research", brand_id, "*.json")
        for path in glob.glob(pattern):
            try:
                with open(path, encoding="utf-8") as file:
                    brief = json.load(file)
                topic = str(brief.get("topic") or "")
                claims = _validated_structured_claims(brief.get("structured_claims") or {})
                sourced = claims.get("sourced_claims") or []
                entries.append(
                    CatalogEntry(
                        catalog_id=f"research:{os.path.basename(path)}",
                        brand_id=brand_id,
                        title="",
                        subject=topic,
                        status="researched",
                        research_topic=topic,
                        entities=list(claims.get("primary_entities") or []),
                        event_identity=str(claims.get("event_identity") or ""),
                        period=str(claims.get("period") or ""),
                        consequence=str(claims.get("consequence") or ""),
                        central_claim=str(claims.get("central_contradiction") or ""),
                        source_claim_ids=[
                            str(item.get("claim_id")) for item in sourced
                            if isinstance(item, dict) and item.get("claim_id")
                        ],
                        source="research_brief",
                        metadata={"brief_path": path},
                    )
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return cls(entries)

    def best_match(self, bridge: ArchiveBridge, canonical_entity: str) -> CatalogMatch:
        best_entry: CatalogEntry | None = None
        best_similarity = 0.0
        historical_event = bridge.historical_event
        entity_tokens = _entity_tokens(canonical_entity)
        entity_entries: list[tuple[CatalogEntry, float]] = []

        for entry in self.entries:
            text = entry.searchable_text
            similarity = topic_similarity(historical_event, text)
            if similarity > best_similarity:
                best_similarity = similarity
                best_entry = entry
            if entity_tokens and entity_tokens & _entity_tokens(text):
                entity_entries.append((entry, similarity))

        if entity_entries:
            entry, similarity = max(entity_entries, key=lambda item: item[1])
            if not entry.event_identity or not entry.source_claim_ids or not (
                entry.consequence and entry.central_claim
            ):
                return CatalogMatch(
                    CatalogDecision.HUMAN_REVIEW_REQUIRED,
                    similarity,
                    entry,
                    "Structured catalog evidence is incomplete; human review is required",
                )
            differences = _material_differences(bridge, entry)
            if len(differences) >= 2:
                return CatalogMatch(
                    CatalogDecision.ALTERNATE_ANGLE,
                    similarity,
                    entry,
                    "Catalog evidence supports material differences in: " + ", ".join(differences),
                )
            same_event = topic_similarity(
                _without_years(bridge.historical_event), _without_years(entry.event_identity)
            ) >= 0.62
            same_consequence = topic_similarity(bridge.central_payoff, entry.consequence) >= 0.45
            same_claim = topic_similarity(bridge.absurd_contradiction, entry.central_claim) >= 0.45
            if same_event and same_consequence and same_claim and entry.status == "uploaded":
                return CatalogMatch(
                    CatalogDecision.RESURFACE_EXISTING,
                    similarity,
                    entry,
                    "Structured event and consequence match an uploaded story",
                )
            return CatalogMatch(
                CatalogDecision.HUMAN_REVIEW_REQUIRED,
                similarity,
                entry,
                "Fewer than two reliable structured differences are proven; human review is required",
            )

        if best_entry and best_similarity >= 0.62:
            decision = CatalogDecision.RESURFACE_EXISTING if best_entry.status == "uploaded" else CatalogDecision.SKIP
            return CatalogMatch(decision, best_similarity, best_entry, "The same historical story is already in the catalog")

        return CatalogMatch(CatalogDecision.NEW_VIDEO, best_similarity, best_entry, "No material catalog match found")
