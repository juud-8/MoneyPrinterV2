"""Backwards-compatible contracts for optional media providers."""

from .contracts import (
    AssetProvenance,
    AudioProvider,
    GenerationRequest,
    GenerationResult,
    HealthState,
    HumanApprovalState,
    ProviderCapabilities,
    ProviderHealth,
    ProviderKind,
    ProviderRegistryEntry,
    SongCandidate,
    SongProvider,
    VideoProvider,
    VideoResult,
    VoiceDescriptor,
)
from .elevenlabs_adapter import (
    ElevenLabsNarrationAdapter,
    elevenlabs_registry_entry,
)
from .errors import (
    ProviderConfigurationError,
    ProviderError,
    ProviderGenerationError,
    ProviderUnavailableError,
    UnknownProviderError,
)
from .provenance import (
    canonical_json,
    create_asset_provenance,
    generation_request_hash,
    sha256_bytes,
    sha256_file,
    sha256_text,
)
from .registry import ProviderRegistry

__all__ = [
    "AssetProvenance",
    "AudioProvider",
    "ElevenLabsNarrationAdapter",
    "GenerationRequest",
    "GenerationResult",
    "HealthState",
    "HumanApprovalState",
    "ProviderCapabilities",
    "ProviderConfigurationError",
    "ProviderError",
    "ProviderGenerationError",
    "ProviderHealth",
    "ProviderKind",
    "ProviderRegistry",
    "ProviderRegistryEntry",
    "ProviderUnavailableError",
    "SongCandidate",
    "SongProvider",
    "UnknownProviderError",
    "VideoProvider",
    "VideoResult",
    "VoiceDescriptor",
    "canonical_json",
    "create_asset_provenance",
    "elevenlabs_registry_entry",
    "generation_request_hash",
    "sha256_bytes",
    "sha256_file",
    "sha256_text",
]
