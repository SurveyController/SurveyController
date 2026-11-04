from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from software.application.run_parts.preparation_job import PreparationJob
from software.application.runtime_port import RunRuntimePort
from software.core.config.schema import RuntimeConfig
from software.core.engine.failure_reason import FailureReason

if TYPE_CHECKING:
    from software.application.run_service import RunApplicationService


class RunLifecycleCoordinator:
    """Coordinate run transitions while keeping adapters on the service facade."""

    def __init__(self, service: RunApplicationService) -> None:
        self._service = service

    def start_run(self, config: RuntimeConfig) -> None:
        service = self._service
        if service._closing:
            return
        previous_preparation = service._init_gate_thread
        if (
            service.running
            or service._starting
            or service._initializing
            or service._stopping
            or (previous_preparation is not None and previous_preparation.is_alive())
        ):
            logging.warning("任务仍在运行或停止收尾中，忽略重复启动请求")
            return

        service._last_loaded_config = config
        service._state_store.hydrate_from_config(config, emit=True)

        service.stop_event = threading.Event()
        stop_signal = service.stop_event
        service._init_gate_stop_event = stop_signal
        service.runtime_port = RunRuntimePort(
            stop_signal=stop_signal,
            notify_random_ip_loading=service.notify_random_ip_loading,
            handle_random_ip_submission=service.handle_random_ip_submission,
        )
        service.runtime_port.set_random_ip_enabled(bool(config.random_ip_enabled))
        service._execution_state = None
        service._paused_state = False
        service._stopping = False
        service._completion_cleanup_done = False
        service._cleanup_scheduled = False
        service._terminal_notice_emitted = False
        service._starting = True
        service._initializing = True
        service._state_store.apply_runtime_patch(
            {
                "phase": "initializing",
                "running": False,
                "paused": False,
                "stopping": False,
                "pause_reason": "",
                "progress": {
                    "current": 0,
                    "target": 0,
                    "consecutive_failures": 0,
                    "device_quota_fail_count": 0,
                },
                "threads": {"rows": [], "num_threads": 0, "per_thread_target": 0},
                "initialization": {"active": True, "stage": "preparing"},
                "terminal_stop": {"category": "", "failure_reason": "", "message": ""},
            }
        )
        fallback_title = str(service._state_store.get_survey_snapshot().get("survey_title") or "")
        job = PreparationJob(
            preparer=service._execution_preparer,
            config=config,
            fallback_survey_title=fallback_title,
            stop_signal=stop_signal,
            dispatch=service._dispatch,
            on_prepared=lambda prepared: service._complete_preparation(
                config,
                prepared,
                stop_signal,
            ),
            on_failed=lambda detail: service._fail_start(
                stop_signal,
                "run_preparation_failed",
                detail,
            ),
            on_dispatch_failed=lambda: self._handle_preparation_dispatch_failure(stop_signal),
        )
        service._preparation_job = job
        service._init_gate_thread = job.thread
        job.start()

    def _handle_preparation_dispatch_failure(self, stop_signal: threading.Event) -> None:
        service = self._service
        if stop_signal is not service.stop_event:
            return
        service._starting = False
        service._initializing = False
        service._state_store.apply_runtime_patch(
            {
                "phase": "failed",
                "initialization": {"active": False, "stage": ""},
                "terminal_stop": {
                    "category": "dispatch_failed",
                    "failure_reason": "",
                    "message": "",
                },
            },
            emit=False,
        )

    def stop_run(self) -> None:
        service = self._service
        context = service._execution_state
        if context is not None:
            context.mark_terminal_stop(
                "user_stopped",
                failure_reason=FailureReason.USER_STOPPED.value,
            )
        if service._starting and not service.running:
            preparation_job = service._preparation_job
            if preparation_job is not None:
                preparation_job.cancel()
            else:
                service.stop_event.set()
            gate_stop = service._init_gate_stop_event
            if gate_stop is not None:
                gate_stop.set()
            service._prepared_execution_artifacts = None
            service._starting = False
            service._initializing = False
            service._state_store.apply_runtime_patch(
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
                emit=not service._closing,
            )
            return
        if not service.running:
            return
        try:
            service._async_engine_client.stop_run()
        except Exception:
            logging.debug("停止 async-first 内核失败", exc_info=True)
        service.stop_event.set()
        gate_stop = service._init_gate_stop_event
        if gate_stop is not None:
            gate_stop.set()
        try:
            service.runtime_port.resume_run()
        except Exception:
            logging.debug("停止时恢复暂停状态失败", exc_info=True)
        try:
            service._async_engine_client.resume_run()
        except Exception:
            logging.debug("停止时恢复 async-first 内核暂停状态失败", exc_info=True)
        service._stopping = True
        service._paused_state = False
        service._stopped_by_stop_run = True
        service._state_store.apply_runtime_patch(
            {"phase": "stopping", "running": True, "paused": False, "stopping": True},
            emit=not service._closing,
        )
        service.emit_status_snapshot()

    def pause_run(self, reason: str = "") -> None:
        service = self._service
        if not service.running or service._stopping:
            return
        service._async_engine_client.pause_run(reason)
        service.runtime_port.pause_run(reason)
        service._paused_state = True
        service.emit_status_snapshot()

    def resume_run(self) -> None:
        service = self._service
        if not service.running:
            return
        try:
            service._async_engine_client.resume_run()
        except Exception:
            logging.debug("恢复 async-first 内核运行失败", exc_info=True)
        try:
            service.runtime_port.resume_run()
        except Exception:
            logging.debug("恢复运行时清除暂停状态失败", exc_info=True)
        if service._paused_state:
            service._paused_state = False
        service.emit_status_snapshot()


__all__ = ["RunLifecycleCoordinator"]
