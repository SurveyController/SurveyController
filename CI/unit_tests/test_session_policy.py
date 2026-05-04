from __future__ import annotations
import time
from unittest.mock import patch
from software.core.task import ExecutionConfig, ExecutionState, ProxyLease
from software.network import session_policy

class SessionPolicyTests:

    def test_record_bad_proxy_never_pauses_task(self) -> None:
        assert not session_policy._record_bad_proxy_and_maybe_pause(ExecutionState(), object())

    def test_resolve_proxy_request_num_caps_by_waiters_remaining_and_global_limit(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(target_num=200))
        ctx.cur_num = 10
        ctx.proxy_waiting_threads = 120
        ctx.proxy_in_use_by_thread = {'Worker-1': ProxyLease(address='http://1.1.1.1:8000'), 'Worker-2': ProxyLease(address='http://2.2.2.2:8000')}
        assert session_policy._resolve_proxy_request_num_locked(ctx) == 80
        ctx.config.target_num = 12
        assert session_policy._resolve_proxy_request_num_locked(ctx) == 0

    def test_purge_unusable_proxy_pool_removes_invalid_duplicate_unpoolable_and_expiring_items(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        ctx.config.proxy_ip_pool = [ProxyLease(address='http://1.1.1.1:8000', poolable=True), ProxyLease(address='http://1.1.1.1:8000', poolable=True), ProxyLease(address='http://2.2.2.2:8000', poolable=False), ProxyLease(address='http://3.3.3.3:8000', poolable=True), '']

        def has_ttl(lease: ProxyLease | None, *, required_ttl_seconds: int) -> bool:
            assert required_ttl_seconds == 30
            return bool(lease and lease.address != 'http://3.3.3.3:8000')
        with patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=30), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', side_effect=has_ttl):
            session_policy._purge_unusable_proxy_pool_locked(ctx)
        assert ctx.config.proxy_ip_pool == [ProxyLease(address='http://1.1.1.1:8000', poolable=True)]

    def test_pop_available_proxy_lease_skips_expiring_proxy(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        expiring = ProxyLease(address='http://1.1.1.1:8000')
        usable = ProxyLease(address='http://2.2.2.2:8000')
        ctx.config.proxy_ip_pool = [expiring, usable]

        def has_ttl(lease: ProxyLease | None, *, required_ttl_seconds: int) -> bool:
            return bool(lease and lease.address == usable.address)
        with patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', side_effect=has_ttl):
            selected = session_policy._pop_available_proxy_lease_locked(ctx)
        assert selected == usable
        assert ctx.config.proxy_ip_pool == []

    def test_pop_available_proxy_lease_skips_proxy_already_used_by_other_session(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        duplicated = ProxyLease(address='http://1.1.1.1:8000')
        usable = ProxyLease(address='http://2.2.2.2:8000')
        ctx.config.proxy_ip_pool = [duplicated, usable]
        ctx.proxy_in_use_by_thread = {'Worker-9': ProxyLease(address='http://1.1.1.1:8000')}
        with patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', return_value=True):
            selected = session_policy._pop_available_proxy_lease_locked(ctx)
        assert selected == usable
        assert ctx.config.proxy_ip_pool == []

    def test_pop_available_proxy_lease_skips_proxy_in_cooldown(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        cooled = ProxyLease(address='http://1.1.1.1:8000')
        usable = ProxyLease(address='http://2.2.2.2:8000')
        ctx.config.proxy_ip_pool = [cooled, usable]
        ctx.mark_proxy_in_cooldown(cooled.address, 180.0)
        with patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', return_value=True):
            selected = session_policy._pop_available_proxy_lease_locked(ctx)
        assert selected == usable
        assert ctx.config.proxy_ip_pool == []

    def test_pop_available_proxy_lease_skips_successfully_used_proxy(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        used = ProxyLease(address='http://1.1.1.1:8000')
        usable = ProxyLease(address='http://2.2.2.2:8000')
        ctx.config.proxy_ip_pool = [used, usable]
        ctx.mark_successful_proxy_address(used.address)
        with patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', return_value=True):
            selected = session_policy._pop_available_proxy_lease_locked(ctx)
        assert selected == usable
        assert ctx.config.proxy_ip_pool == []

    def test_select_proxy_for_session_returns_none_when_random_proxy_disabled(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=False))
        with patch.object(session_policy, 'fetch_proxy_batch') as fetch_proxy_batch:
            assert session_policy._select_proxy_for_session(ctx, 'Worker-1') is None
        fetch_proxy_batch.assert_not_called()

    def test_select_proxy_for_session_marks_existing_pool_proxy_in_use(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True))
        ctx.config.proxy_ip_pool = [ProxyLease(address='http://1.1.1.1:8000', source='unit')]
        selected = session_policy._select_proxy_for_session(ctx, 'Worker-1')
        assert selected == 'http://1.1.1.1:8000'
        assert 'Worker-1' in ctx.proxy_in_use_by_thread
        assert ctx.proxy_in_use_by_thread['Worker-1'].address == selected

    def test_select_proxy_for_session_fetches_one_and_pools_extra_leases(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True, target_num=3))
        ctx.cur_num = 0
        ctx.proxy_waiting_threads = 2
        fetched = [ProxyLease(address='http://1.1.1.1:8000', source='api'), ProxyLease(address='http://2.2.2.2:8000', source='api')]
        with patch.object(session_policy, 'fetch_proxy_batch', return_value=fetched) as fetch_proxy_batch:
            selected = session_policy._select_proxy_for_session(ctx, 'Worker-1')
        assert selected == 'http://1.1.1.1:8000'
        assert [lease.address for lease in ctx.config.proxy_ip_pool] == ['http://2.2.2.2:8000']
        assert ctx.proxy_waiting_threads == 2
        fetch_proxy_batch.assert_called_once()

    def test_select_proxy_for_session_skips_fetched_proxy_already_used_by_other_session(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True, target_num=2))
        ctx.proxy_in_use_by_thread = {'Worker-2': ProxyLease(address='http://1.1.1.1:8000', source='api')}
        fetched = [ProxyLease(address='http://1.1.1.1:8000', source='api'), ProxyLease(address='http://2.2.2.2:8000', source='api')]
        with patch.object(session_policy, 'fetch_proxy_batch', return_value=fetched), patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', return_value=True):
            selected = session_policy._select_proxy_for_session(ctx, 'Worker-1')
        assert selected == 'http://2.2.2.2:8000'
        assert ctx.proxy_in_use_by_thread['Worker-1'].address == 'http://2.2.2.2:8000'

    def test_select_proxy_for_session_skips_fetched_proxy_in_cooldown(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True, target_num=2))
        ctx.mark_proxy_in_cooldown('http://1.1.1.1:8000', 180.0)
        fetched = [ProxyLease(address='http://1.1.1.1:8000', source='api'), ProxyLease(address='http://2.2.2.2:8000', source='api')]
        with patch.object(session_policy, 'fetch_proxy_batch', return_value=fetched), patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', return_value=True):
            selected = session_policy._select_proxy_for_session(ctx, 'Worker-1')
        assert selected == 'http://2.2.2.2:8000'
        assert ctx.proxy_in_use_by_thread['Worker-1'].address == 'http://2.2.2.2:8000'

    def test_select_proxy_for_session_skips_fetched_proxy_used_by_previous_success(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True, target_num=2))
        ctx.mark_successful_proxy_address('http://1.1.1.1:8000')
        fetched = [ProxyLease(address='http://1.1.1.1:8000', source='api'), ProxyLease(address='http://2.2.2.2:8000', source='api')]
        with patch.object(session_policy, 'fetch_proxy_batch', return_value=fetched), patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', return_value=True):
            selected = session_policy._select_proxy_for_session(ctx, 'Worker-1')
        assert selected == 'http://2.2.2.2:8000'
        assert ctx.proxy_in_use_by_thread['Worker-1'].address == 'http://2.2.2.2:8000'

    def test_select_proxy_for_session_waits_for_new_proxy_when_runtime_requests_blocking_mode(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True, target_num=1))
        with patch.object(session_policy, 'fetch_proxy_batch', side_effect=[[], [ProxyLease(address='http://9.9.9.9:8000', source='api')]]), patch.object(session_policy, '_wait_for_next_proxy_cycle', return_value=False):
            selected = session_policy._select_proxy_for_session(ctx, 'Worker-1', stop_signal=ctx.stop_event, wait=True)
        assert selected == 'http://9.9.9.9:8000'
        assert ctx.proxy_in_use_by_thread['Worker-1'].address == 'http://9.9.9.9:8000'

    def test_discard_unresponsive_proxy_removes_matching_proxy_from_pool(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        ctx.config.proxy_ip_pool = [ProxyLease(address='http://1.1.1.1:8000'), ProxyLease(address='http://2.2.2.2:8000')]
        session_policy._discard_unresponsive_proxy(ctx, ' http://1.1.1.1:8000 ')
        assert [lease.address for lease in ctx.config.proxy_ip_pool] == ['http://2.2.2.2:8000']

    def test_mark_proxy_temporarily_bad_adds_cooldown_and_discards_from_pool(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        ctx.config.proxy_ip_pool = [ProxyLease(address='http://1.1.1.1:8000')]
        session_policy._mark_proxy_temporarily_bad(ctx, 'http://1.1.1.1:8000', cooldown_seconds=180.0)
        assert ctx.is_proxy_in_cooldown('http://1.1.1.1:8000')
        assert ctx.config.proxy_ip_pool == []

    def test_expired_proxy_cooldown_allows_proxy_back_into_pool(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        lease = ProxyLease(address='http://1.1.1.1:8000')
        ctx.config.proxy_ip_pool = [lease]
        ctx.proxy_cooldown_until_by_address[lease.address] = time.time() - 1.0
        with patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', return_value=True):
            selected = session_policy._pop_available_proxy_lease_locked(ctx)
        assert selected == lease
        assert not ctx.is_proxy_in_cooldown(lease.address)

    def test_select_user_agent_returns_none_when_disabled(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_user_agent_enabled=False))
        with patch.object(session_policy, '_select_user_agent_from_ratios') as select_user_agent:
            assert session_policy._select_user_agent_for_session(ctx) == (None, None)
        select_user_agent.assert_not_called()
