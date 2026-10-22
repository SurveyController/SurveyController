from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import software.core.engine.async_runtime_loop as runtime_loop
from software.core.engine.failure_reason import FailureReason
from software.core.task import ExecutionConfig, ProxyLease
from surveycore.providers.errors import SubmissionVerificationRequiredError

from .async_runtime_loop_fakes import _build_runner


class AsyncRuntimeProxyRetryTests:
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
