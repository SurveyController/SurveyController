from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import threading
import time
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QTableWidgetItem, QWidget
from qfluentwidgets import BodyLabel, FluentIcon, IconInfoBadge

from surveycore.core.reverse_fill.schema import ReverseFillSpec, reverse_fill_format_label
from software.core.reverse_fill.validation import (
    ReverseFillValidationCancelled,
    build_reverse_fill_spec,
)
from software.providers.common import SURVEY_PROVIDER_WJX, normalize_survey_provider
from software.ui.pages.workbench.reverse_fill.logic import (
    actionable_issue_question_nums,
    build_plan_rows,
    status_badge_level_for_label,
)
from software.ui.pages.workbench.shared.table_helpers import set_table_text


class PreviewDispatcher(QObject):
    finished = Signal(int, object, str, bool)
    progress = Signal(int, str, int, int)


class PreviewCancellation:
    def __init__(self) -> None:
        self._event: threading.Event | None = None

    def begin(self) -> threading.Event:
        event = threading.Event()
        self._event = event
        return event

    def cancel_current(self) -> bool:
        event = self._event
        if event is None:
            return False
        event.set()
        return True

    def finish(self) -> None:
        self._event = None


def _build_preview(
    ticket: int,
    payload: dict[str, Any],
    cancellation_event: threading.Event,
    dispatcher: PreviewDispatcher,
) -> ReverseFillSpec | None:
    last_progress_at = 0.0
    last_stage = ""

    def report_progress(stage: str, current: int, total: int) -> None:
        nonlocal last_progress_at, last_stage
        now = time.monotonic()
        if stage == last_stage and current != total and now - last_progress_at < 0.15:
            return
        last_progress_at = now
        last_stage = stage
        try:
            dispatcher.progress.emit(ticket, stage, current, total)
        except RuntimeError:
            return

    try:
        return build_reverse_fill_spec(
            **payload,
            progress_callback=report_progress,
            cancellation_check=cancellation_event.is_set,
        )
    except ReverseFillValidationCancelled:
        return None


def _publish_preview_result(
    dispatcher: PreviewDispatcher,
    ticket: int,
    future: concurrent.futures.Future[Any],
) -> None:
    spec = None
    error = ""
    cancelled = False
    try:
        spec = future.result()
        cancelled = spec is None
    except concurrent.futures.CancelledError:
        cancelled = True
    except Exception as exc:
        error = str(exc)
    try:
        dispatcher.finished.emit(ticket, spec, error, cancelled)
    except RuntimeError:
        return


def _start_preview(page: Any, ticket: int, payload: dict[str, Any]) -> None:
    page._preview_in_flight = True
    page._preview_cancel_requested = False
    page._preview_stage = "reading"
    page.cancel_preview_btn.setText("取消预检")
    page.cancel_preview_btn.setEnabled(True)
    page.cancel_preview_btn.show()
    page._sync_start_button_state()
    cancellation_event = page._preview_cancellation.begin()
    dispatcher = page._preview_dispatcher
    try:
        future = page.controller.submit_ui_task(
            f"reverse-fill-preview-{ticket}",
            lambda: asyncio.to_thread(
                _build_preview,
                ticket,
                payload,
                cancellation_event,
                dispatcher,
            ),
        )
    except Exception as exc:
        page._preview_cancellation.finish()
        preview_ready(page, ticket, None, str(exc), False)
        return
    page._preview_future = future
    future.add_done_callback(
        lambda done: _publish_preview_result(dispatcher, ticket, done)
    )


def cancel_preview(page: Any) -> None:
    if not page._preview_in_flight or not page._preview_cancellation.cancel_current():
        return
    page._preview_cancel_requested = True
    page._preview_pending = None
    page.cancel_preview_btn.setEnabled(False)
    page.cancel_preview_btn.setText("正在取消...")
    if page._preview_stage == "reading":
        page.state_hint_label.setText("当前 Excel 读取结束后会停止预检")
    else:
        page.state_hint_label.setText("正在停止预检")


def preview_progress(page: Any, ticket: int, stage: str, current: int, total: int) -> None:
    if (
        ticket != page._preview_generation
        or page._preview_cancel_requested
        or not page._preview_in_flight
    ):
        return
    page._preview_stage = stage
    if stage == "reading":
        page.detected_format_label.setText("正在读取 Excel 数据池")
        page.state_hint_label.setText("读取完成前无法中断当前文件操作")
    elif stage == "preparing":
        page.detected_format_label.setText(f"正在准备样本 ({current}/{total})")
        page.state_hint_label.setText("建立样本校验索引")
    elif stage == "questions":
        page.detected_format_label.setText(f"正在校验题目 ({current}/{total})")
        page.state_hint_label.setText("检查题目配置与 Excel 列映射")
    elif stage == "samples":
        page.detected_format_label.setText(
            f"正在校验样本 ({current}/{total})"
        )
        page.state_hint_label.setText("检查样本值是否可以稳定回放")
    elif stage == "assembling":
        page.detected_format_label.setText("正在整理预检结果")
        page.state_hint_label.setText(f"已处理样本 ({current}/{total})")


