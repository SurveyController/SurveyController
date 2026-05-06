from __future__ import annotations
import pytest
from threading import Event
from unittest.mock import patch
from software.app.browser_probe import BrowserProbeRequest, BrowserProbeResult, _parse_probe_stdout, probe_browser_environment, run_browser_probe_cli_from_argv, run_browser_probe_subprocess

class _FakeDriver:

    def __init__(self) -> None:
        self.quit_called = False

    def quit(self) -> None:
        self.quit_called = True

class _CompletedProbeProcess:
    pid = 9527

    def __init__(self, stdout: bytes, stderr: bytes, return_code: int=0) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self._return_code = return_code
        self.killed = False

    def poll(self) -> int:
        return self._return_code

    def communicate(self, timeout: float | None=None) -> tuple[bytes, bytes]:
        return (self._stdout, self._stderr)

    def kill(self) -> None:
        self.killed = True

class _PendingProbeProcess:
    pid = 9528

    def __init__(self) -> None:
        self.killed = False

    def poll(self) -> None:
        return None

    def communicate(self, timeout: float | None=None) -> tuple[bytes, bytes]:
        raise AssertionError('挂起进程不应该被读取输出')

    def kill(self) -> None:
        self.killed = True

class BrowserProbeTests:

    def test_request_token_roundtrip_filters_empty_browser_names(self) -> None:
        request = BrowserProbeRequest(headless=False, browser_preference=['edge', '', '  ', 'chrome'])
        restored = BrowserProbeRequest.from_token(request.to_token())
        assert not restored.headless
        assert restored.browser_preference == ['edge', 'chrome']

    def test_request_from_token_rejects_empty_value(self) -> None:
        with pytest.raises(ValueError):
            BrowserProbeRequest.from_token('')

    def test_parse_probe_stdout_reads_last_json_line(self) -> None:
        result = _parse_probe_stdout('noise line\n{"ok":true,"browser":"edge","error_kind":"","message":"ok","elapsed_ms":321}\n')
        assert result is not None
        assert result is not None
        assert result.ok
        assert result.browser == 'edge'
        assert result.elapsed_ms == 321

    def test_parse_probe_stdout_returns_none_for_invalid_output(self) -> None:
        assert _parse_probe_stdout('not json') is None

    def test_probe_browser_environment_reports_success_and_quits_driver(self) -> None:
        fake_driver = _FakeDriver()
        with patch('software.app.browser_probe.create_playwright_driver', return_value=(fake_driver, 'edge')), patch('software.app.browser_probe.time.monotonic', side_effect=[0.0, 0.2]):
            result = probe_browser_environment(BrowserProbeRequest(headless=True, browser_preference=['edge']))
        assert result.ok
        assert result.browser == 'edge'
        assert result.message == '浏览器环境快速检查通过'
        assert fake_driver.quit_called

    def test_probe_browser_environment_reports_launch_failure(self) -> None:
        with patch('software.app.browser_probe.create_playwright_driver', side_effect=RuntimeError('boom')), patch('software.app.browser_probe.time.monotonic', side_effect=[0.0, 0.5]):
            result = probe_browser_environment(BrowserProbeRequest(headless=True, browser_preference=['edge']))
        assert not result.ok
        assert result.error_kind == 'launch_failed'
        assert 'boom' in result.message

    def test_run_browser_probe_cli_returns_invalid_request_for_bad_token(self) -> None:
        with patch('builtins.print') as print_mock:
            status = run_browser_probe_cli_from_argv(['--sc-browser-probe', '%%%'])
        assert status == 2
        printed = print_mock.call_args.args[0]
        result = BrowserProbeResult.from_json(printed)
        assert not result.ok
        assert result.error_kind == 'invalid_request'

    def test_run_browser_probe_subprocess_tolerates_invalid_utf8_bytes(self) -> None:
        fake_process = _CompletedProbeProcess(b'probe noise:\x80\x81\n{"ok":true,"browser":"edge","error_kind":"","message":"ok","elapsed_ms":15}\n', b'\xff\xfe')
        with patch('software.app.browser_probe.subprocess.Popen', return_value=fake_process):
            result = run_browser_probe_subprocess(headless=True, browser_preference=['edge'], timeout_seconds=1)
        assert result.ok
        assert result.browser == 'edge'
        assert result.elapsed_ms == 15

    def test_run_browser_probe_subprocess_rejects_invalid_response(self) -> None:
        fake_process = _CompletedProbeProcess(b'still booting\n', b'stderr boom')
        with patch('software.app.browser_probe.subprocess.Popen', return_value=fake_process):
            result = run_browser_probe_subprocess(headless=True, browser_preference=['edge'], timeout_seconds=1)
        assert not result.ok
        assert result.error_kind == 'invalid_response'
        assert 'stderr boom' in result.message

    def test_run_browser_probe_subprocess_times_out_and_kills_process(self) -> None:
        fake_process = _PendingProbeProcess()
        with patch('software.app.browser_probe.subprocess.Popen', return_value=fake_process), patch('software.app.browser_probe._kill_process_tree') as kill_mock, patch('software.app.browser_probe.time.monotonic', side_effect=[0.0, 0.0, 2.0, 2.0, 2.0]):
            result = run_browser_probe_subprocess(headless=True, browser_preference=['edge'], timeout_seconds=1)
        assert not result.ok
        assert result.error_kind == 'timeout'
        kill_mock.assert_called_once_with(fake_process)

    def test_run_browser_probe_subprocess_returns_cancelled_when_event_is_set(self) -> None:
        fake_process = _PendingProbeProcess()
        cancel_event = Event()
        cancel_event.set()
        with patch('software.app.browser_probe.subprocess.Popen', return_value=fake_process), patch('software.app.browser_probe._kill_process_tree') as kill_mock, patch('software.app.browser_probe.time.monotonic', side_effect=[0.0, 0.1, 0.1, 0.1]):
            result = run_browser_probe_subprocess(headless=True, browser_preference=['edge'], timeout_seconds=1, cancel_event=cancel_event)
        assert not result.ok
        assert result.error_kind == 'cancelled'
        kill_mock.assert_called_once_with(fake_process)
