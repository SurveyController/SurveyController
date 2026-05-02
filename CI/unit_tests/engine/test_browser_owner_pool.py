from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from software.network.browser.owner_pool import AsyncBrowserOwner, AsyncBrowserDriver


class _FakeContext:
    def __init__(self) -> None:
        self.close_calls = 0

    async def new_page(self):
        return "page-ok"

    async def close(self):
        self.close_calls += 1


class _AlwaysClosedBrowser:
    async def new_context(self, **_kwargs):
        raise RuntimeError("Target page, context or browser has been closed")


class _HealthyBrowser:
    async def new_context(self, **_kwargs):
        return _FakeContext()


class _BrokenPageContext(_FakeContext):
    async def new_page(self):
        raise RuntimeError("new_page failed")


class _BrokenPageBrowser:
    def __init__(self, context: _BrokenPageContext) -> None:
        self.context = context

    async def new_context(self, **_kwargs):
        return self.context


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

    async def test_open_session_async_closes_context_when_new_page_fails(self) -> None:
        broken_context = _BrokenPageContext()
        owner = SimpleNamespace(
            owner_id=1,
            _headless=True,
            _browser_pid=9527,
            _ensure_browser_async=AsyncMock(return_value=(_BrokenPageBrowser(broken_context), "edge")),
            mark_broken=Mock(),
            _shutdown_browser_async=AsyncMock(),
        )

        with self.assertRaisesRegex(RuntimeError, "new_page failed"):
            await AsyncBrowserOwner._open_session_async(
                owner,
                proxy_address="http://1.1.1.1:8000",
                user_agent="UA",
            )

        self.assertEqual(broken_context.close_calls, 1)
        owner.mark_broken.assert_not_called()
        owner._shutdown_browser_async.assert_not_awaited()


class AsyncBrowserOwnerThreadingTests(unittest.TestCase):
    def test_open_session_allows_concurrent_context_creation(self) -> None:
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
            _bridge=_FakeBridge(),
            _open_session_async=_fake_open_session_async,
            release_slot=Mock(),
        )

        class _FakeLease:
            def __init__(self) -> None:
                self.mark_activated_calls = 0

            def mark_activated(self) -> None:
                self.mark_activated_calls += 1

        results: list[AsyncBrowserDriver] = []
        leases: list[_FakeLease] = []

        def _worker() -> None:
            lease = _FakeLease()
            driver = AsyncBrowserOwner.open_session(
                owner,
                proxy_address="http://1.1.1.1:8000",
                user_agent="UA",
                lease=lease,
            )
            results.append(driver)
            leases.append(lease)

        first = threading.Thread(target=_worker)
        second = threading.Thread(target=_worker)
        first.start()
        second.start()
        first.join()
        second.join()

        self.assertEqual(len(results), 2)
        self.assertEqual(owner._bridge.max_active, 2)
        self.assertEqual([lease.mark_activated_calls for lease in leases], [1, 1])
        owner.release_slot.assert_not_called()


if __name__ == "__main__":
    unittest.main()
