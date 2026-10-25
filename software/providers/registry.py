from __future__ import annotations

from typing import Any, Optional

from surveycore.core.engine.provider_common import provider_run_context
from software.core.task import ExecutionConfig, ExecutionState
from software.providers.adapter_base import CallableProviderAdapter, ProviderAdapterHooks
from software.providers.contracts import (
    ProviderAdapter,
    ProviderParseResult,
    ProviderSubmissionResult,
)
from software.providers.common import (
    SURVEY_PROVIDER_CREDAMO,
    SURVEY_PROVIDER_QQ,
    SURVEY_PROVIDER_WJX,
    detect_survey_provider,
    normalize_survey_parse_url,
    normalize_survey_provider,
)
from surveycore.providers.hooks import HookTarget, build_fill_http_hook, build_parse_hook


def _resolve_provider(*, provider: Optional[str] = None, ctx: Any = None) -> str:
    if provider is not None:
        return normalize_survey_provider(provider, default=SURVEY_PROVIDER_WJX)
    if ctx is not None:
        return normalize_survey_provider(
            getattr(getattr(ctx, "config", ctx), "survey_provider", None),
            default=SURVEY_PROVIDER_WJX,
        )
    return SURVEY_PROVIDER_WJX


_WJX_PARSE: HookTarget = ("wjx.provider.parser", "parse_wjx_survey")
_QQ_PARSE: HookTarget = ("tencent.provider.parser", "parse_qq_survey")
_CREDAMO_PARSE: HookTarget = ("credamo.provider.parser", "parse_credamo_survey")

_WJX_FILL_HTTP: HookTarget = ("wjx.provider.http_runtime", "brush_wjx_http")
_QQ_FILL_HTTP: HookTarget = ("tencent.provider.http_runtime", "brush_qq_http")
_CREDAMO_FILL_HTTP: HookTarget = ("credamo.provider.http_runtime", "brush_credamo_http")


async def _wjx_browser_runtime_removed(*_args: Any, **_kwargs: Any) -> bool:
    raise RuntimeError("问卷星已固化为纯 HTTP 提交链路，不再支持浏览器填答兜底")


async def _qq_browser_runtime_removed(*_args: Any, **_kwargs: Any) -> bool:
    raise RuntimeError("腾讯问卷已固化为纯 HTTP 提交链路，不再支持浏览器填答兜底")


async def _credamo_browser_runtime_removed(*_args: Any, **_kwargs: Any) -> bool:
    raise RuntimeError("见数已固化为纯 HTTP 提交链路，不再支持浏览器填答兜底")


_PROVIDER_REGISTRY: dict[str, ProviderAdapter] = {
    SURVEY_PROVIDER_WJX: CallableProviderAdapter(
        SURVEY_PROVIDER_WJX,
        ProviderAdapterHooks(
            parse_survey=build_parse_hook(SURVEY_PROVIDER_WJX, _WJX_PARSE),
            fill_survey_http=build_fill_http_hook(_WJX_FILL_HTTP),
            fill_survey=_wjx_browser_runtime_removed,
        ),
    ),
    SURVEY_PROVIDER_QQ: CallableProviderAdapter(
        SURVEY_PROVIDER_QQ,
        ProviderAdapterHooks(
            parse_survey=build_parse_hook(SURVEY_PROVIDER_QQ, _QQ_PARSE),
            fill_survey=_qq_browser_runtime_removed,
            fill_survey_http=build_fill_http_hook(_QQ_FILL_HTTP),
        ),
    ),
    SURVEY_PROVIDER_CREDAMO: CallableProviderAdapter(
        SURVEY_PROVIDER_CREDAMO,
        ProviderAdapterHooks(
            parse_survey=build_parse_hook(SURVEY_PROVIDER_CREDAMO, _CREDAMO_PARSE),
            fill_survey=_credamo_browser_runtime_removed,
            fill_survey_http=build_fill_http_hook(_CREDAMO_FILL_HTTP),
        ),
    ),
}


def _get_provider_adapter(
    *,
    provider: Optional[str] = None,
    ctx: Any = None,
    url: Optional[str] = None,
) -> ProviderAdapter:
    resolved = _resolve_provider(provider=provider, ctx=ctx)
    if url:
        resolved = detect_survey_provider(url)
    adapter = _PROVIDER_REGISTRY.get(resolved)
    if adapter is None:
        raise RuntimeError(f"不支持的问卷 provider: {resolved}")
    return adapter


async def parse_survey(url: str) -> ProviderParseResult:
    normalized_url = normalize_survey_parse_url(url)
    return await _get_provider_adapter(url=normalized_url).parse_survey_async(normalized_url)


async def fill_survey_http(
    config: ExecutionConfig,
    state: ExecutionState,
    *,
    stop_signal: Any = None,
    thread_name: str = "",
    psycho_plan: Any = None,
    provider: Optional[str] = None,
    proxy_address: str | None = None,
    user_agent: str | None = None,
    user_agent_profile: Any = None,
    submit_proxy_lease_factory: Any = None,
) -> ProviderSubmissionResult:
    adapter = _get_provider_adapter(provider=provider, ctx=state)
    try:
        state.update_thread_status(thread_name, "构造答案", running=True)
    except Exception:
        pass
    with provider_run_context(
        config,
        state=state,
        thread_name=thread_name,
        psycho_plan=psycho_plan,
    ) as resolved_plan:
        return await adapter.fill_survey_http_async(
            config,
            state,
            stop_signal=stop_signal,
            thread_name=thread_name,
            psycho_plan=resolved_plan,
            proxy_address=proxy_address,
            user_agent=user_agent,
            user_agent_profile=user_agent_profile,
            submit_proxy_lease_factory=submit_proxy_lease_factory,
        )


__all__ = [
    "fill_survey_http",
    "parse_survey",
]
