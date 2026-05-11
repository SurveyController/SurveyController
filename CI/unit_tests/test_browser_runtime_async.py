from __future__ import annotations

from typing import Any

import pytest

from software.network.browser.exceptions import NoSuchElementException, ProxyConnectionError
from software.network.browser.runtime_async import PlaywrightAsyncDriver, PlaywrightAsyncElement


class _Handle:
    def __init__(self) -> None:
        self.click_calls = 0
        self.fill_calls: list[str] = []
        self.type_calls: list[str] = []
        self.evaluate_calls: list[tuple[str, Any]] = []
        self.query_selector_result: Any = None
        self.query_selector_all_result: list[Any] = []
        self.bounding_box_result: Any = {"width": 10, "height": 20}
        self.inner_text_value = "inner"
        self.attributes = {"name": "value"}
        self.click_failures = 0
        self.fill_failures = 0
        self.type_failures = 0

    async def inner_text(self) -> str:
        return self.inner_text_value

    async def get_attribute(self, name: str) -> Any:
        return self.attributes.get(name)

    async def bounding_box(self) -> Any:
        return self.bounding_box_result

    async def evaluate(self, script: str, *args: Any) -> Any:
        self.evaluate_calls.append((script, args[0] if args else None))
        if "tagName.toLowerCase" in script:
            return "input"
        if "aria-checked" in script:
            return True
        return True

    async def click(self) -> None:
        self.click_calls += 1
        if self.click_calls <= self.click_failures:
            raise RuntimeError("click failed")

    async def scroll_into_view_if_needed(self) -> None:
        return None

    async def fill(self, value: str) -> None:
        self.fill_calls.append(value)
        if len(self.fill_calls) <= self.fill_failures:
            raise RuntimeError("fill failed")

    async def type(self, value: str) -> None:
        self.type_calls.append(value)
        if len(self.type_calls) <= self.type_failures:
            raise RuntimeError("type failed")

    async def query_selector(self, _selector: str) -> Any:
        return self.query_selector_result

    async def query_selector_all(self, _selector: str) -> list[Any]:
        return list(self.query_selector_all_result)


class _Page:
    def __init__(self) -> None:
        self.query_selector_result: Any = None
        self.query_selector_all_result: list[Any] = []
        self.evaluate_calls: list[tuple[str, Any]] = []
        self.goto_error: Exception | None = None
        self.url = "https://example.com"
        self.content_value = "<html></html>"
        self.title_value = "title"
        self.closed = False
        self.context_closed = False
        self.reload_calls = 0
        self.timeout_calls: list[int] = []
        self.viewport_calls: list[dict[str, int]] = []

    async def query_selector(self, _selector: str) -> Any:
        return self.query_selector_result

    async def query_selector_all(self, _selector: str) -> list[Any]:
        return list(self.query_selector_all_result)

    async def evaluate(self, wrapper: str, args: Any) -> Any:
        self.evaluate_calls.append((wrapper, args))
        return {"ok": True}

    async def set_default_navigation_timeout(self, timeout: int) -> None:
        self.timeout_calls.append(timeout)

    async def set_default_timeout(self, timeout: int) -> None:
        self.timeout_calls.append(timeout)

    async def goto(self, _url: str, *, wait_until: str, timeout: int) -> None:
        del wait_until, timeout
        if self.goto_error is not None:
            raise self.goto_error

    async def content(self) -> str:
        return self.content_value

    async def title(self) -> str:
        return self.title_value

    async def set_viewport_size(self, payload: dict[str, int]) -> None:
        self.viewport_calls.append(payload)

    async def reload(self, *, wait_until: str) -> None:
        del wait_until
        self.reload_calls += 1

    async def close(self) -> None:
        self.closed = True


class _Context:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class BrowserRuntimeAsyncTests:
    @pytest.mark.asyncio
    async def test_playwright_async_element_covers_text_click_fill_and_lookup_paths(self) -> None:
        handle = _Handle()
        nested = _Handle()
        handle.query_selector_result = nested
        handle.query_selector_all_result = [nested]
        element = PlaywrightAsyncElement(handle, object())

        assert await element.text() == "inner"
        assert await element.get_attribute("name") == "value"
        assert await element.is_displayed()
        assert await element.is_selected()
        assert await element.size() == {"width": 10, "height": 20}
        assert await element.tag_name() == "input"

        handle.click_failures = 1
        await element.click()
        assert handle.click_calls >= 2

        handle.fill_failures = 1
        await element.clear()
        await element.send_keys("abc")
        assert handle.fill_calls
        assert handle.type_calls == []

        found = await element.find_element("css", ".a")
        found_many = await element.find_elements("css", ".a")
        assert isinstance(found, PlaywrightAsyncElement)
        assert len(found_many) == 1

        handle.query_selector_result = None
        with pytest.raises(NoSuchElementException):
            await element.find_element("css", ".missing")

    @pytest.mark.asyncio
    async def test_playwright_async_driver_covers_navigation_script_and_close_paths(self, monkeypatch) -> None:
        page = _Page()
        context = _Context()
        handle = _Handle()
        page.query_selector_result = handle
        page.query_selector_all_result = [handle]
        released: list[str] = []
        driver = PlaywrightAsyncDriver(
            context=context,
            page=page,
            browser_name="edge",
            browser_pid=123,
            release_callback=lambda: released.append("released"),
        )

        assert await driver.find_element("css", ".x")
        assert len(await driver.find_elements("css", ".x")) == 1
        assert await driver.execute_script("return 1;", PlaywrightAsyncElement(handle, page)) == {"ok": True}
        await driver.get("https://example.com", timeout=1234)
        assert await driver.current_url() == "https://example.com"
        assert await driver.page() is page
        assert await driver.page_source() == "<html></html>"
        assert await driver.title() == "title"
        await driver.set_window_size(1200, 800)
        await driver.refresh()
        assert page.viewport_calls == [{"width": 1200, "height": 800}]
        assert page.reload_calls == 1

        page.goto_error = RuntimeError("net::ERR_PROXY_CONNECTION_FAILED")
        with pytest.raises(ProxyConnectionError):
            await driver.get("https://example.com")

        await driver.aclose()
        assert page.closed
        assert context.closed
        assert released == ["released"]

        runs: list[list[str]] = []
        monkeypatch.setattr(
            "software.network.browser.runtime_async.subprocess.run",
            lambda cmd, **kwargs: runs.append(cmd) or type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
        )
        assert driver.mark_cleanup_done()
        assert not driver.mark_cleanup_done()
        driver._cleanup_done = False
        driver.quit()
        assert runs == [["taskkill", "/PID", "123", "/T", "/F"]]
