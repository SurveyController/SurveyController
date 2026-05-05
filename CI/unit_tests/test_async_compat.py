from __future__ import annotations

import asyncio
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

import software.network.browser.async_compat as async_compat
from software.network.browser.exceptions import NoSuchElementException, ProxyConnectionError


class _FakeAwaitable:
    def __await__(self):
        async def _inner():
            return "awaited"

        return _inner().__await__()


class _AsyncHandle:
    def __init__(self) -> None:
        self.url = "https://example.com"
        self.actions: list[tuple[str, object]] = []
        self.query_selector_result = None
        self.query_selector_all_result = []
        self.click_errors: list[Exception] = []
        self.evaluate_value = "value"
        self.bounding_box_value = {"width": 10, "height": 20}

    async def inner_text(self):
        return "hello"

    async def get_attribute(self, name: str):
        self.actions.append(("get_attribute", name))
        return "attr"

    async def bounding_box(self):
        return self.bounding_box_value

    async def evaluate(self, script: str, args=None):
        self.actions.append(("evaluate", script))
        if "window.location.href" in script:
            return self.url
        return self.evaluate_value

    async def click(self):
        self.actions.append(("click", None))
        if self.click_errors:
            raise self.click_errors.pop(0)

    async def scroll_into_view_if_needed(self):
        self.actions.append(("scroll", None))

    async def fill(self, value: str):
        self.actions.append(("fill", value))
        raise RuntimeError("fill failed")

    async def type(self, value: str):
        self.actions.append(("type", value))

    async def query_selector(self, selector: str):
        self.actions.append(("query_selector", selector))
        return self.query_selector_result

    async def query_selector_all(self, selector: str):
        self.actions.append(("query_selector_all", selector))
        return self.query_selector_all_result

    async def set_default_navigation_timeout(self, timeout: int):
        self.actions.append(("nav_timeout", timeout))

    async def set_default_timeout(self, timeout: int):
        self.actions.append(("timeout", timeout))

    async def goto(self, url: str, wait_until: str, timeout: int):
        self.actions.append(("goto", (url, wait_until, timeout)))
        return "ok"

    async def content(self):
        return "<html></html>"

    async def title(self):
        return "demo"

    async def set_viewport_size(self, viewport):
        self.actions.append(("viewport", viewport))

    async def reload(self, wait_until: str):
        self.actions.append(("reload", wait_until))

    async def close(self):
        self.actions.append(("close", None))


class AsyncLoopPortalTests:
    def test_run_returns_plain_value_and_rejects_closed_loop(self) -> None:
        loop = asyncio.new_event_loop()
        portal = async_compat.AsyncLoopPortal(loop)
        assert portal.run("plain") == "plain"
        loop.close()
        with pytest.raises(RuntimeError, match="已关闭"):
            portal.run(_FakeAwaitable())

    def test_run_and_run_with_timeout_use_threadsafe_future(self, monkeypatch) -> None:
        loop = asyncio.new_event_loop()
        portal = async_compat.AsyncLoopPortal(loop)
        portal._thread_id = -1
        future: Future[str] = Future()
        future.set_result("done")

        def _fake_run_coroutine_threadsafe(coro, _loop):
            coro.close()
            return future

        monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _fake_run_coroutine_threadsafe)

        assert portal.run(_FakeAwaitable()) == "done"
        assert portal.run_with_timeout(_FakeAwaitable(), timeout=0.1) == "done"
        loop.close()

    def test_wrap_and_unwrap_handle_nested_values(self) -> None:
        loop = asyncio.new_event_loop()
        portal = async_compat.AsyncLoopPortal(loop)
        wrapped = portal.wrap({"items": [object()]})
        assert isinstance(wrapped["items"][0], async_compat.AsyncCompatObject)
        assert portal.unwrap(wrapped)["items"][0] is wrapped["items"][0]._target
        loop.close()

    def test_route_wrapper_is_cached_per_target_and_callback(self) -> None:
        loop = asyncio.new_event_loop()
        portal = async_compat.AsyncLoopPortal(loop)
        callback = lambda route, request: None
        target = object()
        first = portal.route_wrapper(target, callback, owner=None)
        second = portal.route_wrapper(target, callback, owner=None)
        assert first is second
        assert portal.find_route_wrapper(target, callback) is first
        loop.close()


