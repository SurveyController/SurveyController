from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import software.core.engine.async_runtime_loop as runtime_loop
import software.core.engine.async_proxy_session as proxy_session
import software.core.engine.async_round_resources as round_resources
from software.core.ai.runtime import AIRuntimeError
from software.core.engine.async_events import AsyncRunContext
from software.core.engine.async_runtime_loop import AsyncSlotRunner
from software.core.engine.failure_reason import FailureReason
from software.core.task import ExecutionConfig, ExecutionState, ProxyLease
from software.providers.contracts import SurveyQuestionMeta
from software.providers.errors import SubmissionVerificationRequiredError, SurveyProviderUnavailableAtRuntimeError


class _FakeScheduler:
    def __init__(self, acquire_values=None) -> None:
        self.acquire_values = list(acquire_values or [1])
        self.release_calls: list[dict[str, object]] = []

    async def acquire(self):
        if not self.acquire_values:
            return None
        return self.acquire_values.pop(0)

    async def release(self, token_id, **kwargs):
        self.release_calls.append({"token_id": token_id, **kwargs})


class _FakeStopPolicy:
    def __init__(self, state: ExecutionState | None = None) -> None:
        self.state = state
        self.failure_calls: list[dict[str, object]] = []
        self.success_calls: list[dict[str, object]] = []
        self.proxy_threshold = 3

    def record_failure(self, stop_signal, **kwargs):
        self.failure_calls.append({"stop_signal": stop_signal, **kwargs})
        return bool(kwargs.get("threshold_override") == 1)

    def record_success(self, stop_signal, **kwargs):
        self.success_calls.append({"stop_signal": stop_signal, **kwargs})
        if self.state is not None:
            self.state.cur_num += 1
        return False

    def trigger_target_reached_stop(self, stop_signal):
        if self.state is not None:
            self.state.mark_terminal_stop("target_reached", message="目标份数已达成")
        stop_signal.set()

    def proxy_unavailable_threshold(self):
        return self.proxy_threshold


def _build_runner(
    *,
    config: ExecutionConfig | None = None,
    state: ExecutionState | None = None,
    stop_set: bool = False,
):
    config = config or ExecutionConfig(
        target_num=3,
        submit_interval_range_seconds=[1, 3],
        survey_provider="wjx",
        url="https://www.wjx.cn/vm/demo.aspx",
    )
    state = state or ExecutionState(config=config)
    state.step_updates = []
    state.update_thread_status = lambda *_args, **_kwargs: None
    state.update_thread_step = lambda *args, **kwargs: state.step_updates.append((args, kwargs))
    stop_event = asyncio.Event()
    if stop_set:
        stop_event.set()
    run_context = AsyncRunContext(
        state=state,
        stop_event=stop_event,
        pause_event=asyncio.Event(),
    )
    scheduler = _FakeScheduler()
    runner = AsyncSlotRunner(
        slot_id=1,
        config=config,
        state=state,
        run_context=run_context,
        scheduler=scheduler,
        runtime_bridge=None,
    )
    runner.stop_policy = _FakeStopPolicy(state)
    return runner, state, run_context, scheduler


