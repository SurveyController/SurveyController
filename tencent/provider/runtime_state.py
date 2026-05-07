"""腾讯问卷运行时状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from software.providers.common import SURVEY_PROVIDER_QQ
from software.providers.runtime_state import ProviderRuntimeState, get_provider_runtime_state_store


@dataclass
class QqRuntimeState(ProviderRuntimeState):
    page_index: int = 0
    page_question_ids: List[str] = field(default_factory=list)
    visibility_snapshot: Dict[str, Dict[str, bool]] = field(default_factory=dict)
    psycho_plan: Any = None
    submission_recovery_attempts: int = 0


_STORE = get_provider_runtime_state_store(SURVEY_PROVIDER_QQ, QqRuntimeState)


def get_qq_runtime_state(driver: Any) -> QqRuntimeState:
    return _STORE.get_or_create(driver)


def peek_qq_runtime_state(driver: Any) -> QqRuntimeState | None:
    return _STORE.peek(driver)


def clear_qq_runtime_state(driver: Any) -> None:
    _STORE.clear(driver)


__all__ = [
    "QqRuntimeState",
    "clear_qq_runtime_state",
    "get_qq_runtime_state",
    "peek_qq_runtime_state",
]
