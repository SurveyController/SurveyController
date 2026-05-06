"""工作台概览页专用卡片组件。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    FluentIcon,
    IconWidget,
    PushButton,
)


class DashboardActionCard(CardWidget):
    """首页快捷入口卡片。"""

    openRequested = Signal()

    def __init__(
        self,
        title: str,
        description: str,
        button_text: str,
        icon: FluentIcon,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName(f"{title}ActionCard")
        self.setMinimumHeight(62)
        self.setMaximumHeight(62)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.icon_panel = QWidget(self)
        self.icon_panel.setFixedSize(32, 32)
        self.icon_panel.setStyleSheet(
            "QWidget { background-color: rgba(0, 120, 212, 0.12); border-radius: 10px; }"
        )
        icon_panel_layout = QVBoxLayout(self.icon_panel)
        icon_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.icon_widget = IconWidget(icon, self.icon_panel)
        self.icon_widget.setFixedSize(16, 16)
        icon_panel_layout.addWidget(self.icon_widget, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_panel, 0, Qt.AlignmentFlag.AlignVCenter)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        self.title_label = BodyLabel(title, self)
        self.title_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        text_layout.addWidget(self.title_label)
        self.description_label = BodyLabel(description, self)
        self.description_label.setStyleSheet("color: #6b6b6b; font-size: 11px;")
        self.description_label.setWordWrap(True)
        text_layout.addWidget(self.description_label)
        layout.addLayout(text_layout, 1)

        self.open_button = PushButton(button_text, self)
        self.open_button.setFixedSize(76, 30)
        self.open_button.setStyleSheet("font-size: 12px;")
        self.open_button.clicked.connect(self.openRequested.emit)
        layout.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignVCenter)


class RuntimeSettingsHintCard(DashboardActionCard):
    """首页上的运行参数跳转提示卡。"""

    def __init__(self, parent=None):
        super().__init__(
            title="运行参数",
            description="更多设置请前往“运行参数”页仔细调整",
            button_text="打开",
            icon=FluentIcon.DEVELOPER_TOOLS,
            parent=parent,
        )
