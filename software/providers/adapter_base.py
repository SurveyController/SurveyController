from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from software.core.task import ExecutionConfig, ExecutionState
from surveycore.providers.contracts import SurveyDefinition
from surveycore.providers.errors import (
    SubmissionVerificationRequiredError,
    SurveyEnterpriseUnavailableError,
    SurveyNotOpenError,
    SurveyPausedError,
    SurveyProviderUnavailableAtRuntimeError,
    SurveyStoppedError,
)
from software.network.session_policy import SubmitProxyUnavailableError
from software.providers.contracts import (
    ProviderErrorCategory,
    ProviderFailure,
    ProviderParseResult,
    ProviderSubmissionRejectedError,
    ProviderSubmissionResult,
)

ParseSurveyHook = Callable[[str], Awaitable[SurveyDefinition]]
FillSurveyHttpHook = Callable[..., Awaitable[bool]]


@dataclass(frozen=True)
class ProviderAdapterHooks:
    parse_survey: ParseSurveyHook
    fill_survey_http: FillSurveyHttpHook


class CallableProviderAdapter:
    def __init__(self, provider: str, hooks: ProviderAdapterHooks) -> None:
        self.provider = str(provider or "").strip()
        self._hooks = hooks

    async def parse_survey_async(self, url: str) -> ProviderParseResult:
        try:
            definition = await self._hooks.parse_survey(url)
        except Exception as exc:
            return ProviderParseResult(
                provider=self.provider,
                failure=_provider_failure(self.provider, exc),
            )
        return ProviderParseResult(provider=self.provider, definition=definition)

    async def fill_survey_http_async(
        self,
        config: ExecutionConfig,
        state: ExecutionState,
        *,
        stop_signal: Any = None,
        thread_name: str = "",
        psycho_plan: Any = None,
        proxy_address: str | None = None,
        user_agent: str | None = None,
        user_agent_profile: Any = None,
        submit_proxy_lease_factory: Any = None,
    ) -> ProviderSubmissionResult:
        try:
            submitted = bool(
                await self._hooks.fill_survey_http(
                    config,
                    state,
                    stop_signal=stop_signal,
                    thread_name=thread_name,
                    psycho_plan=psycho_plan,
                    proxy_address=proxy_address,
                    user_agent=user_agent,
                    user_agent_profile=user_agent_profile,
                    submit_proxy_lease_factory=submit_proxy_lease_factory,
                )
            )
        except Exception as exc:
            return ProviderSubmissionResult(
                provider=self.provider,
                submitted=False,
                failure=_provider_failure(self.provider, exc),
            )
        return ProviderSubmissionResult(provider=self.provider, submitted=submitted)

__all__ = [
    "CallableProviderAdapter",
    "ProviderAdapterHooks",
]


def _provider_failure(provider: str, exc: Exception) -> ProviderFailure:
    if isinstance(exc, concurrent.futures.CancelledError):
        category = ProviderErrorCategory.CANCELLED
    elif isinstance(exc, ProviderSubmissionRejectedError):
        category = ProviderErrorCategory.SUBMISSION_REJECTED
    elif isinstance(
        exc,
        (
            SurveyEnterpriseUnavailableError,
            SurveyNotOpenError,
            SurveyPausedError,
            SurveyProviderUnavailableAtRuntimeError,
            SurveyStoppedError,
            SubmitProxyUnavailableError,
        ),
    ):
        category = ProviderErrorCategory.UNAVAILABLE
    elif isinstance(exc, SubmissionVerificationRequiredError):
        category = ProviderErrorCategory.VERIFICATION_REQUIRED
    elif isinstance(exc, httpx.HTTPError):
        category = ProviderErrorCategory.NETWORK
    elif isinstance(exc, (ValueError, TypeError)):
        category = ProviderErrorCategory.CONFIGURATION
    else:
        category = ProviderErrorCategory.UNKNOWN
    return ProviderFailure(
        provider=provider,
        category=category,
        message=str(exc),
        exception=exc,
    )
