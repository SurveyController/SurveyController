from __future__ import annotations

from CI.python_checks.common import (
    ENTRY_FILES,
    ROOT_DIR,
    configure_console_encoding,
    ensure_target_dirs,
    print_issues,
    print_scan_targets,
    run_ty_check,
    run_type_ignore_check,
)


def main() -> int:
    configure_console_encoding()
    target_dirs = ensure_target_dirs()

    print_scan_targets(target_dirs)
    suppression_issues = run_type_ignore_check([*target_dirs, ROOT_DIR / "CI", *ENTRY_FILES])
    if suppression_issues:
        print(f"[FAIL] Found {len(suppression_issues)} forbidden type suppression(s):")
        print_issues("[Type suppression diagnostics]", suppression_issues)
        return 1

    issues, error = run_ty_check(target_dirs)
    if error:
        print(f"[ERROR] {error}")
        return 2

    print(f"[INFO] ty diagnostics: {len(issues)}")
    if not issues:
        print("[PASS] ty checks passed.")
        return 0

    print(f"[FAIL] Found {len(issues)} ty diagnostic(s):")
    print_issues("[ty diagnostics]", issues)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
