"""每个 Slot 一个后台预热 session 的会话池。"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

from software.core.engine.browser_session_service import BrowserSessionService
from software.core.task import ExecutionConfig, ExecutionState
from software.logging.log_utils import log_suppressed_exception
from software.network.browser.owner_pool import BrowserOwnerPool


@dataclass(frozen=True)
class PreloadedSessionLease:
    """一次领取结果：命中预热 session，或回退到现建 session。"""

    session: Optional[BrowserSessionService]
    browser_name: str = ""
    preloaded: bool = False


class PreloadedBrowserSessionPool:
    """后台维持一个已打开且已加载问卷首页的 session。"""

    def __init__(
        self,
        *,
        config: ExecutionConfig,
        state: ExecutionState,
        gui_instance: Any,
        thread_name: str,
        browser_owner_pool: BrowserOwnerPool,
        page_loader: Callable[[Any, ExecutionConfig], None],
    ) -> None:
        self.config = config
        self.state = state
        self.gui_instance = gui_instance
        self.thread_name = str(thread_name or "").strip() or "Slot-?"
        self.browser_owner_pool = browser_owner_pool
        self._page_loader = page_loader
        self._condition = threading.Condition()
        self._stopped = False
        self._ready_session: Optional[BrowserSessionService] = None
        self._ready_browser_name: str = ""
        self._loading_thread: Optional[threading.Thread] = None

    def warm_async(
        self,
        preferred_browsers: list[str],
        window_x_pos: int,
        window_y_pos: int,
    ) -> None:
        with self._condition:
            if self._stopped or self._ready_session is not None or self._loading_thread is not None:
                return
            thread = threading.Thread(
                target=self._build_ready_session,
                args=(list(preferred_browsers or []), int(window_x_pos or 0), int(window_y_pos or 0)),
                daemon=True,
                name=f"{self.thread_name}-WarmSession",
            )
            self._loading_thread = thread
            thread.start()

    def acquire(
        self,
        stop_signal: threading.Event,
        *,
        wait: bool = True,
    ) -> PreloadedSessionLease:
        while True:
            with self._condition:
                if self._ready_session is not None:
                    session = self._ready_session
                    browser_name = self._ready_browser_name
                    self._ready_session = None
                    self._ready_browser_name = ""
                    return PreloadedSessionLease(session=session, browser_name=browser_name, preloaded=True)
                loading = self._loading_thread is not None
                stopped = self._stopped

            if stopped or stop_signal.is_set():
                return PreloadedSessionLease(session=None, browser_name="", preloaded=False)
            if not wait or not loading:
                return PreloadedSessionLease(session=None, browser_name="", preloaded=False)
            if stop_signal.wait(0.05):
                return PreloadedSessionLease(session=None, browser_name="", preloaded=False)

    def shutdown(self) -> None:
        ready_session: Optional[BrowserSessionService] = None
        with self._condition:
            if self._stopped:
                return
            self._stopped = True
            ready_session = self._ready_session
            self._ready_session = None
            self._ready_browser_name = ""
            self._condition.notify_all()

        if ready_session is not None:
            try:
                ready_session.shutdown()
            except Exception as exc:
                log_suppressed_exception("PreloadedBrowserSessionPool.shutdown ready_session.shutdown", exc, level=logging.WARNING)

    def _build_ready_session(
        self,
        preferred_browsers: list[str],
        window_x_pos: int,
        window_y_pos: int,
    ) -> None:
        session = BrowserSessionService(
            self.config,
            self.state,
            self.gui_instance,
            self.thread_name,
            browser_owner_pool=self.browser_owner_pool,
        )
        active_browser = ""
        try:
            active_browser = str(
                session.create_browser(
                    list(preferred_browsers or []),
                    int(window_x_pos or 0),
                    int(window_y_pos or 0),
                    acquire_browser_semaphore=False,
                )
                or ""
            ).strip()
            if not active_browser or session.driver is None:
                raise RuntimeError("预热 session 创建失败：浏览器未就绪")
            self._page_loader(session.driver, self.config)
            with self._condition:
                if self._stopped:
                    try:
                        session.shutdown()
                    except Exception as exc:
                        log_suppressed_exception(
                            "PreloadedBrowserSessionPool._build_ready_session shutdown after stop",
                            exc,
                            level=logging.WARNING,
                        )
                    return
                self._ready_session = session
                self._ready_browser_name = active_browser
                logging.info("线程[%s]后台预热 session 已就绪", self.thread_name)
        except Exception as exc:
            logging.warning("线程[%s]后台预热 session 失败：%s", self.thread_name, exc)
            try:
                session.shutdown()
            except Exception as shutdown_exc:
                log_suppressed_exception(
                    "PreloadedBrowserSessionPool._build_ready_session session.shutdown",
                    shutdown_exc,
                    level=logging.WARNING,
                )
        finally:
            with self._condition:
                self._loading_thread = None
                self._condition.notify_all()


__all__ = [
    "PreloadedBrowserSessionPool",
    "PreloadedSessionLease",
]
