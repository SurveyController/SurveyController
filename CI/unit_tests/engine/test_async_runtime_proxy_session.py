from __future__ import annotations

from types import SimpleNamespace

import pytest

import software.core.engine.async_proxy_session as proxy_session
from software.core.task import ExecutionConfig, ExecutionState

from .async_runtime_loop_fakes import _build_runner


class AsyncRuntimeProxySessionTests:
    @pytest.mark.asyncio
    async def test_select_session_proxy_and_ua_does_not_pre_acquire_proxy(
        self, monkeypatch
    ) -> None:
        config = ExecutionConfig(random_proxy_ip_enabled=True, survey_provider="wjx")
        state = ExecutionState(config=config)
        calls: list[str] = []

        async def fake_select_proxy_for_session_async(*_args, **_kwargs):
            calls.append("select")
            return "http://1.1.1.1:80"

        monkeypatch.setattr(
            proxy_session,
            "_select_proxy_for_session_async",
            fake_select_proxy_for_session_async,
            raising=False,
        )
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
