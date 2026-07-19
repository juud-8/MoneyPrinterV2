"""Resolved Archive Song settings with config → brand → episode → CLI precedence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, replace
from typing import Any


DEFAULT_AUDIO_FILENAMES = (
    "song.wav",
    "song.mp3",
    "archive_song.wav",
    "archive_song.mp3",
)


@dataclass(frozen=True)
class ArchiveSongSettings:
    """Operator-tunable Archive Song defaults.

    Precedence when resolving: engine defaults ← config.json `archive_song`
    ← brand `production.archive_song` ← episode package fields ← CLI overrides.
    """

    target_duration_seconds: float = 60.0
    min_duration_seconds: float = 55.0
    max_duration_seconds: float = 65.0
    duration_tolerance_seconds: float = 0.25
    lyric_min_words: int = 75
    lyric_max_words: int = 110
    default_musical_direction: str = (
        "dark medieval folk cabaret; clear consonants; no artist imitation"
    )
    default_vocal_direction: str = (
        "Immediate vocal entrance; articulate proper nouns; restrained chant on the hook"
    )
    bpm_min: int = 70
    bpm_max: int = 120
    caption_style: str = "lyric_highlight"
    hook_repetition: str = "prefer_repeated_hook"
    visual_pacing: str = "beat_map"
    fullscreen_emphasis: str = "on_screen_text"
    fullscreen_max_seconds: float = 1.5
    audio_filenames: tuple[str, ...] = DEFAULT_AUDIO_FILENAMES
    min_shot_seconds: float = 1.5
    max_shot_seconds: float = 12.0
    embed_source_in_visual_prompts: bool = False
    show_source_on_screen: bool = False
    enforce_duration: bool = True

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["audio_filenames"] = list(self.audio_filenames)
        return value


def default_archive_song_settings() -> ArchiveSongSettings:
    return ArchiveSongSettings()


def _as_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return fallback
    return bool(value)


def _merge_settings_dict(
    base: ArchiveSongSettings, overrides: dict[str, Any] | None
) -> ArchiveSongSettings:
    if not overrides or not isinstance(overrides, dict):
        return base
    known = {item.name for item in fields(ArchiveSongSettings)}
    updates: dict[str, Any] = {}
    for key, value in overrides.items():
        if key not in known or value is None or value == "":
            continue
        if key in {
            "target_duration_seconds",
            "min_duration_seconds",
            "max_duration_seconds",
            "duration_tolerance_seconds",
            "fullscreen_max_seconds",
            "min_shot_seconds",
            "max_shot_seconds",
        }:
            updates[key] = _as_float(value, getattr(base, key))
        elif key in {"lyric_min_words", "lyric_max_words", "bpm_min", "bpm_max"}:
            updates[key] = _as_int(value, getattr(base, key))
        elif key in {
            "embed_source_in_visual_prompts",
            "show_source_on_screen",
            "enforce_duration",
        }:
            updates[key] = _as_bool(value, getattr(base, key))
        elif key == "audio_filenames":
            names = tuple(
                str(item).strip()
                for item in (value if isinstance(value, (list, tuple)) else [value])
                if str(item).strip()
            )
            if names:
                updates[key] = names
        else:
            updates[key] = str(value).strip()
    return replace(base, **updates) if updates else base


def _episode_overrides(package: Any | None) -> dict[str, Any]:
    """Map episode package fields that legitimately override operator defaults.

    Generated Suno style text is an episode output, not a settings override for
    brand musical direction. Duration, vocal direction, and BPM still apply.
    """
    if package is None:
        return {}
    if hasattr(package, "to_dict"):
        payload = package.to_dict()
    elif isinstance(package, dict):
        payload = package
    else:
        return {}
    overrides: dict[str, Any] = {}
    if payload.get("target_duration_seconds") is not None:
        overrides["target_duration_seconds"] = payload["target_duration_seconds"]
    if payload.get("vocal_direction"):
        overrides["default_vocal_direction"] = payload["vocal_direction"]
    bpm = payload.get("estimated_bpm")
    if bpm is not None:
        try:
            bpm_value = int(bpm)
            # Episode BPM is a point estimate; keep brand/config range unless
            # the estimate falls outside, in which case expand just enough.
            overrides["_episode_bpm"] = bpm_value
        except (TypeError, ValueError):
            pass
    return overrides


def resolve_archive_song_settings(
    *,
    config_block: dict[str, Any] | None = None,
    brand: dict[str, Any] | None = None,
    episode_package: Any | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> ArchiveSongSettings:
    """Merge Archive Song settings with documented precedence."""
    settings = default_archive_song_settings()
    settings = _merge_settings_dict(settings, config_block)

    brand = brand or {}
    production = brand.get("production") if isinstance(brand.get("production"), dict) else {}
    brand_block = production.get("archive_song")
    if not isinstance(brand_block, dict):
        brand_block = brand.get("archive_song")
    settings = _merge_settings_dict(settings, brand_block if isinstance(brand_block, dict) else None)

    episode = _episode_overrides(episode_package)
    episode_bpm = episode.pop("_episode_bpm", None)
    settings = _merge_settings_dict(settings, episode)
    if episode_bpm is not None:
        settings = replace(
            settings,
            bpm_min=min(settings.bpm_min, episode_bpm),
            bpm_max=max(settings.bpm_max, episode_bpm),
        )

    cli = dict(cli_overrides or {})
    if "skip_song_validation" in cli:
        cli["enforce_duration"] = not bool(cli.pop("skip_song_validation"))
    settings = _merge_settings_dict(settings, cli)

    if settings.lyric_min_words > settings.lyric_max_words:
        settings = replace(
            settings,
            lyric_min_words=settings.lyric_max_words,
            lyric_max_words=settings.lyric_min_words,
        )
    if settings.min_duration_seconds > settings.max_duration_seconds:
        settings = replace(
            settings,
            min_duration_seconds=settings.max_duration_seconds,
            max_duration_seconds=settings.min_duration_seconds,
        )
    if settings.min_shot_seconds > settings.max_shot_seconds:
        settings = replace(
            settings,
            min_shot_seconds=settings.max_shot_seconds,
            max_shot_seconds=settings.min_shot_seconds,
        )
    return settings


def load_resolved_archive_song_settings(
    *,
    brand: dict[str, Any] | None = None,
    episode_package: Any | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> ArchiveSongSettings:
    """Resolve using live config.json + optional brand/episode/CLI layers."""
    from config import get_archive_song_config

    return resolve_archive_song_settings(
        config_block=get_archive_song_config(),
        brand=brand,
        episode_package=episode_package,
        cli_overrides=cli_overrides,
    )
