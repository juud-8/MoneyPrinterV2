"""Non-invasive adapter for the existing ElevenLabs narration method."""

from __future__ import annotations

from typing import Any, Callable, Protocol

from config import (
    get_elevenlabs_api_key,
    get_elevenlabs_model,
    get_elevenlabs_voice_id,
)

from .contracts import (
    GenerationRequest,
    GenerationResult,
    HealthState,
    ProviderCapabilities,
    ProviderHealth,
    ProviderKind,
    ProviderRegistryEntry,
)
from .errors import (
    ProviderConfigurationError,
    ProviderError,
    ProviderGenerationError,
)
from .provenance import create_asset_provenance, sha256_text


class LegacyElevenLabsTTS(Protocol):
    def _synthesize_elevenlabs(self, text: str, output_file: str) -> str: ...


class ElevenLabsNarrationAdapter:
    """Expose the current private synthesis seam as an ``AudioProvider``.

    Existing callers continue using ``TTS.synthesize``. Only new provider-aware
    code opts into this adapter, so the historical fallback and render behavior
    cannot change merely because the foundation exists.
    """

    provider_id = "elevenlabs"
    engine = "moneyprinter-v2.classes.Tts.TTS._synthesize_elevenlabs"

    def __init__(self, legacy_tts: LegacyElevenLabsTTS):
        self._legacy_tts = legacy_tts

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self.provider_id,
            kinds=(ProviderKind.AUDIO,),
            output_formats=("mp3",),
            operations=("generate",),
            is_local=False,
            requires_network=True,
            supports_seed=False,
            supports_streaming=False,
        )

    def health(self) -> ProviderHealth:
        if not callable(getattr(self._legacy_tts, "_synthesize_elevenlabs", None)):
            return ProviderHealth(
                HealthState.MISCONFIGURED,
                "Legacy TTS object does not expose the ElevenLabs synthesis method.",
            )
        try:
            api_key = get_elevenlabs_api_key()
            voice_id = get_elevenlabs_voice_id()
            model = get_elevenlabs_model()
        except Exception as exc:
            return ProviderHealth(
                HealthState.MISCONFIGURED,
                f"Could not load ElevenLabs configuration: {exc}",
            )
        missing = []
        if not api_key:
            missing.append("api key")
        if not voice_id:
            missing.append("voice id")
        if not model:
            missing.append("model")
        if missing:
            return ProviderHealth(
                HealthState.MISCONFIGURED,
                "ElevenLabs configuration is missing " + ", ".join(missing) + ".",
                details={"missing": missing, "network_checked": False},
            )
        return ProviderHealth(
            HealthState.READY,
            "ElevenLabs configuration is present; network was not probed.",
            details={"network_checked": False},
        )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        health = self.health()
        if not health.usable:
            raise ProviderConfigurationError(self.provider_id, health.message)
        if request.voice and request.voice.provider != self.provider_id:
            raise ProviderConfigurationError(
                self.provider_id,
                f"voice belongs to provider {request.voice.provider!r}",
            )
        try:
            # Preserve the exact legacy call boundary. It controls request
            # payload, voice settings, file naming, and last-provider metadata.
            output_path = self._legacy_tts._synthesize_elevenlabs(
                request.content,
                str(request.output_path),
            )
            voice_id = get_elevenlabs_voice_id()
            model = get_elevenlabs_model()
            settings = dict(request.settings)
            settings.update(
                {
                    "legacy_adapter": True,
                    "voice_id_hash": sha256_text(voice_id),
                }
            )
            source_hash = str(request.metadata.get("source_artifact_hash") or "")
            provenance = create_asset_provenance(
                request,
                provider=self.provider_id,
                engine=self.engine,
                model=model,
                output_path=output_path,
                source_artifact_hash=source_hash,
                settings=settings,
            )
            return GenerationResult(
                provider_id=self.provider_id,
                output_path=output_path,
                provenance=provenance,
                media_type="audio/mpeg",
                metadata={"legacy_adapter": True},
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderGenerationError(
                self.provider_id,
                f"legacy narration synthesis failed: {exc}",
                retryable=True,
            ) from exc


def elevenlabs_registry_entry(
    legacy_tts_factory: Callable[[], LegacyElevenLabsTTS],
    *,
    enabled: bool = True,
) -> ProviderRegistryEntry:
    """Build a registry entry without importing or instantiating ``TTS`` here."""

    return ProviderRegistryEntry(
        provider_id=ElevenLabsNarrationAdapter.provider_id,
        kind=ProviderKind.AUDIO,
        factory=lambda: ElevenLabsNarrationAdapter(legacy_tts_factory()),
        enabled=enabled,
        config={"adapter": "legacy_tts"},
    )
