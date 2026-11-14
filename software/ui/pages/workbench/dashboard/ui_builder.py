from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    QAbstractAnimation,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
)
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    Action,
    CommandBar,
    FluentIcon,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
)
from qfluentwidgets.common.animation import FluentAnimation

from software.ui.helpers.fluent_tooltip import install_tooltip_filter
from software.ui.pages.workbench.dashboard.run_setup_panel import DashboardRunSetupPanel
from software.ui.widgets.paste_only_menu import PasteOnlyMenu


class HorizontalSlideStackedWidget(QStackedWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_animation_enabled = True
        self._next_index: int | None = None
        self._ani_group = QParallelAnimationGroup(self)
        self._cur_ani = QPropertyAnimation(self)
        self._cur_ani.setPropertyName(b"pos")
        self._next_ani = QPropertyAnimation(self)
        self._next_ani.setPropertyName(b"pos")
        self._ani_group.addAnimation(self._cur_ani)
        self._ani_group.addAnimation(self._next_ani)
        self._ani_group.finished.connect(self._on_ani_finished)

    def setCurrentWidget(self, widget: QWidget, duration: int = 240, isBack: bool = False) -> None:
        self.setCurrentIndex(self.indexOf(widget), duration=duration, isBack=isBack)

    def setCurrentIndex(self, index: int, duration: int = 240, isBack: bool = False) -> None:
        if index < 0 or index >= self.count() or index == self.currentIndex():
            return
        if not self._is_animation_enabled or not self.isVisible() or self.width() <= 0:
            super().setCurrentIndex(index)
            return

        if self._ani_group.state() == QAbstractAnimation.State.Running:
            self._ani_group.stop()
            self._on_ani_finished()

        current_widget = self.currentWidget()
        next_widget = self.widget(index)
        if current_widget is None or next_widget is None:
            super().setCurrentIndex(index)
            return

        self._next_index = index
        width = self.width()
        height = self.height()
        curve = FluentAnimation.createBezierCurve(0.1, 0.9, 0.2, 1.0)
        anim_duration = duration or 240

        current_widget.setGeometry(0, 0, width, height)
        next_widget.setGeometry(0, 0, width, height)

        next_start_x = -width if isBack else width
        cur_end_x = width if isBack else -width

        next_widget.move(next_start_x, 0)
        next_widget.show()
        next_widget.raise_()

        self._cur_ani.setTargetObject(current_widget)
        self._cur_ani.setDuration(anim_duration)
        self._cur_ani.setStartValue(QPoint(0, 0))
        self._cur_ani.setEndValue(QPoint(cur_end_x, 0))
        self._cur_ani.setEasingCurve(curve)

        self._next_ani.setTargetObject(next_widget)
        self._next_ani.setDuration(anim_duration)
        self._next_ani.setStartValue(QPoint(next_start_x, 0))
        self._next_ani.setEndValue(QPoint(0, 0))
        self._next_ani.setEasingCurve(curve)

        self._ani_group.start()

    def _on_ani_finished(self) -> None:
        target_index = self._next_index
        self._next_index = None
        if target_index is not None and 0 <= target_index < self.count():
            super().setCurrentIndex(target_index)
        for i in range(self.count()):
            widget = self.widget(i)
            if widget is not None:
                widget.move(0, 0)


def build_dashboard_page_ui(page: Any) -> None:
    root_layout = QVBoxLayout(page)
    root_layout.setContentsMargins(0, 0, 0, 0)
    root_layout.setSpacing(0)

    main_stack = HorizontalSlideStackedWidget(page)
    main_stack.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    main_stack.setAutoFillBackground(False)
    main_stack.setStyleSheet(
        "HorizontalSlideStackedWidget { background: transparent; border: none; }"
    )
    page.main_stack = main_stack
    root_layout.addWidget(main_stack, 1)

    home_view = QWidget(main_stack)
    home_view.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    home_view.setAutoFillBackground(False)
    page.home_view = home_view
    outer = QVBoxLayout(home_view)
    outer.setContentsMargins(24, 14, 24, 18)

    scroll = ScrollArea(home_view)
    scroll.setWidgetResizable(True)
    inner = QWidget(home_view)
    inner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    inner.setAutoFillBackground(False)
    scroll.setWidget(inner)
    scroll.enableTransparentBackground()
    scroll.viewport().setAutoFillBackground(False)
    scroll.viewport().setStyleSheet("background: transparent;")
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    actions_row = QHBoxLayout()
    actions_row.setContentsMargins(0, 0, 0, 0)
    actions_row.addStretch(1)
    page.config_command_bar = CommandBar(inner)
    page.config_command_bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    page.config_list_action = Action(FluentIcon.MENU, "配置列表", page.config_command_bar)
    page.load_cfg_action = Action(FluentIcon.DOCUMENT, "载入配置", page.config_command_bar)
    page.save_cfg_action = Action(FluentIcon.SAVE, "保存配置", page.config_command_bar)
    page.config_command_bar.addActions(
        [page.config_list_action, page.load_cfg_action, page.save_cfg_action]
    )
    page.config_command_bar.resizeToSuitableWidth()
    actions_row.addWidget(page.config_command_bar)
    layout.addLayout(actions_row)

    content = QWidget(inner)
    content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    content.setAutoFillBackground(False)
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(0)
    content_layout.addStretch(1)

    entry_row = QHBoxLayout()
    entry_row.setContentsMargins(0, 0, 0, 0)
    entry_row.addStretch(1)

    entry_container = QWidget(content)
    entry_container.setAcceptDrops(True)
    entry_container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    entry_container.setStyleSheet("background: transparent; border: none;")
    entry_container.setMaximumWidth(760)
    entry_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    entry_layout = QVBoxLayout(entry_container)
    entry_layout.setContentsMargins(0, 0, 0, 0)
    entry_layout.setSpacing(20)

    url_edit = LineEdit(entry_container)
    url_edit.setPlaceholderText("在此拖入/粘贴问卷二维码图片或输入问卷链接")
    url_edit.setClearButtonEnabled(True)
    url_edit.setAcceptDrops(True)
    url_edit.setFixedHeight(50)
    url_font = url_edit.font()
    url_font.setPointSize(11)
    url_edit.setFont(url_font)
    paste_only_menu = PasteOnlyMenu(entry_container)
    url_edit.installEventFilter(paste_only_menu)
    entry_layout.addWidget(url_edit)

    action_row = QHBoxLayout()
    action_row.setContentsMargins(0, 0, 0, 0)
    action_row.setSpacing(16)
    action_row.addStretch(1)

    qr_btn = PushButton(FluentIcon.QRCODE, "上传二维码", entry_container)
    qr_btn.setFixedHeight(44)
    qr_btn.setMinimumWidth(148)
    qr_btn.setIconSize(QSize(18, 18))
    qr_btn.setToolTip("上传问卷二维码图片")
    install_tooltip_filter(qr_btn)
    action_row.addWidget(qr_btn)

    parse_btn = PrimaryPushButton(FluentIcon.PLAY, "自动配置问卷", entry_container)
    parse_btn.setFixedHeight(44)
    parse_btn.setMinimumWidth(176)
    parse_btn.setIconSize(QSize(18, 18))
    action_row.addWidget(parse_btn)

    action_row.addStretch(1)
    entry_layout.addLayout(action_row)

    page.link_card = entry_container
    page.qr_btn = qr_btn
    page.url_edit = url_edit
    page.parse_btn = parse_btn
    page._paste_only_menu = paste_only_menu
    page._link_entry_widgets = (entry_container, qr_btn, url_edit, parse_btn)
    for widget in page._link_entry_widgets:
        widget.installEventFilter(page)

    entry_row.addWidget(entry_container, 8)
    entry_row.addStretch(1)
    content_layout.addLayout(entry_row)

    content_layout.addStretch(1)
    layout.addWidget(content, 1)
    outer.addWidget(scroll, 1)

    wizard_host = QWidget(main_stack)
    wizard_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    wizard_host.setAutoFillBackground(False)
    wizard_host_layout = QVBoxLayout(wizard_host)
    wizard_host_layout.setContentsMargins(0, 0, 0, 0)
    wizard_host_layout.setSpacing(0)
    page.wizard_host = wizard_host

    run_setup_host = QWidget(main_stack)
    run_setup_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    run_setup_host.setAutoFillBackground(False)
    run_setup_host_layout = QVBoxLayout(run_setup_host)
    run_setup_host_layout.setContentsMargins(0, 0, 0, 0)
    run_setup_host_layout.setSpacing(0)
    run_setup_panel = DashboardRunSetupPanel(page, run_setup_host)
    run_setup_host_layout.addWidget(run_setup_panel, 1)
    page.run_setup_host = run_setup_host
    page.run_setup_panel = run_setup_panel

    run_setup_panel.backRequested.connect(page._reopen_inline_wizard_from_run_setup)
    run_setup_panel.startRequested.connect(lambda: page._on_start_clicked())

    main_stack.addWidget(home_view)
    main_stack.addWidget(wizard_host)
    main_stack.addWidget(run_setup_host)
    main_stack.setCurrentWidget(home_view)
