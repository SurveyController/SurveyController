from __future__ import annotations

import asyncio

import pytest

import software.core.engine.async_engine as async_engine

from .async_engine_fakes import FakeLoop, FakeThread, build_engine


class AsyncRuntimeEngineStartupTests:
    def test_start_reuses_a_running_background_loop(self) -> None:
        engine = build_engine()
        thread = FakeThread(target=lambda: None, daemon=True, name="AsyncRuntimeEngine")
        thread.started = True
        engine._thread = thread
        engine._engine_state = async_engine.EngineState.RUNNING
        engine._loop_ready.set()

        engine.start()

        assert engine.thread is thread

    def test_start_initializes_background_loop_and_shutdown_clears_handles(
        self, monkeypatch
    ) -> None:
        engine = build_engine()
        fake_loop = FakeLoop()
        real_all_tasks = asyncio.all_tasks
        monkeypatch.setattr(asyncio, "new_event_loop", lambda: fake_loop)
        monkeypatch.setattr(asyncio, "set_event_loop", lambda loop: None)
        monkeypatch.setattr(
            asyncio,
            "all_tasks",
            lambda loop=None: set() if loop is fake_loop else real_all_tasks(loop),
        )
        monkeypatch.setattr(async_engine.threading, "Thread", FakeThread)
        FakeThread.created.clear()

        engine.start()

        assert engine.thread is None
        assert engine._loop is None
        assert fake_loop.run_forever_calls == 1
        assert fake_loop.shutdown_asyncgens_calls == 1
        assert fake_loop.closed is True
        assert engine.engine_state is async_engine.EngineState.CLOSED

        engine.shutdown(timeout=1.5)

        assert engine.thread is None
        assert engine._loop is None

    def test_start_propagates_loop_initialization_failure(self, monkeypatch) -> None:
        engine = build_engine()

        def fail_to_create_loop():
            raise OSError("loop unavailable")

        monkeypatch.setattr(async_engine.asyncio, "new_event_loop", fail_to_create_loop)
        monkeypatch.setattr(async_engine.threading, "Thread", FakeThread)
        FakeThread.created.clear()

        with pytest.raises(RuntimeError, match="loop 启动失败") as exc_info:
            engine.start()

        assert isinstance(exc_info.value.__cause__, OSError)
        assert engine.engine_state is async_engine.EngineState.OPEN
        assert engine.thread is None

    def test_start_cleans_up_when_event_loop_registration_fails(self, monkeypatch) -> None:
        engine = build_engine()
        fake_loop = FakeLoop()

        monkeypatch.setattr(async_engine.asyncio, "new_event_loop", lambda: fake_loop)
        monkeypatch.setattr(
            async_engine.asyncio,
            "set_event_loop",
            lambda _loop: (_ for _ in ()).throw(OSError("loop registration failed")),
        )
        monkeypatch.setattr(async_engine.threading, "Thread", FakeThread)
        FakeThread.created.clear()

        with pytest.raises(RuntimeError, match="loop 启动失败") as exc_info:
            engine.start()

        assert isinstance(exc_info.value.__cause__, OSError)
        assert fake_loop.closed is True
        assert engine.engine_state is async_engine.EngineState.CLOSED
        assert engine.thread is None
        assert engine._loop is None
