from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from CI.python_checks.common import (
    configure_console_encoding,
    ensure_target_dirs,
    ENTRY_FILES,
    iter_compile_targets,
    iter_module_names,
    iter_python_files,
    print_issues,
    print_scan_targets,
    run_compile_checks,
    run_module_import_checks,
    run_ruff_check,
    run_ruff_format_check,
    run_type_ignore_check,
    run_ty_check,
    run_unicode_escape_check,
    run_unit_tests,
    run_window_smoke_check,
)  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check syntax, static imports, and startup-chain issues in wjx, software, and tencent."
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Enable module import and main window smoke checks. The default is quick mode.",
    )
    return parser.parse_args()


def main() -> int:
    configure_console_encoding()
    args = parse_args()
    start_time = time.perf_counter()

    target_dirs = ensure_target_dirs()
    python_files = iter_python_files()
    compile_targets = iter_compile_targets()
    modules = iter_module_names(python_files)
    quick_mode = not args.full

    print_scan_targets(target_dirs)
    ruff_targets = [*target_dirs, ROOT_DIR / "CI"]
    print(
        f"[INFO] Ruff targets: {', '.join(str(path.relative_to(ROOT_DIR)) for path in ruff_targets)}"
    )
    print(f"[INFO] Check mode: {'quick' if quick_mode else 'full'}")
    print(f"[INFO] Python files: {len(python_files)}")
    print(f"[INFO] Compile targets: {len(compile_targets)}")
    print("[INFO] ty diagnostics: enabled")
    print("[INFO] Ruff lint and format diagnostics: enabled")
    print("[INFO] Unit tests: enabled")
    if quick_mode:
        print("[INFO] Module import checks: skipped (use --full to enable)")
        print("[INFO] Main window smoke check: skipped (use --full to enable)")
    else:
        print(f"[INFO] Module import checks: {len(modules)}")
        print("[INFO] Main window smoke check: enabled")

    compile_issues = run_compile_checks(compile_targets)
    ruff_issues, ruff_error = run_ruff_check(ruff_targets)
    ruff_format_issues, ruff_format_error = run_ruff_format_check(ruff_targets)
    type_ignore_issues = run_type_ignore_check([*target_dirs, ROOT_DIR / "CI", *ENTRY_FILES])
    unicode_escape_issues = run_unicode_escape_check([ROOT_DIR / "CI"])
    ty_issues, ty_error = run_ty_check(target_dirs)
    unit_test_issue, coverage_summary = run_unit_tests()
    import_issues = run_module_import_checks(modules) if args.full else []
    window_issue = run_window_smoke_check() if args.full else None

    if ruff_error:
        print(f"[ERROR] {ruff_error}")
        return 2
    if ruff_format_error:
        print(f"[ERROR] {ruff_format_error}")
        return 2
    if ty_error:
        print(f"[ERROR] {ty_error}")
        return 2

    total_issues = (
        len(compile_issues)
        + len(ruff_issues)
        + len(ruff_format_issues)
        + len(type_ignore_issues)
        + len(unicode_escape_issues)
        + len(ty_issues)
        + (1 if unit_test_issue else 0)
        + len(import_issues)
        + (1 if window_issue else 0)
    )
    elapsed = time.perf_counter() - start_time

    print(f"[INFO] Compile issues: {len(compile_issues)}")
    print(f"[INFO] Ruff diagnostics: {len(ruff_issues)}")
    print(f"[INFO] Ruff format diagnostics: {len(ruff_format_issues)}")
    print(f"[INFO] Type ignore diagnostics: {len(type_ignore_issues)}")
    print(f"[INFO] Unicode escape diagnostics: {len(unicode_escape_issues)}")
    print(f"[INFO] ty diagnostics: {len(ty_issues)}")
    print(f"[INFO] Unit test failures: {1 if unit_test_issue else 0}")
    if coverage_summary:
        print("[INFO] Coverage summary:")
        print(coverage_summary)
    print(f"[INFO] Module import failures: {len(import_issues)}")
    print(f"[INFO] Main window smoke failures: {1 if window_issue else 0}")
    print(f"[INFO] Elapsed time: {elapsed:.2f}s")

    if total_issues == 0:
        if quick_mode:
            print("[PASS] Quick checks passed: compile, Ruff, ty, and unit tests all succeeded.")
            print(
                "[INFO] For import and main window smoke checks, run: python CI/python_ci.py --full"
            )
        else:
            print(
                "[PASS] Full checks passed: compile, Ruff, ty, unit tests, module import, and main window smoke checks all succeeded."
            )
        return 0

    print(f"[FAIL] Found {total_issues} issue(s):")
    print_issues("[Compile failures]", compile_issues)
    print_issues("[Ruff diagnostics]", ruff_issues)
    print_issues("[Ruff format diagnostics]", ruff_format_issues)
    print_issues("[Type ignore diagnostics]", type_ignore_issues)
    print_issues("[Unicode escape diagnostics]", unicode_escape_issues)
    print_issues("[ty diagnostics]", ty_issues)
    if unit_test_issue:
        print_issues("[Unit test failures]", [unit_test_issue])
    print_issues("[Module import failures]", import_issues)
    if window_issue:
        print_issues("[Main window smoke failures]", [window_issue])

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
