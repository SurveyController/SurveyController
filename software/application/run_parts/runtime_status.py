from __future__ import annotations

import logging
import math
import threading
import time
from typing import TYPE_CHECKING, Any

from software.application.events import event_payload
from software.application.interactions import InteractionKind, InteractionRequest
from software.core.engine.failure_reason import FailureReason
from software.core.task import ExecutionState

if TYPE_CHECKING:
    from software.application.run_service import RunApplicationService

STATUS_SNAPSHOT_MIN_INTERVAL_SECONDS = 0.15


def monitor_runtime(
    service: RunApplicationService,
    execution_state: ExecutionState,
    stop_signal: threading.Event,
) -> None:
    try:
        observed_seq = execution_state._runtime_change_sequence()
    except Exception:
        observed_seq = -1
    pending_snapshot = False
    last_snapshot_at = 0.0
    while not stop_signal.is_set():
        if pending_snapshot:
            timeout = max(
                0.0,
                STATUS_SNAPSHOT_MIN_INTERVAL_SECONDS - (time.monotonic() - last_snapshot_at),
            )
        else:
            timeout = 1.0
        try:
            stopped = execution_state.wait_for_runtime_change(
                stop_signal=stop_signal,
                timeout=timeout,
            )
        except Exception:
            logging.debug("等待运行态变更失败", exc_info=True)
            time.sleep(1.0)
            stopped = bool(stop_signal.is_set())
        if service._execution_state is not execution_state:
            break
        try:
            current_seq = execution_state._runtime_change_sequence()
        except Exception:
            current_seq = observed_seq + 1
        if stopped:
            break
        if current_seq != observed_seq:
            observed_seq = current_seq
            pending_snapshot = True
        if not pending_snapshot:
            continue
        now = time.monotonic()
        if last_snapshot_at > 0 and now - last_snapshot_at < STATUS_SNAPSHOT_MIN_INTERVAL_SECONDS:
            continue
        try:
            service._dispatch(service.emit_status_snapshot)
            last_snapshot_at = now
            pending_snapshot = False
        except Exception:
            logging.debug("派发运行态快照失败", exc_info=True)
    if service._execution_state is execution_state:
        try:
            service._dispatch(service.emit_status_snapshot)
        except Exception:
            logging.debug("派发最终运行态快照失败", exc_info=True)



def publish_runtime_snapshot(service: RunApplicationService) -> None:
    if service._initializing:
        service._state_store.apply_runtime_patch(
            {
                "phase": "initializing",
                "running": False,
                "paused": False,
                "stopping": False,
                "initialization": {
                    "active": True,
                    "stage": "preparing",
                },
                "threads": {
                    "rows": [],
                    "num_threads": 0,
                    "per_thread_target": 0,
                },
            },
            emit=not service._closing,
        )
        return

    ctx = service._execution_state
    current = int(getattr(ctx, "cur_num", 0) or 0)
    target = int(getattr(getattr(ctx, "config", None), "target_num", 0) or 0)
    consecutive_failures = int(getattr(ctx, "cur_fail", 0) or 0)
    device_quota_fail_count = int(getattr(ctx, "device_quota_fail_count", 0) or 0)
    terminal_category = ""
    terminal_failure_reason = ""
    terminal_message = ""
    if ctx is not None:
        try:
            category, failure_reason, message = ctx.get_terminal_stop_snapshot()
            terminal_category = str(category or "").strip()
            terminal_failure_reason = str(failure_reason or "").strip()
            terminal_message = str(message or "").strip()
        except Exception:
            logging.debug("读取终止状态失败", exc_info=True)

    paused = bool(service.runtime_port.is_paused())
    reason = str(service.runtime_port.get_pause_reason() or "")

    thread_rows: list[dict[str, Any]] = []
    num_threads = 0
    per_thread_target = 0
    if ctx is not None:
        try:
            thread_rows = ctx.snapshot_thread_progress()
        except Exception:
            logging.debug("获取线程进度快照失败", exc_info=True)
        try:
            num_threads = max(
                1,
                int(getattr(getattr(ctx, "config", None), "num_threads", 1) or 1),
            )
        except Exception:
            num_threads = 1
        if target > 0:
            per_thread_target = int(math.ceil(float(target) / float(num_threads)))

    phase = "running"
    if service._stopping:
        phase = "stopping"
    elif paused:
        phase = "paused"
    elif not service.running:
        if terminal_category in {"", "target_reached", "user_stopped"}:
            phase = "finished"
        else:
            phase = "failed"

    service._state_store.apply_runtime_patch(
        {
            "phase": phase,
            "running": bool(service.running),
            "paused": bool(paused),
            "pause_reason": reason,
            "stopping": bool(service._stopping),
            "progress": {
                "current": current,
                "target": target,
                "consecutive_failures": consecutive_failures,
                "device_quota_fail_count": device_quota_fail_count,
            },
            "threads": {
                "rows": thread_rows,
                "num_threads": int(num_threads or 0),
                "per_thread_target": int(per_thread_target or 0),
            },
            "initialization": {
                "active": False,
                "stage": "",
            },
            "terminal_stop": {
                "category": terminal_category,
                "failure_reason": terminal_failure_reason,
                "message": terminal_message,
            },
        },
        emit=not service._closing,
    )

    should_force_cleanup = target > 0 and current >= target and not service._completion_cleanup_done
    if should_force_cleanup:
        service._completion_cleanup_done = True
        service._schedule_cleanup()



def suggest_feedback(service: RunApplicationService) -> None:
    if service._quick_feedback_prompt_emitted:
        return
    if service.running or service._starting or service._initializing:
        return
    ctx = service._execution_state
    if ctx is None:
        return
    category, failure_reason, message = ctx.get_terminal_stop_snapshot()
    category = str(category or "").strip()
    failure_reason = str(failure_reason or "").strip()
    if not category:
        return
    if category == "ai_unstable":
        service._quick_feedback_prompt_emitted = True
        service.emit_event(event_payload("ai_unstable"))
        return
    if category == "submission_verification":
        service._quick_feedback_prompt_emitted = True
        service.emit_event(
            event_payload(
                "submission_verification_required",
                message=str(message or ""),
            )
        )
        return
    if category in {"target_reached", "user_stopped"}:
        return
    if failure_reason in {
        FailureReason.DEVICE_QUOTA_LIMIT.value,
        FailureReason.SUBMISSION_VERIFICATION_REQUIRED.value,
        FailureReason.USER_STOPPED.value,
    }:
        return
    service._quick_feedback_prompt_emitted = True
    service._interactions.request(
        InteractionRequest.create(InteractionKind.CONFIRMATION, "quick_bug_report")
    )
