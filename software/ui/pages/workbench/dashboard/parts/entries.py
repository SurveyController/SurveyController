from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence

from PySide6.QtWidgets import QDialog
from shiboken6 import isValid

from surveycore.core.questions.config import QuestionEntry
from surveycore.providers.contracts import SurveyQuestionMeta
from software.ui.pages.workbench.question_editor.wizard_dialog import (
    QuestionWizardBase,
    QuestionWizardDialog,
    QuestionWizardPanel,
)

WizardResultGetter = Callable[[QuestionWizardBase], Dict[int, Any]]
WizardEntryApplier = Callable[[QuestionEntry, Any], None]
WizardApplyRule = tuple[WizardResultGetter, WizardEntryApplier]


def _normalize_wizard_weights(raw: Any) -> Any:
    if isinstance(raw, list) and any(isinstance(item, (list, tuple)) for item in raw):
        cleaned: List[List[float]] = []
        for row in raw:
            if not isinstance(row, (list, tuple)):
                continue
            cleaned.append([float(max(0, value)) for value in row])
        return cleaned
    if isinstance(raw, list):
        return [float(max(0, value)) for value in raw]
    return raw


def _apply_result_updates(
    entries: List[QuestionEntry],
    updates: Dict[int, Any],
    applier: WizardEntryApplier,
) -> None:
    for idx, value in updates.items():
        if 0 <= idx < len(entries):
            applier(entries[idx], value)


def _apply_distribution_result(entry: QuestionEntry, raw_weights: Any) -> None:
    normalized = _normalize_wizard_weights(raw_weights)
    entry.custom_weights = normalized
    entry.probabilities = normalized
    entry.distribution_mode = "custom"


def _apply_text_result(entry: QuestionEntry, texts: Any) -> None:
    entry.texts = texts


def _apply_location_result(entry: QuestionEntry, parts: Any) -> None:
    entry.location_parts = [str(item or "").strip() for item in list(parts or [])[:3]]


def _apply_option_fill_result(entry: QuestionEntry, option_fill_texts: Any) -> None:
    if entry.question_type not in ("single", "multiple", "dropdown"):
        return
    entry.option_fill_texts = (
        option_fill_texts if any(text for text in option_fill_texts if text) else None
    )


def _apply_text_random_mode_result(entry: QuestionEntry, random_mode: Any) -> None:
    entry.text_random_mode = str(random_mode or "none") if entry.question_type == "text" else "none"


def _apply_text_random_int_range_result(entry: QuestionEntry, int_range: Any) -> None:
    entry.text_random_int_range = int_range if entry.question_type == "text" else []


def _apply_ai_flag_result(entry: QuestionEntry, enabled: Any) -> None:
    entry.ai_enabled = bool(enabled) if entry.question_type in ("text", "multi_text") else False


def _apply_attached_select_result(entry: QuestionEntry, attached_configs: Any) -> None:
    entry.attached_option_selects = attached_configs


def _apply_multi_text_blank_modes_result(entry: QuestionEntry, modes: Any) -> None:
    entry.multi_text_blank_modes = modes


def _apply_multi_text_blank_int_ranges_result(entry: QuestionEntry, int_ranges: Any) -> None:
    entry.multi_text_blank_int_ranges = int_ranges


def _apply_multi_text_blank_ai_flags_result(entry: QuestionEntry, flags: Any) -> None:
    entry.multi_text_blank_ai_flags = flags


def _apply_dimension_result(entry: QuestionEntry, dimension: Any) -> None:
    entry.dimension = dimension


def _apply_bias_preset_result(entry: QuestionEntry, bias: Any) -> None:
    entry.psycho_bias = bias


_WIZARD_DISTRIBUTION_RULES: Sequence[WizardApplyRule] = (
    (QuestionWizardDialog.get_results, _apply_distribution_result),
)

