from __future__ import annotations

import copy
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Slot
from surveycore.providers.contracts import SurveyQuestionMeta, ensure_survey_question_metas

from software.core.config.codec import build_runtime_config_snapshot
from software.core.config.schema import RuntimeConfig
from software.logging.action_logger import log_action
from software.ui.pages.workbench.dashboard.page import DashboardPage
from software.ui.pages.workbench.reverse_fill.page import ReverseFillPage
from software.ui.pages.workbench.session import (
    WorkbenchRunCoordinator,
    WorkbenchState,
)
from software.ui.pages.workbench.strategy.page import QuestionStrategyPage


class WorkbenchPresenter:
    def __init__(self, *, controller: Any, host: Any) -> None:
        self.controller = controller
        self.host = host
        self._last_running_state: bool | None = None
        self._last_pause_state: tuple[bool, str] | None = None
        self.state = WorkbenchState(host)
        self.strategy_page = QuestionStrategyPage(host)
        self.dashboard = DashboardPage(
            controller,
            self.state,
            self.strategy_page,
            host,
        )
        self.run_coordinator = WorkbenchRunCoordinator(
            controller=controller,
            state=self.state,
            dashboard=self.dashboard,
        )
        self.dashboard.set_run_coordinator(self.run_coordinator)
        self.reverse_fill_page = ReverseFillPage(controller, host)
        self.run_coordinator.bind_reverse_fill_page(self.reverse_fill_page)
        self.reverse_fill_page.set_run_coordinator(self.run_coordinator)
        self._configure_pages()
        self._bind_workbench_signals()

    def _configure_pages(self) -> None:
        self.dashboard.setObjectName("dashboard")
        self.strategy_page.setObjectName("strategy")
        self.reverse_fill_page.setObjectName("reverse_fill")
        self.reverse_fill_page.set_open_wizard_handler(self.open_reverse_fill_wizard)

    def _bind_workbench_signals(self) -> None:
        self.reverse_fill_page.surveyUrlChanged.connect(self.state.set_url)
        self.dashboard.url_edit.textChanged.connect(self.state.set_url)
        self.state.configChanged.connect(self._render_draft_config)
        self.strategy_page.strategyChanged.connect(self._store_strategy_config)
        self.reverse_fill_page.configurationChanged.connect(
            lambda changes: self.state.update_settings(**changes)
        )
        self.controller.surveySnapshotChanged.connect(
            self.on_survey_snapshot_changed,
            Qt.ConnectionType.QueuedConnection,
        )
        self.controller.runtimeSnapshotChanged.connect(
            self.on_runtime_snapshot_changed,
            Qt.ConnectionType.QueuedConnection,
        )

    def apply_config(self, cfg: RuntimeConfig) -> None:
        self.state.apply_config(cfg)

    def _render_draft_config(
        self,
        cfg: RuntimeConfig,
        changed_fields: frozenset[str],
    ) -> None:
        all_fields = frozenset(cfg.__dataclass_fields__)
        if changed_fields == all_fields:
            self.dashboard.apply_config(cfg)
            self.reverse_fill_page.apply_config(cfg)
            self.strategy_page.set_questions_info(cfg.questions_info or [])
            self.strategy_page.set_entries(self.state.entries, self.state.entry_questions_info)
            self.strategy_page.set_rules(cfg.answer_rules or [])
            self.strategy_page.set_dimension_groups(cfg.dimension_groups or [])
            self.dashboard.update_question_meta(
                cfg.survey_title or "", len(cfg.question_entries or [])
            )
            self.sync_reverse_fill_context()
            return

        if "url" in changed_fields:
            self._render_survey_url(cfg.url)
        if changed_fields & {
            "survey_title",
            "survey_provider",
            "question_entries",
            "questions_info",
        }:
            self.dashboard.update_question_meta(cfg.survey_title, len(cfg.question_entries or []))
            self.strategy_page.set_questions_info(cfg.questions_info or [])
            self.strategy_page.set_entries(self.state.entries, self.state.entry_questions_info)
            self.sync_reverse_fill_context()
        if "random_ip_enabled" in changed_fields:
            self.reverse_fill_page.apply_runtime_settings(
                {"random_ip_enabled": cfg.random_ip_enabled}
            )
        if "answer_rules" in changed_fields:
            self.strategy_page.set_rules(cfg.answer_rules or [])
        if "dimension_groups" in changed_fields:
            self.strategy_page.set_dimension_groups(cfg.dimension_groups or [])

    def _store_strategy_config(self) -> None:
        self.state.update_settings(
            question_entries=self.strategy_page.get_entries(),
            answer_rules=self.strategy_page.get_rules(),
            dimension_groups=self.strategy_page.get_dimension_groups(),
        )

    def _render_survey_url(self, url: str) -> None:
        text = str(url or "").strip()
        for editor in (self.dashboard.url_edit, self.reverse_fill_page.url_edit):
            if str(editor.text() or "").strip() != text:
                with QSignalBlocker(editor):
                    editor.setText(text)
        self.reverse_fill_page._refresh_preview()

    def load_saved_config(self, *, strict: bool = False) -> RuntimeConfig:
        cfg = self.controller.load_saved_config(strict=strict)
        self.apply_config(cfg)
        self.controller.refresh_random_ip_counter()
        return cfg

    def load_config_from_path(self, path: str) -> RuntimeConfig:
        cfg = self.controller.load_saved_config(path, strict=True)
        self.apply_config(cfg)
        self.controller.refresh_random_ip_counter()
        return cfg

    def build_current_config(self) -> RuntimeConfig:
        return self.state.snapshot()

    def build_current_config_snapshot(self) -> RuntimeConfig:
        return build_runtime_config_snapshot(self.state.snapshot())

    @Slot(dict)
    def on_survey_snapshot_changed(self, snapshot: dict[str, Any]) -> None:
        phase = str((snapshot or {}).get("phase") or "")
        parsed_url = str((snapshot or {}).get("url") or "")
        self.state.set_url(parsed_url)
        if phase == "error":
            self.on_survey_parse_failed(str((snapshot or {}).get("parse_error") or ""))
            return
        if phase in {"idle", "parsing"}:
            self._clear_parsed_questions_state()
            return
        if phase != "ready":
            return

        questions = ensure_survey_question_metas((snapshot or {}).get("questions_info") or [])
        parsed_title = str((snapshot or {}).get("survey_title") or "") or "问卷"
        entries = list((snapshot or {}).get("question_entries") or [])
        self.state.update_settings(
            url=parsed_url,
            survey_title=parsed_title,
            survey_provider=str((snapshot or {}).get("survey_provider") or "wjx"),
        )
        self.dashboard.present_parse_succeeded(questions, parsed_title)
        self.reverse_fill_page.present_parse_succeeded(questions, parsed_title)
        if getattr(self.dashboard, "_open_wizard_after_parse", False):
            self.dashboard._open_wizard_after_parse = False
            info_snapshot = copy.deepcopy(questions)
            QTimer.singleShot(
                0,
                lambda: self.open_parse_wizard_after_parse(
                    info_snapshot, parsed_title, entries=entries
                ),
            )
            return
        self.state.set_questions(questions, entries)
        self.dashboard.update_question_meta(parsed_title, len(entries))
        self.sync_reverse_fill_context()

    @Slot(str)
    def on_survey_parse_failed(self, msg: str) -> None:
        text = str(msg or "").strip()
        self._clear_parsed_questions_state()
        self.dashboard.present_parse_failed(text)
        self.reverse_fill_page.present_parse_failed(text)
        self.dashboard._open_wizard_after_parse = False

    def _clear_parsed_questions_state(self) -> None:
        self.state.update_settings(
            question_entries=[],
            questions_info=[],
            survey_title="",
            dimension_groups=[],
        )

    @Slot(dict)
    def on_runtime_snapshot_changed(self, snapshot: dict[str, Any]) -> None:
        runtime_settings = (snapshot or {}).get("settings") or {}
        if "random_ip_enabled" in runtime_settings:
            self.state.update_settings(
                random_ip_enabled=bool(runtime_settings["random_ip_enabled"])
            )
        running = bool((snapshot or {}).get("running"))
        paused = bool((snapshot or {}).get("paused"))
        pause_reason = str((snapshot or {}).get("status_text") or "")
        progress = (snapshot or {}).get("progress") or {}
        random_ip = (snapshot or {}).get("random_ip") or {}
        if self._last_running_state != running:
            was_running = self._last_running_state
            self._last_running_state = running
            self.reverse_fill_page.on_run_state_changed(running)
            self.dashboard.on_run_state_changed(running)
            if was_running is not True and running:
                self.dashboard.open_execution_step()
                self.host.switchTo(self.dashboard)
            if was_running and not running and self.dashboard._pending_restart:
                self.dashboard._pending_restart = False
                QTimer.singleShot(0, self.run_coordinator.start)
        self.reverse_fill_page.set_random_ip_loading(
            bool(random_ip.get("loading")),
            str(random_ip.get("loading_message") or ""),
        )
        self.reverse_fill_page.update_status(
            str((snapshot or {}).get("status_text") or ""),
            int(progress.get("current") or 0),
            int(progress.get("target") or 0),
        )
        self.dashboard.apply_runtime_snapshot(snapshot or {})
        pause_state = (paused, pause_reason if paused else "")
        if self._last_pause_state != pause_state:
            self._last_pause_state = pause_state
            self.reverse_fill_page.on_pause_state_changed(*pause_state)
            self.dashboard.on_pause_state_changed(*pause_state)

    def sync_reverse_fill_context(self) -> None:
        self.reverse_fill_page.set_question_context(
            self.state.questions_info,
            self.state.get_entries(),
            survey_title=self.state.snapshot().survey_title,
            survey_provider=self.state.snapshot().survey_provider,
        )

    def open_reverse_fill_wizard(self, issue_question_nums: list[int]) -> None:
        info = list(self.state.questions_info or [])
        if not info:
            self.host._toast("当前还没有解析出题目，无法打开配置向导。", "warning")
            return
        issue_nums = {int(num) for num in list(issue_question_nums or []) if int(num) > 0}
        if not issue_nums:
            self.host._toast("当前没有需要处理的异常题目。", "warning")
            return
        self.open_parse_wizard_after_parse(
            copy.deepcopy(info),
            str(self.state.snapshot().survey_title or "问卷"),
            issue_question_nums=sorted(issue_nums),
        )

    def open_parse_wizard_after_parse(
        self,
        info: Sequence[SurveyQuestionMeta | Mapping[str, Any]],
        parsed_title: str,
        *,
        issue_question_nums: list[int] | None = None,
        entries: Sequence[Any] | None = None,
    ) -> None:
        normalized_info = ensure_survey_question_metas(info or [])

        def _finalize_parse_wizard(accepted: bool) -> None:
            if accepted:
                nonlocal pending_entries
                if selected_issue_nums:
                    updated_entries_by_num = {
                        int(getattr(entry, "question_num", 0) or 0): entry
                        for entry in selected_entries
                        if int(getattr(entry, "question_num", 0) or 0) > 0
                    }
                    merged_entries = []
                    for entry in pending_entries:
                        question_num = int(getattr(entry, "question_num", 0) or 0)
                        merged_entries.append(
                            copy.deepcopy(updated_entries_by_num.get(question_num, entry))
                        )
                    pending_entries = merged_entries
                self.state.set_questions(normalized_info, pending_entries)
                log_action(
                    "UI",
                    "open_parse_wizard",
                    "question_wizard",
                    "main_window",
                    result="accepted",
                    payload={"question_count": len(normalized_info)},
                )
                if not selected_issue_nums:
                    self.dashboard._toast(
                        f"已完成问卷配置（共 {len(pending_entries)} 题）", "success"
                    )
                return

            current_entries = self.state.get_entries()
            self.dashboard.update_question_meta(parsed_title, len(current_entries))
            log_action(
                "UI",
                "open_parse_wizard",
                "question_wizard",
                "main_window",
                result="cancelled",
                payload={"question_count": len(normalized_info)},
            )
            self.host._toast("已取消自动配置，保留原有题目设置", "warning")

        try:
            pending_entries = (
                self.state.get_entries() if entries is None else copy.deepcopy(list(entries))
            )
            selected_info: list[SurveyQuestionMeta | dict[str, Any]] = list(
                copy.deepcopy(normalized_info)
            )
            selected_entries = pending_entries
            selected_issue_nums = {
                int(num) for num in list(issue_question_nums or []) if int(num) > 0
            }
            if selected_issue_nums:
                info_by_num = {int(getattr(item, "num", 0) or 0): item for item in selected_info}
                entry_by_num = {
                    int(getattr(entry, "question_num", 0) or 0): entry
                    for entry in selected_entries
                    if int(getattr(entry, "question_num", 0) or 0) > 0
                }
                selected_info = [
                    copy.deepcopy(info_by_num[num])
                    for num in selected_issue_nums
                    if num in info_by_num
                ]
                selected_entries = [
                    copy.deepcopy(entry_by_num[num])
                    for num in selected_issue_nums
                    if num in entry_by_num
                ]
                if not selected_info or not selected_entries:
                    self.host._toast(
                        "异常题目配置数据不完整，暂时无法打开配置向导。",
                        "warning",
                    )
                    return
            if not selected_issue_nums:
                self.dashboard.open_inline_question_wizard(
                    selected_entries,
                    selected_info,
                    parsed_title,
                    on_finished=_finalize_parse_wizard,
                )
                return
            accepted = self.dashboard.run_question_wizard(
                selected_entries, selected_info, parsed_title
            )
        except Exception as exc:
            logging.exception("自动配置向导打开失败")
            log_action(
                "UI",
                "open_parse_wizard",
                "question_wizard",
                "main_window",
                result="failed",
                level=logging.ERROR,
                detail=exc,
                payload={"question_count": len(normalized_info)},
            )
            current_entries = self.state.get_entries()
            self.dashboard.update_question_meta(parsed_title, len(current_entries))
            self.dashboard._toast(
                "自动配置向导打开失败，已保留原有题目设置；详细原因已写入日志",
                "error",
                duration=4200,
            )
            return

        _finalize_parse_wizard(accepted)
