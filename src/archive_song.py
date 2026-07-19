"""Manual Suno handoff and resumable state for Archive Song episodes.

This module deliberately contains no Suno client.  It creates operator-facing
inputs, validates the returned audio locally, and stores durable checkpoints.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from archive_song_settings import (
    ArchiveSongSettings,
    DEFAULT_AUDIO_FILENAMES,
    default_archive_song_settings,
)
from config import ROOT_DIR
from media_providers.provenance import sha256_file, sha256_text
from media_providers.audio_assets import build_ffmpeg_normalize_command


AUDIO_MODE_NARRATION = "narration"
AUDIO_MODE_ARCHIVE_SONG = "archive_song"
SUPPORTED_AUDIO_MODES = {AUDIO_MODE_NARRATION, AUDIO_MODE_ARCHIVE_SONG}
SUPPORTED_SONG_FILENAMES = DEFAULT_AUDIO_FILENAMES
STATE_FILENAME = "archive_song_state.json"
STATE_VERSION = 1
NORMALIZED_BEAT_MAP_FILENAME = "visual_beat_map_normalized.json"
RAW_TIMED_BEAT_MAP_FILENAME = "visual_beat_map_timed.json"
PRODUCTION_AUDIO_FILENAME = "production_audio.wav"


class ArchiveSongError(RuntimeError):
    """Base error for an invalid Archive Song operation."""


class AwaitingSongAudio(ArchiveSongError):
    """Controlled pipeline pause at the manual Suno boundary."""

    def __init__(self, episode_dir: str, resume_command: str):
        self.episode_dir = os.path.abspath(episode_dir)
        self.resume_command = resume_command
        super().__init__(
            "Archive Song package is ready; status=awaiting_song_audio. "
            f"Place song.wav or song.mp3 in {self.episode_dir} and run: "
            f"{resume_command}"
        )


@dataclass(frozen=True)
class SongLyrics:
    text: str

    def validate(
        self,
        min_words: int | None = None,
        max_words: int | None = None,
    ) -> None:
        words = re.findall(r"\b[\w'-]+\b", self.text)
        if not self.text.strip():
            raise ValueError("lyrics must not be empty")
        defaults = default_archive_song_settings()
        # Allow a small LLM variance band around the configured target range.
        low = max(40, int(min_words if min_words is not None else defaults.lyric_min_words) - 20)
        high = int(max_words if max_words is not None else defaults.lyric_max_words) + 20
        if len(words) < low or len(words) > high:
            raise ValueError(
                f"lyrics must be a concise song package ({low}-{high} words); got {len(words)}"
            )


@dataclass(frozen=True)
class SunoStylePrompt:
    text: str

    def validate(self) -> None:
        if len(self.text.strip()) < 20:
            raise ValueError("Suno style prompt is too short")
        living_artist_patterns = ("in the style of", "sound like", "sounds like")
        if any(pattern in self.text.lower() for pattern in living_artist_patterns):
            raise ValueError("style prompt must not request imitation of an artist")


@dataclass(frozen=True)
class PronunciationEntry:
    term: str
    pronunciation: str
    note: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PronunciationEntry":
        item = cls(
            term=str(value.get("term") or "").strip(),
            pronunciation=str(value.get("pronunciation") or "").strip(),
            note=str(value.get("note") or "").strip(),
        )
        if not item.term or not item.pronunciation:
            raise ValueError("pronunciation entries require term and pronunciation")
        return item


@dataclass(frozen=True)
class SongVisualBeat:
    progress_start: float
    progress_end: float
    lyric_phrase: str
    historical_fact: str
    suggested_visual: str
    camera_motion: str
    on_screen_text: str
    source_ids: list[str]
    confidence: str

    @classmethod
    def from_dict(cls, value: dict[str, Any], valid_source_ids: set[str]) -> "SongVisualBeat":
        source_ids = list(
            dict.fromkeys(
                str(source_id).strip()
                for source_id in (value.get("source_ids") or [])
                if str(source_id).strip() in valid_source_ids
            )
        )
        item = cls(
            progress_start=float(value.get("progress_start", -1)),
            progress_end=float(value.get("progress_end", -1)),
            lyric_phrase=str(value.get("lyric_phrase") or "").strip(),
            historical_fact=str(value.get("historical_fact") or "").strip(),
            suggested_visual=str(value.get("suggested_visual") or "").strip(),
            camera_motion=str(value.get("camera_motion") or "").strip(),
            on_screen_text=str(value.get("on_screen_text") or "").strip(),
            source_ids=source_ids,
            confidence=str(value.get("confidence") or "").strip().lower(),
        )
        if not (0 <= item.progress_start < item.progress_end <= 1):
            raise ValueError("visual beat progress must satisfy 0 <= start < end <= 1")
        required_text = (
            item.lyric_phrase,
            item.historical_fact,
            item.suggested_visual,
            item.camera_motion,
        )
        if not all(required_text):
            raise ValueError("visual beats require lyric, fact, visual, and camera guidance")
        if not item.source_ids:
            raise ValueError("every visual beat must cite at least one research source")
        if item.confidence not in {"high", "medium", "low", "disputed"}:
            raise ValueError("visual beat confidence must be high, medium, low, or disputed")
        return item


@dataclass(frozen=True)
class SongPackage:
    episode_title: str
    historical_topic: str
    factual_summary: str
    song_title: str
    lyrics: SongLyrics
    suno_style_prompt: SunoStylePrompt
    exclusions: list[str]
    target_duration_seconds: float
    estimated_bpm: int
    suggested_key_or_mood: str
    vocal_direction: str
    pronunciations: list[PronunciationEntry]
    visual_beat_map: list[SongVisualBeat]
    fact_traceability: list[dict[str, Any]]
    disputed_claim_warnings: list[str]
    suggested_youtube_title: str
    suggested_description: str
    suggested_hashtags: list[str]
    suggested_thumbnail_text: str
    suggested_opening_frame_text: str

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        research_brief: dict[str, Any],
        settings: ArchiveSongSettings | None = None,
    ) -> "SongPackage":
        settings = settings or default_archive_song_settings()
        sources = research_brief.get("sources") or []
        valid_source_ids = {
            str(source.get("id")) for source in sources if source.get("id")
        }
        lyrics = SongLyrics(str(value.get("lyrics") or "").strip())
        style = SunoStylePrompt(str(value.get("suno_style_prompt") or "").strip())
        lyrics.validate(
            min_words=settings.lyric_min_words,
            max_words=settings.lyric_max_words,
        )
        style.validate()
        beats = [
            SongVisualBeat.from_dict(item, valid_source_ids)
            for item in (value.get("visual_beat_map") or [])
            if isinstance(item, dict)
        ]
        if len(beats) < 3:
            raise ValueError("visual beat map must contain at least three source-backed beats")

        valid_claims = {
            str(claim.get("text") or "").strip(): set(claim.get("source_ids") or [])
            for claim in (research_brief.get("claims") or [])
        }
        traceability = []
        for entry in value.get("fact_traceability") or []:
            if not isinstance(entry, dict):
                continue
            claim = str(entry.get("claim") or "").strip()
            source_ids = [
                str(source_id)
                for source_id in (entry.get("source_ids") or [])
                if str(source_id) in valid_source_ids
            ]
            if claim and source_ids:
                traceability.append(
                    {
                        "lyric_excerpt": str(entry.get("lyric_excerpt") or "").strip(),
                        "claim": claim,
                        "source_ids": list(dict.fromkeys(source_ids)),
                        "research_claim_match": claim in valid_claims,
                    }
                )
        if not traceability:
            raise ValueError("song package requires source/fact traceability")

        item = cls(
            episode_title=str(value.get("episode_title") or "").strip(),
            historical_topic=str(value.get("historical_topic") or "").strip(),
            factual_summary=str(value.get("factual_summary") or "").strip(),
            song_title=str(value.get("song_title") or "").strip(),
            lyrics=lyrics,
            suno_style_prompt=style,
            exclusions=[str(x).strip() for x in value.get("exclusions") or [] if str(x).strip()],
            target_duration_seconds=float(
                value.get("target_duration_seconds") or settings.target_duration_seconds
            ),
            estimated_bpm=int(value.get("estimated_bpm") or 0),
            suggested_key_or_mood=str(value.get("suggested_key_or_mood") or "").strip(),
            vocal_direction=str(value.get("vocal_direction") or "").strip(),
            pronunciations=[
                PronunciationEntry.from_dict(entry)
                for entry in (value.get("pronunciations") or [])
                if isinstance(entry, dict)
            ],
            visual_beat_map=beats,
            fact_traceability=traceability,
            disputed_claim_warnings=[
                str(x).strip()
                for x in value.get("disputed_claim_warnings") or []
                if str(x).strip()
            ],
            suggested_youtube_title=str(value.get("suggested_youtube_title") or "").strip(),
            suggested_description=str(value.get("suggested_description") or "").strip(),
            suggested_hashtags=[str(x).strip() for x in value.get("suggested_hashtags") or [] if str(x).strip()],
            suggested_thumbnail_text=str(value.get("suggested_thumbnail_text") or "").strip(),
            suggested_opening_frame_text=str(value.get("suggested_opening_frame_text") or "").strip(),
        )
        item.validate(research_brief, settings=settings)
        return item

    def validate(
        self,
        research_brief: dict[str, Any],
        settings: ArchiveSongSettings | None = None,
    ) -> None:
        settings = settings or default_archive_song_settings()
        required = (
            self.episode_title,
            self.historical_topic,
            self.factual_summary,
            self.song_title,
            self.suggested_key_or_mood,
            self.vocal_direction,
            self.suggested_youtube_title,
            self.suggested_description,
            self.suggested_thumbnail_text,
            self.suggested_opening_frame_text,
        )
        if not all(required):
            raise ValueError("song package is missing required text fields")
        if not (
            settings.min_duration_seconds
            <= self.target_duration_seconds
            <= settings.max_duration_seconds
        ):
            raise ValueError(
                "target duration must be between "
                f"{settings.min_duration_seconds:g} and {settings.max_duration_seconds:g} seconds"
            )
        # BPM may sit slightly outside brand guidance; keep a hard safety band.
        if not 40 <= self.estimated_bpm <= 220:
            raise ValueError("estimated BPM must be between 40 and 220")
        if not self.exclusions:
            raise ValueError("song package requires exclusion instructions")
        expected_warnings = {
            str(x).strip() for x in research_brief.get("disputed_points") or [] if str(x).strip()
        }
        actual_warnings = set(self.disputed_claim_warnings)
        if expected_warnings and not expected_warnings.issubset(actual_warnings):
            raise ValueError("research uncertainties must remain in disputed_claim_warnings")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["lyrics"] = self.lyrics.text
        value["suno_style_prompt"] = self.suno_style_prompt.text
        return value


@dataclass
class SongAudioValidation:
    input_path: str
    normalized_path: str = ""
    supported_format: bool = False
    decodable: bool = False
    duration_seconds: float = 0.0
    sample_rate_hz: int = 0
    channels: int = 0
    peak_dbfs: float | None = None
    leading_silence_seconds: float = 0.0
    trailing_silence_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.supported_format and self.decodable and not self.errors

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["valid"] = self.valid
        return value


@dataclass
class ArchiveSongState:
    episode_id: str
    brand_id: str
    status: str = "created"
    version: int = STATE_VERSION
    audio_mode: str = AUDIO_MODE_ARCHIVE_SONG
    created_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())
    subject: str = ""
    script: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    research_brief: dict[str, Any] = field(default_factory=dict)
    song_package: dict[str, Any] = field(default_factory=dict)
    imported_audio_path: str = ""
    imported_audio_identity: dict[str, Any] = field(default_factory=dict)
    package_lyrics_hash: str = ""
    normalized_audio_path: str = ""
    audio_validation: dict[str, Any] = field(default_factory=dict)
    timed_beat_map_path: str = ""
    caption_alignment_path: str = ""
    subtitles_path: str = ""
    image_prompts: list[str] = field(default_factory=list)
    shot_durations: list[float] = field(default_factory=list)
    shot_plan: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    assets: list[dict[str, Any]] = field(default_factory=list)
    rendered_video_path: str = ""
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ArchiveSongState":
        known = {item.name for item in fields(cls)}
        payload = {key: val for key, val in value.items() if key in known}
        state = cls(**payload)
        if state.audio_mode != AUDIO_MODE_ARCHIVE_SONG:
            raise ValueError("state file is not an Archive Song episode")
        if state.version != STATE_VERSION:
            raise ValueError(f"unsupported Archive Song state version {state.version}")
        return state


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def lyrics_content_hash(lyrics: str) -> str:
    return sha256_text(lyrics or "")


def compute_file_identity(path: str) -> dict[str, Any]:
    """Stable identity for imported audio invalidation (path + size + mtime + sha256)."""
    absolute = os.path.abspath(path)
    stat = os.stat(absolute)
    return {
        "path": absolute,
        "size": int(stat.st_size),
        "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
        "sha256": sha256_file(absolute),
    }


def identities_match(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if not left or not right:
        return False
    return (
        str(left.get("sha256") or "") == str(right.get("sha256") or "")
        and int(left.get("size") or -1) == int(right.get("size") or -2)
    )


def invalidate_audio_dependent_outputs(state: ArchiveSongState) -> None:
    """Clear derived artifacts that become stale when the imported song changes."""
    state.timed_beat_map_path = ""
    state.caption_alignment_path = ""
    state.subtitles_path = ""
    state.image_prompts = []
    state.shot_durations = []
    state.shot_plan = {}
    state.assets = []
    state.rendered_video_path = ""
    state.normalized_audio_path = ""
    state.audio_validation = {}


def snap_durations_to_frames(
    durations: list[float],
    total_seconds: float,
    fps: float = 30.0,
) -> list[float]:
    """Snap shot lengths to whole frames while preserving the audio total."""
    if not durations:
        return []
    frame = 1.0 / max(float(fps), 1.0)
    snapped = [max(frame, round(float(value) / frame) * frame) for value in durations]
    if len(snapped) == 1:
        return [max(frame, float(total_seconds))]
    head = snapped[:-1]
    tail = max(frame, float(total_seconds) - sum(head))
    # If rounding overshoots, shrink earlier shots by one frame at a time.
    while sum(head) + tail > float(total_seconds) + 1e-9 and any(value > frame for value in head):
        for index in range(len(head) - 1, -1, -1):
            if head[index] > frame:
                head[index] = round((head[index] - frame) / frame) * frame
                break
        tail = max(frame, float(total_seconds) - sum(head))
    return [*head, tail]


def _slug(value: str, fallback: str = "episode") -> str:
    result = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return result[:80] or fallback


def normalize_audio_mode(value: str | None) -> str:
    mode = (value or AUDIO_MODE_NARRATION).strip().lower().replace("-", "_")
    if mode not in SUPPORTED_AUDIO_MODES:
        raise ValueError(f"unsupported audio mode {value!r}; choose narration or archive_song")
    return mode


def episode_directory(brand_id: str, episode_id: str) -> str:
    return os.path.abspath(
        os.path.join(ROOT_DIR, "output", _slug(brand_id, "default"), "episodes", _slug(episode_id))
    )


def ensure_episode_directory(brand_id: str, episode_id: str) -> str:
    path = episode_directory(brand_id, episode_id)
    os.makedirs(path, exist_ok=True)
    return path


def state_path(episode_dir: str) -> str:
    return os.path.join(episode_dir, STATE_FILENAME)


def save_state(episode_dir: str, state: ArchiveSongState) -> str:
    os.makedirs(episode_dir, exist_ok=True)
    state.updated_at = _now()
    path = state_path(episode_dir)
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(asdict(state), file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, path)
    return path


def load_state(episode_dir: str) -> ArchiveSongState:
    with open(state_path(episode_dir), "r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError("Archive Song state must be a JSON object")
    return ArchiveSongState.from_dict(payload)


def extract_json_object(raw: str) -> dict[str, Any]:
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip(), flags=re.I)
    start, end = clean.find("{"), clean.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("song package response did not contain a JSON object")
    value = json.loads(clean[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("song package response must be a JSON object")
    return value


def build_song_package_prompt(
    topic: str,
    approved_script: str,
    research_brief: dict[str, Any],
    target_duration_seconds: float = 60.0,
    settings: ArchiveSongSettings | None = None,
) -> str:
    settings = settings or default_archive_song_settings()
    target_duration_seconds = float(
        target_duration_seconds or settings.target_duration_seconds
    )
    hook_rule = {
        "none": "A recurring hook is optional.",
        "prefer_repeated_hook": "Include a memorable recurring hook when it stays factual.",
        "require_repeated_hook": "Include a memorable recurring hook repeated at least twice.",
    }.get(settings.hook_repetition, "Include a memorable recurring hook when it stays factual.")
    source_claims = json.dumps(
        {
            "claims": research_brief.get("claims") or [],
            "disputed_points": research_brief.get("disputed_points") or [],
            "sources": [
                {"id": item.get("id"), "title": item.get("title"), "url": item.get("url")}
                for item in research_brief.get("sources") or []
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    return f"""Create a factual Archive Song package for a historical YouTube Short.

