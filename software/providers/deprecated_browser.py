"""Deprecated browser-provider hooks retained for compatibility."""

from __future__ import annotations

from typing import Any, Optional, Protocol, cast

from surveycore.core.engine.provider_common import provider_run_context
from surveycore.core.engine.runtime_actions import RuntimeActionResult
from software.core.task import ExecutionConfig, ExecutionState
from software.providers.contracts import ProviderAdapter
from software.providers.registry import _get_provider_adapter


class _LegacyBrowserAdapter(ProviderAdapter, Protocol):
    async def fill_survey_async(
        self,
        driver: Any,
        config: ExecutionConfig,
        state: ExecutionState,
        *,
        stop_signal: Any = None,
        thread_name: str = "",
        psycho_plan: Any = None,
    ) -> bool: ...

    async def is_completion_page_async(self, driver: Any) -> bool: ...

    async def submission_requires_verification_async(self, driver: Any) -> bool: ...

    async def submission_validation_message_async(self, driver: Any) -> str: ...

    async def wait_for_submission_verification_async(
        self,
        driver: Any,
        *,
        timeout: int = 3,
        stop_signal: Any = None,
    ) -> bool: ...

    async def attempt_submission_recovery_async(
        self,
        driver: Any,
        ctx: Any,
        gui_instance: Any,
        stop_signal: Any,
        *,
        thread_name: str = "",
    ) -> bool: ...

    async def handle_submission_verification_detected_async(
        self,
        ctx: Any,
        stop_signal: Any,
    ) -> RuntimeActionResult: ...

    async def consume_submission_success_signal_async(self, driver: Any) -> bool: ...

    async def is_device_quota_limit_page_async(self, driver: Any) -> bool: ...


def _get_legacy_browser_adapter(
    *,
    provider: Optional[str] = None,
    ctx: Any = None,
) -> _LegacyBrowserAdapter:
    return cast(_LegacyBrowserAdapter, _get_provider_adapter(provider=provider, ctx=ctx))


async def fill_survey(
    driver: Any,
    config: ExecutionConfig,
    state: ExecutionState,
    *,
    stop_signal: Any = None,
    thread_name: str = "",
    psycho_plan: Any = None,
    provider: Optional[str] = None,
) -> bool:
    adapter = _get_legacy_browser_adapter(provider=provider, ctx=state)
    try:
        state.update_thread_status(thread_name, "识别题目", running=True)
    except Exception:
        pass
    with provider_run_context(
        config,
        state=state,
        thread_name=thread_name,
        psycho_plan=psycho_plan,
    ) as resolved_plan:
        return bool(
            await adapter.fill_survey_async(
                driver,
                config,
                state,
                stop_signal=stop_signal,
                thread_name=thread_name,
                psycho_plan=resolved_plan,
            )
        )


async def is_completion_page(driver: Any, provider: Optional[str] = None) -> bool:
    return bool(
        await _get_legacy_browser_adapter(provider=provider).is_completion_page_async(driver)
    )


async def submission_requires_verification(driver: Any, provider: Optional[str] = None) -> bool:
    adapter = _get_legacy_browser_adapter(provider=provider)
    return bool(await adapter.submission_requires_verification_async(driver))


async def submission_validation_message(driver: Any, provider: Optional[str] = None) -> str:
    adapter = _get_legacy_browser_adapter(provider=provider)
    message = await adapter.submission_validation_message_async(driver)
    return str(message or "").strip()


async def wait_for_submission_verification(
    driver: Any,
    *,
    provider: Optional[str] = None,
    timeout: int = 3,
    stop_signal: Any = None,
) -> bool:
    return bool(
        await _get_legacy_browser_adapter(provider=provider).wait_for_submission_verification_async(
            driver,
            timeout=timeout,
            stop_signal=stop_signal,
        )
    )


async def attempt_submission_recovery(
    driver: Any,
    ctx: Any,
    gui_instance: Any,
    stop_signal: Any,
    *,
    provider: Optional[str] = None,
    thread_name: str = "",
) -> bool:
    return bool(
        await _get_legacy_browser_adapter(provider=provider).attempt_submission_recovery_async(
            driver,
            ctx,
            gui_instance,
            stop_signal,
            thread_name=thread_name,
        )
    )


async def handle_submission_verification_detected(
    ctx: Any,
    stop_signal: Any,
    *,
    provider: Optional[str] = None,
) -> RuntimeActionResult:
    adapter = _get_legacy_browser_adapter(provider=provider, ctx=ctx)
    return await adapter.handle_submission_verification_detected_async(ctx, stop_signal)


async def consume_submission_success_signal(driver: Any, provider: Optional[str] = None) -> bool:
    adapter = _get_legacy_browser_adapter(provider=provider)
    return bool(await adapter.consume_submission_success_signal_async(driver))


async def is_device_quota_limit_page(driver: Any, provider: Optional[str] = None) -> bool:
    adapter = _get_legacy_browser_adapter(provider=provider)
    return bool(await adapter.is_device_quota_limit_page_async(driver))


__all__ = [
    "attempt_submission_recovery",
    "consume_submission_success_signal",
    "fill_survey",
    "handle_submission_verification_detected",
    "is_completion_page",
    "is_device_quota_limit_page",
    "submission_requires_verification",
    "submission_validation_message",
    "wait_for_submission_verification",
]
