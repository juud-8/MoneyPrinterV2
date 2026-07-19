"""Validated Voicebox selection and precedence without changing legacy defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .errors import ProviderConfigurationError


_AUDIO_KEYS = {"provider", "fallback_provider", "allow_fallback", "voicebox"}
_VOICEBOX_KEYS = {
    "base_url",
    "profile",
    "engine",
    "language",
    "model_size",
    "instruct",
    "request_timeout_seconds",
    "health_timeout_seconds",
    "poll_interval_seconds",
    "max_retries",
    "effects_preset",
    "effects_chain",
    "unsupported_tag_policy",
    "max_chunk_chars",
    "crossfade_ms",
    "normalize",
}
_LEGACY_PROVIDERS = {"kittentts", "elevenlabs", "fishaudio", "edge_tts"}


def _config_error(message: str) -> ProviderConfigurationError:
    return ProviderConfigurationError("voicebox", message)


def _as_mapping(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise _config_error(f"{label} must be a JSON object.")
    return dict(value)


def _validate_unknown(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _config_error(
            f"Unknown {label} key(s): {', '.join(unknown)}. Remove misspelled or unsupported settings."
        )


def _number(
    value: Any,
    *,
    label: str,
    integer: bool,
    minimum: float,
    maximum: float,
) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _config_error(f"{label} must be a number.")
    converted: int | float = int(value) if integer else float(value)
    if integer and converted != value:
        raise _config_error(f"{label} must be a whole number.")
    if not minimum <= converted <= maximum:
        raise _config_error(f"{label} must be between {minimum:g} and {maximum:g}.")
    return converted


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _config_error(f"{label} must be a string or null.")
    return value


def _is_loopback_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and parsed.port is not None
        and not parsed.username
        and not parsed.password
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
    )


@dataclass(frozen=True)
class VoiceboxSettings:
    base_url: str = "http://127.0.0.1:17493"
    profile: str = ""
    engine: str | None = "qwen"
    language: str | None = None
    model_size: str | None = None
    instruct: str | None = None
    request_timeout_seconds: float = 600.0
    health_timeout_seconds: float = 5.0
    poll_interval_seconds: float = 1.0
    max_retries: int = 1
    effects_preset: str | None = None
    effects_chain: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    unsupported_tag_policy: str = "error"
    max_chunk_chars: int = 800
    crossfade_ms: int = 50
    normalize: bool = True

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "VoiceboxSettings":
        data = _as_mapping(value, "audio.voicebox")
        _validate_unknown(data, _VOICEBOX_KEYS, "audio.voicebox")

        base_url = data.get("base_url", cls.base_url)
        if not isinstance(base_url, str) or not _is_loopback_url(base_url.strip()):
            raise _config_error(
                "audio.voicebox.base_url must be an explicit loopback HTTP URL with a port, "
                "for example http://127.0.0.1:17493."
            )
        profile = data.get("profile", cls.profile)
        if not isinstance(profile, str):
            raise _config_error("audio.voicebox.profile must be a string.")

        engine = _optional_string(data.get("engine", cls.engine), "audio.voicebox.engine")
        if engine is not None and not engine.strip():
            raise _config_error(
                "audio.voicebox.engine may be null to use the profile default, but not empty."
            )
        language = _optional_string(
            data.get("language", cls.language), "audio.voicebox.language"
        )
        if language is not None and not language.strip():
            raise _config_error(
                "audio.voicebox.language may be null to use the profile language, but not empty."
            )
        model_size = _optional_string(
            data.get("model_size", cls.model_size), "audio.voicebox.model_size"
        )
        if model_size is not None and not model_size.strip():
            raise _config_error(
                "audio.voicebox.model_size may be null, but an empty value is invalid."
            )
        instruct = _optional_string(
            data.get("instruct", cls.instruct), "audio.voicebox.instruct"
        )
        if instruct is not None and len(instruct) > 500:
            raise _config_error("audio.voicebox.instruct cannot exceed 500 characters.")

        effects_preset = _optional_string(
            data.get("effects_preset", cls.effects_preset),
            "audio.voicebox.effects_preset",
        )
        if effects_preset is not None:
            raise _config_error(
                "Voicebox 0.5 POST /generate does not accept effects preset names. "
                "Set effects_preset to null and use an explicit effects_chain instead."
            )
        raw_effects = data.get("effects_chain", ())
        if raw_effects is None:
            effects: tuple[Mapping[str, Any], ...] = ()
        elif isinstance(raw_effects, Sequence) and not isinstance(raw_effects, (str, bytes)):
            if not all(isinstance(effect, Mapping) for effect in raw_effects):
                raise _config_error(
                    "audio.voicebox.effects_chain entries must be JSON objects."
                )
            effects = tuple(dict(effect) for effect in raw_effects)
        else:
            raise _config_error("audio.voicebox.effects_chain must be an array or null.")

        policy = data.get("unsupported_tag_policy", cls.unsupported_tag_policy)
        if policy not in {"error", "strip"}:
            raise _config_error(
                "audio.voicebox.unsupported_tag_policy must be 'error' or 'strip'."
            )
        normalize = data.get("normalize", cls.normalize)
        if not isinstance(normalize, bool):
            raise _config_error("audio.voicebox.normalize must be true or false.")

        return cls(
            base_url=base_url.strip().rstrip("/"),
            profile=profile,
            engine=engine.strip().lower() if engine is not None else None,
            language=language.strip().lower() if language is not None else None,
            model_size=model_size.strip() if model_size is not None else None,
            instruct=instruct,
            request_timeout_seconds=float(
                _number(
                    data.get("request_timeout_seconds", cls.request_timeout_seconds),
                    label="audio.voicebox.request_timeout_seconds",
                    integer=False,
                    minimum=1,
                    maximum=3600,
                )
            ),
            health_timeout_seconds=float(
                _number(
                    data.get("health_timeout_seconds", cls.health_timeout_seconds),
                    label="audio.voicebox.health_timeout_seconds",
                    integer=False,
                    minimum=0.1,
                    maximum=60,
                )
            ),
            poll_interval_seconds=float(
                _number(
                    data.get("poll_interval_seconds", cls.poll_interval_seconds),
                    label="audio.voicebox.poll_interval_seconds",
                    integer=False,
                    minimum=0.1,
                    maximum=30,
                )
            ),
            max_retries=int(
                _number(
                    data.get("max_retries", cls.max_retries),
                    label="audio.voicebox.max_retries",
                    integer=True,
                    minimum=0,
                    maximum=5,
                )
            ),
            effects_preset=None,
            effects_chain=effects,
            unsupported_tag_policy=policy,
            max_chunk_chars=int(
                _number(
                    data.get("max_chunk_chars", cls.max_chunk_chars),
                    label="audio.voicebox.max_chunk_chars",
                    integer=True,
                    minimum=100,
                    maximum=5000,
                )
            ),
            crossfade_ms=int(
                _number(
                    data.get("crossfade_ms", cls.crossfade_ms),
                    label="audio.voicebox.crossfade_ms",
                    integer=True,
                    minimum=0,
                    maximum=500,
                )
            ),
            normalize=normalize,
        )

    def safe_provenance_settings(self) -> dict[str, Any]:
        """Return behavior-affecting settings without raw profile identifiers."""

        return {
            "capability_map": "voicebox-0.5.0@da79e37",
            "engine": self.engine,
            "language": self.language,
            "model_size": self.model_size,
            "instruct": self.instruct,
            "effects_chain": [dict(item) for item in self.effects_chain],
            "unsupported_tag_policy": self.unsupported_tag_policy,
            "max_chunk_chars": self.max_chunk_chars,
            "crossfade_ms": self.crossfade_ms,
            "voicebox_normalize": self.normalize,
        }


@dataclass(frozen=True)
class AudioProviderSettings:
    provider: str
    fallback_provider: str | None
    allow_fallback: bool
    voicebox: VoiceboxSettings


def _merge_audio_layers(layers: Sequence[Mapping[str, Any] | None]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    merged_voicebox: dict[str, Any] = {}
    voicebox_seen = False
    for index, layer in enumerate(layers):
        current = _as_mapping(layer, f"audio precedence layer {index + 1}")
        _validate_unknown(current, _AUDIO_KEYS, "audio")
        for key, item in current.items():
            if key == "voicebox":
                nested = _as_mapping(item, "audio.voicebox")
                _validate_unknown(nested, _VOICEBOX_KEYS, "audio.voicebox")
                merged_voicebox.update(nested)
                voicebox_seen = True
            else:
                merged[key] = item
    if voicebox_seen:
        merged["voicebox"] = merged_voicebox
    return merged


def resolve_audio_provider_settings(
    *,
    legacy_provider: str,
    global_audio: Mapping[str, Any] | None = None,
    brand_audio: Mapping[str, Any] | None = None,
    episode_audio: Mapping[str, Any] | None = None,
    cli_audio: Mapping[str, Any] | None = None,
) -> AudioProviderSettings:
    """Resolve defaults <- global <- brand <- episode <- CLI without truthiness loss."""

    data = _merge_audio_layers(
        (global_audio, brand_audio, episode_audio, cli_audio)
    )
    configured_provider = data.get("provider")
    if configured_provider is None:
        provider = str(legacy_provider or "kittentts").strip().lower()
    elif isinstance(configured_provider, str) and configured_provider.strip():
        provider = configured_provider.strip().lower()
    else:
        raise _config_error(
            "audio.provider may be null to retain tts_provider, but an empty value is invalid."
        )
    if provider not in _LEGACY_PROVIDERS | {"voicebox"}:
        raise _config_error(
            f"Unknown audio.provider {provider!r}. Choose voicebox, elevenlabs, "
            "fishaudio, edge_tts, or kittentts."
        )

    allow_fallback = data.get("allow_fallback", False)
    if not isinstance(allow_fallback, bool):
        raise _config_error("audio.allow_fallback must be true or false.")
    raw_fallback = data.get("fallback_provider")
    if raw_fallback is None:
        fallback = None
    elif isinstance(raw_fallback, str):
        fallback = raw_fallback.strip().lower()
    else:
        raise _config_error("audio.fallback_provider must be a string or null.")
    if allow_fallback:
        if fallback not in _LEGACY_PROVIDERS:
            raise _config_error(
                "When audio.allow_fallback is true, audio.fallback_provider must be "
                "elevenlabs, fishaudio, edge_tts, or kittentts."
            )
        if fallback == provider:
            raise _config_error("audio.fallback_provider must differ from audio.provider.")

    voicebox = VoiceboxSettings.from_mapping(data.get("voicebox"))
    if provider == "voicebox" and not voicebox.profile.strip():
        raise _config_error(
            "Voicebox is selected but audio.voicebox.profile is empty. "
            "List profiles from the local /profiles endpoint and configure a name or id."
        )
    return AudioProviderSettings(
        provider=provider,
        fallback_provider=fallback,
        allow_fallback=allow_fallback,
        voicebox=voicebox,
    )
