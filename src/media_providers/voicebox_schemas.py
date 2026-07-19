"""Strict, dependency-free records for the verified Voicebox 0.5 REST API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .errors import VoiceboxMalformedResponseError


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VoiceboxMalformedResponseError(f"{label} must be a JSON object.")
    return value


def _required_text(value: Mapping[str, Any], key: str, label: str) -> str:
    text = value.get(key)
    if not isinstance(text, str) or not text.strip():
        raise VoiceboxMalformedResponseError(
            f"{label} is missing the required string field {key!r}."
        )
    return text.strip()


def _optional_text(value: Mapping[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str):
        raise VoiceboxMalformedResponseError(f"field {key!r} must be a string or null.")
    return item


@dataclass(frozen=True)
class VoiceboxServerInfo:
    version: str
    message: str = ""

    @classmethod
    def from_json(cls, value: Any) -> "VoiceboxServerInfo":
        data = _mapping(value, "Voicebox root response")
        return cls(
            version=_required_text(data, "version", "Voicebox root response"),
            message=str(data.get("message") or ""),
        )

    @classmethod
    def from_openapi(cls, value: Any) -> "VoiceboxServerInfo":
        data = _mapping(value, "Voicebox OpenAPI response")
        info = _mapping(data.get("info"), "Voicebox OpenAPI info")
        return cls(
            version=_required_text(info, "version", "Voicebox OpenAPI info"),
            message=str(info.get("title") or "voicebox API"),
        )


@dataclass(frozen=True)
class VoiceboxHealth:
    status: str
    model_loaded: bool
    gpu_available: bool
    model_downloaded: bool | None = None
    model_size: str | None = None
    backend_type: str | None = None
    backend_variant: str | None = None

    @classmethod
    def from_json(cls, value: Any) -> "VoiceboxHealth":
        data = _mapping(value, "Voicebox health response")
        model_loaded = data.get("model_loaded")
        gpu_available = data.get("gpu_available")
        if not isinstance(model_loaded, bool) or not isinstance(gpu_available, bool):
            raise VoiceboxMalformedResponseError(
                "Voicebox health response requires boolean model_loaded and gpu_available fields."
            )
        downloaded = data.get("model_downloaded")
        if downloaded is not None and not isinstance(downloaded, bool):
            raise VoiceboxMalformedResponseError(
                "Voicebox health field 'model_downloaded' must be boolean or null."
            )
        return cls(
            status=_required_text(data, "status", "Voicebox health response"),
            model_loaded=model_loaded,
            gpu_available=gpu_available,
            model_downloaded=downloaded,
            model_size=_optional_text(data, "model_size"),
            backend_type=_optional_text(data, "backend_type"),
            backend_variant=_optional_text(data, "backend_variant"),
        )


@dataclass(frozen=True)
class VoiceboxProfile:
    id: str
    name: str
    language: str
    voice_type: str
    preset_engine: str | None = None
    default_engine: str | None = None
    updated_at: str | None = None
    sample_count: int = 0

    @classmethod
    def from_json(cls, value: Any) -> "VoiceboxProfile":
        data = _mapping(value, "Voicebox profile")
        sample_count = data.get("sample_count", 0)
        if isinstance(sample_count, bool) or not isinstance(sample_count, int):
            raise VoiceboxMalformedResponseError(
                "Voicebox profile field 'sample_count' must be an integer."
            )
        return cls(
            id=_required_text(data, "id", "Voicebox profile"),
            name=_required_text(data, "name", "Voicebox profile"),
            language=_required_text(data, "language", "Voicebox profile"),
            voice_type=str(data.get("voice_type") or "cloned").strip().lower(),
            preset_engine=_optional_text(data, "preset_engine"),
            default_engine=_optional_text(data, "default_engine"),
            updated_at=_optional_text(data, "updated_at"),
            sample_count=sample_count,
        )


@dataclass(frozen=True)
class VoiceboxModelStatus:
    model_name: str
    display_name: str
    downloaded: bool
    downloading: bool
    loaded: bool

    @classmethod
    def from_json(cls, value: Any) -> "VoiceboxModelStatus":
        data = _mapping(value, "Voicebox model status")
        downloaded = data.get("downloaded")
        if not isinstance(downloaded, bool):
            raise VoiceboxMalformedResponseError(
                "Voicebox model status requires a boolean 'downloaded' field."
            )
        for key in ("downloading", "loaded"):
            if key in data and not isinstance(data[key], bool):
                raise VoiceboxMalformedResponseError(
                    f"Voicebox model status field {key!r} must be boolean."
                )
        return cls(
            model_name=_required_text(data, "model_name", "Voicebox model status"),
            display_name=_required_text(data, "display_name", "Voicebox model status"),
            downloaded=downloaded,
            downloading=bool(data.get("downloading", False)),
            loaded=bool(data.get("loaded", False)),
        )


@dataclass(frozen=True)
class VoiceboxGeneration:
    id: str
    profile_id: str
    status: str
    engine: str | None = None
    model_size: str | None = None
    audio_path: str | None = None
    duration: float | None = None
    seed: int | None = None
    error: str | None = None

    @classmethod
    def from_json(cls, value: Any) -> "VoiceboxGeneration":
        data = _mapping(value, "Voicebox generation response")
        duration = data.get("duration")
        if duration is not None and not isinstance(duration, (int, float)):
            raise VoiceboxMalformedResponseError(
                "Voicebox generation field 'duration' must be numeric or null."
            )
        seed = data.get("seed")
        if seed is not None and not isinstance(seed, int):
            raise VoiceboxMalformedResponseError(
                "Voicebox generation field 'seed' must be an integer or null."
            )
        return cls(
            id=_required_text(data, "id", "Voicebox generation response"),
            profile_id=_required_text(
                data, "profile_id", "Voicebox generation response"
            ),
            status=str(data.get("status") or "completed").strip().lower(),
            engine=_optional_text(data, "engine"),
            model_size=_optional_text(data, "model_size"),
            audio_path=_optional_text(data, "audio_path"),
            duration=float(duration) if duration is not None else None,
            seed=seed,
            error=_optional_text(data, "error"),
        )

    @property
    def terminal(self) -> bool:
        return self.status in {"completed", "failed"}


@dataclass(frozen=True)
class VoiceboxAudioDownload:
    content: bytes
    content_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.content, bytes) or not self.content:
            raise VoiceboxMalformedResponseError(
                "Voicebox audio response did not contain any bytes."
            )
