"""Narrow HTTP transport for the separately running Voicebox 0.5 service."""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

import requests

from .errors import (
    VoiceboxAuthenticationError,
    VoiceboxGenerationError,
    VoiceboxHealthCheckError,
    VoiceboxMalformedResponseError,
    VoiceboxMissingResultError,
    VoiceboxRequestTimeoutError,
    VoiceboxServiceUnavailableError,
)
from .voicebox_schemas import (
    VoiceboxAudioDownload,
    VoiceboxGeneration,
    VoiceboxHealth,
    VoiceboxModelStatus,
    VoiceboxProfile,
    VoiceboxServerInfo,
)


def _error_detail(response: Any) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, Mapping):
        detail = payload.get("detail")
        if isinstance(detail, Mapping):
            detail = detail.get("message") or detail
        if isinstance(detail, list):
            parts = []
            for item in detail:
                if isinstance(item, Mapping):
                    parts.append(str(item.get("msg") or item))
                else:
                    parts.append(str(item))
            return "; ".join(parts)
        if detail is not None:
            return str(detail)
    text = str(getattr(response, "text", "") or "").strip()
    return text[:500] or f"HTTP {getattr(response, 'status_code', 'error')}"


class VoiceboxClient:
    """Synchronous client used by the existing synchronous narration pipeline."""

    def __init__(
        self,
        base_url: str,
        *,
        health_timeout_seconds: float = 5.0,
        request_timeout_seconds: float = 600.0,
        poll_interval_seconds: float = 1.0,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.base_url = str(base_url).rstrip("/")
        self.health_timeout_seconds = float(health_timeout_seconds)
        self.request_timeout_seconds = float(request_timeout_seconds)
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._session = session or requests.Session()
        self._clock = clock
        self._sleep = sleeper

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float,
        json_body: Mapping[str, Any] | None = None,
    ) -> Any:
        kwargs: dict[str, Any] = {"timeout": float(timeout)}
        if json_body is not None:
            kwargs["json"] = dict(json_body)
        try:
            response = self._session.request(method, self._url(path), **kwargs)
        except requests.Timeout as exc:
            raise VoiceboxRequestTimeoutError(
                f"Request to {path} timed out after {timeout:g} seconds.",
                retryable=True,
            ) from exc
        except requests.ConnectionError as exc:
            raise VoiceboxServiceUnavailableError(
                f"Voicebox is not reachable at {self.base_url}. Start Voicebox and "
                "confirm its local API is enabled, or select another narration provider.",
                retryable=True,
            ) from exc
        except requests.RequestException as exc:
            raise VoiceboxServiceUnavailableError(
                f"Voicebox request to {path} failed: {exc}", retryable=True
            ) from exc

        status = int(getattr(response, "status_code", 0))
        if status in {401, 403}:
            raise VoiceboxAuthenticationError(
                "The local Voicebox service rejected the request. MoneyPrinter does not "
                "send authorization headers; inspect any reverse proxy or local API policy."
            )
        if status >= 400:
            detail = _error_detail(response)
            raise VoiceboxGenerationError(
                f"Voicebox {path} returned HTTP {status}: {detail}",
                retryable=status >= 500 or status in {408, 429},
            )
        return response

    def _json(
        self,
        method: str,
        path: str,
        *,
        timeout: float,
        json_body: Mapping[str, Any] | None = None,
    ) -> Any:
        response = self._request(
            method, path, timeout=timeout, json_body=json_body
        )
        try:
            return response.json()
        except (TypeError, ValueError) as exc:
            raise VoiceboxMalformedResponseError(
                f"Voicebox {path} did not return valid JSON."
            ) from exc

    def server_info(self) -> VoiceboxServerInfo:
        # Packaged Voicebox may serve its SPA at `/`; FastAPI's runtime
        # OpenAPI document remains the stable version-bearing API surface.
        return VoiceboxServerInfo.from_openapi(
            self._json("GET", "/openapi.json", timeout=self.health_timeout_seconds)
        )

    def health(self) -> VoiceboxHealth:
        try:
            result = VoiceboxHealth.from_json(
                self._json("GET", "/health", timeout=self.health_timeout_seconds)
            )
        except VoiceboxRequestTimeoutError as exc:
            raise VoiceboxHealthCheckError(
                f"Voicebox health check timed out after {self.health_timeout_seconds:g} seconds."
            ) from exc
        if result.status.lower() != "healthy":
            raise VoiceboxHealthCheckError(
                f"Voicebox reported status {result.status!r}. Inspect the Voicebox service logs."
            )
        return result

    def list_profiles(self) -> tuple[VoiceboxProfile, ...]:
        payload = self._json(
            "GET", "/profiles", timeout=self.health_timeout_seconds
        )
        if not isinstance(payload, list):
            raise VoiceboxMalformedResponseError(
                "Voicebox /profiles must return a JSON array."
            )
        return tuple(VoiceboxProfile.from_json(item) for item in payload)

    def list_models(self) -> tuple[VoiceboxModelStatus, ...]:
        payload = self._json(
            "GET", "/models/status", timeout=self.health_timeout_seconds
        )
        if not isinstance(payload, Mapping) or not isinstance(payload.get("models"), list):
            raise VoiceboxMalformedResponseError(
                "Voicebox /models/status must return an object containing a models array."
            )
        return tuple(VoiceboxModelStatus.from_json(item) for item in payload["models"])

    def submit_generation(self, payload: Mapping[str, Any]) -> VoiceboxGeneration:
        return VoiceboxGeneration.from_json(
            self._json(
                "POST",
                "/generate",
                timeout=self.request_timeout_seconds,
                json_body=payload,
            )
        )

    def get_generation(self, generation_id: str) -> VoiceboxGeneration:
        return VoiceboxGeneration.from_json(
            self._json(
                "GET",
                f"/history/{generation_id}",
                timeout=self.health_timeout_seconds,
            )
        )

    def cancel_generation(self, generation_id: str) -> None:
        self._request(
            "POST",
            f"/generate/{generation_id}/cancel",
            timeout=self.health_timeout_seconds,
        )

    def wait_for_generation(
        self,
        generation: VoiceboxGeneration,
    ) -> VoiceboxGeneration:
        current = generation
        started = self._clock()
        while not current.terminal:
            elapsed = self._clock() - started
            if elapsed >= self.request_timeout_seconds:
                try:
                    self.cancel_generation(current.id)
                except Exception:
                    pass
                raise VoiceboxRequestTimeoutError(
                    f"Generation {current.id} did not finish within "
                    f"{self.request_timeout_seconds:g} seconds; cancellation was requested.",
                    retryable=True,
                )
            self._sleep(min(self.poll_interval_seconds, self.request_timeout_seconds - elapsed))
            current = self.get_generation(current.id)
        if current.status == "failed":
            detail = current.error or "Voicebox reported a failed generation without detail."
            raise VoiceboxGenerationError(
                f"Voicebox generation failed: {detail}", retryable=True
            )
        if not current.audio_path:
            raise VoiceboxMissingResultError(
                "Voicebox reported completion without an audio_path. Inspect the local generation history."
            )
        return current

    def download_audio(self, generation_id: str) -> VoiceboxAudioDownload:
        response = self._request(
            "GET",
            f"/audio/{generation_id}",
            timeout=self.request_timeout_seconds,
        )
        content = bytes(getattr(response, "content", b"") or b"")
        if not content:
            raise VoiceboxMissingResultError(
                "Voicebox audio endpoint returned an empty file. Inspect the local generation."
            )
        headers = getattr(response, "headers", {}) or {}
        return VoiceboxAudioDownload(
            content=content,
            content_type=str(headers.get("Content-Type") or "application/octet-stream"),
        )
