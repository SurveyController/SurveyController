"""会话策略 - 代理切换与浏览器实例复用逻辑"""
from typing import Any, Optional, Tuple
import logging

from software.core.engine.stop_signal import StopSignalLike
from software.core.task import ExecutionState, ProxyLease
from software.network.proxy.pool import coerce_proxy_lease, is_http_proxy_connect_responsive, mask_proxy_for_log
from software.network.proxy.pool.free_pool import FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS
from software.network.proxy.pool.prefetch import prefetch_proxy_pool
from software.network.proxy import get_proxy_required_ttl_seconds, proxy_lease_has_sufficient_ttl
from software.io.config import _select_user_agent_from_ratios

_PROXY_WAIT_POLL_SECONDS = 0.3
_BAD_PROXY_COOLDOWN_SECONDS = 180.0
_PUBLIC_PROXY_RECHECK_TIMEOUT_SECONDS = 1.0
_FREE_PROXY_POOL_SOURCE = "free_pool"
_PUBLIC_PROXY_SOURCES = {_FREE_PROXY_POOL_SOURCE, "iplist"}
_PUBLIC_PROXY_RECHECK_SOURCES = {_FREE_PROXY_POOL_SOURCE, "iplist"}


def _lease_source(lease: Optional[ProxyLease]) -> str:
    return str(getattr(lease, "source", "") or "").strip().lower()


def _lease_is_free_pool(lease: Optional[ProxyLease]) -> bool:
    return _lease_source(lease) == _FREE_PROXY_POOL_SOURCE


def _proxy_address_has_source_locked(ctx: ExecutionState, proxy_address: str, source: str) -> bool:
    normalized = str(proxy_address or "").strip()
    expected_source = str(source or "").strip().lower()
    if not normalized or not expected_source:
        return False
    for item in list(ctx.config.proxy_ip_pool or []):
        lease = coerce_proxy_lease(item)
        if lease is not None and lease.address == normalized and _lease_source(lease) == expected_source:
            return True
    for lease in list(ctx.proxy_in_use_by_thread.values()):
        if lease is not None and str(getattr(lease, "address", "") or "").strip() == normalized and _lease_source(lease) == expected_source:
            return True
    return False


def _proxy_address_is_free_pool_source(ctx: ExecutionState, proxy_address: str) -> bool:
    with ctx.lock:
        return _proxy_address_has_source_locked(ctx, proxy_address, _FREE_PROXY_POOL_SOURCE)


def _active_proxy_addresses_locked(ctx: ExecutionState, *, exclude_thread_name: str = "") -> set[str]:
    return ctx.active_proxy_addresses_locked(exclude_thread_name=exclude_thread_name)


def _blocked_proxy_addresses_locked(ctx: ExecutionState, *, exclude_thread_name: str = "") -> set[str]:
    blocked = _active_proxy_addresses_locked(ctx, exclude_thread_name=exclude_thread_name)
    blocked.update(ctx.successful_proxy_addresses_locked())
    return blocked


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


def _mark_proxy_temporarily_bad(
    ctx: ExecutionState,
    proxy_address: str,
    *,
    cooldown_seconds: float = _BAD_PROXY_COOLDOWN_SECONDS,
) -> None:
    normalized = str(proxy_address or "").strip()
    if not normalized:
        return
    if _proxy_address_is_free_pool_source(ctx, normalized):
        logging.info("免费代理池代理本轮失败，仅轮换不冷却/剔除：%s", mask_proxy_for_log(normalized))
        return
    ctx.mark_proxy_in_cooldown(normalized, cooldown_seconds)
    _discard_unresponsive_proxy(ctx, normalized)
    logging.info(
        "代理进入冷却 %.0fs：%s",
        float(cooldown_seconds or 0.0),
        mask_proxy_for_log(normalized),
    )


