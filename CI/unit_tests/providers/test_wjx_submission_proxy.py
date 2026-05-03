from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from software.core.task import ExecutionConfig, ExecutionState, ProxyLease
from wjx.provider import submission_proxy


class WjxSubmissionProxyTests(unittest.TestCase):
    def test_acquire_replacement_submit_proxy_skips_active_proxy_and_keeps_browser_proxy_reserved(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True))
        ctx.config.proxy_ip_pool = [
            ProxyLease(address="http://2.2.2.2:8000", source="pool"),
            ProxyLease(address="http://3.3.3.3:8000", source="pool"),
        ]
        ctx.proxy_in_use_by_thread = {
            "Worker-1": ProxyLease(address="http://1.1.1.1:8000", source="session"),
            "Worker-2": ProxyLease(address="http://2.2.2.2:8000", source="session"),
        }
        driver = SimpleNamespace(
            _submit_proxy_address="http://1.1.1.1:8000",
            _thread_name="Worker-1",
        )

        selected = submission_proxy._acquire_replacement_submit_proxy(
            driver,
            ctx,
            stop_signal=threading.Event(),
        )

        self.assertEqual(selected, "http://3.3.3.3:8000")
        self.assertEqual(getattr(driver, "_submit_proxy_address", None), "http://3.3.3.3:8000")
        self.assertEqual(ctx.proxy_in_use_by_thread["Worker-1"].address, "http://1.1.1.1:8000")
        self.assertEqual(ctx.submit_proxy_in_use_by_thread["Worker-1"].address, "http://3.3.3.3:8000")

    def test_acquire_replacement_submit_proxy_uses_locked_snapshot_for_fetched_candidates(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True))
        ctx.proxy_in_use_by_thread = {
            "Worker-1": ProxyLease(address="http://1.1.1.1:8000", source="session"),
            "Worker-2": ProxyLease(address="http://2.2.2.2:8000", source="session"),
        }
        driver = SimpleNamespace(
            _submit_proxy_address="http://1.1.1.1:8000",
            _thread_name="Worker-1",
        )

        original_snapshot = ctx.snapshot_active_proxy_addresses
        snapshot_calls: list[str] = []

        def snapshot_active_proxy_addresses(*, exclude_thread_name: str = "") -> set[str]:
            snapshot_calls.append(exclude_thread_name)
            return original_snapshot(exclude_thread_name=exclude_thread_name)

        ctx.snapshot_active_proxy_addresses = snapshot_active_proxy_addresses  # type: ignore[method-assign]

        with patch.object(
            submission_proxy,
            "fetch_proxy_batch",
            return_value=[
                ProxyLease(address="http://2.2.2.2:8000", source="fetch"),
                ProxyLease(address="http://3.3.3.3:8000", source="fetch"),
            ],
        ):
            selected = submission_proxy._acquire_replacement_submit_proxy(
                driver,
                ctx,
                stop_signal=threading.Event(),
            )

        self.assertEqual(selected, "http://3.3.3.3:8000")
        self.assertEqual(snapshot_calls, ["Worker-1"])
        self.assertEqual(ctx.submit_proxy_in_use_by_thread["Worker-1"].address, "http://3.3.3.3:8000")

    def test_acquire_replacement_submit_proxy_returns_none_when_runtime_fetches_no_proxy(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True))
        ctx.proxy_in_use_by_thread = {
            "Worker-1": ProxyLease(address="http://1.1.1.1:8000", source="session"),
        }
        driver = SimpleNamespace(
            _submit_proxy_address="http://1.1.1.1:8000",
            _thread_name="Worker-1",
        )
        stop_signal = threading.Event()

        with (
            patch.object(submission_proxy, "fetch_proxy_batch", return_value=[]),
            patch.object(submission_proxy, "_SUBMIT_PROXY_WAIT_POLL_SECONDS", 0.0),
        ):
            selected = submission_proxy._acquire_replacement_submit_proxy(
                driver,
                ctx,
                stop_signal=stop_signal,
            )

        self.assertIsNone(selected)
        self.assertNotIn("Worker-1", ctx.submit_proxy_in_use_by_thread)

    def test_acquire_replacement_submit_proxy_waits_only_when_explicitly_requested(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True))
        ctx.proxy_in_use_by_thread = {
            "Worker-1": ProxyLease(address="http://1.1.1.1:8000", source="session"),
        }
        driver = SimpleNamespace(
            _submit_proxy_address="http://1.1.1.1:8000",
            _thread_name="Worker-1",
        )
        stop_signal = threading.Event()

        with (
            patch.object(submission_proxy, "fetch_proxy_batch", side_effect=[[], [ProxyLease(address="http://4.4.4.4:8000", source="fetch")]]),
            patch.object(submission_proxy, "_SUBMIT_PROXY_WAIT_POLL_SECONDS", 0.0),
        ):
            selected = submission_proxy._acquire_replacement_submit_proxy(
                driver,
                ctx,
                stop_signal=stop_signal,
                wait_for_replacement=True,
            )

        self.assertEqual(selected, "http://4.4.4.4:8000")
        self.assertEqual(ctx.submit_proxy_in_use_by_thread["Worker-1"].address, "http://4.4.4.4:8000")


if __name__ == "__main__":
    unittest.main()
