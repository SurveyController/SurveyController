from __future__ import annotations

import unittest
from unittest.mock import patch

from software.app.browser_probe import _parse_probe_stdout, run_browser_probe_subprocess
from software.core.questions.validation import validate_question_config
from software.io.config import RuntimeConfig
from software.core.questions.schema import QuestionEntry
from software.ui.controller.run_controller_parts.runtime_init_gate import (
    RunControllerInitializationMixin,
    _extract_startup_service_warnings,
    _parse_status_page_monitor_names,
)


class _DummyInitGate(RunControllerInitializationMixin):
    pass


class _FakeProbeProcess:
    pid = 9527

    def __init__(self, stdout: bytes, stderr: bytes) -> None:
        self._stdout = stdout
        self._stderr = stderr

    def poll(self) -> int:
        return 0

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:
        return None


class RuntimeInitGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mixin = _DummyInitGate()

    def test_gate_only_enabled_for_headless_multi_thread(self) -> None:
        config = RuntimeConfig()
        config.headless_mode = True
        config.threads = 2
        self.assertTrue(self.mixin._should_use_initialization_gate(config))

        config.threads = 1
        self.assertFalse(self.mixin._should_use_initialization_gate(config))

        config.headless_mode = False
        config.threads = 3
        self.assertFalse(self.mixin._should_use_initialization_gate(config))

    def test_initialization_plan_only_keeps_browser_quick_check(self) -> None:
        config = RuntimeConfig()
        config.headless_mode = True
        config.threads = 2

        self.assertEqual(
            self.mixin._build_initialization_plan(config),
            [{"key": "playwright", "label": "初始化浏览器环境（快速检查）"}],
        )

        config.threads = 1
        self.assertEqual(self.mixin._build_initialization_plan(config), [])

    def test_parse_status_page_monitor_names_reads_public_group_monitors(self) -> None:
        payload = {
            "publicGroupList": [
                {
                    "monitorList": [
                        {"id": 12, "name": "随机ip提取"},
                        {"id": 13, "name": "免费AI填空"},
                    ]
                }
            ]
        }
        self.assertEqual(
            _parse_status_page_monitor_names(payload),
            {12: "随机ip提取", 13: "免费AI填空"},
        )

    def test_extract_startup_service_warnings_only_flags_non_ok_status(self) -> None:
        payload = {
            "heartbeatList": {
                "12": [{"status": 0, "msg": "接口超时", "time": "2026-04-23 11:00:00"}],
                "13": [{"status": 1, "msg": "", "time": "2026-04-23 11:00:30"}],
            }
        }
        warnings = _extract_startup_service_warnings(
            payload,
            {12: "随机IP提取", 13: "免费AI填空"},
            {12: "随机ip提取", 13: "免费AI填空"},
        )
        self.assertEqual(
            warnings,
            ["随机ip提取 当前状态异常（接口超时；最近时间：2026-04-23 11:00:00）"],
        )

    def test_parse_probe_stdout_reads_last_json_line(self) -> None:
        result = _parse_probe_stdout(
            "noise line\n"
            "{\"ok\":true,\"browser\":\"edge\",\"error_kind\":\"\",\"message\":\"ok\",\"elapsed_ms\":321}\n"
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.ok)
        self.assertEqual(result.browser, "edge")
        self.assertEqual(result.elapsed_ms, 321)

    def test_parse_probe_stdout_returns_none_for_invalid_output(self) -> None:
        self.assertIsNone(_parse_probe_stdout("not json"))

    def test_run_browser_probe_subprocess_tolerates_invalid_utf8_bytes(self) -> None:
        fake_process = _FakeProbeProcess(
            b"probe noise:\x80\x81\n"
            b"{\"ok\":true,\"browser\":\"edge\",\"error_kind\":\"\",\"message\":\"ok\",\"elapsed_ms\":15}\n",
            b"\xff\xfe",
        )
        with patch("software.app.browser_probe.subprocess.Popen", return_value=fake_process):
            result = run_browser_probe_subprocess(
                headless=True,
                browser_preference=["edge"],
                timeout_seconds=1,
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.browser, "edge")
        self.assertEqual(result.elapsed_ms, 15)

    def test_multiple_validation_allows_more_positive_candidates_than_max_limit(self) -> None:
        entry = QuestionEntry(
            question_type="multiple",
            probabilities=[50.0, 50.0, 50.0, 50.0],
            option_count=4,
            question_num=4,
        )

        result = validate_question_config(
            [entry],
            [{"num": 4, "multi_min_limit": None, "multi_max_limit": 3}],
        )

        self.assertIsNone(result)

    def test_multiple_validation_still_blocks_when_positive_candidates_below_min_limit(self) -> None:
        entry = QuestionEntry(
            question_type="multiple",
            probabilities=[100.0, 0.0, 0.0, 0.0],
            option_count=4,
            question_num=6,
        )

        result = validate_question_config(
            [entry],
            [{"num": 6, "multi_min_limit": 2, "multi_max_limit": 3}],
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("最少选择 2 项", result)


if __name__ == "__main__":
    unittest.main()
