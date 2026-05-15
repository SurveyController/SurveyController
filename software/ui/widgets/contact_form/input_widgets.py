"""联系表单专用输入控件。"""

from typing import Callable, Optional

from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    Action,
    FluentIcon,
    LineEdit,
    PlainTextEdit,
    RoundMenu,
)


class PasteOnlyLineEdit(LineEdit):
    """只显示 Fluent 风格“复制 / 粘贴 / 全选”菜单的 LineEdit。"""

    def __init__(self, parent=None, on_paste: Optional[Callable[[QWidget], bool]] = None):
        super().__init__(parent)
        self._on_paste = on_paste

    def contextMenuEvent(self, e):
        menu = RoundMenu(parent=self)
        copy_action = Action(FluentIcon.COPY, "复制", parent=menu)
        copy_action.setEnabled(self.hasSelectedText())
        copy_action.triggered.connect(self.copy)
        paste_action = Action(FluentIcon.PASTE, "粘贴", parent=menu)

        def _do_paste():
            if self._on_paste and self._on_paste(self):
                return
            self.paste()

        menu.addAction(copy_action)
        paste_action.triggered.connect(_do_paste)
        menu.addAction(paste_action)
        menu.exec(e.globalPos())
        e.accept()


class PasteOnlyPlainTextEdit(PlainTextEdit):
    """只显示 Fluent 风格“复制 / 粘贴 / 全选”菜单的 PlainTextEdit。"""

    def __init__(self, parent=None, on_paste: Optional[Callable[[QWidget], bool]] = None):
        super().__init__(parent)
        self._on_paste = on_paste

    def contextMenuEvent(self, e):
        menu = RoundMenu(parent=self)
        copy_action = Action(FluentIcon.COPY, "复制", parent=menu)
        copy_action.setEnabled(self.textCursor().hasSelection())
        copy_action.triggered.connect(self.copy)
        paste_action = Action(FluentIcon.PASTE, "粘贴", parent=menu)

        def _do_paste():
            if self._on_paste and self._on_paste(self):
                return
            self.paste()

        menu.addAction(copy_action)
        paste_action.triggered.connect(_do_paste)
        menu.addAction(paste_action)
        menu.exec(e.globalPos())
        e.accept()
