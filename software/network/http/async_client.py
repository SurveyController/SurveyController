"""基于 httpx 的原生异步 HTTP 客户端。"""
from __future__ import annotations

from typing import Any, Literal, overload

import httpx

from software.network.http.client import _CLIENT_LIMITS, _normalize_timeout, _resolve_proxy


class _AsyncStreamResponse:
    """给异步流响应补一个兼容接口。"""

    def __init__(self, response: httpx.Response, stream_ctx: Any, client: httpx.AsyncClient) -> None:
        self._response = response
        self._stream_ctx = stream_ctx
        self._client = client
        self._closed = False

    @property
    def status_code(self) -> int:
        return self._response.status_code

    @property
    def headers(self) -> httpx.Headers:
        return self._response.headers

    @property
    def text(self) -> str:
        return self._response.text

    @property
    def content(self) -> bytes:
        return self._response.content

    def json(self) -> Any:
        return self._response.json()

    def raise_for_status(self) -> None:
        self._response.raise_for_status()

    async def aiter_content(self, chunk_size: int = 8192):
        try:
            async for chunk in self._response.aiter_bytes(chunk_size=max(int(chunk_size), 1)):
                if chunk:
                    yield chunk
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._stream_ctx.__aexit__(None, None, None)
        finally:
            await self._client.aclose()


@overload
async def request(method: str, url: str, *, stream: Literal[True], **kwargs: Any) -> _AsyncStreamResponse:
    ...


@overload
async def request(method: str, url: str, *, stream: Literal[False] = False, **kwargs: Any) -> httpx.Response:
    ...


async def request(method: str, url: str, **kwargs: Any) -> httpx.Response | _AsyncStreamResponse:
    stream = bool(kwargs.pop("stream", False))
    allow_redirects = bool(kwargs.pop("allow_redirects", True))
    verify = kwargs.pop("verify", True)
    proxies = kwargs.pop("proxies", None)
    proxy, trust_env = _resolve_proxy(proxies, url)
    timeout = _normalize_timeout(kwargs.pop("timeout", None))
    client = httpx.AsyncClient(
        timeout=None,
        verify=verify,
        proxy=proxy,
        follow_redirects=allow_redirects,
        trust_env=trust_env,
        limits=_CLIENT_LIMITS,
    )
    if stream:
        stream_ctx = client.stream(method, url, timeout=timeout, **kwargs)
        try:
            response = await stream_ctx.__aenter__()
        except Exception:
            await client.aclose()
            raise
        return _AsyncStreamResponse(response, stream_ctx, client)
    try:
        return await client.request(method, url, timeout=timeout, **kwargs)
    finally:
        await client.aclose()


@overload
async def get(url: str, *, stream: Literal[True], **kwargs: Any) -> _AsyncStreamResponse:
    ...


@overload
async def get(url: str, *, stream: Literal[False] = False, **kwargs: Any) -> httpx.Response:
    ...


async def get(url: str, **kwargs: Any) -> httpx.Response | _AsyncStreamResponse:
    return await request("GET", url, **kwargs)


@overload
async def post(url: str, *, stream: Literal[True], **kwargs: Any) -> _AsyncStreamResponse:
    ...


@overload
async def post(url: str, *, stream: Literal[False] = False, **kwargs: Any) -> httpx.Response:
    ...


async def post(url: str, **kwargs: Any) -> httpx.Response | _AsyncStreamResponse:
    return await request("POST", url, **kwargs)


@overload
async def put(url: str, *, stream: Literal[True], **kwargs: Any) -> _AsyncStreamResponse:
    ...


@overload
async def put(url: str, *, stream: Literal[False] = False, **kwargs: Any) -> httpx.Response:
    ...


async def put(url: str, **kwargs: Any) -> httpx.Response | _AsyncStreamResponse:
    return await request("PUT", url, **kwargs)


@overload
async def delete(url: str, *, stream: Literal[True], **kwargs: Any) -> _AsyncStreamResponse:
    ...


@overload
async def delete(url: str, *, stream: Literal[False] = False, **kwargs: Any) -> httpx.Response:
    ...


async def delete(url: str, **kwargs: Any) -> httpx.Response | _AsyncStreamResponse:
    return await request("DELETE", url, **kwargs)


__all__ = [
    "delete",
    "get",
    "post",
    "put",
    "request",
]
