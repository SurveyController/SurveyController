from __future__ import annotations

import asyncio
import concurrent.futures
from types import SimpleNamespace

import pytest

import software.core.engine.async_engine as async_engine
from software.core.engine.async_engine import AsyncEngineClient
from software.core.task import ExecutionConfig, ExecutionState

from .async_engine_fakes import DoneFuture, FakeLoop, build_engine


class AsyncRuntimeEngineDispatchTests:
    def test_start_reuses_live_thread_and_submit_requires_loop(self, monkeypatch) -> None:
        engine = build_engine()
        alive_thread = SimpleNamespace(is_alive=lambda: True)
        engine._thread = alive_thread
        engine._loop_ready.set()

        engine.start()
        assert engine.thread is alive_thread

        engine._thread = None
        engine._loop = None
        monkeypatch.setattr(engine, "start", lambda: None)
        coro = asyncio.sleep(0)

        with pytest.raises(RuntimeError, match="未启动"):
            engine._submit(coro)
        coro.close()

    def test_start_run_stop_pause_resume_parse_and_submit_ui_task(self, monkeypatch) -> None:
        engine = build_engine()
        config = ExecutionConfig(num_threads=2, survey_provider="wjx")
        state = ExecutionState(config=config)
        submitted: list[object] = []
        run_future = DoneFuture(done=False)
        parse_future = DoneFuture(result_value="parsed")
        ui_future = DoneFuture(result_value="ui-ok")
        returned_futures = [run_future, parse_future, ui_future]
        loop = FakeLoop()
        engine._loop = loop
        engine._run_future = DoneFuture(done=True)
        stop_event = SimpleNamespace(set=lambda: submitted.append("stop-event"))
        pause_event = SimpleNamespace(set=lambda: submitted.append("pause"), clear=lambda: submitted.append("resume"))
        engine._stop_event = stop_event
        engine._pause_event = pause_event
        engine._state = state

        def _fake_submit(coro):
            submitted.append(coro)
            return returned_futures.pop(0)

        monkeypatch.setattr(engine, "_submit", _fake_submit)
        monkeypatch.setattr(async_engine, "parse_survey", lambda url: asyncio.sleep(0, result=f"parsed:{url}"))

        future = engine.start_run(config=config, state=state, runtime_bridge=None)
        assert future is run_future
        assert engine._run_future is run_future

        with pytest.raises(RuntimeError, match="运行中"):
            engine._run_future = DoneFuture(done=False)
            engine.start_run(config=config, state=state)

        engine._run_future = DoneFuture(done=True)
        engine.stop_run()
        engine.pause_run("reason")
        engine.resume_run()
        parse_result = engine.parse_survey("https://example.com")
        ui_result = engine.submit_ui_task("task", lambda: asyncio.sleep(0, result="ui-ok"))

        for item in submitted:
            if asyncio.iscoroutine(item):
                item.close()
        assert asyncio.iscoroutine(submitted[0])
        assert "stop-event" in submitted
        assert "pause" in submitted
        assert "resume" in submitted
        assert parse_result is parse_future
        assert ui_result is ui_future
        assert state.stop_event.is_set()
        assert engine._run_future is None
        assert any(call[0] == stop_event.set for call in loop.threadsafe_calls)
        assert any(call[0] == pause_event.set for call in loop.threadsafe_calls)
        assert any(call[0] == pause_event.clear for call in loop.threadsafe_calls)

    def test_async_engine_client_forwards_all_calls(self) -> None:
        calls: list[tuple[str, object]] = []
        future = concurrent.futures.Future()
        future.set_result("ok")
        engine = SimpleNamespace(
            thread="thread",
            start_run=lambda **kwargs: calls.append(("start_run", kwargs)) or future,
            stop_run=lambda: calls.append(("stop_run", None)),
            pause_run=lambda reason="": calls.append(("pause_run", reason)),
            resume_run=lambda: calls.append(("resume_run", None)),
            parse_survey=lambda url: calls.append(("parse_survey", url)) or future,
            submit_ui_task=lambda task_name, coro_factory: calls.append(("submit_ui_task", task_name)) or future,
            shutdown=lambda timeout=5.0: calls.append(("shutdown", timeout)),
        )
        client = AsyncEngineClient(engine=engine)
        config = ExecutionConfig(survey_provider="wjx")
        state = ExecutionState(config=config)

        assert client.thread == "thread"
        assert client.start_run(config, state) is future
        client.stop_run()
        client.pause_run("pause")
        client.resume_run()
        assert client.parse_survey("https://example.com") is future
        assert client.submit_ui_task("task", lambda: asyncio.sleep(0)) is future
        client.shutdown(timeout=1.2)

        assert [name for name, _value in calls] == [
            "start_run",
            "stop_run",
            "pause_run",
            "resume_run",
            "parse_survey",
            "submit_ui_task",
            "shutdown",
        ]
