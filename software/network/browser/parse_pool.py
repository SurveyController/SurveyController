"""题目解析专用浏览器池。"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Iterator, Optional

from software.app.config import BROWSER_PREFERENCE
from software.network.browser.owner_pool import BrowserOwnerPool, BrowserPoolConfig
from software.network.browser.session import BrowserDriver

_PARSE_POOL_HEADLESS = True
_PARSE_POOL_MAX_CONCURRENCY = 2
_POOL_LOCK = threading.RLock()
_POOL: Optional[BrowserOwnerPool] = None


def _build_parse_pool() -> BrowserOwnerPool:
    config = BrowserPoolConfig.from_concurrency(
        _PARSE_POOL_MAX_CONCURRENCY,
        headless=_PARSE_POOL_HEADLESS,
        contexts_per_owner=_PARSE_POOL_MAX_CONCURRENCY,
    )
    return BrowserOwnerPool(
        config=config,
        headless=_PARSE_POOL_HEADLESS,
        prefer_browsers=list(BROWSER_PREFERENCE),
        window_positions=[],
    )


def _get_parse_pool() -> BrowserOwnerPool:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = _build_parse_pool()
        return _POOL


@contextmanager
def acquire_parse_browser_session(
    *,
    proxy_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Iterator[BrowserDriver]:
    pool = _get_parse_pool()
    lease = pool.acquire_owner_lease(wait=True)
    if lease is None:
        raise RuntimeError("解析浏览器池当前不可用")

    driver: BrowserDriver | None = None
    try:
        driver = lease.owner.open_session(
            proxy_address=proxy_address,
            user_agent=user_agent,
            lease=lease,
        )
        if driver is None:
            raise RuntimeError("解析浏览器会话创建失败")
        yield driver
    finally:
        if driver is not None:
            try:
                if driver.mark_cleanup_done():
                    driver.quit()
            except Exception as exc:
                logging.info("关闭解析浏览器会话失败：%s", exc, exc_info=True)
        else:
            try:
                lease.release()
            except Exception as exc:
                logging.info("释放解析浏览器池租约失败：%s", exc, exc_info=True)


__all__ = [
    "acquire_parse_browser_session",
]
