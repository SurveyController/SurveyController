"""运行时并发协调器：少量浏览器底座 + 多会话槽位。"""

from __future__ import annotations

import logging
import threading
from typing import Any, List, Optional

from software.app.config import BROWSER_PREFERENCE
from software.core.engine.execution_loop import ExecutionLoop
from software.core.task import ExecutionConfig, ExecutionState
from software.logging.log_utils import log_suppressed_exception
from software.network.browser.owner_pool import (
    BrowserOwnerPool,
    BrowserPoolConfig,
    DEFAULT_MAX_CONTEXTS_PER_BROWSER,
)


def _build_owner_window_positions(owner_count: int) -> List[tuple[int, int]]:
    positions: List[tuple[int, int]] = []
    for owner_index in range(max(1, int(owner_count or 1))):
        positions.append((50 + owner_index * 60, 50 + owner_index * 60))
    return positions


class AsyncRuntimeCoordinator:
    """用单个协调线程管理 slot 线程与 browser owner 池。"""

    def __init__(
        self,
        *,
        config: ExecutionConfig,
        state: ExecutionState,
        stop_signal: threading.Event,
        gui_instance: Any = None,
    ) -> None:
        self.config = config
        self.state = state
        self.stop_signal = stop_signal
        self.gui_instance = gui_instance
        self.slot_threads: List[threading.Thread] = []
        self.owner_pool: Optional[BrowserOwnerPool] = None

    def _register_cleanup_target(self, target: Any) -> None:
        drivers = getattr(self.gui_instance, "active_drivers", None)
        if isinstance(drivers, list):
            drivers.append(target)

    def _unregister_cleanup_target(self, target: Any) -> None:
        drivers = getattr(self.gui_instance, "active_drivers", None)
        if not isinstance(drivers, list):
            return
        try:
            drivers.remove(target)
        except ValueError:
            pass

    def _run_slot(self, slot_index: int) -> None:
        owner_pool = self.owner_pool
        if owner_pool is None:
            raise RuntimeError("owner pool 未初始化")
        owner = owner_pool.owner_for_slot(slot_index)
        loop = ExecutionLoop(
            self.config,
            self.state,
            self.gui_instance,
            browser_owner=owner,
        )
        loop.run_thread(0, 0, self.stop_signal)

    def run(self) -> None:
        pool_config = BrowserPoolConfig.from_concurrency(
            self.config.num_threads,
            max_contexts_per_browser=DEFAULT_MAX_CONTEXTS_PER_BROWSER,
        )
        prefer_browsers = list(self.config.browser_preference or BROWSER_PREFERENCE)
        self.owner_pool = BrowserOwnerPool(
            config=pool_config,
            headless=bool(self.config.headless_mode),
            prefer_browsers=prefer_browsers,
            window_positions=_build_owner_window_positions(pool_config.owner_count),
        )
        self._register_cleanup_target(self.owner_pool)
        logging.info(
            "异步上下文池已启动：总并发=%s owner数=%s 每owner槽位=%s",
            self.config.num_threads,
            pool_config.owner_count,
            pool_config.max_contexts_per_browser,
        )

        threads: List[threading.Thread] = []
        try:
            for slot_index in range(max(1, int(self.config.num_threads or 1))):
                slot_no = slot_index + 1
                thread = threading.Thread(
                    target=self._run_slot,
                    args=(slot_index,),
                    daemon=True,
                    name=f"Slot-{slot_no}",
                )
                threads.append(thread)
            self.slot_threads = threads
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        finally:
            self.slot_threads = []
            pool = self.owner_pool
            self.owner_pool = None
            self._unregister_cleanup_target(pool)
            if pool is not None:
                try:
                    pool.shutdown()
                except Exception as exc:
                    log_suppressed_exception("AsyncRuntimeCoordinator.run pool.shutdown", exc, level=logging.WARNING)


__all__ = ["AsyncRuntimeCoordinator"]
