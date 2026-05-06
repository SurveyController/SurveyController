from __future__ import annotations

import asyncio
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from software.core.engine.async_events import AsyncRunContext, ThreadEventProxy
from software.core.engine.async_status_bus import AsyncStatusBus


class AsyncStatusBusTests:
    def test_emit_dispatches_callback_with_sequence(self, patch_attrs) -> None:
        delivered: list[str] = []
        bus = AsyncStatusBus(
            dispatcher=lambda callback: callback(),
            throttle_seconds=0.0,
        )
        patch_attrs((__import__("software.core.engine.async_status_bus", fromlist=["time"]).time, "monotonic", lambda: 10.0))

        bus.emit({"slot_id": "slot-1", "callback": lambda: delivered.append("ok")})

        assert delivered == ["ok"]

    def test_emit_throttles_high_frequency_events(self, patch_attrs) -> None:
        module = __import__("software.core.engine.async_status_bus", fromlist=["time"])
        timestamps = iter([1.0, 1.01])
        dispatched: list[str] = []
        patch_attrs((module.time, "monotonic", lambda: next(timestamps)))
        bus = AsyncStatusBus(
            dispatcher=lambda callback: (dispatched.append("dispatch"), callback()),
            throttle_seconds=0.1,
        )

        bus.emit({"slot_id": "slot-1", "type": "progress", "callback": lambda: dispatched.append("first")})
        bus.emit({"slot_id": "slot-1", "type": "progress", "callback": lambda: dispatched.append("second")})

        assert dispatched == ["dispatch", "first"]

    def test_emit_does_not_throttle_non_high_frequency_events(self, patch_attrs) -> None:
        module = __import__("software.core.engine.async_status_bus", fromlist=["time"])
        timestamps = iter([2.0, 2.01])
        dispatched: list[str] = []
        patch_attrs((module.time, "monotonic", lambda: next(timestamps)))
        bus = AsyncStatusBus(
            dispatcher=lambda callback: (dispatched.append("dispatch"), callback()),
            throttle_seconds=0.1,
        )

        bus.emit({"slot_id": "slot-1", "type": "result", "callback": lambda: dispatched.append("first")})
        bus.emit({"slot_id": "slot-1", "type": "result", "callback": lambda: dispatched.append("second")})

        assert dispatched == ["dispatch", "first", "dispatch", "second"]


class AsyncRunContextTests:
    @pytest.mark.asyncio
    async def test_wait_if_paused_exits_after_pause_cleared(self) -> None:
        stop_event = asyncio.Event()
        pause_event = asyncio.Event()
        pause_event.set()
        ctx = AsyncRunContext(
            state=SimpleNamespace(),
            stop_event=stop_event,
            pause_event=pause_event,
        )

        async def _release_pause() -> None:
            await asyncio.sleep(0.01)
            pause_event.clear()

        await asyncio.gather(ctx.wait_if_paused(), _release_pause())
        assert not pause_event.is_set()

    def test_emit_copies_payload_before_dispatch(self) -> None:
        captured: list[dict[str, object]] = []
        payload = {"value": 1}
        ctx = AsyncRunContext(
            state=SimpleNamespace(),
            stop_event=asyncio.Event(),
            pause_event=asyncio.Event(),
            status_sink=lambda event: captured.append(event),
        )

        ctx.emit(payload)
        payload["value"] = 2

        assert captured == [{"value": 1}]

    @pytest.mark.asyncio
    async def test_wait_if_paused_returns_when_stop_requested(self) -> None:
        stop_event = asyncio.Event()
        pause_event = asyncio.Event()
        pause_event.set()
        ctx = AsyncRunContext(
            state=SimpleNamespace(),
            stop_event=stop_event,
            pause_event=pause_event,
        )

        async def _request_stop() -> None:
            await asyncio.sleep(0.01)
            stop_event.set()

        await asyncio.gather(ctx.wait_if_paused(), _request_stop())
        assert ctx.stop_requested() is True


class ThreadEventProxyTests:
    def test_set_and_clear_use_loop_threadsafe_callback_when_loop_open(self) -> None:
        calls: list[object] = []

        class _Loop:
            def is_closed(self) -> bool:
                return False

            def call_soon_threadsafe(self, callback) -> None:
                calls.append(callback)

        event = asyncio.Event()
        proxy = ThreadEventProxy(event, loop=_Loop())

        proxy.set()
        proxy.clear()

        assert len(calls) == 2

    def test_set_and_clear_are_noops_when_loop_closed(self) -> None:
        class _Loop:
            def is_closed(self) -> bool:
                return True

            def call_soon_threadsafe(self, callback) -> None:
                raise AssertionError(f"unexpected callback: {callback}")

        proxy = ThreadEventProxy(asyncio.Event(), loop=_Loop())
        proxy.set()
        proxy.clear()

    def test_wait_returns_immediately_when_event_already_set(self) -> None:
        event = asyncio.Event()
        event.set()
        proxy = ThreadEventProxy(event, loop=SimpleNamespace())

        assert proxy.wait(timeout=0.1) is True

    def test_wait_uses_run_coroutine_threadsafe_result(self, monkeypatch) -> None:
        loop = asyncio.new_event_loop()
        try:
            event = asyncio.Event()
            proxy = ThreadEventProxy(event, loop=loop)
            future: Future[bool] = Future()
            future.set_result(True)

            def _fake_run_coroutine_threadsafe(coro, _loop):
                coro.close()
                return future

            monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _fake_run_coroutine_threadsafe)

            assert proxy.wait(timeout=0.1) is True
        finally:
            loop.close()

    def test_wait_returns_false_after_timeout(self, monkeypatch) -> None:
        loop = asyncio.new_event_loop()
        try:
            proxy = ThreadEventProxy(asyncio.Event(), loop=loop)
            future: Future[bool] = Future()
            future.set_result(False)

            def _fake_run_coroutine_threadsafe(coro, _loop):
                coro.close()
                return future

            monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _fake_run_coroutine_threadsafe)

            assert proxy.wait(timeout=0.01) is False
        finally:
            loop.close()
