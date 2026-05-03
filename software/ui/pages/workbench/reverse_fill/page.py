
"""问卷星 Excel 反填管理页。"""

from __future__ import annotations

import copy
import logging
import os
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Sequence

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QTableWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    InfoBadge,
    InfoBar,
    InfoBarPosition,
    IndeterminateProgressBar,
    IndeterminateProgressRing,
    LineEdit,
    ProgressBar,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    TableWidget,
    CardWidget,
    ElevatedCardWidget,
    IconWidget,
    ToolButton,
)

from software.app.config import HEADLESS_MAX_THREADS
from software.core.reverse_fill.schema import (
    REVERSE_FILL_FORMAT_AUTO,
    REVERSE_FILL_FORMAT_WJX_SCORE,
    REVERSE_FILL_FORMAT_WJX_SEQUENCE,
    REVERSE_FILL_FORMAT_WJX_TEXT,
    REVERSE_FILL_STATUS_BLOCKED,
    REVERSE_FILL_STATUS_FALLBACK,
    REVERSE_FILL_STATUS_REVERSE,
    ReverseFillSpec,
    reverse_fill_format_label,
)
from software.core.reverse_fill.validation import build_reverse_fill_spec
from software.io.config import RuntimeConfig
from software.logging.action_logger import log_action
from software.logging.log_utils import log_suppressed_exception
from software.providers.common import SURVEY_PROVIDER_WJX, normalize_survey_provider
from software.providers.common import (
    SURVEY_PROVIDER_CREDAMO,
    SURVEY_PROVIDER_QQ,
    detect_survey_provider,
    is_supported_survey_url,
    is_wjx_survey_url,
)
from software.providers.contracts import SurveyQuestionMeta, ensure_survey_question_metas
from software.ui.helpers.fluent_tooltip import install_tooltip_filter
from software.ui.pages.workbench.dashboard.parts.clipboard import DashboardClipboardMixin
from software.ui.widgets.no_wheel import NoWheelSpinBox
from software.ui.widgets.paste_only_menu import PasteOnlyMenu

if TYPE_CHECKING:
    from software.ui.controller import RunController


_FORMAT_CHOICES = [
    (REVERSE_FILL_FORMAT_AUTO, "自动识别 (推荐)"),
    (REVERSE_FILL_FORMAT_WJX_SEQUENCE, "问卷星按序号"),
    (REVERSE_FILL_FORMAT_WJX_SCORE, "问卷星按分数"),
    (REVERSE_FILL_FORMAT_WJX_TEXT, "问卷星按文本"),
]

_STATUS_LABELS = {
    REVERSE_FILL_STATUS_REVERSE: "🟢 正常",
    REVERSE_FILL_STATUS_FALLBACK: "🟡 需要处理",
    REVERSE_FILL_STATUS_BLOCKED: "🔴 不支持",
}

_NON_ACTIONABLE_ISSUE_CATEGORIES = {"auto_handled"}


def _status_label_for_plan(plan: Any) -> str:
    status = str(getattr(plan, "status", "") or "")
    if status == REVERSE_FILL_STATUS_FALLBACK and bool(getattr(plan, "fallback_resolved", False)):
        return "🟢 已处理"
    if status == REVERSE_FILL_STATUS_FALLBACK and bool(getattr(plan, "fallback_ready", False)):
        return "🟡 可回退"
    return _STATUS_LABELS.get(status, status)


