from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from software.logging.action_logger import log_action


class DashboardRunActionsMixin:
    if TYPE_CHECKING:
        run_coordinator: Any
        workbench_state: Any
        run_setup_panel: Any
        execution_panel: Any
        _survey_title: str

        def _toast(self, text: str, level: str = "info") -> Any: ...
        def open_execution_step(self) -> None: ...

    def _on_start_clicked(self, enable_reverse_fill: bool = False) -> None:
        if self.run_coordinator is None:
            log_action(
                "RUN",
                "start_run",
                "start_btn",
                "dashboard",
                result="blocked",
                level=logging.ERROR,
            )
            self._toast("运行编排器未初始化，无法开始执行", "error")
            return
        if self.run_coordinator.start(enable_reverse_fill=enable_reverse_fill):
            self.execution_panel.reset_for_new_run(self.workbench_state.snapshot().target)
            self.open_execution_step()

    def update_question_meta(self, title: str, count: int) -> None:
        self._survey_title = title or ""
        self.run_setup_panel.set_survey_summary(title, count)