def _purge_unusable_proxy_pool_locked(ctx: ExecutionState) -> None:
    ctx._purge_expired_proxy_cooldowns_locked()
    required_ttl = _required_proxy_ttl_seconds(ctx)
    kept = []
    seen = set()
    removed = 0
    for item in list(ctx.config.proxy_ip_pool or []):
        lease = coerce_proxy_lease(item)
        if lease is None:
            removed += 1
            continue
        if _lease_is_free_pool(lease):
            kept.append(lease)
            continue
        if not lease.poolable:
            removed += 1
            continue
        if lease.address in seen:
            removed += 1
            continue
        if ctx._is_proxy_in_cooldown_locked(lease.address) and not _lease_is_free_pool(lease):
            removed += 1
            logging.info("已移除冷却中的代理：%s", mask_proxy_for_log(lease.address))
            continue
        if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=required_ttl):
            removed += 1
            logging.info("已丢弃即将过期的代理：%s", mask_proxy_for_log(lease.address))
            continue
        seen.add(lease.address)
        kept.append(lease)
    if removed:
        logging.info("代理池已清理无效/重复代理 %s 个", removed)
    ctx.config.proxy_ip_pool = kept
    if removed:
        ctx.notify_runtime_change()


def _pop_available_proxy_lease_locked(
    ctx: ExecutionState,
    *,
    exclude_addresses: Optional[set[str]] = None,
) -> Optional[ProxyLease]:
    _purge_unusable_proxy_pool_locked(ctx)
    required_ttl = _required_proxy_ttl_seconds(ctx)
    active_addresses = _active_proxy_addresses_locked(ctx)
    successful_addresses = ctx.successful_proxy_addresses_locked()
    excluded = {
        str(address or "").strip()
        for address in set(exclude_addresses or set())
        if str(address or "").strip()
    }
    raw_items = list(ctx.config.proxy_ip_pool or [])
    free_pool_items: list[ProxyLease] = []
    non_free_items: list[Any] = []
    for item in raw_items:
        lease = coerce_proxy_lease(item)
        if lease is not None and _lease_is_free_pool(lease):
            free_pool_items.append(lease)
        else:
            non_free_items.append(item)

    free_pool_candidates: list[ProxyLease] = []
    for lease in free_pool_items:
        if lease.address in excluded:
            continue
        if lease.address in active_addresses:
            logging.info("已跳过正在占用的代理：%s", mask_proxy_for_log(lease.address))
            continue
        free_pool_candidates.append(lease)
    if free_pool_candidates:
        cursor = max(0, int(getattr(ctx, "free_proxy_pool_cursor", 0) or 0)) % len(free_pool_candidates)
        selected_lease = free_pool_candidates[cursor]
        ctx.free_proxy_pool_cursor = (cursor + 1) % len(free_pool_candidates)
        return selected_lease

    queue = list(non_free_items)
    remaining: list[Any] = []
    selected_lease: Optional[ProxyLease] = None
    while queue:
        item = queue.pop(0)
        lease = coerce_proxy_lease(item)
        if lease is None:
            continue
        if lease.address in excluded:
            continue
        if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=required_ttl):
            logging.info("已跳过即将过期的代理：%s", mask_proxy_for_log(lease.address))
            continue
        if ctx._is_proxy_in_cooldown_locked(lease.address):
            logging.info("已跳过冷却中的代理：%s", mask_proxy_for_log(lease.address))
            continue
        if lease.address in active_addresses:
            logging.info("已跳过正在占用的代理：%s", mask_proxy_for_log(lease.address))
            continue
        if lease.address in successful_addresses:
            logging.info("已跳过已成功使用过的代理：%s", mask_proxy_for_log(lease.address))
            continue
        selected_lease = lease
        break
    remaining = queue
    ctx.config.proxy_ip_pool = free_pool_items + remaining
    return selected_lease


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


def _lease_needs_preuse_recheck(lease: Optional[ProxyLease]) -> bool:
    source = str(getattr(lease, "source", "") or "").strip().lower()
    return source in _PUBLIC_PROXY_RECHECK_SOURCES


def _lease_skips_generic_connect_check(lease: Optional[ProxyLease]) -> bool:
    return _lease_is_free_pool(lease)


def _lease_is_public_proxy(lease: Optional[ProxyLease]) -> bool:
    return _lease_source(lease) in _PUBLIC_PROXY_SOURCES


