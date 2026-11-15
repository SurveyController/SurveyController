from typing import Any

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QWidget

from software.core.config.schema import RuntimeConfig
from software.ui.controller.run_controller import RunController
from software.ui.pages.workbench.dashboard.event_binding import bind_dashboard_events
from software.ui.pages.workbench.dashboard.feedback import dashboard_toast
from software.ui.pages.workbench.dashboard.parts.config_io import (
    DashboardConfigIOMixin,
)
from software.ui.pages.workbench.dashboard.parts.entries import (
    DashboardEntriesMixin,
)
from software.ui.pages.workbench.dashboard.parts.run_actions import (
    DashboardRunActionsMixin,
)
from software.ui.pages.workbench.dashboard.parts.survey_parse import (
    DashboardSurveyParseMixin,
)
from software.ui.pages.workbench.dashboard.ui_builder import build_dashboard_page_ui
from software.ui.pages.workbench.session import WorkbenchState
from software.ui.pages.workbench.shared.clipboard import SurveyClipboardMixin
from software.ui.pages.workbench.strategy.page import QuestionStrategyPage
from software.ui.widgets.config_drawer import ConfigDrawer


class DashboardPage(
    SurveyClipboardMixin,
    DashboardSurveyParseMixin,
    DashboardConfigIOMixin,
    DashboardRunActionsMixin,
    DashboardEntriesMixin,
    QWidget,
):
    run_setup_panel: Any
    execution_panel: Any

    def __init__(
        self,
        controller: RunController,
        workbench_state: WorkbenchState,
        strategy_page: QuestionStrategyPage,
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.controller = controller
        self.workbench_state = workbench_state
        self.strategy_page = strategy_page
        self.run_coordinator = None
        self._open_wizard_after_parse = False
        self._progress_infobar = None
        self._survey_title = ""
        self._pending_restart = False
        self._is_closing = False
        self._clipboard_parse_ticket = 0
        self._inline_wizard = None
        self._build_ui()
        self.config_drawer = ConfigDrawer(self, self._load_config_from_path)
        self._bind_events()

    def set_run_coordinator(self, coordinator) -> None:
        self.run_coordinator = coordinator

    def present_parse_succeeded(self, info: list, title: str) -> None:
        self._on_survey_parsed(info, title)

    def present_parse_failed(self, message: str) -> None:
        self._on_survey_parse_failed(message)

    def apply_runtime_snapshot(self, snapshot: dict) -> None:
        self.run_setup_panel.render_runtime_snapshot(snapshot)
        self.execution_panel.apply_runtime_snapshot(snapshot)

    def apply_config(self, cfg: RuntimeConfig) -> None:
        with QSignalBlocker(self.url_edit):
            self.url_edit.setText(cfg.url)
        self.update_question_meta(cfg.survey_title or "", len(cfg.question_entries or []))
        self.run_setup_panel.apply_config(cfg)

    def on_run_state_changed(self, running: bool) -> None:
        self.execution_panel.on_run_state_changed(running)

    def update_status(self, text: str, current: int, target: int) -> None:
        self.execution_panel.update_status(text, current, target)

    def update_thread_progress(self, payload: dict) -> None:
        self.execution_panel.update_thread_progress(payload)

    def on_pause_state_changed(self, paused: bool, reason: str = "") -> None:
        self.execution_panel.on_pause_state_changed(paused, reason)

    def _build_ui(self):
        build_dashboard_page_ui(self)

    def _bind_events(self):
        bind_dashboard_events(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.config_drawer.sync_to_parent()

    def _toast(
        self,
        text: str,
        level: str = "info",
        duration: int = 2000,
        show_progress: bool = False,
    ):
        return dashboard_toast(
            self,
            text,
            level=level,
            duration=duration,
            show_progress=show_progress,
        )

    @staticmethod
    def _infobar_none_position():
        from qfluentwidgets import InfoBarPosition

        return InfoBarPosition.NONE
