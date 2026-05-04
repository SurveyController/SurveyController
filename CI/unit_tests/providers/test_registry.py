from __future__ import annotations
import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from software.core.task import ExecutionConfig, ExecutionState
from software.providers.common import SURVEY_PROVIDER_CREDAMO, SURVEY_PROVIDER_QQ, SURVEY_PROVIDER_WJX
from software.providers import registry

def test_parse_survey_routes_detected_provider_through_cache_loader() -> None:
    qq_url = 'https://wj.qq.com/s2/123/demo'

    async def _exercise() -> tuple[object, object, object]:
        qq_url = 'https://wj.qq.com/s2/123/demo'
        adapter = registry._PROVIDER_REGISTRY[SURVEY_PROVIDER_QQ]
        with patch.object(adapter, 'parse_survey', return_value='qq-definition') as parse_mock, patch.object(registry, 'parse_survey_with_cache', side_effect=lambda _url, loader: loader(qq_url)) as cache_mock:
            result = await registry.parse_survey(qq_url)
        return (result, cache_mock, parse_mock)
    result, cache_mock, parse_mock = asyncio.run(_exercise())
    assert result == 'qq-definition'
    cache_mock.assert_called_once()
    parse_mock.assert_called_once_with(qq_url)

def test_fill_survey_uses_provider_run_context_and_selected_adapter() -> None:

    async def _exercise() -> tuple[bool, list[tuple[str, bool]], object]:
        state = ExecutionState(config=ExecutionConfig(survey_provider=SURVEY_PROVIDER_WJX))
        status_updates: list[tuple[str, bool]] = []
        state.update_thread_status = lambda _thread_name, status_text, *, running: status_updates.append((status_text, running))
        adapter = registry._PROVIDER_REGISTRY[SURVEY_PROVIDER_WJX]

        @contextmanager
        def fake_provider_run_context(*_args, **_kwargs):
            yield 'resolved-plan'
        with patch.object(adapter, 'fill_survey', return_value=True) as fill_mock, patch.object(registry, 'provider_run_context', fake_provider_run_context):
            result = await registry.fill_survey(object(), ExecutionConfig(survey_provider=SURVEY_PROVIDER_WJX), state, stop_signal='stop', thread_name='Worker-1', psycho_plan='ignored-plan', provider=SURVEY_PROVIDER_WJX)
        return (result, status_updates, fill_mock)
    result, status_updates, fill_mock = asyncio.run(_exercise())
    assert result is True
    assert status_updates == [('识别题目', True)]
    assert fill_mock.call_args.kwargs['psycho_plan'] == 'resolved-plan'

def test_handle_submission_verification_detected_uses_ctx_config_provider() -> None:

    async def _exercise():
        ctx = SimpleNamespace(config=SimpleNamespace(survey_provider=SURVEY_PROVIDER_CREDAMO))
        adapter = registry._PROVIDER_REGISTRY[SURVEY_PROVIDER_CREDAMO]
        with patch.object(adapter, 'handle_submission_verification_detected') as handler_mock:
            await registry.handle_submission_verification_detected(ctx, 'gui', 'stop')
        return (handler_mock, ctx)
    handler_mock, ctx = asyncio.run(_exercise())
    handler_mock.assert_called_once_with(ctx, 'gui', 'stop')

def test_wait_for_submission_verification_routes_timeout_and_stop_signal() -> None:

    async def _exercise():
        adapter = registry._PROVIDER_REGISTRY[SURVEY_PROVIDER_QQ]
        driver = object()
        with patch.object(adapter, 'wait_for_submission_verification', return_value=True) as wait_mock:
            result = await registry.wait_for_submission_verification(driver, provider=SURVEY_PROVIDER_QQ, timeout=9, stop_signal='stop')
        return (result, wait_mock, driver)
    result, wait_mock, driver = asyncio.run(_exercise())
    assert result is True
    wait_mock.assert_called_once_with(driver, timeout=9, stop_signal='stop')
