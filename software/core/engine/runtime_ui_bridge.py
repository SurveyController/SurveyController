"""引擎访问 UI 适配器的最小桥接接口。"""

from __future__ import annotations

from typing import Any, Optional, Protocol, cast

from software.core.engine.stop_signal import StopSignalLike


class RuntimeUiBridge(Protocol):
    def wait_if_paused(self, stop_signal: Optional[StopSignalLike]) -> None: ...

    def handle_random_ip_submission(self, stop_signal: Optional[StopSignalLike] = None) -> None: ...


def wait_if_paused(gui_instance: Any, stop_signal: Optional[StopSignalLike]) -> None:
    if gui_instance is None:
        return
    cast(RuntimeUiBridge, gui_instance).wait_if_paused(stop_signal)


def handle_random_ip_submission(gui_instance: Any, stop_signal: Optional[StopSignalLike]) -> None:
    if gui_instance is None:
        return
    cast(RuntimeUiBridge, gui_instance).handle_random_ip_submission(stop_signal)


__all__ = [
    "RuntimeUiBridge",
    "handle_random_ip_submission",
    "wait_if_paused",
]
