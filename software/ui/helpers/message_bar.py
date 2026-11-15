from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import InfoBarIcon, InfoBarPosition
from shiboken6 import isValid

from software.ui.widgets.full_width_infobar import FullWidthInfoBar


class _NotificationStack(QWidget):
    def __init__(self, parent, position):
        super().__init__(parent)
        self.position = position
        self.setObjectName(f"notificationStack{position.name}")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(12)
        parent.installEventFilter(self)

    def add_bar(self, bar):
        self._layout.addWidget(bar)
        bar.closedSignal.connect(lambda: self.remove_bar(bar))
        bar.show()
        self.relayout()
        self.show()
        self.raise_()

    def remove_bar(self, bar):
        self._layout.removeWidget(bar)
        if self._layout.count():
            self.relayout()
        else:
            self.hide()

    def relayout(self):
        parent = self.parentWidget()
        if parent is None:
            return
        width = max(1, min(640, parent.width() - 32))
        bars = []
        for index in range(self._layout.count()):
            item = self._layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is not None:
                bars.append(widget)
        self._layout.activate()
        height = sum(max(bar.minimumSizeHint().height(), bar.sizeHint().height()) for bar in bars)
        height += max(0, len(bars) - 1) * self._layout.spacing()
        if self.position in {InfoBarPosition.TOP_LEFT, InfoBarPosition.BOTTOM_LEFT}:
            x = 16
        elif self.position in {InfoBarPosition.TOP_RIGHT, InfoBarPosition.BOTTOM_RIGHT}:
            x = parent.width() - width - 16
        else:
            x = (parent.width() - width) // 2
        bottom = self.position in {
            InfoBarPosition.BOTTOM,
            InfoBarPosition.BOTTOM_LEFT,
            InfoBarPosition.BOTTOM_RIGHT,
        }
        y = parent.height() - height - 16 if bottom else 16
        self.setGeometry(max(0, x), max(0, y), width, height)

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest:
            self.relayout()
        return result

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.WindowStateChange,
        }:
            self.relayout()
        return super().eventFilter(watched, event)


class InfoBar(FullWidthInfoBar):
    @classmethod
    def new(
        cls,
        icon,
        title,
        content,
        orient=Qt.Orientation.Horizontal,
        isClosable=True,
        duration=1000,
        position=InfoBarPosition.TOP_RIGHT,
        parent=None,
    ):
        if parent is None:
            raise ValueError("通知必须指定所属窗口")
        if position == InfoBarPosition.NONE:
            bar = cls(icon, title, content, orient, isClosable, duration, position, parent)
            bar.show()
            return bar
        parent = parent.window()
        name = f"notificationStack{position.name}"
        stack = parent.findChild(
            _NotificationStack, name, Qt.FindChildOption.FindDirectChildrenOnly
        )
        if stack is None:
            stack = _NotificationStack(parent, position)
        bar = cls(icon, title, content, orient, isClosable, duration, position, stack)
        stack.add_bar(bar)
        return bar

    @classmethod
    def info(cls, title, content, **kwargs):
        return cls.new(InfoBarIcon.INFORMATION, title, content, **kwargs)

    @classmethod
    def success(cls, title, content, **kwargs):
        return cls.new(InfoBarIcon.SUCCESS, title, content, **kwargs)

    @classmethod
    def warning(cls, title, content, **kwargs):
        return cls.new(InfoBarIcon.WARNING, title, content, **kwargs)

    @classmethod
    def error(cls, title, content, **kwargs):
        return cls.new(InfoBarIcon.ERROR, title, content, **kwargs)


def show_message_bar(
    *,
    parent,
    message,
    level="info",
    title="",
    position=InfoBarPosition.TOP,
    duration=2000,
):
    kind = str(level or "info").strip().lower()
    factory = {
        "success": InfoBar.success,
        "warning": InfoBar.warning,
        "error": InfoBar.error,
        "info": InfoBar.info,
    }.get(kind, InfoBar.info)
    return factory(title, message, parent=parent, position=position, duration=duration)


def replace_message_bar(current):
    if current is not None and isValid(current):
        current.close()


def reposition_message_bar(bar):
    if bar is not None and isValid(bar):
        parent = bar.parentWidget()
        stack = parent if isinstance(parent, _NotificationStack) else parent.parentWidget()
        if isinstance(stack, _NotificationStack):
            stack.relayout()
