from __future__ import annotations

import logging
from typing import Any

from surveycore.core.questions.utils import OPTION_FILL_AI_TOKEN

from software.application.run_plan import compile_run_plan
from software.core.config.schema import RuntimeConfig
from software.integrations.ai import get_ai_readiness_error
from software.logging.action_logger import log_action
from software.providers.common import normalize_survey_parse_url
from software.ui.pages.workbench.shared.run_feedback import (
    get_completion_notified,
    get_last_progress,
    set_completion_notified,
    set_last_progress,
)
from software.ui.pages.workbench.state import WorkbenchState

__all__ = ["WorkbenchRunCoordinator", "WorkbenchState"]


class WorkbenchRunCoordinator:
    def __init__(self, *, controller: Any, state: WorkbenchState, dashboard: Any) -> None:
        self.controller = controller
        self.state = state
        self.dashboard = dashboard
        self.reverse_fill_page: Any | None = None
        self._reverse_fill_target_override: int | None = None

    def bind_reverse_fill_page(self, page: Any) -> None:
        self.reverse_fill_page = page

    def has_question_entries(self) -> bool:
        return self.state.has_question_entries()

    def _uses_ai(self) -> bool:
        for entry in self.state.get_entries():
            if bool(getattr(entry, "ai_enabled", False)):
                return True
            if any(
                bool(flag) for flag in (getattr(entry, "multi_text_blank_ai_flags", None) or ())
            ):
                return True
            if any(
                str(value or "").strip() == OPTION_FILL_AI_TOKEN
                for value in (getattr(entry, "option_fill_texts", None) or ())
            ):
                return True
        return False

    def is_completed_run(self) -> bool:
        if self.reverse_fill_page is not None:
            return bool(
                get_completion_notified(self.reverse_fill_page)
                or get_last_progress(self.reverse_fill_page) >= 100
            )
        return bool(
            getattr(self.dashboard, "_completion_notified", False)
            or getattr(self.dashboard, "_last_progress", 0) >= 100
        )

    def set_reverse_fill_target(self, target: int) -> None:
        normalized_target = max(1, int(target or 1))
        self._reverse_fill_target_override = normalized_target

    def build_config(self) -> RuntimeConfig:
        config = self.state.snapshot()
        config.url = normalize_survey_parse_url(config.url)
        return config

    def start(self, *, enable_reverse_fill: bool = False) -> bool:
        dashboard = self.dashboard
        if getattr(self.controller, "running", False):
            if self.is_completed_run():
                dashboard._pending_restart = True
                self.controller.stop_run()
                log_action(
                    "RUN",
                    "restart_run",
                    "start_btn",
                    "dashboard",
                    result="queued",
                )
                dashboard._toast("正在重新开始，请稍候...", "info", 1200)
            return False

        plan = compile_run_plan(
            self.build_config(),
            question_entries=self.state.get_entries(),
            questions_info=self.state.questions_info,
        )
        cfg = plan.config
        cfg.reverse_fill_enabled = bool(
            enable_reverse_fill and str(getattr(cfg, "reverse_fill_source_path", "") or "").strip()
        )
        if enable_reverse_fill:
            cfg.threads = max(1, int(cfg.reverse_fill_threads or 1))
        if enable_reverse_fill and self._reverse_fill_target_override is not None:
            cfg.target = self._reverse_fill_target_override
        if not cfg.question_entries:
            log_action(
                "RUN",
                "start_run",
                "start_btn",
                "dashboard",
                result="blocked",
                level=logging.WARNING,
                payload={"reason": "no_question_entries"},
            )
            dashboard._toast(
                "未配置任何题目，无法开始执行（请先在'题目配置'页添加/配置题目）",
                "warning",
            )
            if self.reverse_fill_page is not None:
                self.reverse_fill_page._sync_start_button_state(running=False)
            return False

        if self._uses_ai():
            readiness_error = get_ai_readiness_error()
            if readiness_error:
                log_action(
                    "RUN",
                    "start_run",
                    "start_btn",
                    "dashboard",
                    result="blocked",
                    level=logging.WARNING,
                    payload={"reason": "ai_config_incomplete"},
                )
                dashboard._toast(f"请先补全 AI 配置：{readiness_error}", "warning")
                return False

        if self.is_completed_run():
            if self.reverse_fill_page is not None:
                self.reverse_fill_page.progress_bar.setValue(0)
                self.reverse_fill_page.progress_pct.setText("0%")
                self.reverse_fill_page.status_label.setText(
                    f"已提交 0/{cfg.target} 份 | 提交连续失败 0 次"
                )
                set_last_progress(self.reverse_fill_page, 0)
                set_completion_notified(self.reverse_fill_page, False)

        self.controller.start_run(cfg)
        log_action(
            "RUN",
            "start_run",
            "start_btn",
            "dashboard",
            result="started",
            payload={
                "target": cfg.target,
                "threads": cfg.threads,
                "reverse_fill_enabled": cfg.reverse_fill_enabled,
            },
        )
        return True

    def start_reverse_fill(self) -> bool:
        return self.start(enable_reverse_fill=True)

    def resume(self) -> None:
        if self.reverse_fill_page is not None:
            self.reverse_fill_page._on_resume_clicked()
