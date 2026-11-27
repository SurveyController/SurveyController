from __future__ import annotations

import asyncio

import pytest
from surveycore.providers.errors import (
    SubmissionVerificationRequiredError,
    SurveyProviderUnavailableAtRuntimeError,
)

import software.core.engine.async_runtime_loop as runtime_loop
from CI.unit_tests.engine.async_runtime_loop_fakes import _build_runner
from software.core.ai.runtime import AIRuntimeError
from software.core.engine.failure_reason import FailureReason
from software.core.task import ExecutionConfig, ProxyLease
from software.network.http.submission import post_submission


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
        runner, state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [9]
        seen_errors: list[BaseException] = []
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
        monkeypatch.setattr(
            runner,
            "_handle_http_transport_error",
            lambda exc: seen_errors.append(exc) or True,
        )

        await runner.run()

        assert len(seen_errors) == 1
        assert state.get_terminal_stop_snapshot()[0] == ""
        assert scheduler.release_calls[0]["requeue"] is False

    @pytest.mark.asyncio
    async def test_run_remote_protocol_error_stops_with_unknown_result(self, monkeypatch) -> None:
        config = ExecutionConfig(
            url="https://www.credamo.com/answer.html#/s/demo", survey_provider="credamo"
        )
        runner, state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [10, None]
        seen_errors: list[BaseException] = []
        release_flags: list[bool] = []
        reported_results: list[str] = []

        async def submit_after_request_start(**kwargs):
            await kwargs["submit_proxy_lease_factory"]()
            raise runtime_loop.http_client.RemoteProtocolError("server disconnected")

        monkeypatch.setattr(runner.http_submitter, "submit", submit_after_request_start)
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
        monkeypatch.setattr(runner, "_report_submission_result", reported_results.append)

        await runner.run()

        assert seen_errors == []
        assert release_flags == []
        assert reported_results == []
        assert scheduler.release_calls[0]["requeue"] is False
        assert runner.stop_policy.failure_calls == []
        assert state.cur_num == 0
        assert state.get_terminal_stop_snapshot()[0] == "submission_result_unknown"

    @pytest.mark.asyncio
    async def test_run_proxy_error_requeues_without_unknown_result(self, monkeypatch) -> None:
        config = ExecutionConfig(
            url="https://www.wjx.cn/vm/demo.aspx",
            survey_provider="wjx",
            random_proxy_ip_enabled=True,
        )
        config.proxy_ip_pool.append(ProxyLease(address="http://1.1.1.1:80", source="unit"))
        runner, state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [10, None]
        seen_errors: list[BaseException] = []
        reported_results: list[str] = []
        release_flags: list[bool] = []

        async def failing_post(*_args, **_kwargs):
            raise runtime_loop.http_client.ProxyError("631 Internal Server Error")

        async def submit_via_proxy(**kwargs):
            await kwargs["submit_proxy_lease_factory"]()
            return await post_submission(failing_post, config.url)

        monkeypatch.setattr(runner.http_submitter, "submit", submit_via_proxy)
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(
            runner,
            "_select_session_proxy_and_ua",
            lambda: asyncio.sleep(0, result=(None, "UA")),
        )
        monkeypatch.setattr(runner, "_report_submission_result", reported_results.append)
        monkeypatch.setattr(
            runner,
            "_handle_http_transport_error",
            lambda exc: seen_errors.append(exc) or False,
        )
        monkeypatch.setattr(
            runner,
            "_release_round_resources",
            lambda *, requeue_reverse_fill: release_flags.append(requeue_reverse_fill),
        )

        await runner.run()

        assert len(seen_errors) == 1
        assert isinstance(seen_errors[0], runtime_loop.SubmissionConnectionError)
        assert isinstance(seen_errors[0].__cause__, runtime_loop.http_client.ProxyError)
        assert reported_results == ["failed"]
        assert release_flags == [True]
        assert scheduler.release_calls[0]["requeue"] is True
        assert scheduler.release_calls[0]["delay_seconds"] > 0
        assert state.get_terminal_stop_snapshot()[0] == ""

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
