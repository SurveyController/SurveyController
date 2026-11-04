from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRAMEWORK_IMPORTS = ("PySide6", "qfluentwidgets", "software.ui")


def _import_names(source: str) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _is_forbidden(name: str) -> bool:
    return any(name == prefix or name.startswith(f"{prefix}.") for prefix in FRAMEWORK_IMPORTS)


def test_application_layer_has_no_ui_or_qt_imports() -> None:
    application_root = PROJECT_ROOT / "software" / "application"
    violations = [
        f"{path.relative_to(PROJECT_ROOT)}: {name}"
        for path in application_root.rglob("*.py")
        for name in _import_names(path.read_text(encoding="utf-8"))
        if _is_forbidden(name)
    ]

    assert violations == []


def test_core_and_infrastructure_have_no_ui_or_qt_imports() -> None:
    roots = (
        "software/core",
        "software/network",
        "software/providers",
        "software/integrations",
        "software/io",
        "wjx/provider",
        "tencent/provider",
        "credamo/provider",
    )
    violations = [
        f"{path.relative_to(PROJECT_ROOT)}: {name}"
        for relative_root in roots
        for path in (PROJECT_ROOT / relative_root).rglob("*.py")
        for name in _import_names(path.read_text(encoding="utf-8"))
        if _is_forbidden(name)
    ]

    assert violations == []


def test_application_services_import_without_qt_application() -> None:
    script = """
import importlib.abc
import sys

class NoQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'PySide6', 'qfluentwidgets'}:
            raise AssertionError('Qt dependency leaked: ' + fullname)

sys.meta_path.insert(0, NoQt())
from CI.unit_tests.application.fakes import Harness
from software.application.survey_parse_service import SurveyParseService
from software.application.configuration import ConfigurationService
from software.application.preferences import PreferencesService

harness = Harness()
try:
    harness.start()
    harness.service.pause_run()
    harness.service.resume_run()
    harness.finish()
finally:
    harness.close()
assert not any(name.startswith('PySide6') for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
