from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from software.core.task import ExecutionConfig, ExecutionState
from software.providers import registry
from software.providers.adapter_base import CallableProviderAdapter, ProviderAdapterHooks
from software.providers.common import (
    SURVEY_PROVIDER_CREDAMO,
    SURVEY_PROVIDER_WJX,
)
from software.providers.contracts import (
    ProviderErrorCategory,
    ProviderParseResult,
    ProviderSubmissionRejectedError,
    ProviderSubmissionResult,
)
from surveycore.providers.contracts import SurveyDefinition
from surveycore.providers.errors import SubmissionVerificationRequiredError
from surveycore.providers.hooks import build_fill_http_hook, build_parse_hook
from software.network.session_policy import SubmitProxyUnavailableError


async def test_parse_survey_routes_detected_provider_directly() -> None:
    url = "https://wj.qq.com/s2/123/demo"
    definition = SurveyDefinition(provider="qq", title="问卷", questions=[])
    adapter = SimpleNamespace(
        parse_survey_async=AsyncMock(
            return_value=ProviderParseResult(provider="qq", definition=definition)
        )
    )

    with patch.object(registry, "_get_provider_adapter", return_value=adapter):
        result = await registry.parse_survey(url)

    assert result.definition is definition
    adapter.parse_survey_async.assert_awaited_once_with(url)


async def test_parse_survey_normalizes_credamo_short_url_before_dispatch() -> None:
    short_url = "https://www.credamo.com/s/demo/"
    normalized_url = "https://www.credamo.com/answer.html#/s/demo/"
    definition = SurveyDefinition(provider="credamo", title="问卷", questions=[])
    adapter = SimpleNamespace(
        parse_survey_async=AsyncMock(
            return_value=ProviderParseResult(provider="credamo", definition=definition)
        )
    )

    with patch.object(registry, "_get_provider_adapter", return_value=adapter) as get_adapter:
        result = await registry.parse_survey(short_url)

    assert result.definition is definition
    get_adapter.assert_called_once_with(url=normalized_url)
    adapter.parse_survey_async.assert_awaited_once_with(normalized_url)


async def test_fill_survey_http_routes_provider_and_runtime_context() -> None:
    config = ExecutionConfig(survey_provider=SURVEY_PROVIDER_CREDAMO)
    state = ExecutionState(config=config)
    adapter = registry._PROVIDER_REGISTRY[SURVEY_PROVIDER_CREDAMO]
    result = ProviderSubmissionResult(provider="credamo", submitted=True)

    def run_context(*_args, **_kwargs):
        from contextlib import nullcontext

        return nullcontext("resolved-plan")

    with (
        patch.object(adapter, "fill_survey_http_async", new=AsyncMock(return_value=result)) as fill,
        patch.object(registry, "provider_run_context", run_context),
    ):
        actual = await registry.fill_survey_http(
            config,
            state,
            stop_signal="stop",
            thread_name="Worker-1",
            psycho_plan="ignored",
            proxy_address="http://1.1.1.1:80",
            user_agent="UA",
        )

    assert actual.succeeded
    assert fill.await_args.kwargs["psycho_plan"] == "resolved-plan"
    assert fill.await_args.kwargs["proxy_address"] == "http://1.1.1.1:80"
    assert fill.await_args.kwargs["user_agent"] == "UA"


async def test_provider_adapter_classifies_submission_failures() -> None:
    async def submit(*_args, **_kwargs):
        raise SubmissionVerificationRequiredError("需要验证")

    adapter = CallableProviderAdapter(
        SURVEY_PROVIDER_WJX,
        ProviderAdapterHooks(parse_survey=AsyncMock(), fill_survey_http=submit),
    )
    result = await adapter.fill_survey_http_async(ExecutionConfig(), ExecutionState())
    assert result.failure is not None
    assert result.failure.category is ProviderErrorCategory.VERIFICATION_REQUIRED


async def test_provider_adapter_classifies_missing_submit_proxy_as_unavailable() -> None:
    async def submit(*_args, **_kwargs):
        raise SubmitProxyUnavailableError("提交代理不可用")

    adapter = CallableProviderAdapter(
        SURVEY_PROVIDER_WJX,
        ProviderAdapterHooks(parse_survey=AsyncMock(), fill_survey_http=submit),
    )
    result = await adapter.fill_survey_http_async(ExecutionConfig(), ExecutionState())
    assert result.failure is not None
    assert result.failure.category is ProviderErrorCategory.UNAVAILABLE


async def test_provider_adapter_classifies_explicit_submission_rejection() -> None:
    async def submit(*_args, **_kwargs):
        raise ProviderSubmissionRejectedError("提交被拒绝")

    adapter = CallableProviderAdapter(
        SURVEY_PROVIDER_WJX,
        ProviderAdapterHooks(parse_survey=AsyncMock(), fill_survey_http=submit),
    )
    result = await adapter.fill_survey_http_async(ExecutionConfig(), ExecutionState())
    assert result.failure is not None
    assert result.failure.category is ProviderErrorCategory.SUBMISSION_REJECTED


async def test_generic_runtime_error_remains_unknown() -> None:
    async def submit(*_args, **_kwargs):
        raise RuntimeError("提交流程内部错误")

    adapter = CallableProviderAdapter(
        SURVEY_PROVIDER_WJX,
        ProviderAdapterHooks(parse_survey=AsyncMock(), fill_survey_http=submit),
    )
    result = await adapter.fill_survey_http_async(ExecutionConfig(), ExecutionState())
    assert result.failure is not None
    assert result.failure.category is ProviderErrorCategory.UNKNOWN


def test_registry_exposes_http_only_adapter_contract() -> None:
    assert set(registry.__all__) == {"parse_survey", "fill_survey_http"}
    assert not hasattr(registry._PROVIDER_REGISTRY[SURVEY_PROVIDER_WJX], "fill_survey_async")


async def test_provider_hook_rejects_non_async_return_value() -> None:
    with patch(
        "surveycore.providers.hooks._load_hook", return_value=lambda *_args, **_kwargs: True
    ):
        hook = build_fill_http_hook(("fake.module", "sync_http_fill"))
        try:
            await hook(ExecutionConfig(), ExecutionState())
        except TypeError as exc:
            assert "provider hook 必须返回 awaitable" in str(exc)
        else:
            raise AssertionError("同步 provider hook 不应再被接受")


async def test_parse_hook_normalizes_tuple_result_to_survey_definition() -> None:
    async def fake_parse(_url: str):
        return ([{"num": 1, "title": "Q1", "type_code": "3"}], "  标题  ")

    with patch("surveycore.providers.hooks._load_hook", return_value=fake_parse):
        hook = build_parse_hook("qq", ("fake.module", "parse"))
        definition = await hook("https://wj.qq.com/s2/demo")

    assert isinstance(definition, SurveyDefinition)
    assert definition.provider == "qq"
    assert definition.title == "标题"
