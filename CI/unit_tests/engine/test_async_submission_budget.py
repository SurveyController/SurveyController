from __future__ import annotations

import asyncio
import threading

import pytest
from surveycore.core.engine.async_events import AsyncRunContext
from surveycore.core.engine.async_scheduler import AsyncScheduler

import software.core.engine.async_http_submitter as submitter
from software.core.engine.async_engine import AsyncRuntimeEngine
from software.core.engine.async_runtime_loop import AsyncSlotRunner
from software.core.engine.task_registry import TaskRegistry
from software.core.task import ExecutionConfig, ExecutionState
from software.providers.contracts import ProviderSubmissionResult


@pytest.mark.parametrize(
    ("target", "workers", "initial", "failures"),
    [(1, 2, 0, 0), (3, 2, 0, 0), (5, 3, 0, 0), (5, 3, 3, 0), (1, 2, 0, 1)],
)
@pytest.mark.asyncio
async def test_submission_budget_bounds_accepted_requests(
    monkeypatch, target: int, workers: int, initial: int, failures: int
) -> None:
    engine = AsyncRuntimeEngine()
    config = ExecutionConfig(
        num_threads=workers,
        target_num=target,
        url="https://www.wjx.cn/vm/local.aspx",
    )
    state = ExecutionState(config=config, cur_num=initial)
    attempts = []
    accepted = []

    async def fill(*args, **kwargs):
        attempt = len(attempts)
        attempts.append(kwargs["thread_name"])
        await asyncio.sleep(0)
        if attempt < failures:
            raise RuntimeError("本地模拟提交失败")
        accepted.append(kwargs["thread_name"])
        return ProviderSubmissionResult(provider="wjx", submitted=True)

    monkeypatch.setattr(submitter, "fill_survey_http", fill)

    await asyncio.wait_for(engine._run(config=config, state=state), timeout=2.0)

    assert len(accepted) == target - initial
    assert len(attempts) == target - initial + failures
    assert state.cur_num == target
    assert state.get_terminal_stop_snapshot()[0] == "target_reached"
    assert all(not progress.running for progress in state.thread_progress.values())


@pytest.mark.asyncio
async def test_inflight_successes_are_committed_after_stop(monkeypatch) -> None:
    engine = AsyncRuntimeEngine()
    config = ExecutionConfig(
        num_threads=2,
        target_num=3,
        url="https://www.wjx.cn/vm/local.aspx",
    )
    state = ExecutionState(config=config)
    all_started = asyncio.Event()
    release_responses = asyncio.Event()
    requests = []

    async def fill(*args, **kwargs):
        requests.append(kwargs["thread_name"])
        if len(requests) == 2:
            all_started.set()
        await release_responses.wait()
        return ProviderSubmissionResult(provider="wjx", submitted=True)

    monkeypatch.setattr(submitter, "fill_survey_http", fill)
    run = asyncio.create_task(engine._run(config=config, state=state))
    try:
        await asyncio.wait_for(all_started.wait(), timeout=1.0)
        state.mark_terminal_stop("user_stopped")
        state.stop_event.set()
        engine._stop_event.set()
        release_responses.set()
        await asyncio.wait_for(run, timeout=2.0)
    finally:
        release_responses.set()
        if not run.done():
            run.cancel()
        await asyncio.gather(run, return_exceptions=True)

    assert len(requests) == 2
    assert state.cur_num == 2
    assert state.get_terminal_stop_snapshot()[0] == "user_stopped"


def test_stop_wakes_runner_waiting_for_submit_interval(monkeypatch) -> None:
    engine = AsyncRuntimeEngine()
    config = ExecutionConfig(
        num_threads=1,
        target_num=2,
        submit_interval_range_seconds=(60, 60),
        url="https://www.wjx.cn/vm/local.aspx",
    )
    state = ExecutionState(config=config)
    waiting_dispatch = threading.Event()
    requests = []
    original_acquire = AsyncScheduler.acquire

    async def acquire(scheduler):
        if state.cur_num == 1:
            waiting_dispatch.set()
        return await original_acquire(scheduler)

    async def fill(*args, **kwargs):
        requests.append(kwargs["thread_name"])
        return ProviderSubmissionResult(provider="wjx", submitted=True)

    monkeypatch.setattr(AsyncScheduler, "acquire", acquire)
    monkeypatch.setattr(submitter, "fill_survey_http", fill)
    try:
        future = engine.start_run(config=config, state=state)
        assert waiting_dispatch.wait(1.0)
        engine.stop_run()
        future.result(timeout=0.2)
    finally:
        engine.shutdown(timeout=0.2)

    assert requests == ["Slot-1"]
    assert state.cur_num == 1
    assert not state.thread_progress["Slot-1"].running


@pytest.mark.parametrize("cancel_at", ["", "acquire", "cleanup"])
@pytest.mark.asyncio
async def test_dispatch_wait_retires_token_when_stop_or_cancel_wins(monkeypatch, cancel_at) -> None:
    existing_tasks = set(asyncio.all_tasks())
    config = ExecutionConfig(url="https://www.wjx.cn/vm/local.aspx", target_num=2)
    state = ExecutionState(config=config)
    stop_event = asyncio.Event()
    context = AsyncRunContext(state=state, stop_event=stop_event, pause_event=asyncio.Event())
    scheduler = AsyncScheduler(concurrency=1)
    registry = TaskRegistry()
    runner = AsyncSlotRunner(
        slot_id=1,
        config=config,
        state=state,
        run_context=context,
        scheduler=scheduler,
        task_registry=registry,
    )
    acquired = asyncio.Event()
    requests = []
    releases = []
    original_acquire = scheduler.acquire
    original_release = scheduler.release
    original_stop_wait = stop_event.wait

    async def acquire():
        token_id = await original_acquire()
        acquired.set()
        if cancel_at == "acquire":
            task.cancel()
        elif not cancel_at:
            stop_event.set()
        return token_id

    async def wait_for_stop():
        try:
            await original_stop_wait()
        finally:
            task.cancel()

    async def release(token_id, **kwargs):
        releases.append((token_id, kwargs["requeue"]))
        await original_release(token_id, **kwargs)

    async def fill(*args, **kwargs):
        requests.append(kwargs["thread_name"])
        return ProviderSubmissionResult(provider="wjx", submitted=True)

    monkeypatch.setattr(scheduler, "acquire", acquire)
    monkeypatch.setattr(scheduler, "release", release)
    monkeypatch.setattr(submitter, "fill_survey_http", fill)
    if cancel_at == "cleanup":
        monkeypatch.setattr(stop_event, "wait", wait_for_stop)
    task = asyncio.create_task(runner.run())
    try:
        await asyncio.wait_for(acquired.wait(), timeout=1.0)
        if cancel_at:
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await asyncio.wait_for(task, timeout=0.2)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await scheduler.close()
        await registry.drain()

    assert requests == []
    assert releases == [(0, False)]
    assert not (set(asyncio.all_tasks()) - existing_tasks)
