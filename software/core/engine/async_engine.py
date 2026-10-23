from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from typing import Any, Callable, Coroutine, Optional

from surveycore.core.engine.async_events import AsyncRunContext
from software.core.engine.async_runtime_loop import AsyncSlotRunner
from software.core.engine.engine_state import EngineState
from software.core.engine.task_registry import TaskRegistry
from software.network.http.async_client import aclose_for_loop
from software.network.http.client import close as close_sync_http_clients
from surveycore.core.engine.async_scheduler import AsyncScheduler
from surveycore.core.engine.async_status_bus import AsyncStatusBus
from software.core.engine.runtime_control_port import RuntimeControlPort, on_random_ip_loading_changed
from software.core.task import ExecutionConfig, ExecutionState
from software.network.proxy.api import fetch_proxy_batch_async
from software.network.session_policy import (
    _acquire_proxy_fetch_lock_async,
    merge_prefetched_proxy_leases,
    release_proxy_fetch_lock,
    resolve_proxy_prefetch_request_count,
    should_continue_proxy_prefetch,
    wait_for_proxy_prefetch_cycle,
)
from software.providers.registry import parse_survey
from software.providers.contracts import ProviderParseResult


def _format_seconds_range(value: Any) -> str:
    try:
        start, end = value
        return f"{int(start)}-{int(end)}秒"
    except Exception:
        return "未知"


def _format_proxy_source(source: Any) -> str:
    normalized = str(source or "default").strip().lower()
    labels = {
        "default": "默认",
        "benefit": "限时福利",
        "custom": "自定义",
    }
    return labels.get(normalized, normalized or "默认")


