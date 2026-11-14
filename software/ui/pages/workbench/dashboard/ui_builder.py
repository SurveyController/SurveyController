from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    CommandBar,
    FluentIcon,
    ScrollArea,
    TitleLabel,
)

from software.ui.pages.workbench.shared.survey_entry_card import SurveyEntryCard


def build_dashboard_page_ui(page: Any) -> None:
    root_layout = QVBoxLayout(page)
    root_layout.setContentsMargins(0, 0, 0, 0)
    root_layout.setSpacing(0)

    main_stack = QStackedWidget(page)
    main_stack.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    main_stack.setAutoFillBackground(False)
    main_stack.setStyleSheet("QStackedWidget { background: transparent; border: none; }")
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
    content_layout.addStretch(2)

    title_label = TitleLabel("SurveyController", content)
    title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    content_layout.addWidget(title_label)
    content_layout.addSpacing(8)

    subtitle_label = BodyLabel("输入问卷链接，或拖入 / 粘贴问卷二维码图片开始配置", content)
    subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    subtitle_label.setTextColor(QColor(96, 96, 96), QColor(175, 175, 175))
    content_layout.addWidget(subtitle_label)
    content_layout.addSpacing(28)

    entry_row = QHBoxLayout()
    entry_row.setContentsMargins(0, 0, 0, 0)
    entry_row.addStretch(1)
    entry = SurveyEntryCard(
        content,
        event_filter_owner=page,
        show_parse_button=True,
        parse_inline=True,
        flat=True,
    )
    entry.setMaximumWidth(680)
    entry.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    page.link_card = entry
    page.qr_btn = entry.qr_btn
    page.url_edit = entry.url_edit
    if entry.parse_btn is None:
        raise RuntimeError("SurveyEntryCard 缺少解析按钮，无法初始化主页入口")
    page.parse_btn = entry.parse_btn
    page._link_entry_widgets = entry.entry_widgets()
    entry_row.addWidget(entry, 8)
    entry_row.addStretch(1)
    content_layout.addLayout(entry_row)
    content_layout.addSpacing(14)

    hint_label = CaptionLabel("支持问卷星 · 腾讯问卷 · Credamo", content)
    hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    hint_label.setTextColor(QColor(120, 120, 120), QColor(135, 135, 135))
    content_layout.addWidget(hint_label)

    content_layout.addStretch(3)
    layout.addWidget(content, 1)
    outer.addWidget(scroll, 1)

    wizard_host = QWidget(main_stack)
    wizard_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    wizard_host.setAutoFillBackground(False)
    wizard_host_layout = QVBoxLayout(wizard_host)
    wizard_host_layout.setContentsMargins(0, 0, 0, 0)
    wizard_host_layout.setSpacing(0)
    page.wizard_host = wizard_host

    main_stack.addWidget(home_view)
    main_stack.addWidget(wizard_host)
    main_stack.setCurrentWidget(home_view)
