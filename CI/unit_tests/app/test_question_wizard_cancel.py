from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, cast

from PySide6.QtWidgets import QDialog

import software.ui.pages.workbench.dashboard.parts.entries as entries_module
from software.core.questions.config import QuestionEntry
from software.providers.contracts import SurveyQuestionMeta
from software.ui.pages.workbench.dashboard.parts.entries import DashboardEntriesMixin


class _FakeSwitchButton:
    def isChecked(self) -> bool:
        return True


class _FakeWizardDialog:
    def __init__(self, *_args, **_kwargs) -> None:
        return

    def exec(self) -> int:
        return int(QDialog.DialogCode.Rejected)

    def deleteLater(self) -> None:
        raise RuntimeError("Internal C++ object already deleted.")


class _FakeDashboard(DashboardEntriesMixin):
    def __init__(self) -> None:
        self._survey_title = "demo"
        self.runtime_page = SimpleNamespace(
            reliability_card=SimpleNamespace(switchButton=_FakeSwitchButton())
        )
        self.toast_calls: list[tuple[str, str]] = []

    def _toast(self, text: str, level: str = "info", duration: int = 2000) -> None:
        _ = duration
        self.toast_calls.append((str(text), str(level)))

    def _apply_wizard_results(self, entries, dlg) -> None:
        raise AssertionError("取消时不该应用结果")


def test_run_question_wizard_cancel_does_not_raise_on_already_deleted_dialog(monkeypatch) -> None:
    dashboard = _FakeDashboard()
    monkeypatch.setattr(entries_module, "QuestionWizardDialog", _FakeWizardDialog)
    monkeypatch.setattr(entries_module, "isValid", lambda _obj: False)
    entries = cast(list[QuestionEntry], [SimpleNamespace()])
    info = cast(list[SurveyQuestionMeta | Dict[str, Any]], [cast(Dict[str, Any], {"num": 1})])

    accepted = dashboard.run_question_wizard(entries, info, "demo")

    assert accepted is False
    assert dashboard.toast_calls == []
