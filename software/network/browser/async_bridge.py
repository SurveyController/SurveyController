"""异步 Playwright 对象的同步桥接层。"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from concurrent.futures import Future
from typing import Any, Callable, Dict, Optional

from software.logging.log_utils import log_suppressed_exception
from software.network.browser.options import _is_browser_disconnected_error

_PRIMITIVE_TYPES = (str, int, float, bool, bytes, type(None))


class AsyncBridgeLoopThread:
    """在专属线程里运行 asyncio 循环，并为同步调用方提供阻塞桥接。"""

    def __init__(self, *, name: str):
        self._name = str(name or "AsyncBridgeLoop")
        self._loop_ready = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread_id: Optional[int] = None
        self._closed = False
        self._route_wrappers: Dict[tuple[int, int], Callable[..., Any]] = {}
        self._start_stop_lock = threading.Lock()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        self.start()
        assert self._loop is not None
        return self._loop

    @property
    def thread_id(self) -> int:
        self.start()
        return int(self._thread_id or 0)

    def start(self) -> None:
        if self._thread is not None:
            return
        with self._start_stop_lock:
            if self._thread is not None:
                return
            self._loop_ready.clear()

            def _runner() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                self._thread_id = threading.get_ident()
                self._loop_ready.set()
                try:
                    loop.run_forever()
                finally:
                    pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                    for task in pending:
                        task.cancel()
                    if pending:
                        try:
                            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                        except Exception:
                            logging.debug("停止桥接循环时等待挂起任务失败", exc_info=True)
                    try:
                        loop.run_until_complete(loop.shutdown_asyncgens())
                    except Exception:
                        logging.debug("停止桥接循环时关闭 async generators 失败", exc_info=True)
                    loop.close()

            self._thread = threading.Thread(target=_runner, daemon=True, name=self._name)
            self._thread.start()
        self._loop_ready.wait()

    def run_coroutine(self, coro: Any) -> Any:
        if self._closed:
            if inspect.iscoroutine(coro):
                coro.close()
            raise RuntimeError(f"{self._name} 已关闭")
        try:
            loop = self.loop
            future: Future[Any] = asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception:
            if inspect.iscoroutine(coro):
                coro.close()
            raise
        return future.result()

    def call_soon(self, callback: Callable[..., Any], *args: Any) -> None:
        if self._closed:
            return
        self.loop.call_soon_threadsafe(callback, *args)

    def stop(self) -> None:
        with self._start_stop_lock:
            if self._closed:
                return
            self._closed = True
            loop = self._loop
            thread = self._thread
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=5)
        with self._start_stop_lock:
            self._thread = None
            self._loop = None
            self._thread_id = None
            self._route_wrappers.clear()

    def _wrap_value(self, value: Any, owner: Optional[Any] = None) -> Any:
        if isinstance(value, _PRIMITIVE_TYPES):
            return value
        if isinstance(value, list):
            return [self._wrap_value(item, owner=owner) for item in value]
        if isinstance(value, tuple):
            return tuple(self._wrap_value(item, owner=owner) for item in value)
        if isinstance(value, set):
            return {self._wrap_value(item, owner=owner) for item in value}
        if isinstance(value, dict):
            return {key: self._wrap_value(item, owner=owner) for key, item in value.items()}
        return AsyncObjectProxy(self, value, owner=owner)

    def _unwrap_value(self, value: Any) -> Any:
        if isinstance(value, AsyncObjectProxy):
            return value._target
        if isinstance(value, list):
            return [self._unwrap_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._unwrap_value(item) for item in value)
        if isinstance(value, set):
            return {self._unwrap_value(item) for item in value}
        if isinstance(value, dict):
            return {key: self._unwrap_value(item) for key, item in value.items()}
        return value

    def _route_wrapper_key(self, target: Any, callback: Callable[..., Any]) -> tuple[int, int]:
        return (id(target), id(callback))

    def _resolve_route_wrapper(
        self,
        target: Any,
        callback: Callable[..., Any],
        owner: Optional[Any],
    ) -> Callable[..., Any]:
        key = self._route_wrapper_key(target, callback)
        existing = self._route_wrappers.get(key)
        if existing is not None:
            return existing

        async def _wrapped(route: Any, request: Any) -> None:
            route_proxy = AsyncObjectProxy(self, route, owner=owner)
            request_proxy = AsyncObjectProxy(self, request, owner=owner)
            await asyncio.to_thread(callback, route_proxy, request_proxy)

        self._route_wrappers[key] = _wrapped
        return _wrapped

    async def _invoke_attr(
        self,
        target: Any,
        attr_name: str,
        *,
        owner: Optional[Any],
        args: tuple[Any, ...] = (),
        kwargs: Optional[dict[str, Any]] = None,
        call: bool,
    ) -> Any:
        kwargs = dict(kwargs or {})
        try:
            attr = getattr(target, attr_name)
        except Exception as exc:
            if owner is not None and _is_browser_disconnected_error(exc):
                owner.mark_broken()
            raise
        if not call:
            return attr

        if attr_name == "route" and len(args) >= 2 and callable(args[1]):
            callback = args[1]
            args = (args[0], self._resolve_route_wrapper(target, callback, owner), *args[2:])
        elif attr_name == "unroute" and len(args) >= 2 and callable(args[1]):
            key = self._route_wrapper_key(target, args[1])
            wrapped = self._route_wrappers.get(key)
            if wrapped is not None:
                args = (args[0], wrapped, *args[2:])

        raw_args = tuple(self._unwrap_value(arg) for arg in args)
        raw_kwargs = {key: self._unwrap_value(value) for key, value in kwargs.items()}
        try:
            result = attr(*raw_args, **raw_kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception as exc:
            if owner is not None and _is_browser_disconnected_error(exc):
                owner.mark_broken()
            raise

    def get_attr(self, target: Any, attr_name: str, *, owner: Optional[Any]) -> Any:
        return self.run_coroutine(self._invoke_attr(target, attr_name, owner=owner, call=False))

    def call_attr(
        self,
        target: Any,
        attr_name: str,
        *args: Any,
        owner: Optional[Any],
        **kwargs: Any,
    ) -> Any:
        return self.run_coroutine(
            self._invoke_attr(
                target,
                attr_name,
                owner=owner,
                args=args,
                kwargs=kwargs,
                call=True,
            )
        )


class AsyncMethodProxy:
    """桥接对象上的可调用属性。"""

    def __init__(self, bridge: AsyncBridgeLoopThread, target: Any, attr_name: str, *, owner: Optional[Any]):
        self._bridge = bridge
        self._target = target
        self._attr_name = attr_name
        self._owner = owner

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        result = self._bridge.call_attr(
            self._target,
            self._attr_name,
            *args,
            owner=self._owner,
            **kwargs,
        )
        return self._bridge._wrap_value(result, owner=self._owner)

    def __repr__(self) -> str:
        return f"<AsyncMethodProxy {self._attr_name}>"


class AsyncObjectProxy:
    """同步风格访问异步 Playwright 对象。"""

    def __init__(self, bridge: AsyncBridgeLoopThread, target: Any, *, owner: Optional[Any]):
        object.__setattr__(self, "_bridge", bridge)
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_owner", owner)

    def __getattr__(self, item: str) -> Any:
        value = self._bridge.get_attr(self._target, item, owner=self._owner)
        if callable(value):
            return AsyncMethodProxy(self._bridge, self._target, item, owner=self._owner)
        return self._bridge._wrap_value(value, owner=self._owner)

    def __repr__(self) -> str:
        try:
            cls_name = type(self._target).__name__
        except Exception:
            cls_name = "AsyncTarget"
        return f"<AsyncObjectProxy {cls_name}>"


def close_bridge_loop_safely(loop_thread: Optional[AsyncBridgeLoopThread]) -> None:
    if loop_thread is None:
        return
    try:
        loop_thread.stop()
    except Exception as exc:
        log_suppressed_exception("async_bridge.close_bridge_loop_safely", exc, level=logging.WARNING)


__all__ = [
    "AsyncBridgeLoopThread",
    "AsyncMethodProxy",
    "AsyncObjectProxy",
    "close_bridge_loop_safely",
]
