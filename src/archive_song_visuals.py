"""Beat-map driven shot planning for Archive Song episodes."""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from typing import Any

from archive_song_settings import ArchiveSongSettings, default_archive_song_settings


@dataclass
class ArchiveShot:
    prompt: str
    duration_seconds: float
    lyric_phrase: str = ""
    historical_fact: str = ""
    suggested_visual: str = ""
    camera_motion: str = ""
    on_screen_text: str = ""
    source_ids: list[str] = field(default_factory=list)
    confidence: str = ""
    start_seconds: float = 0.0
    end_seconds: float = 0.0
    split_index: int = 0
    split_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArchiveShotPlan:
    shots: list[ArchiveShot]
    used_fallback: bool = False
    fallback_reason: str = ""
    total_duration_seconds: float = 0.0
    audio_duration_seconds: float = 0.0
    source: str = "beat_map"

    def to_dict(self) -> dict[str, Any]:
        return {
            "used_fallback": self.used_fallback,
            "fallback_reason": self.fallback_reason,
            "total_duration_seconds": self.total_duration_seconds,
            "audio_duration_seconds": self.audio_duration_seconds,
            "source": self.source,
            "shots": [shot.to_dict() for shot in self.shots],
        }


def _load_timed_beats(timed_beat_map_path: str | None) -> list[dict[str, Any]]:
    if not timed_beat_map_path or not os.path.isfile(timed_beat_map_path):
        return []
    try:
        with open(timed_beat_map_path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _raw_beats_from_package(
    package_beats: list[Any], audio_duration: float
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for beat in package_beats or []:
        if hasattr(beat, "progress_start"):
            start = float(beat.progress_start) * audio_duration
            end = float(beat.progress_end) * audio_duration
            rows.append(
                {
                    "start_seconds": start,
                    "end_seconds": end,
                    "lyric_phrase": beat.lyric_phrase,
                    "historical_fact": beat.historical_fact,
                    "suggested_visual": beat.suggested_visual,
                    "camera_motion": beat.camera_motion,
                    "on_screen_text": beat.on_screen_text,
                    "source_ids": list(beat.source_ids),
                    "confidence": beat.confidence,
                }
            )
        elif isinstance(beat, dict):
            if "start_seconds" in beat and "end_seconds" in beat:
                rows.append(dict(beat))
            elif "progress_start" in beat and "progress_end" in beat:
                rows.append(
                    {
                        **beat,
                        "start_seconds": float(beat["progress_start"]) * audio_duration,
                        "end_seconds": float(beat["progress_end"]) * audio_duration,
                    }
                )
    return rows


def normalize_timed_beats(
    beats: list[dict[str, Any]],
    audio_duration: float,
    settings: ArchiveSongSettings | None = None,
) -> list[dict[str, Any]]:
    """Clamp, de-overlap, merge short, split long, and fit to audio duration."""
    settings = settings or default_archive_song_settings()
    if audio_duration <= 0:
        return []

    cleaned: list[dict[str, Any]] = []
    for beat in beats:
        try:
            start = max(0.0, float(beat.get("start_seconds", -1)))
            end = min(audio_duration, float(beat.get("end_seconds", -1)))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        row = dict(beat)
        row["start_seconds"] = start
        row["end_seconds"] = end
        row["source_ids"] = [
            str(item).strip()
            for item in (beat.get("source_ids") or [])
            if str(item).strip()
        ]
        cleaned.append(row)

    if not cleaned:
        return []

    cleaned.sort(key=lambda item: (item["start_seconds"], item["end_seconds"]))

    # Resolve overlaps by truncating the later beat; drop zero-length leftovers.
    deoverlapped: list[dict[str, Any]] = []
    cursor = 0.0
    for beat in cleaned:
        start = max(float(beat["start_seconds"]), cursor)
        end = float(beat["end_seconds"])
        if end <= start:
            continue
        row = dict(beat)
        row["start_seconds"] = start
        row["end_seconds"] = end
        deoverlapped.append(row)
        cursor = end

    if not deoverlapped:
        return []

    # Cover gaps so the timeline is continuous for the renderer.
    if deoverlapped[0]["start_seconds"] > 0:
        deoverlapped[0]["start_seconds"] = 0.0
    for index in range(1, len(deoverlapped)):
        prev = deoverlapped[index - 1]
        current = deoverlapped[index]
        if current["start_seconds"] > prev["end_seconds"]:
            prev["end_seconds"] = current["start_seconds"]
    if deoverlapped[-1]["end_seconds"] < audio_duration:
        deoverlapped[-1]["end_seconds"] = audio_duration

    min_shot = max(0.2, float(settings.min_shot_seconds))
    max_shot = max(min_shot, float(settings.max_shot_seconds))

    # Merge impractically short beats into neighbors without inventing facts.
    merged: list[dict[str, Any]] = []
    index = 0
    while index < len(deoverlapped):
        current = dict(deoverlapped[index])
        while (
            index + 1 < len(deoverlapped)
            and (current["end_seconds"] - current["start_seconds"]) < min_shot
        ):
            nxt = deoverlapped[index + 1]
            current["end_seconds"] = nxt["end_seconds"]
            current["lyric_phrase"] = " / ".join(
                part
                for part in (
                    str(current.get("lyric_phrase") or "").strip(),
                    str(nxt.get("lyric_phrase") or "").strip(),
                )
                if part
            )
            current["historical_fact"] = " ".join(
                part
                for part in (
                    str(current.get("historical_fact") or "").strip(),
                    str(nxt.get("historical_fact") or "").strip(),
                )
                if part
            )
            current["suggested_visual"] = " ".join(
                part
                for part in (
                    str(current.get("suggested_visual") or "").strip(),
                    str(nxt.get("suggested_visual") or "").strip(),
                )
                if part
            )
            current["camera_motion"] = str(
                current.get("camera_motion") or nxt.get("camera_motion") or ""
            ).strip()
            if not str(current.get("on_screen_text") or "").strip():
                current["on_screen_text"] = nxt.get("on_screen_text") or ""
            current["source_ids"] = list(
                dict.fromkeys(
                    list(current.get("source_ids") or [])
                    + list(nxt.get("source_ids") or [])
                )
            )
            if str(nxt.get("confidence") or "") == "disputed":
                current["confidence"] = "disputed"
            index += 1
        # Still too short and no next neighbor: merge backward.
        duration = current["end_seconds"] - current["start_seconds"]
        if duration < min_shot and merged:
            prev = merged[-1]
            prev["end_seconds"] = current["end_seconds"]
            prev["lyric_phrase"] = " / ".join(
                part
                for part in (
                    str(prev.get("lyric_phrase") or "").strip(),
                    str(current.get("lyric_phrase") or "").strip(),
                )
                if part
            )
            prev["historical_fact"] = " ".join(
                part
                for part in (
                    str(prev.get("historical_fact") or "").strip(),
                    str(current.get("historical_fact") or "").strip(),
                )
                if part
            )
            prev["suggested_visual"] = " ".join(
                part
                for part in (
                    str(prev.get("suggested_visual") or "").strip(),
                    str(current.get("suggested_visual") or "").strip(),
                )
                if part
            )
            prev["source_ids"] = list(
                dict.fromkeys(
                    list(prev.get("source_ids") or [])
                    + list(current.get("source_ids") or [])
                )
            )
        else:
            merged.append(current)
        index += 1

    if not merged:
        return []

    # Split unusually long beats into equal temporal slices; reuse facts/visuals.
    split_rows: list[dict[str, Any]] = []
    for beat in merged:
        duration = float(beat["end_seconds"]) - float(beat["start_seconds"])
        if duration <= max_shot:
            row = dict(beat)
            row["split_index"] = 0
            row["split_count"] = 1
            split_rows.append(row)
            continue
        parts = max(2, int(math.ceil(duration / max_shot)))
        slice_dur = duration / parts
        for part_index in range(parts):
            row = dict(beat)
            row["start_seconds"] = beat["start_seconds"] + part_index * slice_dur
            row["end_seconds"] = (
                beat["end_seconds"]
                if part_index == parts - 1
                else beat["start_seconds"] + (part_index + 1) * slice_dur
            )
            row["split_index"] = part_index
            row["split_count"] = parts
            split_rows.append(row)

    # Final fit: scale durations so totals match audio within float error.
    total = sum(row["end_seconds"] - row["start_seconds"] for row in split_rows)
    if total <= 0:
        return []
    if abs(total - audio_duration) > 1e-6:
        scale = audio_duration / total
        cursor = 0.0
        for index, row in enumerate(split_rows):
            duration = (row["end_seconds"] - row["start_seconds"]) * scale
            row["start_seconds"] = cursor
            if index == len(split_rows) - 1:
                row["end_seconds"] = audio_duration
            else:
                row["end_seconds"] = cursor + duration
            cursor = row["end_seconds"]

    return split_rows


def build_shot_prompt(
    beat: dict[str, Any],
    *,
    subject: str,
    historical_topic: str,
    style_suffix: str,
    settings: ArchiveSongSettings,
) -> str:
    visual = str(beat.get("suggested_visual") or "").strip()
    camera = str(beat.get("camera_motion") or "").strip()
    fact = str(beat.get("historical_fact") or "").strip()
    topic = historical_topic or subject
    parts = [
        visual or f"Historical documentary still about {topic}",
        f"Camera/motion: {camera}" if camera else "",
        f"Historical setting/period context: {topic}",
        f"Supported fact for framing (do not render as text): {fact}" if fact else "",
        style_suffix,
        "no text in images, 9:16 vertical",
    ]
    if int(beat.get("split_count") or 1) > 1:
        parts.append(
            f"Continued visual beat {int(beat['split_index']) + 1}/"
            f"{int(beat['split_count'])}; same factual scene, no new claims"
        )
    if settings.embed_source_in_visual_prompts:
        source_ids = ", ".join(beat.get("source_ids") or []) or "unspecified"
        confidence = str(beat.get("confidence") or "unknown")
        parts.append(
            f"Internal provenance only (never render as text): sources={source_ids}; "
            f"confidence={confidence}"
        )
    return ", ".join(part for part in parts if part)


def equal_duration_fallback_plan(
    image_prompts: list[str],
    audio_duration: float,
    reason: str,
) -> ArchiveShotPlan:
    prompts = [str(item).strip() for item in image_prompts if str(item).strip()]
    if not prompts:
        prompts = ["Historical documentary still, dramatic lighting, 9:16 vertical"]
    if audio_duration <= 0:
        return ArchiveShotPlan(
            shots=[],
            used_fallback=True,
            fallback_reason=reason,
            total_duration_seconds=0.0,
            audio_duration_seconds=audio_duration,
            source="equal_lyric_fallback",
        )
    per = audio_duration / len(prompts)
    shots = []
    cursor = 0.0
    for index, prompt in enumerate(prompts):
        end = audio_duration if index == len(prompts) - 1 else cursor + per
        shots.append(
            ArchiveShot(
                prompt=prompt,
                duration_seconds=round(end - cursor, 6),
                start_seconds=round(cursor, 6),
                end_seconds=round(end, 6),
            )
        )
        cursor = end
    total = sum(shot.duration_seconds for shot in shots)
    return ArchiveShotPlan(
        shots=shots,
        used_fallback=True,
        fallback_reason=reason,
        total_duration_seconds=round(total, 6),
        audio_duration_seconds=audio_duration,
        source="equal_lyric_fallback",
    )


def build_archive_shot_plan(
    *,
    audio_duration: float,
    timed_beat_map_path: str | None = None,
    package_beats: list[Any] | None = None,
    subject: str = "",
    historical_topic: str = "",
    style_suffix: str = "",
    settings: ArchiveSongSettings | None = None,
    fallback_prompts: list[str] | None = None,
) -> ArchiveShotPlan:
    """Build renderer shot prompts/durations from the timed beat map."""
    settings = settings or default_archive_song_settings()
    if settings.visual_pacing != "beat_map":
        return equal_duration_fallback_plan(
            fallback_prompts or [],
            audio_duration,
            f"visual_pacing={settings.visual_pacing!r} forces equal-duration lyric fallback",
        )

    raw = _load_timed_beats(timed_beat_map_path)
    if not raw:
        raw = _raw_beats_from_package(package_beats or [], audio_duration)
    if not raw:
        return equal_duration_fallback_plan(
            fallback_prompts or [],
            audio_duration,
            "timed visual beat map missing or unreadable; using equal-duration lyric fallback",
        )

    normalized = normalize_timed_beats(raw, audio_duration, settings)
    usable = [
        beat
        for beat in normalized
        if str(beat.get("suggested_visual") or "").strip()
        or str(beat.get("historical_fact") or "").strip()
    ]
    if len(usable) < 2:
        return equal_duration_fallback_plan(
            fallback_prompts or [],
            audio_duration,
            "visual beat map malformed or lacked usable suggested visuals; "
            "using equal-duration lyric fallback",
        )

    shots: list[ArchiveShot] = []
    for beat in usable:
        duration = float(beat["end_seconds"]) - float(beat["start_seconds"])
        if duration <= 0:
            continue
        shots.append(
            ArchiveShot(
                prompt=build_shot_prompt(
                    beat,
                    subject=subject,
                    historical_topic=historical_topic,
                    style_suffix=style_suffix,
                    settings=settings,
                ),
                duration_seconds=round(duration, 6),
                lyric_phrase=str(beat.get("lyric_phrase") or ""),
                historical_fact=str(beat.get("historical_fact") or ""),
                suggested_visual=str(beat.get("suggested_visual") or ""),
                camera_motion=str(beat.get("camera_motion") or ""),
                on_screen_text=str(beat.get("on_screen_text") or ""),
                source_ids=list(beat.get("source_ids") or []),
                confidence=str(beat.get("confidence") or ""),
                start_seconds=round(float(beat["start_seconds"]), 6),
                end_seconds=round(float(beat["end_seconds"]), 6),
                split_index=int(beat.get("split_index") or 0),
                split_count=int(beat.get("split_count") or 1),
            )
        )

    if len(shots) < 2:
        return equal_duration_fallback_plan(
            fallback_prompts or [],
            audio_duration,
            "normalized beat map produced fewer than two shots; "
            "using equal-duration lyric fallback",
        )

    total = sum(shot.duration_seconds for shot in shots)
    tolerance = max(0.01, float(settings.duration_tolerance_seconds))
    if abs(total - audio_duration) > tolerance:
        # Re-fit last shot so the renderer audio window is covered.
        delta = audio_duration - total
        shots[-1].duration_seconds = round(shots[-1].duration_seconds + delta, 6)
        shots[-1].end_seconds = round(shots[-1].start_seconds + shots[-1].duration_seconds, 6)
        total = sum(shot.duration_seconds for shot in shots)

    return ArchiveShotPlan(
        shots=shots,
        used_fallback=False,
        fallback_reason="",
        total_duration_seconds=round(total, 6),
        audio_duration_seconds=audio_duration,
        source="beat_map",
    )


def durations_match_audio(
    durations: list[float],
    audio_duration: float,
    tolerance_seconds: float,
) -> bool:
    total = sum(max(0.0, float(value)) for value in durations)
    return abs(total - audio_duration) <= max(0.01, tolerance_seconds)
