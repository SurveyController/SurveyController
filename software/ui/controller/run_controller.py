from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, Signal, Slot

from software.app.bootstrap import ApplicationDependencies, create_application_dependencies
from software.application.events import ApplicationEvent
from software.application.models import RuntimeSnapshot, SurveySnapshot
from software.application.interactions import InteractionBroker, InteractionRequest
from software.ui.controller.presentation import interaction_view, runtime_status, runtime_view, survey_view
from software.application.ports import ProxyOperationsPort
from software.application.run_service import RunApplicationService
from software.application.run_state_store import RunStateStore
from software.application.survey_parse_service import SurveyParseService
from software.core.config.codec import build_runtime_config_snapshot
from software.core.config.schema import RuntimeConfig
from software.ui.controller.ui_dispatcher import UiCallbackDispatcher


class RunController(QObject):
    runtimeSnapshotChanged = Signal(dict)
    surveySnapshotChanged = Signal(dict)
    controllerEvent = Signal(dict)
    _uiCallbackQueued = Signal()

    def __init__(
        self,
        parent=None,
        *,
        dependencies: ApplicationDependencies | None = None,
    ):
        super().__init__(parent)
        self.dependencies = dependencies or create_application_dependencies()
        self._ui_dispatcher = UiCallbackDispatcher(self._uiCallbackQueued.emit)
        self._uiCallbackQueued.connect(self._drain_ui_callbacks)
        self._async_engine_client = self.dependencies.runtime_engine
        self._cleanup_runner = self.dependencies.cleanup_runner
        self.preferences = self.dependencies.preferences
        self.ai_settings = self.dependencies.ai_settings
        self._state_store = RunStateStore(
            on_runtime_snapshot_changed=self._emit_runtime_snapshot,
            on_survey_snapshot_changed=self._emit_survey_snapshot,
        )
        self._interactions = InteractionBroker(self._publish_interaction)
        self._command_service = RunApplicationService(
            state_store=self._state_store,
            async_engine_client=self._async_engine_client,
            execution_preparer=self.dependencies.execution_preparer,
            proxy_gateway=self.dependencies.proxy_gateway,
            configuration_service=self.dependencies.configuration,
            cleanup_runner=self._cleanup_runner,
            interactions=self._interactions,
            dispatch_async=self._dispatch_to_ui_async,
            emit_event=self._emit_controller_event,
        )
        self.proxy_operations: ProxyOperationsPort = self._command_service
        self._parse_service = SurveyParseService(
            async_engine_client=self._async_engine_client,
            state_store=self._state_store,
            emit_event=self._emit_controller_event,
            dispatch_async=self._dispatch_to_ui_async,
        )
        self.on_ip_counter: Optional[Callable[[float, float, bool], None]] = None
        self.config = RuntimeConfig()
        self._emit_runtime_snapshot(self._state_store.get_runtime_snapshot())
        self._emit_survey_snapshot(self._state_store.get_survey_snapshot())

    @Slot()
    def _drain_ui_callbacks(self) -> None:
        self._ui_dispatcher.drain()

    def _dispatch_to_ui_async(self, callback: Callable[[], Any]) -> None:
        self._ui_dispatcher.dispatch_async(callback)

    _format_runtime_status = staticmethod(runtime_status)
    _runtime_snapshot_view = staticmethod(runtime_view)

    def _publish_interaction(self, request: InteractionRequest) -> None:
        def publish() -> None:
            if self._command_service._closing:
                self._interactions.resolve(request.request_id, False)
                return
            try:
                self.controllerEvent.emit(interaction_view(request))
            except Exception:
                self._interactions.resolve(request.request_id, False)
                raise

        self._dispatch_to_ui_async(publish)

    def respond_to_interaction(self, request_id: str, accepted: bool) -> None:
        self._interactions.resolve(request_id, accepted)

    def _emit_runtime_snapshot(self, snapshot: RuntimeSnapshot) -> None:
        view = self._runtime_snapshot_view(snapshot)
        self.runtimeSnapshotChanged.emit(dict(view))
        random_ip = snapshot.get("random_ip") or {}
        if callable(self.on_ip_counter):
            try:
                self.on_ip_counter(
                    float(random_ip.get("used_quota") or 0.0),
                    float(random_ip.get("total_quota") or 0.0),
                    bool(random_ip.get("custom_api")),
                )
            except Exception:
                pass

    def _emit_survey_snapshot(self, snapshot: SurveySnapshot) -> None:
        self.surveySnapshotChanged.emit(survey_view(snapshot))

    def _emit_controller_event(self, event: ApplicationEvent) -> None:
        payload = event.to_dict()
        if payload.get("type") == "run_failed":
            payload["message"] = str(payload.get("detail") or "后台运行内核异常退出，请查看日志")
        self.controllerEvent.emit(payload)

    @property
    def running(self) -> bool:
        return bool(self._command_service.running)

    @running.setter
    def running(self, value: bool) -> None:
        self._command_service.running = bool(value)

    @property
    def adapter(self) -> Any:
        return self._command_service.runtime_port

    def is_initializing(self) -> bool:
        return self._command_service.is_initializing()

    def get_runtime_snapshot(self) -> dict[str, Any]:
        return self._runtime_snapshot_view(self._state_store.get_runtime_snapshot())

    def get_survey_snapshot(self) -> dict[str, Any]:
        return survey_view(self._state_store.get_survey_snapshot())

    def get_runtime_ui_state(self) -> dict[str, Any]:
        return dict(self.get_runtime_snapshot().get("settings") or {})

    def update_runtime_settings(self, *, emit: bool = True, **updates: Any) -> dict[str, Any]:
        state = self._state_store.update_runtime_settings(
            emit=emit,
            lock_threads=self._command_service.threads_update_locked(),
            **updates,
        )
        self._command_service.sync_runtime_settings(state)
        return state

    def set_runtime_ui_state(self, emit: bool = True, **updates: Any) -> dict[str, Any]:
        return self.update_runtime_settings(emit=emit, **updates)

    def hydrate_from_config(self, cfg: RuntimeConfig) -> RuntimeConfig:
        self.config = cfg
        self._state_store.hydrate_from_config(cfg)
        self._command_service.sync_runtime_settings(self.get_runtime_snapshot().get("settings", {}))
        return cfg

    def replace_question_entries(self, entries: Any, questions_info: Any = None) -> SurveySnapshot:
        return self._state_store.replace_question_entries(
            entries,
            questions_info=questions_info,
        )

    def write_runtime_settings_to_config(self, config: RuntimeConfig) -> RuntimeConfig:
        return self._state_store.write_runtime_settings_to_config(config)

    def write_to_config(self, config: RuntimeConfig) -> RuntimeConfig:
        return self.write_runtime_settings_to_config(config)

    def parse_survey(self, url: str) -> None:
        self._parse_service.parse_survey(url)

    def start_run(self, cfg: RuntimeConfig) -> None:
        self._command_service.start_run(cfg)

    def stop_run(self) -> None:
        self._command_service.stop_run()

    def pause_run(self, reason: str = "") -> None:
        self._command_service.pause_run(reason)

    def resume_run(self) -> None:
        self._command_service.resume_run()

    def request_shutdown_for_close(self, timeout_seconds: float = 5.0) -> None:
        self._parse_service.close()
        self._command_service.request_shutdown_for_close(timeout_seconds=timeout_seconds)

    def request_toggle_random_ip(
        self,
        enabled: bool,
        *,
        on_done: Optional[Callable[[bool], None]] = None,
    ) -> bool:
        return self.proxy_operations.request_toggle_random_ip(
            bool(enabled),
            on_done=on_done,
        )

    def refresh_random_ip_counter(self) -> None:
        self.proxy_operations.refresh_random_ip_counter()

    def sync_random_ip_counter_from_server(
        self,
        *,
        silent: bool = True,
        min_interval_seconds: float = 0.0,
    ) -> None:
        self.proxy_operations.sync_random_ip_counter_from_server(
            silent=silent,
            min_interval_seconds=min_interval_seconds,
        )

    def load_saved_config(
        self,
        path: Optional[str] = None,
        *,
        strict: bool = False,
    ) -> RuntimeConfig:
        cfg = self._command_service.load_saved_config(path, strict=strict)
        self.hydrate_from_config(cfg)
        return cfg

    def save_config(self, cfg: RuntimeConfig, path: Optional[str] = None) -> str:
        self.config = cfg
        self.hydrate_from_config(cfg)
        return self._command_service.save_config(cfg, path)

    def save_current_config(
        self,
        path: Optional[str] = None,
        *,
        config: Optional[RuntimeConfig] = None,
    ) -> str:
        cfg = config or build_runtime_config_snapshot(
            RuntimeConfig(),
            question_entries=self.get_survey_snapshot().get("question_entries") or [],
            questions_info=self.get_survey_snapshot().get("questions_info") or [],
        )
        self.write_runtime_settings_to_config(cfg)
        snapshot = self.get_survey_snapshot()
        cfg.url = str(snapshot.get("url") or "")
        cfg.survey_title = str(snapshot.get("survey_title") or "")
        cfg.survey_provider = str(snapshot.get("survey_provider") or "wjx")
        cfg.questions_info = list(snapshot.get("questions_info") or [])
        cfg.question_entries = list(snapshot.get("question_entries") or [])
        self.config = cfg
        return self.dependencies.configuration.save(cfg, path)


__all__ = ["RunController"]
