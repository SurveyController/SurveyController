from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLayout, QSizePolicy
from qfluentwidgets import InfoBar, InfoBarPosition


class FullWidthInfoBar(InfoBar):
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
        super().__init__(
            icon=icon,
            title=str(title or ""),
            content=str(content or ""),
            orient=orient,
            isClosable=isClosable,
            duration=duration,
            position=position,
            parent=parent,
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        self.hBoxLayout.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
        self.textLayout.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
        self.hBoxLayout.setStretchFactor(self.textLayout, 1)
        for label in (self.titleLabel, self.contentLabel):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._adjustText()

    def _adjustText(self):
        self.titleLabel.setText(str(self.title or ""))
        self.titleLabel.setVisible(bool(self.title))
        self.contentLabel.setText(str(self.content or ""))
        self.contentLabel.setVisible(bool(self.content))
        self.updateGeometry()

    def setTitle(self, title):
        self.title = str(title or "")
        self._adjustText()

    def setContent(self, content):
        self.content = str(content or "")
        self._adjustText()
