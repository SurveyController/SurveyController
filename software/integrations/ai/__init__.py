"""AI 外部服务适配。"""

from software.integrations.ai.client import (
    AI_PROVIDERS,
    DEFAULT_SYSTEM_PROMPT_FREE,
    DEFAULT_SYSTEM_PROMPT_PROVIDER,
    agenerate_answer,
    get_ai_readiness_error,
    get_ai_settings,
    get_default_system_prompt,
    save_ai_settings,
    atest_connection,
)
from software.integrations.ai.settings import reset_ai_settings

__all__ = [
    "AI_PROVIDERS",
    "DEFAULT_SYSTEM_PROMPT_FREE",
    "DEFAULT_SYSTEM_PROMPT_PROVIDER",
    "agenerate_answer",
    "get_ai_readiness_error",
    "get_ai_settings",
    "get_default_system_prompt",
    "reset_ai_settings",
    "save_ai_settings",
    "atest_connection",
]