Topic: {topic}
Target duration: {target_duration_seconds:.0f} seconds (must remain {settings.min_duration_seconds:g}-{settings.max_duration_seconds:g} seconds)
Default musical direction: {settings.default_musical_direction}
Default vocal direction: {settings.default_vocal_direction}
Preferred BPM range: {settings.bpm_min}-{settings.bpm_max}
Hook guidance: {hook_rule}
Approved researched narration script:
{approved_script}

Authoritative research data:
{source_claims}

Use ONLY claims supported by the authoritative research data. Preserve every
disputed point verbatim in disputed_claim_warnings. Do not invent dialogue.
Do not imitate or name an artist and do not reference copyrighted lyrics.
Lyrics should be {settings.lyric_min_words}-{settings.lyric_max_words} words where practical: immediate first line, historical
setting, recurring hook, chronological progression, 1-2 concrete facts, and a
haunting unresolved ending. Prefer short intelligible lines and minimal filler.

Return ONLY valid JSON with exactly these keys:
{{
  "episode_title": "...",
  "historical_topic": "...",
  "factual_summary": "...",
  "song_title": "...",
  "lyrics": "line-broken lyrics",
  "suno_style_prompt": "genre, instrumentation, production, tempo and mood; no artist names",
  "exclusions": ["no spoken intro", "no artist imitation", "..."],
  "target_duration_seconds": {target_duration_seconds:.0f},
  "estimated_bpm": {max(settings.bpm_min, min(96, settings.bpm_max))},
  "suggested_key_or_mood": "...",
  "vocal_direction": "...",
  "pronunciations": [{{"term": "...", "pronunciation": "...", "note": "..."}}],
  "visual_beat_map": [
    {{"progress_start": 0.0, "progress_end": 0.1, "lyric_phrase": "...", "historical_fact": "...", "suggested_visual": "...", "camera_motion": "...", "on_screen_text": "...", "source_ids": ["S1"], "confidence": "high"}}
  ],
  "fact_traceability": [{{"lyric_excerpt": "...", "claim": "...", "source_ids": ["S1"]}}],
  "disputed_claim_warnings": ["..."],
  "suggested_youtube_title": "...",
  "suggested_description": "...",
  "suggested_hashtags": ["#History"],
  "suggested_thumbnail_text": "...",
  "suggested_opening_frame_text": "..."
}}

