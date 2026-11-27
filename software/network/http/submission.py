from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

_SUBMISSION_TIMEOUT = httpx.Timeout(30, read=45)
_CONNECTION_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError, httpx.PoolTimeout)


class SubmissionConnectionError(httpx.TransportError):
    def __init__(self, cause: httpx.TransportError) -> None:
        detail = str(cause)
        super().__init__(f"{type(cause).__name__}: {detail}" if detail else type(cause).__name__)
        self.pool_timeout = isinstance(cause, httpx.PoolTimeout)


async def post_submission(
    post: Callable[..., Awaitable[httpx.Response]], url: str, **kwargs: Any
) -> httpx.Response:
    request_started = False
    proxy_connect_started = False

    async def trace(event: str, info: dict[str, Any]) -> None:
        nonlocal request_started, proxy_connect_started
        if event.endswith(".send_request_headers.started"):
            if info["request"].method == b"CONNECT":
                proxy_connect_started = True
            else:
                request_started = True

    try:
        return await post(url, timeout=_SUBMISSION_TIMEOUT, extensions={"trace": trace}, **kwargs)
    except httpx.TransportError as exc:
        if not request_started and (proxy_connect_started or isinstance(exc, _CONNECTION_ERRORS)):
            raise SubmissionConnectionError(exc) from exc
        raise
