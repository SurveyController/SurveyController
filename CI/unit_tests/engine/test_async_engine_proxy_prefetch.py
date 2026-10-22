from __future__ import annotations

import asyncio

import pytest

import software.core.engine.async_engine as async_engine
from software.core.task import ExecutionConfig, ExecutionState, ProxyLease

from .async_engine_fakes import build_engine


class AsyncRuntimeEngineProxyPrefetchTests:
    @pytest.mark.asyncio
    async def test_run_without_waiting_slots_does_not_prefetch_proxy_pool(self, monkeypatch) -> None:
        engine = build_engine()
        config = ExecutionConfig(
            num_threads=2,
            target_num=5,
            random_proxy_ip_enabled=True,
            survey_provider="wjx",
        )
        state = ExecutionState(config=config)
        events: list[str] = []
        loading_calls: list[tuple[bool, str]] = []

        class _FakeRunner:
            def __init__(self, **kwargs) -> None:
                self.slot_id = kwargs["slot_id"]

            async def run(self) -> None:
                events.append(f"slot-{self.slot_id}")

        class _FakeScheduler:
            def __init__(self, *, concurrency: int) -> None:
                self.concurrency = concurrency

            async def close(self) -> None:
                events.append("scheduler-close")

        class _FakeBridge:
            def set_random_ip_loading(self, loading: bool, message: str = "") -> None:
                loading_calls.append((bool(loading), str(message or "")))

        async def fake_fetch_proxy_batch_async(**kwargs):
            events.append(f"fetch-{kwargs['expected_count']}")
            await asyncio.sleep(0)
            return [
                ProxyLease(address="http://1.1.1.1:8000"),
                ProxyLease(address="http://2.2.2.2:8000"),
            ][: int(kwargs["expected_count"])]

        monkeypatch.setattr(async_engine, "AsyncScheduler", _FakeScheduler)
        monkeypatch.setattr(async_engine, "AsyncSlotRunner", _FakeRunner)
        monkeypatch.setattr(async_engine, "fetch_proxy_batch_async", fake_fetch_proxy_batch_async)

        await engine._run(config=config, state=state, runtime_bridge=_FakeBridge())

        assert "slot-1" in events
        assert "slot-2" in events
        assert not any(event.startswith("fetch-") for event in events)
        assert list(state.config.proxy_ip_pool) == []
        assert loading_calls == []

    @pytest.mark.asyncio
    async def test_run_keeps_prefetching_proxy_pool_after_first_batch_is_consumed(self, monkeypatch) -> None:
        engine = build_engine()
        config = ExecutionConfig(
            num_threads=2,
            target_num=5,
            random_proxy_ip_enabled=True,
            survey_provider="wjx",
        )
        state = ExecutionState(config=config)
        fetch_counts: list[int] = []

        class _FakeRunner:
            def __init__(self, **_kwargs) -> None:
                pass

            async def run(self) -> None:
                for _idx in range(2):
                    state.register_proxy_waiter()
                    deadline = asyncio.get_running_loop().time() + 1.0
                    try:
                        while not state.config.proxy_ip_pool and asyncio.get_running_loop().time() < deadline:
                            await asyncio.sleep(0.01)
                        with state.lock:
                            if state.config.proxy_ip_pool:
                                state.config.proxy_ip_pool.popleft()
                                state.cur_num += 1
                        state.notify_runtime_change()
                        await asyncio.sleep(0)
                    finally:
                        state.unregister_proxy_waiter()

        class _FakeScheduler:
            def __init__(self, *, concurrency: int) -> None:
                self.concurrency = concurrency

            async def close(self) -> None:
                return None

        async def fake_fetch_proxy_batch_async(**kwargs):
            fetch_counts.append(kwargs["expected_count"])
            await asyncio.sleep(0)
            start = sum(fetch_counts)
            return [
                ProxyLease(address=f"http://10.0.0.{start + idx}:8000")
                for idx in range(max(1, int(kwargs["expected_count"])))
            ]

        monkeypatch.setattr(async_engine, "AsyncScheduler", _FakeScheduler)
        monkeypatch.setattr(async_engine, "AsyncSlotRunner", _FakeRunner)
        monkeypatch.setattr(async_engine, "fetch_proxy_batch_async", fake_fetch_proxy_batch_async)
        monkeypatch.setattr(async_engine, "wait_for_proxy_prefetch_cycle", lambda *_args, **_kwargs: asyncio.sleep(0, result=False))

        await engine._run(config=config, state=state, runtime_bridge=None)

        assert len(fetch_counts) >= 2
        assert state.cur_num == 4

    @pytest.mark.asyncio
    async def test_run_async_proxy_prefetch_does_not_write_after_stop(self, monkeypatch) -> None:
        engine = build_engine()
        config = ExecutionConfig(
            num_threads=1,
            target_num=3,
            random_proxy_ip_enabled=True,
            survey_provider="wjx",
        )
        state = ExecutionState(config=config)

        class _FakeRunner:
            def __init__(self, **_kwargs) -> None:
                pass

            async def run(self) -> None:
                state.stop_event.set()

        class _FakeScheduler:
            def __init__(self, *, concurrency: int) -> None:
                self.concurrency = concurrency

            async def close(self) -> None:
                return None

        async def fake_fetch_proxy_batch_async(**_kwargs):
            state.stop_event.set()
            return [ProxyLease(address="http://1.1.1.1:8000")]

        monkeypatch.setattr(async_engine, "AsyncScheduler", _FakeScheduler)
        monkeypatch.setattr(async_engine, "AsyncSlotRunner", _FakeRunner)
        monkeypatch.setattr(async_engine, "fetch_proxy_batch_async", fake_fetch_proxy_batch_async)

        await engine._run(config=config, state=state, runtime_bridge=None)

        assert list(state.config.proxy_ip_pool) == []

    @pytest.mark.asyncio
    async def test_run_async_proxy_prefetch_rechecks_demand_after_lock(self, monkeypatch) -> None:
        engine = build_engine()
        config = ExecutionConfig(
            num_threads=1,
            target_num=1,
            random_proxy_ip_enabled=True,
            survey_provider="wjx",
        )
        state = ExecutionState(config=config)
        fetch_counts: list[int] = []

        class _FakeRunner:
            def __init__(self, **_kwargs) -> None:
                pass

            async def run(self) -> None:
                state.register_proxy_waiter()
                try:
                    await asyncio.sleep(0)
                    with state.lock:
                        state.config.proxy_ip_pool.append(ProxyLease(address="http://9.9.9.9:8000"))
                    state.notify_runtime_change()
                    await asyncio.sleep(0.05)
                    with state.lock:
                        if state.config.proxy_ip_pool:
                            state.config.proxy_ip_pool.popleft()
                            state.cur_num = 1
                    state.notify_runtime_change()
                finally:
                    state.unregister_proxy_waiter()

        class _FakeScheduler:
            def __init__(self, *, concurrency: int) -> None:
                self.concurrency = concurrency

            async def close(self) -> None:
                return None

        async def fake_fetch_proxy_batch_async(**kwargs):
            fetch_counts.append(int(kwargs["expected_count"]))
            return [ProxyLease(address="http://1.1.1.1:8000")]

        monkeypatch.setattr(async_engine, "AsyncScheduler", _FakeScheduler)
        monkeypatch.setattr(async_engine, "AsyncSlotRunner", _FakeRunner)
        monkeypatch.setattr(async_engine, "fetch_proxy_batch_async", fake_fetch_proxy_batch_async)
        monkeypatch.setattr(async_engine, "_acquire_proxy_fetch_lock_async", lambda *_args, **_kwargs: asyncio.sleep(0.02, result=True))

        def fake_recheck(_state):
            return 0 if list(state.config.proxy_ip_pool) else 1

        recheck_calls = {"count": 0}

        def resolve_count(_state):
            recheck_calls["count"] += 1
            if recheck_calls["count"] == 1:
                return 1
            return fake_recheck(_state)

        monkeypatch.setattr(async_engine, "resolve_proxy_prefetch_request_count", resolve_count)
        monkeypatch.setattr(async_engine, "wait_for_proxy_prefetch_cycle", lambda *_args, **_kwargs: asyncio.sleep(0, result=False))

        await engine._run(config=config, state=state, runtime_bridge=None)

        assert fetch_counts == []
