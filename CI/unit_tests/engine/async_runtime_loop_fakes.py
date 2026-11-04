from __future__ import annotations

import asyncio

from software.core.engine.async_runtime_loop import AsyncSlotRunner
from software.core.engine.task_registry import TaskRegistry
from software.core.task import ExecutionConfig, ExecutionState
from surveycore.core.engine.async_events import AsyncRunContext


class _FakeScheduler:
    def __init__(self, acquire_values=None) -> None:
        self.acquire_values = list(acquire_values or [1])
        self.release_calls: list[dict[str, object]] = []

    async def acquire(self):
        if not self.acquire_values:
            return None
        return self.acquire_values.pop(0)

    async def release(self, token_id, **kwargs):
        self.release_calls.append({"token_id": token_id, **kwargs})


class _FakeStopPolicy:
    def __init__(self, state: ExecutionState | None = None) -> None:
        self.state = state
        self.failure_calls: list[dict[str, object]] = []
        self.success_calls: list[dict[str, object]] = []
        self.proxy_threshold = 3

    def record_failure(self, stop_signal, **kwargs):
        self.failure_calls.append({"stop_signal": stop_signal, **kwargs})
        return bool(kwargs.get("threshold_override") == 1)

    def record_success(self, stop_signal, **kwargs):
        self.success_calls.append({"stop_signal": stop_signal, **kwargs})
        if self.state is not None:
            self.state.cur_num += 1
        return False

    def trigger_target_reached_stop(self, stop_signal):
        if self.state is not None:
            self.state.mark_terminal_stop("target_reached", message="目标份数已达成")
        stop_signal.set()

    def proxy_unavailable_threshold(self):
        return self.proxy_threshold


def _build_runner(
    *,
    config: ExecutionConfig | None = None,
    state: ExecutionState | None = None,
    stop_set: bool = False,
):
    config = config or ExecutionConfig(
        target_num=3,
        submit_interval_range_seconds=[1, 3],
        survey_provider="wjx",
        url="https://www.wjx.cn/vm/demo.aspx",
    )
    state = state or ExecutionState(config=config)
    state.step_updates = []
    state.update_thread_status = lambda *_args, **_kwargs: None
    state.update_thread_step = lambda *args, **kwargs: state.step_updates.append((args, kwargs))
    stop_event = asyncio.Event()
    if stop_set:
        stop_event.set()
    run_context = AsyncRunContext(
        state=state,
        stop_event=stop_event,
        pause_event=asyncio.Event(),
    )
    scheduler = _FakeScheduler()
    runner = AsyncSlotRunner(
        slot_id=1,
        config=config,
        state=state,
        run_context=run_context,
        scheduler=scheduler,
        task_registry=TaskRegistry(),
        runtime_bridge=None,
    )
    runner.stop_policy = _FakeStopPolicy(state)
    return runner, state, run_context, scheduler
