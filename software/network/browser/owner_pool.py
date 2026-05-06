"""少量浏览器底座 + 多上下文动态租约池。"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Set, Tuple

from software.app.config import BROWSER_PREFERENCE
from software.core.engine.stop_signal import StopSignalLike
from software.logging.log_utils import log_suppressed_exception
from software.network.browser.async_bridge import (
    AsyncBridgeLoopThread,
    AsyncObjectProxy,
    close_bridge_loop_safely,
)
from software.network.browser.element import PlaywrightElement
from software.network.browser.exceptions import NoSuchElementException, ProxyConnectionError
from software.network.browser.options import (
    _build_context_args,
    _build_launch_args,
    _build_selector,
    _is_browser_disconnected_error,
    _is_proxy_tunnel_error,
)
from software.network.browser.startup import (
    _format_exception_chain,
    classify_playwright_startup_error,
    is_playwright_startup_environment_error,
)

DEFAULT_HEADED_CONTEXTS_PER_BROWSER = 4
DEFAULT_HEADLESS_CONTEXTS_PER_BROWSER = 8


@dataclass(frozen=True)
class BrowserPoolConfig:
    logical_concurrency: int
    contexts_per_owner: int
    owner_count: int
    headless: bool = False

    @classmethod
    def from_concurrency(
        cls,
        logical_concurrency: int,
        *,
        headless: bool,
        contexts_per_owner: Optional[int] = None,
    ) -> "BrowserPoolConfig":
        concurrency = max(1, int(logical_concurrency or 1))
        default_capacity = (
            DEFAULT_HEADLESS_CONTEXTS_PER_BROWSER
            if bool(headless)
            else DEFAULT_HEADED_CONTEXTS_PER_BROWSER
        )
        normalized_capacity = max(1, int(contexts_per_owner or default_capacity))
        owner_count = max(1, (concurrency + normalized_capacity - 1) // normalized_capacity)
        return cls(
            logical_concurrency=concurrency,
            contexts_per_owner=normalized_capacity,
            owner_count=owner_count,
            headless=bool(headless),
        )


class BrowserOwnerLease:
    """一次会话占用一个 owner 容量名额，直到 session 结束。"""

    def __init__(self, owner: "AsyncBrowserOwner") -> None:
        self.owner = owner
        self._activated = False
        self._released = False
        self._lock = threading.Lock()

    def mark_activated(self) -> None:
        with self._lock:
            if self._released:
                raise RuntimeError("BrowserOwnerLease 已释放，不能再激活")
            if self._activated:
                return
            self.owner.activate_reserved_slot()
            self._activated = True

    def release(self) -> bool:
        with self._lock:
            if self._released:
                return False
            self._released = True
            activated = self._activated
        if not activated:
            self.owner.release_reserved_slot()
        return True

    @property
    def activated(self) -> bool:
        with self._lock:
            return bool(self._activated)


class AsyncBrowserDriver:
    """供现有同步 provider 复用的浏览器 driver。"""

    def __init__(
        self,
        *,
        owner: "AsyncBrowserOwner",
        bridge: AsyncBridgeLoopThread,
        context: AsyncObjectProxy,
        page: AsyncObjectProxy,
        browser_name: str,
        browser_pid: Optional[int] = None,
    ) -> None:
        self._owner = owner
        self._bridge = bridge
        self._context = context
        self._page = page
        self.browser_name = str(browser_name or "")
        self.session_id = f"apw-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
        self.browser_pid = int(browser_pid or 0) or None
        self.browser_pids: Set[int] = {self.browser_pid} if self.browser_pid else set()
        self._cleanup_done = False
        self._cleanup_lock = threading.Lock()

    def find_element(self, by: str, value: str):
        handle = self._page.query_selector(_build_selector(by, value))
        if handle is None:
            raise NoSuchElementException(f"Element not found: {by} {value}")
        return PlaywrightElement(handle, self._page)

    def find_elements(self, by: str, value: str):
        handles = self._page.query_selector_all(_build_selector(by, value))
        return [PlaywrightElement(h, self._page) for h in handles]

    def execute_script(self, script: str, *args):
        processed_args = [arg._handle if isinstance(arg, PlaywrightElement) else arg for arg in args]
        try:
            wrapper = (
                "(args) => {"
                "  const fn = function(){"
                + script
                + "  };"
                "  return fn.apply(null, Array.isArray(args) ? args : []);"
                "}"
            )
            return self._page.evaluate(wrapper, processed_args)
        except Exception as exc:
            logging.info("execute_script failed: %s", exc)
            return None

    def get(self, url: str, timeout: int = 20000, wait_until: str = "domcontentloaded") -> None:
        try:
            self._page.set_default_navigation_timeout(timeout)
            self._page.set_default_timeout(timeout)
            self._page.goto(url, wait_until=wait_until, timeout=timeout)
            return
        except Exception as exc:
            if _is_proxy_tunnel_error(exc):
                logging.info("Page.goto proxy tunnel failure: %s", exc)
                raise ProxyConnectionError(str(exc)) from exc
            raise

    @property
    def current_url(self) -> str:
        try:
            return str(self._page.url or "")
        except Exception:
            return ""

    @property
    def page(self):
        return self._page

    @property
    def page_source(self) -> str:
        try:
            return str(self._page.content() or "")
        except Exception:
            return ""

    @property
    def title(self) -> str:
        try:
            return str(self._page.title() or "")
        except Exception:
            return ""

    def set_window_size(self, width: int, height: int) -> None:
        try:
            self._page.set_viewport_size({"width": int(width), "height": int(height)})
        except Exception as exc:
            log_suppressed_exception("AsyncBrowserDriver.set_window_size", exc, level=logging.WARNING)

    def refresh(self) -> None:
        try:
            self._page.reload(wait_until="domcontentloaded")
        except Exception as exc:
            log_suppressed_exception("AsyncBrowserDriver.refresh", exc, level=logging.WARNING)

    def mark_cleanup_done(self) -> bool:
        with self._cleanup_lock:
            if self._cleanup_done:
                return False
            self._cleanup_done = True
            return True

    def quit(self) -> None:
        try:
            self._page.close()
        except Exception as exc:
            log_suppressed_exception("AsyncBrowserDriver.quit page.close", exc, level=logging.WARNING)
        try:
            self._context.close()
        except Exception as exc:
            log_suppressed_exception("AsyncBrowserDriver.quit context.close", exc, level=logging.WARNING)
        try:
            self._owner.release_slot()
        except Exception as exc:
            log_suppressed_exception("AsyncBrowserDriver.quit owner.release_slot", exc, level=logging.WARNING)


class AsyncBrowserOwner:
    """一个浏览器底座，对外提供多个独立 context。"""

    def __init__(
        self,
        *,
        owner_id: int,
        prefer_browsers: Optional[List[str]] = None,
        headless: bool = False,
        window_position: Optional[Tuple[int, int]] = None,
        max_contexts: int = DEFAULT_HEADED_CONTEXTS_PER_BROWSER,
        capacity_notifier: Optional[Callable[[], None]] = None,
    ) -> None:
        self.owner_id = max(1, int(owner_id or 1))
        self._prefer_browsers = list(prefer_browsers or BROWSER_PREFERENCE)
        self._headless = bool(headless)
        self._window_position = window_position
        self._max_contexts = max(1, int(max_contexts or 1))
        self._bridge = AsyncBridgeLoopThread(name=f"BrowserOwner-{self.owner_id}")
        self._browser = None
        self._playwright = None
        self._browser_name = ""
        self._browser_pid: Optional[int] = None
        self._broken = False
        self._closed = False
        self._slot_lock = threading.Lock()
        self._active_slots = 0
        self._reserved_slots = 0
        self._capacity_notifier = capacity_notifier
        self._ensure_browser_lock: Optional[asyncio.Lock] = None
        self._cleanup_marked = False
        self._cleanup_lock = threading.Lock()

    @property
    def browser_name(self) -> str:
        return str(self._browser_name or "")

    @property
    def active_slots(self) -> int:
        with self._slot_lock:
            return int(self._active_slots or 0)

    @property
    def reserved_slots(self) -> int:
        with self._slot_lock:
            return int(self._reserved_slots or 0)

    @property
    def total_load(self) -> int:
        with self._slot_lock:
            return int(self._active_slots or 0) + int(self._reserved_slots or 0)

    def mark_cleanup_done(self) -> bool:
        with self._cleanup_lock:
            if self._cleanup_marked:
                return False
            self._cleanup_marked = True
            return True

    def mark_broken(self) -> None:
        self._broken = True

    def try_reserve_slot(self) -> bool:
        with self._slot_lock:
            current_total = int(self._active_slots or 0) + int(self._reserved_slots or 0)
            if current_total >= self._max_contexts:
                return False
            self._reserved_slots += 1
            return True

    def activate_reserved_slot(self) -> None:
        with self._slot_lock:
            if self._reserved_slots <= 0:
                raise RuntimeError(f"owner={self.owner_id} 没有待激活的 context 预留名额")
            self._reserved_slots -= 1
            self._active_slots += 1

    def release_reserved_slot(self) -> None:
        should_notify = False
        with self._slot_lock:
            if self._reserved_slots <= 0:
                return
            self._reserved_slots -= 1
            should_notify = True
        if should_notify:
            self._notify_capacity_available()

    def release_slot(self) -> None:
        should_notify = False
        with self._slot_lock:
            if self._active_slots <= 0:
                return
            self._active_slots -= 1
            should_notify = True
        if should_notify:
            self._notify_capacity_available()

    def _notify_capacity_available(self) -> None:
        callback = self._capacity_notifier
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:
            log_suppressed_exception("AsyncBrowserOwner._notify_capacity_available", exc, level=logging.WARNING)

    async def _shutdown_browser_async(self) -> None:
        browser = self._browser
        playwright_instance = self._playwright
        self._browser = None
        self._playwright = None
        self._browser_name = ""
        self._browser_pid = None
        if browser is not None:
            try:
                await browser.close()
            except Exception as exc:
                log_suppressed_exception("AsyncBrowserOwner._shutdown_browser_async browser.close", exc, level=logging.WARNING)
        if playwright_instance is not None:
            try:
                await playwright_instance.stop()
            except Exception as exc:
                log_suppressed_exception("AsyncBrowserOwner._shutdown_browser_async playwright.stop", exc, level=logging.WARNING)

    async def _launch_browser_async(self) -> tuple[Any, str]:
        from playwright.async_api import async_playwright

        candidates = list(self._prefer_browsers or BROWSER_PREFERENCE)
        if not candidates:
            candidates = list(BROWSER_PREFERENCE)

        last_exc: Optional[Exception] = None
        for browser_name in candidates:
            pw = None
            try:
                launch_args = _build_launch_args(
                    browser_name=browser_name,
                    headless=self._headless,
                    window_position=self._window_position,
                    append_no_proxy=False,
                )
                pw = await async_playwright().start()
                browser = await pw.chromium.launch(**launch_args)
                self._playwright = pw
                self._browser = browser
                self._browser_name = browser_name
                self._broken = False
                self._browser_pid = self._extract_browser_pid(browser)
                logging.info("[Action Log] AsyncBrowserOwner 启动底座成功：owner=%s browser=%s", self.owner_id, browser_name)
                return browser, browser_name
            except Exception as exc:
                last_exc = exc
                logging.warning("AsyncBrowserOwner 启动 %s 失败(owner=%s): %s", browser_name, self.owner_id, exc)
                logging.error(
                    "[Action Log] AsyncBrowserOwner 启动异常链(owner=%s browser=%s): %s",
                    self.owner_id,
                    browser_name,
                    _format_exception_chain(exc),
                )
                if pw is not None:
                    try:
                        await pw.stop()
                    except Exception as stop_exc:
                        log_suppressed_exception("AsyncBrowserOwner._launch_browser_async pw.stop", stop_exc, level=logging.WARNING)
                if is_playwright_startup_environment_error(exc):
                    break

        friendly = classify_playwright_startup_error(last_exc).message if last_exc is not None else "未知错误"
        if last_exc is not None:
            raise RuntimeError(f"AsyncBrowserOwner 无法启动任何浏览器: {friendly}") from last_exc
        raise RuntimeError(f"AsyncBrowserOwner 无法启动任何浏览器: {friendly}")

    @staticmethod
    def _extract_browser_pid(browser: Any) -> Optional[int]:
        try:
            proc = getattr(browser, "process", None)
            return int(proc.pid) if proc and getattr(proc, "pid", None) else None
        except Exception:
            return None

    async def _ensure_browser_async(self) -> tuple[Any, str]:
        if self._closed:
            raise RuntimeError("AsyncBrowserOwner 已关闭")
        if self._browser is not None and not self._broken:
            return self._browser, self.browser_name
        if self._ensure_browser_lock is None:
            self._ensure_browser_lock = asyncio.Lock()
        async with self._ensure_browser_lock:
            if self._closed:
                raise RuntimeError("AsyncBrowserOwner 已关闭")
            if self._browser is not None and not self._broken:
                return self._browser, self.browser_name
            await self._shutdown_browser_async()
            return await self._launch_browser_async()

    async def _open_session_async(
        self,
        *,
        proxy_address: Optional[str],
        user_agent: Optional[str],
    ) -> tuple[Any, Any, str, Optional[int]]:
        last_exc: Optional[Exception] = None
        context_args = _build_context_args(
            headless=self._headless,
            proxy_address=proxy_address,
            user_agent=user_agent,
        )
        for attempt in range(2):
            browser, browser_name = await self._ensure_browser_async()
            context = None
            try:
                context = await browser.new_context(**context_args)
                page = await context.new_page()
                return context, page, browser_name, self._browser_pid
            except Exception as exc:
                last_exc = exc
                if context is not None:
                    try:
                        await context.close()
                    except Exception as close_exc:
                        log_suppressed_exception(
                            "AsyncBrowserOwner._open_session_async context.close after failure",
                            close_exc,
                            level=logging.WARNING,
                        )
                if attempt == 0 and _is_browser_disconnected_error(exc):
                    logging.warning(
                        "AsyncBrowserOwner 检测到底座浏览器已断开，准备重建后重试一次：owner=%s error=%s",
                        self.owner_id,
                        exc,
                    )
                    self.mark_broken()
                    await self._shutdown_browser_async()
                    continue
                raise
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("AsyncBrowserOwner 打开浏览器会话失败：未知错误")

    def open_session(
        self,
        *,
        proxy_address: Optional[str],
        user_agent: Optional[str],
        lease: BrowserOwnerLease,
    ) -> AsyncBrowserDriver:
        if self._closed:
            raise RuntimeError("AsyncBrowserOwner 已关闭")
        context, page, browser_name, browser_pid = self._bridge.run_coroutine(
            self._open_session_async(proxy_address=proxy_address, user_agent=user_agent)
        )
        lease.mark_activated()
        context_proxy = AsyncObjectProxy(self._bridge, context, owner=self)
        page_proxy = AsyncObjectProxy(self._bridge, page, owner=self)
        return AsyncBrowserDriver(
            owner=self,
            bridge=self._bridge,
            context=context_proxy,
            page=page_proxy,
            browser_name=browser_name,
            browser_pid=browser_pid,
        )

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._bridge.run_coroutine(self._shutdown_browser_async())
        except Exception as exc:
            log_suppressed_exception("AsyncBrowserOwner.shutdown", exc, level=logging.WARNING)
        finally:
            close_bridge_loop_safely(self._bridge)

    def quit(self) -> None:
        self.shutdown()


class BrowserOwnerPool:
    """共享少量浏览器底座，按负载动态分配 session 所属 owner。"""

    def __init__(
        self,
        *,
        config: BrowserPoolConfig,
        headless: bool,
        prefer_browsers: Optional[List[str]] = None,
        window_positions: Optional[List[Tuple[int, int]]] = None,
    ) -> None:
        self.config = config
        self._condition = threading.Condition()
        self._owners: List[AsyncBrowserOwner] = []
        self._closed = False
        self._cleanup_marked = False
        positions = list(window_positions or [])
        for owner_index in range(config.owner_count):
            window_position = positions[owner_index] if owner_index < len(positions) else None
            self._owners.append(
                AsyncBrowserOwner(
                    owner_id=owner_index + 1,
                    prefer_browsers=prefer_browsers,
                    headless=headless,
                    window_position=window_position,
                    max_contexts=config.contexts_per_owner,
                    capacity_notifier=self._notify_capacity_available,
                )
            )

    @property
    def owners(self) -> List[AsyncBrowserOwner]:
        return list(self._owners)

    def _notify_capacity_available(self) -> None:
        with self._condition:
            self._condition.notify_all()

    @staticmethod
    def _owner_sort_key(owner: AsyncBrowserOwner) -> tuple[int, int, int, int]:
        idle_rank = 0 if owner.total_load <= 0 else 1
        return (idle_rank, owner.total_load, owner.active_slots, owner.owner_id)

    def acquire_owner_lease(
        self,
        *,
        stop_signal: Optional[StopSignalLike] = None,
        wait: bool = True,
    ) -> Optional[BrowserOwnerLease]:
        while True:
            if stop_signal is not None and stop_signal.is_set():
                return None
            with self._condition:
                if self._closed:
                    return None
                candidates = sorted(self._owners, key=self._owner_sort_key)
                for owner in candidates:
                    if owner.try_reserve_slot():
                        return BrowserOwnerLease(owner)
                if not wait:
                    return None
                self._condition.wait(timeout=0.05)

    def shutdown(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()
        for owner in list(self._owners):
            try:
                owner.shutdown()
            except Exception as exc:
                log_suppressed_exception("BrowserOwnerPool.shutdown", exc, level=logging.WARNING)

    def mark_cleanup_done(self) -> bool:
        if self._cleanup_marked:
            return False
        self._cleanup_marked = True
        return True

    def quit(self) -> None:
        self.shutdown()


__all__ = [
    "AsyncBrowserDriver",
    "AsyncBrowserOwner",
    "BrowserOwnerLease",
    "BrowserOwnerPool",
    "BrowserPoolConfig",
    "DEFAULT_HEADED_CONTEXTS_PER_BROWSER",
    "DEFAULT_HEADLESS_CONTEXTS_PER_BROWSER",
]
