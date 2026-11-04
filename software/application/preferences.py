from __future__ import annotations

from typing import Any

from software.application.ports import PreferencesStorePort


class PreferencesService:
    def __init__(self, store: PreferencesStorePort) -> None:
        self._store = store

    def get(self, key: str, default: Any = None) -> Any:
        return self._store.value(key, default)

    def set(self, key: str, value: Any) -> None:
        self._store.setValue(key, value)
        self._store.sync()

    def remove(self, key: str) -> None:
        self._store.remove(key)
        self._store.sync()

    def reset(self) -> None:
        self._store.clear()
        self._store.sync()


__all__ = ["PreferencesService"]
