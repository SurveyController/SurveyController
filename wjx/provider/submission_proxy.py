"""问卷星无头提交代理切换。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional
from urllib.parse import quote, urlparse

import httpx

from software.app.config import get_proxy_auth
from software.core.task import ExecutionState, ProxyLease
from software.network.browser import BrowserDriver
from software.network.proxy import (
    PROXY_SOURCE_CUSTOM,
    get_proxy_required_ttl_seconds,
    get_proxy_source,
    proxy_lease_has_sufficient_ttl,
)
from software.network.proxy.api import fetch_proxy_batch
from software.network.proxy.pool import coerce_proxy_lease, mask_proxy_for_log, normalize_proxy_address

_HEADLESS_SUBMIT_RETRYABLE_ERRORS = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
)
_SUBMIT_PROXY_WAIT_POLL_SECONDS = 0.3


def _build_submit_proxy_url(proxy_address: Optional[str]) -> Optional[str]:
    """构造给 httpx 使用的代理 URL，必要时补全认证信息。"""
    normalized = normalize_proxy_address(proxy_address)
    if not normalized:
        return None

    try:
        parsed = urlparse(normalized)
    except Exception:
        return normalized

    scheme = str(parsed.scheme or "http").lower()
    host = str(parsed.hostname or "").strip()
    if not host:
        return normalized
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    host_port = f"{host}:{parsed.port}" if parsed.port else host

    username = parsed.username
    password = parsed.password
    if not username and get_proxy_source() == PROXY_SOURCE_CUSTOM:
        try:
            auth = get_proxy_auth()
            username, password = auth.split(":", 1)
        except Exception:
            username = None
            password = None

    if username:
        user = quote(str(username), safe="")
        pwd = quote("" if password is None else str(password), safe="")
        netloc = f"{user}:{pwd}@{host_port}"
    else:
        netloc = host_port

    return f"{scheme}://{netloc}"


def _is_retryable_submit_proxy_error(exc: BaseException) -> bool:
    return isinstance(exc, _HEADLESS_SUBMIT_RETRYABLE_ERRORS)


def _required_submit_proxy_ttl_seconds(ctx: Optional[ExecutionState]) -> int:
    if ctx is None:
        return 20
    return int(get_proxy_required_ttl_seconds(getattr(ctx.config, "answer_duration_range_seconds", (0, 0))))


def _remove_proxy_from_ctx_pool(ctx: ExecutionState, proxy_address: Optional[str]) -> bool:
    normalized = normalize_proxy_address(proxy_address)
    if not normalized:
        return False

    removed = False
    with ctx.lock:
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
    return removed


def _active_proxy_addresses_locked(ctx: ExecutionState, *, exclude_thread_name: str = "") -> set[str]:
    return ctx.active_proxy_addresses_locked(exclude_thread_name=exclude_thread_name)


def _mark_submit_proxy_in_use(
    ctx: ExecutionState,
    driver: BrowserDriver,
    proxy_address: Optional[str],
    *,
    source: str = "submit_replacement",
) -> None:
    normalized = normalize_proxy_address(proxy_address)
    thread_name = str(getattr(driver, "_thread_name", "") or "").strip()
    if not normalized or not thread_name:
        return
    ctx.mark_submit_proxy_in_use(
        thread_name,
        ProxyLease(address=normalized, poolable=False, source=source),
    )


def _pop_replacement_proxy_from_pool_locked(
    ctx: ExecutionState,
    current_proxy: Optional[str],
    *,
    exclude_thread_name: str = "",
) -> Optional[ProxyLease]:
    required_ttl = _required_submit_proxy_ttl_seconds(ctx)
    current = normalize_proxy_address(current_proxy)
    active_addresses = _active_proxy_addresses_locked(ctx, exclude_thread_name=exclude_thread_name)
    retained = []
    selected: Optional[ProxyLease] = None
    for item in list(ctx.config.proxy_ip_pool or []):
        lease = coerce_proxy_lease(item)
        if lease is None:
            continue
        if lease.address == current:
            continue
        if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=required_ttl):
            logging.info("已丢弃即将过期的提交代理：%s", mask_proxy_for_log(lease.address))
            continue
        if lease.address in active_addresses:
            logging.info("已跳过正在被其他会话占用的提交代理：%s", mask_proxy_for_log(lease.address))
            continue
        if selected is None:
            selected = lease
            continue
        retained.append(lease)
    ctx.config.proxy_ip_pool = retained
    return selected


def _acquire_replacement_submit_proxy(
    driver: BrowserDriver,
    ctx: Optional[ExecutionState],
    *,
    stop_signal: Optional[threading.Event],
    wait_for_replacement: bool = False,
) -> Optional[str]:
    if ctx is None or not bool(getattr(ctx.config, "random_proxy_ip_enabled", False)):
        return None
    if stop_signal and stop_signal.is_set():
        return None

    current_proxy = normalize_proxy_address(getattr(driver, "_submit_proxy_address", None))
    thread_name = str(getattr(driver, "_thread_name", "") or "").strip()
    removed_from_pool = _remove_proxy_from_ctx_pool(ctx, current_proxy)
    if current_proxy:
        logging.warning("无头提交代理疑似失效，已废弃：%s", mask_proxy_for_log(current_proxy))
    elif removed_from_pool:
        logging.info("已从代理池移除重复的失效提交代理")

    should_wait = bool(wait_for_replacement)
    while True:
        if stop_signal and stop_signal.is_set():
            return None

        with ctx.lock:
            candidate = _pop_replacement_proxy_from_pool_locked(
                ctx,
                current_proxy,
                exclude_thread_name=thread_name,
            )
        if candidate is not None:
            setattr(driver, "_submit_proxy_address", candidate.address)
            _mark_submit_proxy_in_use(ctx, driver, candidate.address, source=str(candidate.source or "submit_pool"))
            logging.info("无头提交改用代理池中的新代理：%s", mask_proxy_for_log(candidate.address))
            return candidate.address

        with ctx._proxy_fetch_lock:
            with ctx.lock:
                candidate = _pop_replacement_proxy_from_pool_locked(
                    ctx,
                    current_proxy,
                    exclude_thread_name=thread_name,
                )
            if candidate is not None:
                setattr(driver, "_submit_proxy_address", candidate.address)
                _mark_submit_proxy_in_use(ctx, driver, candidate.address, source=str(candidate.source or "submit_pool"))
                logging.info("无头提交改用代理池中的新代理：%s", mask_proxy_for_log(candidate.address))
                return candidate.address

            if stop_signal and stop_signal.is_set():
                return None

            try:
                fetched = fetch_proxy_batch(expected_count=1, stop_signal=stop_signal)
            except Exception as exc:
                logging.warning("无头提交切换新代理失败：%s", exc)
                fetched = None
            active_addresses = ctx.snapshot_active_proxy_addresses(exclude_thread_name=thread_name)
            for item in fetched or []:
                lease = coerce_proxy_lease(item)
                candidate = lease.address if lease is not None else ""
                if not candidate or candidate == current_proxy:
                    continue
                if candidate in active_addresses:
                    logging.info("已跳过正在被其他会话占用的新提交代理：%s", mask_proxy_for_log(candidate))
                    continue
                if not proxy_lease_has_sufficient_ttl(lease, required_ttl_seconds=_required_submit_proxy_ttl_seconds(ctx)):
                    logging.info("已跳过即将过期的新提交代理：%s", mask_proxy_for_log(candidate))
                    continue
                setattr(driver, "_submit_proxy_address", candidate)
                _mark_submit_proxy_in_use(ctx, driver, candidate, source=str(getattr(lease, "source", "") or "submit_fetch"))
                logging.info("无头提交已切换为新提取代理：%s", mask_proxy_for_log(candidate))
                return candidate

        if not should_wait:
            return None
        if stop_signal and stop_signal.wait(_SUBMIT_PROXY_WAIT_POLL_SECONDS):
            return None
        if not stop_signal:
            time.sleep(_SUBMIT_PROXY_WAIT_POLL_SECONDS)
    return None


__all__ = [
    "_acquire_replacement_submit_proxy",
    "_build_submit_proxy_url",
    "_is_retryable_submit_proxy_error",
]
