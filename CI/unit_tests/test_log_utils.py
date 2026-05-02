from __future__ import annotations

import logging
import os
import tempfile
import unittest
from unittest.mock import patch

import software.logging.log_utils as log_utils
from software.logging.log_utils import (
    LogBufferEntry,
    export_full_log_to_file,
    log_deduped_message,
    reset_deduped_log_message,
)


class LogUtilsTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_deduped_log_message("test_random_ip_sync_failure")
        handler = getattr(log_utils, "_SESSION_LOG_HANDLER", None)
        if handler is not None:
            try:
                handler.close()
            except Exception:
                pass
        log_utils._SESSION_LOG_HANDLER = None
        log_utils._SESSION_LOG_PATH = ""

    def test_log_deduped_message_only_logs_same_message_once(self) -> None:
        with patch("software.logging.log_utils.logging.log") as mock_log:
            first = log_deduped_message("test_random_ip_sync_failure", "同步随机IP额度失败：网络超时", level=logging.INFO)
            second = log_deduped_message("test_random_ip_sync_failure", "同步随机IP额度失败：网络超时", level=logging.INFO)

        self.assertTrue(first)
        self.assertFalse(second)
        mock_log.assert_called_once_with(logging.INFO, "同步随机IP额度失败：网络超时")

    def test_reset_deduped_log_message_allows_same_message_to_log_again(self) -> None:
        with patch("software.logging.log_utils.logging.log") as mock_log:
            first = log_deduped_message("test_random_ip_sync_failure", "同步随机IP额度失败：网络超时", level=logging.INFO)
            reset_deduped_log_message("test_random_ip_sync_failure")
            second = log_deduped_message("test_random_ip_sync_failure", "同步随机IP额度失败：网络超时", level=logging.INFO)

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(mock_log.call_count, 2)

    def test_export_full_log_to_file_prefers_session_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "session.log")
            target_path = os.path.join(temp_dir, "exported.log")
            handler = logging.FileHandler(source_path, mode="a", encoding="utf-8")
            try:
                handler.stream.write("第一行\n第二行\n")
                handler.flush()
                log_utils._SESSION_LOG_HANDLER = handler
                log_utils._SESSION_LOG_PATH = source_path

                exported_path = export_full_log_to_file(
                    temp_dir,
                    target_path,
                    fallback_records=[LogBufferEntry(text="缓冲区内容", category="INFO")],
                )

                self.assertEqual(exported_path, target_path)
                with open(target_path, "r", encoding="utf-8") as file:
                    self.assertEqual(file.read(), "第一行\n第二行\n")
            finally:
                handler.close()
                log_utils._SESSION_LOG_HANDLER = None
                log_utils._SESSION_LOG_PATH = ""

    def test_export_full_log_to_file_falls_back_to_buffer_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target_path = os.path.join(temp_dir, "buffer.log")
            exported_path = export_full_log_to_file(
                temp_dir,
                target_path,
                fallback_records=[
                    LogBufferEntry(text="缓冲一", category="INFO"),
                    LogBufferEntry(text="缓冲二", category="WARNING"),
                ],
            )

            self.assertEqual(exported_path, target_path)
            with open(target_path, "r", encoding="utf-8") as file:
                self.assertEqual(file.read(), "缓冲一\n缓冲二")
