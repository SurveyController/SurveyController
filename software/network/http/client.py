from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Literal, Optional, Union, cast, overload

import httpx
from packaging.version import InvalidVersion, Version

from software.logging.log_utils import log_suppressed_exception
from software.network.http.client_policy import (
    CLIENT_LIMITS as _CLIENT_LIMITS,
    CLIENT_TTL_SECONDS as _CLIENT_TTL,
    MAX_CLIENTS as _MAX_CLIENTS,
    normalize_timeout as _normalize_timeout,
    resolve_proxy as _resolve_proxy,
)


_MIN_HTTPX_VERSION = Version("0.27.0")


def _ensure_supported_httpx() -> None:
    raw_version = getattr(httpx, "__version__", "")
    try:
        current_version = Version(raw_version)
    except InvalidVersion as exc:
        raise RuntimeError(
            f"检测到无法识别的 httpx 版本：{raw_version!r}。请在项目根目录执行 uv sync，重新装回锁定依赖。"
        ) from exc
    if current_version < _MIN_HTTPX_VERSION:
        raise RuntimeError(
            f"当前 httpx 版本过旧：{current_version}。本项目需要 httpx>={_MIN_HTTPX_VERSION},<1。"
            "请在项目根目录执行：uv sync"
        )


_ensure_supported_httpx()


_PREWARM_LOCK = threading.Lock()
_PREWARMED = False


RequestException = httpx.HTTPError
TransportError = httpx.TransportError
Timeout = httpx.TimeoutException
ConnectTimeout = httpx.ConnectTimeout
ReadTimeout = httpx.ReadTimeout
ConnectionError = httpx.ConnectError
ProxyError = httpx.ProxyError
RemoteProtocolError = httpx.RemoteProtocolError
HTTPError = httpx.HTTPStatusError


@dataclass(frozen=True)
class _ClientKey:
    proxy: Optional[str]
    verify: Union[bool, str]
    follow_redirects: bool
    trust_env: bool


@dataclass
class _ClientEntry:
    client: httpx.Client
    last_used: float
    active_requests: int = 0


class _StreamResponse:
    def __init__(
        self,
        response: httpx.Response,
        stream_ctx: Any,
        release: Any,
    ):
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

    def iter_content(self, chunk_size: int = 8192) -> Iterator[bytes]:
        try:
            for chunk in self._response.iter_bytes(chunk_size=max(int(chunk_size), 1)):
                if chunk:
                    yield chunk
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._stream_ctx.__exit__(None, None, None)
        except Exception as exc:
            log_suppressed_exception(
                "_StreamResponse.close stream_ctx.__exit__", exc, level=logging.WARNING
            )
        finally:
            try:
                self._release()
            except Exception as exc:
                log_suppressed_exception(
                    "_StreamResponse.close release()", exc, level=logging.WARNING
                )

    def __del__(self) -> None:
        self.close()


class _SyncClientManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._clients: Dict[_ClientKey, _ClientEntry] = {}

    def _create_client(
        self,
        *,
        proxy: Optional[str],
        verify: Union[bool, str],
        follow_redirects: bool,
        trust_env: bool,
    ) -> httpx.Client:
        return httpx.Client(
            timeout=None,
            verify=verify,
            proxy=proxy,
            follow_redirects=follow_redirects,
            trust_env=trust_env,
            limits=_CLIENT_LIMITS,
        )

    def _cleanup_stale_clients_locked(self) -> list[httpx.Client]:
        now = time.time()
        stale_keys = [
            key
            for key, entry in self._clients.items()
            if entry.active_requests <= 0 and (now - entry.last_used) > _CLIENT_TTL
        ]
        closed: list[httpx.Client] = []
        for key in stale_keys:
            entry = self._clients.pop(key, None)
            if entry is not None:
                closed.append(entry.client)
        return closed

    def _evict_oldest_idle_client_locked(self) -> Optional[httpx.Client]:
        idle_items = [
            (key, entry) for key, entry in self._clients.items() if entry.active_requests <= 0
        ]
        if not idle_items:
            return None
        oldest_key, oldest_entry = min(idle_items, key=lambda item: item[1].last_used)
        self._clients.pop(oldest_key, None)
        return oldest_entry.client

    def _close_clients(self, clients: list[httpx.Client]) -> None:
        for client in clients:
            try:
                client.close()
            except Exception as exc:
                log_suppressed_exception(
                    "_SyncClientManager._close_clients client.close()", exc, level=logging.WARNING
                )

    def acquire(
        self,
        *,
        proxy: Optional[str],
        verify: Union[bool, str],
        follow_redirects: bool,
        trust_env: bool,
    ) -> tuple[_ClientKey, _ClientEntry]:
        key = _ClientKey(
            proxy=proxy,
            verify=verify,
            follow_redirects=follow_redirects,
            trust_env=trust_env,
        )

        clients_to_close: list[httpx.Client] = []
        now = time.time()
        with self._lock:
            clients_to_close.extend(self._cleanup_stale_clients_locked())

            entry = self._clients.get(key)
            if entry is None:
                if len(self._clients) >= _MAX_CLIENTS:
                    evicted = self._evict_oldest_idle_client_locked()
                    if evicted is not None:
                        clients_to_close.append(evicted)
                entry = _ClientEntry(
                    client=self._create_client(
                        proxy=proxy,
                        verify=verify,
                        follow_redirects=follow_redirects,
                        trust_env=trust_env,
                    ),
                    last_used=now,
                )
                self._clients[key] = entry

            entry.last_used = now
            entry.active_requests += 1

        self._close_clients(clients_to_close)
        return key, entry

    def release(self, key: _ClientKey) -> None:
        with self._lock:
            entry = self._clients.get(key)
            if entry is None:
                return
            entry.active_requests = max(0, entry.active_requests - 1)
            entry.last_used = time.time()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Any = None,
        content: Any = None,
        data: Any = None,
        headers: Any = None,
        cookies: Any = None,
        files: Any = None,
        auth: Any = None,
        timeout: Any = None,
        allow_redirects: bool = True,
        proxies: Any = None,
        stream: bool = False,
        verify: Union[bool, str] = True,
        json: Any = None,
    ) -> Union[httpx.Response, _StreamResponse]:
        proxy, trust_env = _resolve_proxy(proxies, url)
        key, entry = self.acquire(
            proxy=proxy,
            verify=verify,
            follow_redirects=allow_redirects,
            trust_env=trust_env,
        )
        normalized_timeout = _normalize_timeout(timeout)

        try:
            if stream:
                stream_ctx = entry.client.stream(
                    method=method,
                    url=url,
                    params=params,
                    content=content,
                    data=data,
                    headers=headers,
                    cookies=cookies,
                    files=files,
                    auth=auth,
                    json=json,
                    timeout=normalized_timeout,
                )
                response = stream_ctx.__enter__()
                return _StreamResponse(response, stream_ctx, lambda: self.release(key))

            response = entry.client.request(
                method=method,
                url=url,
                params=params,
                content=content,
                data=data,
                headers=headers,
                cookies=cookies,
                files=files,
                auth=auth,
                json=json,
                timeout=normalized_timeout,
            )
            self.release(key)
            return response
        except Exception:
            self.release(key)
            raise

    def close(self) -> None:
        with self._lock:
            clients = [entry.client for entry in self._clients.values()]
            self._clients.clear()
        self._close_clients(clients)


