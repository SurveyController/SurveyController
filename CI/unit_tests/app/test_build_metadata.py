from __future__ import annotations

import json
from pathlib import Path

import pytest

from CI.build_tools import app_metadata
from software.app import app_info


def _project(tmp_path: Path, version: str) -> Path:
    project = tmp_path / "pyproject.toml"
    project.write_text(f'[project]\nversion = "{version}"\n', encoding="utf-8")
    return project


@pytest.mark.parametrize("version", ["4.1.0", "4.1.0rc2", "4.1.0.dev3", "4.1.0.post1"])
def test_metadata_preserves_full_version_and_derives_windows_version(tmp_path, version):
    metadata = app_metadata.build_metadata(_project(tmp_path, version), release_tag=f"v{version}")

    assert metadata == {
        "version": version,
        "windows_version": "4.1.0.0",
        "archive_name": f"SurveyController-{version}.zip",
    }


@pytest.mark.parametrize("tag", ["v4.1.1", "4.1.0", "v4.1.0rc2", ""])
def test_release_tag_must_match_project_version(tmp_path, tag):
    with pytest.raises(ValueError, match="Release tag"):
        app_metadata.build_metadata(_project(tmp_path, "4.1.0"), release_tag=tag)


@pytest.mark.parametrize("version", ["65536.0.0", "1.2.3.4.5", "1!4.1.0", "4.1.0+local"])
def test_versions_that_cannot_fit_windows_resources_are_rejected(tmp_path, version):
    with pytest.raises(ValueError, match="Windows version"):
        app_metadata.build_metadata(_project(tmp_path, version))


def test_generated_snapshot_loads_without_a_source_checkout(tmp_path, monkeypatch, capsys):
    _project(tmp_path, "4.1.0rc2")
    monkeypatch.setattr(app_metadata, "PROJECT_ROOT", tmp_path)
    bundled_module = tmp_path / "bundle" / "software" / "app" / "app_info.py"
    output = bundled_module.with_name("build-info.json")

    assert app_metadata.main(["--output", str(output), "--release-tag", "v4.1.0rc2"]) == 0
    assert json.loads(capsys.readouterr().out) == json.loads(output.read_text(encoding="utf-8"))
    (tmp_path / "pyproject.toml").unlink()
    monkeypatch.setattr(app_info, "__file__", str(bundled_module))
    monkeypatch.setattr(app_info, "__compiled__", object(), raising=False)

    assert app_info._load_app_version() == "4.1.0rc2"


def test_failed_tag_check_does_not_overwrite_existing_snapshot(tmp_path, monkeypatch):
    _project(tmp_path, "4.1.0")
    monkeypatch.setattr(app_metadata, "PROJECT_ROOT", tmp_path)
    output = tmp_path / "build-info.json"
    output.write_text("previous build", encoding="utf-8")

    with pytest.raises(SystemExit) as failure:
        app_metadata.main(["--output", str(output), "--release-tag", "v4.1.1"])

    assert failure.value.code == 1
    assert output.read_text(encoding="utf-8") == "previous build"