class AsyncCompatFacadeTests:
    def test_async_compat_object_and_method_wrap_values(self, monkeypatch) -> None:
        loop = asyncio.new_event_loop()
        portal = async_compat.AsyncLoopPortal(loop)
        target = SimpleNamespace(value="x")

        async def _method():
            return {"ok": [1, 2]}

        target.method = _method
        monkeypatch.setattr(portal, "run", lambda awaitable: asyncio.run(awaitable) if asyncio.iscoroutine(awaitable) else awaitable)

        obj = async_compat.AsyncCompatObject(portal, target, owner=None)
        assert obj.value == "x"
        wrapped = obj.method()
        assert wrapped["ok"] == [1, 2]
        obj.value = "y"
        assert target.value == "y"
        loop.close()

    def test_async_compat_element_supports_find_and_click_fallbacks(self, monkeypatch) -> None:
        loop = asyncio.new_event_loop()
        portal = async_compat.AsyncLoopPortal(loop)
        handle = _AsyncHandle()
        child = _AsyncHandle()
        handle.query_selector_result = child
        handle.query_selector_all_result = [child]
        handle.click_errors = [RuntimeError("first"), RuntimeError("second")]
        monkeypatch.setattr(portal, "run", lambda awaitable: asyncio.run(awaitable) if asyncio.iscoroutine(awaitable) else awaitable)
        element = async_compat.AsyncCompatElement(portal, handle, page=object())

        assert element.text == "hello"
        assert element.get_attribute("data-id") == "attr"
        assert element.is_displayed() is True
        assert element.size == {"width": 10, "height": 20}
        assert element.tag_name == "value"
        element.click()
        element.clear()
        element.send_keys("abc")
        assert isinstance(element.find_element("id", "demo"), async_compat.AsyncCompatElement)
        assert len(element.find_elements("css", ".x")) == 1
        loop.close()

    def test_async_compat_element_raises_for_missing_selector(self, monkeypatch) -> None:
        loop = asyncio.new_event_loop()
        portal = async_compat.AsyncLoopPortal(loop)
        monkeypatch.setattr(portal, "run", lambda awaitable: asyncio.run(awaitable) if asyncio.iscoroutine(awaitable) else awaitable)
        element = async_compat.AsyncCompatElement(portal, _AsyncHandle(), page=object())

        with pytest.raises(NoSuchElementException, match="Element not found"):
            element.find_element("id", "missing")
        loop.close()

    def test_async_browser_driver_covers_navigation_execute_and_quit_fallback(self, monkeypatch) -> None:
        loop = asyncio.new_event_loop()
        portal = async_compat.AsyncLoopPortal(loop)
        page = _AsyncHandle()
        context = _AsyncHandle()
        page.query_selector_result = _AsyncHandle()
        page.query_selector_all_result = [_AsyncHandle()]
        monkeypatch.setattr(portal, "run", lambda awaitable: asyncio.run(awaitable) if asyncio.iscoroutine(awaitable) else awaitable)

        driver = async_compat.AsyncBrowserDriver(
            portal=portal,
            owner=None,
            context=context,
            page=page,
            browser_name="edge",
            browser_pid=1234,
            release_callback=lambda: page.actions.append(("released", None)),
        )

        assert isinstance(driver.find_element("id", "demo"), async_compat.AsyncCompatElement)
        assert len(driver.find_elements("css", ".x")) == 1
        assert driver.execute_script("return 1;") == "value"
        driver.get("https://example.com", timeout=1000)
        assert driver.current_url == "https://example.com"
        assert driver.page_source == "<html></html>"
        assert driver.title == "demo"
        driver.set_window_size(10, 20)
        driver.refresh()
        assert driver.mark_cleanup_done() is True
        assert driver.mark_cleanup_done() is False

        def _failing_run_with_timeout(awaitable, timeout):
            del timeout
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            raise RuntimeError("boom")

        monkeypatch.setattr(portal, "run_with_timeout", _failing_run_with_timeout)
        monkeypatch.setattr(driver, "_force_terminate_browser_process_tree", lambda: True)
        driver._cleanup_done = False
        driver.quit()
        loop.close()

    def test_async_browser_driver_wraps_proxy_tunnel_errors(self, monkeypatch) -> None:
        loop = asyncio.new_event_loop()
        portal = async_compat.AsyncLoopPortal(loop)
        page = _AsyncHandle()
        context = _AsyncHandle()
        driver = async_compat.AsyncBrowserDriver(
            portal=portal,
            owner=None,
            context=context,
            page=page,
            browser_name="edge",
        )

        def _raise_proxy(awaitable):
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            raise RuntimeError("ERR_PROXY_CONNECTION_FAILED")

        monkeypatch.setattr(portal, "run", _raise_proxy)
        monkeypatch.setattr(async_compat, "_is_proxy_tunnel_error", lambda exc: "ERR_PROXY_CONNECTION_FAILED" in str(exc))

        with pytest.raises(ProxyConnectionError):
            driver.get("https://example.com")
        loop.close()