def preview_ready(
    page: Any,
    ticket: int,
    spec: ReverseFillSpec | None,
    error: str,
    cancelled: bool,
) -> None:
    page._preview_in_flight = False
    page._preview_future = None
    page._preview_cancellation.finish()
    page.cancel_preview_btn.hide()
    page.cancel_preview_btn.setEnabled(True)
    if ticket == page._preview_generation:
        if cancelled or page._preview_cancel_requested:
            page._last_spec = None
            page._last_error = ""
            page.detected_format_label.setText("预检已取消")
            page.state_hint_label.setText("")
            clear_tables(page)
        elif error:
            page._last_error = error
            page.detected_format_label.setText("验证结果：无法读取 Excel 数据池")
            page.state_hint_label.setText(error)
            clear_tables(page)
        elif spec is not None:
            page._last_spec = spec
            page._last_error = ""
            page.detected_format_label.setText(
                f"识别格式：{reverse_fill_format_label(spec.detected_format)}"
            )
            page.state_hint_label.setText("")
            page._issue_question_nums = actionable_issue_question_nums(spec)
            page.open_wizard_btn.setVisible(bool(page._issue_question_nums))
            populate_plan_table(page, spec)
        else:
            page._last_error = "预检未返回结果，请重新选择 Excel 文件后重试"
            page.detected_format_label.setText("验证结果：没有预检结果")
            page.state_hint_label.setText(page._last_error)
            clear_tables(page)
        page._preview_cancel_requested = False

    page._sync_start_button_state()

    pending = page._preview_pending
    page._preview_pending = None
    if pending is not None and pending[0] == page._preview_generation:
        _start_preview(page, pending[0], pending[1])


def _make_status_badge(level: str, parent: QWidget) -> IconInfoBadge:
    normalized = str(level or "").strip().lower()
    if normalized == "success":
        return IconInfoBadge.success(FluentIcon.ACCEPT_MEDIUM, parent=parent)
    if normalized == "warning":
        return IconInfoBadge.warning(FluentIcon.INFO, parent=parent)
    if normalized == "error":
        return IconInfoBadge.error(FluentIcon.CANCEL_MEDIUM, parent=parent)
    return IconInfoBadge.info(FluentIcon.INFO, parent=parent)


def _set_status_cell(page: Any, row: int, column: int, text: str) -> None:
    table = page.mapping_table
    container = QWidget(table)
    layout = QHBoxLayout(container)
    layout.setContentsMargins(8, 0, 8, 0)
    layout.setSpacing(6)
    layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    layout.addWidget(_make_status_badge(status_badge_level_for_label(text), container))
    layout.addWidget(BodyLabel(text, container))
    layout.addStretch(1)
    item = table.item(row, column)
    if item is None:
        item = QTableWidgetItem("")
        table.setItem(row, column, item)
    item.setData(Qt.ItemDataRole.UserRole, text)
    item.setToolTip(text)
    table.setCellWidget(row, column, container)


def clear_tables(page: Any) -> None:
    page._issue_question_nums = []
    page.mapping_table.setRowCount(0)
    page.open_wizard_btn.hide()


def populate_plan_table(page: Any, spec: ReverseFillSpec) -> None:
    rows = build_plan_rows(spec)
    page.mapping_table.setRowCount(len(rows))
    for row_index, row_values in enumerate(rows):
        for column_index, value in enumerate(row_values):
            if column_index == 2:
                _set_status_cell(page, row_index, column_index, value)
                continue
            set_table_text(page.mapping_table, row_index, column_index, value)


def refresh_preview(page: Any) -> None:
    page._preview_generation += 1
    ticket = page._preview_generation
    page._preview_pending = None
    page._preview_cancel_requested = False
    page._preview_cancellation.cancel_current()
    page._last_spec = None
    page._last_error = ""
    source_path = page.file_edit.text().strip()
    context_ready = page._context_ready()
    has_link_text = page._has_survey_link_text()
    page._sync_start_button_state()

    controls_enabled = has_link_text
    page.file_edit.setEnabled(controls_enabled)
    page.browse_btn.setEnabled(controls_enabled)
    page.open_wizard_btn.hide()

    if not context_ready:
        page.cancel_preview_btn.hide()
        provider = normalize_survey_provider(page._survey_provider, default="")
        if not has_link_text:
            hint = ""
        elif page._parsed_url and page.url_edit.text().strip() != page._parsed_url:
            hint = ""
        elif provider != SURVEY_PROVIDER_WJX:
            hint = "该执行总线暂不能在当前平台环境接管反填覆盖支持，相关控制流已全托管休眠"
        else:
            hint = ""

        page.detected_format_label.setText("验证结果：未接通目标流")
        page.state_hint_label.setText(hint)
        clear_tables(page)
        return

    if not source_path:
        page.cancel_preview_btn.hide()
        page.detected_format_label.setText("验证结果：待指定 Excel 数据池")
        page.state_hint_label.setText("")
        clear_tables(page)
        return

    payload = {
        "source_path": source_path,
        "survey_provider": page._survey_provider or SURVEY_PROVIDER_WJX,
        "questions_info": copy.deepcopy(page._questions_info),
        "question_entries": copy.deepcopy(page._question_entries),
        "selected_format": page._selected_format(),
        "start_row": max(1, int(page._start_row_value or 1)),
        "target_num": 0,
    }
    page.detected_format_label.setText("正在读取 Excel 数据池")
    if page._preview_in_flight:
        page._preview_pending = (ticket, payload)
        page.cancel_preview_btn.show()
        return
    _start_preview(page, ticket, payload)


__all__ = [
    "PreviewCancellation",
    "PreviewDispatcher",
    "cancel_preview",
    "clear_tables",
    "populate_plan_table",
    "preview_progress",
    "preview_ready",
    "refresh_preview",
]
