from __future__ import annotations

import asyncio

import pytest
from surveycore.core.engine.async_events import ThreadEventProxy

from software.core.task import ExecutionConfig, ExecutionState
from software.network import session_policy
from software.network.proxy.api import provider
from software.network.proxy.session.models import RandomIPAuthError


@pytest.fixture
def official_proxy(monkeypatch):
    monkeypatch.setattr(provider, "get_proxy_source", lambda: "default")
    monkeypatch.setattr(provider, "get_proxy_area_code", lambda: "")
    monkeypatch.setattr(provider, "get_proxy_occupy_minute", lambda: 1)
    return ExecutionState(
        config=ExecutionConfig(random_proxy_ip_enabled=True, target_num=2, num_threads=2)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "detail",
    [
        "insufficient_quota",
        "not_authenticated",
        "session_changed",
        "invalid_user_id",
        "user_id_required",
        "unauthorized",
        "device_banned",
        "user_banned",
        "user_expired",
        "device_owned_by_other_user",
        "device_id_required",
        "invalid_request_body",
        "minute_not_allowed",
        "pool_not_allowed",
        "area_not_allowed",
        "invalid_area",
        "invalid_upstream",
        "minute_not_supported_for_idiot",
        "invalid_area_for_idiot",
    ],
)
async def test_official_permanent_error_stops_instead_of_retrying(
    official_proxy, monkeypatch, detail
):
    attempts = 0

    async def denied(**_kwargs):
        nonlocal attempts
        attempts += 1
        raise RandomIPAuthError(detail)

    async def prevent_infinite_retry(*_args, **_kwargs):
        pytest.fail("不可恢复的代理错误仍进入重试等待")

    monkeypatch.setattr(provider, "extract_proxy_async", denied)
    monkeypatch.setattr(session_policy, "_wait_for_next_proxy_cycle_async", prevent_infinite_retry)

    with pytest.raises(provider.ProxyApiFatalError):
        await session_policy.acquire_submit_proxy(
            official_proxy, "Slot-1", stop_signal=official_proxy.stop_event
        )

    assert attempts == 1
    assert official_proxy.stop_event.is_set()
    assert official_proxy.get_terminal_stop_snapshot()[0] == "proxy_api_error"
    assert official_proxy.proxy_waiting_threads == 0
    assert official_proxy.snapshot_active_proxy_addresses() == set()
    assert not session_policy.is_proxy_fetch_in_progress(official_proxy)


@pytest.mark.asyncio
async def test_transient_official_error_can_recover(official_proxy, monkeypatch):
    attempts = 0

    async def extract(**_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RandomIPAuthError("network_error:timeout")
        return {
            "host": "1.1.1.1",
            "port": 8000,
            "account": "unit",
            "password": "unit",
        }

    async def next_cycle(*_args, **_kwargs):
        return False

    monkeypatch.setattr(provider, "extract_proxy_async", extract)
    monkeypatch.setattr(session_policy, "_wait_for_next_proxy_cycle_async", next_cycle)

    lease = await session_policy.acquire_submit_proxy(
        official_proxy, "Slot-1", stop_signal=official_proxy.stop_event
    )

    assert attempts == 2
    assert lease.address == "http://unit:unit@1.1.1.1:8000"
    assert not official_proxy.stop_event.is_set()
    assert official_proxy.get_terminal_stop_snapshot()[0] == ""
    session_policy.release_submit_proxy(official_proxy, "Slot-1", lease.address)
    assert official_proxy.snapshot_active_proxy_addresses() == set()


@pytest.mark.asyncio
async def test_fatal_error_releases_fetch_lock_and_concurrent_waiters(official_proxy, monkeypatch):
    request_started = asyncio.Event()
    return_error = asyncio.Event()
    waiter_waiting = asyncio.Event()
    attempts = 0

    async def denied(**_kwargs):
        nonlocal attempts
        attempts += 1
        request_started.set()
        await return_error.wait()
        raise RandomIPAuthError("insufficient_quota")

    async def next_cycle(ctx, stop_signal, **_kwargs):
        waiter_waiting.set()
        await return_error.wait()
        await asyncio.sleep(0)
        return stop_signal.is_set()

    monkeypatch.setattr(provider, "extract_proxy_async", denied)
    monkeypatch.setattr(session_policy, "_wait_for_next_proxy_cycle_async", next_cycle)

    first = asyncio.create_task(
        session_policy.acquire_submit_proxy(
            official_proxy, "Slot-1", stop_signal=official_proxy.stop_event
        )
    )
    await request_started.wait()
    second = asyncio.create_task(
        session_policy.acquire_submit_proxy(
            official_proxy, "Slot-2", stop_signal=official_proxy.stop_event
        )
    )
    await waiter_waiting.wait()
    return_error.set()
    results = await asyncio.wait_for(
        asyncio.gather(first, second, return_exceptions=True), timeout=1.0
    )

    assert isinstance(results[0], provider.ProxyApiFatalError)
    assert results[1].address is None
    assert attempts == 1
    assert official_proxy.proxy_waiting_threads == 0
    assert official_proxy.snapshot_active_proxy_addresses() == set()
    assert not session_policy.is_proxy_fetch_in_progress(official_proxy)


@pytest.mark.asyncio
async def test_fatal_error_sets_both_thread_and_async_stop_signals(official_proxy, monkeypatch):
    async_stop = asyncio.Event()
    signal = ThreadEventProxy(async_stop, loop=asyncio.get_running_loop())

    async def denied(**_kwargs):
        raise RandomIPAuthError("insufficient_quota")

    monkeypatch.setattr(provider, "extract_proxy_async", denied)

    with pytest.raises(provider.ProxyApiFatalError):
        await session_policy.acquire_submit_proxy(official_proxy, "Slot-1", stop_signal=signal)

    await asyncio.wait_for(async_stop.wait(), timeout=1.0)
    assert official_proxy.stop_event.is_set()
    assert signal.is_set()
    assert official_proxy.get_terminal_stop_snapshot()[0] == "proxy_api_error"