class ReverseFillPage(DashboardClipboardMixin, QWidget):
    """独立的反填数据源页。"""

    surveyUrlChanged = Signal(str)

    def __init__(self, controller: "RunController", parent=None):
        super().__init__(parent)
        self.controller = controller
        self._questions_info: List[SurveyQuestionMeta] = []
        self._question_entries: List[Any] = []
        self._survey_provider: str = ""
        self._survey_title: str = ""
        self._reverse_fill_threads_value: int = 1
        self._selected_format_value: str = REVERSE_FILL_FORMAT_AUTO
        self._start_row_value: int = 1
        self._last_spec: Optional[ReverseFillSpec] = None
        self._last_error: str = ""
        self._open_wizard_handler: Optional[Callable[[List[int]], None]] = None
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

        self._build_ui()
        self._bind_events()
        self._refresh_preview()
        self._sync_start_button_state()

    def _build_title_area(self, layout: QVBoxLayout) -> None:
        title_row = QWidget(self.view)
        title_row_layout = QHBoxLayout(title_row)
        title_row_layout.setContentsMargins(0, 0, 0, 0)
        title_row_layout.setSpacing(10)

        title_label = SubtitleLabel("Excel 反填", title_row)
        title_row_layout.addWidget(title_label)

        self.preview_badge = InfoBadge.custom(
            "预览",
            QColor("#fbbf24"),
            QColor("#f59e0b"),
            parent=title_row,
        )
        title_row_layout.addWidget(self.preview_badge)
        title_row_layout.addStretch(1)

        layout.addWidget(title_row)
        layout.addSpacing(4)

    def _build_survey_entry_card(self, layout: QVBoxLayout) -> None:
        self.link_card = CardWidget(self.view)
        self.link_card.setAcceptDrops(True)
        link_layout = QVBoxLayout(self.link_card)
        link_layout.setContentsMargins(12, 12, 12, 12)
        link_layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        self.qr_btn = ToolButton(self.link_card)
        self.qr_btn.setIcon(FluentIcon.QRCODE)
        self.qr_btn.setFixedSize(36, 36)
        self.qr_btn.setToolTip("上传问卷二维码图片")
        install_tooltip_filter(self.qr_btn)
        title_row.addWidget(self.qr_btn)

        self.url_edit = LineEdit(self.link_card)
        self.url_edit.setPlaceholderText("在此拖入/粘贴问卷二维码图片或输入问卷链接")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.setAcceptDrops(True)
        self.url_edit.installEventFilter(self)
        self._paste_only_menu = PasteOnlyMenu(self)
        self.url_edit.installEventFilter(self._paste_only_menu)
        title_row.addWidget(self.url_edit, 1)

        link_layout.addLayout(title_row)

        self._link_entry_widgets = (
            self.link_card,
            self.qr_btn,
            self.url_edit,
        )
        for widget in self._link_entry_widgets:
            if widget is self.url_edit:
                continue
            widget.installEventFilter(self)

        layout.addWidget(self.link_card)

    def _build_file_picker(self, layout: QVBoxLayout) -> None:
        self.file_panel = ElevatedCardWidget(self.view)
        self.file_panel.setAcceptDrops(True)
        file_layout = QVBoxLayout(self.file_panel)
        file_layout.setContentsMargins(20, 18, 20, 20)
        file_layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_icon = IconWidget(FluentIcon.DOCUMENT, self.file_panel)
        header_icon.setFixedSize(20, 20)
        header_title = StrongBodyLabel("Excel 数据源指定", self.file_panel)
        header_row.addWidget(header_icon)
        header_row.addWidget(header_title)
        header_row.addStretch(1)
        file_layout.addLayout(header_row)

        desc_label = CaptionLabel("在此处导入/拖入用于反填的 .xlsx 文件。", self.file_panel)
        desc_label.setContentsMargins(0, 0, 0, 4)
        file_layout.addWidget(desc_label)

        input_row = QHBoxLayout()
        input_row.setSpacing(12)
        self.file_edit = LineEdit(self.file_panel)
        self.file_edit.setPlaceholderText("~/Desktop/待填答卷数据.xlsx")
        self.file_edit.setClearButtonEnabled(True)
        self.browse_btn = PushButton(FluentIcon.FOLDER_ADD, "选择路径", self.file_panel)
        input_row.addWidget(self.file_edit, 1)
        input_row.addWidget(self.browse_btn)
        file_layout.addLayout(input_row)

        info_row = QHBoxLayout()
        info_row.setSpacing(24)
        self.detected_format_label = BodyLabel("检测结果：等待校验事件", self.file_panel)
        self.state_hint_label = CaptionLabel("暂无有效数据装载", self.file_panel)
        info_row.addWidget(self.detected_format_label)
        info_row.addWidget(self.state_hint_label)
        info_row.addStretch(1)
        file_layout.addLayout(info_row)

        concurrency_row = QHBoxLayout()
        concurrency_row.setSpacing(12)
        concurrency_label = BodyLabel("反填并发数", self.file_panel)
        concurrency_hint = CaptionLabel("", self.file_panel)
        self.reverse_fill_threads_spin = NoWheelSpinBox(self.file_panel)
        self.reverse_fill_threads_spin.setRange(1, HEADLESS_MAX_THREADS)
        self.reverse_fill_threads_spin.setValue(self._reverse_fill_threads_value)
        self.reverse_fill_threads_spin.setFixedWidth(160)
        self.reverse_fill_threads_spin.setFixedHeight(36)
        concurrency_row.addWidget(concurrency_label)
        concurrency_row.addWidget(self.reverse_fill_threads_spin)
        concurrency_row.addWidget(concurrency_hint, 1)
        file_layout.addLayout(concurrency_row)

        self._file_drop_widgets = (
            self.file_panel,
            header_icon,
            header_title,
            desc_label,
            self.file_edit,
        )
        for widget in self._file_drop_widgets:
            try:
                widget.setAcceptDrops(True)
            except Exception:
                pass
            widget.installEventFilter(self)

        layout.addWidget(self.file_panel)

    def _build_details_tables(self, layout: QVBoxLayout) -> None:
        self.table_panel = ElevatedCardWidget(self.view)
        table_layout = QVBoxLayout(self.table_panel)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)

        header_widget = QWidget(self.table_panel)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(24, 16, 24, 12)
        header_layout.addStretch(1)

        self.open_wizard_btn = PrimaryPushButton(FluentIcon.EDIT, "配置异常题目", header_widget)
        self.open_wizard_btn.hide()
        header_layout.addWidget(self.open_wizard_btn)

        table_layout.addWidget(header_widget)

        table_wrapper = QWidget(self.table_panel)
        table_vbox = QVBoxLayout(table_wrapper)
        table_vbox.setContentsMargins(24, 0, 24, 24)

        self.mapping_table = TableWidget(table_wrapper)
        self.mapping_table.setColumnCount(6)
        self.mapping_table.setHorizontalHeaderLabels(["题号", "题型", "状态", "关联列", "异常说明", "处理建议"])
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.mapping_table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.mapping_table.setAlternatingRowColors(True)
        self.mapping_table.setMinimumHeight(420)
        m_header = self.mapping_table.horizontalHeader()
        m_header.setSectionResizeMode(0, m_header.ResizeMode.ResizeToContents)
        m_header.setSectionResizeMode(1, m_header.ResizeMode.ResizeToContents)
        m_header.setSectionResizeMode(2, m_header.ResizeMode.ResizeToContents)
        m_header.setSectionResizeMode(3, m_header.ResizeMode.Stretch)
        m_header.setSectionResizeMode(4, m_header.ResizeMode.Stretch)
        m_header.setSectionResizeMode(5, m_header.ResizeMode.Stretch)
        table_vbox.addWidget(self.mapping_table)

        table_layout.addWidget(table_wrapper)
        layout.addWidget(self.table_panel)

    def _build_ui(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(10)

        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.enableTransparentBackground()
        self.scroll_area.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.view = QWidget(self.scroll_area)
        self.view.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.view.setStyleSheet("background: transparent;")
        self.scroll_area.setWidget(self.view)
        viewport = self.scroll_area.viewport()
        if viewport is not None:
            viewport.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
            viewport.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        self._build_title_area(layout)
        self._build_survey_entry_card(layout)
        self._build_file_picker(layout)
        self._build_details_tables(layout)
        layout.addStretch(1)
        outer.addWidget(self.scroll_area, 1)
        self._build_bottom_status_card(outer)

    def _build_bottom_status_card(self, outer_layout: QVBoxLayout) -> None:
        bottom = CardWidget(self)
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(12, 10, 12, 10)
        bottom_layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        self.status_label = StrongBodyLabel("等待配置...", bottom)
        self.progress_bar = ProgressBar(bottom)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_indeterminate_bar = IndeterminateProgressBar(start=True, parent=bottom)
        self.progress_indeterminate_bar.hide()
        self.progress_pct = StrongBodyLabel("0%", bottom)
        self.progress_pct.setMinimumWidth(50)
        self.progress_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_pct.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.start_btn = PrimaryPushButton("开始执行", bottom)
        self.resume_btn = PrimaryPushButton("继续", bottom)
        self.resume_btn.setEnabled(False)
        self.resume_btn.hide()
        self.stop_btn = PushButton("停止", bottom)
        self.stop_btn.setEnabled(False)
        self.start_btn.setToolTip("请先完成问卷解析、题目配置，并导入 Excel 数据源")
        install_tooltip_filter(self.start_btn)

        top_row.addWidget(self.status_label)
        top_row.addWidget(self.progress_bar, 1)
        top_row.addWidget(self.progress_indeterminate_bar, 1)
        top_row.addWidget(self.progress_pct)
        top_row.addWidget(self.start_btn)
        top_row.addWidget(self.resume_btn)
        top_row.addWidget(self.stop_btn)
        bottom_layout.addLayout(top_row)
        outer_layout.addWidget(bottom)

    def _bind_events(self) -> None:
        self.qr_btn.clicked.connect(self._on_qr_clicked)
        self.url_edit.returnPressed.connect(self._on_parse_clicked)
        self.url_edit.textChanged.connect(self.surveyUrlChanged.emit)
        self.file_edit.editingFinished.connect(self._refresh_preview)
        self.reverse_fill_threads_spin.valueChanged.connect(self._on_reverse_fill_threads_changed)
        self.browse_btn.clicked.connect(self._browse_excel_file)
        self.open_wizard_btn.clicked.connect(self._open_wizard)
        clipboard = QApplication.clipboard()
        clipboard.dataChanged.connect(self._on_clipboard_changed)
        self.controller.surveyParsed.connect(self._on_survey_parsed)
        self.controller.surveyParseFailed.connect(self._on_survey_parse_failed)
        self.start_btn.clicked.connect(self._on_start_clicked)
        self.resume_btn.clicked.connect(self._on_resume_clicked)
        self.stop_btn.clicked.connect(self.controller.stop_run)

    def set_open_wizard_handler(self, handler: Optional[Callable[[List[int]], None]]) -> None:
        self._open_wizard_handler = handler

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

        selected_format = str(getattr(cfg, "reverse_fill_format", REVERSE_FILL_FORMAT_AUTO) or REVERSE_FILL_FORMAT_AUTO)
        valid_formats = {value for value, _label in _FORMAT_CHOICES}
        self._selected_format_value = selected_format if selected_format in valid_formats else REVERSE_FILL_FORMAT_AUTO
        self._refresh_preview()

    def _selected_format(self) -> str:
        return str(self._selected_format_value or REVERSE_FILL_FORMAT_AUTO)

    def eventFilter(self, watched, event):
        if watched in getattr(self, "_file_drop_widgets", ()):
            if event.type() == QEvent.Type.DragEnter:
                if isinstance(event, QDragEnterEvent) and self._mime_has_excel_file(event):
                    event.acceptProposedAction()
                    return True
                return False
            if event.type() == QEvent.Type.Drop:
                if isinstance(event, QDropEvent):
                    file_path = self._extract_excel_path_from_drop(event)
                    if file_path:
                        self._apply_excel_source_path(file_path)
                        event.acceptProposedAction()
                        return True
                return False
        return super().eventFilter(watched, event)

    def _toast(self, message: str, level: str = "warning", duration: int = 2400, show_progress: bool = False) -> Optional[InfoBar]:
        if self._progress_infobar:
            try:
                self._progress_infobar.close()
            except Exception as exc:
                log_suppressed_exception("_toast: self._progress_infobar.close()", exc, level=logging.WARNING)
            self._progress_infobar = None

        parent = self.window() or self
        kind = str(level or "warning").lower()

        if kind == "error":
            infobar = InfoBar.error("反填页提示", message, parent=parent, position=InfoBarPosition.TOP, duration=duration)
        elif kind == "success":
            infobar = InfoBar.success("反填页提示", message, parent=parent, position=InfoBarPosition.TOP, duration=duration)
        elif kind == "info":
            infobar = InfoBar.info("反填页提示", message, parent=parent, position=InfoBarPosition.TOP, duration=duration)
        else:
            infobar = InfoBar.warning("反填页提示", message, parent=parent, position=InfoBarPosition.TOP, duration=duration)

        if show_progress:
            spinner = IndeterminateProgressRing()
            spinner.setFixedSize(20, 20)
            spinner.setStrokeWidth(3)
            infobar.addWidget(spinner)
            self._progress_infobar = infobar
        return infobar

    def _main_dashboard(self) -> Any:
        return getattr(self.window(), "dashboard", None)

    def _has_question_entries(self) -> bool:
        try:
            dashboard = self._main_dashboard()
            return bool(dashboard and dashboard._has_question_entries())
        except Exception:
            return False

    def _has_excel_source_path(self) -> bool:
        return bool(self.file_edit.text().strip())

    def _sync_start_button_state(self, running: Optional[bool] = None) -> None:
        if running is None:
            running = bool(getattr(self.controller, "running", False))
        enabled = (not bool(running)) and self._has_question_entries() and self._has_excel_source_path()
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
        if int(target or 0) > 0 and int(current or 0) >= int(target or 0) and not self._completion_notified:
            self._completion_notified = True
            self._toast("全部份数已完成", "success", duration=5000)
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
        dashboard = self._main_dashboard()
        if dashboard is None:
            self._toast("主页尚未完成初始化，暂时不能开始执行", "error", duration=3000)
            return
        should_reset = bool(getattr(dashboard, "_completion_notified", False) or getattr(dashboard, "_last_progress", 0) >= 100)
        dashboard._on_start_clicked()
        if should_reset:
            self.progress_bar.setValue(0)
            self.progress_pct.setText("0%")
            self._last_progress = 0
            self._completion_notified = False

    def _on_resume_clicked(self) -> None:
        dashboard = self._main_dashboard()
        if dashboard is None:
            self._toast("主页尚未完成初始化，暂时不能继续执行", "error", duration=3000)
            return
        dashboard._on_resume_clicked()

    def _context_ready(self) -> bool:
        provider = normalize_survey_provider(self._survey_provider, default="")
        return provider == SURVEY_PROVIDER_WJX and bool(self._questions_info)

    def _browse_excel_file(self) -> None:
        start_dir = os.path.dirname(self.file_edit.text().strip()) if self.file_edit.text().strip() else ""
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
        for url in mime_data.urls():
            file_path = str(url.toLocalFile() or "").strip()
            if self._is_supported_excel_path(file_path):
                return True
        return False

    def _extract_excel_path_from_drop(self, event: QDropEvent) -> str:
        mime_data = event.mimeData()
        if not mime_data or not mime_data.hasUrls():
            return ""
        for url in mime_data.urls():
            file_path = str(url.toLocalFile() or "").strip()
            if self._is_supported_excel_path(file_path):
                return file_path
        self._toast("这里只支持拖入 .xlsx 表格文件", "warning", duration=2600)
        return ""

    @staticmethod
    def _is_supported_excel_path(file_path: str) -> bool:
        normalized = str(file_path or "").strip()
        return bool(normalized) and os.path.isfile(normalized) and normalized.lower().endswith(".xlsx")

    def _apply_excel_source_path(self, file_path: str) -> None:
        normalized = str(file_path or "").strip()
        if not self._is_supported_excel_path(normalized):
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
            self._toast("仅支持问卷星、腾讯问卷与 Credamo 见数链接", "error", duration=3000)
            return
        provider = detect_survey_provider(url)
        if not (provider in {SURVEY_PROVIDER_QQ, SURVEY_PROVIDER_CREDAMO} or is_wjx_survey_url(url)):
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

    def _on_survey_parsed(self, info: list, title: str) -> None:
        if not self._parse_requested_from_reverse_fill:
            return
        self._parse_requested_from_reverse_fill = False
        parsed_info = ensure_survey_question_metas(info or [])
        unsupported_count = sum(1 for item in parsed_info if bool(item.unsupported))
        self._survey_title = str(title or "").strip()
        self._survey_provider = normalize_survey_provider(
            getattr(self.controller, "survey_provider", "") or detect_survey_provider(self.url_edit.text().strip(), default=""),
            default=self._survey_provider or "",
        )
        self._refresh_preview()
        if unsupported_count > 0:
            self._toast(f"问卷已解析，发现 {unsupported_count} 道反填不能直接覆盖的题型", "warning", duration=3600)
            return
        self._toast("问卷已解析，可以继续选择 Excel 做反填预检", "success", duration=2600)

    def _on_survey_parse_failed(self, error_msg: str) -> None:
        if not self._parse_requested_from_reverse_fill:
            return
        self._parse_requested_from_reverse_fill = False
        text = str(error_msg or "").strip() or "请确认链接有效且网络正常"
        self._toast(f"解析失败：{text}", "error", duration=3200)

    def _open_wizard(self) -> None:
        if not callable(self._open_wizard_handler):
            self._toast("目前无法直接导航至系统向导。您需优先在仪表盘主页完成问卷解析方可继续。", "warning")
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
        issues_by_question: dict[int, list[Any]] = {}
        for issue in list(spec.issues or []):
            key = int(issue.question_num or 0)
            issues_by_question.setdefault(key, []).append(issue)

        plans = list(spec.question_plans or [])
        global_issues = list(issues_by_question.get(0, []))
        self.mapping_table.setRowCount(len(plans) + len(global_issues))
        for row, plan in enumerate(plans):
            question_num = int(plan.question_num or 0)
            issues = issues_by_question.get(question_num, [])
            detail_parts = [str(plan.detail or "").strip()] if str(plan.detail or "").strip() else []
            suggestion_parts: list[str] = []
            for issue in issues:
                reason = str(issue.reason or "").strip()
                if reason and reason not in detail_parts:
                    detail_parts.append(reason)
                suggestion = str(issue.suggestion or "").strip()
                if suggestion and suggestion not in suggestion_parts:
                    suggestion_parts.append(suggestion)
            if not issues and str(plan.status or "") == REVERSE_FILL_STATUS_REVERSE:
                suggestion_parts.append("无需处理")

            self._set_table_text(self.mapping_table, row, 0, str(int(plan.question_num or 0)))
            self._set_table_text(self.mapping_table, row, 1, str(plan.question_type or ""))
            self._set_table_text(self.mapping_table, row, 2, _status_label_for_plan(plan))
            self._set_table_text(self.mapping_table, row, 3, " / ".join(list(plan.column_headers or [])))
            self._set_table_text(self.mapping_table, row, 4, "\n".join(detail_parts) or "无")
            self._set_table_text(self.mapping_table, row, 5, "\n".join(suggestion_parts) or "无")

        base_row = len(plans)
        for offset, issue in enumerate(global_issues):
            row = base_row + offset
            self._set_table_text(self.mapping_table, row, 0, "全局")
            self._set_table_text(self.mapping_table, row, 1, str(issue.category or "全局"))
            self._set_table_text(self.mapping_table, row, 2, "🔴 不支持")
            self._set_table_text(self.mapping_table, row, 3, "无")
            self._set_table_text(self.mapping_table, row, 4, str(issue.reason or ""))
            self._set_table_text(self.mapping_table, row, 5, str(issue.suggestion or ""))

    def _refresh_preview(self) -> None:
        self._last_spec = None
        self._last_error = ""
        source_path = self.file_edit.text().strip()
        context_ready = self._context_ready()
        self._sync_start_button_state()

        controls_enabled = context_ready
        self.file_edit.setEnabled(controls_enabled)
        self.browse_btn.setEnabled(controls_enabled)
        self.open_wizard_btn.hide()

        if not context_ready:
            provider = normalize_survey_provider(self._survey_provider, default="")
            if provider != SURVEY_PROVIDER_WJX:
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
        
        actionable_issues = [
            item
            for item in list(spec.issues or [])
            if str(getattr(item, "category", "") or "").strip() not in _NON_ACTIONABLE_ISSUE_CATEGORIES
        ]
        issue_question_nums = sorted({int(item.question_num or 0) for item in actionable_issues if int(item.question_num or 0) > 0})
        self._issue_question_nums = issue_question_nums
        issue_cnt = len(actionable_issues)
        self.open_wizard_btn.setVisible(issue_cnt > 0)
        self._populate_plan_table(spec)
