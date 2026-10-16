from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QPointF,
    Property,
    QPropertyAnimation,
    QRectF,
    QTimer,
    Qt,
)
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget
from qfluentwidgets import isDarkTheme, themeColor


class ChartOverlay(QWidget):
    def __init__(self, parent=None, curve_y_fn=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._current_x = -1.0
        self._current_y = -1.0
        self._target_x = -1.0
        self._target_y = -1.0
        self.date_str = ""
        self.ip_count = 0
        self.plot_area = QRectF()
        self._opacity = 0.0
        self._curve_y_fn = curve_y_fn
        self._anim = QPropertyAnimation(self, QByteArray(b"opacity"), self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._smooth_timer = QTimer(self)
        self._smooth_timer.setInterval(16)
        self._smooth_timer.timeout.connect(self._smooth_step)

    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, value):
        self._opacity = value
        self.update()

    opacity = cast(Any, Property)(float, _get_opacity, _set_opacity)

    def _smooth_step(self):
        dx = self._target_x - self._current_x
        dy = self._target_y - self._current_y
        if abs(dx) < 0.5 and abs(dy) < 0.5:
            self._current_x = self._target_x
            self._current_y = self._target_y
            self._smooth_timer.stop()
        else:
            self._current_x += dx * 0.2
            if self._curve_y_fn:
                cy = self._curve_y_fn(self._current_x)
                self._current_y = cy if cy is not None else self._current_y + dy * 0.2
            else:
                self._current_y += dy * 0.2
        self.update()

    def update_point(self, x, y, date_str, ip_count, plot_area):
        self.date_str = date_str
        self.ip_count = ip_count
        self.plot_area = plot_area
        self._target_x = float(x)
        self._target_y = float(y)
        if self._opacity < 0.01:
            self._current_x = self._target_x
            self._current_y = self._target_y
        if not self._smooth_timer.isActive():
            self._smooth_timer.start()
        self._anim.stop()
        self._anim.setStartValue(self._opacity)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def hide_line(self):
        self._smooth_timer.stop()
        self._anim.stop()
        self._anim.setStartValue(self._opacity)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def paintEvent(self, event):
        _ = event
        if self._opacity < 0.01 or not self.plot_area.isValid():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)

        top_y = self.plot_area.top()
        bottom_y = self.plot_area.bottom()
        accent = themeColor()

        painter.setPen(QPen(accent, 1.5, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(self._current_x, top_y), QPointF(self._current_x, bottom_y))

        painter.setPen(QPen(accent, 2.5))
        painter.setBrush(QColor(255, 255, 255) if not isDarkTheme() else QColor(30, 30, 30))
        painter.drawEllipse(QPointF(self._current_x, self._current_y), 5, 5)

        text1 = f"{self.date_str}"
        text2 = f"提取数量: {self.ip_count}"
        font = self.font()
        font.setPointSize(10)
        painter.setFont(font)
        fm = painter.fontMetrics()
        box_w = max(fm.horizontalAdvance(text1), fm.horizontalAdvance(text2)) + 32
        box_h = fm.height() * 2 + 20

        box_x = self._current_x + 12
        if box_x + box_w > self.width() - 10:
            box_x = self._current_x - box_w - 12
        box_y = self._current_y - box_h / 2
        if box_y < top_y:
            box_y = top_y
        if box_y + box_h > bottom_y:
            box_y = bottom_y - box_h

        dark = isDarkTheme()
        bg_col = QColor(43, 43, 43, 245) if dark else QColor(255, 255, 255, 245)
        border_col = QColor(255, 255, 255, 20) if dark else QColor(0, 0, 0, 20)
        text_col1 = QColor(200, 200, 200) if dark else QColor(100, 100, 100)
        text_col2 = QColor(255, 255, 255) if dark else QColor(30, 30, 30)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40 if not dark else 80))
        painter.drawRoundedRect(QRectF(box_x + 2, box_y + 3, box_w, box_h), 8, 8)

        painter.setPen(QPen(border_col, 1))
        painter.setBrush(QBrush(bg_col))
        painter.drawRoundedRect(QRectF(box_x, box_y, box_w, box_h), 8, 8)

        painter.setPen(text_col1)
        painter.drawText(int(box_x + 16), int(box_y + 10 + fm.ascent()), text1)
        painter.setPen(text_col2)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            int(box_x + 16),
            int(box_y + 10 + fm.height() + 6 + fm.ascent()),
            text2,
        )
