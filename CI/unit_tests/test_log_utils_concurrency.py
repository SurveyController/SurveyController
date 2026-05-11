from __future__ import annotations
import logging
import os
import threading
import time
import tempfile
from unittest.mock import patch
from software.logging.log_utils import AsyncFileHandler, LogBufferHandler

class LogBufferHandlerConcurrencyTests:

    def teardown_method(self, _method) -> None:
        handler = getattr(self, '_handler', None)
        if handler is not None:
            handler.stop()

    def _create_handler(self, capacity: int=10) -> LogBufferHandler:
        handler = LogBufferHandler(capacity=capacity)
        self._handler = handler
        return handler

    def _wait_until(self, predicate, timeout: float=1.5) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return predicate()

    def test_emit_processes_records_asynchronously(self) -> None:
        handler = self._create_handler()
        logger = logging.getLogger('unit.logbuffer.async')
        handler.emit(logging.LogRecord(logger.name, logging.INFO, __file__, 10, '普通日志', (), None))
        assert self._wait_until(lambda: len(handler.get_records()) == 1)
        assert '普通日志' in handler.get_records()[0].text
        assert handler.get_records()[0].category == 'INFO'

    def test_emit_keeps_only_latest_records_when_capacity_is_reached(self) -> None:
        handler = self._create_handler(capacity=2)
        logger = logging.getLogger('unit.logbuffer.capacity')
        for message in ('第一条', '第二条', '第三条'):
            handler.emit(logging.LogRecord(logger.name, logging.INFO, __file__, 10, message, (), None))
        assert self._wait_until(lambda: len(handler.get_records()) == 2)
        texts = [entry.text for entry in handler.get_records()]
        assert not any(('第一条' in text for text in texts))
        assert any(('第二条' in text for text in texts))
        assert any(('第三条' in text for text in texts))

    def test_emit_filters_sensitive_and_noise_messages(self) -> None:
        handler = self._create_handler()
        logger = logging.getLogger('unit.logbuffer.filter')
        handler.emit(logging.LogRecord(logger.name, logging.INFO, __file__, 10, 'Authorization: Bearer abc', (), None))
        handler.emit(logging.LogRecord(logger.name, logging.INFO, __file__, 10, 'QFluentWidgets Pro is now released', (), None))
        time.sleep(0.15)
        assert handler.get_records() == []

    def test_worker_survives_process_record_failure_and_handles_next_log(self) -> None:
        handler = self._create_handler()
        logger = logging.getLogger('unit.logbuffer.failure')
        original_format = handler.format
        with patch('software.logging.log_utils._safe_internal_log') as mock_safe_log:
            with patch.object(handler, 'format', side_effect=[RuntimeError('boom'), original_format(logging.LogRecord(logger.name, logging.INFO, __file__, 10, '恢复后的日志', (), None))]):
                handler.emit(logging.LogRecord(logger.name, logging.INFO, __file__, 10, '坏日志', (), None))
                handler.emit(logging.LogRecord(logger.name, logging.INFO, __file__, 10, '好日志', (), None))
                assert self._wait_until(lambda: any(('恢复后的日志' in entry.text for entry in handler.get_records())))
        assert handler._worker_thread is not None and handler._worker_thread.is_alive()
        mock_safe_log.assert_called()

    def test_emit_is_safe_under_multiple_threads(self) -> None:
        handler = self._create_handler(capacity=20)
        barrier = threading.Barrier(5)

        def _worker(idx: int) -> None:
            barrier.wait()
            handler.emit(logging.LogRecord('unit.logbuffer.concurrent', logging.INFO, __file__, 10, f'日志-{idx}', (), None))
        threads = [threading.Thread(target=_worker, args=(idx,), name=f'Logger-{idx}') for idx in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=1.0)
        assert self._wait_until(lambda: len(handler.get_records()) == 5)
        texts = [entry.text for entry in handler.get_records()]
        for idx in range(5):
            assert any((f'日志-{idx}' in text for text in texts))

    def test_log_buffer_notifies_listener_after_batch_processed(self) -> None:
        handler = self._create_handler()
        versions: list[int] = []
        listener_id = handler.add_listener(lambda version: versions.append(version))
        try:
            handler.emit(logging.LogRecord('unit.logbuffer.listener', logging.INFO, __file__, 10, '监听日志', (), None))
            assert self._wait_until(lambda: bool(versions))
            assert versions[-1] == handler.get_version()
        finally:
            handler.remove_listener(listener_id)

    def test_async_file_handler_writes_without_calling_file_handler_emit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, 'session.log')
            handler = AsyncFileHandler(path)
            handler.setFormatter(logging.Formatter('%(message)s'))
            try:
                record = logging.LogRecord('unit.logfile.async', logging.INFO, __file__, 10, '异步落盘', (), None)
                handler.emit(record)
                handler.flush()
                assert self._wait_until(lambda: os.path.exists(path) and '异步落盘' in open(path, 'r', encoding='utf-8').read())
            finally:
                handler.close()
