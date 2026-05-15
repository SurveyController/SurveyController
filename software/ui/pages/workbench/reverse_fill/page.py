"""问卷星 Excel 反填管理页。"""

from __future__ import annotations

import copy
import logging
import os
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Sequence

from PySide6.QtCore import QEvent, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QToolButton,
    QTableWidgetItem,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    InfoBar,
    InfoBarPosition,
    IndeterminateProgressRing,
    LineEdit,
    PushButton,
    PrimaryPushButton,
    ProgressBar,
    StrongBodyLabel,
    TableWidget,
)

from software.core.reverse_fill.schema import (
    REVERSE_FILL_FORMAT_AUTO,
    REVERSE_FILL_FORMAT_WJX_SCORE,
    REVERSE_FILL_FORMAT_WJX_SEQUENCE,
    REVERSE_FILL_FORMAT_WJX_TEXT,
    ReverseFillSpec,
    reverse_fill_format_label,
)
from software.core.reverse_fill.validation import build_reverse_fill_spec
from software.io.config import RuntimeConfig
from software.logging.action_logger import log_action
from software.logging.log_utils import log_suppressed_exception
from software.providers.common import (
    SURVEY_PROVIDER_WJX,
    normalize_survey_provider,
)
from software.providers.common import (
    SURVEY_PROVIDER_CREDAMO,
    SURVEY_PROVIDER_QQ,
    detect_survey_provider,
    is_supported_survey_url,
    is_wjx_survey_url,
)
from software.providers.contracts import (
    SurveyQuestionMeta,
    ensure_survey_question_metas,
)
from software.ui.helpers.message_bar import replace_message_bar, show_message_bar
from software.ui.pages.workbench.reverse_fill.logic import (
    actionable_issue_question_nums,
    build_plan_rows,
    is_supported_excel_path,
    iter_supported_drop_paths,
)
from software.ui.pages.workbench.reverse_fill.ui_builder import build_reverse_fill_page_ui
from software.ui.pages.workbench.shared.clipboard import SurveyClipboardMixin

if TYPE_CHECKING:
    from software.ui.controller.run_controller import RunController
    from software.ui.pages.workbench.shared.random_ip_toggle_row import RandomIpToggleRow
    from software.ui.pages.workbench.shared.survey_entry_card import SurveyEntryCard
    from software.ui.widgets.no_wheel import NoWheelSpinBox
    from qfluentwidgets import (
        IndeterminateProgressBar,
        InfoBadge,
        ScrollArea,
        SimpleCardWidget,
        TogglePushButton,
    )


_FORMAT_CHOICES = [
    (REVERSE_FILL_FORMAT_AUTO, "自动识别 (推荐)"),
    (REVERSE_FILL_FORMAT_WJX_SEQUENCE, "问卷星按序号"),
    (REVERSE_FILL_FORMAT_WJX_SCORE, "问卷星按分数"),
    (REVERSE_FILL_FORMAT_WJX_TEXT, "问卷星按文本"),
]


