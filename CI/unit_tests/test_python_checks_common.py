from __future__ import annotations

from CI.python_checks import common


def test_build_unit_test_pytest_args_uses_default_coverage_constant() -> None:
    args = common.build_unit_test_pytest_args(verbose_in_ci=False)

    assert f"--cov-fail-under={common.DEFAULT_UNIT_TEST_COVERAGE_FAIL_UNDER}" in args


def test_default_unit_test_coverage_fail_under_is_45() -> None:
    assert common.DEFAULT_UNIT_TEST_COVERAGE_FAIL_UNDER == "45"


def test_build_unit_test_pytest_args_does_not_depend_on_env_override(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SURVEY_CONTROLLER_UNIT_TEST_COVERAGE_FAIL_UNDER", "99")
    args = common.build_unit_test_pytest_args(verbose_in_ci=False)

    assert "--cov-fail-under=45" in args
    assert "--cov-fail-under=99" not in args
