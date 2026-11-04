from __future__ import annotations

from typing import Any, Optional, Tuple
from urllib.parse import urlsplit

import httpx

CLIENT_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
MAX_CLIENTS = 20
CLIENT_TTL_SECONDS = 300


def resolve_proxy(proxies: Any, url: str) -> Tuple[Optional[str], bool]:
    if proxies is None:
        return None, True
    if proxies == {}:
        return None, False
    if isinstance(proxies, str):
        return proxies, False
    if isinstance(proxies, dict):
        scheme = urlsplit(url).scheme.lower()
        http_proxy = proxies.get("http") or proxies.get("http://")
        https_proxy = proxies.get("https") or proxies.get("https://")
        if not http_proxy and not https_proxy:
            return None, False
        if scheme == "https":
            return str(https_proxy or http_proxy), False
        return str(http_proxy or https_proxy), False
    return None, False


def normalize_timeout(timeout: Any) -> Any:
    if timeout is None:
        return None
    if isinstance(timeout, (int, float)):
        return float(timeout)
    if isinstance(timeout, tuple):
        if len(timeout) == 2:
            connect, read = timeout
            connect_val = float(connect) if connect is not None else None
            read_val = float(read) if read is not None else None
            return httpx.Timeout(
                connect=connect_val, read=read_val, write=read_val, pool=connect_val
            )
        if len(timeout) == 4:
            connect, read, write, pool = timeout
            return httpx.Timeout(
                connect=float(connect) if connect is not None else None,
                read=float(read) if read is not None else None,
                write=float(write) if write is not None else None,
                pool=float(pool) if pool is not None else None,
            )
    return timeout


__all__ = [
    "CLIENT_LIMITS",
    "CLIENT_TTL_SECONDS",
    "MAX_CLIENTS",
    "normalize_timeout",
    "resolve_proxy",
]
