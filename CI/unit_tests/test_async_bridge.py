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

    def test_loop_property_waits_until_background_loop_is_ready(self) -> None:
        bridge = AsyncBridgeLoopThread(name="BridgeLoopReady")
        release_loop = threading.Event()
        ready_to_race = threading.Event()
        original_new_event_loop = __import__("asyncio").new_event_loop
        errors: list[BaseException] = []
        loops = []

        def _slow_new_event_loop():
            ready_to_race.set()
            release_loop.wait(timeout=2)
            return original_new_event_loop()

        def _read_loop() -> None:
            try:
                loops.append(bridge.loop)
            except BaseException as exc:  # pragma: no cover - 用于捕获旧竞态
                errors.append(exc)

        callers = [threading.Thread(target=_read_loop, name=f"LoopCaller-{idx}") for idx in range(2)]
        try:
            with patch("software.network.browser.async_bridge.asyncio.new_event_loop", side_effect=_slow_new_event_loop):
                callers[0].start()
                self.assertTrue(ready_to_race.wait(timeout=2))
                callers[1].start()
                time.sleep(0.05)
                release_loop.set()
                for caller in callers:
                    caller.join(timeout=2)
            self.assertEqual(errors, [])
            self.assertEqual(len(loops), 2)
            self.assertIs(loops[0], loops[1])
        finally:
            release_loop.set()
            bridge.stop()

    def test_start_raises_when_background_loop_initialization_fails(self) -> None:
        bridge = AsyncBridgeLoopThread(name="BridgeStartupFailure")

        def _boom():
            raise RuntimeError("boom")

        with patch("software.network.browser.async_bridge.asyncio.new_event_loop", side_effect=_boom):
            with self.assertRaisesRegex(RuntimeError, "启动失败"):
                bridge.start()

        bridge.stop()


if __name__ == "__main__":
    unittest.main()
