"""只保留粘贴项的输入框右键菜单。"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QContextMenuEvent
from qfluentwidgets import Action, FluentIcon, LineEdit, RoundMenu


class PasteOnlyMenu(QObject):
    """把输入框右键菜单收敛为单独的“粘贴”操作。"""

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ContextMenu and isinstance(watched, LineEdit):
            if isinstance(event, QContextMenuEvent):
                menu = RoundMenu(parent=watched)
                paste_action = Action(FluentIcon.PASTE, "粘贴", parent=menu)
                paste_action.triggered.connect(watched.paste)
                menu.addAction(paste_action)
                menu.exec(event.globalPos())
                return True
        return super().eventFilter(watched, event)
