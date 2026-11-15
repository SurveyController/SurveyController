from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    IconWidget,
    InfoBarIcon,
    InfoBarPosition,
    StrongBodyLabel,
    TransparentToolButton,
    isDarkTheme,
)


class FullWidthInfoBar(QFrame):
    closedSignal = Signal()

    def __init__(
        self,
        icon,
        title,
        content,
        orient=Qt.Orientation.Horizontal,
        isClosable=True,
        duration=-1,
        position=InfoBarPosition.NONE,
        parent=None,
    ):
        super().__init__(parent)
        self.icon = icon
        self.title = str(title or "")
        self.content = str(content or "")
        self.position = position
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.hBoxLayout = QHBoxLayout(self)
        self.hBoxLayout.setContentsMargins(12, 10, 12, 10)
        self.hBoxLayout.setSpacing(10)
        self.iconWidget = IconWidget(icon, self)
        self.iconWidget.setFixedSize(18, 18)
        self.hBoxLayout.addWidget(self.iconWidget, 0, Qt.AlignmentFlag.AlignTop)
        self.textLayout = QVBoxLayout()
        self.textLayout.setContentsMargins(0, 0, 0, 0)
        self.textLayout.setSpacing(3)
        self.titleLabel = StrongBodyLabel(self.title, self)
        self.contentLabel = BodyLabel(self.content, self)
        for label in (self.titleLabel, self.contentLabel):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.textLayout.addWidget(label)
        self.titleLabel.setVisible(bool(self.title))
        self.contentLabel.setVisible(bool(self.content))
        self.hBoxLayout.addLayout(self.textLayout, 1)
        self.widgetLayout = QHBoxLayout() if orient == Qt.Orientation.Horizontal else QVBoxLayout()
        self.widgetLayout.setContentsMargins(0, 0, 0, 0)
        self.widgetLayout.setSpacing(8)
        if orient == Qt.Orientation.Horizontal:
            self.hBoxLayout.addLayout(self.widgetLayout)
        else:
            self.textLayout.addLayout(self.widgetLayout)
        self.closeButton = TransparentToolButton(FluentIcon.CLOSE, self)
        self.closeButton.setFixedSize(24, 24)
        self.closeButton.setVisible(isClosable)
        self.closeButton.clicked.connect(self.close)
        self.hBoxLayout.addWidget(self.closeButton, 0, Qt.AlignmentFlag.AlignTop)
        self._background_colors = None
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.close)
        self._duration = duration

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.StyleChange,
        }:
            self.update()

    def addWidget(self, widget, stretch=0):
        self.widgetLayout.addWidget(widget, stretch)
        self.updateGeometry()

    def setTitle(self, title):
        self.title = str(title or "")
        self.titleLabel.setText(self.title)
        self.titleLabel.setVisible(bool(self.title))
        self.updateGeometry()

    def setContent(self, content):
        self.content = str(content or "")
        self.contentLabel.setText(self.content)
        self.contentLabel.setVisible(bool(self.content))
        self.updateGeometry()

    def setCustomBackgroundColor(self, light, dark):
        self._background_colors = (QColor(light), QColor(dark))
        self.update()

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(min(hint.width(), 640), hint.height())

    def showEvent(self, event):
        super().showEvent(event)
        if self._duration >= 0:
            self._dismiss_timer.start(self._duration)

    def closeEvent(self, event):
        self._dismiss_timer.stop()
        self.hide()
        self.closedSignal.emit()
        self.deleteLater()
        event.accept()

    def paintEvent(self, event):
        colors = {
            InfoBarIcon.SUCCESS: ("#dff6dd", "#393d1b"),
            InfoBarIcon.WARNING: ("#fff4ce", "#433519"),
            InfoBarIcon.ERROR: ("#fde7e9", "#442726"),
        }.get(self.icon, ("#f4f4f4", "#2e2e2e"))
        color = (self._background_colors or colors)[int(isDarkTheme())]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(self.rect(), 6, 6)
