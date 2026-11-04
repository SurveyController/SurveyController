from __future__ import annotations

import asyncio
import threading

import pytest

import software.core.engine.async_engine as async_engine
from software.core.engine.async_engine import AsyncRuntimeEngine, EngineState
from software.core.task import ExecutionConfig, ExecutionState


def test_engine_rejects_all_submissions_after_shutdown(monkeypatch) -> None:
    engine = AsyncRuntimeEngine()
    engine.shutdown()
    parsed_coro = asyncio.sleep(0)
    monkeypatch.setattr(async_engine, "parse_survey", lambda _url: parsed_coro)

    with pytest.raises(RuntimeError, match="关闭"):
        engine.submit_ui_task("after-close", lambda: asyncio.sleep(0))
    with pytest.raises(RuntimeError, match="关闭"):
        engine.parse_survey("https://example.test/survey")
    with pytest.raises(RuntimeError, match="关闭"):
        config = ExecutionConfig()
        engine.start_run(config=config, state=ExecutionState(config=config))

    assert parsed_coro.cr_frame is None
    assert engine.engine_state is EngineState.CLOSED


def test_shutdown_timeout_retains_handles_until_loop_exits() -> None:
    engine = AsyncRuntimeEngine()
    task_started = threading.Event()
    release_task = threading.Event()

    async def block_loop_thread() -> None:
        task_started.set()
        release_task.wait(timeout=2.0)

    future = engine.submit_ui_task("blocking-test", lambda: block_loop_thread())
    assert task_started.wait(timeout=1.0)
    thread = engine.thread
    loop = engine._loop
    assert thread is not None
    assert loop is not None

    engine.shutdown(timeout=0.01)

    assert engine.engine_state is EngineState.STOPPING
    assert engine.thread is thread
    assert engine._loop is loop
    with pytest.raises(RuntimeError, match="关闭"):
        engine.submit_ui_task("late-task", lambda: asyncio.sleep(0))

    release_task.set()
    thread.join(timeout=1.0)
    engine.shutdown(timeout=1.0)

    assert not thread.is_alive()
    assert engine.engine_state is EngineState.CLOSED
    assert engine.thread is None
    assert engine._loop is None
    assert future.done() or future.cancelled()


def test_shutdown_cancels_registered_ui_tasks() -> None:
    engine = AsyncRuntimeEngine()
    task_started = threading.Event()
    task_cancelled = threading.Event()

    async def wait_for_shutdown() -> None:
        task_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            task_cancelled.set()

    future = engine.submit_ui_task("cancel-on-shutdown", wait_for_shutdown)
    assert task_started.wait(timeout=1.0)

    engine.shutdown(timeout=2.0)

    assert task_cancelled.is_set()
    assert future.done()