class AsyncRuntimeEngine:
    

    def __init__(
        self,
        *,
        status_bus: Optional[AsyncStatusBus] = None,
        app_version: str = "",
        submission_report_enabled: Callable[[], bool] | None = None,
    ) -> None:
        self._status_bus = status_bus or AsyncStatusBus()
        self._app_version = str(app_version or "")
        self._submission_report_enabled = submission_report_enabled or (lambda: True)
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_ready = threading.Event()
        self._start_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._run_future: Optional[concurrent.futures.Future[Any]] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._pause_event: Optional[asyncio.Event] = None
        self._engine_state = EngineState.OPEN
        self._ui_task_registry: TaskRegistry | None = None
        self._state: Optional[ExecutionState] = None
        self._loop_start_error: BaseException | None = None

    @property
    def thread(self) -> Optional[threading.Thread]:
        return self._thread

    @property
    def engine_state(self) -> EngineState:
        with self._lifecycle_lock:
            return self._engine_state

    def start(self) -> None:
        wait_for_existing_loop = False
        with self._start_lock:
            with self._lifecycle_lock:
                if self._engine_state is EngineState.RUNNING:
                    if self._thread is None or not self._thread.is_alive():
                        raise RuntimeError("AsyncRuntimeEngine 运行线程已退出")
                    wait_for_existing_loop = True
                elif self._engine_state is not EngineState.OPEN:
                    raise RuntimeError(f"AsyncRuntimeEngine 已关闭或正在关闭：{self._engine_state.value}")
                elif self._thread is not None and self._thread.is_alive():
                    return

            if wait_for_existing_loop:
                self._loop_ready.wait()
                if self._loop_start_error is not None:
                    error = self._loop_start_error
                    raise RuntimeError("AsyncRuntimeEngine loop 启动失败") from error
                return

            self._loop_ready.clear()
            self._loop_start_error = None

            def _runner() -> None:
                loop: asyncio.AbstractEventLoop | None = None
                try:
                    loop = asyncio.new_event_loop()
                    self._loop = loop
                    asyncio.set_event_loop(loop)
                    self._ui_task_registry = TaskRegistry()
                    self._loop_ready.set()
                    loop.run_forever()
                except BaseException as exc:
                    self._loop_start_error = exc
                    logging.exception("AsyncRuntimeEngine loop 启动失败")
                finally:
                    self._loop_ready.set()
                    if loop is not None:
                        try:
                            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                            for task in pending:
                                task.cancel()
                            if pending:
                                _, pending = loop.run_until_complete(asyncio.wait(pending, timeout=1.0))
                            if pending:
                                names = ", ".join(sorted(task.get_name() for task in pending))
                                logging.warning("事件循环关闭后仍有任务未退出：%s", names)
                        except Exception:
                            logging.warning("取消事件循环后台任务失败", exc_info=True)
                        try:
                            loop.run_until_complete(loop.shutdown_asyncgens())
                        except Exception:
                            logging.warning("关闭事件循环异步生成器失败", exc_info=True)
                        try:
                            loop.run_until_complete(aclose_for_loop(loop))
                        except Exception:
                            logging.warning("回收事件循环 HTTP 客户端失败", exc_info=True)
                        finally:
                            try:
                                loop.close()
                            finally:
                                self._mark_stopped(loop)
                    else:
                        with self._lifecycle_lock:
                            self._thread = None
                            self._engine_state = EngineState.OPEN

            thread = threading.Thread(target=_runner, daemon=True, name="AsyncRuntimeEngine")
            with self._lifecycle_lock:
                self._thread = thread
                self._engine_state = EngineState.RUNNING
            try:
                thread.start()
            except Exception:
                with self._lifecycle_lock:
                    if self._thread is thread:
                        self._thread = None
                        self._engine_state = EngineState.OPEN
                raise
        self._loop_ready.wait()
        if self._loop_start_error is not None:
            error = self._loop_start_error
            raise RuntimeError("AsyncRuntimeEngine loop 启动失败") from error

    def _mark_stopped(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        with self._lifecycle_lock:
            if (
                loop is None
                or self._loop is loop
                or self._thread is threading.current_thread()
            ):
                self._loop = None
                self._thread = None
                self._engine_state = EngineState.CLOSED

    def _submit(self, coro: Any) -> concurrent.futures.Future[Any]:
        try:
            self.start()
            with self._lifecycle_lock:
                if self._engine_state in {EngineState.STOPPING, EngineState.CLOSED}:
                    raise RuntimeError(f"AsyncRuntimeEngine 不接受新任务：{self._engine_state.value}")
                loop = self._loop
                if loop is None or loop.is_closed():
                    raise RuntimeError("AsyncRuntimeEngine loop 未启动")
                if self._engine_state is not EngineState.RUNNING:
                    raise RuntimeError(f"AsyncRuntimeEngine 不接受新任务：{self._engine_state.value}")
                return asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception:
            close = getattr(coro, "close", None)
            if callable(close):
                close()
            raise

    def start_run(
        self,
        *,
        config: ExecutionConfig,
        state: ExecutionState,
        runtime_bridge: RuntimeControlPort | None = None,
    ) -> concurrent.futures.Future[Any]:
        if self._run_future is not None and not self._run_future.done():
            raise RuntimeError("任务已在运行中")
        future = self._submit(self._run(config=config, state=state, runtime_bridge=runtime_bridge))
        self._run_future = future
        return future

    async def _run(
        self,
        *,
        config: ExecutionConfig,
        state: ExecutionState,
        runtime_bridge: RuntimeControlPort | None = None,
    ) -> None:
        self._stop_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._state = state
        state.stop_event.clear()
        worker_count = max(1, int(config.num_threads or 1))
        state.ensure_worker_threads(worker_count, prefix="Slot")
        scheduler = AsyncScheduler(concurrency=worker_count)
        task_registry = TaskRegistry()
        run_context = AsyncRunContext(
            state=state,
            stop_event=self._stop_event,
            pause_event=self._pause_event,
            status_sink=self._status_bus.emit,
        )
        logging.info(
            "任务启动：版本=%s 问卷链接=%s 平台=%s 目标份数=%s 当前进度=%s/%s 并发数=%s 作答时长=%s 随机IP=%s 代理源=%s 运行时=纯HTTP",
            self._app_version,
            config.url or "",
            config.survey_provider or "",
            config.target_num,
            state.cur_num,
            config.target_num,
            worker_count,
            _format_seconds_range(config.answer_duration_range_seconds),
            "开启" if config.random_proxy_ip_enabled else "关闭",
            _format_proxy_source(config.proxy_source),
        )
        stop_event = self._stop_event
        if stop_event is None:
            raise RuntimeError("AsyncRuntimeEngine stop_event 未初始化")

        async def _prefetch_proxy_pool() -> None:
            while should_continue_proxy_prefetch(state) and not stop_event.is_set():
                request_count = resolve_proxy_prefetch_request_count(state)
                if request_count <= 0:
                    if await wait_for_proxy_prefetch_cycle(state, state.stop_event):
                        return
                    continue
                on_random_ip_loading_changed(runtime_bridge, True, f"正在准备代理 0/{request_count}")
                fetch_lock_acquired = False
                try:
                    fetch_lock_acquired = await _acquire_proxy_fetch_lock_async(state, state.stop_event)
                    if not fetch_lock_acquired or state.stop_event.is_set() or stop_event.is_set():
                        return
                    request_count = resolve_proxy_prefetch_request_count(state)
                    if request_count <= 0:
                        continue
                    fetched = await fetch_proxy_batch_async(
                        expected_count=request_count,
                        stop_signal=state.stop_event,
                    )
                    if state.stop_event.is_set() or stop_event.is_set():
                        return
                    merged_count = merge_prefetched_proxy_leases(state, fetched)
                    if merged_count:
                        on_random_ip_loading_changed(
                            runtime_bridge,
                            True,
                            f"正在准备代理 {min(merged_count, request_count)}/{request_count}",
                        )
                except Exception:
                    logging.info("随机IP异步预热失败", exc_info=True)
                finally:
                    if fetch_lock_acquired:
                        try:
                            release_proxy_fetch_lock(state)
                        except Exception:
                            logging.info("释放随机IP异步预热锁失败", exc_info=True)
                    on_random_ip_loading_changed(runtime_bridge, False, "")
                if await wait_for_proxy_prefetch_cycle(state, state.stop_event):
                    return

        prefetch_task = asyncio.create_task(_prefetch_proxy_pool(), name="AsyncProxyPrefetch")
        try:
            async with asyncio.TaskGroup() as task_group:
                for slot_index in range(worker_count):
                    task_group.create_task(
                        AsyncSlotRunner(
                            slot_id=slot_index + 1,
                            config=config,
                            state=state,
                            run_context=run_context,
                            scheduler=scheduler,
                            task_registry=task_registry,
                            app_version=self._app_version,
                            submission_report_enabled=self._submission_report_enabled,
                            runtime_bridge=runtime_bridge,
                        ).run(),
                        name=f"AsyncSlotRunner-{slot_index + 1}",
                    )
        except* Exception as exc_group:
            errors = [exc for exc in exc_group.exceptions if not isinstance(exc, asyncio.CancelledError)]
            if not errors:
                raise
            if len(errors) == 1:
                raise errors[0]
            raise ExceptionGroup("AsyncRuntimeEngine slot 运行失败", errors)
        finally:
            prefetch_task.cancel()
            await asyncio.gather(prefetch_task, return_exceptions=True)
            if self._stop_event is not None:
                self._stop_event.set()
            dropped = await task_registry.drain(timeout=5.0)
            if dropped:
                logging.warning("任务结束时有 %d 个后台任务超时取消", dropped)
            await scheduler.close()
            state.stop_event.set()
            self._stop_event = None
            self._pause_event = None
            self._state = None

    def stop_run(self) -> None:
        stop_event = self._stop_event
        state = self._state
        if state is not None:
            try:
                state.stop_event.set()
            except Exception:
                logging.debug("设置 ExecutionState.stop_event 失败", exc_info=True)
        loop = self._loop
        if loop is not None and stop_event is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(stop_event.set)
            except RuntimeError:
                logging.debug("AsyncRuntimeEngine loop 已关闭，忽略 stop 信号", exc_info=True)
        future = self._run_future
        if future is not None and future.done():
            self._run_future = None

    def pause_run(self, reason: str = "") -> None:
        del reason
        pause_event = self._pause_event
        loop = self._loop
        if loop is not None and pause_event is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(pause_event.set)
            except RuntimeError:
                logging.debug("AsyncRuntimeEngine loop 已关闭，忽略 pause 信号", exc_info=True)

    def resume_run(self) -> None:
        pause_event = self._pause_event
        loop = self._loop
        if loop is not None and pause_event is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(pause_event.clear)
            except RuntimeError:
                logging.debug("AsyncRuntimeEngine loop 已关闭，忽略 resume 信号", exc_info=True)

    def parse_survey(self, url: str) -> concurrent.futures.Future[ProviderParseResult]:
        return self._submit(parse_survey(url))

    def submit_ui_task(
        self,
        task_name: str,
        coro_factory: Callable[[], Coroutine[Any, Any, Any]],
    ) -> concurrent.futures.Future[Any]:
        async def _run_task() -> Any:
            logging.debug("AsyncUiTaskService 执行任务：%s", task_name)
            registry = self._ui_task_registry
            if registry is None:
                raise RuntimeError("AsyncRuntimeEngine 后台任务注册表未初始化")
            task = registry.create_task(coro_factory(), name=task_name)
            return await task

        return self._submit(_run_task())

    def shutdown(self, *, timeout: float = 5.0) -> None:
        timeout_seconds = max(0.0, float(timeout or 0.0))
        deadline = time.monotonic() + timeout_seconds
        with self._start_lock:
            with self._lifecycle_lock:
                if self._engine_state is EngineState.CLOSED:
                    return
                self._engine_state = EngineState.STOPPING
                thread = self._thread
                loop = self._loop
                future = self._run_future
        if loop is None and thread is not None:
            self._loop_ready.wait(timeout=max(0.0, deadline - time.monotonic()))
            with self._lifecycle_lock:
                loop = self._loop
        self.stop_run()
        called_from_engine_thread = thread is threading.current_thread()
        if future is not None and not called_from_engine_thread:
            try:
                future.result(timeout=max(0.0, deadline - time.monotonic()))
            except Exception:
                logging.debug("AsyncRuntimeEngine shutdown 等待运行结束失败", exc_info=True)
        if loop is not None and not loop.is_closed():
            registry = self._ui_task_registry
            if registry is not None and not called_from_engine_thread:
                try:
                    drain_future = asyncio.run_coroutine_threadsafe(registry.drain(timeout=1.0), loop)
                    drain_future.result(timeout=max(0.0, deadline - time.monotonic()))
                except Exception:
                    logging.warning("等待后台 UI 任务收尾失败", exc_info=True)
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                logging.debug("AsyncRuntimeEngine loop 已关闭，无法发送 stop", exc_info=True)
        if thread is not None and thread is not threading.current_thread() and thread.is_alive():
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if thread is None or not thread.is_alive():
            self._mark_stopped(loop)
            close_sync_http_clients()
        elif thread is not None:
            logging.warning("AsyncRuntimeEngine 在 %.1f 秒关闭期限内未退出", timeout_seconds)


class AsyncEngineClient:
    

    def __init__(self, engine: Optional[AsyncRuntimeEngine] = None) -> None:
        self._engine = engine or AsyncRuntimeEngine()

    @property
    def thread(self) -> Optional[threading.Thread]:
        return self._engine.thread

    @property
    def engine_state(self) -> EngineState:
        return self._engine.engine_state

    def start_run(
        self,
        config: ExecutionConfig,
        state: ExecutionState,
        *,
        runtime_bridge: RuntimeControlPort | None = None,
    ) -> concurrent.futures.Future[Any]:
        return self._engine.start_run(config=config, state=state, runtime_bridge=runtime_bridge)

    def stop_run(self) -> None:
        self._engine.stop_run()

    def pause_run(self, reason: str = "") -> None:
        self._engine.pause_run(reason)

    def resume_run(self) -> None:
        self._engine.resume_run()

    def parse_survey(self, url: str) -> concurrent.futures.Future[ProviderParseResult]:
        return self._engine.parse_survey(url)

    def submit_ui_task(
        self,
        task_name: str,
        coro_factory: Callable[[], Coroutine[Any, Any, Any]],
    ) -> concurrent.futures.Future[Any]:
        return self._engine.submit_ui_task(task_name, coro_factory)

    def shutdown(self, *, timeout: float = 5.0) -> None:
        self._engine.shutdown(timeout=timeout)


__all__ = ["AsyncEngineClient", "AsyncRuntimeEngine", "EngineState"]
