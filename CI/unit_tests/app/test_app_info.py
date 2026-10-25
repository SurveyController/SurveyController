from __future__ import annotations

import json
from pathlib import Path

import pytest

from software.app import app_info


@pytest.fixture
def source_tree(tmp_path, monkeypatch) -> Path:
    module_file = tmp_path / "software" / "app" / "app_info.py"
    module_file.parent.mkdir(parents=True)
    monkeypatch.setattr(app_info, "__file__", str(module_file))
    monkeypatch.delattr(app_info, "__compiled__", raising=False)
    monkeypatch.setattr(app_info.sys, "frozen", False, raising=False)
    return tmp_path


def test_source_version_ignores_working_directory_environment_and_stale_snapshot(
    source_tree,
    tmp_path,
    monkeypatch,
) -> None:
    (source_tree / "pyproject.toml").write_text(
        '[project]\nversion = "4.1.0rc2"\n',
        encoding="utf-8",
    )
    snapshot = source_tree / "software" / "app" / "build-info.json"
    snapshot.write_text('{"version": "1.0.0"}', encoding="utf-8")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    monkeypatch.setenv("APP_VERSION", "9.9.9")

    assert app_info._load_app_version() == "4.1.0rc2"


@pytest.mark.parametrize("compiled,frozen", [(True, False), (False, True)])
def test_packaged_version_uses_snapshot_instead_of_source(
    source_tree, monkeypatch, compiled, frozen
):
    (source_tree / "pyproject.toml").write_text(
        '[project]\nversion = "9.9.9"\n',
        encoding="utf-8",
    )
    snapshot = source_tree / "software" / "app" / "build-info.json"
    snapshot.write_text('{"version": "4.1.0rc2"}', encoding="utf-8")
    if compiled:
        monkeypatch.setattr(app_info, "__compiled__", object(), raising=False)
    monkeypatch.setattr(app_info.sys, "frozen", frozen, raising=False)

    assert app_info._load_app_version() == "4.1.0rc2"


def test_missing_packaged_snapshot_never_falls_back_to_source(source_tree, monkeypatch):
    (source_tree / "pyproject.toml").write_text(
        '[project]\nversion = "4.1.0"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(app_info, "__compiled__", object(), raising=False)

    with pytest.raises(FileNotFoundError, match="build-info.json"):
        app_info._load_app_version()


@pytest.mark.parametrize("payload", ["[]", "{}", '{"version": "invalid"}', "{bad"])
def test_invalid_packaged_snapshot_is_rejected(source_tree, monkeypatch, payload):
    snapshot = source_tree / "software" / "app" / "build-info.json"
    snapshot.write_text(payload, encoding="utf-8")
    monkeypatch.setattr(app_info, "__compiled__", object(), raising=False)

    with pytest.raises(ValueError):
        app_info._load_app_version()


@pytest.mark.parametrize("value", ["", "invalid", "v4.1.0", "4.1.0beta1", " 4.1.0 ", 410])
def test_source_requires_a_canonical_version(tmp_path, value):
    project = tmp_path / "pyproject.toml"
    project.write_text(f"[project]\nversion = {json.dumps(value)}\n", encoding="utf-8")

    with pytest.raises(ValueError):
        app_info.read_project_version(project)


@pytest.mark.parametrize("payload", ["", "[project]\nname = 'surveycontroller'\n"])
def test_missing_source_version_is_rejected(tmp_path, payload):
    project = tmp_path / "pyproject.toml"
    project.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError):
        app_info.read_project_version(project)


def test_missing_source_file_is_rejected(source_tree):
    with pytest.raises(FileNotFoundError, match="pyproject.toml"):
        app_info._load_app_version()
