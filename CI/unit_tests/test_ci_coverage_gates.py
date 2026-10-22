from __future__ import annotations

from CI.python_checks.common import (
    PACKAGE_COVERAGE_THRESHOLDS,
    check_package_coverage,
    make_window_smoke_env,
)


def test_package_coverage_gate_checks_branch_coverage_separately() -> None:
    files = {}
    for package, threshold in PACKAGE_COVERAGE_THRESHOLDS.items():
        if package == "providers":
            path = "wjx/example.py"
        else:
            path = f"{package}/example.py"
        branch_percent = 50 if package == "software/core" else threshold
        files[path] = {
            "summary": {
                "num_statements": 100,
                "covered_lines": 90,
                "num_branches": 100,
                "covered_branches": branch_percent,
            }
        }

    diagnostics = check_package_coverage({"files": files})

    assert diagnostics == [
        {
            "phase": "unit",
            "message": "software/core branch coverage is 50.0%; the required minimum is 85%.",
        }
    ]


def test_package_coverage_gate_rejects_missing_coverage_data() -> None:
    diagnostics = check_package_coverage({"files": {}})

    assert len(diagnostics) == len(PACKAGE_COVERAGE_THRESHOLDS)
    assert all("Coverage data is missing" in item["message"] for item in diagnostics)


def test_window_smoke_uses_offscreen_qt_platform() -> None:
    assert make_window_smoke_env()["QT_QPA_PLATFORM"] == "offscreen"
