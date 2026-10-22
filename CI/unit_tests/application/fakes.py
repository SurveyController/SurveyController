from __future__ import annotations

from collections import deque
from concurrent.futures import Future
from types import SimpleNamespace
from typing import Any

from software.application.configuration import ConfigurationService
from software.application.interactions import InteractionBroker
from software.application.run_service import RunApplicationService
from software.application.run_state_store import RunStateStore
from software.core.config.schema import RuntimeConfig
from software.core.engine.execution_artifacts import PreparedExecutionArtifacts, RuntimePreparationError
from software.core.task import ExecutionConfig


class FakePreferences:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.sync_count = 0

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def remove(self, key):
        self.values.pop(key, None)

    def clear(self):
        self.values.clear()

    def sync(self):
        self.sync_count += 1


class FakeRepository:
    def __init__(self) -> None:
        self.config = RuntimeConfig(url="https://v.wjx.cn/vm/config.aspx")
        self.saved = None

    def load(self, path=None, *, strict=False):
        self.load_args = (path, strict)
        return self.config

    def save(self, config, path=None, *, include_secrets=False):
        del include_secrets
        self.saved = (config, path)
        return path or "default.json"


class FakeEngine:
    def __init__(self) -> None:
        self.thread = None
        self.parse_future = Future()
        self.run_future = Future()
        self.starts: list[tuple[Any, Any, Any]] = []
        self.stop_calls = 0
        self.pause_calls: list[str] = []
        self.resume_calls = 0
        self.shutdown_calls: list[float] = []
        self.start_error = None
        self.parse_error = None

    def parse_survey(self, url):
        self.parsed_url = url
        if self.parse_error:
            raise self.parse_error
        return self.parse_future

    def start_run(self, config, state, *, runtime_bridge=None):
        if self.start_error:
            raise self.start_error
        self.starts.append((config, state, runtime_bridge))
        return self.run_future

    def stop_run(self):
        self.stop_calls += 1

    def pause_run(self, reason=""):
        self.pause_calls.append(reason)

    def resume_run(self):
        self.resume_calls += 1

    def shutdown(self, *, timeout=5.0):
        self.shutdown_calls.append(timeout)

    def submit_ui_task(self, task_name, coro_factory):
        raise AssertionError(f"Unexpected background task: {task_name}")


class FakeProxy:
    def is_custom_api_active(self):
        return True

    def has_authenticated_session(self):
        return False

    def get_counter_snapshot_local(self):
        return 1.0, 5.0, True

    def get_fresh_quota_snapshot(self):
        return {"used_quota": 1, "total_quota": 5}

    get_quota_snapshot = get_fresh_quota_snapshot

    def load_session_for_startup(self):
        pass

    async def sync_quota_snapshot(self, *, emit_logs=True):
        return self.get_quota_snapshot()

    async def activate_trial(self):
        return SimpleNamespace(total_quota=5, used_quota=1)

    def is_quota_exhausted(self, snapshot):
        return False

    def get_session_snapshot(self):
        return {"authenticated": True}

    def format_error(self, error):
        return str(error)


class FakeCleanup:
    def __init__(self) -> None:
        self.tasks: list[tuple[Any, float]] = []

    def submit(self, task, delay_seconds=0.0):
        self.tasks.append((task, delay_seconds))


def prepare(
    config: RuntimeConfig,
    *,
    fallback_survey_title: str = "",
    stop_signal=None,
) -> PreparedExecutionArtifacts:
    del fallback_survey_title
    if stop_signal is not None and stop_signal.is_set():
        raise RuntimePreparationError("运行准备已取消")
    return PreparedExecutionArtifacts(
        execution_config_template=ExecutionConfig(target_num=config.target, num_threads=config.threads),
        survey_provider=config.survey_provider,
        question_entries=[], questions_info=[], reverse_fill_spec=None,
    )


class Harness:
    def __init__(self, preparer=prepare):
        self.callbacks = deque()
        self.events = []
        self.requests = []
        self.snapshots = []
        self.engine = FakeEngine()
        self.repository = FakeRepository()
        self.cleanup = FakeCleanup()
        self.interactions = InteractionBroker(self.requests.append)
        self.state = RunStateStore(on_runtime_snapshot_changed=self.snapshots.append)
        self.service = RunApplicationService(
            state_store=self.state, async_engine_client=self.engine,
            execution_preparer=preparer, proxy_gateway=FakeProxy(),
            configuration_service=ConfigurationService(self.repository), cleanup_runner=self.cleanup,
            interactions=self.interactions, dispatch_async=self.callbacks.append,
            emit_event=self.events.append,
        )

    def drain(self):
        while self.callbacks:
            self.callbacks.popleft()()

    def start(self, config=None):
        self.service.start_run(config or RuntimeConfig(target=3, threads=2))
        self.service._init_gate_thread.join(timeout=2)
        assert not self.service._init_gate_thread.is_alive()
        self.drain()

    def finish(self, *, category="target_reached", reason="", error=None):
        state = self.service._execution_state
        state.mark_terminal_stop(category, failure_reason=reason)
        if error:
            self.engine.run_future.set_exception(error)
        else:
            self.engine.run_future.set_result(None)
        monitor = self.service._monitor_thread
        if monitor:
            monitor.join(timeout=2)
            assert not monitor.is_alive()
        self.drain()

    def close(self):
        if not self.engine.run_future.done():
            self.engine.run_future.set_result(None)
        self.service.shutdown_for_close(timeout_seconds=2)
        self.drain()
