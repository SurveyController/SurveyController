from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from software.application.ports import PreferencesStorePort
from software.io.runtime_environment import preference_store

AI_PROVIDERS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "recommended_models": ["deepseek-flash", "deepseek-v4-pro"],
        "default_model": "deepseek-flash",
    },
    "custom": {
        "label": "OpenAI 兼容",
        "base_url": "",
        "recommended_models": [],
        "default_model": "",
    },
}

CUSTOM_API_PROTOCOLS = {
    "auto": {
        "label": "自动识别（推荐）",
        "description": "自动识别完整端点；只填 /v1 时自动尝试兼容协议",
    },
    "chat_completions": {
        "label": "Chat Completions",
        "description": "兼容 /chat/completions 协议",
    },
    "responses": {
        "label": "Responses",
        "description": "兼容 /responses 协议",
    },
}

AI_MODE_PROVIDER = "provider"

QUESTION_TYPE_FILL = "fill_blank"
QUESTION_TYPE_MULTI = "multi_fill_blank"

_SYSTEM_PROMPT_BASE = (
    "你现在不是AI助手，而是一名有实际使用经验但不专业的普通用户。\n"
    "请按照“填写问卷/填空题”的方式作答，而不是进行解释或对话。\n\n"
    "回答规则：\n"
    "1. 只给出答案本身，不要解释原因，不要分析，不要教学\n"
    "2. 以个人体验和模糊印象为主，可以不确定、可以用模糊一些的表达\n"
    "3. 回答尽量简短，避免长句\n"
    "4. 不要使用专业术语或严谨表述\n\n"
    "请注意：\n"
    "- 不要像AI助手一样分点说明\n"
    "- 不要补充背景知识\n"
    "- 不要解释题目\n"
    "- 不要自称“作为AI”\n\n"
    "如果你的回答开始变得专业、详细或像在解释，请立即改回普通用户的随意回答风格。"
)

DEFAULT_SYSTEM_PROMPT_PROVIDER = (
    _SYSTEM_PROMPT_BASE
    + "\n\n多项填空补充规则：\n"
      "6. 当题目有多个空位时，按空位顺序输出一个字符串，并使用 || 分隔每个答案（示例：答案1||答案2||答案3）"
)

_DEFAULT_AI_SETTINGS: Dict[str, Any] = {
    "ai_mode": AI_MODE_PROVIDER,
    "provider": "deepseek",
    "api_key": "",
    "base_url": "",
    "api_protocol": "auto",
    "model": "",
    "system_prompt": DEFAULT_SYSTEM_PROMPT_PROVIDER,
}
_RUNTIME_AI_SETTINGS: Optional[Dict[str, Any]] = None
_AI_SETTINGS_KEY_PREFIX = "ai/"
_SETTINGS_STORE_FACTORY: Optional[Callable[[], PreferencesStorePort]] = None

__all__ = [
    "AI_MODE_PROVIDER",
    "AI_PROVIDERS",
    "CUSTOM_API_PROTOCOLS",
    "DEFAULT_SYSTEM_PROMPT_PROVIDER",
    "QUESTION_TYPE_FILL",
    "QUESTION_TYPE_MULTI",
    "_normalize_custom_api_protocol",
    "configure_ai_settings_store",
    "get_ai_readiness_error",
    "get_ai_settings",
    "get_default_system_prompt",
    "save_ai_settings",
    "reset_ai_settings",
]


def get_default_system_prompt() -> str:
    return DEFAULT_SYSTEM_PROMPT_PROVIDER


def configure_ai_settings_store(
    store_factory: Callable[[], PreferencesStorePort] | None,
) -> None:
    global _SETTINGS_STORE_FACTORY, _RUNTIME_AI_SETTINGS
    _SETTINGS_STORE_FACTORY = store_factory
    _RUNTIME_AI_SETTINGS = None


def _get_settings_store() -> PreferencesStorePort:
    if _SETTINGS_STORE_FACTORY is None:
        return preference_store()
    return _SETTINGS_STORE_FACTORY()


def _ensure_runtime_settings() -> Dict[str, Any]:
    global _RUNTIME_AI_SETTINGS
    if _RUNTIME_AI_SETTINGS is None:
        _RUNTIME_AI_SETTINGS = _load_ai_settings_from_store()
    return _RUNTIME_AI_SETTINGS


def _load_ai_settings_from_store() -> Dict[str, Any]:
    settings = dict(_DEFAULT_AI_SETTINGS)
    store = _get_settings_store()
    provider = str(store.value(f"{_AI_SETTINGS_KEY_PREFIX}provider", settings["provider"]) or "deepseek").strip()
    settings["provider"] = provider if provider in AI_PROVIDERS else "deepseek"
    settings["api_key"] = str(store.value(f"{_AI_SETTINGS_KEY_PREFIX}api_key", settings["api_key"]) or "")
    settings["base_url"] = str(store.value(f"{_AI_SETTINGS_KEY_PREFIX}base_url", settings["base_url"]) or "").strip()
    settings["api_protocol"] = _normalize_custom_api_protocol(
        store.value(f"{_AI_SETTINGS_KEY_PREFIX}api_protocol", settings["api_protocol"])
    )
    settings["model"] = str(store.value(f"{_AI_SETTINGS_KEY_PREFIX}model", settings["model"]) or "").strip()
    prompt = str(store.value(f"{_AI_SETTINGS_KEY_PREFIX}system_prompt", settings["system_prompt"]) or "").strip()
    settings["system_prompt"] = (
        DEFAULT_SYSTEM_PROMPT_PROVIDER if not prompt or prompt == _SYSTEM_PROMPT_BASE else prompt
    )
    return settings


