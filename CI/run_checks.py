from __future__ import annotations

import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from CI.python_checks.common import ROOT_DIR, configure_console_encoding, make_child_env


def run_checks(checks: dict[str, list[str]]) -> int:
    failed = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(
                subprocess.run,
                command,
                cwd=ROOT_DIR,
                env=make_child_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            ): name
            for name, command in checks.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            result = future.result()
            print(f"::group::{name}", flush=True)
            print(result.stdout, end="", flush=True)
            print("::endgroup::", flush=True)
            if result.returncode:
                failed.append(name)
                print(f"::error::{name} failed with exit code {result.returncode}", flush=True)
            else:
                print(f"[PASS] {name}", flush=True)
    if failed:
        print(f"[FAIL] {', '.join(failed)}", flush=True)
        return 1
    return 0


def main() -> int:
    configure_console_encoding()
    parser = argparse.ArgumentParser()
    parser.add_argument("group", choices=("python", "desktop"))
    args = parser.parse_args()
    python_modules = {
        "Compile": "CI.python_checks.compile_check",
        "Ruff": "CI.python_checks.ruff_check",
        "Types": "CI.python_checks.ty_check",
    }
    if os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
        python_modules["Live survey regression"] = "CI.live_tests.surveycore_regression"
    desktop_modules = {
        "Unit tests": "CI.python_checks.unit_test_check",
        "Imports": "CI.python_checks.import_check",
        "Window smoke": "CI.python_checks.window_smoke_check",
    }
    modules = python_modules if args.group == "python" else desktop_modules
    return run_checks({name: [sys.executable, "-m", module] for name, module in modules.items()})


if __name__ == "__main__":
    raise SystemExit(main())
