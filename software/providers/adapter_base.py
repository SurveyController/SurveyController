from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from surveycore.core.engine.runtime_actions import RuntimeActionResult, ensure_runtime_action_result
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
FillSurveyHook = Callable[..., Awaitable[bool]]
FillSurveyHttpHook = Callable[..., Awaitable[bool]]
PagePredicateHook = Callable[[Any], Awaitable[bool]]
ValidationMessageHook = Callable[[Any], Awaitable[str]]
WaitVerificationHook = Callable[..., Awaitable[bool]]
VerificationDetectedHook = Callable[[Any, Any], Awaitable[RuntimeActionResult]]
SubmissionRecoveryHook = Callable[..., Awaitable[bool]]


async def _return_false(*_args: Any, **_kwargs: Any) -> bool:
    return False


async def _return_empty_text(*_args: Any, **_kwargs: Any) -> str:
    return ""


async def _noop_action_result(*_args: Any, **_kwargs: Any) -> RuntimeActionResult:
    return RuntimeActionResult.empty()


@dataclass(frozen=True)
class ProviderAdapterHooks:
    parse_survey: ParseSurveyHook
    fill_survey: FillSurveyHook
    fill_survey_http: FillSurveyHttpHook = _return_false
    is_completion_page: PagePredicateHook = _return_false
    submission_requires_verification: PagePredicateHook = _return_false
    submission_validation_message: ValidationMessageHook = _return_empty_text
    wait_for_submission_verification: WaitVerificationHook = _return_false
    handle_submission_verification_detected: VerificationDetectedHook = _noop_action_result
    attempt_submission_recovery: SubmissionRecoveryHook = _return_false
    consume_submission_success_signal: PagePredicateHook = _return_false
    is_device_quota_limit_page: PagePredicateHook = _return_false


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

    async def fill_survey_async(
        self,
        driver: Any,
        config: ExecutionConfig,
        state: ExecutionState,
        *,
        stop_signal: Any = None,
        thread_name: str = "",
        psycho_plan: Any = None,
    ) -> bool:
        return bool(
            await self._hooks.fill_survey(
                driver,
                config,
                state,
                stop_signal=stop_signal,
                thread_name=thread_name,
                psycho_plan=psycho_plan,
            )
        )

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

    async def is_completion_page_async(self, driver: Any) -> bool:
        return bool(await self._hooks.is_completion_page(driver))

    async def submission_requires_verification_async(self, driver: Any) -> bool:
        return bool(await self._hooks.submission_requires_verification(driver))

    async def submission_validation_message_async(self, driver: Any) -> str:
        return str(await self._hooks.submission_validation_message(driver) or "").strip()

    async def wait_for_submission_verification_async(
        self,
        driver: Any,
        *,
        timeout: int = 3,
        stop_signal: Any = None,
    ) -> bool:
        return bool(
            await self._hooks.wait_for_submission_verification(
                driver,
                timeout=timeout,
                stop_signal=stop_signal,
            )
        )

    async def handle_submission_verification_detected_async(
        self, ctx: Any, stop_signal: Any
    ) -> RuntimeActionResult:
        return ensure_runtime_action_result(
            await self._hooks.handle_submission_verification_detected(ctx, stop_signal)
        )

    async def attempt_submission_recovery_async(
        self,
        driver: Any,
        ctx: Any,
        gui_instance: Any,
        stop_signal: Any,
        *,
        thread_name: str = "",
    ) -> bool:
        return bool(
            await self._hooks.attempt_submission_recovery(
                driver,
                ctx,
                gui_instance,
                stop_signal,
                thread_name=thread_name,
            )
        )

    async def consume_submission_success_signal_async(self, driver: Any) -> bool:
        return bool(await self._hooks.consume_submission_success_signal(driver))

    async def is_device_quota_limit_page_async(self, driver: Any) -> bool:
        return bool(await self._hooks.is_device_quota_limit_page(driver))


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
