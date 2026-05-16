"""可点击卡片组件。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QWidget
from qfluentwidgets import ElevatedCardWidget


class ClickableElevatedCardWidget(ElevatedCardWidget):
    """支持忽略指定子控件点击的卡片。"""

    backgroundClicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ignored_click_widgets: list[QWidget] = []

    def set_ignored_click_widgets(self, widgets: list[QWidget]) -> None:
        self._ignored_click_widgets = [widget for widget in widgets if widget is not None]

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self._is_background_click(e.position().toPoint()):
            self.backgroundClicked.emit()
            e.accept()
            return
        super().mousePressEvent(e)

    def _is_background_click(self, pos: QPoint) -> bool:
        target = self.childAt(pos)
        while target is not None and target is not self:
            if any(target is ignored for ignored in self._ignored_click_widgets):
                return False
            target = target.parentWidget()
        return True
