from __future__ import annotations

import pytest

import software.core.engine.async_runtime_loop as runtime_loop
from software.core.task import ExecutionConfig, ExecutionState

from .async_runtime_loop_fakes import _build_runner


class AsyncRuntimeLoopControlTests:
    @pytest.mark.asyncio
    async def test_should_stop_loop_honors_stop_event(self) -> None:
        runner, _state, _ctx, _scheduler = _build_runner(stop_set=True)

        assert await runner._should_stop_loop() is True

    @pytest.mark.asyncio
    async def test_should_stop_loop_honors_target_num(self) -> None:
        config = ExecutionConfig(target_num=2, survey_provider="wjx")
        state = ExecutionState(config=config, cur_num=2)
        runner, _state, _ctx, _scheduler = _build_runner(config=config, state=state)

        assert await runner._should_stop_loop() is True

    @pytest.mark.asyncio
    async def test_sleep_or_stop_handles_zero_delay_and_timeout(self) -> None:
        runner, _state, _ctx, _scheduler = _build_runner()

        assert await runner._sleep_or_stop(0) is False
        assert await runner._sleep_or_stop(0.001) is False

    @pytest.mark.asyncio
    async def test_resolve_dispatch_delay_seconds_covers_zero_fixed_and_random(
        self, monkeypatch
    ) -> None:
        config = ExecutionConfig(submit_interval_range_seconds=[0, 0], survey_provider="wjx")
        runner, _state, _ctx, _scheduler = _build_runner(config=config)
        assert runner._resolve_dispatch_delay_seconds() == 0.0

        config.submit_interval_range_seconds = [2, 2]
        assert runner._resolve_dispatch_delay_seconds() == 2.0

        config.submit_interval_range_seconds = [1, 3]
        monkeypatch.setattr(runtime_loop.random, "uniform", lambda _a, _b: 2.5)
        assert runner._resolve_dispatch_delay_seconds() == 2.5
