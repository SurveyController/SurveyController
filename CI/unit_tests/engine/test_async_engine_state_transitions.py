from __future__ import annotations

import concurrent.futures
import threading

import pytest

import software.core.engine.async_engine as async_engine
from software.core.engine.async_engine import AsyncRuntimeEngine
from software.core.task import ExecutionConfig, ExecutionState


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
