from __future__ import annotations

from typing import Any
from threading import local

from software.app.settings_store import app_settings


class QSettingsPreferences:
    """Adapter exposing the existing QSettings store through a stable object."""

    def __init__(self, settings: Any | None = None) -> None:
        self._provided = settings
        self._local = local()

    @property
    def _settings(self) -> Any:
        if self._provided is not None:
            return self._provided
        # QSettings supports independent objects per thread, not one shared instance.
        if not hasattr(self._local, "settings"):
            self._local.settings = app_settings()
        return self._local.settings

    def value(self, key: str, default: Any = None) -> Any:
        return self._settings.value(key, default)

    def setValue(self, key: str, value: Any) -> None:
        self._settings.setValue(key, value)

    def remove(self, key: str) -> None:
        self._settings.remove(key)

    def sync(self) -> None:
        self._settings.sync()

    def clear(self) -> None:
        self._settings.clear()


__all__ = ["QSettingsPreferences"]
