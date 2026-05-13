"""运行时动作请求。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional, Tuple


class RuntimeActionKind(str, Enum):
    PAUSE_RUN = "pause_run"
    SHOW_MESSAGE = "show_message"
    CONFIRM_ENABLE_RANDOM_IP = "confirm_enable_random_ip"
    SET_RANDOM_IP_ENABLED = "set_random_ip_enabled"
    REFRESH_RANDOM_IP_COUNTER = "refresh_random_ip_counter"


@dataclass(frozen=True)
class RuntimeActionRequest:
    kind: RuntimeActionKind
    title: str = ""
    message: str = ""
    level: str = "info"
    reason: str = ""
    enabled: Optional[bool] = None


@dataclass(frozen=True)
class RuntimeActionResult:
    actions: Tuple[RuntimeActionRequest, ...] = ()
    should_stop: bool = False

    @classmethod
    def empty(cls) -> "RuntimeActionResult":
        return cls()

    @classmethod
    def from_actions(
        cls,
        actions: Iterable[RuntimeActionRequest],
        *,
        should_stop: bool = False,
    ) -> "RuntimeActionResult":
        return cls(tuple(actions or ()), bool(should_stop))


def ensure_runtime_action_result(value: object) -> RuntimeActionResult:
    if isinstance(value, RuntimeActionResult):
        return value
    if value is None:
        return RuntimeActionResult.empty()
    if isinstance(value, RuntimeActionRequest):
        return RuntimeActionResult((value,))
    if isinstance(value, (list, tuple)):
        actions = tuple(item for item in value if isinstance(item, RuntimeActionRequest))
        return RuntimeActionResult(actions)
    return RuntimeActionResult.empty()


__all__ = [
    "RuntimeActionKind",
    "RuntimeActionRequest",
    "RuntimeActionResult",
    "ensure_runtime_action_result",
]
