"""Typed, provider-neutral contracts for generated local-media assets.

These contracts are intentionally additive. Existing MoneyPrinter generation
paths can be wrapped by adapters without being rewritten around this package.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping, Protocol, runtime_checkable
from uuid import uuid4


_PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp suitable for durable JSON."""

    return datetime.now(timezone.utc).isoformat()


def _provider_id(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _PROVIDER_ID.fullmatch(normalized):
        raise ValueError(
            "provider_id must start with a letter or digit and contain only "
            "lowercase letters, digits, '.', '_', or '-'"
        )
    return normalized


def _json_mapping(value: Mapping[str, Any] | None, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    result = dict(value)
    try:
        json.dumps(result, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain JSON-serializable values") from exc
    return result


def _iso_timestamp(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return text


def _hash(value: str, field_name: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized and not _SHA256.fullmatch(normalized):
        raise ValueError(f"{field_name} must be an empty value or a SHA-256 hex digest")
    return normalized


class ProviderKind(str, Enum):
    AUDIO = "audio"
    SONG = "song"
    VIDEO = "video"


class HealthState(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    MISCONFIGURED = "misconfigured"
    UNKNOWN = "unknown"


class HumanApprovalState(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ProviderHealth:
    state: HealthState
    message: str
    checked_at: str = field(default_factory=utc_now)
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", HealthState(self.state))
        if not str(self.message or "").strip():
            raise ValueError("provider health message must not be empty")
        object.__setattr__(self, "checked_at", _iso_timestamp(self.checked_at, "checked_at"))
        object.__setattr__(self, "details", _json_mapping(self.details, "details"))

    @property
    def usable(self) -> bool:
        return self.state in {HealthState.READY, HealthState.DEGRADED}

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "message": self.message,
            "checked_at": self.checked_at,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class ProviderCapabilities:
    provider_id: str
    kinds: tuple[ProviderKind, ...]
    output_formats: tuple[str, ...] = ()
    operations: tuple[str, ...] = ("generate",)
    is_local: bool = False
    requires_network: bool = True
    supports_seed: bool = False
    supports_streaming: bool = False
    supports_health_check: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        kinds = tuple(ProviderKind(kind) for kind in self.kinds)
        if not kinds:
            raise ValueError("provider capabilities require at least one kind")
        object.__setattr__(self, "kinds", kinds)
        object.__setattr__(
            self,
            "output_formats",
            tuple(str(value).strip().lower().lstrip(".") for value in self.output_formats),
        )
        operations = tuple(str(value).strip().lower() for value in self.operations if str(value).strip())
        if not operations:
            raise ValueError("provider capabilities require at least one operation")
        object.__setattr__(self, "operations", operations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "kinds": [kind.value for kind in self.kinds],
            "output_formats": list(self.output_formats),
            "operations": list(self.operations),
            "is_local": self.is_local,
            "requires_network": self.requires_network,
            "supports_seed": self.supports_seed,
            "supports_streaming": self.supports_streaming,
            "supports_health_check": self.supports_health_check,
        }


@dataclass(frozen=True)
class VoiceDescriptor:
    provider: str
    voice_id: str
    display_name: str = ""
    language: str = ""
    model: str = ""
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _provider_id(self.provider))
        if not str(self.voice_id or "").strip():
            raise ValueError("voice_id must not be empty")
        object.__setattr__(self, "settings", _json_mapping(self.settings, "settings"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "voice_id": self.voice_id,
            "display_name": self.display_name,
            "language": self.language,
            "model": self.model,
            "settings": dict(self.settings),
        }


@dataclass(frozen=True)
class GenerationRequest:
    content: str
    output_path: str | os.PathLike[str]
    request_id: str = field(default_factory=lambda: str(uuid4()))
    settings: Mapping[str, Any] = field(default_factory=dict)
    seed: int | None = None
    voice: VoiceDescriptor | None = None
    parent_artifact: str = ""
    retry_count: int = 0
    fallback_behavior: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.content or "").strip():
            raise ValueError("generation content must not be empty")
        path = os.fspath(self.output_path)
        if not path:
            raise ValueError("output_path must not be empty")
        object.__setattr__(self, "output_path", path)
        if not str(self.request_id or "").strip():
            raise ValueError("request_id must not be empty")
        object.__setattr__(self, "settings", _json_mapping(self.settings, "settings"))
        object.__setattr__(self, "metadata", _json_mapping(self.metadata, "metadata"))
        if self.seed is not None and not isinstance(self.seed, int):
            raise ValueError("seed must be an integer or None")
        if int(self.retry_count) < 0:
            raise ValueError("retry_count must be zero or greater")
        object.__setattr__(self, "retry_count", int(self.retry_count))

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "output_path": str(self.output_path),
            "request_id": self.request_id,
            "settings": dict(self.settings),
            "seed": self.seed,
            "voice": self.voice.to_dict() if self.voice else None,
            "parent_artifact": self.parent_artifact,
            "retry_count": self.retry_count,
            "fallback_behavior": self.fallback_behavior,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GenerationRequest":
        voice_value = value.get("voice")
        voice = VoiceDescriptor(**voice_value) if isinstance(voice_value, Mapping) else None
        return cls(
            content=str(value.get("content") or ""),
            output_path=os.fspath(value.get("output_path") or ""),
            request_id=str(value.get("request_id") or ""),
            settings=value.get("settings") or {},
            seed=value.get("seed"),
            voice=voice,
            parent_artifact=str(value.get("parent_artifact") or ""),
            retry_count=int(value.get("retry_count") or 0),
            fallback_behavior=str(value.get("fallback_behavior") or ""),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True)
class AssetProvenance:
    provider: str
    engine: str
    model: str = ""
    model_version: str = ""
    request_hash: str = ""
    input_content_hash: str = ""
    source_artifact_hash: str = ""
    derived_artifact_hash: str = ""
    seed: int | None = None
    settings: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    parent_artifact: str = ""
    human_approval_state: HumanApprovalState = HumanApprovalState.PENDING
    retry_count: int = 0
    fallback_behavior: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _provider_id(self.provider))
        if not str(self.engine or "").strip():
            raise ValueError("provenance engine must not be empty")
        for name in (
            "request_hash",
            "input_content_hash",
            "source_artifact_hash",
            "derived_artifact_hash",
        ):
            object.__setattr__(self, name, _hash(getattr(self, name), name))
        if self.seed is not None and not isinstance(self.seed, int):
            raise ValueError("seed must be an integer or None")
        object.__setattr__(self, "settings", _json_mapping(self.settings, "settings"))
        object.__setattr__(self, "created_at", _iso_timestamp(self.created_at, "created_at"))
        object.__setattr__(
            self,
            "human_approval_state",
            HumanApprovalState(self.human_approval_state),
        )
        if int(self.retry_count) < 0:
            raise ValueError("retry_count must be zero or greater")
        object.__setattr__(self, "retry_count", int(self.retry_count))
        if int(self.schema_version) != 1:
            raise ValueError(f"unsupported provenance schema version {self.schema_version}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "engine": self.engine,
            "model": self.model,
            "model_version": self.model_version,
            "request_hash": self.request_hash,
            "input_content_hash": self.input_content_hash,
            "source_artifact_hash": self.source_artifact_hash,
            "derived_artifact_hash": self.derived_artifact_hash,
            "seed": self.seed,
            "settings": dict(self.settings),
            "created_at": self.created_at,
            "parent_artifact": self.parent_artifact,
            "human_approval_state": self.human_approval_state.value,
            "retry_count": self.retry_count,
            "fallback_behavior": self.fallback_behavior,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AssetProvenance":
        return cls(
            provider=str(value.get("provider") or ""),
            engine=str(value.get("engine") or ""),
            model=str(value.get("model") or ""),
            model_version=str(value.get("model_version") or ""),
            request_hash=str(value.get("request_hash") or ""),
            input_content_hash=str(value.get("input_content_hash") or ""),
            source_artifact_hash=str(value.get("source_artifact_hash") or ""),
            derived_artifact_hash=str(value.get("derived_artifact_hash") or ""),
            seed=value.get("seed"),
            settings=value.get("settings") or {},
            created_at=str(value.get("created_at") or ""),
            parent_artifact=str(value.get("parent_artifact") or ""),
            human_approval_state=HumanApprovalState(
                value.get("human_approval_state") or HumanApprovalState.PENDING
            ),
            retry_count=int(value.get("retry_count") or 0),
            fallback_behavior=str(value.get("fallback_behavior") or ""),
            schema_version=int(value.get("schema_version") or 1),
        )


@dataclass(frozen=True)
class GenerationResult:
    provider_id: str
    output_path: str | os.PathLike[str]
    provenance: AssetProvenance
    media_type: str = "audio"
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        path = os.fspath(self.output_path)
        if not path:
            raise ValueError("result output_path must not be empty")
        object.__setattr__(self, "output_path", path)
        if self.provenance.provider != self.provider_id:
            raise ValueError("result provider_id must match provenance provider")
        object.__setattr__(self, "warnings", tuple(str(value) for value in self.warnings))
        object.__setattr__(self, "metadata", _json_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "output_path": str(self.output_path),
            "media_type": self.media_type,
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True)
class SongCandidate:
    candidate_id: str
    provider_id: str
    output_path: str | os.PathLike[str]
    provenance: AssetProvenance
    title: str = ""
    duration_seconds: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.candidate_id or "").strip():
            raise ValueError("song candidate_id must not be empty")
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        object.__setattr__(self, "output_path", os.fspath(self.output_path))
        if self.provenance.provider != self.provider_id:
            raise ValueError("song provider_id must match provenance provider")
        if self.duration_seconds is not None and float(self.duration_seconds) <= 0:
            raise ValueError("song duration_seconds must be positive when provided")
        object.__setattr__(self, "metadata", _json_mapping(self.metadata, "metadata"))


@dataclass(frozen=True)
class VideoResult:
    provider_id: str
    output_path: str | os.PathLike[str]
    provenance: AssetProvenance
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        object.__setattr__(self, "output_path", os.fspath(self.output_path))
        if self.provenance.provider != self.provider_id:
            raise ValueError("video provider_id must match provenance provider")
        if self.duration_seconds is not None and float(self.duration_seconds) <= 0:
            raise ValueError("video duration_seconds must be positive when provided")
        if self.width is not None and int(self.width) <= 0:
            raise ValueError("video width must be positive when provided")
        if self.height is not None and int(self.height) <= 0:
            raise ValueError("video height must be positive when provided")
        if self.fps is not None and float(self.fps) <= 0:
            raise ValueError("video fps must be positive when provided")
        object.__setattr__(self, "metadata", _json_mapping(self.metadata, "metadata"))


@runtime_checkable
class AudioProvider(Protocol):
    provider_id: str

    def health(self) -> ProviderHealth: ...

    def capabilities(self) -> ProviderCapabilities: ...

    def generate(self, request: GenerationRequest) -> GenerationResult: ...


@runtime_checkable
class SongProvider(Protocol):
    provider_id: str

    def health(self) -> ProviderHealth: ...

    def capabilities(self) -> ProviderCapabilities: ...

    def generate(self, request: GenerationRequest) -> tuple[SongCandidate, ...]: ...


@runtime_checkable
class VideoProvider(Protocol):
    provider_id: str

    def health(self) -> ProviderHealth: ...

    def capabilities(self) -> ProviderCapabilities: ...

    def generate(self, request: GenerationRequest) -> VideoResult: ...


ProviderInstance = AudioProvider | SongProvider | VideoProvider
ProviderFactory = Callable[[], ProviderInstance]


@dataclass(frozen=True)
class ProviderRegistryEntry:
    provider_id: str
    kind: ProviderKind
    factory: ProviderFactory
    enabled: bool = True
    config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        object.__setattr__(self, "kind", ProviderKind(self.kind))
        if not callable(self.factory):
            raise ValueError("provider registry factory must be callable")
        object.__setattr__(self, "config", _json_mapping(self.config, "config"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "kind": self.kind.value,
            "enabled": self.enabled,
            "config": dict(self.config),
        }
