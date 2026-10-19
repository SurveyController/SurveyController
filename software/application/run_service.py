from __future__ import annotations

import logging
import math
import threading
import copy
from concurrent.futures import Future
from typing import Any, Callable, Dict, List, Optional

from software.application.configuration import ConfigurationService
from software.application.constants import STOP_FORCE_WAIT_SECONDS
from software.application.events import ApplicationEvent, event_payload
from software.application.ports import (
    CleanupRunnerPort, ExecutionPreparerPort, ProxyGatewayPort, RuntimeEnginePort, UserInteractionPort,
)
from software.application.interactions import InteractionKind, InteractionRequest
from software.core.config.schema import RuntimeConfig
from software.core.engine.failure_reason import FailureReason
from software.core.task import ExecutionConfig, ExecutionState, ProxyLease
from software.application.runtime_port import RunRuntimePort
from software.application.run_state_store import RunStateStore
from software.core.engine.execution_artifacts import PreparedExecutionArtifacts, RuntimePreparationError
from software.application.run_parts.runtime_random_ip import (
    RandomIpRuntimeService,
)
from software.application.run_parts.runtime_shutdown import (
    request_shutdown_for_close,
    shutdown_for_close,
)

from software.application.run_parts.runtime_status import (
    monitor_runtime, publish_runtime_snapshot, suggest_feedback,
)


class _ProxyStateAdapter:
    def __init__(self, service: "RunApplicationService") -> None:
        self._service = service

    def notify(self, code: str, detail: str = "", *, level: str = "info") -> None:
        self._service._interactions.request(
            InteractionRequest.create(InteractionKind.NOTICE, code, detail=detail, level=level)
        )

    def update_random_ip_counter(self, used: float, total: float, custom_api: bool) -> None:
        self._service.apply_runtime_patch(
            {
                "random_ip": {
                    "used_quota": max(0.0, float(used or 0.0)),
                    "total_quota": max(0.0, float(total or 0.0)),
                    "custom_api": bool(custom_api),
                }
            }
        )

    def set_random_ip_enabled(self, enabled: bool) -> None:
        self._service.sync_random_ip_enabled(bool(enabled))

    def set_random_ip_loading(self, loading: bool, message: str = "") -> None:
        self._service.notify_random_ip_loading(bool(loading), str(message or ""))

    def request_quota(self) -> Future[bool]:
        return self._service._interactions.request(
            InteractionRequest.create(InteractionKind.QUOTA, "random_ip_required")
        )


