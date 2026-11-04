from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

from PySide6.QtCore import QCoreApplication


class UiDispatchError(RuntimeError):
    pass


class _QueuedCallback:
    def __init__(self, callback: Callable[[], Any]) -> None:
        self.callback = callback
        self.cancelled = False

    def __call__(self) -> None:
        if not self.cancelled:
            self.callback()


class UiCallbackDispatcher:
    def __init__(self, emit_signal: Callable[[], Any]) -> None:
        self._emit_signal = emit_signal
        self._queue: "queue.Queue[Callable[[], Any]]" = queue.Queue()

    def drain(self) -> None:
        while True:
            try:
                callback = self._queue.get_nowait()
            except queue.Empty:
                return
            if not callable(callback):
                continue
            try:
                callback()
            except Exception:
                logging.info("执行 UI 回调失败", exc_info=True)

    def enqueue(self, callback: Callable[[], Any]) -> bool:
        queued = _QueuedCallback(callback)
        try:
            self._queue.put_nowait(queued)
            self._emit_signal()
            return True
        except Exception:
            queued.cancelled = True
            logging.warning("UI 回调入队失败", exc_info=True)
            return False

    def dispatch_async(self, callback: Callable[[], Any]) -> None:
        if not callable(callback):
            return
        if QCoreApplication.instance() is None:
            try:
                callback()
            except Exception:
                logging.info("无 QCoreApplication 时执行回调失败", exc_info=True)
            return
        if threading.current_thread() is threading.main_thread():
            try:
                callback()
            except Exception:
                logging.info("主线程直接执行回调失败", exc_info=True)
            return
        if not self.enqueue(callback):
            raise UiDispatchError("UI 回调派发失败")
