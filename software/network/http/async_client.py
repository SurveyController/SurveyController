"""基于 httpx 的原生异步 HTTP 客户端。"""
from __future__ import annotations

import asyncio
import atexit
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal, overload

import httpx

from software.logging.log_utils import log_suppressed_exception
from software.network.http.client import _CLIENT_LIMITS, _normalize_timeout, _resolve_proxy

_MAX_CLIENTS = 20
_CLIENT_TTL = 300


@dataclass(frozen=True)
class _AsyncClientKey:
    proxy: str | None
    verify: bool | str
    follow_redirects: bool
    trust_env: bool


@dataclass
class _AsyncClientEntry:
    client: httpx.AsyncClient
    last_used: float
    active_requests: int = 0


class _AsyncStreamResponse:
    """给异步流响应补一个兼容接口。"""

    def __init__(self, response: httpx.Response, stream_ctx: Any, release: Any) -> None:
        self._response = response
        self._stream_ctx = stream_ctx
        self._release = release
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
            try:
                await self._release()
            except Exception as exc:
                log_suppressed_exception("_AsyncStreamResponse.aclose release()", exc, level=logging.WARNING)


class _AsyncClientManager:
    """按事件循环和配置缓存 AsyncClient。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._clients: dict[tuple[int, _AsyncClientKey], _AsyncClientEntry] = {}

    def _make_storage_key(self, loop: asyncio.AbstractEventLoop, key: _AsyncClientKey) -> tuple[int, _AsyncClientKey]:
        return id(loop), key

    def _create_client(
        self,
        *,
        proxy: str | None,
        verify: bool | str,
        follow_redirects: bool,
        trust_env: bool,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=None,
            verify=verify,
            proxy=proxy,
            follow_redirects=follow_redirects,
            trust_env=trust_env,
            limits=_CLIENT_LIMITS,
        )

    def _select_stale_clients_locked(self) -> list[httpx.AsyncClient]:
        now = time.time()
        stale_keys = [
            storage_key
            for storage_key, entry in self._clients.items()
            if entry.active_requests <= 0 and (now - entry.last_used) > _CLIENT_TTL
        ]
        stale_clients: list[httpx.AsyncClient] = []
        for storage_key in stale_keys:
            entry = self._clients.pop(storage_key, None)
            if entry is not None:
                stale_clients.append(entry.client)
        return stale_clients

    def _evict_oldest_idle_client_locked(self) -> httpx.AsyncClient | None:
        idle_items = [
            (storage_key, entry)
            for storage_key, entry in self._clients.items()
            if entry.active_requests <= 0
        ]
        if not idle_items:
            return None
        oldest_key, oldest_entry = min(idle_items, key=lambda item: item[1].last_used)
        self._clients.pop(oldest_key, None)
        return oldest_entry.client

    async def _close_clients(self, clients: list[httpx.AsyncClient]) -> None:
        for client in clients:
            try:
                await client.aclose()
            except Exception as exc:
                log_suppressed_exception("_AsyncClientManager._close_clients client.aclose()", exc, level=logging.WARNING)

    def acquire(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        proxy: str | None,
        verify: bool | str,
        follow_redirects: bool,
        trust_env: bool,
    ) -> tuple[tuple[int, _AsyncClientKey], _AsyncClientEntry, list[httpx.AsyncClient]]:
        key = _AsyncClientKey(
            proxy=proxy,
            verify=verify,
            follow_redirects=follow_redirects,
            trust_env=trust_env,
        )
        storage_key = self._make_storage_key(loop, key)
        now = time.time()
        clients_to_close: list[httpx.AsyncClient] = []
        with self._lock:
            clients_to_close.extend(self._select_stale_clients_locked())
            entry = self._clients.get(storage_key)
            if entry is None:
                if len(self._clients) >= _MAX_CLIENTS:
                    evicted = self._evict_oldest_idle_client_locked()
                    if evicted is not None:
                        clients_to_close.append(evicted)
                entry = _AsyncClientEntry(
                    client=self._create_client(
                        proxy=proxy,
                        verify=verify,
                        follow_redirects=follow_redirects,
                        trust_env=trust_env,
                    ),
                    last_used=now,
                )
                self._clients[storage_key] = entry
            entry.last_used = now
            entry.active_requests += 1
        return storage_key, entry, clients_to_close

    async def release(self, storage_key: tuple[int, _AsyncClientKey]) -> None:
        clients_to_close: list[httpx.AsyncClient] = []
        with self._lock:
            entry = self._clients.get(storage_key)
            if entry is None:
                return
            entry.active_requests = max(0, entry.active_requests - 1)
            entry.last_used = time.time()
            clients_to_close.extend(self._select_stale_clients_locked())
        if clients_to_close:
            await self._close_clients(clients_to_close)

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response | _AsyncStreamResponse:
        stream = bool(kwargs.pop("stream", False))
        allow_redirects = bool(kwargs.pop("allow_redirects", True))
        verify = kwargs.pop("verify", True)
        proxies = kwargs.pop("proxies", None)
        proxy, trust_env = _resolve_proxy(proxies, url)
        timeout = _normalize_timeout(kwargs.pop("timeout", None))
        loop = asyncio.get_running_loop()
        storage_key, entry, clients_to_close = self.acquire(
            loop=loop,
            proxy=proxy,
            verify=verify,
            follow_redirects=allow_redirects,
            trust_env=trust_env,
        )
        if clients_to_close:
            await self._close_clients(clients_to_close)
        if stream:
            stream_ctx = entry.client.stream(method, url, timeout=timeout, **kwargs)
            try:
                response = await stream_ctx.__aenter__()
            except Exception:
                await self.release(storage_key)
                raise
            return _AsyncStreamResponse(response, stream_ctx, lambda: self.release(storage_key))
        try:
            return await entry.client.request(method, url, timeout=timeout, **kwargs)
        finally:
            await self.release(storage_key)

    async def close(self) -> None:
        with self._lock:
            clients = [entry.client for entry in self._clients.values()]
            self._clients.clear()
        await self._close_clients(clients)


_client_manager = _AsyncClientManager()


def close() -> None:
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_client_manager.close())
            return
        loop.create_task(_client_manager.close())
    except Exception as exc:
        log_suppressed_exception("async_http_client.close _client_manager.close()", exc, level=logging.WARNING)


atexit.register(close)


@overload
async def request(method: str, url: str, *, stream: Literal[True], **kwargs: Any) -> _AsyncStreamResponse:
    ...


@overload
async def request(method: str, url: str, *, stream: Literal[False] = False, **kwargs: Any) -> httpx.Response:
    ...


async def request(method: str, url: str, **kwargs: Any) -> httpx.Response | _AsyncStreamResponse:
    return await _client_manager.request(method, url, **kwargs)


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
    "close",
    "delete",
    "get",
    "post",
    "put",
    "request",
]
