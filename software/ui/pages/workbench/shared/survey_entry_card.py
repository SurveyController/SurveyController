"""Shared survey URL and QR-code entry card."""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QVBoxLayout, QWidget
from qfluentwidgets import (
    CardWidget,
    FluentIcon,
    LineEdit,
    PrimaryPushButton,
    ToolButton,
)

from software.ui.helpers.fluent_tooltip import install_tooltip_filter
from software.ui.widgets.paste_only_menu import PasteOnlyMenu


class SurveyEntryCard(CardWidget):
    """Card containing the common survey URL field and QR image entry."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        event_filter_owner: QWidget | None = None,
        trailing_widget: QWidget | None = None,
        show_parse_button: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._event_filter_owner = event_filter_owner
        self._trailing_widget = trailing_widget
        self._show_parse_button = bool(show_parse_button)
        self._build_ui()
        self._install_entry_filters()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        entry_row = QHBoxLayout()
        entry_row.setSpacing(8)

        self.qr_btn = ToolButton(self)
        self.qr_btn.setIcon(FluentIcon.QRCODE)
        self.qr_btn.setFixedSize(36, 36)
        self.qr_btn.setToolTip("上传问卷二维码图片")
        install_tooltip_filter(self.qr_btn)
        entry_row.addWidget(self.qr_btn)

        self.url_edit = LineEdit(self)
        self.url_edit.setPlaceholderText("在此拖入/粘贴问卷二维码图片或输入问卷链接")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.setAcceptDrops(True)
        self._paste_only_menu = PasteOnlyMenu(self)
        self.url_edit.installEventFilter(self._paste_only_menu)
        entry_row.addWidget(self.url_edit, 1)

        if self._trailing_widget is not None:
            entry_row.addWidget(self._trailing_widget)

        layout.addLayout(entry_row)

        self.parse_btn: PrimaryPushButton | None = None
        if self._show_parse_button:
            button_row = QHBoxLayout()
            button_row.setSpacing(8)
            self.parse_btn = PrimaryPushButton(FluentIcon.PLAY, "自动配置问卷", self)
            button_row.addWidget(self.parse_btn)
            button_row.addStretch(1)
            layout.addLayout(button_row)

    def entry_widgets(self) -> tuple[QWidget, ...]:
        widgets: list[QWidget] = [self, self.qr_btn, self.url_edit]
        if self._trailing_widget is not None:
            widgets.append(self._trailing_widget)
            widgets.extend(self._tool_buttons_in(self._trailing_widget))
        if self.parse_btn is not None:
            widgets.append(self.parse_btn)
        return tuple(widgets)

    @staticmethod
    def _tool_buttons_in(widget: QWidget) -> Iterable[QWidget]:
        return tuple(widget.findChildren(QToolButton))

    def _install_entry_filters(self) -> None:
        owner = self._event_filter_owner
        if owner is None:
            return
        for widget in self.entry_widgets():
            if widget is self.url_edit:
                self.url_edit.installEventFilter(owner)
                continue
            widget.installEventFilter(owner)
