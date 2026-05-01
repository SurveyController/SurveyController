from __future__ import annotations

import threading
import unittest

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


if __name__ == "__main__":
    unittest.main()
