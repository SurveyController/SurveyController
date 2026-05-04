"""Synchronous compatibility facade over async Playwright objects."""

from __future__ import annotations

import asyncio
import inspect
import logging
import random
import threading
import time
from concurrent.futures import Future
from typing import Any, Optional, Set

from software.logging.log_utils import log_suppressed_exception
from software.network.browser.exceptions import NoSuchElementException, ProxyConnectionError
from software.network.browser.options import _build_selector, _is_browser_disconnected_error, _is_proxy_tunnel_error

_PRIMITIVE_TYPES = (str, int, float, bool, bytes, type(None))


class AsyncLoopPortal:
    """Thread-safe portal for blocking calls into one running asyncio loop."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._thread_id = threading.get_ident()
        self._route_lock = threading.Lock()
        self._route_wrappers: dict[tuple[int, int], Any] = {}

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def run(self, awaitable: Any) -> Any:
        if self._loop.is_closed():
            if inspect.iscoroutine(awaitable):
                awaitable.close()
            raise RuntimeError("后台 asyncio loop 已关闭")
        if not inspect.isawaitable(awaitable):
            return awaitable
        if threading.get_ident() == self._thread_id:
            if inspect.iscoroutine(awaitable):
                awaitable.close()
            raise RuntimeError("不能在后台 asyncio 线程里阻塞等待自身协程")
        try:
            future: Future[Any] = asyncio.run_coroutine_threadsafe(awaitable, self._loop)
        except Exception:
            if inspect.iscoroutine(awaitable):
                awaitable.close()
            raise
        return future.result()

    def wrap(self, value: Any, *, owner: Optional[Any] = None) -> Any:
        if isinstance(value, _PRIMITIVE_TYPES):
            return value
        if isinstance(value, list):
            return [self.wrap(item, owner=owner) for item in value]
        if isinstance(value, tuple):
            return tuple(self.wrap(item, owner=owner) for item in value)
        if isinstance(value, set):
            return {self.wrap(item, owner=owner) for item in value}
        if isinstance(value, dict):
            return {key: self.wrap(item, owner=owner) for key, item in value.items()}
        return AsyncCompatObject(self, value, owner=owner)

    def unwrap(self, value: Any) -> Any:
        if isinstance(value, AsyncCompatObject):
            return value._target
        if isinstance(value, AsyncCompatElement):
            return value._target
        if isinstance(value, list):
            return [self.unwrap(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.unwrap(item) for item in value)
        if isinstance(value, set):
            return {self.unwrap(item) for item in value}
        if isinstance(value, dict):
            return {key: self.unwrap(item) for key, item in value.items()}
        return value

    def route_wrapper(self, target: Any, callback: Any, *, owner: Optional[Any]) -> Any:
        key = (id(target), id(callback))
        with self._route_lock:
            existing = self._route_wrappers.get(key)
            if existing is not None:
                return existing

            async def _wrapped(route: Any, request: Any) -> None:
                route_proxy = AsyncCompatObject(self, route, owner=owner)
                request_proxy = AsyncCompatObject(self, request, owner=owner)
                await asyncio.to_thread(callback, route_proxy, request_proxy)

            self._route_wrappers[key] = _wrapped
            return _wrapped

    def find_route_wrapper(self, target: Any, callback: Any) -> Any:
        key = (id(target), id(callback))
        with self._route_lock:
            return self._route_wrappers.get(key, callback)


class AsyncCompatMethod:
    def __init__(self, portal: AsyncLoopPortal, target: Any, attr_name: str, *, owner: Optional[Any]) -> None:
        self._portal = portal
        self._target = target
        self._attr_name = attr_name
        self._owner = owner

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        async def _call() -> Any:
            attr = getattr(self._target, self._attr_name)
            raw_args = tuple(self._portal.unwrap(arg) for arg in args)
            raw_kwargs = {key: self._portal.unwrap(value) for key, value in kwargs.items()}
            if self._attr_name == "route" and len(args) >= 2 and callable(args[1]):
                raw_args = (
                    self._portal.unwrap(args[0]),
                    self._portal.route_wrapper(self._target, args[1], owner=self._owner),
                    *tuple(self._portal.unwrap(arg) for arg in args[2:]),
                )
            elif self._attr_name == "unroute" and len(args) >= 2 and callable(args[1]):
                raw_args = (
                    self._portal.unwrap(args[0]),
                    self._portal.find_route_wrapper(self._target, args[1]),
                    *tuple(self._portal.unwrap(arg) for arg in args[2:]),
                )
            try:
                result = attr(*raw_args, **raw_kwargs)
                if inspect.isawaitable(result):
                    result = await result
                return result
            except Exception as exc:
                if self._owner is not None and _is_browser_disconnected_error(exc):
                    mark_broken = getattr(self._owner, "mark_broken", None)
                    if callable(mark_broken):
                        mark_broken()
                raise

        return self._portal.wrap(self._portal.run(_call()), owner=self._owner)


class AsyncCompatObject:
    """Generic blocking facade for async Playwright objects."""

    def __init__(self, portal: AsyncLoopPortal, target: Any, *, owner: Optional[Any]) -> None:
        object.__setattr__(self, "_portal", portal)
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_owner", owner)

    def __getattr__(self, item: str) -> Any:
        async def _get() -> Any:
            try:
                value = getattr(self._target, item)
            except Exception as exc:
                owner = object.__getattribute__(self, "_owner")
                if owner is not None and _is_browser_disconnected_error(exc):
                    mark_broken = getattr(owner, "mark_broken", None)
                    if callable(mark_broken):
                        mark_broken()
                raise
            return value

        value = self._portal.run(_get())
        if callable(value):
            return AsyncCompatMethod(self._portal, self._target, item, owner=self._owner)
        return self._portal.wrap(value, owner=self._owner)

    def __setattr__(self, key: str, value: Any) -> None:
        if key.startswith("_"):
            object.__setattr__(self, key, value)
            return

        async def _set() -> None:
            setattr(self._target, key, self._portal.unwrap(value))

        self._portal.run(_set())

    def __repr__(self) -> str:
        return f"<AsyncCompatObject {type(self._target).__name__}>"


class AsyncCompatElement:
    """Selenium-style element facade over async ElementHandle/Locator."""

    def __init__(self, portal: AsyncLoopPortal, handle: Any, page: Any, *, owner: Optional[Any] = None) -> None:
        self._portal = portal
        self._target = handle
        self._handle = AsyncCompatObject(portal, handle, owner=owner)
        self._page = page
        self._owner = owner

    def _call_target(self, attr_name: str, *args: Any, **kwargs: Any) -> Any:
        async def _call() -> Any:
            attr = getattr(self._target, attr_name)
            raw_args = tuple(self._portal.unwrap(arg) for arg in args)
            raw_kwargs = {key: self._portal.unwrap(value) for key, value in kwargs.items()}
            try:
                result = attr(*raw_args, **raw_kwargs)
                if inspect.isawaitable(result):
                    result = await result
                return result
            except Exception as exc:
                owner = self._owner
                if owner is not None and _is_browser_disconnected_error(exc):
                    mark_broken = getattr(owner, "mark_broken", None)
                    if callable(mark_broken):
                        mark_broken()
                raise

        return self._portal.run(_call())

    @property
    def text(self) -> str:
        try:
            return str(self._call_target("inner_text") or "")
        except Exception:
            return ""

    def get_attribute(self, name: str) -> Any:
        try:
            return self._call_target("get_attribute", name)
        except Exception:
            return None

    def is_displayed(self) -> bool:
        try:
            return self._call_target("bounding_box") is not None
        except Exception:
            return False

    def is_selected(self) -> bool:
        script = "el => !!(el.checked || el.selected || el.getAttribute('aria-checked') === 'true')"
        try:
            return bool(self._call_target("evaluate", script))
        except Exception:
            return False

    @property
    def size(self) -> dict[str, float]:
        try:
            box = self._call_target("bounding_box")
        except Exception:
            box = None
        if not box:
            return {"width": 0, "height": 0}
        return {"width": box.get("width") or 0, "height": box.get("height") or 0}

    @property
    def tag_name(self) -> str:
        try:
            return str(self._call_target("evaluate", "el => el.tagName.toLowerCase()") or "")
        except Exception:
            return ""

    def click(self) -> None:
        last_exc: Optional[Exception] = None
        try:
            self._call_target("click")
            return
        except Exception as exc:
            last_exc = exc
        try:
            self._call_target("scroll_into_view_if_needed")
            self._call_target("click")
            return
        except Exception as exc:
            last_exc = exc
            log_suppressed_exception("AsyncCompatElement.click fallback", exc, level=logging.WARNING)
        try:
            self._call_target("evaluate", "el => { el.click(); return true; }")
            return
        except Exception as exc:
            last_exc = exc
            log_suppressed_exception("AsyncCompatElement.click js fallback", exc, level=logging.WARNING)
        if last_exc is not None:
            raise last_exc

    def clear(self) -> None:
        try:
            self._call_target("fill", "")
            return
        except Exception as exc:
            log_suppressed_exception("AsyncCompatElement.clear fill", exc, level=logging.WARNING)
        try:
            self._call_target(
                "evaluate",
                "el => { el.value = ''; el.dispatchEvent(new Event('input', {bubbles:true})); "
                "el.dispatchEvent(new Event('change', {bubbles:true})); }",
            )
        except Exception as exc:
            log_suppressed_exception("AsyncCompatElement.clear js", exc, level=logging.WARNING)

    def send_keys(self, value: str) -> None:
        text = "" if value is None else str(value)
        try:
            self._call_target("fill", text)
            return
        except Exception as exc:
            log_suppressed_exception("AsyncCompatElement.send_keys fill", exc, level=logging.WARNING)
        try:
            self._call_target("type", text)
        except Exception as exc:
            log_suppressed_exception("AsyncCompatElement.send_keys type", exc, level=logging.WARNING)

    def find_element(self, by: str, value: str) -> "AsyncCompatElement":
        handle = self._call_target("query_selector", _build_selector(by, value))
        if handle is None:
            raise NoSuchElementException(f"Element not found: {by} {value}")
        return AsyncCompatElement(self._portal, handle, self._page, owner=self._owner)

    def find_elements(self, by: str, value: str) -> list["AsyncCompatElement"]:
        handles = self._call_target("query_selector_all", _build_selector(by, value))
        return [AsyncCompatElement(self._portal, handle, self._page, owner=self._owner) for handle in handles]


class AsyncBrowserDriver:
    """Synchronous driver facade used by legacy provider code."""

    def __init__(
        self,
        *,
        portal: AsyncLoopPortal,
        owner: Any,
        context: Any,
        page: Any,
        browser_name: str,
        browser_pid: Optional[int] = None,
        release_callback: Optional[Any] = None,
    ) -> None:
        self._portal = portal
        self._owner = owner
        self._context = context
        self._page = page
        self._release_callback = release_callback
        self.browser_name = str(browser_name or "")
        self.session_id = f"apw-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
        self.browser_pid = int(browser_pid or 0) or None
        self.browser_pids: Set[int] = {self.browser_pid} if self.browser_pid else set()
        self._cleanup_done = False
        self._cleanup_lock = threading.Lock()

    def find_element(self, by: str, value: str) -> AsyncCompatElement:
        handle = self._portal.run(self._page.query_selector(_build_selector(by, value)))
        if handle is None:
            raise NoSuchElementException(f"Element not found: {by} {value}")
        return AsyncCompatElement(self._portal, handle, self._page, owner=self._owner)

    def find_elements(self, by: str, value: str) -> list[AsyncCompatElement]:
        handles = self._portal.run(self._page.query_selector_all(_build_selector(by, value)))
        return [AsyncCompatElement(self._portal, handle, self._page, owner=self._owner) for handle in handles]

    def execute_script(self, script: str, *args: Any) -> Any:
        processed_args = [self._portal.unwrap(arg) for arg in args]
        wrapper = (
            "(args) => {"
            "  const fn = function(){"
            + script
            + "  };"
            "  return fn.apply(null, Array.isArray(args) ? args : []);"
            "}"
        )
        try:
            return self._portal.wrap(self._portal.run(self._page.evaluate(wrapper, processed_args)), owner=self._owner)
        except Exception as exc:
            logging.info("execute_script failed: %s", exc)
            return None

    def get(self, url: str, timeout: int = 20000, wait_until: str = "domcontentloaded") -> None:
        try:
            self._portal.run(self._page.set_default_navigation_timeout(timeout))
            self._portal.run(self._page.set_default_timeout(timeout))
            self._portal.run(self._page.goto(url, wait_until=wait_until, timeout=timeout))
        except Exception as exc:
            if _is_proxy_tunnel_error(exc):
                logging.info("Page.goto proxy tunnel failure: %s", exc)
                raise ProxyConnectionError(str(exc)) from exc
            raise

    @property
    def current_url(self) -> str:
        try:
            return str(self._portal.run(self._page.evaluate("() => window.location.href")) or "")
        except Exception:
            try:
                return str(getattr(self.page, "url", "") or "")
            except Exception:
                return ""

    @property
    def page(self) -> AsyncCompatObject:
        return AsyncCompatObject(self._portal, self._page, owner=self._owner)

    @property
    def page_source(self) -> str:
        try:
            return str(self._portal.run(self._page.content()) or "")
        except Exception:
            return ""

    @property
    def title(self) -> str:
        try:
            return str(self._portal.run(self._page.title()) or "")
        except Exception:
            return ""

    def set_window_size(self, width: int, height: int) -> None:
        try:
            self._portal.run(self._page.set_viewport_size({"width": int(width), "height": int(height)}))
        except Exception as exc:
            log_suppressed_exception("AsyncBrowserDriver.set_window_size", exc, level=logging.WARNING)

    def refresh(self) -> None:
        try:
            self._portal.run(self._page.reload(wait_until="domcontentloaded"))
        except Exception as exc:
            log_suppressed_exception("AsyncBrowserDriver.refresh", exc, level=logging.WARNING)

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
            log_suppressed_exception("AsyncBrowserDriver.aclose page.close", exc, level=logging.WARNING)
        try:
            await self._context.close()
        except Exception as exc:
            log_suppressed_exception("AsyncBrowserDriver.aclose context.close", exc, level=logging.WARNING)
        if callable(self._release_callback):
            try:
                self._release_callback()
            except Exception as exc:
                log_suppressed_exception("AsyncBrowserDriver.aclose release_callback", exc, level=logging.WARNING)

    def quit(self) -> None:
        if not self.mark_cleanup_done():
            return
        try:
            self._portal.run(self.aclose())
        except Exception as exc:
            log_suppressed_exception("AsyncBrowserDriver.quit", exc, level=logging.WARNING)


__all__ = [
    "AsyncBrowserDriver",
    "AsyncCompatElement",
    "AsyncCompatObject",
    "AsyncLoopPortal",
]
