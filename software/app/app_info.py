from __future__ import annotations

import json
from pathlib import Path
import sys
import tomllib

from packaging.version import InvalidVersion, Version


def _validated_version(value: object, source: Path) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing application version in {source}")
    if value != value.strip() or value[:1].lower() == "v":
        raise ValueError(f"Invalid application version in {source}: {value!r}")
    try:
        Version(value)
    except InvalidVersion as exc:
        raise ValueError(f"Invalid application version in {source}: {value!r}") from exc
    return value


def read_project_version(project_file: Path) -> str:
    with project_file.open("rb") as stream:
        metadata = tomllib.load(stream)
    project = metadata.get("project")
    if not isinstance(project, dict):
        raise ValueError(f"Missing project metadata in {project_file}")
    return _validated_version(project.get("version"), project_file)


def _load_app_version() -> str:
    module_file = Path(__file__).resolve()
    if "__compiled__" in globals() or getattr(sys, "frozen", False):
        snapshot_file = module_file.with_name("build-info.json")
        metadata = json.loads(snapshot_file.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError(f"Invalid application metadata in {snapshot_file}")
        return _validated_version(metadata.get("version"), snapshot_file)
    return read_project_version(module_file.parents[2] / "pyproject.toml")


APP_VERSION = _load_app_version()
