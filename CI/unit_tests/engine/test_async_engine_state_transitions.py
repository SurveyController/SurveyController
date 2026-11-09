from __future__ import annotations

import asyncio
import concurrent.futures
import threading

import pytest

import software.core.engine.async_engine as async_engine
from software.core.engine.async_engine import AsyncRuntimeEngine
from software.core.task import ExecutionConfig, ExecutionState
from software.network.proxy.api import ProxyApiFatalError


@pytest.mark.parametrize("control", ["stop", "pause", "pause_resume"])
def test_pending_run_preserves_controls(monkeypatch, control: str) -> None:
    engine = AsyncRuntimeEngine()
    config = ExecutionConfig(num_threads=1)
    state = ExecutionState(config=config)
    loop_blocked = threading.Event()
    release_loop = threading.Event()
    observed = []

    class Runner:
        def __init__(self, **kwargs) -> None:
            self.context = kwargs["run_context"]

        async def run(self) -> None:
            observed.append(
                (
                    self.context.stop_requested(),
                    state.stop_event.is_set(),
                    self.context.pause_event.is_set(),
                )
            )

    def block_loop() -> None:
        loop_blocked.set()
        release_loop.wait(3.0)

    monkeypatch.setattr(async_engine, "AsyncSlotRunner", Runner)
    try:
        engine.start()
        engine._loop.call_soon_threadsafe(block_loop)
        assert loop_blocked.wait(1.0)
        future = engine.start_run(config=config, state=state)
        if control == "stop":
            state.stop_event.set()
            engine.stop_run()
        else:
            engine.pause_run()
            if control == "pause_resume":
                engine.resume_run()
        release_loop.set()
        future.result(timeout=2.0)
    finally:
        release_loop.set()
        engine.shutdown(timeout=2.0)

    assert observed == [(control == "stop", control == "stop", control == "pause")]


def test_concurrent_start_accepts_only_one_run(monkeypatch) -> None:
    engine = AsyncRuntimeEngine()
    config = ExecutionConfig()
    first_submit = threading.Event()
    second_submitted = threading.Event()
    release_submit = threading.Event()
    futures = []
    errors = []
    submitted = []

    def submit(coro):
        coro.close()
        submitted.append(coro)
        if len(submitted) == 1:
            first_submit.set()
            assert release_submit.wait(3.0)
        else:
            second_submitted.set()
        return concurrent.futures.Future()

    def start() -> None:
        try:
            futures.append(engine.start_run(config=config, state=ExecutionState(config=config)))
        except RuntimeError as exc:
            errors.append(str(exc))

    monkeypatch.setattr(engine, "_submit", submit)
    first = threading.Thread(target=start)
    second = threading.Thread(target=start)
    first.start()
    try:
        assert first_submit.wait(1.0)
        second.start()
        second_submitted.wait(0.2)
    finally:
        release_submit.set()
        first.join(timeout=2.0)
        if second.ident is not None:
            second.join(timeout=2.0)

    assert not first.is_alive() and not second.is_alive()
    assert len(futures) == 1
    assert len(errors) == 1 and "运行中" in errors[0]
    assert len(submitted) == 1


@pytest.mark.asyncio
async def test_fatal_proxy_prefetch_stops_run_and_releases_fetch_lock(monkeypatch) -> None:
    engine = AsyncRuntimeEngine()
    config = ExecutionConfig(random_proxy_ip_enabled=True, target_num=3)
    state = ExecutionState(config=config)
    state.register_proxy_waiter()
    fetches = []
    released = []
    observed = []

    class Runner:
        def __init__(self, **kwargs) -> None:
            self.context = kwargs["run_context"]

        async def run(self) -> None:
            try:
                await asyncio.wait_for(self.context.stop_event.wait(), timeout=0.2)
            except TimeoutError:
                observed.append(False)
            else:
                observed.append(True)

    async def fetch(**kwargs):
        fetches.append(kwargs)
        raise ProxyApiFatalError("账号额度不足")

    async def wait_cycle(*args):
        await asyncio.sleep(0)
        return True

    monkeypatch.setattr(async_engine, "AsyncSlotRunner", Runner)
    monkeypatch.setattr(async_engine, "fetch_proxy_batch_async", fetch)
    monkeypatch.setattr(async_engine, "wait_for_proxy_prefetch_cycle", wait_cycle)
    real_release = async_engine.release_proxy_fetch_lock

    def release(value) -> None:
        released.append(value)
        real_release(value)

    monkeypatch.setattr(async_engine, "release_proxy_fetch_lock", release)

    try:
        await engine._run(config=config, state=state)
    finally:
        state.unregister_proxy_waiter()

    assert observed == [True]
    assert len(fetches) == 1
    assert released == [state]
    assert state.get_terminal_stop_snapshot() == (
        "proxy_api_error",
        "proxy_unavailable",
        "账号额度不足",
    )
    assert state.stop_event.is_set()
