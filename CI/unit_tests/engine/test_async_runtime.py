from __future__ import annotations

from software.core.task import ExecutionState
from software.network.browser.pool_config import (
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


def test_execution_state_formats_slot_display_name() -> None:
    state = ExecutionState()
    state.ensure_worker_threads(2, prefix="Slot")
    rows = state.snapshot_thread_progress()
    assert rows[0]["thread_name"] == "Slot-1"
    assert rows[0]["thread_display_name"] == "会话 1"
    assert rows[1]["thread_name"] == "Slot-2"
    assert rows[1]["thread_display_name"] == "会话 2"
