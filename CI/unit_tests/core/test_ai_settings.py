from __future__ import annotations

import pytest

from software.app.settings_store import app_settings
from software.core.config.codec import deserialize_runtime_config, serialize_runtime_config
from software.core.config.schema import RuntimeConfig
from software.core.task import ExecutionConfig
from software.integrations.ai import client, settings


def test_legacy_ai_settings_preserve_provider_credentials_and_prompt() -> None:
    store = app_settings()
    for key, value in {
        "mode": "free",
        "provider": "custom",
        "api_key": "test-key",
        "base_url": "https://example.test/v1",
        "api_protocol": "responses",
        "model": "test-model",
        "system_prompt": "用户提示词",
    }.items():
        store.setValue(f"ai/{key}", value)
    store.sync()

    config = settings.get_ai_settings()
    assert config["ai_mode"] == "provider"
    assert settings.get_ai_readiness_error(config) == ""
    settings.save_ai_settings(ai_mode="free")
    settings._RUNTIME_AI_SETTINGS = None
    assert settings.get_ai_settings() == config
    assert store.value("ai/mode") == "provider"


def test_ai_defaults_require_api_key_and_include_multi_blank_instructions() -> None:
    config = settings.get_ai_settings()
    assert config["ai_mode"] == "provider"
    assert settings.get_ai_readiness_error(config) == "缺少 API Key"
    assert "||" in config["system_prompt"]
    assert RuntimeConfig().ai_mode == "provider"
    assert ExecutionConfig().ai_mode == "provider"


@pytest.mark.parametrize("mode", ["free", "provider", "bad", None])
def test_runtime_config_normalizes_legacy_mode_without_losing_provider_fields(mode) -> None:
    config = deserialize_runtime_config({
        "ai_mode": mode,
        "ai_provider": "custom",
        "ai_api_key": "test-key",
        "ai_base_url": "https://example.test/v1",
        "ai_model": "test-model",
        "ai_system_prompt": "用户提示词",
    })
    payload = serialize_runtime_config(config)
    assert payload["ai_mode"] == "provider"
    assert payload["ai_api_key"] == "test-key"
    assert payload["ai_system_prompt"] == "用户提示词"
    assert serialize_runtime_config(RuntimeConfig(ai_mode=mode))["ai_mode"] == "provider"


@pytest.mark.asyncio
async def test_legacy_mode_without_key_fails_before_provider_request(monkeypatch) -> None:
    monkeypatch.setattr(client, "get_ai_settings", lambda: {"ai_mode": "free", "provider": "deepseek"})

    async def unexpected_request(*_args, **_kwargs):
        raise AssertionError("配置不完整时不得发送请求")

    monkeypatch.setattr(client, "acall_chat_completions", unexpected_request)
    with pytest.raises(RuntimeError, match="缺少 API Key"):
        await client.agenerate_answer("题目")


@pytest.mark.asyncio
async def test_legacy_settings_use_configured_provider_endpoint(monkeypatch) -> None:
    settings.save_ai_settings(
        ai_mode="free",
        provider="custom",
        api_key="test-key",
        base_url="https://example.test/v1",
        api_protocol="responses",
        model="test-model",
        system_prompt="用户提示词",
    )
    calls = []

    async def provider_request(*args):
        calls.append(args)
        return "答案"

    monkeypatch.setattr(client, "acall_responses_api", provider_request)
    assert await client.agenerate_answer("题目") == "答案"
    assert calls == [
        ("https://example.test/v1/responses", "test-key", "test-model", "题目", "用户提示词")
    ]
