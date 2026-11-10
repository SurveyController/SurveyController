from __future__ import annotations

from typing import cast

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    InfoBar,
    InfoBarIcon,
    InfoBarPosition,
    PushButton,
    SearchLineEdit,
    TransparentPushButton,
)
from surveycore.core.questions.config import QuestionEntry

from .multilevel_distribution import MultilevelDistributionWidget
from .multilevel_paths import MultilevelPaths


class MultilevelDropdownEditor(QWidget):
    def __init__(self, entry: QuestionEntry, option_texts: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        raw = entry.custom_weights or entry.probabilities
        weights = (
            [max(0.0, float(value)) for value in cast(list[float], raw)]
            if isinstance(raw, list)
            else []
        )
        weights = (weights + [1.0] * entry.option_count)[: entry.option_count]
        self.paths = MultilevelPaths(option_texts, weights)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(12)
        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText("搜索分支或选项")
        self.search_edit.setAccessibleName("搜索分支或选项")
        layout.addWidget(self.search_edit)
        tools = QHBoxLayout()
        self.only_selected = CheckBox("仅看已选", self)
        tools.addWidget(self.only_selected)
        tools.addStretch(1)
        self.select_button = PushButton("全选", self)
        self.select_button.clicked.connect(self._select_matches)
        tools.addWidget(self.select_button)
        self.clear_button = TransparentPushButton("清空", self)
        self.clear_button.clicked.connect(self._clear)
        tools.addWidget(self.clear_button)
        layout.addLayout(tools)
        self.distribution = MultilevelDistributionWidget(self.paths, self)
        layout.addWidget(self.distribution, 1)
        self.total_label = BodyLabel(self)
        layout.addWidget(self.total_label)
        self.error_bar = InfoBar(
            InfoBarIcon.ERROR,
            "请选择至少一条路径",
            "",
            isClosable=False,
            duration=-1,
            position=InfoBarPosition.NONE,
            parent=self,
        )
        layout.addWidget(self.error_bar)
        self.distribution.changed.connect(self._refresh)
        self.distribution.selectionRequested.connect(self._select)
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(120)
        self._filter_timer.timeout.connect(self._filter)
        self.search_edit.textChanged.connect(lambda: self._filter_timer.start())
        self.only_selected.toggled.connect(self._filter)
        self._refresh()

    def _filter(self) -> None:
        self.distribution.set_filter(self.search_edit.text(), self.only_selected.isChecked())
        self.select_button.setText("选中结果" if self.search_edit.text().strip() else "全选")

    def _select_matches(self) -> None:
        self._filter_timer.stop()
        self._filter()
        self._select(self.distribution.matching_indices(), True)

    def _clear(self) -> None:
        self._select(list(self.paths.selected), False)

    def _select(self, indices: list[int], checked: bool) -> None:
        self.paths.select(indices, checked)
        self._refresh()

    def _refresh(self) -> None:
        self.distribution.refresh()
        self.total_label.setText(
            f"已选 {len(self.paths.selected)} / {len(self.paths.values)} 条路径"
        )
        self.error_bar.title = self.validation_message()
        self.error_bar.titleLabel.setText(self.error_bar.title)
        self.error_bar.setVisible(not self.paths.is_valid())

    def validation_message(self) -> str:
        if not self.paths.selected:
            return "请选择至少一条路径"
        return "" if self.paths.is_valid() else "请至少保留一项大于 0 的权重"

    def get_weights(self) -> list[float]:
        if message := self.validation_message():
            raise ValueError(message)
        return list(self.paths.values)
