from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from surveycore.core.engine.async_events import AsyncRunContext
from surveycore.core.engine.async_scheduler import AsyncScheduler
from surveycore.core.reverse_fill.schema import ReverseFillSampleRow, ReverseFillSpec

from software.core.engine.async_runtime_loop import AsyncSlotRunner
from software.core.engine.task_registry import TaskRegistry
from software.core.task import ExecutionConfig, ExecutionState
from software.network.proxy.api import ProxyApiFatalError
from software.providers.contracts import ProviderSubmissionRejectedError


def build_runner():
    config = ExecutionConfig(
        url="https://v.wjx.cn/vm/local.aspx",
        target_num=1,
        num_threads=1,
        stop_on_fail_enabled=False,
        reverse_fill_spec=ReverseFillSpec(
            source_path="local.xlsx",
            selected_format="wjx_sequence",
            detected_format="wjx_sequence",
            start_row=1,
            total_samples=1,
            available_samples=1,
            target_num=1,
            samples=[ReverseFillSampleRow(data_row_number=1, worksheet_row_number=2)],
        ),
    )
    state = ExecutionState(config=config)
    state.initialize_reverse_fill_runtime()
    state.ensure_worker_threads(1, prefix="Slot")
    scheduler = AsyncScheduler(concurrency=1)
    context = AsyncRunContext(state=state, stop_event=asyncio.Event(), pause_event=asyncio.Event())
    runner = AsyncSlotRunner(
        slot_id=1,
        config=config,
        state=state,
        run_context=context,
        scheduler=scheduler,
        task_registry=TaskRegistry(),
    )
    return runner, state, scheduler


@pytest.mark.asyncio
async def test_explicit_rejection_exhausts_sample_after_one_retry(monkeypatch):
    runner, state, scheduler = build_runner()
    attempted_rows = []

    async def reject(**kwargs):
        attempted_rows.append(state.reverse_fill_runtime.reserved_row_by_thread["Slot-1"])
        if len(attempted_rows) == 3:
            runner.run_context.stop_event.set()
        raise ProviderSubmissionRejectedError("提交内容不符合问卷要求")

    monkeypatch.setattr(runner.http_submitter, "submit", reject)
    try:
        await asyncio.wait_for(runner.run(), timeout=2)
        assert attempted_rows == [1, 1]
        assert state.reverse_fill_runtime.discarded_row_numbers == {1}
        assert state.get_terminal_stop_snapshot()[0] == "reverse_fill_exhausted"
        assert not state.reverse_fill_runtime.reserved_row_by_thread
        assert state.cur_num == 0
    finally:
        await scheduler.close()


@pytest.mark.asyncio
async def test_fatal_proxy_failure_stops_slot_when_failure_stop_is_disabled(monkeypatch):
    runner, state, scheduler = build_runner()
    calls = 0

    async def denied(**kwargs):
        nonlocal calls
        calls += 1
        state.mark_terminal_stop("proxy_api_error", failure_reason="proxy_unavailable")
        state.stop_event.set()
        raise ProxyApiFatalError("额度不足")

    monkeypatch.setattr(runner.http_submitter, "submit", denied)
    try:
        await asyncio.wait_for(runner.run(), timeout=2)
        assert calls == 1
        assert runner.run_context.stop_requested()
        assert state.cur_fail == 0
        assert state.get_terminal_stop_snapshot()[0] == "proxy_api_error"
        assert not state.reverse_fill_runtime.reserved_row_by_thread
        assert not state.snapshot_thread_progress()[0]["running"]
    finally:
        await scheduler.close()


@pytest.mark.asyncio
async def test_transient_failure_requeues_sample_without_consuming_retry(monkeypatch):
    runner, state, scheduler = build_runner()
    calls = 0

    async def submit(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("临时准备失败")
        return True

    monkeypatch.setattr(runner.http_submitter, "submit", submit)
    try:
        await asyncio.wait_for(runner.run(), timeout=2)
        assert calls == 2
        assert state.cur_num == 1
        assert state.reverse_fill_runtime.failure_count_by_row == {}
        assert not state.reverse_fill_runtime.discarded_row_numbers
    finally:
        await scheduler.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["preparing", "submitting"])
async def test_cancellation_releases_samples_and_finishes_slot(monkeypatch, stage):
    runner, state, scheduler = build_runner()
    runner.config.joint_psychometric_answer_plan = SimpleNamespace(sample_count=1)
    entered = asyncio.Event()

    async def block(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    if stage == "preparing":
        monkeypatch.setattr(runner.proxy_session, "select_user_agent", block)
    else:
        monkeypatch.setattr(runner.http_submitter, "submit", block)
    task = asyncio.create_task(runner.run())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert state.peek_reserved_joint_sample("Slot-1") == 0
        assert state.reverse_fill_runtime.reserved_row_by_thread == {"Slot-1": 1}
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not state.joint_reserved_sample_by_thread
        assert not state.joint_answering_threads
        assert not state.reverse_fill_runtime.reserved_row_by_thread
        assert list(state.reverse_fill_runtime.queued_row_numbers) == [1]
        assert not state.snapshot_thread_progress()[0]["running"]
        assert state.cur_num == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await scheduler.close()
