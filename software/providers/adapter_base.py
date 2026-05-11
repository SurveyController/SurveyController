"""Provider 适配层公共壳。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from software.core.task import ExecutionConfig, ExecutionState
from software.providers.contracts import SurveyDefinition

ParseSurveyHook = Callable[[str], Awaitable[SurveyDefinition]]
FillSurveyHook = Callable[..., Awaitable[bool]]
PagePredicateHook = Callable[[Any], Awaitable[bool]]
ValidationMessageHook = Callable[[Any], Awaitable[str]]
WaitVerificationHook = Callable[..., Awaitable[bool]]
VerificationDetectedHook = Callable[[Any, Any, Any], Awaitable[None]]
SubmissionRecoveryHook = Callable[..., Awaitable[bool]]


async def _return_false(*_args: Any, **_kwargs: Any) -> bool:
    return False


async def _return_empty_text(*_args: Any, **_kwargs: Any) -> str:
    return ""


async def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


@dataclass(frozen=True)
class ProviderAdapterHooks:
    parse_survey: ParseSurveyHook
    fill_survey: FillSurveyHook
    is_completion_page: PagePredicateHook = _return_false
    submission_requires_verification: PagePredicateHook = _return_false
    submission_validation_message: ValidationMessageHook = _return_empty_text
    wait_for_submission_verification: WaitVerificationHook = _return_false
    handle_submission_verification_detected: VerificationDetectedHook = _noop
    attempt_submission_recovery: SubmissionRecoveryHook = _return_false
    consume_submission_success_signal: PagePredicateHook = _return_false
    is_device_quota_limit_page: PagePredicateHook = _return_false


class CallableProviderAdapter:
    def __init__(self, provider: str, hooks: ProviderAdapterHooks) -> None:
        self.provider = str(provider or "").strip()
        self._hooks = hooks

    async def parse_survey_async(self, url: str) -> SurveyDefinition:
        return await self._hooks.parse_survey(url)

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

    async def handle_submission_verification_detected_async(self, ctx: Any, gui_instance: Any, stop_signal: Any) -> None:
        await self._hooks.handle_submission_verification_detected(ctx, gui_instance, stop_signal)

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
