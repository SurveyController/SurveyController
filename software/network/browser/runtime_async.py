"""运行时专用的原生异步浏览器驱动。"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from inspect import isawaitable
from typing import Any, Optional, Protocol, Set, TypeVar

from software.logging.log_utils import log_suppressed_exception
from software.network.browser.exceptions import NoSuchElementException, ProxyConnectionError
from software.network.browser.options import _build_selector, _is_proxy_tunnel_error
from software.network.browser.subprocess_utils import build_local_text_subprocess_kwargs

_BrowserElementT = TypeVar("_BrowserElementT", bound="BrowserElement")


async def _maybe_await(value: Any) -> Any:
    if isawaitable(value):
        return await value
    return value


class BrowserElement(Protocol):
    async def text(self) -> str: ...

    async def get_attribute(self, name: str) -> Any: ...

    async def is_displayed(self) -> bool: ...

    async def is_selected(self) -> bool: ...

    async def size(self) -> dict[str, float]: ...

    async def tag_name(self) -> str: ...

    async def click(self) -> None: ...

    async def clear(self) -> None: ...

    async def send_keys(self, value: str) -> None: ...

    async def find_element(self: _BrowserElementT, by: str, value: str) -> _BrowserElementT: ...

    async def find_elements(self: _BrowserElementT, by: str, value: str) -> list[_BrowserElementT]: ...


class BrowserDriver(Protocol):
    browser_name: str
    session_id: str
    browser_pid: Optional[int]
    browser_pids: Set[int]

    async def find_element(self, by: str, value: str) -> BrowserElement: ...

    async def find_elements(self, by: str, value: str) -> list[BrowserElement]: ...

    async def execute_script(self, script: str, *args: Any) -> Any: ...

    async def get(
        self,
        url: str,
        timeout: int = 20000,
        wait_until: str = "domcontentloaded",
    ) -> None: ...

    async def current_url(self) -> str: ...

    async def page(self) -> Any: ...

    async def page_source(self) -> str: ...

    async def title(self) -> str: ...

    async def set_window_size(self, width: int, height: int) -> None: ...

    async def refresh(self) -> None: ...

    async def aclose(self) -> None: ...

    def mark_cleanup_done(self) -> bool: ...

    def quit(self) -> None: ...


class PlaywrightAsyncElement:
    """基于 Playwright async_api 的元素薄封装。"""

    def __init__(self, handle: Any, page: Any):
        self._handle = handle
        self._page = page

    @property
    def raw_handle(self) -> Any:
        return self._handle

    async def text(self) -> str:
        try:
            return str(await self._handle.inner_text() or "")
        except Exception:
            return ""

    async def get_attribute(self, name: str) -> Any:
        try:
            return await self._handle.get_attribute(name)
        except Exception:
            return None

    async def is_displayed(self) -> bool:
        try:
            return await self._handle.bounding_box() is not None
        except Exception:
            return False

    async def is_selected(self) -> bool:
        script = "el => !!(el.checked || el.selected || el.getAttribute('aria-checked') === 'true')"
        try:
            return bool(await self._handle.evaluate(script))
        except Exception:
            return False

    async def size(self) -> dict[str, float]:
        try:
            box = await self._handle.bounding_box()
        except Exception:
            box = None
        if not box:
            return {"width": 0, "height": 0}
        return {"width": box.get("width") or 0, "height": box.get("height") or 0}

    async def tag_name(self) -> str:
        try:
            return str(await self._handle.evaluate("el => el.tagName.toLowerCase()") or "")
        except Exception:
            return ""

    async def click(self) -> None:
        last_exc: Optional[Exception] = None
        try:
            await self._handle.click()
            return
        except Exception as exc:
            last_exc = exc
        try:
            await self._handle.scroll_into_view_if_needed()
            await self._handle.click()
            return
        except Exception as exc:
            last_exc = exc
            log_suppressed_exception("PlaywrightAsyncElement.click fallback", exc, level=logging.WARNING)
        try:
            await self._handle.evaluate("el => { el.click(); return true; }")
            return
        except Exception as exc:
            last_exc = exc
            log_suppressed_exception("PlaywrightAsyncElement.click js fallback", exc, level=logging.WARNING)
        if last_exc is not None:
            raise last_exc

    async def clear(self) -> None:
        try:
            await self._handle.fill("")
            return
        except Exception as exc:
            log_suppressed_exception("PlaywrightAsyncElement.clear fill", exc, level=logging.WARNING)
        try:
            await self._handle.evaluate(
                "el => { el.value = ''; el.dispatchEvent(new Event('input', {bubbles:true})); "
                "el.dispatchEvent(new Event('change', {bubbles:true})); }"
            )
        except Exception as exc:
            log_suppressed_exception("PlaywrightAsyncElement.clear js", exc, level=logging.WARNING)

    async def send_keys(self, value: str) -> None:
        text = "" if value is None else str(value)
        try:
            await self._handle.fill(text)
            return
        except Exception as exc:
            log_suppressed_exception("PlaywrightAsyncElement.send_keys fill", exc, level=logging.WARNING)
        try:
            await self._handle.type(text)
        except Exception as exc:
            log_suppressed_exception("PlaywrightAsyncElement.send_keys type", exc, level=logging.WARNING)

    async def find_element(self, by: str, value: str) -> "PlaywrightAsyncElement":
        selector = _build_selector(by, value)
        handle = await self._handle.query_selector(selector)
        if handle is None:
            raise NoSuchElementException(f"Element not found: {by} {value}")
        return PlaywrightAsyncElement(handle, self._page)

    async def find_elements(self, by: str, value: str) -> list["PlaywrightAsyncElement"]:
        selector = _build_selector(by, value)
        handles = await self._handle.query_selector_all(selector)
        return [PlaywrightAsyncElement(handle, self._page) for handle in handles]


class PlaywrightAsyncDriver:
    """运行时主链使用的原生异步浏览器驱动。"""

    def __init__(
        self,
        *,
        context: Any,
        page: Any,
        browser_name: str,
        browser_pid: Optional[int] = None,
        release_callback: Optional[Any] = None,
    ) -> None:
        self._context = context
        self._page = page
        self._release_callback = release_callback
        self.browser_name = str(browser_name or "")
        self.session_id = f"apw-{int(time.time() * 1000)}"
        self.browser_pid = int(browser_pid or 0) or None
        self.browser_pids: Set[int] = {self.browser_pid} if self.browser_pid else set()
        self._cleanup_done = False
        self._cleanup_lock = threading.Lock()

    async def find_element(self, by: str, value: str) -> PlaywrightAsyncElement:
        selector = _build_selector(by, value)
        handle = await self._page.query_selector(selector)
        if handle is None:
            raise NoSuchElementException(f"Element not found: {by} {value}")
        return PlaywrightAsyncElement(handle, self._page)

    async def find_elements(self, by: str, value: str) -> list[PlaywrightAsyncElement]:
        selector = _build_selector(by, value)
        handles = await self._page.query_selector_all(selector)
        return [PlaywrightAsyncElement(handle, self._page) for handle in handles]

    async def execute_script(self, script: str, *args: Any) -> Any:
        processed_args = [
            arg.raw_handle if isinstance(arg, PlaywrightAsyncElement) else arg
            for arg in args
        ]
        wrapper = (
            "(args) => {"
            "  const fn = function(){"
            + script
            + "  };"
            "  return fn.apply(null, Array.isArray(args) ? args : []);"
            "}"
        )
        try:
            return await self._page.evaluate(wrapper, processed_args)
        except Exception as exc:
            logging.info("execute_script failed: %s", exc)
            return None

    async def get(self, url: str, timeout: int = 20000, wait_until: str = "domcontentloaded") -> None:
        try:
            await _maybe_await(self._page.set_default_navigation_timeout(timeout))
            await _maybe_await(self._page.set_default_timeout(timeout))
            await self._page.goto(url, wait_until=wait_until, timeout=timeout)
        except Exception as exc:
            if _is_proxy_tunnel_error(exc):
                logging.info("Page.goto proxy tunnel failure: %s", exc)
                raise ProxyConnectionError(str(exc)) from exc
            raise

    async def current_url(self) -> str:
        try:
            return str(self._page.url or "")
        except Exception:
            return ""

    async def page(self) -> Any:
        return self._page

    async def page_source(self) -> str:
        try:
            return str(await self._page.content() or "")
        except Exception:
            return ""

    async def title(self) -> str:
        try:
            return str(await self._page.title() or "")
        except Exception:
            return ""

    async def set_window_size(self, width: int, height: int) -> None:
        try:
            await self._page.set_viewport_size({"width": int(width), "height": int(height)})
        except Exception as exc:
            log_suppressed_exception("PlaywrightAsyncDriver.set_window_size", exc, level=logging.WARNING)

    async def refresh(self) -> None:
        try:
            await self._page.reload(wait_until="domcontentloaded")
        except Exception as exc:
            log_suppressed_exception("PlaywrightAsyncDriver.refresh", exc, level=logging.WARNING)

    def mark_cleanup_done(self) -> bool:
        with self._cleanup_lock:
            if self._cleanup_done:
                return False
            self._cleanup_done = True
            return True

    async def aclose(self) -> None:
        try:
            await self._page.close()
        except Exception as exc:
            log_suppressed_exception("PlaywrightAsyncDriver.aclose page.close", exc, level=logging.WARNING)
        try:
            await self._context.close()
        except Exception as exc:
            log_suppressed_exception("PlaywrightAsyncDriver.aclose context.close", exc, level=logging.WARNING)
        if callable(self._release_callback):
            try:
                self._release_callback()
            except Exception as exc:
                log_suppressed_exception("PlaywrightAsyncDriver.aclose release_callback", exc, level=logging.WARNING)

    def _force_terminate_browser_process_tree(self) -> bool:
        pids = {int(pid) for pid in self.browser_pids if pid}
        if self.browser_pid:
            pids.add(int(self.browser_pid))
        if not pids:
            return False
        no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        terminated = False
        for pid in sorted(pids):
            try:
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    timeout=5,
                    creationflags=no_window,
                    **build_local_text_subprocess_kwargs(),
                )
            except Exception as exc:
                log_suppressed_exception(
                    "PlaywrightAsyncDriver._force_terminate_browser_process_tree taskkill",
                    exc,
                    level=logging.WARNING,
                )
                continue
            output = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
            if result.returncode == 0:
                terminated = True
                continue
            if "not found" in output or "没有运行的任务" in output or "找不到进程" in output:
                terminated = True
                continue
            logging.warning("强制关闭异步浏览器进程失败(pid=%s): %s", pid, output.strip() or f"returncode={result.returncode}")
        return terminated

    def quit(self) -> None:
        self.mark_cleanup_done()
        self._force_terminate_browser_process_tree()


__all__ = [
    "BrowserDriver",
    "BrowserElement",
    "PlaywrightAsyncDriver",
    "PlaywrightAsyncElement",
]
