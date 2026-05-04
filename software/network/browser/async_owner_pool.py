"""Pure async browser owner/context pool."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from software.app.config import BROWSER_PREFERENCE
from software.logging.log_utils import log_suppressed_exception
from software.network.browser.async_compat import AsyncBrowserDriver, AsyncLoopPortal
from software.network.browser.options import (
    _build_context_args,
    _build_launch_args,
    _is_browser_disconnected_error,
)
from software.network.browser.startup import (
    _format_exception_chain,
    classify_playwright_startup_error,
    is_playwright_startup_environment_error,
)
from software.network.browser.owner_pool import (
    BrowserPoolConfig,
    DEFAULT_HEADED_CONTEXTS_PER_BROWSER,
    DEFAULT_HEADLESS_CONTEXTS_PER_BROWSER,
)


@dataclass
class AsyncBrowserSession:
    driver: AsyncBrowserDriver
    owner_id: int
    browser_name: str

    async def close(self) -> None:
        await self.driver.aclose()


class AsyncBrowserOwner:
    """One real browser process with multiple async contexts."""

    def __init__(
        self,
        *,
        owner_id: int,
        portal: AsyncLoopPortal,
        prefer_browsers: Optional[List[str]] = None,
        headless: bool = False,
        window_position: Optional[Tuple[int, int]] = None,
        max_contexts: int = DEFAULT_HEADED_CONTEXTS_PER_BROWSER,
    ) -> None:
        self.owner_id = max(1, int(owner_id or 1))
        self._portal = portal
        self._prefer_browsers = list(prefer_browsers or BROWSER_PREFERENCE)
        self._headless = bool(headless)
        self._window_position = window_position
        self._semaphore = asyncio.Semaphore(max(1, int(max_contexts or 1)))
        self._browser = None
        self._playwright = None
        self._browser_name = ""
        self._browser_pid: Optional[int] = None
        self._broken = False
        self._closed = False
        self._ensure_lock = asyncio.Lock()
        self._active_contexts = 0

    @property
    def browser_name(self) -> str:
        return str(self._browser_name or "")

    @property
    def active_contexts(self) -> int:
        return int(self._active_contexts or 0)

    def mark_broken(self) -> None:
        self._broken = True

    async def _shutdown_browser(self) -> None:
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
                log_suppressed_exception("AsyncBrowserOwner._shutdown_browser browser.close", exc, level=logging.WARNING)
        if playwright_instance is not None:
            try:
                await playwright_instance.stop()
            except Exception as exc:
                log_suppressed_exception("AsyncBrowserOwner._shutdown_browser playwright.stop", exc, level=logging.WARNING)

    async def _launch_browser(self) -> tuple[Any, str]:
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
                        log_suppressed_exception("AsyncBrowserOwner._launch_browser pw.stop", stop_exc, level=logging.WARNING)
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

    async def _ensure_browser(self) -> tuple[Any, str]:
        if self._closed:
            raise RuntimeError("AsyncBrowserOwner 已关闭")
        if self._browser is not None and not self._broken:
            return self._browser, self.browser_name
        async with self._ensure_lock:
            if self._closed:
                raise RuntimeError("AsyncBrowserOwner 已关闭")
            if self._browser is not None and not self._broken:
                return self._browser, self.browser_name
            await self._shutdown_browser()
            return await self._launch_browser()

    async def open_session(self, *, proxy_address: Optional[str], user_agent: Optional[str]) -> AsyncBrowserSession:
        await self._semaphore.acquire()
        self._active_contexts += 1
        context = None
        try:
            browser, browser_name = await self._ensure_browser()
            context_args = _build_context_args(
                headless=self._headless,
                proxy_address=proxy_address,
                user_agent=user_agent,
            )
            context = await browser.new_context(**context_args)
            await context.route(
                "**/*",
                _route_runtime_resource,
            )
            page = await context.new_page()
            driver = AsyncBrowserDriver(
                portal=self._portal,
                owner=self,
                context=context,
                page=page,
                browser_name=browser_name,
                browser_pid=self._browser_pid,
                release_callback=self._release_slot,
            )
            return AsyncBrowserSession(driver=driver, owner_id=self.owner_id, browser_name=browser_name)
        except Exception as exc:
            if context is not None:
                try:
                    await context.close()
                except Exception as close_exc:
                    log_suppressed_exception("AsyncBrowserOwner.open_session context.close", close_exc, level=logging.WARNING)
            self._release_slot()
            if _is_browser_disconnected_error(exc):
                self.mark_broken()
            raise

    def _release_slot(self) -> None:
        if self._active_contexts > 0:
            self._active_contexts -= 1
        try:
            self._semaphore.release()
        except ValueError:
            pass

    async def shutdown(self) -> None:
        self._closed = True
        await self._shutdown_browser()


async def _route_runtime_resource(route: Any, request: Any) -> None:
    async def _pass_through() -> None:
        fallback = getattr(route, "fallback", None)
        if callable(fallback):
            await fallback()
            return
        await route.continue_()

    try:
        resource_type = str(getattr(request, "resource_type", "") or "").lower()
        url = str(getattr(request, "url", "") or "").lower()
        if "joinnew/processjq.ashx" in url:
            await _pass_through()
            return
        if resource_type in {"image", "font", "media"}:
            await route.abort()
            return
        if any(marker in url for marker in ("google-analytics", "doubleclick", "hm.baidu.com", "cnzz.com")):
            await route.abort()
            return
        await _pass_through()
    except Exception:
        try:
            await _pass_through()
        except Exception:
            pass


class AsyncBrowserOwnerPool:
    """Shared async pool: few browsers, many contexts."""

    def __init__(
        self,
        *,
        config: BrowserPoolConfig,
        portal: AsyncLoopPortal,
        headless: bool,
        prefer_browsers: Optional[List[str]] = None,
        window_positions: Optional[List[Tuple[int, int]]] = None,
    ) -> None:
        self.config = config
        self._closed = False
        self._owners: List[AsyncBrowserOwner] = []
        positions = list(window_positions or [])
        for owner_index in range(config.owner_count):
            self._owners.append(
                AsyncBrowserOwner(
                    owner_id=owner_index + 1,
                    portal=portal,
                    prefer_browsers=prefer_browsers,
                    headless=headless,
                    window_position=positions[owner_index] if owner_index < len(positions) else None,
                    max_contexts=config.contexts_per_owner,
                )
            )

    @property
    def owners(self) -> List[AsyncBrowserOwner]:
        return list(self._owners)

    @staticmethod
    def _owner_sort_key(owner: AsyncBrowserOwner) -> tuple[int, int]:
        return (owner.active_contexts, owner.owner_id)

    async def open_session(self, *, proxy_address: Optional[str], user_agent: Optional[str]) -> AsyncBrowserSession:
        if self._closed:
            raise RuntimeError("AsyncBrowserOwnerPool 已关闭")
        owners = sorted(self._owners, key=self._owner_sort_key)
        last_exc: Optional[Exception] = None
        for owner in owners:
            try:
                return await owner.open_session(proxy_address=proxy_address, user_agent=user_agent)
            except Exception as exc:
                last_exc = exc
                if _is_browser_disconnected_error(exc):
                    continue
                raise
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("AsyncBrowserOwnerPool 没有可用 owner")

    async def shutdown(self) -> None:
        self._closed = True
        await asyncio.gather(*(owner.shutdown() for owner in list(self._owners)), return_exceptions=True)


__all__ = [
    "AsyncBrowserOwner",
    "AsyncBrowserOwnerPool",
    "AsyncBrowserSession",
    "BrowserPoolConfig",
    "DEFAULT_HEADED_CONTEXTS_PER_BROWSER",
    "DEFAULT_HEADLESS_CONTEXTS_PER_BROWSER",
]