def _proxy_address_is_public_source(ctx: ExecutionState, proxy_address: str) -> bool:
    normalized = str(proxy_address or "").strip()
    if not normalized:
        return False
    with ctx.lock:
        for item in list(ctx.config.proxy_ip_pool or []):
            lease = coerce_proxy_lease(item)
            if lease is not None and lease.address == normalized:
                return _lease_is_public_proxy(lease)
        for lease in list(ctx.proxy_in_use_by_thread.values()):
            if lease is not None and str(getattr(lease, "address", "") or "").strip() == normalized:
                return _lease_is_public_proxy(lease)
    return False


def _lease_passes_preuse_recheck(ctx: ExecutionState, lease: Optional[ProxyLease]) -> bool:
    if lease is None or not _lease_needs_preuse_recheck(lease):
        return True
    timeout_seconds = _PUBLIC_PROXY_RECHECK_TIMEOUT_SECONDS
    if _lease_is_free_pool(lease):
        try:
            timeout_seconds = max(
                0.001,
                int(
                    getattr(
                        ctx.config,
                        "free_proxy_pool_probe_timeout_ms",
                        FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS,
                    )
                    or FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS
                )
                / 1000.0,
            )
        except Exception:
            timeout_seconds = FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS / 1000.0
    if is_http_proxy_connect_responsive(
        lease.address,
        target_url=str(getattr(ctx.config, "url", "") or ""),
        timeout=timeout_seconds,
        log_failures=False,
        log_success=False,
    ):
        return True
    if _lease_is_free_pool(lease):
        logging.warning("自由 IP 池代理使用前快检失败，本次跳过并继续轮循：%s", mask_proxy_for_log(lease.address))
    else:
        logging.warning("代理使用前快检失败，已丢弃：%s", mask_proxy_for_log(lease.address))
    _mark_proxy_temporarily_bad(ctx, lease.address, cooldown_seconds=_BAD_PROXY_COOLDOWN_SECONDS)
    return False


