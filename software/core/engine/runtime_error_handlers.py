"""Helpers for runtime error handling in execution loop."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from software.core.ai.runtime import AIRuntimeError, is_ai_timeout_runtime_error, is_free_ai_runtime_error
from software.core.engine.failure_reason import FailureReason
from software.core.task import ExecutionConfig, ExecutionState
FREE_AI_TIMEOUT_FAIL_THRESHOLD = 5


def handle_ai_runtime_error(
    exc: AIRuntimeError,
    stop_signal: threading.Event,
    *,
    thread_name: str,
    stop_policy: Any,
    state: ExecutionState,
) -> bool:
    if is_ai_timeout_runtime_error(exc):
        logging.warning("免费 AI 调用超时，本轮丢弃并继续下一轮：%s", exc)
        stopped = stop_policy.record_failure(
            stop_signal,
            thread_name=thread_name,
            failure_reason=FailureReason.FILL_FAILED,
            status_text="免费AI超时",
            log_message=(
                f"免费AI调用超时，本轮按失败处理；连续达到 {FREE_AI_TIMEOUT_FAIL_THRESHOLD} 次才停止：{exc}"
            ),
            threshold_override=FREE_AI_TIMEOUT_FAIL_THRESHOLD,
            terminal_stop_category="free_ai_unstable",
            force_stop_when_threshold_reached=True,
            consume_reverse_fill_attempt=False,
        )
        if stopped:
            logging.error("免费 AI 连续超时达到阈值，任务停止：%s", exc, exc_info=True)
        return bool(stopped)

    logging.error("AI 填空失败，已停止任务：%s", exc, exc_info=True)
    stop_category = "free_ai_unstable" if is_free_ai_runtime_error(exc) else "ai_runtime"
    stop_message = "目前免费AI不稳定，请稍后再试" if stop_category == "free_ai_unstable" else str(exc)
    state.mark_terminal_stop(
        stop_category,
        failure_reason=FailureReason.FILL_FAILED.value,
        message=stop_message,
    )
    if not stop_signal.is_set():
        stop_signal.set()
    return True


def handle_proxy_connection_error(
    session: Any,
    stop_signal: threading.Event,
    *,
    thread_name: str,
    state: ExecutionState,
    config: ExecutionConfig,
    stop_policy: Any,
    update_thread_status: Callable[[str, str], None],
    handle_proxy_unavailable: Callable[..., bool],
    mark_proxy_temporarily_bad: Callable[[ExecutionState, str], None],
) -> bool:
    if stop_signal.is_set():
        return True
    logging.warning("代理连接失败，当前会话将废弃并重新尝试")
    if session is not None and getattr(session, "proxy_address", None):
        mark_proxy_temporarily_bad(state, session.proxy_address)
    if config.random_proxy_ip_enabled:
        update_thread_status(thread_name, "代理失效，切换中")
        if handle_proxy_unavailable(
            stop_signal,
            thread_name=thread_name,
            status_text="代理不可用",
            log_message="代理连接失败，本轮按失败处理",
        ):
            return True
        return False
    return stop_policy.record_failure(
        stop_signal,
        thread_name=thread_name,
        failure_reason=FailureReason.PROXY_UNAVAILABLE,
        consume_reverse_fill_attempt=False,
    )


__all__ = [
    "FREE_AI_TIMEOUT_FAIL_THRESHOLD",
    "handle_ai_runtime_error",
    "handle_proxy_connection_error",
]
