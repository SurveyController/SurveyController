from __future__ import annotations

import concurrent.futures
import threading
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Protocol

from software.application.events import ApplicationEvent
from software.application.interactions import InteractionRequest
if TYPE_CHECKING:
    from software.core.engine.execution_artifacts import PreparedExecutionArtifacts
    from software.core.config.schema import RuntimeConfig
    from software.core.task import ExecutionConfig, ExecutionState
    from software.core.engine.runtime_control_port import RuntimeControlPort
    from software.providers.contracts import ProviderParseResult


class RuntimeEnginePort(Protocol):
    @property
    def thread(self) -> Any: ...

    def parse_survey(self, url: str) -> concurrent.futures.Future[ProviderParseResult]: ...

    def start_run(
        self,
        config: ExecutionConfig,
        state: ExecutionState,
        *,
        runtime_bridge: RuntimeControlPort | None = None,
    ) -> concurrent.futures.Future[Any]: ...

    def stop_run(self) -> None: ...

    def pause_run(self, reason: str = "") -> None: ...

    def resume_run(self) -> None: ...

    def submit_ui_task(
        self, task_name: str, coro_factory: Callable[[], Coroutine[Any, Any, Any]],
    ) -> concurrent.futures.Future[Any]: ...

    def shutdown(self, *, timeout: float = 5.0) -> None: ...


class ConfigRepositoryPort(Protocol):
    def load(self, path: str | None = None, *, strict: bool = False) -> RuntimeConfig: ...

    def save(
        self,
        config: RuntimeConfig,
        path: str | None = None,
        *,
        include_secrets: bool = False,
    ) -> str: ...


class AiConfigPort(Protocol):
    def update(self, config: RuntimeConfig) -> None: ...

    def snapshot(self) -> dict[str, Any]: ...


class ExecutionPreparerPort(Protocol):
    def __call__(
        self,
        config: RuntimeConfig,
        *,
        fallback_survey_title: str = "",
        stop_signal: threading.Event | None = None,
    ) -> PreparedExecutionArtifacts: ...


class CleanupRunnerPort(Protocol):
    def submit(self, task: Callable[[], None], *, delay_seconds: float = 0.0) -> None: ...


class UserInteractionPort(Protocol):
    def request(self, request: InteractionRequest) -> concurrent.futures.Future[bool]: ...

    def cancel_pending(self) -> None: ...


class PreferencesStorePort(Protocol):
    def value(self, key: str, default: Any = None) -> Any: ...

    def setValue(self, key: str, value: Any) -> None: ...

    def remove(self, key: str) -> None: ...

    def sync(self) -> None: ...

    def clear(self) -> None: ...


class AiSettingsPort(Protocol):
    @property
    def providers(self) -> Mapping[str, dict[str, Any]]: ...

    def default_system_prompt(self) -> str: ...

    def get_settings(self) -> dict[str, Any]: ...

    def save_settings(
        self,
        *,
        provider: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        api_protocol: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
    ) -> None: ...

    def update_session(self, config: dict[str, Any]) -> dict[str, Any]: ...

    def reset_settings(self) -> None: ...

    def readiness_error(self, config: dict[str, Any] | None = None) -> str: ...

    async def test_connection(self) -> str: ...


class ProxyOperationsPort(Protocol):
    def refresh_random_ip_counter(self) -> None: ...

    def request_toggle_random_ip(
        self,
        enabled: bool,
        *,
        on_done: Callable[[bool], None] | None = None,
    ) -> bool: ...

    def sync_random_ip_counter_from_server(
        self,
        *,
        silent: bool = True,
        min_interval_seconds: float = 0.0,
    ) -> None: ...


class RandomIpHealthPort(Protocol):
    async def check(self) -> dict[str, str]: ...


class ProxyGatewayPort(Protocol):
    def is_custom_api_active(self) -> bool: ...

    def has_authenticated_session(self) -> bool: ...

    def get_fresh_quota_snapshot(self) -> dict[str, Any]: ...

    def get_quota_snapshot(self) -> dict[str, Any]: ...

    def get_counter_snapshot_local(self) -> tuple[float, float, bool]: ...

    def load_session_for_startup(self) -> None: ...

    async def sync_quota_snapshot(self, *, emit_logs: bool = True) -> dict[str, Any]: ...

    async def activate_trial(self) -> Any: ...

    def is_quota_exhausted(self, snapshot: dict[str, Any]) -> bool: ...

    def get_session_snapshot(self) -> dict[str, Any]: ...

    def format_error(self, error: Exception) -> str: ...


class ApplicationEventSink(Protocol):
    def __call__(self, event: ApplicationEvent) -> None: ...
