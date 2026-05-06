#!/usr/bin/env python
"""离线单元测试检查。"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from CI.python_checks.common import (
    configure_console_encoding,
    ensure_target_dirs,
    print_issues,
    print_scan_targets,
    run_unit_tests,
)


def main() -> int:
    configure_console_encoding()
    target_dirs = ensure_target_dirs()

    print_scan_targets(target_dirs)
    issue, coverage_summary = run_unit_tests()
    print(f"[INFO] Unit test failures: {1 if issue else 0}")
    if issue is None:
        if coverage_summary:
            print("[INFO] Coverage summary:")
            print(coverage_summary)
        print("[PASS] Unit tests passed.")
        return 0

    print("[FAIL] Unit tests failed:")
    print_issues("[Unit test failures]", [issue])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
