from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

from software.core.task import ExecutionConfig, ExecutionState, ProxyLease
from software.network import session_policy
from software.network.proxy.sidecar_client import ProxySidecarError


class _FakeSidecarClient:
    def __init__(self) -> None:
        self.apply_config_calls = 0
        self.prefetch_calls: list[int] = []
        self.acquire_calls: list[tuple[str, bool]] = []
        self.mark_bad_calls: list[dict[str, object]] = []
        self.raise_on_prefetch = False
        self.leases: list[ProxyLease | None] = []

    def apply_config(self, _settings) -> dict[str, object]:
        self.apply_config_calls += 1
        return {"ok": True}

    def prefetch(self, expected_count: int) -> dict[str, object]:
        self.prefetch_calls.append(int(expected_count))
        if self.raise_on_prefetch:
            raise ProxySidecarError("prefetch failed")
        return {"ok": True}

    def acquire_lease(self, *, thread_name: str, wait: bool) -> ProxyLease | None:
        self.acquire_calls.append((thread_name, bool(wait)))
        if self.leases:
            return self.leases.pop(0)
        return None

    def mark_bad(self, *, thread_name: str, proxy_address: str, cooldown_seconds: float) -> dict[str, object]:
        self.mark_bad_calls.append(
            {
                "thread_name": thread_name,
                "proxy_address": proxy_address,
                "cooldown_seconds": cooldown_seconds,
            }
        )
        return {"ok": True}


class SessionPolicyTests:
    def test_record_bad_proxy_never_pauses_task(self) -> None:
        assert not session_policy._record_bad_proxy_and_maybe_pause(ExecutionState(), object())

    def test_resolve_proxy_request_num_caps_by_waiters_remaining_and_global_limit(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(target_num=200))
        ctx.cur_num = 10
        ctx.proxy_waiting_threads = 120
        ctx.proxy_in_use_by_thread = {
            "Worker-1": ProxyLease(address="http://1.1.1.1:8000"),
            "Worker-2": ProxyLease(address="http://2.2.2.2:8000"),
        }
        assert session_policy._resolve_proxy_request_num_locked(ctx) == 80
        ctx.config.target_num = 12
        assert session_policy._resolve_proxy_request_num_locked(ctx) == 0

    def test_select_proxy_for_session_returns_none_when_random_proxy_disabled(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=False))
        with patch.object(session_policy, "_sidecar_client") as sidecar_factory:
            assert session_policy._select_proxy_for_session(ctx, "Worker-1") is None
        sidecar_factory.assert_not_called()

    def test_select_proxy_for_session_applies_config_prefetches_and_marks_proxy_in_use(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True, target_num=3))
        ctx.proxy_waiting_threads = 2
        lease = ProxyLease(address="http://1.1.1.1:8000", source="unit")
        client = _FakeSidecarClient()
        client.leases = [lease]
        with patch.object(session_policy, "_sidecar_client", return_value=client), patch(
            "software.network.proxy.policy.settings.get_proxy_settings",
            return_value=SimpleNamespace(source="default", custom_api_url="", area_code="", occupy_minute=1),
        ):
            selected = session_policy._select_proxy_for_session(ctx, "Worker-1")
        assert selected == "http://1.1.1.1:8000"
        assert client.apply_config_calls == 1
        assert client.prefetch_calls == [3]
        assert client.acquire_calls == [("Worker-1", False)]
        assert ctx.proxy_in_use_by_thread["Worker-1"].address == "http://1.1.1.1:8000"

    def test_select_proxy_for_session_waits_and_restarts_sidecar_after_failure(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True, target_num=1))
        client = _FakeSidecarClient()
        client.raise_on_prefetch = True
        client.leases = [None, ProxyLease(address="http://9.9.9.9:8000", source="api")]
        wait_calls: list[float] = []
        restart_calls: list[bool] = []

        def fake_wait(*_args, **_kwargs) -> bool:
            wait_calls.append(1.0)
            client.raise_on_prefetch = False
            return False

        with patch.object(session_policy, "_sidecar_client", return_value=client), patch.object(
            session_policy,
            "_wait_for_next_proxy_cycle",
            side_effect=fake_wait,
        ), patch.object(session_policy, "restart_proxy_sidecar", side_effect=lambda: restart_calls.append(True) or client), patch(
            "software.network.proxy.policy.settings.get_proxy_settings",
            return_value=SimpleNamespace(source="default", custom_api_url="", area_code="", occupy_minute=1),
        ):
            selected = session_policy._select_proxy_for_session(ctx, "Worker-1", wait=True)
        assert selected == "http://9.9.9.9:8000"
        assert restart_calls == [True]
        assert wait_calls == [1.0, 1.0]

    def test_mark_proxy_temporarily_bad_adds_cooldown_discards_runtime_view_and_notifies_sidecar(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        ctx.config.proxy_ip_pool = [
            ProxyLease(address="http://1.1.1.1:8000"),
            ProxyLease(address="http://2.2.2.2:8000"),
        ]
        client = _FakeSidecarClient()
        with patch.object(session_policy, "_sidecar_client", return_value=client):
            session_policy._mark_proxy_temporarily_bad(ctx, "http://1.1.1.1:8000", cooldown_seconds=180.0)
        assert ctx.is_proxy_in_cooldown("http://1.1.1.1:8000")
        assert [lease.address for lease in ctx.config.proxy_ip_pool] == ["http://2.2.2.2:8000"]
        assert client.mark_bad_calls == [
            {
                "thread_name": "",
                "proxy_address": "http://1.1.1.1:8000",
                "cooldown_seconds": 180.0,
            }
        ]

    def test_discard_unresponsive_proxy_removes_runtime_view_and_notifies_sidecar(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        ctx.config.proxy_ip_pool = [
            ProxyLease(address="http://1.1.1.1:8000"),
            ProxyLease(address="http://2.2.2.2:8000"),
        ]
        client = _FakeSidecarClient()
        with patch.object(session_policy, "_sidecar_client", return_value=client):
            session_policy._discard_unresponsive_proxy(ctx, " http://1.1.1.1:8000 ")
        assert [lease.address for lease in ctx.config.proxy_ip_pool] == ["http://2.2.2.2:8000"]
        assert client.mark_bad_calls == [
            {
                "thread_name": "",
                "proxy_address": "http://1.1.1.1:8000",
                "cooldown_seconds": 0.0,
            }
        ]

    def test_should_stop_proxy_wait_honors_stop_signal_and_state_stop_event(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        stop_signal = SimpleNamespace(is_set=lambda: True)
        assert session_policy._should_stop_proxy_wait(ctx, stop_signal) is True
        ctx.stop_event.set()
        assert session_policy._should_stop_proxy_wait(ctx, None) is True

    def test_wait_for_next_proxy_cycle_delegates_to_runtime_condition(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        called: list[float] = []
        ctx.wait_for_runtime_change = lambda *, stop_signal=None, timeout=None: called.append(float(timeout or 0.0)) or False
        assert session_policy._wait_for_next_proxy_cycle(ctx, None, timeout=0.5) is False
        assert called == [0.5]

    def test_expired_proxy_cooldown_is_cleared_by_execution_state(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        ctx.proxy_cooldown_until_by_address["http://1.1.1.1:8000"] = time.time() - 1.0
        assert not ctx.is_proxy_in_cooldown("http://1.1.1.1:8000")

    def test_select_user_agent_returns_none_when_disabled(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_user_agent_enabled=False))
        with patch.object(session_policy, "_select_user_agent_from_ratios") as select_user_agent:
            assert session_policy._select_user_agent_for_session(ctx) == (None, None)
        select_user_agent.assert_not_called()
