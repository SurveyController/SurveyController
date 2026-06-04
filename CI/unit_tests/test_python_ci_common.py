from __future__ import annotations

from pathlib import Path

import pytest

from CI.python_checks import common


def test_run_unicode_escape_check_reports_ci_unicode_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ci_dir = tmp_path / "CI"
    ci_dir.mkdir()
    source_path = ci_dir / "demo.py"
    escaped = "\\" + "u4e2d" + "\\" + "u6587"
    source_path.write_text(f'value = "{escaped}"\n', encoding="utf-8")

    monkeypatch.setattr(common, "UNICODE_ESCAPE_SCAN_ROOTS", (ci_dir,))
    issues = common.run_unicode_escape_check([ci_dir])

    assert len(issues) == 1
    assert all(item["phase"] == "unicode-escape" for item in issues)
    assert all(item["path"] == common.format_path(source_path) for item in issues)


def test_run_unicode_escape_check_skips_non_ci_targets(tmp_path: Path, monkeypatch) -> None:
    software_dir = tmp_path / "software"
    software_dir.mkdir()
    source_path = software_dir / "demo.py"
    escaped = "\\" + "u4e2d" + "\\" + "u6587"
    source_path.write_text(f'value = "{escaped}"\n', encoding="utf-8")

    monkeypatch.setattr(common, "UNICODE_ESCAPE_SCAN_ROOTS", (tmp_path / "CI",))
    issues = common.run_unicode_escape_check([software_dir])

    assert issues == []