Cover the timeline with roughly these normalized ranges: 0-.10, .10-.25,
.25-.45, .45-.65, .65-.85, .85-1.0. Every beat must cite a valid source ID.
"""


def write_song_package_files(
    episode_dir: str,
    package: SongPackage,
    research_brief: dict[str, Any],
    resume_command: str,
) -> None:
    os.makedirs(episode_dir, exist_ok=True)
    package_dict = package.to_dict()
    files: dict[str, Any] = {
        "song_package.json": package_dict,
        "pronunciations.json": [asdict(item) for item in package.pronunciations],
        "visual_beat_map.json": [asdict(item) for item in package.visual_beat_map],
        "fact_check.json": {
            "topic": package.historical_topic,
            "fact_traceability": package.fact_traceability,
            "disputed_claim_warnings": package.disputed_claim_warnings,
            "sources": research_brief.get("sources") or [],
        },
    }
    for filename, value in files.items():
        with open(os.path.join(episode_dir, filename), "w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)

    with open(os.path.join(episode_dir, "lyrics.txt"), "w", encoding="utf-8") as file:
        file.write(package.lyrics.text.rstrip() + "\n")
    with open(os.path.join(episode_dir, "suno_prompt.txt"), "w", encoding="utf-8") as file:
        file.write(package.suno_style_prompt.text.rstrip() + "\n\nExclusions:\n")
        file.write("\n".join(f"- {value}" for value in package.exclusions) + "\n")

    readme = f"""# Archive Song manual Suno handoff

