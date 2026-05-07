"""Credamo 运行时状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List

from software.providers.common import SURVEY_PROVIDER_CREDAMO
from software.providers.runtime_state import ProviderRuntimeState, get_provider_runtime_state_store


@dataclass
class CredamoRuntimeState(ProviderRuntimeState):
    page_index: int = 0
    answered_question_keys: List[str] = field(default_factory=list)
    last_page_signature: Any = None
    psycho_plan: Any = None
    submission_recovery_attempts: int = 0


_STORE = get_provider_runtime_state_store(SURVEY_PROVIDER_CREDAMO, CredamoRuntimeState)


def get_credamo_runtime_state(driver: Any) -> CredamoRuntimeState:
    return _STORE.get_or_create(driver)


def peek_credamo_runtime_state(driver: Any) -> CredamoRuntimeState | None:
    return _STORE.peek(driver)


def clear_credamo_runtime_state(driver: Any) -> None:
    _STORE.clear(driver)


__all__ = [
    "CredamoRuntimeState",
    "clear_credamo_runtime_state",
    "get_credamo_runtime_state",
    "peek_credamo_runtime_state",
]
