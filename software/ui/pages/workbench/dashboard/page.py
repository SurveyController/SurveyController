from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from software.ui.pages.workbench.dashboard.event_binding import bind_dashboard_events
from software.ui.pages.workbench.dashboard.feedback import dashboard_toast
from software.ui.pages.workbench.dashboard.ui_builder import build_dashboard_page_ui
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
from software.ui.pages.workbench.shared.clipboard import SurveyClipboardMixin
from software.ui.widgets.config_drawer import ConfigDrawer
from software.ui.controller.run_controller import RunController
from software.core.config.schema import RuntimeConfig
from software.ui.pages.workbench.runtime_panel.main import RuntimePage
from software.ui.pages.workbench.strategy.page import QuestionStrategyPage
from software.ui.pages.workbench.session import WorkbenchState

class DashboardPage(
    SurveyClipboardMixin,
    DashboardSurveyParseMixin,
    DashboardConfigIOMixin,
    DashboardRunActionsMixin,
    DashboardEntriesMixin,
    QWidget,
):

    def __init__(
        self,
        controller: RunController,
        workbench_state: WorkbenchState,
        runtime_page: RuntimePage,
        strategy_page: QuestionStrategyPage,
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.controller = controller
        self.workbench_state = workbench_state
        self.runtime_page = runtime_page
        self.strategy_page = strategy_page
        self.run_coordinator = None
        self.config_builder: Optional[Callable[[], RuntimeConfig]] = None
        self._open_wizard_after_parse = False
        self._progress_infobar = None
        self._survey_title = ""
        self._pending_restart = False
        self._is_closing = False
        self._clipboard_parse_ticket = 0
        self._build_ui()
        self.config_drawer = ConfigDrawer(self, self._load_config_from_path)
        self._bind_events()

    def set_run_coordinator(self, coordinator) -> None:
        self.run_coordinator = coordinator

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
