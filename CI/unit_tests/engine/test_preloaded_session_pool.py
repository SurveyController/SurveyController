from __future__ import annotations

import threading
import time
import unittest
from contextlib import contextmanager

import software.core.engine.preloaded_session_pool as pool_module
from software.core.engine.preloaded_session_pool import PreloadedBrowserSessionPool
from software.core.task import ExecutionConfig, ExecutionState


@contextmanager
def _patched_attr(target, name: str, value):
    original = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, original)


class _FakeBrowserSessionService:
    instances: list["_FakeBrowserSessionService"] = []

    def __init__(self, *_args, **_kwargs):
        self.driver = object()
        self.shutdown_called = 0
        self.create_browser_calls: list[tuple[list[str], int, int]] = []
        _FakeBrowserSessionService.instances.append(self)

    def create_browser(self, preferred_browsers, window_x_pos: int, window_y_pos: int):
        self.create_browser_calls.append((list(preferred_browsers or []), int(window_x_pos), int(window_y_pos)))
        return "edge"

    def shutdown(self) -> None:
        self.shutdown_called += 1


class PreloadedSessionPoolTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeBrowserSessionService.instances = []

    def test_warm_async_builds_ready_session_and_acquire_returns_preloaded_lease(self) -> None:
        config = ExecutionConfig(url="https://example.com/form")
        state = ExecutionState(config=config)
        loaded_drivers: list[object] = []

        def _page_loader(driver, _config) -> None:
            loaded_drivers.append(driver)

        with _patched_attr(pool_module, "BrowserSessionService", _FakeBrowserSessionService):
            pool = PreloadedBrowserSessionPool(
                config=config,
                state=state,
                gui_instance=None,
                thread_name="Slot-1",
                browser_owner=object(),
                page_loader=_page_loader,
            )
            stop_signal = threading.Event()
            pool.warm_async(["edge"], 0, 0)
            lease = pool.acquire(stop_signal, wait=True)

        self.assertTrue(lease.preloaded)
        self.assertEqual(lease.browser_name, "edge")
        self.assertIsNotNone(lease.session)
        self.assertEqual(len(loaded_drivers), 1)
        self.assertIs(loaded_drivers[0], lease.session.driver)

    def test_shutdown_closes_unused_ready_session(self) -> None:
        config = ExecutionConfig(url="https://example.com/form")
        state = ExecutionState(config=config)

        with _patched_attr(pool_module, "BrowserSessionService", _FakeBrowserSessionService):
            pool = PreloadedBrowserSessionPool(
                config=config,
                state=state,
                gui_instance=None,
                thread_name="Slot-1",
                browser_owner=object(),
                page_loader=lambda *_args, **_kwargs: None,
            )
            stop_signal = threading.Event()
            pool.warm_async(["edge"], 0, 0)

            deadline = time.time() + 2.0
            while time.time() < deadline:
                lease = pool.acquire(stop_signal, wait=False)
                if lease.preloaded:
                    pool.shutdown()
                    self.assertEqual(lease.session.shutdown_called, 0)
                    return
                time.sleep(0.02)

            self.fail("预热 session 未在预期时间内完成")

    def test_shutdown_disposes_ready_session_when_not_consumed(self) -> None:
        config = ExecutionConfig(url="https://example.com/form")
        state = ExecutionState(config=config)

        with _patched_attr(pool_module, "BrowserSessionService", _FakeBrowserSessionService):
            pool = PreloadedBrowserSessionPool(
                config=config,
                state=state,
                gui_instance=None,
                thread_name="Slot-1",
                browser_owner=object(),
                page_loader=lambda *_args, **_kwargs: None,
            )
            pool.warm_async(["edge"], 0, 0)

            deadline = time.time() + 2.0
            while time.time() < deadline:
                if pool._ready_session is not None:
                    ready_session = pool._ready_session
                    pool.shutdown()
                    self.assertEqual(ready_session.shutdown_called, 1)
                    return
                time.sleep(0.02)

            self.fail("预热 session 未在预期时间内进入 ready 状态")


if __name__ == "__main__":
    unittest.main()
