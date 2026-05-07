"""Provider 运行时状态仓库。"""

from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass
from typing import Any, Callable, Dict, Generic, Optional, TypeVar, cast

from software.providers.common import SURVEY_PROVIDER_WJX, normalize_survey_provider

StateT = TypeVar("StateT")


@dataclass
class ProviderRuntimeState:
    """Provider 运行时状态基类。"""


class ProviderRuntimeStateStore(Generic[StateT]):
    """按 driver 实例隔离 provider 运行时状态。"""

    def __init__(self, provider: str, factory: Callable[[], StateT]) -> None:
        self.provider = normalize_survey_provider(provider, default=SURVEY_PROVIDER_WJX)
        self._factory = factory
        self._lock = threading.RLock()
        self._states: "weakref.WeakKeyDictionary[object, StateT]" = weakref.WeakKeyDictionary()
        self._fallback_states: Dict[int, StateT] = {}

    @staticmethod
    def _driver_identity(driver: object) -> int:
        return id(driver)

    @staticmethod
    def _supports_weakref(driver: object) -> bool:
        try:
            weakref.ref(driver)
        except TypeError:
            return False
        return True

    def get_or_create(self, driver: Any) -> StateT:
        if driver is None:
            raise ValueError("driver 不能为空")
        key = cast(object, driver)
        with self._lock:
            if self._supports_weakref(key):
                existing = self._states.get(key)
                if existing is not None:
                    return existing
                state = self._factory()
                self._states[key] = state
                return state

            identity = self._driver_identity(key)
            existing = self._fallback_states.get(identity)
            if existing is not None:
                return existing
            state = self._factory()
            self._fallback_states[identity] = state
            return state

    def peek(self, driver: Any) -> Optional[StateT]:
        if driver is None:
            return None
        key = cast(object, driver)
        with self._lock:
            if self._supports_weakref(key):
                return self._states.get(key)
            return self._fallback_states.get(self._driver_identity(key))

    def clear(self, driver: Any) -> None:
        if driver is None:
            return
        key = cast(object, driver)
        with self._lock:
            if self._supports_weakref(key):
                self._states.pop(key, None)
                return
            self._fallback_states.pop(self._driver_identity(key), None)

    def snapshot_size(self) -> int:
        with self._lock:
            return len(self._states) + len(self._fallback_states)


_STATE_STORES: Dict[str, ProviderRuntimeStateStore[Any]] = {}
_STATE_STORES_LOCK = threading.RLock()


def get_provider_runtime_state_store(
    provider: str,
    factory: Callable[[], StateT],
) -> ProviderRuntimeStateStore[StateT]:
    normalized = normalize_survey_provider(provider, default=SURVEY_PROVIDER_WJX)
    with _STATE_STORES_LOCK:
        existing = _STATE_STORES.get(normalized)
        if existing is None:
            store: ProviderRuntimeStateStore[StateT] = ProviderRuntimeStateStore(normalized, factory)
            _STATE_STORES[normalized] = store
            return store
        return cast(ProviderRuntimeStateStore[StateT], existing)


__all__ = [
    "ProviderRuntimeState",
    "ProviderRuntimeStateStore",
    "get_provider_runtime_state_store",
]
