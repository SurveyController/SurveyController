"""WJX 运行时状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from software.providers.common import SURVEY_PROVIDER_WJX
from software.providers.runtime_state import ProviderRuntimeState, get_provider_runtime_state_store


@dataclass
class WjxRuntimeState(ProviderRuntimeState):
    page_number: int = 0
    page_questions: List[dict[str, Any]] = field(default_factory=list)
    indices_snapshot: Dict[str, int] = field(default_factory=dict)
    psycho_plan: Any = None
    submission_recovery_attempts: int = 0


_STORE = get_provider_runtime_state_store(SURVEY_PROVIDER_WJX, WjxRuntimeState)


def get_wjx_runtime_state(driver: Any) -> WjxRuntimeState:
    return _STORE.get_or_create(driver)


def peek_wjx_runtime_state(driver: Any) -> WjxRuntimeState | None:
    return _STORE.peek(driver)


def clear_wjx_runtime_state(driver: Any) -> None:
    _STORE.clear(driver)


__all__ = [
    "WjxRuntimeState",
    "clear_wjx_runtime_state",
    "get_wjx_runtime_state",
    "peek_wjx_runtime_state",
]