def _resolve_proxy_request_num_locked(ctx: ExecutionState) -> int:
    waiting_count = max(1, int(ctx.proxy_waiting_threads or 0))
    active_count = len(ctx.proxy_in_use_by_thread)
    remaining_to_start = max(0, int(ctx.config.target_num or 0) - int(ctx.cur_num or 0) - active_count)
    if remaining_to_start <= 0:
        return 0
    return max(1, min(waiting_count, remaining_to_start, 200))


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
    current_source = str(getattr(ctx.config, "proxy_source", "") or "").strip().lower()
    selected: Optional[ProxyLease] = None
    preuse_failed_addresses: set[str] = set()
    with ctx.lock:
        selected = _pop_available_proxy_lease_locked(ctx, exclude_addresses=preuse_failed_addresses)
    if selected is not None:
        if _lease_passes_preuse_recheck(ctx, selected):
            return _mark_proxy_in_use(ctx, thread_name, selected)
        preuse_failed_addresses.add(selected.address)
        selected = None

    ctx.register_proxy_waiter()
    try:
        while True:
            if _should_stop_proxy_wait(ctx, stop_signal):
                return None
            with ctx.lock:
                selected = _pop_available_proxy_lease_locked(ctx, exclude_addresses=preuse_failed_addresses)
            if selected is not None:
                if _lease_passes_preuse_recheck(ctx, selected):
                    return _mark_proxy_in_use(ctx, thread_name, selected)
                preuse_failed_addresses.add(selected.address)
                selected = None
                if current_source == _FREE_PROXY_POOL_SOURCE:
                    continue

            if current_source == _FREE_PROXY_POOL_SOURCE:
                with ctx.lock:
                    active_free_pool_addresses = {
                        str(getattr(lease, "address", "") or "").strip()
                        for lease in list(ctx.proxy_in_use_by_thread.values())
                        if _lease_is_free_pool(lease) and str(getattr(lease, "address", "") or "").strip()
                    }
                if not active_free_pool_addresses:
                    return None
                if not wait:
                    return None
                if _wait_for_next_proxy_cycle(ctx, stop_signal):
                    return None
                continue

            # 代理池为空时，使用全局 fetch 锁避免多线程并发重复请求代理 API（会快速耗尽额度）
            with ctx._proxy_fetch_lock:
                with ctx.lock:
                    selected = _pop_available_proxy_lease_locked(ctx, exclude_addresses=preuse_failed_addresses)
                    if selected is None:
                        request_num = _resolve_proxy_request_num_locked(ctx)
                    else:
                        request_num = 0
                if selected is not None:
                    if _lease_passes_preuse_recheck(ctx, selected):
                        return _mark_proxy_in_use(ctx, thread_name, selected)
                    preuse_failed_addresses.add(selected.address)
                    selected = None
                    if current_source == _FREE_PROXY_POOL_SOURCE:
                        continue

                if request_num > 0:
                    try:
                        fetched = prefetch_proxy_pool(
                            expected_count=request_num,
                            stop_signal=ctx.stop_event,
                            probe_timeout_ms=max(
                                1,
                                int(
                                    getattr(
                                        ctx.config,
                                        "free_proxy_pool_probe_timeout_ms",
                                        FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS,
                                    )
                                    or FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS
                                ),
                            )
                            if str(getattr(ctx.config, "proxy_source", "") or "").strip().lower() == _FREE_PROXY_POOL_SOURCE
                            else None,
                            target_url=str(getattr(ctx.config, "url", "") or ""),
                        )
                    except Exception as exc:
                        logging.warning(f"获取随机代理失败：{exc}")
                        fetched = None
                    if fetched:
                        selected = None
                        with ctx.lock:
                            _purge_unusable_proxy_pool_locked(ctx)
                            _pool_leases = [coerce_proxy_lease(item) for item in ctx.config.proxy_ip_pool]
                            existing = {lease.address for lease in _pool_leases if lease is not None}
                            active_addresses = _active_proxy_addresses_locked(ctx)
                            successful_addresses = ctx.successful_proxy_addresses_locked()
                            required_ttl = _required_proxy_ttl_seconds(ctx)
                            for item in fetched:
                                lease = coerce_proxy_lease(item)
                                if lease is None:
                                    continue
                                if not _lease_is_free_pool(lease) and not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=required_ttl):
                                    logging.info("已丢弃即将过期的新代理：%s", mask_proxy_for_log(lease.address))
                                    continue
                                if not _lease_is_free_pool(lease) and ctx._is_proxy_in_cooldown_locked(lease.address):
                                    logging.info("已跳过冷却中的新代理：%s", mask_proxy_for_log(lease.address))
                                    continue
                                if selected is None:
                                    blocked_for_selection = set(active_addresses)
                                    if not _lease_is_free_pool(lease):
                                        blocked_for_selection.update(successful_addresses)
                                    if lease.address in blocked_for_selection:
                                        logging.info("已跳过重复或正在占用的新代理：%s", mask_proxy_for_log(lease.address))
                                        continue
                                    selected = lease
                                    existing.add(lease.address)
                                    continue
                                if not lease.poolable or lease.address in existing or lease.address in active_addresses:
                                    continue
                                ctx.config.proxy_ip_pool.append(lease)
                                existing.add(lease.address)
                            ctx.notify_runtime_change()
                        if selected is not None:
                            if _lease_passes_preuse_recheck(ctx, selected):
                                return _mark_proxy_in_use(ctx, thread_name, selected)
                            preuse_failed_addresses.add(selected.address)
                            selected = None

            if not wait:
                return None
            with ctx.lock:
                has_buffered_proxy = bool(ctx.config.proxy_ip_pool)
            if not has_buffered_proxy and _wait_for_next_proxy_cycle(ctx, stop_signal):
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
    with ctx.lock:
        removed = False
        normalized = str(proxy_address or "").strip()
        if _proxy_address_has_source_locked(ctx, normalized, _FREE_PROXY_POOL_SOURCE):
            logging.info("免费代理池代理不剔除，保留用于后续随机循环：%s", mask_proxy_for_log(normalized))
            return
        retained = []
        for item in list(ctx.config.proxy_ip_pool or []):
            lease = coerce_proxy_lease(item)
            if lease is None:
                continue
            if lease.address == normalized:
                removed = True
                continue
            retained.append(lease)
        ctx.config.proxy_ip_pool = retained
        if removed:
            logging.info(f"已移除无响应代理：{mask_proxy_for_log(proxy_address)}")
            ctx.notify_runtime_change()


