from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from software.network.browser.owner_pool import AsyncBrowserOwner


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


if __name__ == "__main__":
    unittest.main()
