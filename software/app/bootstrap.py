from __future__ import annotations

from dataclasses import dataclass

from software.app.ai_settings_adapter import PythonAiSettingsAdapter
from software.app.preferences_adapter import QSettingsPreferences
from software.app.proxy_gateway import PythonProxyGateway
from software.application.configuration import ConfigurationService
from software.application.preferences import PreferencesService
from software.application.ports import (
    AiSettingsPort,
    CleanupRunnerPort,
    ExecutionPreparerPort,
    PreferencesStorePort,
    ProxyGatewayPort,
    RuntimeEnginePort,
)
from software.core.engine.async_engine import AsyncEngineClient
from software.core.engine.cleanup import CleanupRunner
from software.core.engine.runtime_preparation import prepare_execution_artifacts
from software.io.config.repository import JsonConfigRepository
from software.io.runtime_environment import configure_runtime_environment
from software.app.user_paths import get_default_runtime_config_path
from software.integrations.ai.settings import configure_ai_settings_store


@dataclass(frozen=True)
class ApplicationDependencies:
    runtime_engine: RuntimeEnginePort
    cleanup_runner: CleanupRunnerPort
    configuration: ConfigurationService
    execution_preparer: ExecutionPreparerPort
    proxy_gateway: ProxyGatewayPort
    preference_store: PreferencesStorePort
    preferences: PreferencesService
    ai_settings: AiSettingsPort


def create_application_dependencies(
    *,
    runtime_engine: RuntimeEnginePort | None = None,
    cleanup_runner: CleanupRunnerPort | None = None,
    preference_store: PreferencesStorePort | None = None,
    proxy_gateway: ProxyGatewayPort | None = None,
) -> ApplicationDependencies:
    selected_store = preference_store if preference_store is not None else QSettingsPreferences()
    configure_runtime_environment(lambda: selected_store, get_default_runtime_config_path)
    configure_ai_settings_store(lambda: selected_store)
    return ApplicationDependencies(
        runtime_engine=runtime_engine or AsyncEngineClient(),
        cleanup_runner=cleanup_runner or CleanupRunner(),
        configuration=ConfigurationService(JsonConfigRepository()),
        execution_preparer=prepare_execution_artifacts,
        proxy_gateway=proxy_gateway if proxy_gateway is not None else PythonProxyGateway(),
        preference_store=selected_store,
        preferences=PreferencesService(selected_store),
        ai_settings=PythonAiSettingsAdapter(),
    )


__all__ = ["ApplicationDependencies", "create_application_dependencies"]
