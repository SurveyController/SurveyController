from __future__ import annotations

import logging
from typing import Any, Optional

from surveycore.core.engine.stop_signal import StopSignalLike
from software.core.task import ExecutionConfig, ExecutionState
from software.providers.common import (
    SURVEY_PROVIDER_CREDAMO,
    SURVEY_PROVIDER_QQ,
    SURVEY_PROVIDER_WJX,
    normalize_survey_provider,
)
from software.providers.contracts import ProviderFailure
from software.providers.registry import fill_survey_http
from surveycore.providers.http_logic import get_http_logic_fallback_reason

HTTP_RUNTIME_PROVIDERS = {
    SURVEY_PROVIDER_WJX,
    SURVEY_PROVIDER_QQ,
    SURVEY_PROVIDER_CREDAMO,
}


class AsyncHttpSubmitter:
    

    def __init__(self, *, config: ExecutionConfig, state: ExecutionState, slot_label: str) -> None:
        self.config = config
        self.state = state
        self.slot_label = slot_label

    def uses_http_runtime(self) -> bool:
        provider = normalize_survey_provider(self.config.survey_provider)
        if not bool(str(self.config.url or "").strip()) or provider not in HTTP_RUNTIME_PROVIDERS:
            return False
        questions = list((self.config.questions_metadata or {}).values())
        return not bool(get_http_logic_fallback_reason(questions))

    def resolve_block_reason(self) -> str:
        provider = normalize_survey_provider(self.config.survey_provider)
        if provider not in HTTP_RUNTIME_PROVIDERS:
            return ""
        url = str(self.config.url or "").strip()
        if not url:
            return "问卷链接为空，无法进入纯 HTTP 提交"
        questions = list((self.config.questions_metadata or {}).values())
        reason = str(get_http_logic_fallback_reason(questions) or "").strip()
        if reason:
            return reason
        return ""

    async def submit(
        self,
        *,
        stop_signal: StopSignalLike,
        proxy_address: Optional[str],
        user_agent: Optional[str],
        user_agent_profile: Any = None,
        submit_proxy_lease_factory: Any = None,
    ) -> bool:
        result = await fill_survey_http(
            self.config,
            self.state,
            stop_signal=stop_signal,
            thread_name=self.slot_label,
            provider=self.config.survey_provider,
            proxy_address=proxy_address,
            user_agent=user_agent,
            user_agent_profile=user_agent_profile,
            submit_proxy_lease_factory=submit_proxy_lease_factory,
        )
        if result.failure is not None:
            _record_provider_failure(result.failure, operation="提交")
            raise result.failure.exception
        return result.submitted


def _record_provider_failure(failure: ProviderFailure, *, operation: str) -> None:
    category = failure.category.value
    logging.error(
        "Provider[%s] %s失败 category=%s: %s",
        failure.provider,
        operation,
        category,
        failure.message,
    )
    add_note = getattr(failure.exception, "add_note", None)
    if callable(add_note):
        add_note(f"provider={failure.provider}; category={category}")


__all__ = ["AsyncHttpSubmitter", "HTTP_RUNTIME_PROVIDERS"]