This directory contains a factual songwriting package. There is no direct Suno integration.

1. Open Suno manually.
2. Paste the contents of `lyrics.txt` into the lyrics field.
3. Paste `suno_prompt.txt` into the style/instructions field.
4. Generate multiple candidates.
5. Select the clearest factual performance; check the pronunciation and fact files.
6. Export the audio without editing the source lyrics.
7. Place it here as `song.wav`, `song.mp3`, `archive_song.wav`, or `archive_song.mp3`:
   `{os.path.abspath(episode_dir)}`
8. Resume with:
   `{resume_command}`

Before commercial use, verify that your current Suno plan and Suno's current terms permit your intended use.
"""
    with open(os.path.join(episode_dir, "README_SUNO.md"), "w", encoding="utf-8") as file:
        file.write(readme)


def discover_song_audio(
    episode_dir: str,
    explicit_path: str | None = None,
    filenames: tuple[str, ...] | list[str] | None = None,
) -> str | None:
    if explicit_path:
        candidate = os.path.abspath(explicit_path)
        return candidate if os.path.isfile(candidate) else None
    accepted = tuple(filenames or SUPPORTED_SONG_FILENAMES)
    candidates = [
        os.path.join(episode_dir, filename)
        for filename in accepted
        if os.path.isfile(os.path.join(episode_dir, filename))
    ]
    if not candidates:
        return None
    # Operators commonly add a corrected export under another accepted name.
    # Prefer the newest candidate so a stale invalid `song.wav` does not mask it.
    return os.path.abspath(max(candidates, key=os.path.getmtime))


def _silence_lengths(samples: Any, sample_rate: int, threshold: float = 0.01) -> tuple[float, float]:
    import numpy as np

    if samples.size == 0 or sample_rate <= 0:
        return 0.0, 0.0
    levels = np.max(np.abs(samples), axis=1) if samples.ndim > 1 else np.abs(samples)
    audible = np.flatnonzero(levels > threshold)
    if audible.size == 0:
        duration = len(levels) / sample_rate
        return duration, duration
    return audible[0] / sample_rate, (len(levels) - audible[-1] - 1) / sample_rate


def validate_and_normalize_audio(
    input_path: str,
    episode_dir: str,
    *,
    target_duration_seconds: float = 60.0,
    min_duration_seconds: float = 45.0,
    max_duration_seconds: float = 70.0,
    enforce_duration: bool = True,
) -> SongAudioValidation:
    result = SongAudioValidation(input_path=os.path.abspath(input_path or ""))
    suffix = Path(input_path or "").suffix.lower()
    result.supported_format = suffix in {".wav", ".mp3"}
    if not os.path.isfile(input_path or ""):
        result.errors.append("Audio file does not exist. Place song.wav or song.mp3 in the episode directory.")
        return result
    if not result.supported_format:
        result.errors.append("Unsupported audio format; use WAV or MP3.")
        return result
    if os.path.getsize(input_path) <= 0:
        result.errors.append("Audio file is empty.")
        return result

    normalized_path = os.path.join(episode_dir, PRODUCTION_AUDIO_FILENAME)
    # Keep a real audio suffix so FFmpeg can infer WAV on Windows; ".wav.tmp" fails.
    temp_path = os.path.join(episode_dir, "production_audio.tmp.wav")
    try:
        os.makedirs(episode_dir, exist_ok=True)
        if os.path.isfile(temp_path):
            os.remove(temp_path)
        command = build_ffmpeg_normalize_command(input_path, temp_path)
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise ValueError(
                "FFmpeg binary was not found. Install FFmpeg and ensure MoviePy's "
                "FFMPEG_BINARY points at it."
            ) from exc
        if process.returncode != 0:
            detail = (process.stderr or "FFmpeg rejected the audio").strip().splitlines()[-1]
            raise ValueError(detail)
        if not os.path.isfile(temp_path) or os.path.getsize(temp_path) <= 0:
            raise ValueError("FFmpeg produced an empty normalized audio file")
        os.replace(temp_path, normalized_path)
        result.normalized_path = os.path.abspath(normalized_path)
    except Exception as exc:
        for candidate in (temp_path,):
            try:
                if os.path.isfile(candidate):
                    os.remove(candidate)
            except OSError:
                pass
        # Do not leave a previous production_audio.wav pretending to match a failed import.
        result.errors.append(f"Audio could not be decoded or normalized: {exc}")
        return result

    try:
        import numpy as np
        import soundfile as sf

        samples, sample_rate = sf.read(result.normalized_path, always_2d=True, dtype="float32")
        result.duration_seconds = float(len(samples) / sample_rate) if sample_rate else 0.0
        if result.duration_seconds <= 0:
            raise ValueError("decoded audio has zero duration")
        result.decodable = True
        result.sample_rate_hz = int(sample_rate)
        result.channels = int(samples.shape[1])
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        result.peak_dbfs = float(20 * np.log10(max(peak, 1e-12)))
        result.leading_silence_seconds, result.trailing_silence_seconds = _silence_lengths(
            samples, sample_rate
        )
        if result.peak_dbfs >= -0.1:
            result.warnings.append(
                f"Peak level is {result.peak_dbfs:.2f} dBFS; inspect for clipping before render."
            )
        if result.leading_silence_seconds > 1.5:
            result.warnings.append(
                f"Leading silence is {result.leading_silence_seconds:.1f}s; trim manually or enable an explicit trim workflow."
            )
        if result.trailing_silence_seconds > 2.0:
            result.warnings.append(
                f"Trailing silence is {result.trailing_silence_seconds:.1f}s; trim manually if unintended."
            )
    except Exception as exc:
        if not result.decodable:
            result.errors.append(f"Normalized audio could not be inspected: {exc}")
        else:
            result.warnings.append(f"Peak/silence analysis was unavailable: {exc}")

    if result.duration_seconds < min_duration_seconds:
        message = (
            f"Track is {result.duration_seconds:.1f}s; expected about {target_duration_seconds:.0f}s "
            f"and at least {min_duration_seconds:.0f}s. Generate or export a longer candidate."
        )
        (result.errors if enforce_duration else result.warnings).append(message)
    if result.duration_seconds > max_duration_seconds:
        message = (
            f"Track is {result.duration_seconds:.1f}s; maximum is {max_duration_seconds:.0f}s. "
            "Choose a shorter Suno candidate or edit it intentionally; the pipeline will not truncate the song."
        )
        (result.errors if enforce_duration else result.warnings).append(message)
    return result


def _atomic_write_json(path: str, value: Any) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, path)
    return os.path.abspath(path)


def materialize_timed_beat_map(
    episode_dir: str, beats: list[SongVisualBeat], duration_seconds: float
) -> str:
    timed = []
    for beat in beats:
        value = asdict(beat)
        value["start_seconds"] = round(beat.progress_start * duration_seconds, 3)
        value["end_seconds"] = round(beat.progress_end * duration_seconds, 3)
        timed.append(value)
    path = os.path.join(episode_dir, RAW_TIMED_BEAT_MAP_FILENAME)
    return _atomic_write_json(path, timed)


def write_normalized_beat_map(
    episode_dir: str, normalized_beats: list[dict[str, Any]]
) -> str:
    path = os.path.join(episode_dir, NORMALIZED_BEAT_MAP_FILENAME)
    return _atomic_write_json(path, normalized_beats)


def prepare_timed_beat_maps(
    episode_dir: str,
    beats: list[SongVisualBeat],
    duration_seconds: float,
    settings: ArchiveSongSettings | None = None,
) -> tuple[str, str]:
    """Write raw progress→time map and the normalized map used by shots/captions."""
    from archive_song_visuals import normalize_timed_beats

    raw_path = materialize_timed_beat_map(episode_dir, beats, duration_seconds)
    with open(raw_path, "r", encoding="utf-8") as file:
        raw_beats = json.load(file)
    normalized = normalize_timed_beats(
        raw_beats if isinstance(raw_beats, list) else [],
        duration_seconds,
        settings or default_archive_song_settings(),
    )
    normalized_path = write_normalized_beat_map(episode_dir, normalized)
    return raw_path, normalized_path


def _format_srt(seconds: float) -> str:
    millis = max(0, int(round(seconds * 1000)))
    return f"{millis // 3600000:02d}:{(millis % 3600000) // 60000:02d}:{(millis % 60000) // 1000:02d},{millis % 1000:03d}"


def build_lyric_alignment(
    episode_dir: str,
    lyrics: str,
    duration_seconds: float,
    detected_entries: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    lines = [line.strip() for line in lyrics.splitlines() if line.strip()]
    if not lines:
        raise ValueError("cannot align empty lyrics")
    entries = detected_entries or []
    reliable = len(entries) >= max(2, len(lines) // 3)
    start = max(0.0, float(entries[0].get("start", 0))) if reliable else 0.0
    end = min(duration_seconds, float(entries[-1].get("end", duration_seconds))) if reliable else duration_seconds
    if end <= start:
        start, end, reliable = 0.0, duration_seconds, False

    weights = [max(1, len(re.findall(r"\b[\w'-]+\b", line))) for line in lines]
    total_weight = sum(weights)
    cursor = start
    alignment = []
    for index, (line, weight) in enumerate(zip(lines, weights), start=1):
        line_end = end if index == len(lines) else cursor + (end - start) * weight / total_weight
        alignment.append(
            {
                "index": index,
                "start_seconds": round(cursor, 3),
                "end_seconds": round(line_end, 3),
                "text": line,
                "timing_source": "whisper_guided_phrase" if reliable else "proportional_phrase_fallback",
                "operator_review_required": True,
            }
        )
        cursor = line_end

    alignment_path = os.path.join(episode_dir, "lyrics_alignment.json")
    with open(alignment_path, "w", encoding="utf-8") as file:
        json.dump(
            {
                "schema_version": 1,
                "lyrics_are_authoritative": True,
                "timing_can_be_edited_without_changing_text": True,
                "entries": alignment,
            },
            file,
            ensure_ascii=False,
            indent=2,
        )

    srt_path = os.path.join(episode_dir, "lyrics.srt")
    blocks = []
    for entry in alignment:
        blocks.append(
            f"{entry['index']}\n{_format_srt(entry['start_seconds'])} --> "
            f"{_format_srt(entry['end_seconds'])}\n{entry['text']}"
        )
    with open(srt_path, "w", encoding="utf-8") as file:
        file.write("\n\n".join(blocks) + "\n")
    return os.path.abspath(alignment_path), os.path.abspath(srt_path)


def copy_checkpoint_asset(path: str, episode_dir: str, index: int) -> str:
    assets_dir = os.path.join(episode_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    suffix = Path(path).suffix or ".bin"
    destination = os.path.join(assets_dir, f"shot_{index + 1:02d}{suffix.lower()}")
    if os.path.abspath(path) != os.path.abspath(destination):
        shutil.copy2(path, destination)
    return os.path.abspath(destination)
