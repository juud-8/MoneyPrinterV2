"""In-process registry for optional media providers."""

from __future__ import annotations

from threading import RLock

from .contracts import ProviderInstance, ProviderKind, ProviderRegistryEntry
from .errors import (
    ProviderConfigurationError,
    ProviderUnavailableError,
    UnknownProviderError,
)


class ProviderRegistry:
    """Register factories by provider kind without importing provider internals."""

    def __init__(self) -> None:
        self._entries: dict[tuple[ProviderKind, str], ProviderRegistryEntry] = {}
        self._lock = RLock()

    @staticmethod
    def _key(kind: ProviderKind | str, provider_id: str) -> tuple[ProviderKind, str]:
        return ProviderKind(kind), str(provider_id or "").strip().lower()

    def register(self, entry: ProviderRegistryEntry, *, replace: bool = False) -> None:
        key = self._key(entry.kind, entry.provider_id)
        with self._lock:
            if key in self._entries and not replace:
                raise ProviderConfigurationError(
                    entry.provider_id,
                    f"duplicate {entry.kind.value} provider registration",
                )
            self._entries[key] = entry

    def unregister(self, kind: ProviderKind | str, provider_id: str) -> None:
        key = self._key(kind, provider_id)
        with self._lock:
            if key not in self._entries:
                raise UnknownProviderError(provider_id, key[0].value)
            del self._entries[key]

    def get_entry(
        self, kind: ProviderKind | str, provider_id: str
    ) -> ProviderRegistryEntry:
        key = self._key(kind, provider_id)
        with self._lock:
            entry = self._entries.get(key)
        if entry is None:
            raise UnknownProviderError(provider_id, key[0].value)
        return entry

    def create(self, kind: ProviderKind | str, provider_id: str) -> ProviderInstance:
        entry = self.get_entry(kind, provider_id)
        if not entry.enabled:
            raise ProviderUnavailableError(
                entry.provider_id,
                f"{entry.kind.value} provider is disabled",
            )
        try:
            instance = entry.factory()
        except ProviderConfigurationError:
            raise
        except Exception as exc:
            raise ProviderConfigurationError(
                entry.provider_id,
                f"provider factory failed: {exc}",
            ) from exc
        actual_id = str(getattr(instance, "provider_id", "") or "").strip().lower()
        if actual_id != entry.provider_id:
            raise ProviderConfigurationError(
                entry.provider_id,
                f"factory returned provider_id {actual_id!r}",
            )
        return instance

    def entries(
        self, kind: ProviderKind | str | None = None
    ) -> tuple[ProviderRegistryEntry, ...]:
        selected_kind = ProviderKind(kind) if kind is not None else None
        with self._lock:
            values = [
                entry
                for (entry_kind, _), entry in self._entries.items()
                if selected_kind is None or entry_kind == selected_kind
            ]
        return tuple(sorted(values, key=lambda item: (item.kind.value, item.provider_id)))
