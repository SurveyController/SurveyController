from __future__ import annotations

import sys

import pytest

from CI import run_checks as runner
from CI.run_checks import run_checks


def test_parallel_checks_wait_for_each_other_and_propagate_failure(tmp_path, capsys) -> None:
    signal = tmp_path / "ready"
    waiting = (
        "import pathlib, sys, time; "
        f"signal = pathlib.Path({str(signal)!r}); "
        "deadline = time.monotonic() + 10\n"
        "while not signal.exists() and time.monotonic() < deadline: time.sleep(0.01)\n"
        "assert signal.exists(); print('waiter completed'); sys.exit(7)"
    )
    notifying = (
        f"from pathlib import Path; Path({str(signal)!r}).touch(); print('notifier completed')"
    )

    result = run_checks(
        {
            "waiting": [sys.executable, "-c", waiting],
            "notifying": [sys.executable, "-c", notifying],
        }
    )

    output = capsys.readouterr().out
    assert result == 1
    assert "waiter completed" in output
    assert "notifier completed" in output
    assert "waiting failed with exit code 7" in output
    assert "[PASS] notifying" in output


def test_successful_checks_pass(capsys) -> None:
    assert run_checks({"success": [sys.executable, "-c", "print('complete')"]}) == 0
    assert "[PASS] success" in capsys.readouterr().out


@pytest.mark.parametrize("event", ["pull_request", "push", "workflow_dispatch", ""])
@pytest.mark.parametrize("group", ["python", "desktop"])
def test_live_regression_runs_only_in_pull_request_python_job(monkeypatch, event, group) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setattr(sys, "argv", ["run_checks", group])
    commands = {}

    def capture(checks):
        commands.update(checks)
        return 0

    monkeypatch.setattr(runner, "run_checks", capture)

    assert runner.main() == 0
    assert ("Live survey regression" in commands) == (event == "pull_request" and group == "python")
    assert len(commands) == (4 if event == "pull_request" and group == "python" else 3)
