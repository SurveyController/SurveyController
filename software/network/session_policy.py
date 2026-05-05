"""会话策略 - 代理切换与浏览器实例复用逻辑"""
from typing import Any, Optional, Tuple
import logging

from software.core.engine.stop_signal import StopSignalLike
from software.core.task import ExecutionState, ProxyLease
from software.network.proxy.pool import mask_proxy_for_log
from software.network.proxy.sidecar_manager import (
    ProxySidecarError,
    ensure_proxy_sidecar_running,
    restart_proxy_sidecar,
)
from software.network.proxy import get_proxy_required_ttl_seconds
from software.io.config import _select_user_agent_from_ratios

_PROXY_WAIT_POLL_SECONDS = 0.3
_BAD_PROXY_COOLDOWN_SECONDS = 180.0


def _record_bad_proxy_and_maybe_pause(
    ctx: ExecutionState,
    gui_instance: Optional[Any],
) -> bool:
    """
    记录代理不可用事件。
    现阶段不再根据代理异常次数自动暂停任务，统一由提交连续失败止损控制。
    """
    _ = ctx, gui_instance
    return False


def _required_proxy_ttl_seconds(ctx: ExecutionState) -> int:
    return int(get_proxy_required_ttl_seconds(getattr(ctx.config, "answer_duration_range_seconds", (0, 0))))


def _sidecar_client():
    return ensure_proxy_sidecar_running(force_restart=False)


def _ensure_sidecar_config_applied() -> None:
    client = _sidecar_client()
    client.apply_config(__import__("software.network.proxy.policy.settings", fromlist=["get_proxy_settings"]).get_proxy_settings())


def _mark_proxy_temporarily_bad(
    ctx: ExecutionState,
    proxy_address: str,
    *,
    cooldown_seconds: float = _BAD_PROXY_COOLDOWN_SECONDS,
) -> None:
    normalized = str(proxy_address or "").strip()
    if not normalized:
        return
    ctx.mark_proxy_in_cooldown(normalized, cooldown_seconds)
    with ctx.lock:
        ctx.config.proxy_ip_pool = [
            lease
            for lease in list(getattr(ctx.config, "proxy_ip_pool", []) or [])
            if str(getattr(lease, "address", "") or "").strip() != normalized
        ]
    try:
        _sidecar_client().mark_bad(
            thread_name="",
            proxy_address=normalized,
            cooldown_seconds=float(cooldown_seconds or 0.0),
        )
    except ProxySidecarError as exc:
        logging.warning("通知代理服务标记坏代理失败：%s", exc)
    logging.info(
        "代理进入冷却 %.0fs：%s",
        float(cooldown_seconds or 0.0),
        mask_proxy_for_log(normalized),
    )


def _mark_proxy_in_use(ctx: ExecutionState, thread_name: str, lease: Optional[ProxyLease]) -> Optional[str]:
    if lease is None:
        return None
    if thread_name:
        ctx.mark_proxy_in_use(thread_name, lease)
    logging.info(
        "线程[%s] 已分配随机IP：%s（来源=%s）",
        thread_name or "?",
        mask_proxy_for_log(lease.address),
        str(getattr(lease, "source", "") or "unknown"),
    )
    return lease.address


def _resolve_proxy_request_num_locked(ctx: ExecutionState) -> int:
    waiting_count = max(1, int(ctx.proxy_waiting_threads or 0))
    active_count = len(ctx.proxy_in_use_by_thread)
    remaining_to_start = max(0, int(ctx.config.target_num or 0) - int(ctx.cur_num or 0) - active_count)
    if remaining_to_start <= 0:
        return 0
    return max(1, min(waiting_count, remaining_to_start, 80))


def _should_stop_proxy_wait(
    ctx: ExecutionState,
    stop_signal: Optional[StopSignalLike],
) -> bool:
    if stop_signal is not None and stop_signal.is_set():
        return True
    return bool(getattr(ctx, "stop_event", None) and ctx.stop_event.is_set())


def _wait_for_next_proxy_cycle(
    ctx: ExecutionState,
    stop_signal: Optional[StopSignalLike],
    *,
    timeout: float = _PROXY_WAIT_POLL_SECONDS,
) -> bool:
    return ctx.wait_for_runtime_change(stop_signal=stop_signal, timeout=timeout)


def _select_proxy_for_session(
    ctx: ExecutionState,
    thread_name: str = "",
    *,
    stop_signal: Optional[StopSignalLike] = None,
    wait: bool = False,
) -> Optional[str]:
    if not ctx.config.random_proxy_ip_enabled:
        return None
    ctx.register_proxy_waiter()
    try:
        while True:
            if _should_stop_proxy_wait(ctx, stop_signal):
                return None
            try:
                client = _sidecar_client()
                client.apply_config(__import__("software.network.proxy.policy.settings", fromlist=["get_proxy_settings"]).get_proxy_settings())
                with ctx.lock:
                    request_num = _resolve_proxy_request_num_locked(ctx)
                if request_num > 0:
                    client.prefetch(request_num)
                lease = client.acquire_lease(thread_name=thread_name, wait=bool(wait))
                if lease is not None:
                    return _mark_proxy_in_use(ctx, thread_name, lease)
            except ProxySidecarError as exc:
                logging.warning("获取随机代理失败：%s", exc)
                if wait:
                    try:
                        restart_proxy_sidecar()
                    except Exception as restart_exc:
                        logging.warning("重启代理服务失败：%s", restart_exc)

            if not wait:
                return None
            if _wait_for_next_proxy_cycle(ctx, stop_signal):
                return None
    finally:
        ctx.unregister_proxy_waiter()


def _select_user_agent_for_session(ctx: ExecutionState) -> Tuple[Optional[str], Optional[str]]:
    if not ctx.config.random_user_agent_enabled:
        return None, None
    return _select_user_agent_from_ratios(ctx.config.user_agent_ratios)


def _discard_unresponsive_proxy(ctx: ExecutionState, proxy_address: str) -> None:
    if not proxy_address:
        return
    normalized = str(proxy_address or "").strip()
    with ctx.lock:
        ctx.config.proxy_ip_pool = [
            lease
            for lease in list(getattr(ctx.config, "proxy_ip_pool", []) or [])
            if str(getattr(lease, "address", "") or "").strip() != normalized
        ]
    try:
        _sidecar_client().mark_bad(
            thread_name="",
            proxy_address=normalized,
            cooldown_seconds=0.0,
        )
    except ProxySidecarError as exc:
        logging.warning("移除无响应代理失败：%s", exc)
    logging.info("已移除无响应代理：%s", mask_proxy_for_log(proxy_address))