_WIZARD_TEXT_RULES: Sequence[WizardApplyRule] = (
    (QuestionWizardDialog.get_text_results, _apply_text_result),
    (QuestionWizardDialog.get_location_results, _apply_location_result),
    (QuestionWizardDialog.get_option_fill_results, _apply_option_fill_result),
    (QuestionWizardDialog.get_text_random_modes, _apply_text_random_mode_result),
    (QuestionWizardDialog.get_text_random_int_ranges, _apply_text_random_int_range_result),
    (QuestionWizardDialog.get_ai_flags, _apply_ai_flag_result),
    (QuestionWizardDialog.get_attached_select_results, _apply_attached_select_result),
    (QuestionWizardDialog.get_multi_text_blank_modes, _apply_multi_text_blank_modes_result),
    (
        QuestionWizardDialog.get_multi_text_blank_int_ranges,
        _apply_multi_text_blank_int_ranges_result,
    ),
    (QuestionWizardDialog.get_multi_text_blank_ai_flags, _apply_multi_text_blank_ai_flags_result),
)

_WIZARD_META_RULES: Sequence[WizardApplyRule] = (
    (QuestionWizardDialog.get_dimensions, _apply_dimension_result),
    (QuestionWizardDialog.get_bias_presets, _apply_bias_preset_result),
)