_client_manager = _SyncClientManager()


def prewarm() -> None:

    global _PREWARMED

    if _PREWARMED:
        return

    with _PREWARM_LOCK:
        if _PREWARMED:
            return
        temp_client: httpx.Client | None = None
        try:
            temp_client = httpx.Client(
                timeout=None,
                limits=_CLIENT_LIMITS,
                verify=False,
                trust_env=False,
            )
            _PREWARMED = True
        except Exception as exc:
            log_suppressed_exception(
                "http_client.prewarm httpx.Client()", exc, level=logging.WARNING
            )
        finally:
            if temp_client is not None:
                try:
                    temp_client.close()
                except Exception as exc:
                    log_suppressed_exception(
                        "http_client.prewarm temp_client.close()", exc, level=logging.WARNING
                    )


def close() -> None:

    try:
        _client_manager.close()
    except Exception as exc:
        log_suppressed_exception(
            "http_client.close _client_manager.close()", exc, level=logging.WARNING
        )


@overload
def request(method: str, url: str, *, stream: Literal[True], **kwargs: Any) -> _StreamResponse: ...


@overload
def request(
    method: str, url: str, *, stream: Literal[False] = False, **kwargs: Any
) -> httpx.Response: ...


def request(method: str, url: str, **kwargs: Any) -> httpx.Response | _StreamResponse:
    return _client_manager.request(method, url, **kwargs)


@overload
def get(url: str, *, stream: Literal[True], **kwargs: Any) -> _StreamResponse: ...


@overload
def get(url: str, *, stream: Literal[False] = False, **kwargs: Any) -> httpx.Response: ...


def get(url: str, **kwargs: Any) -> httpx.Response | _StreamResponse:
    return cast(httpx.Response | _StreamResponse, request("GET", url, **kwargs))


@overload
def post(url: str, *, stream: Literal[True], **kwargs: Any) -> _StreamResponse: ...


@overload
def post(url: str, *, stream: Literal[False] = False, **kwargs: Any) -> httpx.Response: ...


def post(url: str, **kwargs: Any) -> httpx.Response | _StreamResponse:
    return cast(httpx.Response | _StreamResponse, request("POST", url, **kwargs))


@overload
def put(url: str, *, stream: Literal[True], **kwargs: Any) -> _StreamResponse: ...


@overload
def put(url: str, *, stream: Literal[False] = False, **kwargs: Any) -> httpx.Response: ...


def put(url: str, **kwargs: Any) -> httpx.Response | _StreamResponse:
    return cast(httpx.Response | _StreamResponse, request("PUT", url, **kwargs))


@overload
def delete(url: str, *, stream: Literal[True], **kwargs: Any) -> _StreamResponse: ...


@overload
def delete(url: str, *, stream: Literal[False] = False, **kwargs: Any) -> httpx.Response: ...


def delete(url: str, **kwargs: Any) -> httpx.Response | _StreamResponse:
    return cast(httpx.Response | _StreamResponse, request("DELETE", url, **kwargs))
