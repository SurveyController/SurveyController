from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    Signal,
)
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    HorizontalSeparator,
    IndeterminateProgressRing,
    LargeTitleLabel,
    PrimaryPushButton,
    ProgressBar,
    ProgressRing,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    TransparentToolButton,
)
from software.ui.widgets.indeterminate_progress import IndeterminateProgressBar
from shiboken6 import isValid

_STEP_ANIMATION_MS = 140
_PAUSED_KEYWORDS = ("重试", "切换", "暂停", "智能验证", "设备限制", "冷却", "未知")
_ERROR_KEYWORDS = ("代理连接失败", "网络请求失败", "执行失败")
_TERMINAL_ERROR_CATEGORIES = frozenset(
    {
        "run_preparation_failed",
        "engine_start_failed",
        "engine_failed",
        "dispatch_failed",
    }
)


def _format_session_name(thread_name: str, display_name: str = "") -> str:
    explicit = str(display_name or "").strip()
    if explicit:
        return explicit
    raw = str(thread_name or "").strip()
    if raw.startswith("Slot-"):
        suffix = raw[5:].strip()
        if suffix:
            return f"会话 {suffix}"
    return raw or "会话"


def _resolve_step_percent(step_current: int, step_total: int) -> int:
    total = max(0, int(step_total or 0))
    current = max(0, int(step_current or 0))
    if total <= 0:
        return 0
    return int(min(100, (min(current, total) / float(total)) * 100))


def _resolve_session_visual_mode(
    *,
    status_text: str,
    progress_kind: str,
    item_running: bool,
    step_total: int,
    global_paused: bool,
) -> str:
    text = str(status_text or "").strip()
    kind = str(progress_kind or "").strip().lower()
    if (
        kind == "failed"
        or text in _ERROR_KEYWORDS
        or ("失败" in text and "重试" not in text and "0 次" not in text)
    ):
        return "error"
    if (
        (global_paused and item_running)
        or kind == "unknown"
        or any(kw in text for kw in _PAUSED_KEYWORDS)
    ):
        return "paused"
    if item_running and (
        kind in {"preparing", "submitting"}
        or (not kind and step_total <= 0 and text not in {"", "等待中", "已完成", "构造答案"})
    ):
        return "loading"
    return "percent"


def _resolve_hero_status_text(data: dict[str, Any], current: int, target: int) -> str:
    phase_code = str(data.get("phase_code") or data.get("phase") or "")
    running = bool(data.get("running"))
    paused = bool(data.get("paused"))
    stopping = bool(data.get("stopping"))
    initializing = bool((data.get("initialization") or {}).get("active")) or (
        phase_code == "initializing"
    )
    terminal = data.get("terminal_stop") or {}
    terminal_category = str(terminal.get("category") or "")

    if initializing:
        return "正在初始化"
    if phase_code == "failed" or terminal_category in _TERMINAL_ERROR_CATEGORIES:
        return str(terminal.get("message") or "执行异常")
    if stopping or phase_code == "stopping":
        return "正在停止"
    if paused or phase_code == "paused":
        return "已暂停"
    if running:
        return "执行中"
    if terminal_category == "user_stopped":
        return "已停止"
    if target > 0 and current >= target:
        return "已完成"
    if phase_code == "finished":
        return "已完成"
    return "等待开始"


