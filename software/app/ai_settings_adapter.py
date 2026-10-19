from __future__ import annotations

from typing import Any

from software.application.ports import AiSettingsPort
from software.integrations.ai import (
    AI_PROVIDERS,
    atest_connection,
    get_ai_readiness_error,
    get_ai_settings,
    get_default_system_prompt,
    reset_ai_settings,
    save_ai_settings,
)


class PythonAiSettingsAdapter(AiSettingsPort):
    @property
    def providers(self) -> dict[str, dict[str, Any]]:
        return AI_PROVIDERS

    def default_system_prompt(self) -> str:
        return get_default_system_prompt()

    def get_settings(self) -> dict[str, Any]:
        return get_ai_settings()

    def save_settings(self, **values: Any) -> None:
        save_ai_settings(**values)

    def reset_settings(self) -> None:
        reset_ai_settings()

    def readiness_error(self, config: dict[str, Any] | None = None) -> str:
        return get_ai_readiness_error(config)

    async def test_connection(self) -> str:
        return await atest_connection()


__all__ = ["PythonAiSettingsAdapter"]
