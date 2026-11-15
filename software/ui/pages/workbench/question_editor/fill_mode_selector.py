from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRegularExpression, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget
from qfluentwidgets import BodyLabel, ComboBox, FluentIcon, LineEdit

from .utils import _apply_label_color

FILL_MODE_NONE = "none"
FILL_MODE_AI = "ai"
FILL_MODE_NAME = "name"
FILL_MODE_MOBILE = "mobile"
FILL_MODE_ID_CARD = "id_card"
FILL_MODE_INTEGER = "integer"

_MODE_TO_GROUP_ID = {
    FILL_MODE_NONE: 0,
    FILL_MODE_AI: 0,
    FILL_MODE_NAME: 1,
    FILL_MODE_MOBILE: 2,
    FILL_MODE_ID_CARD: 3,
    FILL_MODE_INTEGER: 4,
}


class _ModeGroupProxy:
    def __init__(self, selector: FillModeSelector) -> None:
        self._selector = selector

    def checkedId(self) -> int:
        return _MODE_TO_GROUP_ID.get(self._selector.current_mode(), 0)


class _AiFlagProxy:
    def __init__(self, selector: FillModeSelector) -> None:
        self._selector = selector

    def isChecked(self) -> bool:
        return self._selector.current_mode() == FILL_MODE_AI


class FillModeSelector(QWidget):
    modeChanged = Signal(str)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        list_label: str = "答案列表",
        leading_label: Optional[str] = None,
        leading_width: int = 48,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        self._current_mode = FILL_MODE_NONE
        self._group_proxy = _ModeGroupProxy(self)
        self._ai_proxy = _AiFlagProxy(self)

        self._row_layout = QHBoxLayout(self)
        self._row_layout.setContentsMargins(0, 0, 0, 0)
        self._row_layout.setSpacing(8)

        if leading_label is not None:
            label = BodyLabel(leading_label, self)
            label.setFixedWidth(leading_width)
            label.setStyleSheet("font-size: 12px;")
            _apply_label_color(label, "#666666", "#bfbfbf")
            self._row_layout.addWidget(label)

        self.combo = ComboBox(self)
        self.combo.setFixedWidth(134)
        modes = (
            (FILL_MODE_NONE, list_label, FluentIcon.EDIT),
            (FILL_MODE_AI, "AI 生成", FluentIcon.ROBOT),
            (FILL_MODE_NAME, "随机姓名", FluentIcon.PEOPLE),
            (FILL_MODE_MOBILE, "随机手机号", FluentIcon.PHONE),
            (FILL_MODE_ID_CARD, "随机身份证", FluentIcon.CERTIFICATE),
            (FILL_MODE_INTEGER, "随机整数", FluentIcon.TAG),
        )
        for route_key, text, icon in modes:
            self.combo.addItem(text, icon=icon, userData=route_key)
        self._row_layout.addWidget(self.combo)

        self.range_widget = QWidget(self)
        self.range_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.range_widget.setAutoFillBackground(False)
        range_layout = QHBoxLayout(self.range_widget)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.setSpacing(6)

        self.min_edit = self._create_int_edit(min_value, "最小值")
        self.max_edit = self._create_int_edit(max_value, "最大值")
        sep = BodyLabel("—", self.range_widget)
        sep.setStyleSheet("font-size: 12px;")
        _apply_label_color(sep, "#666666", "#a6a6a6")

        range_layout.addWidget(self.min_edit)
        range_layout.addWidget(sep)
        range_layout.addWidget(self.max_edit)
        self._row_layout.addWidget(self.range_widget)

        self._trailing_spacer = QWidget(self)
        self._trailing_spacer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._trailing_spacer.setAutoFillBackground(False)
        self._trailing_spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored
        )
        self._row_layout.addWidget(self._trailing_spacer, 1)

        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        self.set_mode(FILL_MODE_NONE, emit=False)

    def add_inline_widget(self, widget: QWidget, stretch: int = 0) -> None:
        insert_pos = max(0, self._row_layout.count() - 1)
        self._row_layout.insertWidget(insert_pos, widget, stretch)

    def set_trailing_stretch(self, enabled: bool) -> None:
        self._trailing_spacer.setVisible(enabled)

    def _create_int_edit(self, initial_value: Optional[int], placeholder: str) -> LineEdit:
        edit = LineEdit(self.range_widget)
        edit.setFixedWidth(84)
        edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        edit.setPlaceholderText(placeholder)
        edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"-?\d*"), edit))
        if initial_value is not None:
            edit.setText(str(int(initial_value)))
        return edit

    def _on_combo_changed(self, _index: int) -> None:
        route_key = str(self.combo.currentData() or FILL_MODE_NONE)
        normalized = route_key if route_key in _MODE_TO_GROUP_ID else FILL_MODE_NONE
        if normalized == self._current_mode:
            return
        self._current_mode = normalized
        self.range_widget.setVisible(normalized == FILL_MODE_INTEGER)
        self.modeChanged.emit(normalized)

    def current_mode(self) -> str:
        return self._current_mode

    def random_mode(self) -> str:
        return FILL_MODE_NONE if self._current_mode == FILL_MODE_AI else self._current_mode

    def is_ai_enabled(self) -> bool:
        return self._current_mode == FILL_MODE_AI

    def set_mode(self, mode: str, *, emit: bool = False) -> None:
        normalized = mode if mode in _MODE_TO_GROUP_ID else FILL_MODE_NONE
        self._current_mode = normalized
        idx = self.combo.findData(normalized)
        with QSignalBlocker(self.combo):
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
        self.range_widget.setVisible(normalized == FILL_MODE_INTEGER)
        if emit:
            self.modeChanged.emit(normalized)

    def group_proxy(self) -> _ModeGroupProxy:
        return self._group_proxy

    def ai_proxy(self) -> _AiFlagProxy:
        return self._ai_proxy
