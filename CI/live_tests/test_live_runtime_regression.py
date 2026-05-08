"""真实运行链路回归测试。"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATHS = (
    ROOT_DIR / "configs" / "debug.json",
    ROOT_DIR / "configs" / "credamo.json",
    ROOT_DIR / "configs" / "腾讯问卷.json",
)
LIVE_CONFIG_ENV = "SURVEY_CONTROLLER_LIVE_TEST_CONFIG"
INNER_TIMEOUT_SECONDS = "240"
OUTER_TIMEOUT_SECONDS = 300


def _resolve_live_config_paths() -> list[Path]:
    configured = str(os.environ.get(LIVE_CONFIG_ENV, "") or "").strip()
    if not configured:
        return list(DEFAULT_CONFIG_PATHS)

    config_path = Path(configured)
    if not config_path.is_absolute():
        config_path = ROOT_DIR / config_path
    return [config_path]


def _build_child_env() -> dict[str, str]:
    env = os.environ.copy()
    current_python_path = env.get("PYTHONPATH", "")
    root_path = str(ROOT_DIR)
    env["PYTHONPATH"] = root_path if not current_python_path else os.pathsep.join([root_path, current_python_path])
    return env


def _format_output(stdout: str, stderr: str) -> str:
    stdout_text = (stdout or "").strip()
    stderr_text = (stderr or "").strip()
    chunks = [chunk for chunk in (stdout_text, stderr_text) if chunk]
    return "\n".join(chunks)


@pytest.mark.parametrize("config_path", _resolve_live_config_paths(), ids=lambda path: path.stem)
def test_live_runtime_regression(config_path: Path) -> None:
    assert config_path.exists(), f"Live test config not found: {config_path}"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "CI.live_tests.run_async_engine_once",
            "--config",
            str(config_path),
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
        f"Live runtime regression failed for {config_path.name}.\n"
        f"Exit code: {result.returncode}\n"
        f"Output:\n{output}"
    )
    assert "cur_num=1" in output, (
        f"Live runtime regression did not report a successful submission for {config_path.name}.\n"
        f"Output:\n{output}"
    )
