from __future__ import annotations

from typing import Callable

from software.application.ports import PreferencesStorePort

_preferences_factory: Callable[[], PreferencesStorePort] | None = None
_config_path_factory: Callable[[], str] | None = None


def configure_runtime_environment(
    preferences: Callable[[], PreferencesStorePort], config_path: Callable[[], str],
) -> None:
    global _preferences_factory, _config_path_factory
    _preferences_factory = preferences
    _config_path_factory = config_path


def preference_store() -> PreferencesStorePort:
    if _preferences_factory is None:
        raise RuntimeError("用户偏好存储尚未注入")
    return _preferences_factory()


def default_config_path() -> str:
    if _config_path_factory is None:
        raise RuntimeError("配置路径尚未注入")
    return _config_path_factory()
