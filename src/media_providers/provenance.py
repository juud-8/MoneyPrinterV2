"""Canonical SHA-256 helpers and provenance construction."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Mapping

from .contracts import (
    AssetProvenance,
    GenerationRequest,
    HumanApprovalState,
)


def canonical_json(value: Any) -> str:
    """Serialize JSON deterministically for stable cross-process hashes."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(str(value or "").encode("utf-8"))


def sha256_file(path: str | os.PathLike[str], *, chunk_size: int = 1024 * 1024) -> str:
    """Hash an artifact using the same chunked pattern as Archive Song identity."""

    if int(chunk_size) <= 0:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    with open(os.fspath(path), "rb") as file:
        while True:
            chunk = file.read(int(chunk_size))
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def generation_request_hash(
    request: GenerationRequest,
    *,
    provider: str,
    engine: str,
    model: str = "",
    model_version: str = "",
    settings: Mapping[str, Any] | None = None,
) -> str:
    """Hash semantic generation inputs, excluding machine-specific output paths."""

    voice = None
    if request.voice:
        voice = {
            "provider": request.voice.provider,
            # Voice identifiers can identify an account. Hash them before
            # recording request identity or provenance.
            "voice_id_hash": sha256_text(request.voice.voice_id),
            "language": request.voice.language,
            "model": request.voice.model,
            "settings": dict(request.voice.settings),
        }
    payload = {
        "provider": str(provider),
        "engine": str(engine),
        "model": str(model),
        "model_version": str(model_version),
        "input_content_hash": sha256_text(request.content),
        "settings": dict(settings if settings is not None else request.settings),
        "seed": request.seed,
        "voice": voice,
        "parent_artifact": request.parent_artifact,
    }
    return sha256_text(canonical_json(payload))


def create_asset_provenance(
    request: GenerationRequest,
    *,
    provider: str,
    engine: str,
    model: str = "",
    model_version: str = "",
    output_path: str | os.PathLike[str] | None = None,
    source_artifact_hash: str = "",
    settings: Mapping[str, Any] | None = None,
    human_approval_state: HumanApprovalState = HumanApprovalState.PENDING,
) -> AssetProvenance:
    """Build validated provenance without persisting credentials or raw content."""

    recorded_settings = dict(settings if settings is not None else request.settings)
    path = os.fspath(output_path) if output_path is not None else ""
    derived_hash = sha256_file(path) if path and os.path.isfile(path) else ""
    return AssetProvenance(
        provider=provider,
        engine=engine,
        model=model,
        model_version=model_version,
        request_hash=generation_request_hash(
            request,
            provider=provider,
            engine=engine,
            model=model,
            model_version=model_version,
            settings=recorded_settings,
        ),
        input_content_hash=sha256_text(request.content),
        source_artifact_hash=source_artifact_hash,
        derived_artifact_hash=derived_hash,
        seed=request.seed,
        settings=recorded_settings,
        parent_artifact=request.parent_artifact,
        human_approval_state=human_approval_state,
        retry_count=request.retry_count,
        fallback_behavior=request.fallback_behavior,
    )
