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
