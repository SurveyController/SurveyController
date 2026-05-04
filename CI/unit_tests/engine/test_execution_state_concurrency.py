from __future__ import annotations

import threading
import time
import unittest

from software.core.task import ExecutionState, ProxyLease


class ExecutionStateConcurrencyTests(unittest.TestCase):
    def test_wait_for_runtime_change_returns_false_after_notify(self) -> None:
        state = ExecutionState()
        result: dict[str, bool] = {}

        def _waiter() -> None:
            result["value"] = state.wait_for_runtime_change(timeout=1.0)

        worker = threading.Thread(target=_waiter, name="RuntimeWaiter")
        worker.start()
        time.sleep(0.05)
        state.notify_runtime_change()
        worker.join(timeout=1.0)

        self.assertFalse(worker.is_alive())
        self.assertFalse(result["value"])

    def test_wait_for_runtime_change_returns_true_when_stop_signal_is_set_during_wait(self) -> None:
        state = ExecutionState()
        stop_signal = threading.Event()
        result: dict[str, bool] = {}

        def _waiter() -> None:
            result["value"] = state.wait_for_runtime_change(stop_signal=stop_signal, timeout=1.0)

        worker = threading.Thread(target=_waiter, name="RuntimeStopWaiter")
        worker.start()
        time.sleep(0.05)
        stop_signal.set()
        state.notify_runtime_change()
        worker.join(timeout=1.0)

        self.assertFalse(worker.is_alive())
        self.assertTrue(result["value"])

    def test_register_and_unregister_proxy_waiter_stays_consistent_under_concurrency(self) -> None:
        state = ExecutionState()
        barrier = threading.Barrier(8)

        def _worker() -> None:
            barrier.wait()
            for _ in range(50):
                state.register_proxy_waiter()
                time.sleep(0.001)
                state.unregister_proxy_waiter()

        threads = [threading.Thread(target=_worker, name=f"ProxyWaiter-{idx}") for idx in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2.0)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(state.proxy_waiting_threads, 0)

    def test_get_browser_semaphore_reuses_same_instance_under_concurrent_calls(self) -> None:
        state = ExecutionState()
        barrier = threading.Barrier(6)
        semaphore_ids: list[int] = []
        ids_lock = threading.Lock()

        def _worker() -> None:
            barrier.wait()
            semaphore = state.get_browser_semaphore(2)
            with ids_lock:
                semaphore_ids.append(id(semaphore))

        threads = [threading.Thread(target=_worker, name=f"SemaphoreCaller-{idx}") for idx in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2.0)

        self.assertEqual(len(set(semaphore_ids)), 1)
        self.assertIs(state.get_browser_semaphore(2), state.get_browser_semaphore(2))
        self.assertIsNot(state.get_browser_semaphore(2), state.get_browser_semaphore(3))

    def test_reserve_joint_sample_returns_unique_values_under_concurrency(self) -> None:
        state = ExecutionState()
        barrier = threading.Barrier(5)
        results: dict[str, int | None] = {}
        result_lock = threading.Lock()

        def _worker(name: str) -> None:
            barrier.wait()
            value = state.reserve_joint_sample(3, thread_name=name)
            with result_lock:
                results[name] = value

        threads = [threading.Thread(target=_worker, args=(f"Worker-{idx}",), name=f"Worker-{idx}") for idx in range(1, 6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2.0)

        acquired = [value for value in results.values() if value is not None]
        self.assertEqual(len(acquired), 3)
        self.assertEqual(len(set(acquired)), 3)
        self.assertEqual(sum(value is None for value in results.values()), 2)

    def test_release_proxy_in_use_notifies_waiting_threads(self) -> None:
        state = ExecutionState()
        state.mark_proxy_in_use("Worker-1", ProxyLease(address="http://1.1.1.1:8000"))
        result: dict[str, bool] = {}

        def _waiter() -> None:
            result["value"] = state.wait_for_runtime_change(timeout=1.0)

        worker = threading.Thread(target=_waiter, name="ProxyReleaseWaiter")
        worker.start()
        time.sleep(0.05)
        released = state.release_proxy_in_use("Worker-1")
        worker.join(timeout=1.0)

        self.assertIsNotNone(released)
        self.assertFalse(worker.is_alive())
        self.assertFalse(result["value"])
        self.assertEqual(state.snapshot_active_proxy_addresses(), set())

    def test_mark_successful_proxy_address_blocks_future_reuse(self) -> None:
        state = ExecutionState()
        changed = state.mark_successful_proxy_address("http://1.1.1.1:8000")

        self.assertTrue(changed)
        self.assertTrue(state.is_successful_proxy_address("http://1.1.1.1:8000"))
        self.assertEqual(state.snapshot_successful_proxy_addresses(), {"http://1.1.1.1:8000"})

    def test_snapshot_blocked_proxy_addresses_merges_active_and_successful_sets(self) -> None:
        state = ExecutionState()
        state.mark_proxy_in_use("Worker-1", ProxyLease(address="http://1.1.1.1:8000"))
        state.mark_successful_proxy_address("http://2.2.2.2:8000")

        blocked = state.snapshot_blocked_proxy_addresses()

        self.assertEqual(blocked, {"http://1.1.1.1:8000", "http://2.2.2.2:8000"})

    def test_mark_terminal_stop_preserves_first_value_until_explicit_overwrite(self) -> None:
        state = ExecutionState()
        state.mark_terminal_stop("first", failure_reason="a", message="first-message")

        barrier = threading.Barrier(4)

        def _worker(idx: int) -> None:
            barrier.wait()
            state.mark_terminal_stop(f"other-{idx}", failure_reason=f"b-{idx}", message=f"message-{idx}")

        threads = [threading.Thread(target=_worker, args=(idx,), name=f"Stop-{idx}") for idx in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=1.0)

        self.assertEqual(state.get_terminal_stop_snapshot(), ("first", "a", "first-message"))

        state.mark_terminal_stop("forced", failure_reason="c", message="forced-message", overwrite=True)
        self.assertEqual(state.get_terminal_stop_snapshot(), ("forced", "c", "forced-message"))

    def test_snapshot_thread_progress_clamps_step_and_sorts_unknown_threads_last(self) -> None:
        state = ExecutionState()
        state.update_thread_step("Worker-2", 99, 3, status_text="running", running=True)
        state.update_thread_status("Worker-?", "waiting", running=False)
        state.update_thread_step("Worker-1", 1, 4, status_text="step", running=True)

        rows = state.snapshot_thread_progress()

        self.assertEqual([row["thread_name"] for row in rows], ["Worker-1", "Worker-2", "Worker-?"])
        self.assertEqual(rows[1]["step_current"], 3)
        self.assertEqual(rows[1]["step_total"], 3)
        self.assertEqual(rows[1]["step_percent"], 100)


if __name__ == "__main__":
    unittest.main()