def _persist_ai_settings(settings: Dict[str, Any]) -> None:
    store = _get_settings_store()
    store.setValue(f"{_AI_SETTINGS_KEY_PREFIX}mode", settings["ai_mode"])
    store.setValue(f"{_AI_SETTINGS_KEY_PREFIX}provider", settings["provider"])
    store.setValue(f"{_AI_SETTINGS_KEY_PREFIX}api_key", settings["api_key"])
    store.setValue(f"{_AI_SETTINGS_KEY_PREFIX}base_url", settings["base_url"])
    store.setValue(f"{_AI_SETTINGS_KEY_PREFIX}api_protocol", settings["api_protocol"])
    store.setValue(f"{_AI_SETTINGS_KEY_PREFIX}model", settings["model"])
    store.setValue(f"{_AI_SETTINGS_KEY_PREFIX}system_prompt", settings["system_prompt"])
    store.sync()


def get_ai_settings() -> Dict[str, Any]:
    
    settings = dict(_ensure_runtime_settings())
    settings["ai_mode"] = AI_MODE_PROVIDER
    provider = str(settings.get("provider") or "deepseek").strip()
    settings["provider"] = provider if provider in AI_PROVIDERS else "deepseek"
    settings["api_protocol"] = _normalize_custom_api_protocol(settings.get("api_protocol"))
    prompt = str(settings.get("system_prompt") or "").strip()
    settings["system_prompt"] = prompt or get_default_system_prompt()
    return settings


def save_ai_settings(
    ai_mode: Optional[str] = None,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    api_protocol: Optional[str] = None,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
):
    
    settings = _ensure_runtime_settings()
    # 保留参数以兼容旧调用，运行时只使用服务商模式。
    del ai_mode
    if provider is not None:
        settings["provider"] = str(provider)
    if api_key is not None:
        settings["api_key"] = str(api_key)
    if base_url is not None:
        settings["base_url"] = str(base_url)
    if api_protocol is not None:
        settings["api_protocol"] = _normalize_custom_api_protocol(api_protocol)
    if model is not None:
        settings["model"] = str(model)
    if system_prompt is not None:
        settings["system_prompt"] = str(system_prompt)
    settings["ai_mode"] = AI_MODE_PROVIDER
    provider_value = str(settings.get("provider") or "deepseek").strip()
    settings["provider"] = provider_value if provider_value in AI_PROVIDERS else "deepseek"
    settings["api_key"] = str(settings.get("api_key") or "")
    settings["base_url"] = str(settings.get("base_url") or "").strip()
    settings["api_protocol"] = _normalize_custom_api_protocol(settings.get("api_protocol"))
    settings["model"] = str(settings.get("model") or "").strip()
    prompt = str(settings.get("system_prompt") or "").strip()
    settings["system_prompt"] = prompt or get_default_system_prompt()
    _persist_ai_settings(settings)


def reset_ai_settings() -> None:
    
    global _RUNTIME_AI_SETTINGS
    store = _get_settings_store()
    for key in (
        f"{_AI_SETTINGS_KEY_PREFIX}mode",
        f"{_AI_SETTINGS_KEY_PREFIX}provider",
        f"{_AI_SETTINGS_KEY_PREFIX}api_key",
        f"{_AI_SETTINGS_KEY_PREFIX}base_url",
        f"{_AI_SETTINGS_KEY_PREFIX}api_protocol",
        f"{_AI_SETTINGS_KEY_PREFIX}model",
        f"{_AI_SETTINGS_KEY_PREFIX}system_prompt",
    ):
        store.remove(key)
    store.sync()
    _RUNTIME_AI_SETTINGS = dict(_DEFAULT_AI_SETTINGS)


def get_ai_readiness_error(config: Optional[Dict[str, Any]] = None) -> str:
    
    settings = get_ai_settings() if config is None else dict(config)
    provider = str(settings.get("provider") or "deepseek").strip() or "deepseek"
    provider_config = AI_PROVIDERS.get(provider)
    if provider_config is None:
        return "服务提供商无效"

    missing_fields: List[str] = []
    if not str(settings.get("api_key") or "").strip():
        missing_fields.append("API Key")

    if provider == "custom":
        if not str(settings.get("base_url") or "").strip():
            missing_fields.append("Base URL")
        if not str(settings.get("model") or "").strip():
            missing_fields.append("模型 ID")
    else:
        resolved_model = str(settings.get("model") or provider_config.get("default_model") or "").strip()
        if not resolved_model:
            missing_fields.append("模型 ID")

    if missing_fields:
        return f"缺少 {'、'.join(missing_fields)}"
    return ""


def _normalize_custom_api_protocol(value: Any) -> str:
    protocol = str(value or "auto").strip().lower()
    if protocol in CUSTOM_API_PROTOCOLS:
        return protocol
    return "auto"