class RunApplicationService(RandomIpRuntimeService):
    def __init__(
        self,
        *,
        state_store: RunStateStore,
        async_engine_client: RuntimeEnginePort,
        execution_preparer: ExecutionPreparerPort,
        proxy_gateway: ProxyGatewayPort,
        configuration_service: ConfigurationService,
        cleanup_runner: CleanupRunnerPort,
        interactions: UserInteractionPort,
        dispatch_async: Callable[[Callable[[], Any]], None],
        emit_event: Callable[[ApplicationEvent], None],
    ) -> None:
        self._state_store = state_store
        self._async_engine_client = async_engine_client
        self._execution_preparer = execution_preparer
        self._proxy_gateway = proxy_gateway
        self._configuration_service = configuration_service
        self._interactions = interactions
        self._cleanup_runner = cleanup_runner
        self._dispatch_async = dispatch_async
        self._emit_event = emit_event
        self._paused_state = False
        self._stopping = False
        self._completion_cleanup_done = False
        self._cleanup_scheduled = False
        self._stopped_by_stop_run = False
        self._quick_feedback_prompt_emitted = False
        self._starting = False
        self._initializing = False
        self._init_gate_stop_event: threading.Event | None = None
        self._prepared_execution_artifacts: PreparedExecutionArtifacts | None = None
        self.stop_event = threading.Event()
        self.worker_threads: List[threading.Thread] = []
        self._monitor_thread: Optional[threading.Thread] = None
        self._init_gate_thread: Optional[threading.Thread] = None
        self._status_snapshot_monitor_thread: Optional[threading.Thread] = None
        self._execution_state: Optional[ExecutionState] = None
        self._close_shutdown_lock = threading.Lock()
        self._close_shutdown_thread: Optional[threading.Thread] = None
        self._random_ip_toggle_lock = threading.Lock()
        self._random_ip_toggle_active = False
        self._random_ip_server_sync_lock = threading.Lock()
        self._random_ip_server_sync_active = False
        self._random_ip_last_server_sync_at = 0.0
        self._random_ip_background_threads: set[threading.Thread] = set()
        self._random_ip_background_threads_lock = threading.Lock()
        self._last_loaded_config = RuntimeConfig()
        self.running = False
        self._closing = False
        self.runtime_port = RunRuntimePort(
            stop_signal=self.stop_event,
            notify_random_ip_loading=self.notify_random_ip_loading,
            handle_random_ip_submission=self.handle_random_ip_submission,
        )
        self.adapter = _ProxyStateAdapter(self)

    def _dispatch(self, callback: Callable[[], Any]) -> None:
        self._dispatch_async(callback)

    def _proxy_callbacks_active(self) -> bool:
        return not self._closing

    def is_initializing(self) -> bool:
        return bool(self._initializing)

    def threads_update_locked(self) -> bool:
        return bool(self.running or self._starting or self._initializing)

    def apply_runtime_patch(self, patch: Dict[str, Any]) -> None:
        self._dispatch(
            lambda payload=copy.deepcopy(patch): self._state_store.apply_runtime_patch(payload)
            if not self._closing else None
        )

    def emit_event(self, payload: ApplicationEvent) -> None:
        self._dispatch(lambda event=payload: self._emit_event(event) if not self._closing else None)

    def sync_random_ip_enabled(self, enabled: bool) -> None:
        self.runtime_port.set_random_ip_enabled(bool(enabled))
        self._dispatch(
            lambda value=bool(enabled): self._state_store.update_runtime_settings(
                random_ip_enabled=value,
                lock_threads=self.threads_update_locked(),
            ) if not self._closing else None
        )

    def sync_runtime_settings(self, settings: Dict[str, Any]) -> None:
        self.runtime_port.set_random_ip_enabled(bool(settings.get("random_ip_enabled", False)))

    def notify_random_ip_loading(self, loading: bool, message: str = "") -> None:
        self.apply_runtime_patch(
            {
                "random_ip": {
                    "loading": bool(loading),
                    "loading_stage": str(message or ""),
                }
            }
        )

    def load_saved_config(self, path: Optional[str] = None, *, strict: bool = False) -> RuntimeConfig:
        cfg = self._configuration_service.load(path, strict=strict)
        self._last_loaded_config = cfg
        return cfg

    def save_config(self, config: RuntimeConfig, path: Optional[str] = None) -> str:
        self._last_loaded_config = config
        return self._configuration_service.save(config, path)

    def save_current_config(self, path: Optional[str] = None) -> str:
        return self._configuration_service.save(self._last_loaded_config, path)

    def _prepare_engine_state(
        self,
        proxy_pool: List[ProxyLease],
    ) -> tuple[ExecutionConfig, ExecutionState]:
        prepared = self._prepared_execution_artifacts
        if prepared is None:
            raise RuntimeError("运行准备产物缺失，无法启动任务")
        execution_config = copy.deepcopy(prepared.execution_config_template)
        execution_config.proxy_ip_pool = (
            list(proxy_pool) if execution_config.random_proxy_ip_enabled else []
        )
        return (
            execution_config,
            ExecutionState(config=execution_config, stop_event=self.stop_event),
        )

    def _start_with_initialization_gate(
        self,
        config: RuntimeConfig,
        proxy_pool: List[ProxyLease],
    ) -> None:
        if self.stop_event.is_set():
            self._starting = False
            return
        self._start_workers_with_proxy_pool(config, list(proxy_pool))

    def start_run(self, config: RuntimeConfig) -> None:
        if self._closing:
            return
        previous_preparation = self._init_gate_thread
        if self.running or self._starting or self._initializing or self._stopping or (
            previous_preparation is not None and previous_preparation.is_alive()
        ):
            logging.warning("任务仍在运行或停止收尾中，忽略重复启动请求")
            return

        self._last_loaded_config = config
        self._state_store.hydrate_from_config(config, emit=True)

        self.stop_event = threading.Event()
        stop_signal = self.stop_event
        self.runtime_port = RunRuntimePort(
            stop_signal=stop_signal,
            notify_random_ip_loading=self.notify_random_ip_loading,
            handle_random_ip_submission=self.handle_random_ip_submission,
        )
        self.runtime_port.set_random_ip_enabled(bool(config.random_ip_enabled))
        self._execution_state = None
        self._paused_state = False
        self._stopping = False
        self._completion_cleanup_done = False
        self._cleanup_scheduled = False
        self._quick_feedback_prompt_emitted = False
        self._starting = True
        self._initializing = True
        self._state_store.apply_runtime_patch({
            "phase": "initializing", "running": False, "paused": False, "stopping": False,
            "pause_reason": "",
            "progress": {"current": 0, "target": 0, "consecutive_failures": 0, "device_quota_fail_count": 0},
            "threads": {"rows": [], "num_threads": 0, "per_thread_target": 0},
            "initialization": {"active": True, "stage": "preparing"},
            "terminal_stop": {"category": "", "failure_reason": "", "message": ""},
        })
        fallback_title = str(self._state_store.get_survey_snapshot().get("survey_title") or "")

        def prepare() -> None:
            try:
                prepared = self._execution_preparer(config, fallback_survey_title=fallback_title)
            except Exception as exc:
                if isinstance(exc, RuntimePreparationError):
                    logging.error(exc.log_message, exc_info=exc.detailed)
                    detail = exc.user_message
                else:
                    logging.exception("运行准备失败")
                    detail = str(exc)
                callback = lambda detail=detail: self._fail_start(stop_signal, "run_preparation_failed", detail)
            else:
                callback = lambda: self._complete_preparation(config, prepared, stop_signal)
            try:
                self._dispatch(callback)
            except Exception:
                stop_signal.set()
                if stop_signal is self.stop_event:
                    self._starting = False
                    self._initializing = False
                    self._state_store.apply_runtime_patch({
                        "phase": "failed", "initialization": {"active": False, "stage": ""},
                        "terminal_stop": {"category": "dispatch_failed", "failure_reason": "", "message": ""},
                    }, emit=False)
                logging.warning("派发运行准备结果失败", exc_info=True)

        thread = threading.Thread(target=prepare, daemon=True, name="RuntimePreparation")
        self._init_gate_thread = thread
        thread.start()

    def _fail_start(self, stop_signal: threading.Event, category: str, detail: str) -> None:
        if self._closing or stop_signal is not self.stop_event or stop_signal.is_set():
            return
        self._starting = False
        self._initializing = False
        self.running = False
        stop_signal.set()
        self._prepared_execution_artifacts = None
        self._state_store.apply_runtime_patch({
            "phase": "failed", "running": False, "paused": False, "stopping": False,
            "initialization": {"active": False, "stage": ""},
            "terminal_stop": {"category": category, "failure_reason": "", "message": detail},
        })
        self._schedule_cleanup()
        self.emit_event(event_payload("run_failed", code=category, detail=detail))

    def _complete_preparation(
        self, config: RuntimeConfig, prepared: PreparedExecutionArtifacts, stop_signal: threading.Event,
    ) -> None:
        if self._closing or stop_signal is not self.stop_event or stop_signal.is_set():
            return
        self._prepared_execution_artifacts = prepared
        try:
            self._start_with_initialization_gate(config, [])
        except Exception as exc:
            logging.exception("运行引擎初始化失败")
            try:
                self._async_engine_client.stop_run()
            except Exception:
                logging.debug("初始化失败后停止引擎失败", exc_info=True)
            self._fail_start(stop_signal, "engine_start_failed", str(exc))

    def _start_workers_with_proxy_pool(
        self,
        config: RuntimeConfig,
        proxy_pool: List[ProxyLease],
        *,
        emit_run_state: bool = True,
    ) -> None:
        del emit_run_state
        execution_config, execution_state = self._prepare_engine_state(proxy_pool)
        worker_count = max(1, int(execution_config.num_threads or 1))
        execution_state.ensure_worker_threads(worker_count, prefix="Slot")
        execution_state.initialize_reverse_fill_runtime()
        self._execution_state = execution_state
        self._prepared_execution_artifacts = None
        self._last_loaded_config = config

        run_future = self._async_engine_client.start_run(
            execution_config,
            execution_state,
            runtime_bridge=self.runtime_port,
        )
        self.running = True
        self._starting = False
        self._initializing = False
        self._stopping = False
        self._state_store.apply_runtime_patch(
            {
                "phase": "running",
                "running": True,
                "paused": False,
                "stopping": False,
                "initialization": {
                    "active": False,
                    "stage": "",
                },
                "threads": {
                    "num_threads": worker_count,
                    "per_thread_target": int(
                        math.ceil(float(max(0, execution_config.target_num or 0)) / float(worker_count))
                    )
                    if int(execution_config.target_num or 0) > 0
                    else 0,
                },
            }
        )
        self._start_status_snapshot_monitor(execution_state)

        runtime_thread = self._async_engine_client.thread
        self.worker_threads = (
            [runtime_thread] if isinstance(runtime_thread, threading.Thread) else []
        )
        monitor = threading.Thread(
            target=self._wait_for_async_run,
            args=(run_future, execution_state, self.stop_event),
            daemon=True,
            name="Monitor",
        )
        self._monitor_thread = monitor
        monitor.start()
        self.emit_status_snapshot()

    def _start_status_snapshot_monitor(self, execution_state: ExecutionState) -> None:
        previous = self._status_snapshot_monitor_thread
        if isinstance(previous, threading.Thread) and previous.is_alive():
            previous.join(timeout=0.5)

        monitor = threading.Thread(
            target=self._status_snapshot_monitor_loop,
            args=(execution_state, self.stop_event),
            daemon=True,
            name="RuntimeStatusSnapshotMonitor",
        )
        self._status_snapshot_monitor_thread = monitor
        monitor.start()

    def _status_snapshot_monitor_loop(self, execution_state: ExecutionState, stop_signal: threading.Event) -> None:
        monitor_runtime(self, execution_state, stop_signal)

    def stop_run(self) -> None:
        ctx = self._execution_state
        if ctx is not None:
            ctx.mark_terminal_stop(
                "user_stopped",
                failure_reason=FailureReason.USER_STOPPED.value,
            )
        if self._starting and not self.running:
            self.stop_event.set()
            gate_stop = self._init_gate_stop_event
            if gate_stop is not None:
                gate_stop.set()
            self._prepared_execution_artifacts = None
            self._starting = False
            self._initializing = False
            self._state_store.apply_runtime_patch(
                {
                    "phase": "finished",
                    "running": False,
                    "paused": False,
                    "stopping": False,
                    "terminal_stop": {
                        "category": "user_stopped",
                        "failure_reason": FailureReason.USER_STOPPED.value,
                        "message": "",
                    },
                    "initialization": {"active": False, "stage": ""},
                },
                emit=not self._closing,
            )
            return
        if not self.running:
            return
        try:
            self._async_engine_client.stop_run()
        except Exception:
            logging.debug("停止 async-first 内核失败", exc_info=True)
        self.stop_event.set()
        gate_stop = self._init_gate_stop_event
        if gate_stop is not None:
            gate_stop.set()
        try:
            self.runtime_port.resume_run()
        except Exception:
            logging.debug("停止时恢复暂停状态失败", exc_info=True)
        try:
            self._async_engine_client.resume_run()
        except Exception:
            logging.debug("停止时恢复 async-first 内核暂停状态失败", exc_info=True)
        self._stopping = True
        self._paused_state = False
        self._stopped_by_stop_run = True
        self._state_store.apply_runtime_patch(
            {
                "phase": "stopping",
                "running": True,
                "paused": False,
                "stopping": True,
            },
            emit=not self._closing,
        )
        self.emit_status_snapshot()

    def pause_run(self, reason: str = "") -> None:
        if not self.running or self._stopping:
            return
        self._async_engine_client.pause_run(reason)
        self.runtime_port.pause_run(reason)
        self._paused_state = True
        self.emit_status_snapshot()

    def resume_run(self) -> None:
        if not self.running:
            return
        try:
            self._async_engine_client.resume_run()
        except Exception:
            logging.debug("恢复 async-first 内核运行失败", exc_info=True)
        try:
            self.runtime_port.resume_run()
        except Exception:
            logging.debug("恢复运行时清除暂停状态失败", exc_info=True)
        if self._paused_state:
            self._paused_state = False
        self.emit_status_snapshot()

    def _wait_for_async_run(
        self,
        run_future: Future[Any],
        execution_state: ExecutionState,
        stop_signal: threading.Event,
    ) -> None:
        failure: Exception | None = None
        try:
            run_future.result()
        except Exception as exc:
            logging.warning("async-first 运行内核异常退出", exc_info=True)
            execution_state.mark_terminal_stop("engine_failed", message=str(exc))
            failure = exc
        finally:
            def finish() -> None:
                if self._execution_state is not execution_state or self.stop_event is not stop_signal:
                    return
                if failure is not None and not self._closing:
                    self._emit_event(event_payload("run_failed", code="engine_failed"))
                self._on_run_finished()

            try:
                self._dispatch(finish)
            except Exception:
                logging.warning("派发运行结束状态失败", exc_info=True)
                if self._execution_state is execution_state and self.stop_event is stop_signal:
                    stop_signal.set()
                    execution_state.mark_terminal_stop("dispatch_failed", overwrite=True)
                    self.running = False
                    self._starting = False
                    self._initializing = False
                    self._stopping = False
                    self._state_store.apply_runtime_patch({
                        "phase": "failed", "running": False, "paused": False, "stopping": False,
                        "initialization": {"active": False, "stage": ""},
                        "terminal_stop": {"category": "dispatch_failed", "failure_reason": "", "message": ""},
                    }, emit=False)
                    self._schedule_cleanup()
            finally:
                if self._monitor_thread is threading.current_thread():
                    self._monitor_thread = None

    def _on_run_finished(self) -> None:
        self.stop_event.set()
        self._schedule_cleanup()
        was_active = bool(self.running or self._stopping or self._initializing)
        self._stopped_by_stop_run = False
        self._stopping = False
        self.running = False
        self._initializing = False
        self.runtime_port.resume_run()
        if was_active:
            self.emit_status_snapshot()
        if not self._closing:
            self._emit_quick_bug_report_suggestion_if_needed()

    def _submit_cleanup_task(self, delay_seconds: float = 0.0) -> None:
        runtime_port = self.runtime_port

        def notify_finished() -> None:
            if self.runtime_port is runtime_port and not self._closing:
                self._emit_event(event_payload("cleanup_finished"))

        def _cleanup() -> None:
            try:
                runtime_port.cleanup_targets()
            except Exception:
                logging.warning("执行运行时清理任务失败", exc_info=True)
            finally:
                try:
                    self._dispatch(notify_finished)
                except Exception:
                    logging.debug("派发运行时清理结果失败", exc_info=True)

        self._cleanup_runner.submit(_cleanup, delay_seconds=delay_seconds)

    def _schedule_cleanup(self) -> None:
        if self._cleanup_scheduled:
            return
        self._cleanup_scheduled = True
        self._submit_cleanup_task(delay_seconds=STOP_FORCE_WAIT_SECONDS)

    def emit_status_snapshot(self) -> None:
        publish_runtime_snapshot(self)

    def request_shutdown_for_close(self, timeout_seconds: float = 5.0) -> None:
        request_shutdown_for_close(self, timeout_seconds)

    def shutdown_for_close(self, timeout_seconds: float = 5.0) -> bool:
        return shutdown_for_close(self, timeout_seconds)

    def _emit_quick_bug_report_suggestion_if_needed(self) -> None:
        suggest_feedback(self)



__all__ = ["RunApplicationService"]
