from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from surveycore.core.questions.config import QuestionEntry
from surveycore.providers.contracts import SurveyQuestionMeta

import software.ui.pages.workbench.dashboard.parts.entries as entries_module
import software.ui.pages.workbench.dashboard.parts.run_actions as run_actions_module
from software.core.config.schema import RuntimeConfig
from software.ui.pages.workbench.dashboard.parts.entries import (
    DashboardEntriesMixin,
    _apply_result_updates,
    _normalize_wizard_weights,
)
from software.ui.pages.workbench.dashboard.parts.run_actions import DashboardRunActionsMixin


class _DashboardDouble(DashboardEntriesMixin, DashboardRunActionsMixin):
    def __init__(self) -> None:
        self._survey_title = ""
        self.run_setup_panel = SimpleNamespace(
            set_survey_summary=MagicMock(),
            get_reliability_mode_enabled=MagicMock(return_value=False),
        )
        self.execution_panel = SimpleNamespace(reset_for_new_run=MagicMock())
        self.open_execution_step = MagicMock()
        self.workbench_state = SimpleNamespace(snapshot=lambda: RuntimeConfig(target=4))
        self.controller = SimpleNamespace(fetch_question_media=None)
        self.toasts: list[tuple[str, str]] = []
        self.url_edit = SimpleNamespace(
            text=lambda: "https://www.wjx.cn/vm/demo.aspx",
            setText=MagicMock(),
        )

    def _toast(self, text: str, level: str = "info", **_kwargs) -> None:
        self.toasts.append((text, level))


def test_wizard_result_updates_normalize_weights_and_keep_entry_contract() -> None:
    entries = [QuestionEntry("single", [1, 1]), QuestionEntry("text", None)]

    assert _normalize_wizard_weights([[1, -2], [3]]) == [[1.0, 0.0], [3.0]]
    assert _normalize_wizard_weights([1, -2]) == [1.0, 0.0]
    assert _normalize_wizard_weights("raw") == "raw"

    _apply_result_updates(entries, {0: [5, 0], 10: [1]}, entries_module._apply_distribution_result)
    assert entries[0].distribution_mode == "custom"
    assert entries[0].custom_weights == [5.0, 0.0]

    _apply_result_updates(entries, {1: ["A"]}, entries_module._apply_text_result)
    entries_module._apply_ai_flag_result(entries[1], True)
    entries_module._apply_dimension_result(entries[0], "体验")
    assert entries[1].texts == ["A"]
    assert entries[1].ai_enabled is True
    assert entries[0].dimension == "体验"


def test_run_question_wizard_applies_results_without_legacy_entry_table(monkeypatch) -> None:
    page = _DashboardDouble()

    class _AcceptedDialog:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        @staticmethod
        def get_results(_dialog):
            return {0: [3, 7]}

        @staticmethod
        def get_text_results(_dialog):
            return {}

        @staticmethod
        def get_option_fill_results(_dialog):
            return {}

        @staticmethod
        def get_text_random_modes(_dialog):
            return {}

        @staticmethod
        def get_text_random_int_ranges(_dialog):
            return {}

        @staticmethod
        def get_ai_flags(_dialog):
            return {}

        @staticmethod
        def get_attached_select_results(_dialog):
            return {}

        @staticmethod
        def get_multi_text_blank_modes(_dialog):
            return {}

        @staticmethod
        def get_multi_text_blank_int_ranges(_dialog):
            return {}

        @staticmethod
        def get_multi_text_blank_ai_flags(_dialog):
            return {}

        @staticmethod
        def get_dimensions(_dialog):
            return {}

        @staticmethod
        def get_bias_presets(_dialog):
            return {}

        def deleteLater(self):
            return None

    monkeypatch.setattr(entries_module, "QuestionWizardDialog", _AcceptedDialog)
    monkeypatch.setattr(entries_module, "isValid", lambda _dialog: True)
    monkeypatch.setattr(
        entries_module,
        "_WIZARD_DISTRIBUTION_RULES",
        ((lambda _dialog: {0: [3, 7]}, entries_module._apply_distribution_result),),
    )
    monkeypatch.setattr(entries_module, "_WIZARD_TEXT_RULES", ())
    monkeypatch.setattr(entries_module, "_WIZARD_META_RULES", ())

    selected_entries = [QuestionEntry("single", [1, 1])]
    assert (
        page.run_question_wizard(
            selected_entries,
            [SurveyQuestionMeta(num=1, title="Q1")],
        )
        is True
    )
    assert selected_entries[0].custom_weights == [3.0, 7.0]
    assert not hasattr(page, "entry_table")


def test_dashboard_start_and_summary_use_real_run_setup_surface(monkeypatch) -> None:
    page = _DashboardDouble()
    page.run_coordinator = SimpleNamespace(start=MagicMock(return_value=True))

    page._on_start_clicked(enable_reverse_fill=True)
    page.run_coordinator.start.assert_called_once_with(enable_reverse_fill=True)
    page.execution_panel.reset_for_new_run.assert_called_once_with(4)
    page.open_execution_step.assert_called_once_with()

    page.update_question_meta("问卷", 3)
    page.run_setup_panel.set_survey_summary.assert_called_once_with("问卷", 3)

    page.run_coordinator = None
    monkeypatch.setattr(run_actions_module, "log_action", lambda *_args, **_kwargs: None)
    page._on_start_clicked()
    assert page.toasts[-1] == ("运行编排器未初始化，无法开始执行", "error")
