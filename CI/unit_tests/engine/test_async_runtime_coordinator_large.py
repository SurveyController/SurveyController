from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import software.core.engine.async_runtime as async_runtime
from software.core.engine.async_runtime import AsyncRuntimeCoordinator
from software.core.task import ExecutionConfig, ExecutionState


class _FakeLoop:
    instances: list["_FakeLoop"] = []

    def __init__(self, config, state, gui_instance, *, browser_owner_pool, dispatcher) -> None:
        self.config = config
        self.state = state
        self.gui_instance = gui_instance
        self.browser_owner_pool = browser_owner_pool
        self.dispatcher = dispatcher
        self.run_thread_calls: list[tuple[int, int, threading.Event]] = []
        _FakeLoop.instances.append(self)

    def run_thread(self, slot_index: int, attempt_index: int, stop_signal: threading.Event) -> None:
        self.run_thread_calls.append((slot_index, attempt_index, stop_signal))


class _FakeDispatcher:
    def __init__(self, config, state, stop_signal) -> None:
        self.config = config
        self.state = state
        self.stop_signal = stop_signal
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _FakePool:
    def __init__(self, *, config, headless, prefer_browsers, window_positions) -> None:
        self.config = config
        self.headless = headless
        self.prefer_browsers = prefer_browsers
        self.window_positions = window_positions
        self.shutdown_calls = 0

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _ImmediateThread:
    instances: list["_ImmediateThread"] = []

    def __init__(self, *, target, daemon: bool, name: str) -> None:
        self.target = target
        self.daemon = daemon
        self.name = name
        self.started = False
        self.joined = False
        _ImmediateThread.instances.append(self)

    def start(self) -> None:
        self.started = True
        self.target()

    def join(self) -> None:
        self.joined = True


def _build_coordinator(*, config: ExecutionConfig | None = None, gui_instance=None):
    config = config or ExecutionConfig(num_threads=2, survey_provider="wjx")
    state = ExecutionState(config=config)
    stop_signal = threading.Event()
    coordinator = AsyncRuntimeCoordinator(
        config=config,
        state=state,
        stop_signal=stop_signal,
        gui_instance=gui_instance,
    )
    return coordinator, state, stop_signal


class AsyncRuntimeCoordinatorLargeTests:
    def test_build_owner_window_positions_handles_zero_and_multiple(self) -> None:
        assert async_runtime._build_owner_window_positions(0) == [(50, 50)]
        assert async_runtime._build_owner_window_positions(3) == [(50, 50), (110, 110), (170, 170)]

    def test_register_and_unregister_cleanup_target_support_both_gui_styles(self) -> None:
        gui = SimpleNamespace(active_drivers=[])
        coordinator, _state, _stop_signal = _build_coordinator(gui_instance=gui)
        target = object()

        coordinator._register_cleanup_target(target)
        assert gui.active_drivers == [target]

        coordinator._unregister_cleanup_target(target)
        assert gui.active_drivers == []

        registered: list[object] = []
        unregistered: list[object] = []
        gui = SimpleNamespace(
            register_cleanup_target=lambda target: registered.append(target),
            unregister_cleanup_target=lambda target: unregistered.append(target),
        )
        coordinator, _state, _stop_signal = _build_coordinator(gui_instance=gui)

        coordinator._register_cleanup_target(target)
        coordinator._unregister_cleanup_target(target)

        assert registered == [target]
        assert unregistered == [target]

    def test_unregister_cleanup_target_ignores_missing_target(self) -> None:
        coordinator, _state, _stop_signal = _build_coordinator(gui_instance=SimpleNamespace(active_drivers=[]))

        coordinator._unregister_cleanup_target(object())

    def test_run_slot_requires_pool_and_runs_execution_loop(self, monkeypatch) -> None:
        _FakeLoop.instances.clear()
        coordinator, _state, stop_signal = _build_coordinator()

        with pytest.raises(RuntimeError, match="未初始化"):
            coordinator._run_slot()

        coordinator.owner_pool = object()
        coordinator.dispatcher = object()
        monkeypatch.setattr(async_runtime, "ExecutionLoop", _FakeLoop)

        coordinator._run_slot()

        created = _FakeLoop.instances[-1]
        assert created.browser_owner_pool is coordinator.owner_pool
        assert created.dispatcher is coordinator.dispatcher
        assert created.run_thread_calls == [(0, 0, stop_signal)]

    def test_run_builds_pool_dispatcher_threads_and_cleans_up(self, monkeypatch) -> None:
        _ImmediateThread.instances.clear()
        _FakeLoop.instances.clear()
        created_pools: list[_FakePool] = []
        created_dispatchers: list[_FakeDispatcher] = []
        gui = SimpleNamespace(active_drivers=[])
        config = ExecutionConfig(num_threads=3, headless_mode=True, browser_preference=["edge", "chrome"], survey_provider="wjx")
        coordinator, _state, _stop_signal = _build_coordinator(config=config, gui_instance=gui)

        monkeypatch.setattr(async_runtime, "ExecutionLoop", _FakeLoop)
        monkeypatch.setattr(async_runtime, "AttemptDispatcher", lambda *args, **kwargs: created_dispatchers.append(_FakeDispatcher(*args, **kwargs)) or created_dispatchers[-1])
        monkeypatch.setattr(async_runtime, "BrowserOwnerPool", lambda **kwargs: created_pools.append(_FakePool(**kwargs)) or created_pools[-1])
        monkeypatch.setattr(async_runtime.threading, "Thread", _ImmediateThread)

        coordinator.run()

        assert len(created_pools) == 1
        pool = created_pools[0]
        assert pool.headless is True
        assert pool.prefer_browsers == ["edge", "chrome"]
        assert pool.window_positions == [(50, 50)]
        assert len(created_dispatchers) == 1
        assert created_dispatchers[0].close_calls == 1
        assert pool.shutdown_calls == 1
        assert coordinator.slot_threads == []
        assert coordinator.owner_pool is None
        assert coordinator.dispatcher is None
        assert gui.active_drivers == []
        assert [thread.name for thread in _ImmediateThread.instances] == ["Slot-1", "Slot-2", "Slot-3"]
        assert all(thread.started and thread.joined for thread in _ImmediateThread.instances)
        assert len(_FakeLoop.instances) == 3

    def test_run_logs_suppressed_exception_when_pool_shutdown_fails(self, monkeypatch) -> None:
        _ImmediateThread.instances.clear()
        suppressed: list[str] = []
        created_dispatchers: list[_FakeDispatcher] = []
        coordinator, _state, _stop_signal = _build_coordinator(config=ExecutionConfig(num_threads=1, survey_provider="wjx"))
        bad_pool = SimpleNamespace(shutdown=lambda: (_ for _ in ()).throw(RuntimeError("shutdown boom")))

        monkeypatch.setattr(async_runtime, "ExecutionLoop", _FakeLoop)
        monkeypatch.setattr(async_runtime, "AttemptDispatcher", lambda *args, **kwargs: created_dispatchers.append(_FakeDispatcher(*args, **kwargs)) or created_dispatchers[-1])
        monkeypatch.setattr(async_runtime, "BrowserOwnerPool", lambda **kwargs: bad_pool)
        monkeypatch.setattr(async_runtime.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(async_runtime, "log_suppressed_exception", lambda where, exc, **_kwargs: suppressed.append(f"{where}:{exc}"))

        coordinator.run()

        assert created_dispatchers[0].close_calls == 1
        assert suppressed == ["AsyncRuntimeCoordinator.run pool.shutdown:shutdown boom"]
