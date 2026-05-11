"""题目解析专用异步浏览器池。"""

from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, cast

from software.app.config import BROWSER_PREFERENCE
from software.network.browser.async_owner_pool import AsyncBrowserOwnerPool
from software.network.browser.pool_config import BrowserPoolConfig
from software.network.browser.runtime_async import BrowserDriver as AsyncBrowserDriver

_PARSE_POOL_HEADLESS = True
_PARSE_POOL_MAX_CONCURRENCY = 2
_POOL_LOCK = threading.RLock()
_POOLS: dict[int, AsyncBrowserOwnerPool] = {}


def _build_parse_pool() -> AsyncBrowserOwnerPool:
    config = BrowserPoolConfig.from_concurrency(
        _PARSE_POOL_MAX_CONCURRENCY,
        headless=_PARSE_POOL_HEADLESS,
        contexts_per_owner=_PARSE_POOL_MAX_CONCURRENCY,
    )
    return AsyncBrowserOwnerPool(
        config=config,
        headless=_PARSE_POOL_HEADLESS,
        prefer_browsers=list(BROWSER_PREFERENCE),
        window_positions=[],
    )


def _get_parse_pool() -> AsyncBrowserOwnerPool:
    loop_key = id(asyncio.get_running_loop())
    with _POOL_LOCK:
        pool = _POOLS.get(loop_key)
        if pool is None:
            pool = _build_parse_pool()
            _POOLS[loop_key] = pool
        return pool


@asynccontextmanager
async def acquire_parse_browser_session(
    *,
    proxy_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> AsyncIterator[AsyncBrowserDriver]:
    pool = _get_parse_pool()
    driver: AsyncBrowserDriver | None = None
    session = None
    try:
        session = await pool.open_session(
            proxy_address=proxy_address,
            user_agent=user_agent,
        )
        driver = cast(AsyncBrowserDriver | None, session.driver if session is not None else None)
        if driver is None:
            raise RuntimeError("解析浏览器会话创建失败")
        yield driver
    finally:
        if driver is not None:
            try:
                if driver.mark_cleanup_done():
                    await driver.aclose()
            except Exception as exc:
                logging.info("关闭解析浏览器会话失败：%s", exc, exc_info=True)


__all__ = [
    "acquire_parse_browser_session",
]
