from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from software.network.browser.owner_pool import AsyncBrowserOwner, AsyncBrowserDriver


class _FakeContext:
    async def new_page(self):
        return "page-ok"


class _AlwaysClosedBrowser:
    async def new_context(self, **_kwargs):
        raise RuntimeError("Target page, context or browser has been closed")


class _HealthyBrowser:
    async def new_context(self, **_kwargs):
        return _FakeContext()


class AsyncBrowserOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_session_async_rebuilds_browser_once_after_disconnect(self) -> None:
        owner = SimpleNamespace(
            owner_id=1,
            _headless=True,
            _browser_pid=9527,
            _ensure_browser_async=AsyncMock(
                side_effect=[
                    (_AlwaysClosedBrowser(), "edge"),
                    (_HealthyBrowser(), "edge"),
                ]
            ),
            mark_broken=Mock(),
            _shutdown_browser_async=AsyncMock(),
        )

        context, page, browser_name, browser_pid = await AsyncBrowserOwner._open_session_async(
            owner,
            proxy_address="http://1.1.1.1:8000",
            user_agent="UA",
        )

        self.assertIsInstance(context, _FakeContext)
        self.assertEqual(page, "page-ok")
        self.assertEqual(browser_name, "edge")
        self.assertEqual(browser_pid, 9527)
        self.assertEqual(owner._ensure_browser_async.await_count, 2)
        owner.mark_broken.assert_called_once()
        owner._shutdown_browser_async.assert_awaited_once()


class AsyncBrowserOwnerThreadingTests(unittest.TestCase):
    def test_open_session_serializes_first_wave_session_creation(self) -> None:
        class _FakeBridge:
            def __init__(self) -> None:
                self.active = 0
                self.max_active = 0
                self.lock = threading.Lock()

            def run_coroutine(self, coro):
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                try:
                    time.sleep(0.05)
                    return object(), object(), "edge", 9527
                finally:
                    coro.close()
                    with self.lock:
                        self.active -= 1

        async def _fake_open_session_async(*, proxy_address=None, user_agent=None):
            del proxy_address, user_agent
            return object(), object(), "edge", 9527

        owner = SimpleNamespace(
            _closed=False,
            _session_open_lock=threading.Lock(),
            _bridge=_FakeBridge(),
            _open_session_async=_fake_open_session_async,
            acquire_slot=Mock(),
            release_slot=Mock(),
        )

        results: list[AsyncBrowserDriver] = []

        def _worker() -> None:
            driver = AsyncBrowserOwner.open_session(
                owner,
                proxy_address="http://1.1.1.1:8000",
                user_agent="UA",
            )
            results.append(driver)

        first = threading.Thread(target=_worker)
        second = threading.Thread(target=_worker)
        first.start()
        second.start()
        first.join()
        second.join()

        self.assertEqual(len(results), 2)
        self.assertEqual(owner._bridge.max_active, 1)
        self.assertEqual(owner.acquire_slot.call_count, 2)
        owner.release_slot.assert_not_called()


if __name__ == "__main__":
    unittest.main()
