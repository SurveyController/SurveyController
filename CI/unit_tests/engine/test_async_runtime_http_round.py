from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import software.core.engine.async_runtime_loop as runtime_loop
import software.core.engine.async_round_resources as round_resources
from software.core.task import ExecutionConfig, ExecutionState
from surveycore.providers.contracts import SurveyQuestionMeta

from .async_runtime_loop_fakes import _build_runner


class AsyncRuntimeHttpRoundTests:
    @pytest.mark.asyncio
    async def test_prepare_round_context_marks_terminal_stop_when_reverse_fill_exhausted(
        self, monkeypatch
    ) -> None:
        config = ExecutionConfig(target_num=2, survey_provider="wjx")
        state = ExecutionState(config=config)
        state.reset_pending_distribution = lambda *_args, **_kwargs: None
        state.reserve_joint_sample = lambda *_args, **_kwargs: 0
        state.acquire_reverse_fill_sample = lambda *_args, **_kwargs: SimpleNamespace(
            status="exhausted", sample=None
        )
        terminal: list[tuple[str, str, str]] = []
        state.mark_terminal_stop = lambda category, *, failure_reason, message: terminal.append(
            (category, failure_reason, message)
        )
        state.release_joint_sample = lambda *_args, **_kwargs: None
        monkeypatch.setattr(
            round_resources,
            "ensure_joint_psychometric_answer_plan",
            lambda _config: SimpleNamespace(sample_count=2),
        )
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
        config = ExecutionConfig(
            url="https://www.credamo.com/answer.html#/s/demo", survey_provider="credamo"
        )
        runner, _state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [6, None]
        monkeypatch.setattr(
            runner.http_submitter, "submit", lambda **_kwargs: asyncio.sleep(0, result=True)
        )
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(
            runner, "_select_session_proxy_and_ua", lambda: asyncio.sleep(0, result=(None, "UA"))
        )

        await runner.run()

        assert scheduler.release_calls[0]["token_id"] == 6
        assert runner.stop_policy.failure_calls == []

    @pytest.mark.asyncio
    async def test_run_http_runtime_reports_fixed_submit_steps(self, monkeypatch) -> None:
        config = ExecutionConfig(
            url="https://www.credamo.com/answer.html#/s/demo", survey_provider="credamo"
        )
        runner, state, _ctx, scheduler = _build_runner(config=config)
        scheduler.acquire_values = [6, None]
        monkeypatch.setattr(
            runner.http_submitter, "submit", lambda **_kwargs: asyncio.sleep(0, result=True)
        )
        monkeypatch.setattr(runner, "_prepare_round_context", lambda: asyncio.sleep(0, result=True))
        monkeypatch.setattr(
            runner, "_select_session_proxy_and_ua", lambda: asyncio.sleep(0, result=(None, "UA"))
        )
        monkeypatch.setattr(
            runtime_loop,
            "update_http_submit_step",
            lambda state, thread, label: asyncio.sleep(
                0, result=state.update_thread_step(thread, 1, 4, status_text=label, running=True)
            ),
        )

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
        runner.submission_report_enabled = lambda: True
        runner.app_version = ""
        scheduler.acquire_values = [6, None]
        reports: list[dict[str, object]] = []

        async def fake_report(**kwargs):
            reports.append(kwargs)
            return True

        async def select_proxy():
            runner.proxy_session.proxy_provider = "default"
            return "http://1.1.1.1:80", "UA"

        monkeypatch.setattr(
            runner.http_submitter, "submit", lambda **_kwargs: asyncio.sleep(0, result=True)
        )
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
                "enabled": True,
                "client_version": "",
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
        runner.submission_report_enabled = lambda: True
        runner.app_version = ""
        scheduler.acquire_values = [6, None]
        reports: list[dict[str, object]] = []

        async def fake_report(**kwargs):
            reports.append(kwargs)
            return True

        monkeypatch.setattr(
            runner, "_prepare_round_context", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        )
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
                "enabled": True,
                "client_version": "",
            }
        ]
