from __future__ import annotations

import logging
import threading
import time
import unittest
from unittest.mock import patch

from software.logging.log_utils import LogBufferHandler


class LogBufferHandlerConcurrencyTests(unittest.TestCase):
    def tearDown(self) -> None:
        handler = getattr(self, "_handler", None)
        if handler is not None:
            handler.stop()

    def _create_handler(self, capacity: int = 10) -> LogBufferHandler:
        handler = LogBufferHandler(capacity=capacity)
        self._handler = handler
        return handler

    def _wait_until(self, predicate, timeout: float = 1.5) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return predicate()

    def test_emit_processes_records_asynchronously(self) -> None:
        handler = self._create_handler()
        logger = logging.getLogger("unit.logbuffer.async")

        handler.emit(logging.LogRecord(logger.name, logging.INFO, __file__, 10, "普通日志", (), None))

        self.assertTrue(self._wait_until(lambda: len(handler.get_records()) == 1))
        self.assertIn("普通日志", handler.get_records()[0].text)
        self.assertEqual(handler.get_records()[0].category, "INFO")

    def test_emit_keeps_only_latest_records_when_capacity_is_reached(self) -> None:
        handler = self._create_handler(capacity=2)
        logger = logging.getLogger("unit.logbuffer.capacity")

        for message in ("第一条", "第二条", "第三条"):
            handler.emit(logging.LogRecord(logger.name, logging.INFO, __file__, 10, message, (), None))

        self.assertTrue(self._wait_until(lambda: len(handler.get_records()) == 2))
        texts = [entry.text for entry in handler.get_records()]
        self.assertFalse(any("第一条" in text for text in texts))
        self.assertTrue(any("第二条" in text for text in texts))
        self.assertTrue(any("第三条" in text for text in texts))

    def test_emit_filters_sensitive_and_noise_messages(self) -> None:
        handler = self._create_handler()
        logger = logging.getLogger("unit.logbuffer.filter")

        handler.emit(logging.LogRecord(logger.name, logging.INFO, __file__, 10, "Authorization: Bearer abc", (), None))
        handler.emit(
            logging.LogRecord(
                logger.name,
                logging.INFO,
                __file__,
                10,
                "QFluentWidgets Pro is now released",
                (),
                None,
            )
        )

        time.sleep(0.15)
        self.assertEqual(handler.get_records(), [])

    def test_worker_survives_process_record_failure_and_handles_next_log(self) -> None:
        handler = self._create_handler()
        logger = logging.getLogger("unit.logbuffer.failure")
        original_format = handler.format

        with patch("software.logging.log_utils._safe_internal_log") as mock_safe_log:
            with patch.object(
                handler,
                "format",
                side_effect=[RuntimeError("boom"), original_format(logging.LogRecord(logger.name, logging.INFO, __file__, 10, "恢复后的日志", (), None))],
            ):
                handler.emit(logging.LogRecord(logger.name, logging.INFO, __file__, 10, "坏日志", (), None))
                handler.emit(logging.LogRecord(logger.name, logging.INFO, __file__, 10, "好日志", (), None))
                self.assertTrue(self._wait_until(lambda: any("恢复后的日志" in entry.text for entry in handler.get_records())))

        self.assertTrue(handler._worker_thread is not None and handler._worker_thread.is_alive())
        mock_safe_log.assert_called()

    def test_emit_is_safe_under_multiple_threads(self) -> None:
        handler = self._create_handler(capacity=20)
        barrier = threading.Barrier(5)

        def _worker(idx: int) -> None:
            barrier.wait()
            handler.emit(logging.LogRecord("unit.logbuffer.concurrent", logging.INFO, __file__, 10, f"日志-{idx}", (), None))

        threads = [threading.Thread(target=_worker, args=(idx,), name=f"Logger-{idx}") for idx in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=1.0)

        self.assertTrue(self._wait_until(lambda: len(handler.get_records()) == 5))
        texts = [entry.text for entry in handler.get_records()]
        for idx in range(5):
            self.assertTrue(any(f"日志-{idx}" in text for text in texts))


if __name__ == "__main__":
    unittest.main()
