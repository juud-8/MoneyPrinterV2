"""Provider-specific errors with stable, operator-readable categories."""

from __future__ import annotations


class ProviderError(RuntimeError):
    def __init__(self, provider_id: str, message: str, *, retryable: bool = False):
        self.provider_id = str(provider_id or "unknown")
        self.retryable = bool(retryable)
        super().__init__(f"{self.provider_id}: {message}")


class ProviderConfigurationError(ProviderError):
    """The provider cannot run until local configuration is corrected."""


class ProviderUnavailableError(ProviderError):
    """The provider is registered but currently unavailable or disabled."""


class ProviderGenerationError(ProviderError):
    """A configured provider failed while generating an asset."""


class UnknownProviderError(ProviderError):
    """No provider is registered for the requested kind and identifier."""

    def __init__(self, provider_id: str, kind: str):
        self.kind = str(kind)
        super().__init__(provider_id, f"unknown {self.kind} provider")


class VoiceboxError(ProviderError):
    """Base class for stable Voicebox operator-facing failures."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        attempt_count: int = 0,
    ):
        self.attempt_count = int(attempt_count)
        super().__init__("voicebox", message, retryable=retryable)


class VoiceboxServiceUnavailableError(VoiceboxError, ProviderUnavailableError):
    """The separately managed local Voicebox service cannot be reached."""


class VoiceboxHealthCheckError(VoiceboxError, ProviderUnavailableError):
    """Voicebox responded, but its readiness response was unhealthy or invalid."""


class VoiceboxRequestTimeoutError(VoiceboxError, ProviderGenerationError):
    """A bounded Voicebox request or generation poll timed out."""


class VoiceboxInvalidProfileError(VoiceboxError, ProviderConfigurationError):
    """The configured Voicebox profile does not exist or cannot use the engine."""


class VoiceboxInvalidEngineError(VoiceboxError, ProviderConfigurationError):
    """The configured Voicebox engine is unknown or unavailable."""


class VoiceboxUnsupportedCapabilityError(VoiceboxError, ProviderConfigurationError):
    """The selected engine cannot honor an explicitly requested capability."""


class VoiceboxUnsupportedTagError(VoiceboxUnsupportedCapabilityError):
    """Performance tags would be spoken literally by the selected engine."""


class VoiceboxGenerationError(VoiceboxError, ProviderGenerationError):
    """Voicebox accepted a request but failed to produce usable speech."""


class VoiceboxMalformedResponseError(VoiceboxGenerationError):
    """A Voicebox JSON response did not match the verified API schema."""


class VoiceboxMissingResultError(VoiceboxGenerationError):
    """Voicebox reported completion but did not return an audio artifact."""


class VoiceboxInvalidAudioError(VoiceboxGenerationError):
    """Downloaded Voicebox audio was empty or could not be decoded."""


class VoiceboxNormalizationError(VoiceboxGenerationError):
    """The immutable Voicebox original could not be normalized for production."""


class VoiceboxAuthenticationError(VoiceboxError, ProviderConfigurationError):
    """A Voicebox deployment rejected the request as unauthenticated."""


class VoiceboxVersionIncompatibilityError(VoiceboxError, ProviderConfigurationError):
    """The running Voicebox API version is outside the verified contract."""
