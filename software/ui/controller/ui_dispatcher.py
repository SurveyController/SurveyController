"""RunController 的 UI 回调派发辅助。"""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

from PySide6.QtCore import QCoreApplication


class UiCallbackDispatcher:
    """把后台线程回调安全地送回 Qt 主线程。"""

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
        try:
            self._queue.put_nowait(callback)
            self._emit_signal()
            return True
        except Exception:
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
        self.enqueue(callback)
