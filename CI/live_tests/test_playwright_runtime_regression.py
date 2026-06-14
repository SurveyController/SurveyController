"""真实 Playwright 作答链路回归测试。"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
LIVE_URL_ENV = "SURVEY_CONTROLLER_LIVE_TEST_URL"
INNER_TIMEOUT_SECONDS = "240"
OUTER_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class PlaywrightSurveyCase:
    name: str
    url: str


DEFAULT_PLAYWRIGHT_SURVEY_CASES = (
    PlaywrightSurveyCase("wjx", "https://v.wjx.cn/vm/ei3sVrE.aspx"),
    PlaywrightSurveyCase("credamo", "https://www.credamo.com/s/A73QR3ano"),
    PlaywrightSurveyCase("tencent", "https://wj.qq.com/s2/26070328/fa89/"),
)


def _resolve_playwright_survey_cases() -> list[PlaywrightSurveyCase]:
    configured_url = str(os.environ.get(LIVE_URL_ENV, "") or "").strip()
    if not configured_url:
        return list(DEFAULT_PLAYWRIGHT_SURVEY_CASES)

    return [PlaywrightSurveyCase("configured", configured_url)]


def _build_child_env() -> dict[str, str]:
    env = os.environ.copy()
    current_python_path = env.get("PYTHONPATH", "")
    root_path = str(ROOT_DIR)
    env["PYTHONPATH"] = root_path if not current_python_path else os.pathsep.join([root_path, current_python_path])
    env["PYTHONIOENCODING"] = "utf-8:replace"
    env["PYTHONUTF8"] = "1"
    return env


def _format_output(stdout: str, stderr: str) -> str:
    stdout_text = (stdout or "").strip()
    stderr_text = (stderr or "").strip()
    chunks = [chunk for chunk in (stdout_text, stderr_text) if chunk]
    return "\n".join(chunks)


@pytest.mark.parametrize("survey_case", _resolve_playwright_survey_cases(), ids=lambda case: case.name)
def test_playwright_runtime_regression(survey_case: PlaywrightSurveyCase) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "CI.live_tests.run_playwright_runtime_once",
            "--url",
            survey_case.url,
            "--timeout",
            INNER_TIMEOUT_SECONDS,
        ],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_build_child_env(),
        timeout=OUTER_TIMEOUT_SECONDS,
    )
    output = _format_output(result.stdout, result.stderr)

    assert result.returncode == 0, (
        f"Playwright runtime regression failed for {survey_case.name}.\n"
        f"Exit code: {result.returncode}\n"
        f"Output:\n{output}"
    )
    assert "playwright_browser=edge" in output and "playwright_channel=msedge" in output, (
        f"Playwright runtime regression did not use system Microsoft Edge for {survey_case.name}.\n"
        f"Output:\n{output}"
    )
    assert "cur_num=1" in output, (
        f"Playwright runtime regression did not report a successful submission for {survey_case.name}.\n"
        f"Output:\n{output}"
    )
