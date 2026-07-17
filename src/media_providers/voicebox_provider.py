"""Voicebox 0.5 narration orchestration behind the shared AudioProvider contract."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from .audio_assets import (
    AudioInspection,
    atomic_write_immutable_bytes,
    atomic_write_json,
    inspect_audio,
    normalize_production_audio,
)
from .contracts import (
    GenerationRequest,
    GenerationResult,
    HealthState,
    ProviderCapabilities,
    ProviderHealth,
    ProviderKind,
    VoiceDescriptor,
)
from .errors import (
    ProviderConfigurationError,
    ProviderError,
    VoiceboxGenerationError,
    VoiceboxHealthCheckError,
    VoiceboxInvalidAudioError,
    VoiceboxInvalidEngineError,
    VoiceboxInvalidProfileError,
    VoiceboxNormalizationError,
    VoiceboxServiceUnavailableError,
    VoiceboxUnsupportedCapabilityError,
    VoiceboxVersionIncompatibilityError,
)
from .provenance import (
    canonical_json,
    create_asset_provenance,
    generation_request_hash,
    sha256_text,
)
from .voicebox_capabilities import (
    VOICEBOX_CAPABILITY_MAP_VERSION,
    VOICEBOX_ENGINES,
    VOICEBOX_MAX_TEXT_LENGTH,
    capabilities_for_engine,
    model_name_for_engine,
    prepare_performance_tags,
)
from .voicebox_client import VoiceboxClient
from .voicebox_schemas import VoiceboxHealth, VoiceboxProfile, VoiceboxServerInfo
from .voicebox_settings import VoiceboxSettings


_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


class VoiceboxAudioProvider:
    provider_id = "voicebox"
    engine = "voicebox-rest-0.5"

    def __init__(
        self,
        settings: VoiceboxSettings,
        *,
        client: VoiceboxClient | None = None,
        normalizer: Callable[[str | Path, str | Path], AudioInspection] = normalize_production_audio,
    ):
        self.settings = settings
        self.client = client or VoiceboxClient(
            settings.base_url,
            health_timeout_seconds=settings.health_timeout_seconds,
            request_timeout_seconds=settings.request_timeout_seconds,
            poll_interval_seconds=settings.poll_interval_seconds,
        )
        self._normalizer = normalizer

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self.provider_id,
            kinds=(ProviderKind.AUDIO,),
            output_formats=("wav",),
            operations=(
                "generate",
                "health",
                "discover_profiles",
                "discover_engines",
                "async_poll",
                "effects",
                "transcription_available_not_wired",
            ),
            is_local=True,
            requires_network=False,
            supports_seed=True,
            supports_streaming=True,
            supports_health_check=True,
        )

    @staticmethod
    def _verify_version(info: VoiceboxServerInfo) -> None:
        match = _VERSION.fullmatch(info.version)
        if not match or (int(match.group(1)), int(match.group(2))) != (0, 5):
            raise VoiceboxVersionIncompatibilityError(
                f"Voicebox API version {info.version!r} is outside the verified 0.5.x contract. "
                "Use Voicebox 0.5.x or re-audit the adapter against the installed version."
            )

    def _check_service(self) -> tuple[VoiceboxServerInfo, VoiceboxHealth]:
        info = self.client.server_info()
        self._verify_version(info)
        health = self.client.health()
        return info, health

    def health(self) -> ProviderHealth:
        try:
            info, health = self._check_service()
        except (ProviderConfigurationError, VoiceboxVersionIncompatibilityError) as exc:
            return ProviderHealth(
                HealthState.MISCONFIGURED,
                str(exc),
                details={"base_url": self.settings.base_url, "network_checked": True},
            )
        except (VoiceboxServiceUnavailableError, VoiceboxHealthCheckError) as exc:
            return ProviderHealth(
                HealthState.UNAVAILABLE,
                str(exc),
                details={"base_url": self.settings.base_url, "network_checked": True},
            )
        except ProviderError as exc:
            return ProviderHealth(
                HealthState.DEGRADED if exc.retryable else HealthState.UNAVAILABLE,
                str(exc),
                details={"base_url": self.settings.base_url, "network_checked": True},
            )
        return ProviderHealth(
            HealthState.READY,
            "Voicebox 0.5 local API is healthy.",
            details={
                "base_url": self.settings.base_url,
                "network_checked": True,
                "version": info.version,
                "model_loaded": health.model_loaded,
                "gpu_available": health.gpu_available,
                "backend_type": health.backend_type,
                "backend_variant": health.backend_variant,
            },
        )

    def discover_profiles(self) -> tuple[VoiceboxProfile, ...]:
        self._check_service()
        return self.client.list_profiles()

    def discover_engines(self) -> tuple[dict[str, Any], ...]:
        self._check_service()
        statuses = {item.model_name: item for item in self.client.list_models()}
        discovered = []
        for engine, capability in VOICEBOX_ENGINES.items():
            models = [statuses[name] for name in capability.model_names if name in statuses]
            discovered.append(
                {
                    "engine": engine,
                    "capability_map": VOICEBOX_CAPABILITY_MAP_VERSION,
                    "capabilities": capability.to_dict(),
                    "models": [
                        {
                            "model_name": item.model_name,
                            "display_name": item.display_name,
                            "downloaded": item.downloaded,
                            "downloading": item.downloading,
                            "loaded": item.loaded,
                        }
                        for item in models
                    ],
                }
            )
        return tuple(discovered)

    def _resolve_profile(self, profiles: tuple[VoiceboxProfile, ...]) -> VoiceboxProfile:
        selected = self.settings.profile.strip()
        exact_id = [profile for profile in profiles if profile.id == selected]
        by_name = [profile for profile in profiles if profile.name.casefold() == selected.casefold()]
        matches = exact_id or by_name
        if len(matches) != 1:
            raise VoiceboxInvalidProfileError(
                f"Voicebox profile {selected!r} was not found uniquely. "
                "List http://127.0.0.1:17493/profiles and configure an exact name or id."
            )
        return matches[0]

    @staticmethod
    def _validate_profile_engine(profile: VoiceboxProfile, engine: str) -> None:
        capability = capabilities_for_engine(engine)
        if profile.voice_type == "preset":
            if not profile.preset_engine or profile.preset_engine != engine:
                raise VoiceboxInvalidProfileError(
                    f"Preset profile {profile.name!r} requires engine "
                    f"{profile.preset_engine!r}, not {engine!r}."
                )
            if not capability.preset_voices:
                raise VoiceboxInvalidProfileError(
                    f"Engine {engine!r} is not mapped as a preset-voice engine."
                )
            return
        if profile.voice_type == "designed":
            raise VoiceboxUnsupportedCapabilityError(
                "Voicebox designed profiles are not enabled for factual narration in this adapter."
            )
        if profile.voice_type != "cloned":
            raise VoiceboxInvalidProfileError(
                f"Voicebox profile type {profile.voice_type!r} is not supported."
            )
        if not capability.voice_cloning:
            raise VoiceboxInvalidProfileError(
                f"Engine {engine!r} does not support cloned voice profiles."
            )

    def _validate_model_available(self, model_name: str) -> None:
        statuses = {item.model_name: item for item in self.client.list_models()}
        status = statuses.get(model_name)
        if status is None:
            raise VoiceboxVersionIncompatibilityError(
                f"Voicebox /models/status did not advertise required model {model_name!r}. "
                "Confirm the running service matches Voicebox 0.5.x."
            )
        if status.downloading:
            raise VoiceboxServiceUnavailableError(
                f"Voicebox model {model_name!r} is still downloading. Wait for the manual "
                "Voicebox download to finish; MoneyPrinter will not start model downloads."
            )
        if not status.downloaded:
            raise VoiceboxServiceUnavailableError(
                f"Voicebox model {model_name!r} is not installed. Download it manually in "
                "Voicebox before selecting this provider; MoneyPrinter will not download weights."
            )

    def _artifact_directory(self, request: GenerationRequest, request_hash: str) -> Path:
        request_id = _SAFE_ID.sub("-", request.request_id).strip("-._") or "request"
        return (
            Path(request.output_path).resolve().parent
            / "narration"
            / f"{request_hash[:20]}-{request_id[:20]}"
        )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if len(request.content) > VOICEBOX_MAX_TEXT_LENGTH:
            raise VoiceboxGenerationError(
                f"Narration has {len(request.content)} characters; Voicebox 0.5 accepts at most "
                f"{VOICEBOX_MAX_TEXT_LENGTH}. Split the script intentionally."
            )
        self._check_service()
        profiles = self.client.list_profiles()
        profile = self._resolve_profile(profiles)
        if request.voice and request.voice.provider != self.provider_id:
            raise VoiceboxInvalidProfileError(
                f"Generation request voice belongs to {request.voice.provider!r}, not Voicebox."
            )

        engine = (
            self.settings.engine
            if self.settings.engine is not None
            else profile.default_engine or profile.preset_engine or "qwen"
        )
        capability = capabilities_for_engine(engine)
        self._validate_profile_engine(profile, engine)
        model_name, model_size = model_name_for_engine(engine, self.settings.model_size)
        supported_languages = capability.languages
        if engine == "tada" and model_size == "1B":
            supported_languages = ("en",)
        language = self.settings.language or profile.language or "en"
        if language not in supported_languages:
            raise VoiceboxUnsupportedCapabilityError(
                f"Engine {engine!r} does not support language {language!r}. "
                f"Choose one of: {', '.join(supported_languages)}."
            )
        if self.settings.instruct is not None and not capability.delivery_instructions:
            raise VoiceboxUnsupportedCapabilityError(
                f"Engine {engine!r} does not honor delivery instructions in Voicebox 0.5. "
                "Use qwen_custom_voice or remove audio.voicebox.instruct."
            )
        text, warnings = prepare_performance_tags(
            request.content,
            engine=engine,
            unsupported_policy=self.settings.unsupported_tag_policy,
        )
        self._validate_model_available(model_name)

        resolved_settings = self.settings.safe_provenance_settings()
        resolved_settings.update(
            {
                "engine": engine,
                "language": language,
                "model_size": model_size,
                "performance_tags_transformed": text != request.content,
            }
        )
        resolved_request = replace(
            request,
            content=text,
            settings=resolved_settings,
            voice=VoiceDescriptor(
                provider=self.provider_id,
                voice_id=profile.id,
                display_name=profile.name,
                language=language,
                model=engine,
                settings={
                    "voice_type": profile.voice_type,
                    "profile_updated_at": profile.updated_at,
                    "sample_count": profile.sample_count,
                },
            ),
        )
        request_hash = generation_request_hash(
            resolved_request,
            provider=self.provider_id,
            engine=self.engine,
            model=model_name,
            model_version=VOICEBOX_CAPABILITY_MAP_VERSION,
            settings=resolved_settings,
        )
        artifact_dir = self._artifact_directory(resolved_request, request_hash)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        request_manifest_path = artifact_dir / "voicebox_request.json"
        request_manifest = {
            "schema_version": 1,
            "provider": self.provider_id,
            "api_assumption": "0.5.x",
            "capability_map": VOICEBOX_CAPABILITY_MAP_VERSION,
            "request_id": resolved_request.request_id,
            "request_hash": request_hash,
            "text_sha256": sha256_text(text),
            "text_length": len(text),
            "profile_id_sha256": sha256_text(profile.id),
            "profile_name_sha256": sha256_text(profile.name),
            "profile_source_sha256": sha256_text(
                canonical_json(
                    {
                        "id": profile.id,
                        "updated_at": profile.updated_at,
                        "sample_count": profile.sample_count,
                        "voice_type": profile.voice_type,
                        "preset_engine": profile.preset_engine,
                    }
                )
            ),
            "engine": engine,
            "model_name": model_name,
            "model_size": model_size,
            "language": language,
            "seed": resolved_request.seed,
            "instruct": self.settings.instruct,
            "effects_chain": [dict(effect) for effect in self.settings.effects_chain],
            "max_chunk_chars": self.settings.max_chunk_chars,
            "crossfade_ms": self.settings.crossfade_ms,
            "voicebox_normalize": self.settings.normalize,
            "unsupported_tag_policy": self.settings.unsupported_tag_policy,
            "status": "submitting",
            "attempt_count": 0,
        }
        atomic_write_json(request_manifest_path, request_manifest)

        payload: dict[str, Any] = {
            "profile_id": profile.id,
            "text": text,
            "language": language,
            "engine": engine,
            "max_chunk_chars": self.settings.max_chunk_chars,
            "crossfade_ms": self.settings.crossfade_ms,
            "normalize": self.settings.normalize,
        }
        if resolved_request.seed is not None:
            payload["seed"] = resolved_request.seed
        if model_size is not None:
            payload["model_size"] = model_size
        if self.settings.instruct is not None:
            payload["instruct"] = self.settings.instruct
        if self.settings.effects_chain:
            payload["effects_chain"] = [dict(effect) for effect in self.settings.effects_chain]

        attempts = 0
        try:
            while True:
                attempts += 1
                try:
                    submitted = self.client.submit_generation(payload)
                    completed = self.client.wait_for_generation(submitted)
                    download = self.client.download_audio(completed.id)
                    break
                except ProviderError as exc:
                    exc.attempt_count = attempts
                    if not exc.retryable or attempts > self.settings.max_retries:
                        raise
            request_manifest.update(
                {
                    "status": "downloaded",
                    "attempt_count": attempts,
                    "generation_id": completed.id,
                    "response_content_type": download.content_type,
                }
            )
            atomic_write_json(request_manifest_path, request_manifest)
        except ProviderError as exc:
            request_manifest.update(
                {
                    "status": "failed",
                    "attempt_count": attempts,
                    "error_class": type(exc).__name__,
                }
            )
            atomic_write_json(request_manifest_path, request_manifest)
            raise

        original_path = artifact_dir / "voicebox_original.wav"
        production_path = artifact_dir / "production_audio.wav"
        try:
            atomic_write_immutable_bytes(original_path, download.content)
            original_validation = inspect_audio(original_path)
            if original_validation.format.upper() not in {"WAV", "WAVEX"}:
                raise VoiceboxInvalidAudioError(
                    f"Voicebox returned {original_validation.format or 'unknown'} audio; "
                    "the verified generation contract requires WAV."
                )
            production_validation = self._normalizer(original_path, production_path)
            if (
                production_validation.sample_rate_hz != 44_100
                or production_validation.channels != 2
                or production_validation.subtype.upper() != "PCM_16"
            ):
                raise VoiceboxNormalizationError(
                    "Derived production audio must be 44.1 kHz stereo PCM_16."
                )
        except ProviderError as exc:
            try:
                production_path.unlink(missing_ok=True)
            except OSError:
                pass
            request_manifest.update(
                {
                    "status": "failed",
                    "attempt_count": attempts,
                    "error_class": type(exc).__name__,
                }
            )
            atomic_write_json(request_manifest_path, request_manifest)
            exc.attempt_count = attempts
            raise
        validation = {
            "schema_version": 1,
            "valid": True,
            "original": original_validation.to_dict(),
            "production": production_validation.to_dict(),
            "normalization": {
                "source_immutable": True,
                "atomic_derived_write": True,
                "target_sample_rate_hz": 44100,
                "target_channels": 2,
            },
        }
        atomic_write_json(artifact_dir / "audio_validation.json", validation)

        final_request = replace(resolved_request, retry_count=attempts - 1)
        provenance = create_asset_provenance(
            final_request,
            provider=self.provider_id,
            engine=self.engine,
            model=model_name,
            model_version=VOICEBOX_CAPABILITY_MAP_VERSION,
            output_path=production_path,
            source_artifact_hash=original_validation.sha256,
            settings=resolved_settings,
        )
        atomic_write_json(artifact_dir / "provenance.json", provenance.to_dict())
        request_manifest.update(
            {
                "status": "completed",
                "source_sha256": original_validation.sha256,
                "production_sha256": production_validation.sha256,
            }
        )
        atomic_write_json(request_manifest_path, request_manifest)
        return GenerationResult(
            provider_id=self.provider_id,
            output_path=production_path,
            provenance=provenance,
            media_type="audio/wav",
            warnings=warnings,
            metadata={
                "artifact_directory": str(artifact_dir),
                "generation_id": completed.id,
                "engine": engine,
                "model_name": model_name,
                "model_size": model_size,
                "language": language,
                "profile_id_sha256": sha256_text(profile.id),
                "request_hash": request_hash,
                "source_sha256": original_validation.sha256,
                "production_sha256": production_validation.sha256,
                "attempt_count": attempts,
                "audio_validation": validation,
            },
        )


def build_voicebox_provider(settings: VoiceboxSettings) -> VoiceboxAudioProvider:
    """Composition boundary used by the legacy TTS dispatcher after opt-in."""

    return VoiceboxAudioProvider(settings)
