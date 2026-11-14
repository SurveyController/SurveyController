from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

from software.core.engine.runtime_control_port import RuntimeControlPort
from software.application.run_state_store import RunLifecycleState
from surveycore.core.engine.stop_signal import StopSignalLike


class BoolState:
    def __init__(self, value: bool = False) -> None:
        self._value = bool(value)

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        self._value = bool(value)


class RunRuntimePort(RuntimeControlPort):
    def __init__(
        self,
        *,
        stop_signal: threading.Event,
        notify_random_ip_loading: Callable[[bool, str], Any],
        handle_random_ip_submission: Callable[..., None],
        lifecycle: RunLifecycleState | None = None,
    ) -> None:
        self.random_ip_enabled_state = BoolState(False)
        self._stop_signal = stop_signal
        self._lifecycle = lifecycle or RunLifecycleState()
        self._notify_random_ip_loading = notify_random_ip_loading
        self._handle_random_ip_submission = handle_random_ip_submission
        self._pause_event = threading.Event()

    def pause_run(self, reason: str = "") -> None:
        self._lifecycle.pause_reason = str(reason or "")
        self._lifecycle.paused = True
        self._pause_event.set()

    def resume_run(self) -> None:
        self._lifecycle.pause_reason = ""
        self._lifecycle.paused = False
        self._pause_event.clear()

    def is_paused(self) -> bool:
        return bool(self._lifecycle.paused)

    def get_pause_reason(self) -> str:
        return self._lifecycle.pause_reason or ""

    def wait_if_paused(self, stop_signal: Optional[StopSignalLike] = None) -> None:
        signal = stop_signal or self._stop_signal
        while self.is_paused() and signal and not signal.is_set():
            signal.wait(0.25)

    def on_random_ip_submission(self, stop_signal: Optional[StopSignalLike] = None) -> None:
        signal = stop_signal if isinstance(stop_signal, threading.Event) else None
        try:
            self._handle_random_ip_submission(stop_signal=signal)
        except Exception:
            logging.info("处理随机IP提交流程失败", exc_info=True)

    def on_random_ip_loading_changed(self, loading: bool, message: str = "") -> None:
        try:
            self._notify_random_ip_loading(bool(loading), str(message or ""))
        except Exception:
            logging.info("更新随机IP加载状态失败", exc_info=True)

    def set_random_ip_enabled(self, enabled: bool) -> None:
        self.random_ip_enabled_state.set(bool(enabled))

    def is_random_ip_enabled(self) -> bool:
        return bool(self.random_ip_enabled_state.get())

__all__ = ["BoolState", "RunRuntimePort"]
