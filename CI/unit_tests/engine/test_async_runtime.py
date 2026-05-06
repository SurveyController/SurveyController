from __future__ import annotations

import threading
import time

from software.core.task import ExecutionState
from software.network.browser.owner_pool import (
    BrowserOwnerPool,
    BrowserPoolConfig,
    DEFAULT_HEADED_CONTEXTS_PER_BROWSER,
    DEFAULT_HEADLESS_CONTEXTS_PER_BROWSER,
)


def test_browser_pool_config_uses_headless_capacity_defaults() -> None:
    config = BrowserPoolConfig.from_concurrency(8, headless=True)
    assert config.logical_concurrency == 8
    assert config.contexts_per_owner == DEFAULT_HEADLESS_CONTEXTS_PER_BROWSER
    assert config.owner_count == 1

    config = BrowserPoolConfig.from_concurrency(9, headless=True)
    assert config.owner_count == 2


def test_browser_pool_config_uses_headed_capacity_defaults() -> None:
    config = BrowserPoolConfig.from_concurrency(4, headless=False)
    assert config.contexts_per_owner == DEFAULT_HEADED_CONTEXTS_PER_BROWSER
    assert config.owner_count == 1

    config = BrowserPoolConfig.from_concurrency(5, headless=False)
    assert config.owner_count == 2


def test_browser_owner_pool_balances_dynamic_leases_by_load() -> None:
    pool = BrowserOwnerPool(
        config=BrowserPoolConfig.from_concurrency(9, headless=True),
        headless=True,
    )
    try:
        lease1 = pool.acquire_owner_lease(wait=False)
        lease2 = pool.acquire_owner_lease(wait=False)
        lease3 = pool.acquire_owner_lease(wait=False)
        assert lease1 is not None
        assert lease2 is not None
        assert lease3 is not None

        assert lease1.owner.owner_id == 1
        assert lease2.owner.owner_id == 2
        assert lease3.owner.owner_id == 1
    finally:
        for lease in (locals().get("lease1"), locals().get("lease2"), locals().get("lease3")):
            if lease is not None:
                lease.release()
        pool.shutdown()


def test_browser_owner_pool_waits_until_capacity_returns() -> None:
    pool = BrowserOwnerPool(
        config=BrowserPoolConfig.from_concurrency(
            1,
            headless=False,
            contexts_per_owner=1,
        ),
        headless=False,
    )
    stop_signal = threading.Event()
    first_lease = pool.acquire_owner_lease(wait=False)
    assert first_lease is not None
    assert first_lease is not None

    result: dict[str, object] = {}

    def _waiter() -> None:
        result["lease"] = pool.acquire_owner_lease(stop_signal=stop_signal, wait=True)

    worker = threading.Thread(target=_waiter)
    worker.start()
    time.sleep(0.1)
    assert "lease" not in result

    first_lease.release()
    worker.join(timeout=1.0)
    assert not worker.is_alive()
    waited_lease = result.get("lease")
    assert waited_lease is not None
    assert waited_lease is not None
    waited_lease.release()
    pool.shutdown()


def test_execution_state_formats_slot_display_name() -> None:
    state = ExecutionState()
    state.ensure_worker_threads(2, prefix="Slot")
    rows = state.snapshot_thread_progress()
    assert rows[0]["thread_name"] == "Slot-1"
    assert rows[0]["thread_display_name"] == "会话 1"
    assert rows[1]["thread_name"] == "Slot-2"
    assert rows[1]["thread_display_name"] == "会话 2"
