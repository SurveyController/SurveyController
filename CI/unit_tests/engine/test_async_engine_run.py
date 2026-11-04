from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import software.core.engine.async_engine as async_engine
from software.core.task import ExecutionConfig, ExecutionState

from .async_engine_fakes import build_engine


class AsyncRuntimeEngineRunTests:
    @pytest.mark.asyncio
    async def test_run_starts_slots_and_closes_scheduler_when_runner_fails(
        self, monkeypatch
    ) -> None:
        engine = build_engine()
        config = ExecutionConfig(num_threads=2, target_num=5, survey_provider="wjx")
        state = ExecutionState(config=config)
        bus_events: list[dict[str, object]] = []
        engine._status_bus = SimpleNamespace(emit=lambda event: bus_events.append(event))
        created_runners: list[SimpleNamespace] = []
        created_schedulers: list[SimpleNamespace] = []

        class _FakeRunner:
            def __init__(self, **kwargs) -> None:
                self.slot_id = kwargs["slot_id"]
                self.cancelled = False
                created_runners.append(self)

            async def run(self) -> None:
                if self.slot_id == 2:
                    raise RuntimeError("slot boom")
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise

        class _FakeScheduler:
            def __init__(self, *, concurrency: int) -> None:
                self.concurrency = concurrency
                self.close_calls = 0
                created_schedulers.append(self)

            async def close(self) -> None:
                self.close_calls += 1

        monkeypatch.setattr(async_engine, "AsyncScheduler", _FakeScheduler)
        monkeypatch.setattr(
            async_engine, "AsyncRunContext", lambda **kwargs: SimpleNamespace(**kwargs)
        )
        monkeypatch.setattr(async_engine, "AsyncSlotRunner", _FakeRunner)

        with pytest.raises(RuntimeError, match="slot boom"):
            await engine._run(config=config, state=state, runtime_bridge=None)

        assert len(created_runners) == 2
        assert created_runners[0].slot_id == 1
        assert created_runners[1].slot_id == 2
        assert created_runners[0].cancelled is True
        assert created_schedulers[0].close_calls == 1
        assert state.stop_event.is_set()
        assert engine._stop_event is None
        assert engine._pause_event is None
        assert engine._state is None
