from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from credamo.provider import runtime


class CredamoRuntimeTests(unittest.TestCase):
    def test_click_submit_waits_until_dynamic_button_appears(self) -> None:
        attempts = iter([False, False, True])

        with patch("credamo.provider.runtime._click_submit_once", side_effect=lambda _page: next(attempts)), \
             patch("credamo.provider.runtime.time.sleep") as sleep_mock:
            clicked = runtime._click_submit(object(), timeout_ms=2000)

        self.assertTrue(clicked)
        self.assertEqual(sleep_mock.call_count, 2)

    def test_click_submit_stops_waiting_when_abort_requested(self) -> None:
        stop_signal = threading.Event()

        def abort_after_first_wait(_seconds: float | None = None) -> bool:
            stop_signal.set()
            return True

        with patch("credamo.provider.runtime._click_submit_once", return_value=False):
            setattr(stop_signal, "wait", abort_after_first_wait)
            clicked = runtime._click_submit(object(), stop_signal, timeout_ms=2000)

        self.assertFalse(clicked)


if __name__ == "__main__":
    unittest.main()