class AsyncRuntimeLoopLargeTests:
    @pytest.mark.asyncio
    async def test_should_stop_loop_honors_stop_event(self) -> None:
        runner, _state, _ctx, _scheduler = _build_runner(stop_set=True)

        assert await runner._should_stop_loop() is True

    @pytest.mark.asyncio
    async def test_should_stop_loop_honors_target_num(self) -> None:
        config = ExecutionConfig(target_num=2, survey_provider="wjx")
        state = ExecutionState(config=config, cur_num=2)
        runner, _state, _ctx, _scheduler = _build_runner(config=config, state=state)

        assert await runner._should_stop_loop() is True

    @pytest.mark.asyncio
    async def test_sleep_or_stop_handles_zero_delay_and_timeout(self) -> None:
        runner, _state, _ctx, _scheduler = _build_runner()

        assert await runner._sleep_or_stop(0) is False
        assert await runner._sleep_or_stop(0.001) is False

    @pytest.mark.asyncio
    async def test_resolve_dispatch_delay_seconds_covers_zero_fixed_and_random(self, monkeypatch) -> None:
        config = ExecutionConfig(submit_interval_range_seconds=[0, 0], survey_provider="wjx")
        runner, _state, _ctx, _scheduler = _build_runner(config=config)
        assert runner._resolve_dispatch_delay_seconds() == 0.0

        config.submit_interval_range_seconds = [2, 2]
        assert runner._resolve_dispatch_delay_seconds() == 2.0

        config.submit_interval_range_seconds = [1, 3]
        monkeypatch.setattr(runtime_loop.random, "uniform", lambda _a, _b: 2.5)
        assert runner._resolve_dispatch_delay_seconds() == 2.5

    @pytest.mark.asyncio
    async def test_select_session_proxy_and_ua_does_not_pre_acquire_proxy(self, monkeypatch) -> None:
        config = ExecutionConfig(random_proxy_ip_enabled=True, survey_provider="wjx")
        state = ExecutionState(config=config)
        calls: list[str] = []

        async def fake_select_proxy_for_session_async(*_args, **_kwargs):
            calls.append("select")
            return "http://1.1.1.1:80"

        monkeypatch.setattr(proxy_session, "_select_proxy_for_session_async", fake_select_proxy_for_session_async, raising=False)
        monkeypatch.setattr(
            proxy_session,
            "_select_user_agent_for_session",
            lambda *_args, **_kwargs: SimpleNamespace(ua="UA", category="pc", label="电脑网页端"),
        )
        runner, _state, _ctx, _scheduler = _build_runner(config=config, state=state)

        proxy, ua = await runner._select_session_proxy_and_ua()

        assert (proxy, ua) == (None, "UA")
        assert calls == []
        assert state.snapshot_active_proxy_addresses() == set()

    @pytest.mark.asyncio
    async def test_prepare_round_context_marks_terminal_stop_when_reverse_fill_exhausted(self, monkeypatch) -> None:
        config = ExecutionConfig(target_num=2, survey_provider="wjx")
        state = ExecutionState(config=config)
        state.reset_pending_distribution = lambda *_args, **_kwargs: None
        state.reserve_joint_sample = lambda *_args, **_kwargs: 0
        state.acquire_reverse_fill_sample = lambda *_args, **_kwargs: SimpleNamespace(status="exhausted", sample=None)
        terminal: list[tuple[str, str, str]] = []
        state.mark_terminal_stop = lambda category, *, failure_reason, message: terminal.append((category, failure_reason, message))
        state.release_joint_sample = lambda *_args, **_kwargs: None
        monkeypatch.setattr(round_resources, "ensure_joint_psychometric_answer_plan", lambda _config: SimpleNamespace(sample_count=2))
        runner, _state, ctx, _scheduler = _build_runner(config=config, state=state)

        assert await runner._prepare_round_context() is False
        assert terminal[0][0] == "reverse_fill_exhausted"
        assert ctx.stop_event.is_set()

    @pytest.mark.asyncio
    async def test_uses_http_runtime_respects_logic_parse_status(self) -> None:
        config = ExecutionConfig(url="https://www.wjx.cn/vm/demo.aspx", survey_provider="wjx")
        config.questions_metadata = {
            1: SurveyQuestionMeta(
                num=1,
                title="Q1",
                has_jump=True,
                logic_parse_status="complete",
                jump_rules=[{"option_index": 0, "jumpto": 2}],
            ),
            2: SurveyQuestionMeta(num=2, title="Q2"),
        }
        runner, _state, _ctx, _scheduler = _build_runner(config=config)

        assert runner._uses_http_runtime() is True

        config.questions_metadata = {
            1: SurveyQuestionMeta(
                num=1,
                title="Q1",
                has_jump=True,
                jump_rules=[{"option_index": 0, "jumpto": 1}],
            ),
            2: SurveyQuestionMeta(num=2, title="Q2"),
        }

        assert runner._uses_http_runtime() is False
        assert "第1题" in runner._resolve_http_runtime_block_reason()

    @pytest.mark.asyncio
    async def test_run_blocks_unsupported_http_logic_without_fallback(self) -> None:
        config = ExecutionConfig(url="https://www.wjx.cn/vm/demo.aspx", survey_provider="wjx")
        config.questions_metadata = {
            1: SurveyQuestionMeta(
                num=1,
                title="Q1",
                has_jump=True,
                jump_rules=[{"option_index": 0, "jumpto": 1}],
            ),
        }
        runner, state, ctx, scheduler = _build_runner(config=config)

        await runner.run()
        await asyncio.sleep(0)

        assert ctx.stop_event.is_set()
        assert scheduler.release_calls == []
        assert runner.stop_policy.failure_calls[0]["status_text"] == "纯 HTTP 不支持"
        assert "第1题" in str(runner.stop_policy.failure_calls[0]["log_message"])
        assert state.get_terminal_stop_snapshot()[0] == "http_runtime_only"

    @pytest.mark.asyncio
    async def test_run_uses_http_runtime_for_credamo(self, monkeypatch) -> None:
        config = ExecutionConfig(url="https://www.credamo.com/answer.html#/s/demo", survey_provider="credamo")
        runner, _state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [6, None]
        monkeypatch.setattr(runner.http_submitter, "submit", lambda **_kwargs: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_select_session_proxy_and_ua", lambda: asyncio.sleep(0, result=(None, "UA")))

        await runner.run()

        assert scheduler.release_calls[0]["token_id"] == 6
        assert runner.stop_policy.failure_calls == []

    @pytest.mark.asyncio
    async def test_run_random_proxy_enabled_acquires_proxy_only_at_submit(self, monkeypatch) -> None:
        config = ExecutionConfig(
            url="https://www.wjx.cn/vm/demo.aspx",
            survey_provider="wjx",
            random_proxy_ip_enabled=True,
        )
        config.proxy_ip_pool.append(ProxyLease(address="http://1.1.1.1:80", source="unit"))
        runner, state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [6, None]
        submit_calls: list[dict[str, object]] = []
        pre_submit_active: list[set[str]] = []

        async def fake_prepare():
            pre_submit_active.append(state.snapshot_active_proxy_addresses())
            return True

        async def fake_submit(**kwargs):
            factory = kwargs["submit_proxy_lease_factory"]
            lease = await factory()
            submit_calls.append({**kwargs, "lease": lease})
            return True

        monkeypatch.setattr(runner.http_submitter, "submit", fake_submit)
        monkeypatch.setattr(runner, "_prepare_round_context", fake_prepare)
        monkeypatch.setattr(runner, "_select_session_proxy_and_ua", lambda: asyncio.sleep(0, result=(None, "UA")))

        await runner.run()

        assert pre_submit_active == [set()]
        assert submit_calls[0]["proxy_address"] is None
        assert submit_calls[0]["lease"].address == "http://1.1.1.1:80"
        assert state.snapshot_active_proxy_addresses() == set()
        assert scheduler.release_calls[0]["requeue"] is True

    @pytest.mark.asyncio
    async def test_run_random_proxy_enabled_never_submits_without_proxy(self, monkeypatch) -> None:
        config = ExecutionConfig(
            url="https://www.wjx.cn/vm/demo.aspx",
            survey_provider="wjx",
            random_proxy_ip_enabled=True,
        )
        runner, _state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [6, None]
        submit_calls: list[dict[str, object]] = []
        release_flags: list[bool] = []

        async def fake_submit(**kwargs):
            factory = kwargs["submit_proxy_lease_factory"]
            lease = await factory()
            if not getattr(lease, "address", None):
                raise runtime_loop.SubmitProxyUnavailableError("提交前未获取到随机 IP")
            submit_calls.append(kwargs)
            return True

        monkeypatch.setattr(runner.http_submitter, "submit", fake_submit)
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_select_session_proxy_and_ua", lambda: asyncio.sleep(0, result=(None, "UA")))
        monkeypatch.setattr(runtime_loop, "_record_bad_proxy_and_maybe_pause", lambda *_args, **_kwargs: False)
        async def fake_acquire_submit_proxy(*_args, **_kwargs):
            return SimpleNamespace(address=None, provider="unknown")

        monkeypatch.setattr(runtime_loop, "acquire_submit_proxy", fake_acquire_submit_proxy)
        monkeypatch.setattr(
            runner,
            "_release_round_resources",
            lambda *, requeue_reverse_fill: release_flags.append(requeue_reverse_fill),
        )

        await runner.run()

        assert submit_calls == []
        assert release_flags == [True]
        assert scheduler.release_calls[0]["requeue"] is True

    @pytest.mark.asyncio
    async def test_run_http_runtime_reports_fixed_submit_steps(self, monkeypatch) -> None:
        config = ExecutionConfig(url="https://www.credamo.com/answer.html#/s/demo", survey_provider="credamo")
        runner, state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [6, None]
        monkeypatch.setattr(runner.http_submitter, "submit", lambda **_kwargs: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_select_session_proxy_and_ua", lambda: asyncio.sleep(0, result=(None, "UA")))
        monkeypatch.setattr(runtime_loop, "update_http_submit_step", lambda state, thread, label: asyncio.sleep(0, result=state.update_thread_step(thread, 1, 4, status_text=label, running=True)))

        await runner.run()

        labels = [kwargs.get("status_text") for _args, kwargs in state.step_updates]
        assert "准备请求" in labels

    @pytest.mark.asyncio
    async def test_run_reports_success_when_random_proxy_enabled(self, monkeypatch) -> None:
        config = ExecutionConfig(
            url="https://www.wjx.cn/vm/demo.aspx",
            survey_provider="wjx",
            random_proxy_ip_enabled=True,
        )
        runner, _state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [6, None]
        reports: list[dict[str, object]] = []

        async def fake_report(**kwargs):
            reports.append(kwargs)
            return True

        async def select_proxy():
            runner.proxy_session.proxy_provider = "default"
            return "http://1.1.1.1:80", "UA"

        monkeypatch.setattr(runner.http_submitter, "submit", lambda **_kwargs: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_select_session_proxy_and_ua", select_proxy)
        monkeypatch.setattr(runtime_loop, "get_session_snapshot", lambda: {"user_id": 73952})
        monkeypatch.setattr(runtime_loop, "report_submission_result_async", fake_report)

        await runner.run()
        await asyncio.sleep(0)

        assert reports == [
            {
                "user_id": 73952,
                "survey_url": "https://www.wjx.cn/vm/demo.aspx",
                "result": "success",
                "proxy_provider": "default",
            }
        ]

    @pytest.mark.asyncio
    async def test_run_reports_failure_when_random_proxy_enabled(self, monkeypatch) -> None:
        config = ExecutionConfig(
            url="https://www.wjx.cn/vm/demo.aspx",
            survey_provider="wjx",
            random_proxy_ip_enabled=True,
        )
        runner, _state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [6, None]
        reports: list[dict[str, object]] = []

        async def fake_report(**kwargs):
            reports.append(kwargs)
            return True

        monkeypatch.setattr(runner, "_prepare_round_context", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(runtime_loop, "get_session_snapshot", lambda: {"user_id": 73952})
        monkeypatch.setattr(runtime_loop, "report_submission_result_async", fake_report)

        await runner.run()
        await asyncio.sleep(0)

        assert reports == [
            {
                "user_id": 73952,
                "survey_url": "https://www.wjx.cn/vm/demo.aspx",
                "result": "failed",
                "proxy_provider": "unknown",
            }
        ]

    @pytest.mark.asyncio
    async def test_run_airuntime_error_releases_resources_and_requeues(self, monkeypatch) -> None:
        config = ExecutionConfig(url="https://www.credamo.com/answer.html#/s/demo", survey_provider="credamo")
        runner, _state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [5, None]
        monkeypatch.setattr(runner.http_submitter, "submit", lambda **_kwargs: (_ for _ in ()).throw(AIRuntimeError("ai bad")))
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_select_session_proxy_and_ua", lambda: asyncio.sleep(0, result=(None, "UA")))
        monkeypatch.setattr(runner, "_handle_ai_runtime_error", lambda exc: asyncio.sleep(0, result=False))
        release_flags: list[bool] = []
        monkeypatch.setattr(runner, "_release_round_resources", lambda *, requeue_reverse_fill: release_flags.append(requeue_reverse_fill))

        await runner.run()

        assert release_flags == [True]
        assert scheduler.release_calls[0]["requeue"] is True

    @pytest.mark.asyncio
    async def test_run_submission_verification_error_stops_without_requeue(self, monkeypatch) -> None:
        config = ExecutionConfig(url="https://www.wjx.cn/vm/demo.aspx", survey_provider="wjx")
        runner, state, ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [8]
        monkeypatch.setattr(
            runner.http_submitter,
            "submit",
            lambda **_kwargs: (_ for _ in ()).throw(SubmissionVerificationRequiredError("请启用随机 IP 后再提交")),
        )
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_select_session_proxy_and_ua", lambda: asyncio.sleep(0, result=(None, "UA")))

        await runner.run()
        await asyncio.sleep(0)

        assert ctx.stop_event.is_set()
        assert scheduler.release_calls[0]["requeue"] is False
        assert state.get_terminal_stop_snapshot()[0] == "submission_verification"
        assert state.get_terminal_stop_snapshot()[1] == FailureReason.SUBMISSION_VERIFICATION_REQUIRED.value

    @pytest.mark.asyncio
    async def test_run_submission_verification_with_random_proxy_retries_next_ip(self, monkeypatch) -> None:
        config = ExecutionConfig(
            url="https://www.wjx.cn/vm/demo.aspx",
            survey_provider="wjx",
            random_proxy_ip_enabled=True,
            stop_on_fail_enabled=True,
            fail_threshold=3,
        )
        runner, state, ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [8, None]

        def fail_submit(**_kwargs):
            raise SubmissionVerificationRequiredError("当前随机 IP 已被风控，正在更换随机 IP 重试。")

        async def select_proxy():
            runner.proxy_session.proxy_address = "http://1.1.1.1:80"
            return "http://1.1.1.1:80", "UA"

        monkeypatch.setattr(runner.http_submitter, "submit", fail_submit)
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_select_session_proxy_and_ua", select_proxy)

        await runner.run()
        await asyncio.sleep(0)

        assert not ctx.stop_event.is_set()
        assert scheduler.release_calls[0]["requeue"] is True
        assert state.is_proxy_in_cooldown("http://1.1.1.1:80")
        assert runner.stop_policy.failure_calls[0]["failure_reason"] == FailureReason.SUBMISSION_VERIFICATION_REQUIRED
        assert runner.stop_policy.failure_calls[0]["status_text"] == "触发验证，换IP"
        assert state.get_terminal_stop_snapshot()[0] == ""

    @pytest.mark.asyncio
    async def test_run_provider_unavailable_error_stops_without_requeue(self, monkeypatch) -> None:
        config = ExecutionConfig(url="https://www.wjx.cn/vm/demo.aspx", survey_provider="wjx")
        runner, state, ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [10]
        monkeypatch.setattr(
            runner.http_submitter,
            "submit",
            lambda **_kwargs: (_ for _ in ()).throw(SurveyProviderUnavailableAtRuntimeError("问卷已暂停")),
        )
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_select_session_proxy_and_ua", lambda: asyncio.sleep(0, result=(None, "UA")))

        await runner.run()
        await asyncio.sleep(0)

        assert ctx.stop_event.is_set()
        assert scheduler.release_calls[0]["requeue"] is False
        assert state.get_terminal_stop_snapshot()[0] == "survey_provider_unavailable"
        assert state.get_terminal_stop_snapshot()[1] == FailureReason.SURVEY_PROVIDER_UNAVAILABLE.value

    @pytest.mark.asyncio
    async def test_run_http_transport_error_breaks_when_handler_requests_stop(self, monkeypatch) -> None:
        config = ExecutionConfig(url="https://www.credamo.com/answer.html#/s/demo", survey_provider="credamo")
        runner, _state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [9]
        monkeypatch.setattr(runner.http_submitter, "submit", lambda **_kwargs: (_ for _ in ()).throw(runtime_loop.http_client.ConnectTimeout("proxy bad")))
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(runner, "_select_session_proxy_and_ua", lambda: asyncio.sleep(0, result=("http://1.1.1.1:80", "UA")))
        monkeypatch.setattr(runner, "_handle_http_transport_error", lambda _exc: True)

        await runner.run()

        assert scheduler.release_calls[0]["requeue"] is False

    @pytest.mark.asyncio
    async def test_http_transport_error_discards_proxy_without_cooldown(self) -> None:
        config = ExecutionConfig(
            url="https://www.wjx.cn/vm/demo.aspx",
            survey_provider="wjx",
            random_proxy_ip_enabled=True,
        )
        runner, state, _ctx, _scheduler = _build_runner(config=config)
        proxy_address = "http://1.1.1.1:80"
        runner.proxy_session.proxy_address = proxy_address

        assert runner._handle_http_transport_error(runtime_loop.http_client.ConnectTimeout("proxy bad")) is False

        assert not state.is_proxy_in_cooldown(proxy_address)
        assert runner.stop_policy.failure_calls[0]["status_text"] == "代理连接失败"

    @pytest.mark.asyncio
    async def test_run_remote_protocol_error_uses_transport_handler(self, monkeypatch) -> None:
        config = ExecutionConfig(url="https://www.credamo.com/answer.html#/s/demo", survey_provider="credamo")
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
        monkeypatch.setattr(runner, "_select_session_proxy_and_ua", lambda: asyncio.sleep(0, result=("http://1.1.1.1:80", "UA")))
        monkeypatch.setattr(runner, "_release_round_resources", lambda *, requeue_reverse_fill: release_flags.append(requeue_reverse_fill))

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
        config = ExecutionConfig(url="https://www.credamo.com/answer.html#/s/demo", survey_provider="credamo")
        runner, _state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [11, None]
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        release_flags: list[bool] = []
        monkeypatch.setattr(runner, "_release_round_resources", lambda *, requeue_reverse_fill: release_flags.append(requeue_reverse_fill))

        await runner.run()

        assert release_flags == [True]
        assert scheduler.release_calls[0]["requeue"] is True
        assert runner.stop_policy.failure_calls[0]["failure_reason"] == FailureReason.FILL_FAILED
