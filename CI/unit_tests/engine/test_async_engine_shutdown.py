from __future__ import annotations

import pytest

import software.core.engine.async_engine as async_engine

from .async_engine_fakes import DoneFuture, FakeLoop, FakeThread, build_engine


class AsyncRuntimeEngineShutdownTests:
    def test_shutdown_handles_future_errors_and_stops_loop(self) -> None:
        engine = build_engine()
        run_future = DoneFuture(done=False, result_error=RuntimeError("future boom"))
        engine._run_future = run_future
        engine._loop = FakeLoop()
        thread = FakeThread(target=lambda: None, daemon=True, name="AsyncRuntimeEngine")
        thread.started = True
        engine._thread = thread

        engine.shutdown(timeout=2.5)

        assert engine.engine_state is async_engine.EngineState.STOPPING
        assert run_future.result_calls[0] == pytest.approx(2.5, abs=0.01)
        assert engine._loop is not None
        assert engine._thread is thread
        assert thread.join_calls[0] == pytest.approx(run_future.result_calls[0], abs=0.01)
