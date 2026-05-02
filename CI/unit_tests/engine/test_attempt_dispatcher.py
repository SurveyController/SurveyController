from __future__ import annotations

import threading
import time
import unittest

from software.core.engine.attempt_dispatcher import AttemptDispatcher
from software.core.task import ExecutionConfig, ExecutionState


class AttemptDispatcherTests(unittest.TestCase):
    def test_acquire_stops_after_target_reached(self) -> None:
        config = ExecutionConfig(num_threads=2, target_num=2)
        state = ExecutionState(config=config, cur_num=2)
        dispatcher = AttemptDispatcher(config, state, threading.Event())

        self.assertFalse(dispatcher.acquire())

    def test_release_with_delay_wakes_waiting_worker_after_token_returns(self) -> None:
        config = ExecutionConfig(num_threads=1)
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        dispatcher = AttemptDispatcher(config, state, stop_signal)

        self.assertTrue(dispatcher.acquire())

        result: dict[str, float] = {}
        started_at = time.monotonic()

        def _waiter() -> None:
            acquired = dispatcher.acquire()
            result["acquired"] = time.monotonic()
            result["ok"] = 1.0 if acquired else 0.0

        worker = threading.Thread(target=_waiter, daemon=True)
        worker.start()
        time.sleep(0.05)
        self.assertNotIn("ok", result)

        dispatcher.release(requeue=True, delay_seconds=0.15)

        worker.join(timeout=1.0)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result.get("ok"), 1.0)
        self.assertGreaterEqual(float(result["acquired"]) - started_at, 0.12)

    def test_release_without_requeue_keeps_waiter_blocked_until_close(self) -> None:
        config = ExecutionConfig(num_threads=1)
        state = ExecutionState(config=config)
        dispatcher = AttemptDispatcher(config, state, threading.Event())

        self.assertTrue(dispatcher.acquire())

        completed = threading.Event()

        def _waiter() -> None:
            dispatcher.acquire()
            completed.set()

        worker = threading.Thread(target=_waiter, daemon=True)
        worker.start()
        time.sleep(0.05)
        dispatcher.release(requeue=False)
        time.sleep(0.05)
        self.assertFalse(completed.is_set())

        dispatcher.close()
        worker.join(timeout=1.0)
        self.assertFalse(worker.is_alive())
        self.assertTrue(completed.is_set())

    def test_acquire_polling_wait_observes_stop_signal_without_close(self) -> None:
        config = ExecutionConfig(num_threads=1)
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        dispatcher = AttemptDispatcher(config, state, stop_signal)

        self.assertTrue(dispatcher.acquire())
        dispatcher.release(requeue=True, delay_seconds=5.0)

        result: dict[str, bool] = {}

        def _waiter() -> None:
            result["acquired"] = dispatcher.acquire()

        worker = threading.Thread(target=_waiter, daemon=True)
        started_at = time.monotonic()
        worker.start()
        time.sleep(0.05)
        stop_signal.set()

        worker.join(timeout=1.0)
        self.assertFalse(worker.is_alive())
        self.assertFalse(result.get("acquired", True))
        self.assertLess(time.monotonic() - started_at, 1.0)


if __name__ == "__main__":
    unittest.main()
