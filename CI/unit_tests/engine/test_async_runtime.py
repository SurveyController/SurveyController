from __future__ import annotations

import unittest

from software.core.task import ExecutionState
from software.network.browser.owner_pool import BrowserOwnerPool, BrowserPoolConfig


class AsyncRuntimeTests(unittest.TestCase):
    def test_browser_pool_config_computes_owner_count_by_four_slots(self) -> None:
        config = BrowserPoolConfig.from_concurrency(8, max_contexts_per_browser=4)
        self.assertEqual(config.logical_concurrency, 8)
        self.assertEqual(config.max_contexts_per_browser, 4)
        self.assertEqual(config.owner_count, 2)

    def test_browser_owner_pool_maps_four_slots_per_owner(self) -> None:
        pool = BrowserOwnerPool(
            config=BrowserPoolConfig.from_concurrency(8, max_contexts_per_browser=4),
            headless=True,
        )
        try:
            self.assertEqual(pool.owner_for_slot(0).owner_id, 1)
            self.assertEqual(pool.owner_for_slot(3).owner_id, 1)
            self.assertEqual(pool.owner_for_slot(4).owner_id, 2)
            self.assertEqual(pool.owner_for_slot(7).owner_id, 2)
        finally:
            pool.shutdown()

    def test_execution_state_formats_slot_display_name(self) -> None:
        state = ExecutionState()
        state.ensure_worker_threads(2, prefix="Slot")
        rows = state.snapshot_thread_progress()
        self.assertEqual(rows[0]["thread_name"], "Slot-1")
        self.assertEqual(rows[0]["thread_display_name"], "会话 1")
        self.assertEqual(rows[1]["thread_name"], "Slot-2")
        self.assertEqual(rows[1]["thread_display_name"], "会话 2")


if __name__ == "__main__":
    unittest.main()