class DashboardEntriesMixin:
    if TYPE_CHECKING:
        workbench_state: Any
        _toast: Any
        _survey_title: Any
        controller: Any

    def _apply_wizard_results(self, entries: List[QuestionEntry], dlg: QuestionWizardBase) -> None:
        for rules in (_WIZARD_DISTRIBUTION_RULES, _WIZARD_TEXT_RULES, _WIZARD_META_RULES):
            for getter, applier in rules:
                _apply_result_updates(entries, getter(dlg), applier)

    def close_inline_question_wizard(self, *, return_home: bool = True) -> None:
        panel = getattr(self, "_inline_wizard", None)
        self._inline_wizard = None
        wizard_host = getattr(self, "wizard_host", None)
        main_stack = getattr(self, "main_stack", None)
        home_view = getattr(self, "home_view", None)
        if wizard_host is not None and wizard_host.layout() is not None and panel is not None:
            wizard_host.layout().removeWidget(panel)
        if panel is not None:
            try:
                if isValid(panel):
                    panel.hide()
                    panel.deleteLater()
            except Exception:
                pass
        if return_home and main_stack is not None and home_view is not None:
            main_stack.setCurrentWidget(home_view, isBack=True)

    def return_to_home_view(self) -> None:
        self.close_inline_question_wizard(return_home=False)
        main_stack = getattr(self, "main_stack", None)
        home_view = getattr(self, "home_view", None)
        if main_stack is not None and home_view is not None:
            main_stack.setCurrentWidget(home_view, isBack=True)

    def open_run_setup_step(self, survey_title: str = "", question_count: int = 0) -> None:
        main_stack = getattr(self, "main_stack", None)
        run_setup_host = getattr(self, "run_setup_host", None)
        run_setup_panel = getattr(self, "run_setup_panel", None)
        if main_stack is None or run_setup_host is None or run_setup_panel is None:
            self.return_to_home_view()
            return
        run_setup_panel.set_survey_summary(survey_title, question_count)
        run_setup_panel.render_runtime_snapshot(self.controller.get_runtime_snapshot())
        main_stack.setCurrentWidget(run_setup_host, isBack=False)

    def open_execution_step(self) -> None:
        main_stack = getattr(self, "main_stack", None)
        execution_host = getattr(self, "execution_host", None)
        if main_stack is None or execution_host is None:
            return
        main_stack.setCurrentWidget(execution_host, isBack=False)

    def return_to_run_setup_step(self) -> None:
        main_stack = getattr(self, "main_stack", None)
        run_setup_host = getattr(self, "run_setup_host", None)
        run_setup_panel = getattr(self, "run_setup_panel", None)
        if main_stack is None or run_setup_host is None:
            self.return_to_home_view()
            return
        if run_setup_panel is not None:
            run_setup_panel.render_runtime_snapshot(self.controller.get_runtime_snapshot())
        main_stack.setCurrentWidget(run_setup_host, isBack=True)

    def _reopen_inline_wizard_from_run_setup(self) -> None:
        entries = self.workbench_state.get_entries()
        info = self.workbench_state.entry_questions_info or []
        if not entries:
            self._toast("当前没有可编辑的题目", "warning")
            self.return_to_home_view()
            return
        title = getattr(self, "_survey_title", "") or ""

        def _after_reedit(accepted: bool) -> None:
            if not accepted:
                return
            self.workbench_state.set_questions(info, entries)

        self.open_inline_question_wizard(
            entries,
            info,
            title,
            on_finished=_after_reedit,
            is_back=True,
        )

    def open_inline_question_wizard(
        self,
        entries: List[QuestionEntry],
        info: List[SurveyQuestionMeta | Dict[str, Any]],
        survey_title: Optional[str] = None,
        *,
        on_finished: Optional[Callable[[bool], None]] = None,
        pop_out_on_cancel: bool = True,
        is_back: bool = False,
    ) -> None:
        if not entries:
            self._toast("请先解析问卷或手动添加题目", "warning")
            if callable(on_finished):
                on_finished(False)
            return
        wizard_host = getattr(self, "wizard_host", None)
        main_stack = getattr(self, "main_stack", None)
        if wizard_host is None or main_stack is None or wizard_host.layout() is None:
            accepted = self.run_question_wizard(entries, info, survey_title)
            if callable(on_finished):
                on_finished(accepted)
            return

        self.close_inline_question_wizard(return_home=False)
        title = survey_title if survey_title is not None else self._survey_title
        setup_panel = getattr(self, "run_setup_panel", None)
        reliability_mode_enabled = (
            setup_panel.get_reliability_mode_enabled() if setup_panel is not None else True
        )
        media_fetcher = getattr(getattr(self, "controller", None), "fetch_question_media", None)
        panel = QuestionWizardPanel(
            entries,
            info,
            title,
            parent=wizard_host,
            reliability_mode_enabled=reliability_mode_enabled,
            media_fetcher=media_fetcher,
        )
        self._inline_wizard = panel
        wizard_host.layout().addWidget(panel)
        main_stack.setCurrentWidget(wizard_host, isBack=is_back)

        def _finish(accepted: bool) -> None:
            if getattr(self, "_inline_wizard", None) is not panel:
                return
            applied = False
            try:
                if accepted:
                    self._apply_wizard_results(entries, panel)
                    applied = True
            except ValueError as exc:
                self._toast(f"配置应用失败：{exc}", "error")
                applied = False
            finally:
                self.close_inline_question_wizard(return_home=not applied and pop_out_on_cancel)
            if callable(on_finished):
                on_finished(applied)
            if applied:
                self.open_run_setup_step(title, len(entries))

        panel.accepted.connect(lambda: _finish(True))
        panel.rejected.connect(lambda: _finish(False))

    def run_question_wizard(
        self,
        entries: List[QuestionEntry],
        info: List[SurveyQuestionMeta | Dict[str, Any]],
        survey_title: Optional[str] = None,
    ) -> bool:
        if not entries:
            self._toast("请先解析问卷或手动添加题目", "warning")
            return False
        title = survey_title if survey_title is not None else self._survey_title
        setup_panel = getattr(self, "run_setup_panel", None)
        reliability_mode_enabled = (
            setup_panel.get_reliability_mode_enabled() if setup_panel is not None else True
        )
        media_fetcher = getattr(getattr(self, "controller", None), "fetch_question_media", None)
        dlg = QuestionWizardDialog(
            entries,
            info,
            title,
            parent=self,
            reliability_mode_enabled=reliability_mode_enabled,
            media_fetcher=media_fetcher,
        )
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        try:
            if accepted:
                self._apply_wizard_results(entries, dlg)
                return True
            return False
        except ValueError as exc:
            self._toast(f"配置应用失败：{exc}", "error")
            return False
        finally:
            try:
                if isValid(dlg):
                    dlg.deleteLater()
            except Exception:
                pass