class DashboardExecutionPanel(QWidget):
    backRequested = Signal()
    pauseRequested = Signal()
    resumeRequested = Signal()
    stopRequested = Signal()
    restartRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._running = False
        self._paused = False
        self._session_rows: dict[str, dict[str, Any]] = {}
        self._session_order: list[str] = []
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self._build_ui()
        self._bind_events()
        self.on_run_state_changed(False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 16)
        root.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)

        self.back_btn = TransparentToolButton(FluentIcon.RETURN, self)
        self.back_btn.setFixedSize(34, 34)
        self.back_btn.setToolTip("返回运行设置")
        header_row.addWidget(self.back_btn)

        self.title_label = SubtitleLabel("执行进度", self)
        header_row.addWidget(self.title_label)
        header_row.addStretch(1)
        root.addLayout(header_row)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content_host = QWidget(scroll)
        content_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        content_host.setAutoFillBackground(False)
        scroll.setWidget(content_host)
        scroll.enableTransparentBackground()
        scroll.viewport().setAutoFillBackground(False)
        scroll.viewport().setStyleSheet("background: transparent;")

        host_layout = QHBoxLayout(content_host)
        host_layout.setContentsMargins(0, 8, 0, 16)
        host_layout.addStretch(1)

        container = QWidget(content_host)
        container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        container.setAutoFillBackground(False)
        container.setMaximumWidth(860)
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(24)

        hero_widget = QWidget(container)
        hero_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        hero_widget.setAutoFillBackground(False)
        hero_layout = QHBoxLayout(hero_widget)
        hero_layout.setContentsMargins(8, 12, 8, 12)
        hero_layout.setSpacing(28)

        ring_holder = QWidget(hero_widget)
        ring_holder.setFixedSize(108, 108)
        ring_holder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        ring_holder.setAutoFillBackground(False)
        ring_layout = QVBoxLayout(ring_holder)
        ring_layout.setContentsMargins(0, 0, 0, 0)
        ring_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.overall_progress_ring = ProgressRing(ring_holder)
        self.overall_progress_ring.setFixedSize(108, 108)
        self.overall_progress_ring.setStrokeWidth(8)
        self.overall_progress_ring.setTextVisible(True)
        self.overall_progress_ring.setRange(0, 100)
        self.overall_progress_ring.setValue(0)

        self.overall_indeterminate_ring = IndeterminateProgressRing(ring_holder, start=False)
        self.overall_indeterminate_ring.setFixedSize(108, 108)
        self.overall_indeterminate_ring.setStrokeWidth(8)
        self.overall_indeterminate_ring.hide()

        ring_layout.addWidget(self.overall_progress_ring)
        ring_layout.addWidget(self.overall_indeterminate_ring)
        hero_layout.addWidget(ring_holder)

        hero_info = QVBoxLayout()
        hero_info.setContentsMargins(0, 0, 0, 0)
        hero_info.setSpacing(10)
        hero_info.addStretch(1)

        self.summary_label = LargeTitleLabel("0 / 0 份", hero_widget)
        hero_info.addWidget(self.summary_label)

        self.overall_status_label = StrongBodyLabel("等待开始", hero_widget)
        self.overall_status_label.setWordWrap(True)
        hero_info.addWidget(self.overall_status_label)
        hero_info.addStretch(1)
        hero_layout.addLayout(hero_info, 1)

        container_layout.addWidget(hero_widget)
        container_layout.addWidget(HorizontalSeparator(container))

        sessions_section = QWidget(container)
        sessions_section.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        sessions_section.setAutoFillBackground(False)
        sessions_section_layout = QVBoxLayout(sessions_section)
        sessions_section_layout.setContentsMargins(8, 0, 8, 0)
        sessions_section_layout.setSpacing(16)

        sessions_section_layout.addWidget(StrongBodyLabel("并发会话", sessions_section))

        self.sessions_container = QWidget(sessions_section)
        self.sessions_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.sessions_container.setAutoFillBackground(False)
        self.sessions_layout = QGridLayout(self.sessions_container)
        self.sessions_layout.setContentsMargins(0, 0, 0, 0)
        self.sessions_layout.setHorizontalSpacing(28)
        self.sessions_layout.setVerticalSpacing(20)
        sessions_section_layout.addWidget(self.sessions_container)

        container_layout.addWidget(sessions_section)
        container_layout.addStretch(1)

        host_layout.addWidget(container, 1000)
        host_layout.addStretch(1)
        root.addWidget(scroll, 1)

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 4, 0, 0)
        footer_row.setSpacing(12)
        footer_row.addStretch(1)

        self.pause_resume_btn = PushButton(FluentIcon.PAUSE, "暂停", self)
        self.pause_resume_btn.setFixedHeight(38)
        footer_row.addWidget(self.pause_resume_btn)

        self.stop_btn = PushButton(FluentIcon.CLOSE, "停止", self)
        self.stop_btn.setFixedHeight(38)
        footer_row.addWidget(self.stop_btn)

        self.restart_btn = PrimaryPushButton(FluentIcon.PLAY, "重新开始", self)
        self.restart_btn.setFixedHeight(38)
        footer_row.addWidget(self.restart_btn)

        root.addLayout(footer_row)

    def _bind_events(self) -> None:
        self.back_btn.clicked.connect(self.backRequested.emit)
        self.pause_resume_btn.clicked.connect(self._on_pause_resume_clicked)
        self.stop_btn.clicked.connect(self.stopRequested.emit)
        self.restart_btn.clicked.connect(self.restartRequested.emit)

    def _on_pause_resume_clicked(self) -> None:
        if self._paused:
            self.resumeRequested.emit()
        else:
            self.pauseRequested.emit()

    def reset_for_new_run(self, target: int = 0) -> None:
        self._clear_session_rows()
        self._paused = False
        normalized_target = max(0, int(target or 0))
        self.summary_label.setText(f"0 / {normalized_target} 份")
        self.overall_status_label.setText("正在初始化")
        self.overall_progress_ring.resume()
        self.overall_progress_ring.setValue(0)
        self.overall_progress_ring.hide()
        self.overall_indeterminate_ring.show()
        self.overall_indeterminate_ring.start()

    def apply_runtime_snapshot(self, snapshot: dict[str, Any]) -> None:
        data = snapshot or {}
        running = bool(data.get("running"))
        paused = bool(data.get("paused"))
        phase_code = str(data.get("phase_code") or data.get("phase") or "")
        progress = data.get("progress") or {}
        current = max(0, int(progress.get("current") or 0))
        target = max(0, int(progress.get("target") or 0))
        terminal = data.get("terminal_stop") or {}
        terminal_category = str(terminal.get("category") or "")
        initializing = bool((data.get("initialization") or {}).get("active")) or (
            phase_code == "initializing"
        )
        failed = phase_code == "failed" or terminal_category in _TERMINAL_ERROR_CATEGORIES

        self._paused = paused
        self.summary_label.setText(f"{current} / {target} 份")

        self._apply_overall_state(
            status_text=_resolve_hero_status_text(data, current, target),
            current=current,
            target=target,
            initializing=initializing,
            paused=paused,
            failed=failed,
        )
        threads = data.get("threads") or {}
        self.update_thread_progress(
            {
                "target": target,
                "num_threads": int(threads.get("num_threads") or 0),
                "per_thread_target": int(threads.get("per_thread_target") or 0),
                "threads": list(threads.get("rows") or []),
                "running": running,
                "paused": paused,
                "phase_code": phase_code,
            }
        )

    def update_status(self, text: str, current: int, target: int) -> None:
        cur = max(0, int(current or 0))
        tgt = max(0, int(target or 0))
        status_text = str(text or "").strip()
        self.summary_label.setText(f"{cur} / {tgt} 份")
        self._apply_overall_state(
            status_text=status_text or "等待开始",
            current=cur,
            target=tgt,
            initializing=(status_text == "正在初始化"),
            paused=self._paused,
            failed=False,
        )

    def _apply_overall_state(
        self,
        *,
        status_text: str,
        current: int,
        target: int,
        initializing: bool,
        paused: bool,
        failed: bool,
    ) -> None:
        self.overall_status_label.setText(status_text or "等待开始")
        if initializing:
            self.overall_progress_ring.hide()
            self.overall_indeterminate_ring.show()
            self.overall_indeterminate_ring.start()
            return

        self.overall_indeterminate_ring.stop()
        self.overall_indeterminate_ring.hide()
        self.overall_progress_ring.show()

        pct = 0
        if target > 0:
            pct = min(100, int((current / float(target)) * 100))

        if failed:
            self.overall_progress_ring.setValue(pct if pct > 0 else 100)
            self.overall_progress_ring.setError(True)
            return

        if paused:
            self.overall_progress_ring.setValue(pct if pct > 0 else 100)
            self.overall_progress_ring.resume()
            self.overall_progress_ring.setPaused(True)
            return

        self.overall_progress_ring.resume()
        self.overall_progress_ring.setValue(pct)

    def on_run_state_changed(self, running: bool) -> None:
        self._running = bool(running)
        self.back_btn.setEnabled(not self._running)
        if self._running:
            self.pause_resume_btn.show()
            self.pause_resume_btn.setEnabled(True)
            self.stop_btn.show()
            self.stop_btn.setEnabled(True)
            self.restart_btn.hide()
            self.restart_btn.setEnabled(False)
            self._sync_pause_button()
            return

        self._paused = False
        self.pause_resume_btn.hide()
        self.pause_resume_btn.setEnabled(False)
        self.stop_btn.hide()
        self.stop_btn.setEnabled(False)
        self.restart_btn.show()
        self.restart_btn.setEnabled(True)

    def on_pause_state_changed(self, paused: bool, reason: str = "") -> None:
        _ = reason
        self._paused = bool(paused)
        self._sync_pause_button()

    def _sync_pause_button(self) -> None:
        if self._paused:
            self.pause_resume_btn.setIcon(FluentIcon.PLAY)
            self.pause_resume_btn.setText("继续执行")
        else:
            self.pause_resume_btn.setIcon(FluentIcon.PAUSE)
            self.pause_resume_btn.setText("暂停")

    def update_thread_progress(self, payload: dict[str, Any]) -> None:
        data = payload or {}
        raw_rows = list(data.get("threads") or [])
        global_paused = bool(data.get("paused", self._paused))
        seen_names: list[str] = []
        seen_set: set[str] = set()

        for index, item in enumerate(raw_rows):
            if not isinstance(item, dict):
                continue
            thread_name = str(item.get("thread_name") or f"Slot-{index + 1}").strip()
            if not thread_name or thread_name in seen_set:
                continue
            seen_names.append(thread_name)
            seen_set.add(thread_name)
            display_name = _format_session_name(
                thread_name,
                str(item.get("thread_display_name") or ""),
            )
            row = self._session_rows.get(thread_name)
            if row is None:
                row = self._create_session_row(display_name)
                self._session_rows[thread_name] = row
            elif row["name"].text() != display_name:
                row["name"].setText(display_name)

            status_text = str(item.get("status_text") or "等待中").strip() or "等待中"
            step_current = max(0, int(item.get("step_current") or 0))
            step_total = max(0, int(item.get("step_total") or 0))
            item_running = bool(item.get("running", False))
            progress_kind = str(item.get("progress_kind") or "")

            if row["status"].text() != status_text:
                row["status"].setText(status_text)

            mode = _resolve_session_visual_mode(
                status_text=status_text,
                progress_kind=progress_kind,
                item_running=item_running,
                step_total=step_total,
                global_paused=global_paused,
            )
            self._apply_session_row_visual(
                row=row,
                mode=mode,
                status_text=status_text,
                step_current=step_current,
                step_total=step_total,
                item_running=item_running,
            )

        stale = [name for name in self._session_rows if name not in seen_set]
        for name in stale:
            row = self._session_rows.pop(name, None)
            if row is not None:
                self._dispose_session_widget(row)

        if seen_names != self._session_order:
            self._session_order = seen_names
            self._relayout_session_grid()

    def _create_session_row(self, display_name: str) -> dict[str, Any]:
        cell = QWidget(self.sessions_container)
        cell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        cell.setAutoFillBackground(False)
        cell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        cell_layout = QVBoxLayout(cell)
        cell_layout.setContentsMargins(0, 2, 0, 2)
        cell_layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        name_label = StrongBodyLabel(display_name, cell)
        status_label = BodyLabel("等待中", cell)
        pct_label = StrongBodyLabel("0%", cell)
        pct_label.setMinimumWidth(42)
        pct_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        top_row.addWidget(name_label)
        top_row.addWidget(status_label, 1)
        top_row.addWidget(pct_label)
        cell_layout.addLayout(top_row)

        step_bar = ProgressBar(cell)
        step_bar.setRange(0, 100)
        step_bar.setValue(0)
        step_busy_bar = IndeterminateProgressBar(start=True, parent=cell)
        step_busy_bar.stop()
        step_busy_bar.hide()

        cell_layout.addWidget(step_bar)
        cell_layout.addWidget(step_busy_bar)

        anim = QPropertyAnimation(step_bar, QByteArray(b"value"), cell)
        anim.setDuration(_STEP_ANIMATION_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        return {
            "widget": cell,
            "name": name_label,
            "status": status_label,
            "pct": pct_label,
            "step_bar": step_bar,
            "step_busy_bar": step_busy_bar,
            "step_anim": anim,
        }

    def _relayout_session_grid(self) -> None:
        while self.sessions_layout.count():
            self.sessions_layout.takeAt(0)
        cols = 2 if len(self._session_order) > 1 else 1
        for col in range(2):
            self.sessions_layout.setColumnStretch(col, 1 if col < cols else 0)
        for idx, name in enumerate(self._session_order):
            row = self._session_rows.get(name)
            if row is None:
                continue
            widget = row.get("widget")
            if widget is None or not isValid(widget):
                continue
            self.sessions_layout.addWidget(widget, idx // cols, idx % cols)

    def _apply_session_row_visual(
        self,
        *,
        row: dict[str, Any],
        mode: str,
        status_text: str,
        step_current: int,
        step_total: int,
        item_running: bool,
    ) -> None:
        step_bar: ProgressBar = row["step_bar"]
        step_busy_bar: IndeterminateProgressBar = row["step_busy_bar"]
        pct_label: StrongBodyLabel = row["pct"]

        if mode == "loading":
            self._stop_step_animation(row)
            step_bar.hide()
            step_busy_bar.show()
            step_busy_bar.start()
            if pct_label.text() != "...":
                pct_label.setText("...")
            return

        step_busy_bar.stop()
        step_busy_bar.hide()
        step_bar.show()

        if mode == "error":
            target_pct = _resolve_step_percent(step_current, step_total)
            self._set_step_bar_value(row, target_pct if target_pct > 0 else 100, animate=False)
            step_bar.setError(True)
            pct_text = f"{target_pct}%" if step_total > 0 else "异常"
            if pct_label.text() != pct_text:
                pct_label.setText(pct_text)
            return

        if mode == "paused":
            target_pct = _resolve_step_percent(step_current, step_total)
            self._set_step_bar_value(row, target_pct if target_pct > 0 else 100, animate=False)
            step_bar.resume()
            step_bar.setPaused(True)
            pct_text = f"{target_pct}%" if step_total > 0 else "暂停"
            if pct_label.text() != pct_text:
                pct_label.setText(pct_text)
            return

        step_bar.resume()
        target_pct = (
            100
            if (not item_running and status_text == "已完成")
            else _resolve_step_percent(step_current, step_total)
        )
        self._set_step_bar_value(row, target_pct, animate=True)
        pct_text = f"{target_pct}%"
        if pct_label.text() != pct_text:
            pct_label.setText(pct_text)

    def _stop_step_animation(self, row: dict[str, Any]) -> None:
        anim = row.get("step_anim")
        if anim is not None:
            try:
                anim.stop()
            except Exception:
                pass

    def _set_step_bar_value(
        self,
        row: dict[str, Any],
        target_value: int,
        *,
        animate: bool,
    ) -> None:
        step_bar: ProgressBar = row["step_bar"]
        anim: QPropertyAnimation | None = row.get("step_anim")
        normalized = max(0, min(100, int(target_value)))
        current_value = int(step_bar.value())
        if current_value == normalized:
            return
        if not animate or anim is None:
            self._stop_step_animation(row)
            step_bar.setValue(normalized)
            return
        try:
            anim.stop()
            anim.setStartValue(current_value)
            anim.setEndValue(normalized)
            anim.start()
        except Exception:
            step_bar.setValue(normalized)

    def _dispose_session_widget(self, row: dict[str, Any]) -> None:
        self._stop_step_animation(row)
        busy_bar = row.get("step_busy_bar")
        if busy_bar is not None:
            try:
                busy_bar.stop()
            except Exception:
                pass
        widget = row.get("widget")
        if widget is None:
            return
        try:
            if not isValid(widget):
                return
            self.sessions_layout.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
        except Exception:
            pass

    def _clear_session_rows(self) -> None:
        for row in list(self._session_rows.values()):
            self._dispose_session_widget(row)
        self._session_rows.clear()
        self._session_order.clear()
