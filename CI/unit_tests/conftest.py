from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def patch_attrs(monkeypatch: pytest.MonkeyPatch):
    def apply(*entries: tuple[object, str, object]) -> None:
        for target, name, value in entries:
            monkeypatch.setattr(target, name, value)

    return apply


@pytest.fixture
def make_runtime_state():
    def factory(
        questions_metadata: dict[Any, Any] | None = None,
        question_config_index_map: dict[Any, Any] | None = None,
        *,
        config_defaults: dict[str, Any] | None = None,
        config_overrides: dict[str, Any] | None = None,
        base_overrides: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        config_payload = {
            "questions_metadata": dict(questions_metadata or {}),
            "question_config_index_map": dict(question_config_index_map or {}),
            "answer_duration_range_seconds": [0, 0],
        }
        if config_defaults:
            config_payload.update(config_defaults)
        if config_overrides:
            config_payload.update(config_overrides)

        state = SimpleNamespace(
            config=SimpleNamespace(**config_payload),
            stop_event=threading.Event(),
            step_updates=[],
            status_updates=[],
        )
        if base_overrides:
            for name, value in base_overrides.items():
                setattr(state, name, value)

        def update_thread_step(
            _thread_name: str,
            current: int,
            total: int,
            *,
            status_text: str,
            running: bool,
        ) -> None:
            state.step_updates.append((current, total, status_text, running))

        def update_thread_status(
            _thread_name: str,
            status_text: str,
            *,
            running: bool,
        ) -> None:
            state.status_updates.append((status_text, running))

        state.update_thread_step = update_thread_step
        state.update_thread_status = update_thread_status
        return state

    return factory


@pytest.fixture
def restore_credamo_runtime_patchpoints():
    yield
    from credamo.provider import runtime as credamo_runtime

    credamo_runtime._sync_runtime_dom_patch_points()
    credamo_runtime._sync_runtime_answerer_patch_points()


class _FakeNavigationDriver:
    def __init__(self, *, failures: int = 0, failure_message: str = "goto timeout") -> None:
        self.failures = failures
        self.failure_message = failure_message
        self.calls: list[tuple[str, int, str]] = []

    def get(self, url: str, timeout: int = 20000, wait_until: str = "domcontentloaded") -> None:
        self.calls.append((url, timeout, wait_until))
        if self.failures > 0:
            self.failures -= 1
            raise TimeoutError(self.failure_message)


class _FakeBrowserSession:
    def __init__(self, *, create_browser_exception: Exception | None = None, driver: object | None = None) -> None:
        self.create_browser_exception = create_browser_exception
        self.driver = driver
        self.proxy_address = ""
        self.dispose_called = 0
        self.shutdown_called = 0

    def create_browser(self, *_args, **_kwargs):
        if self.create_browser_exception is not None:
            raise self.create_browser_exception
        return "edge"

    def dispose(self) -> None:
        self.dispose_called += 1
        self.driver = None

    def shutdown(self) -> None:
        self.shutdown_called += 1


class _FakeManagedDriver:
    def __init__(self) -> None:
        self.window_sizes: list[tuple[int, int]] = []
        self.cleanup_marked = False
        self.quit_calls = 0

    def set_window_size(self, width: int, height: int) -> None:
        self.window_sizes.append((width, height))

    def mark_cleanup_done(self) -> bool:
        if self.cleanup_marked:
            return False
        self.cleanup_marked = True
        return True

    def quit(self) -> None:
        self.quit_calls += 1


@pytest.fixture
def make_mock_event():
    def factory(
        *,
        is_set: bool = False,
        wait_return: bool = False,
        spec: object = threading.Event,
    ) -> MagicMock:
        event = MagicMock(spec=spec)
        event.is_set.return_value = is_set
        event.wait.return_value = wait_return
        return event

    return factory


@pytest.fixture
def make_navigation_driver():
    def factory(*, failures: int = 0, failure_message: str = "goto timeout") -> _FakeNavigationDriver:
        return _FakeNavigationDriver(failures=failures, failure_message=failure_message)

    return factory


@pytest.fixture
def make_browser_session():
    def factory(
        *,
        create_browser_exception: Exception | None = None,
        driver: object | None = None,
    ) -> _FakeBrowserSession:
        return _FakeBrowserSession(
            create_browser_exception=create_browser_exception,
            driver=driver,
        )

    return factory


@pytest.fixture
def make_managed_driver():
    def factory() -> _FakeManagedDriver:
        return _FakeManagedDriver()

    return factory


@pytest.fixture
def make_stop_policy_mock():
    def factory(
        *,
        record_success_return: bool = False,
        record_failure_return: bool = False,
    ) -> MagicMock:
        policy = MagicMock()
        policy.record_success.return_value = record_success_return
        policy.record_failure.return_value = record_failure_return
        return policy

    return factory


@pytest.fixture
def make_gui_mock():
    def factory(*method_names: str) -> SimpleNamespace:
        return SimpleNamespace(
            **{name: MagicMock() for name in method_names},
        )

    return factory


@pytest.fixture
def make_http_response():
    def factory(*, json_payload: Any | None = None) -> MagicMock:
        response = MagicMock()
        response.json.return_value = {} if json_payload is None else json_payload
        return response

    return factory


@pytest.fixture
def make_settings_mock():
    def factory(*, value_return: Any = None) -> MagicMock:
        settings = MagicMock()
        settings.value.return_value = value_return
        return settings

    return factory


@pytest.fixture
def make_callable_mock():
    def factory(*, return_value: Any = None, side_effect: Any = None) -> MagicMock:
        mock = MagicMock()
        if side_effect is not None:
            mock.side_effect = side_effect
        else:
            mock.return_value = return_value
        return mock

    return factory
