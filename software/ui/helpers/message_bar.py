from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtWidgets import QLayout
from qfluentwidgets import InfoBar as FluentInfoBar
from qfluentwidgets import InfoBarManager, InfoBarPosition, TextWrap
from shiboken6 import isValid


class InfoBar(FluentInfoBar):
    def __init__(
        self,
        icon,
        title,
        content,
        orient=Qt.Orientation.Horizontal,
        isClosable=True,
        duration=1000,
        position=InfoBarPosition.TOP_RIGHT,
        parent=None,
    ):
        super().__init__(
            icon=icon,
            title=title,
            content=content,
            orient=orient,
            isClosable=isClosable,
            duration=duration,
            position=position,
            parent=parent,
        )
        self.hBoxLayout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

    def _adjustText(self):
        parent = self.parentWidget()
        max_w = 640 if parent is None else max(200, min(640, parent.width() - 32))
        avail = max(110, max_w - 120)
        if self.orient == Qt.Orientation.Horizontal and self.title:
            title_w = self.titleLabel.fontMetrics().horizontalAdvance(self.title)
            avail = max(110, avail - min(title_w + 16, avail // 2))
        title_chars = max(int((max_w - 120) / 7), 16)
        content_chars = max(int(avail / 7), 16)
        self.titleLabel.setText(TextWrap.wrap(self.title, title_chars, False)[0])
        self.contentLabel.setText(TextWrap.wrap(self.content, content_chars, False)[0])
        self.adjustSize()

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
        target_parent = parent if position == InfoBarPosition.NONE else (parent.window() or parent)
        w = cls(
            icon,
            title,
            content,
            orient=orient,
            isClosable=isClosable,
            duration=duration,
            position=position,
            parent=target_parent,
        )
        w.show()
        return w


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
    if bar is None or not isValid(bar):
        return
    bar.adjustSize()
    if bar.position == InfoBarPosition.NONE or bar.parentWidget() is None:
        return
    manager = InfoBarManager.make(bar.position)
    bars = manager.infoBars.get(bar.parentWidget())
    if not bars or bar not in bars:
        return
    target = manager._pos(bar)
    slide_ani = bar.property("slideAni")
    if slide_ani is not None and slide_ani.state() == QAbstractAnimation.State.Running:
        slide_ani.setEndValue(target)
    else:
        bar.move(target)
