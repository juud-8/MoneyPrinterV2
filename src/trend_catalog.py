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
from trend_models import ArchiveBridge, CatalogDecision


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
    source: str = "analytics"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def searchable_text(self) -> str:
        return " ".join(
            value for value in [self.title, self.subject, self.research_topic, *self.entities] if value
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
                entries.append(
                    CatalogEntry(
                        catalog_id=f"video:{_youtube_id(video.get('url', '')) or index}",
                        brand_id=brand_id,
                        title=str(video.get("title") or ""),
                        subject=str(video.get("subject") or ""),
                        status=str(video.get("status") or "generated"),
                        youtube_video_id=_youtube_id(video.get("url", "")),
                        entities=list(video.get("historical_entities") or []),
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
                entries.append(
                    CatalogEntry(
                        catalog_id=f"research:{os.path.basename(path)}",
                        brand_id=brand_id,
                        title="",
                        subject=topic,
                        status="researched",
                        research_topic=topic,
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

        if best_entry and best_similarity >= 0.62:
            decision = CatalogDecision.RESURFACE_EXISTING if best_entry.status == "uploaded" else CatalogDecision.SKIP
            return CatalogMatch(decision, best_similarity, best_entry, "The same historical story is already in the catalog")

        if entity_entries:
            entry, similarity = max(entity_entries, key=lambda item: item[1])
            if bridge.relationship_type.value == "alternate_angle" or similarity < 0.45:
                return CatalogMatch(
                    CatalogDecision.ALTERNATE_ANGLE,
                    similarity,
                    entry,
                    "The entity exists in the catalog, but the historical event is materially different",
                )
            return CatalogMatch(CatalogDecision.SKIP, similarity, entry, "The proposed angle is not materially distinct")

        return CatalogMatch(CatalogDecision.NEW_VIDEO, best_similarity, best_entry, "No material catalog match found")
