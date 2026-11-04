from __future__ import annotations

import asyncio

import pytest

import software.core.engine.async_runtime_loop as runtime_loop
from software.core.ai.runtime import AIRuntimeError
from software.core.engine.failure_reason import FailureReason
from software.core.task import ExecutionConfig
from surveycore.providers.errors import (
    SubmissionVerificationRequiredError,
    SurveyProviderUnavailableAtRuntimeError,
)

from .async_runtime_loop_fakes import _build_runner


class AsyncRuntimeErrorsTests:
    @pytest.mark.asyncio
    async def test_run_airuntime_error_releases_resources_and_requeues(self, monkeypatch) -> None:
        config = ExecutionConfig(
            url="https://www.credamo.com/answer.html#/s/demo", survey_provider="credamo"
        )
        runner, _state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [5, None]
        monkeypatch.setattr(
            runner.http_submitter,
            "submit",
            lambda **_kwargs: (_ for _ in ()).throw(AIRuntimeError("ai bad")),
        )
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(
            runner, "_select_session_proxy_and_ua", lambda: asyncio.sleep(0, result=(None, "UA"))
        )
        monkeypatch.setattr(
            runner, "_handle_ai_runtime_error", lambda exc: asyncio.sleep(0, result=False)
        )
        release_flags: list[bool] = []
        monkeypatch.setattr(
            runner,
            "_release_round_resources",
            lambda *, requeue_reverse_fill: release_flags.append(requeue_reverse_fill),
        )

        await runner.run()

        assert release_flags == [True]
        assert scheduler.release_calls[0]["requeue"] is True

    @pytest.mark.asyncio
    async def test_run_submission_verification_error_stops_without_requeue(
        self, monkeypatch
    ) -> None:
        config = ExecutionConfig(url="https://www.wjx.cn/vm/demo.aspx", survey_provider="wjx")
        runner, state, ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [8]
        monkeypatch.setattr(
            runner.http_submitter,
            "submit",
            lambda **_kwargs: (_ for _ in ()).throw(
                SubmissionVerificationRequiredError("请启用随机 IP 后再提交")
            ),
        )
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(
            runner, "_select_session_proxy_and_ua", lambda: asyncio.sleep(0, result=(None, "UA"))
        )

        await runner.run()
        await asyncio.sleep(0)

        assert ctx.stop_event.is_set()
        assert scheduler.release_calls[0]["requeue"] is False
        assert state.get_terminal_stop_snapshot()[0] == "submission_verification"
        assert (
            state.get_terminal_stop_snapshot()[1]
            == FailureReason.SUBMISSION_VERIFICATION_REQUIRED.value
        )

    @pytest.mark.asyncio
    async def test_run_provider_unavailable_error_stops_without_requeue(self, monkeypatch) -> None:
        config = ExecutionConfig(url="https://www.wjx.cn/vm/demo.aspx", survey_provider="wjx")
        runner, state, ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [10]
        monkeypatch.setattr(
            runner.http_submitter,
            "submit",
            lambda **_kwargs: (_ for _ in ()).throw(
                SurveyProviderUnavailableAtRuntimeError("问卷已暂停")
            ),
        )
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(
            runner, "_select_session_proxy_and_ua", lambda: asyncio.sleep(0, result=(None, "UA"))
        )

        await runner.run()
        await asyncio.sleep(0)

        assert ctx.stop_event.is_set()
        assert scheduler.release_calls[0]["requeue"] is False
        assert state.get_terminal_stop_snapshot()[0] == "survey_provider_unavailable"
        assert (
            state.get_terminal_stop_snapshot()[1] == FailureReason.SURVEY_PROVIDER_UNAVAILABLE.value
        )

    @pytest.mark.asyncio
    async def test_run_http_transport_error_breaks_when_handler_requests_stop(
        self, monkeypatch
    ) -> None:
        config = ExecutionConfig(
            url="https://www.credamo.com/answer.html#/s/demo", survey_provider="credamo"
        )
        runner, _state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [9]
        monkeypatch.setattr(
            runner.http_submitter,
            "submit",
            lambda **_kwargs: (_ for _ in ()).throw(
                runtime_loop.http_client.ConnectTimeout("proxy bad")
            ),
        )
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(
            runner,
            "_select_session_proxy_and_ua",
            lambda: asyncio.sleep(0, result=("http://1.1.1.1:80", "UA")),
        )
        monkeypatch.setattr(runner, "_handle_http_transport_error", lambda _exc: True)

        await runner.run()

        assert scheduler.release_calls[0]["requeue"] is False

    @pytest.mark.asyncio
    async def test_run_remote_protocol_error_uses_transport_handler(self, monkeypatch) -> None:
        config = ExecutionConfig(
            url="https://www.credamo.com/answer.html#/s/demo", survey_provider="credamo"
        )
        runner, _state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [10, None]
        seen_errors: list[BaseException] = []
        release_flags: list[bool] = []
        monkeypatch.setattr(
            runner.http_submitter,
            "submit",
            lambda **_kwargs: (_ for _ in ()).throw(
                runtime_loop.http_client.RemoteProtocolError("server disconnected")
            ),
        )
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(
            runner,
            "_select_session_proxy_and_ua",
            lambda: asyncio.sleep(0, result=("http://1.1.1.1:80", "UA")),
        )
        monkeypatch.setattr(
            runner,
            "_release_round_resources",
            lambda *, requeue_reverse_fill: release_flags.append(requeue_reverse_fill),
        )

        def handle_transport_error(exc: BaseException) -> bool:
            seen_errors.append(exc)
            return False

        monkeypatch.setattr(runner, "_handle_http_transport_error", handle_transport_error)

        await runner.run()

        assert isinstance(seen_errors[0], runtime_loop.http_client.RemoteProtocolError)
        assert release_flags == [True]
        assert scheduler.release_calls[0]["requeue"] is True
        assert runner.stop_policy.failure_calls == []

    @pytest.mark.asyncio
    async def test_run_generic_exception_records_failure_and_requeues(self, monkeypatch) -> None:
        config = ExecutionConfig(
            url="https://www.credamo.com/answer.html#/s/demo", survey_provider="credamo"
        )
        runner, _state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [11, None]
        monkeypatch.setattr(
            runner, "_prepare_round_context", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        release_flags: list[bool] = []
        monkeypatch.setattr(
            runner,
            "_release_round_resources",
            lambda *, requeue_reverse_fill: release_flags.append(requeue_reverse_fill),
        )

        await runner.run()

        assert release_flags == [True]
        assert scheduler.release_calls[0]["requeue"] is True
        assert runner.stop_policy.failure_calls[0]["failure_reason"] == FailureReason.FILL_FAILED