class ReverseFillPage(SurveyClipboardMixin, QWidget):
    """独立的反填数据源页。"""

    surveyUrlChanged = Signal(str)
    scroll_area: "ScrollArea"
    view: QWidget
    link_card: "SurveyEntryCard"
    file_panel: "SimpleCardWidget"
    table_panel: "SimpleCardWidget"
    preview_badge: "InfoBadge"
    qr_btn: QToolButton
    url_edit: LineEdit
    file_edit: LineEdit
    browse_btn: "PushButton"
    open_wizard_btn: PrimaryPushButton
    reverse_fill_threads_spin: "NoWheelSpinBox"
    random_ip_row: "RandomIpToggleRow"
    random_ip_cb: "TogglePushButton"
    random_ip_loading_ring: IndeterminateProgressRing
    random_ip_loading_label: CaptionLabel
    detected_format_label: StrongBodyLabel | CaptionLabel
    state_hint_label: CaptionLabel
    mapping_table: TableWidget
    status_label: StrongBodyLabel
    progress_bar: ProgressBar
    progress_indeterminate_bar: "IndeterminateProgressBar"
    progress_pct: StrongBodyLabel
    start_btn: PrimaryPushButton
    resume_btn: PrimaryPushButton
    stop_btn: "PushButton"

    def __init__(self, controller: "RunController", parent=None):
        super().__init__(parent)
        self.controller = controller
        self._questions_info: List[SurveyQuestionMeta] = []
        self._question_entries: List[Any] = []
        self._survey_provider: str = ""
        self._survey_title: str = ""
        self._parsed_url: str = ""
        self._reverse_fill_threads_value: int = 1
        self._selected_format_value: str = REVERSE_FILL_FORMAT_AUTO
        self._start_row_value: int = 1
        self._last_spec: Optional[ReverseFillSpec] = None
        self._last_error: str = ""
        self._open_wizard_handler: Optional[Callable[[List[int]], None]] = None
        self._run_coordinator: Optional[Any] = None
        self._issue_question_nums: List[int] = []
        self._clipboard_parse_ticket = 0
        self._parse_requested_from_reverse_fill = False
        self._progress_infobar: Optional[InfoBar] = None
        self._completion_notified = False
        self._show_end_toast_after_cleanup = False
        self._last_progress = 0
        self._last_pause_reason = ""
        self._main_progress_indeterminate = False

        self.setObjectName("reverseFillPage")

        build_reverse_fill_page_ui(self)
        self._bind_events()
        self._refresh_preview()
        self._sync_start_button_state()

    def _bind_events(self) -> None:
        self.qr_btn.clicked.connect(self._on_qr_clicked)
        self.url_edit.returnPressed.connect(self._on_parse_clicked)
        self.url_edit.textChanged.connect(self._on_url_text_changed)
        self.file_edit.editingFinished.connect(self._refresh_preview)
        self.reverse_fill_threads_spin.valueChanged.connect(self._on_reverse_fill_threads_changed)
        self.random_ip_cb.toggled.connect(self._on_random_ip_toggled)
        self.browse_btn.clicked.connect(self._browse_excel_file)
        self.open_wizard_btn.clicked.connect(self._open_wizard)
        clipboard = QApplication.clipboard()
        clipboard.dataChanged.connect(self._on_clipboard_changed)
        self.controller.surveyParsed.connect(self._on_survey_parsed)
        self.controller.surveyParseFailed.connect(self._on_survey_parse_failed)
        self.controller.runtimeUiStateChanged.connect(self._apply_runtime_ui_state)
        self.controller.randomIpLoadingChanged.connect(self.set_random_ip_loading)
        self._apply_runtime_ui_state(self.controller.get_runtime_ui_state())
        self.start_btn.clicked.connect(self._on_start_clicked)
        self.resume_btn.clicked.connect(self._on_resume_clicked)
        self.stop_btn.clicked.connect(self.controller.stop_run)

    def set_open_wizard_handler(self, handler: Optional[Callable[[List[int]], None]]) -> None:
        self._open_wizard_handler = handler

    def set_run_coordinator(self, coordinator: Any) -> None:
        self._run_coordinator = coordinator

    def set_question_context(
        self,
        questions_info: Sequence[SurveyQuestionMeta],
        question_entries: Sequence[Any],
        *,
        survey_title: str = "",
        survey_provider: str = "",
    ) -> None:
        self._questions_info = ensure_survey_question_metas(questions_info or [])
        self._question_entries = list(copy.deepcopy(list(question_entries or [])))
        self._survey_title = str(survey_title or "").strip()
        self._survey_provider = str(survey_provider or "").strip()
        if self._questions_info:
            self._parsed_url = self.url_edit.text().strip()
        self._refresh_preview()
        self._sync_start_button_state()

    def update_config(self, cfg: RuntimeConfig) -> None:
        cfg.reverse_fill_source_path = self.file_edit.text().strip()
        cfg.reverse_fill_enabled = bool(cfg.reverse_fill_source_path)
        cfg.reverse_fill_format = self._selected_format()
        cfg.reverse_fill_start_row = max(1, int(self._start_row_value or 1))
        cfg.reverse_fill_threads = max(1, int(self._reverse_fill_threads_value or 1))
        if cfg.reverse_fill_enabled:
            cfg.threads = max(1, int(cfg.reverse_fill_threads or 1))

    def apply_config(self, cfg: RuntimeConfig) -> None:
        self.url_edit.blockSignals(True)
        self.url_edit.setText(str(getattr(cfg, "url", "") or ""))
        self.url_edit.blockSignals(False)
        self.file_edit.setText(str(getattr(cfg, "reverse_fill_source_path", "") or ""))
        self._start_row_value = max(1, int(getattr(cfg, "reverse_fill_start_row", 1) or 1))
        self._reverse_fill_threads_value = max(
            1,
            int(getattr(cfg, "reverse_fill_threads", getattr(cfg, "threads", 1)) or 1),
        )
        self.reverse_fill_threads_spin.blockSignals(True)
        self.reverse_fill_threads_spin.setValue(self._reverse_fill_threads_value)
        self.reverse_fill_threads_spin.blockSignals(False)

        selected_format = str(
            getattr(cfg, "reverse_fill_format", REVERSE_FILL_FORMAT_AUTO)
            or REVERSE_FILL_FORMAT_AUTO
        )
        valid_formats = {value for value, _label in _FORMAT_CHOICES}
        self._selected_format_value = (
            selected_format if selected_format in valid_formats else REVERSE_FILL_FORMAT_AUTO
        )
        self._refresh_preview()

    def _selected_format(self) -> str:
        return str(self._selected_format_value or REVERSE_FILL_FORMAT_AUTO)

    def eventFilter(self, watched, event):
        if watched in getattr(self, "_file_drop_widgets", ()):
            if event.type() == QEvent.Type.DragEnter:
                if not self._has_survey_link_text():
                    return False
                if isinstance(event, QDragEnterEvent) and self._mime_has_excel_file(event):
                    event.acceptProposedAction()
                    return True
                return False
            if event.type() == QEvent.Type.Drop:
                if not self._has_survey_link_text():
                    return False
                if isinstance(event, QDropEvent):
                    file_path = self._extract_excel_path_from_drop(event)
                    if file_path:
                        self._apply_excel_source_path(file_path)
                        event.acceptProposedAction()
                        return True
                return False
        return super().eventFilter(watched, event)

    def _toast(
        self,
        message: str,
        level: str = "warning",
        duration: int = 2400,
        show_progress: bool = False,
    ) -> Optional[InfoBar]:
        try:
            replace_message_bar(self._progress_infobar)
        except Exception as exc:
            log_suppressed_exception(
                "_toast: replace_message_bar(self._progress_infobar)",
                exc,
                level=logging.WARNING,
            )
        self._progress_infobar = None

        infobar = show_message_bar(
            parent=self.window() or self,
            title="反填页提示",
            message=message,
            level=level,
            position=InfoBarPosition.TOP,
            duration=duration,
        )

        if show_progress:
            spinner = IndeterminateProgressRing()
            spinner.setFixedSize(20, 20)
            spinner.setStrokeWidth(3)
            infobar.addWidget(spinner)
            self._progress_infobar = infobar
        return infobar

    def _has_question_entries(self) -> bool:
        try:
            coordinator = getattr(self, "_run_coordinator", None)
            if coordinator is not None:
                return bool(coordinator.has_question_entries())
        except Exception:
            pass
        return False

    def _has_excel_source_path(self) -> bool:
        return bool(self.file_edit.text().strip())

    def _has_survey_link_text(self) -> bool:
        return bool(self.url_edit.text().strip())

    def _sync_random_ip_toggle_presentation(self, enabled: bool) -> None:
        self.random_ip_row.sync_toggle_presentation(enabled)

    def _apply_runtime_ui_state(self, state: dict) -> None:
        enabled = bool((state or {}).get("random_ip_enabled", False))
        if bool(self.random_ip_cb.isChecked()) != enabled:
            self.random_ip_cb.blockSignals(True)
            self.random_ip_cb.setChecked(enabled)
            self.random_ip_cb.blockSignals(False)
        self._sync_random_ip_toggle_presentation(enabled)

    def set_random_ip_loading(self, loading: bool, message: str = "") -> None:
        self.random_ip_row.set_loading(loading, message)

    def _on_random_ip_toggled(self, enabled: bool) -> None:
        self._sync_random_ip_toggle_presentation(bool(enabled))
        if self.controller.request_toggle_random_ip(bool(enabled), adapter=self.controller.adapter):
            return
        fallback_enabled = bool(
            self.controller.get_runtime_ui_state().get("random_ip_enabled", False)
        )
        self.random_ip_cb.blockSignals(True)
        self.random_ip_cb.setChecked(fallback_enabled)
        self.random_ip_cb.blockSignals(False)
        self._sync_random_ip_toggle_presentation(fallback_enabled)

    def _sync_start_button_state(self, running: Optional[bool] = None) -> None:
        if running is None:
            running = bool(getattr(self.controller, "running", False))
        enabled = (
            (not bool(running)) and self._has_question_entries() and self._has_excel_source_path()
        )
        self.start_btn.setEnabled(enabled)

    def _set_main_progress_indeterminate(self, enabled: bool) -> None:
        flag = bool(enabled)
        if flag == self._main_progress_indeterminate:
            return
        self._main_progress_indeterminate = flag
        if flag:
            self.progress_bar.hide()
            self.progress_indeterminate_bar.show()
            self.progress_pct.setText("...")
            return
        self.progress_indeterminate_bar.hide()
        self.progress_bar.show()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(max(0, min(100, int(self._last_progress or 0))))

    def update_status(self, text: str, current: int, target: int) -> None:
        if str(text or "").strip() == "正在初始化":
            self.status_label.setText("正在初始化")
            self._set_main_progress_indeterminate(True)
            self.progress_pct.setText("...")
            self._last_progress = 0
            return

        self._set_main_progress_indeterminate(False)
        status_text = str(text or "").strip() or "等待配置..."
        self.status_label.setText(status_text)
        progress = 0
        if int(target or 0) > 0:
            progress = min(100, int((int(current or 0) / max(int(target or 0), 1)) * 100))
        self.progress_bar.setValue(progress)
        self.progress_pct.setText(f"{progress}%")
        self._last_progress = progress
        if (
            int(target or 0) > 0
            and int(current or 0) >= int(target or 0)
            and not self._completion_notified
        ):
            self._completion_notified = True
            self.stop_btn.setEnabled(False)

    def on_run_state_changed(self, running: bool) -> None:
        self._sync_start_button_state(running=running)
        self.stop_btn.setEnabled(bool(running))
        if running:
            self.resume_btn.setEnabled(False)
            self.resume_btn.hide()
            self._completion_notified = False
            self.start_btn.setText("执行中...")
            self.start_btn.setEnabled(False)
            return

        self.resume_btn.setEnabled(False)
        self.resume_btn.hide()
        self._set_main_progress_indeterminate(False)
        if self._completion_notified or self._last_progress >= 100:
            self.start_btn.setText("重新开始")
        else:
            self.start_btn.setText("开始执行")
        self._sync_start_button_state(running=False)
        self.stop_btn.setEnabled(False)
        if not self._completion_notified:
            self._show_end_toast_after_cleanup = True

    def on_pause_state_changed(self, paused: bool, reason: str = "") -> None:
        self._last_pause_reason = str(reason or "")
        if not getattr(self.controller, "running", False):
            self.resume_btn.setEnabled(False)
            self.resume_btn.hide()
            return
        if paused:
            self.resume_btn.show()
            self.resume_btn.setEnabled(True)
            msg = f"已暂停：{reason}" if reason else "已暂停"
            self._toast(msg, "warning", 2200)
            return
        self.resume_btn.setEnabled(False)
        self.resume_btn.hide()

    def on_cleanup_finished(self) -> None:
        if not self._show_end_toast_after_cleanup:
            return
        self._show_end_toast_after_cleanup = False

    def _on_start_clicked(self) -> None:
        coordinator = getattr(self, "_run_coordinator", None)
        if coordinator is None:
            self._toast("主页尚未完成初始化，暂时不能开始执行", "error", duration=3000)
            return
        if not self._validate_reverse_fill_start_url():
            return
        if not self._prepare_reverse_fill_start_target():
            return
        should_reset = bool(coordinator.is_completed_run())
        started = bool(coordinator.start_reverse_fill())
        if started and should_reset:
            self.progress_bar.setValue(0)
            self.progress_pct.setText("0%")
            self._last_progress = 0
            self._completion_notified = False

    def _prepare_reverse_fill_start_target(self) -> bool:
        if self._last_spec is None:
            self._refresh_preview()
        spec = self._last_spec
        if spec is None:
            message = self._last_error or "反填数据还没预检成功，暂时不能启动"
            self._toast(message, "error", duration=3200)
            return False
        effective_target = max(0, int(getattr(spec, "target_num", 0) or 0))
        if effective_target <= 0:
            self._toast(
                "当前 Excel 没有可提交的有效行，先检查起始行和表格内容",
                "warning",
                duration=3200,
            )
            return False
        coordinator = getattr(self, "_run_coordinator", None)
        if coordinator is not None:
            coordinator.set_reverse_fill_target(effective_target)
        return True

    def _on_resume_clicked(self) -> None:
        coordinator = getattr(self, "_run_coordinator", None)
        if coordinator is None:
            self._toast("主页尚未完成初始化，暂时不能继续执行", "error", duration=3000)
            return
        coordinator.resume()

    def _context_ready(self) -> bool:
        provider = normalize_survey_provider(self._survey_provider, default="")
        current_url = self.url_edit.text().strip()
        return (
            provider == SURVEY_PROVIDER_WJX
            and bool(self._questions_info)
            and bool(self._parsed_url)
            and current_url == self._parsed_url
        )

    def _validate_reverse_fill_start_url(self) -> bool:
        url = self.url_edit.text().strip()
        if not url:
            self._toast("请先输入问卷链接或贴入二维码", "warning")
            return False
        if not is_supported_survey_url(url):
            self._toast(
                "仅支持问卷星、腾讯问卷与 Credamo 见数链接",
                "error",
                duration=3000,
            )
            return False
        if not is_wjx_survey_url(url):
            self._toast("Excel 反填目前只支持问卷星公开问卷链接", "error", duration=3000)
            return False
        if url != self._parsed_url:
            self._toast("反填链接已修改，请先按回车解析问卷结构", "warning", duration=3200)
            return False
        return True

    def _browse_excel_file(self) -> None:
        source_path = self.file_edit.text().strip()
        start_dir = os.path.dirname(source_path) if source_path else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择源数据 Excel 文件",
            start_dir,
            "Excel 数据工作表 (*.xlsx);;所有包含的文件 (*.*)",
        )
        if not path:
            return
        self._apply_excel_source_path(path)

    def _on_reverse_fill_threads_changed(self, value: int) -> None:
        self._reverse_fill_threads_value = max(1, int(value or 1))
        self._refresh_preview()

    def _mime_has_excel_file(self, event: QDragEnterEvent | QDropEvent) -> bool:
        mime_data = event.mimeData()
        if not mime_data or not mime_data.hasUrls():
            return False
        return bool(iter_supported_drop_paths(mime_data.urls()))

    def _extract_excel_path_from_drop(self, event: QDropEvent) -> str:
        mime_data = event.mimeData()
        if not mime_data or not mime_data.hasUrls():
            return ""
        paths = iter_supported_drop_paths(mime_data.urls())
        if paths:
            return paths[0]
        self._toast("这里只支持拖入 .xlsx 表格文件", "warning", duration=2600)
        return ""

    def _apply_excel_source_path(self, file_path: str) -> None:
        normalized = str(file_path or "").strip()
        if not is_supported_excel_path(normalized):
            self._toast("请选择 .xlsx 表格文件", "warning", duration=2600)
            return
        self.file_edit.setText(normalized)
        self._refresh_preview()

    def _on_parse_clicked(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            self._toast("请先输入问卷链接或贴入二维码", "warning")
            return
        if not is_supported_survey_url(url):
            self._toast(
                "仅支持问卷星、腾讯问卷与 Credamo 见数链接",
                "error",
                duration=3000,
            )
            return
        provider = detect_survey_provider(url)
        if not (
            provider in {SURVEY_PROVIDER_QQ, SURVEY_PROVIDER_CREDAMO} or is_wjx_survey_url(url)
        ):
            self._toast("链接不是可解析的公开问卷", "error", duration=3000)
            return

        self._parse_requested_from_reverse_fill = True
        self.surveyUrlChanged.emit(url)
        self._toast("正在解析问卷结构...", "info", duration=-1, show_progress=True)
        self.controller.parse_survey(url)
        log_action(
            "UI",
            "parse_survey",
            "url_edit",
            "reverse_fill",
            result="started",
            payload={"provider": provider},
        )

    def _on_url_text_changed(self, text: str) -> None:
        self.surveyUrlChanged.emit(str(text or ""))
        self._refresh_preview()

    def _on_survey_parsed(self, info: list, title: str) -> None:
        if not self._parse_requested_from_reverse_fill:
            return
        self._parse_requested_from_reverse_fill = False
        parsed_info = ensure_survey_question_metas(info or [])
        unsupported_count = sum(1 for item in parsed_info if bool(item.unsupported))
        self._survey_title = str(title or "").strip()
        self._parsed_url = self.url_edit.text().strip()
        self._survey_provider = normalize_survey_provider(
            getattr(self.controller, "survey_provider", "")
            or detect_survey_provider(self.url_edit.text().strip(), default=""),
            default=self._survey_provider or "",
        )
        self._refresh_preview()
        if unsupported_count > 0:
            message = f"问卷已解析，发现 {unsupported_count} 道反填不能直接覆盖的题型"
            self._toast(
                message,
                "warning",
                duration=3600,
            )
            return
        self._toast(
            "问卷已解析，可以继续选择 Excel 做反填预检",
            "success",
            duration=2600,
        )

    def _on_survey_parse_failed(self, error_msg: str) -> None:
        if not self._parse_requested_from_reverse_fill:
            return
        self._parse_requested_from_reverse_fill = False
        text = str(error_msg or "").strip() or "请确认链接有效且网络正常"
        if "问卷已停止" in text or "停止状态" in text:
            self._toast("问卷已停止，无法作答", "warning", duration=2200)
            return
        if "企业标准版" in text:
            self._toast("问卷发布者企业标准版未购买或已到期，暂时不能填写", "warning", duration=2200)
            return
        if "问卷已暂停" in text:
            self._toast("问卷已暂停，需要前往问卷星后台重新发布", "warning", duration=2200)
            return
        if "暂未开放" in text:
            self._toast(text, "warning", duration=2200)
            return
        self._toast(f"解析失败：{text}", "error", duration=3200)

    def _open_wizard(self) -> None:
        if not callable(self._open_wizard_handler):
            self._toast(
                "目前无法直接导航至系统向导。您需优先在仪表盘主页完成问卷解析方可继续。",
                "warning",
            )
            return
        issue_question_nums = [int(num) for num in self._issue_question_nums if int(num) > 0]
        if not issue_question_nums:
            self._toast("当前没有需要处理的异常题目。", "warning")
            return
        try:
            self._open_wizard_handler(issue_question_nums)
        except Exception as exc:
            logging.info("打开配置向导异常崩溃", exc_info=True)
            self._toast(f"触发配置交互向导意外阻断：{exc}", "error")

    def _set_table_text(self, table: TableWidget, row: int, column: int, text: str) -> None:
        item = table.item(row, column)
        if item is None:
            table.setItem(row, column, QTableWidgetItem(text))
            return
        item.setText(text)

    def _clear_tables(self) -> None:
        self._issue_question_nums = []
        self.mapping_table.setRowCount(0)
        self.open_wizard_btn.hide()

    def _populate_plan_table(self, spec: ReverseFillSpec) -> None:
        rows = build_plan_rows(spec)
        self.mapping_table.setRowCount(len(rows))
        for row_index, row_values in enumerate(rows):
            for column_index, value in enumerate(row_values):
                self._set_table_text(self.mapping_table, row_index, column_index, value)

    def _refresh_preview(self) -> None:
        self._last_spec = None
        self._last_error = ""
        source_path = self.file_edit.text().strip()
        context_ready = self._context_ready()
        has_link_text = self._has_survey_link_text()
        self._sync_start_button_state()

        controls_enabled = has_link_text
        self.file_edit.setEnabled(controls_enabled)
        self.browse_btn.setEnabled(controls_enabled)
        self.open_wizard_btn.hide()

        if not context_ready:
            provider = normalize_survey_provider(self._survey_provider, default="")
            if not has_link_text:
                hint = ""
            elif self._parsed_url and self.url_edit.text().strip() != self._parsed_url:
                hint = ""
            elif provider != SURVEY_PROVIDER_WJX:
                hint = "该执行总线暂不能在当前平台环境接管反填覆盖支持，相关控制流已全托管休眠"
            else:
                hint = ""

            self.detected_format_label.setText("验证结果：未接通目标流")
            self.state_hint_label.setText(hint)
            self._clear_tables()
            return

        if not source_path:
            self.detected_format_label.setText("验证结果：待指定 Excel 数据池")
            self.state_hint_label.setText("")
            self._clear_tables()
            return

        try:
            spec = build_reverse_fill_spec(
                source_path=source_path,
                survey_provider=self._survey_provider or SURVEY_PROVIDER_WJX,
                questions_info=self._questions_info,
                question_entries=self._question_entries,
                selected_format=self._selected_format(),
                start_row=max(1, int(self._start_row_value or 1)),
                target_num=0,
            )
        except Exception as exc:
            self._last_error = str(exc)
            self.detected_format_label.setText("验证结果：提取引发崩溃挂起")
            self.state_hint_label.setText(self._last_error)
            self._clear_tables()
            return

        self._last_spec = spec
        self.detected_format_label.setText(
            f"识别格式：{reverse_fill_format_label(spec.detected_format)}"
        )
        self.state_hint_label.setText("")

        self._issue_question_nums = actionable_issue_question_nums(spec)
        self.open_wizard_btn.setVisible(bool(self._issue_question_nums))
        self._populate_plan_table(spec)
