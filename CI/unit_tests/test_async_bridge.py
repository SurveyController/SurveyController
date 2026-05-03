from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from software.network.browser.async_bridge import AsyncBridgeLoopThread, AsyncObjectProxy


class _FakeChild:
    def __init__(self) -> None:
        self.value = "child"

    async def echo(self, text: str) -> str:
        return f"{self.value}:{text}"


class _FakeRoute:
    def __init__(self) -> None:
        self.aborted = False

    async def abort(self) -> None:
        self.aborted = True


class _FakeRequest:
    def __init__(self) -> None:
        self.method = "POST"
        self.url = "https://example.com"
        self.headers = {"x-test": "1"}
        self.post_data = "payload"


class _FakePage:
    def __init__(self) -> None:
        self.url = "https://example.com/page"
        self.child = _FakeChild()
        self._route_handler = None
        self.last_route: _FakeRoute | None = None

    async def title(self) -> str:
        return "demo"

    async def route(self, _pattern: str, callback) -> None:
        self._route_handler = callback

    async def unroute(self, _pattern: str, callback) -> None:
        if callback is self._route_handler:
            self._route_handler = None

    async def trigger_route(self) -> None:
        route = _FakeRoute()
        request = _FakeRequest()
        self.last_route = route
        assert self._route_handler is not None
        await self._route_handler(route, request)


class AsyncBridgeTests(unittest.TestCase):
    def test_proxy_reads_property_and_async_method(self) -> None:
        bridge = AsyncBridgeLoopThread(name="BridgeTest")
        page = _FakePage()
        proxy = AsyncObjectProxy(bridge, page, owner=None)
        try:
            self.assertEqual(proxy.url, "https://example.com/page")
            self.assertEqual(proxy.title(), "demo")
            self.assertEqual(proxy.child.echo("ok"), "child:ok")
        finally:
            bridge.stop()

    def test_proxy_route_wraps_sync_callback_and_keeps_same_callback_for_unroute(self) -> None:
        bridge = AsyncBridgeLoopThread(name="BridgeRouteTest")
        page = _FakePage()
        proxy = AsyncObjectProxy(bridge, page, owner=None)
        captured = {}
        handled = threading.Event()

        def _handler(route, request) -> None:
            captured["method"] = request.method
            captured["url"] = request.url
            captured["payload"] = request.post_data
            route.abort()
            handled.set()

        try:
            proxy.route("**/api/**", _handler)
            bridge.run_coroutine(page.trigger_route())
            self.assertTrue(handled.wait(timeout=2))
            self.assertEqual(captured, {"method": "POST", "url": "https://example.com", "payload": "payload"})
            self.assertIsNotNone(page.last_route)
            self.assertTrue(bool(page.last_route and page.last_route.aborted))
            proxy.unroute("**/api/**", _handler)
            self.assertIsNone(page._route_handler)
        finally:
            bridge.stop()

    def test_run_coroutine_closes_unscheduled_coroutine_when_bridge_is_closed(self) -> None:
        bridge = AsyncBridgeLoopThread(name="BridgeClosedTest")
        bridge.stop()

        async def _sample() -> str:
            return "ok"

        coro = _sample()
        with self.assertRaisesRegex(RuntimeError, "已关闭"):
            bridge.run_coroutine(coro)
        self.assertIsNone(coro.cr_frame)

    def test_start_is_thread_safe_under_concurrent_calls(self) -> None:
        bridge = AsyncBridgeLoopThread(name="BridgeConcurrentStart")
        real_thread = threading.Thread
        created_threads: list[str] = []

        class _SlowThread(real_thread):
            def __init__(self, *args, **kwargs) -> None:
                created_threads.append(str(kwargs.get("name") or ""))
                time.sleep(0.02)
                super().__init__(*args, **kwargs)

        barrier = threading.Barrier(8)
        callers = []

        def _call_start() -> None:
            barrier.wait()
            bridge.start()

        try:
            with patch("software.network.browser.async_bridge.threading.Thread", _SlowThread):
                callers = [real_thread(target=_call_start, name=f"Caller-{idx}") for idx in range(8)]
                for caller in callers:
                    caller.start()
                for caller in callers:
                    caller.join(timeout=2)
            self.assertEqual(len(created_threads), 1)
        finally:
            bridge.stop()


if __name__ == "__main__":
    unittest.main()
