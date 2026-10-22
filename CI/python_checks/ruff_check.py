from __future__ import annotations

from CI.python_checks.common import (
    ROOT_DIR,
    configure_console_encoding,
    ensure_target_dirs,
    print_issues,
    print_scan_targets,
    run_ruff_check,
    run_ruff_format_check,
)


def main() -> int:
    configure_console_encoding()
    target_dirs = ensure_target_dirs()

    check_targets = [*target_dirs, ROOT_DIR / "CI"]
    print_scan_targets(check_targets)
    issues, error = run_ruff_check(check_targets)
    if error:
        print(f"[ERROR] {error}")
        return 2

    format_issues, format_error = run_ruff_format_check(check_targets)
    if format_error:
        print(f"[ERROR] {format_error}")
        return 2

    print(f"[INFO] Ruff lint diagnostics: {len(issues)}")
    print(f"[INFO] Ruff format diagnostics: {len(format_issues)}")
    if not issues and not format_issues:
        print("[PASS] Ruff lint and format checks passed.")
        return 0

    print(f"[FAIL] Found {len(issues) + len(format_issues)} Ruff diagnostic(s):")
    print_issues("[Ruff lint diagnostics]", issues)
    print_issues("[Ruff format diagnostics]", format_issues)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
