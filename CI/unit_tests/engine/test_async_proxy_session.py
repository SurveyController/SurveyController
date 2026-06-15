from __future__ import annotations

import asyncio
import threading

import software.core.engine.async_proxy_session as proxy_session_module
from software.core.engine.async_proxy_session import AsyncProxySession
from software.core.task import ExecutionConfig, ExecutionState


class AsyncProxySessionTests:
    def test_custom_proxy_source_does_not_pre_acquire_proxy(self, monkeypatch) -> None:
        calls: list[str] = []

        async def fake_select_proxy(*_args, **_kwargs):
            calls.append("select")
            return "http://1.1.1.1:8000"

        monkeypatch.setattr(proxy_session_module, "_select_proxy_for_session_async", fake_select_proxy, raising=False)

        config = ExecutionConfig(random_proxy_ip_enabled=True, proxy_source="custom")
        state = ExecutionState(config=config)
        session = AsyncProxySession(
            config=config,
            state=state,
            slot_label="Slot-1",
            stop_signal=state.stop_event,
            runtime_bridge=None,
            update_step=lambda _text: None,
        )

        proxy_address, _ua = asyncio.run(session.select_proxy_and_user_agent())

        assert proxy_address is None
        assert calls == []

    def test_official_proxy_source_does_not_pre_acquire_proxy(self, monkeypatch) -> None:
        calls: list[str] = []

        async def fake_select_proxy(*_args, **_kwargs):
            calls.append("select")
            return "http://1.1.1.1:8000"

        monkeypatch.setattr(proxy_session_module, "_select_proxy_for_session_async", fake_select_proxy, raising=False)

        config = ExecutionConfig(random_proxy_ip_enabled=True, proxy_source="default")
        state = ExecutionState(config=config, stop_event=threading.Event())
        session = AsyncProxySession(
            config=config,
            state=state,
            slot_label="Slot-1",
            stop_signal=state.stop_event,
            runtime_bridge=None,
            update_step=lambda _text: None,
        )

        proxy_address, _ua = asyncio.run(session.select_proxy_and_user_agent())

        assert proxy_address is None
        assert calls == []
