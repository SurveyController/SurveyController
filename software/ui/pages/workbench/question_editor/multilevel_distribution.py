from __future__ import annotations

from functools import partial
from typing import cast

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    PushButton,
    ScrollArea,
    SimpleCardWidget,
    Slider,
    StrongBodyLabel,
)

from .multilevel_paths import MultilevelPaths
from .wizard_sections_common import WizardSectionsCommonMixin


class MultilevelDistributionWidget(QWidget):
    changed = Signal()
    selectionRequested = Signal(object, bool)
    _PAGE_SIZE = 60

    def __init__(self, paths: MultilevelPaths, parent=None) -> None:
        super().__init__(parent)
        self.paths = paths
        self._branches: dict[tuple[str, ...], list[int]] = {}
        for index, parts in enumerate(paths.parts):
            for branch in [parts[:depth] for depth in range(1, len(parts))] or [()]:
                self._branches.setdefault(branch, []).append(index)
        self._keyword = ""
        self._only_selected = False
        self._indices: list[int] = []
        self._page = 0
        self._weight_limit = max([100.0, *paths.values])
        self.sliders: dict[int, Slider] = {}
        self.ratio_labels: dict[int, BodyLabel] = {}
        self.group_cards: dict[tuple[str, ...], SimpleCardWidget] = {}
        self.group_checks: dict[tuple[str, ...], CheckBox] = {}
        self.option_checks: dict[int, CheckBox] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(240)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.scroll_area, 1)
        self.pager = QWidget(self)
        pager_layout = QHBoxLayout(self.pager)
        pager_layout.setContentsMargins(0, 0, 0, 0)
        self.previous_button = PushButton("上一页", self.pager)
        self.previous_button.clicked.connect(lambda: self._show_page(self._page - 1))
        pager_layout.addWidget(self.previous_button)
        self.page_label = BodyLabel(self.pager)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pager_layout.addWidget(self.page_label, 1)
        self.next_button = PushButton("下一页", self.pager)
        self.next_button.clicked.connect(lambda: self._show_page(self._page + 1))
        pager_layout.addWidget(self.next_button)
        layout.addWidget(self.pager)
        self.refresh()

    def refresh(self) -> None:
        self._weight_limit = max([self._weight_limit, *self.paths.values])
        indices = self.matching_indices()
        if self._indices != indices or self.scroll_area.widget() is None:
            self._indices = indices
            self._show_page(min(self._page, max(0, (len(self._indices) - 1) // self._PAGE_SIZE)))
        else:
            self._refresh_controls()

    def set_filter(self, keyword: str, only_selected: bool) -> None:
        self._keyword = keyword.strip().casefold()
        self._only_selected = only_selected
        self.refresh()

    def matching_indices(self) -> list[int]:
        return [
            index
            for index in range(len(self.paths.parts))
            if (not self._only_selected or index in self.paths.selected)
            and self._keyword in " / ".join(self.paths.parts[index]).casefold()
        ]

    def _refresh_controls(self) -> None:
        total = sum(self.paths.values)
        for index, slider in self.sliders.items():
            with QSignalBlocker(slider):
                slider.setValue(round(self.paths.values[index] / self._weight_limit * 10000))
            ratio = self.paths.values[index] / total * 100 if total else 0
            self.ratio_labels[index].setText(f"{ratio:.1f}%")
            color = WizardSectionsCommonMixin._pick_ratio_color(ratio)
            self.ratio_labels[index].setTextColor(color, color)
            with QSignalBlocker(self.option_checks[index]):
                self.option_checks[index].setChecked(index in self.paths.selected)
        for branch, checkbox in self.group_checks.items():
            selected = sum(index in self.paths.selected for index in self._branches[branch])
            state = (
                Qt.CheckState.Checked
                if selected == len(self._branches[branch])
                else Qt.CheckState.PartiallyChecked
                if selected
                else Qt.CheckState.Unchecked
            )
            with QSignalBlocker(checkbox):
                checkbox.setCheckState(state)

    def _show_page(self, page: int) -> None:
        self._page = page
        old = self.scroll_area.takeWidget()
        if old is not None:
            old.deleteLater()
        self.sliders.clear()
        self.ratio_labels.clear()
        self.group_cards.clear()
        self.group_checks.clear()
        self.option_checks.clear()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 0)
        content_layout.setSpacing(12)
        content_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        start = page * self._PAGE_SIZE
        for index in self._indices[start : start + self._PAGE_SIZE]:
            parts = self.paths.parts[index]
            card = content
            for branch in [parts[:depth] for depth in range(1, len(parts))] or [()]:
                if branch not in self.group_cards:
                    group = self._build_group(branch, card)
                    cast(QVBoxLayout, card.layout()).addWidget(group)
                    self.group_cards[branch] = group
                card = self.group_cards[branch]
            row = QWidget(card)
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 2)
            row_layout.setSpacing(4)
            option_header = QHBoxLayout()
            checkbox = CheckBox(row)
            checkbox.setFixedWidth(24)
            checkbox.setAccessibleName("选择 " + " / ".join(self.paths.parts[index]))
            checkbox.checkStateChanged.connect(partial(self._select_option, index))
            option_header.addWidget(checkbox)
            self.option_checks[index] = checkbox
            name = BodyLabel(self.paths.parts[index][-1], row)
            name.setWordWrap(True)
            option_header.addWidget(name, 1)
            row_layout.addLayout(option_header)
            controls = QHBoxLayout()
            slider = Slider(Qt.Orientation.Horizontal, row)
            slider.setAccessibleName(" / ".join(self.paths.parts[index]))
            slider.setRange(0, 10000)
            slider.setPageStep(100)
            slider.setMinimumWidth(48)
            slider.valueChanged.connect(partial(self._change_weight, index))
            controls.addWidget(slider, 1)
            ratio = BodyLabel(row)
            ratio.setMinimumWidth(64)
            ratio.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            controls.addWidget(ratio)
            row_layout.addLayout(controls)
            cast(QVBoxLayout, card.layout()).addWidget(row)
            self.sliders[index] = slider
            self.ratio_labels[index] = ratio
        if not self._indices:
            content_layout.addWidget(
                BodyLabel("无匹配选项" if self._keyword else "未选择范围", content)
            )
        content_layout.addStretch(1)
        self.scroll_area.setWidget(content)
        pages = max(1, (len(self._indices) + self._PAGE_SIZE - 1) // self._PAGE_SIZE)
        self.pager.setVisible(pages > 1)
        self.page_label.setText(f"{page + 1} / {pages}")
        self.previous_button.setEnabled(page > 0)
        self.next_button.setEnabled(page + 1 < pages)
        self._refresh_controls()

    def _build_group(self, branch: tuple[str, ...], parent: QWidget) -> SimpleCardWidget:
        card = SimpleCardWidget(parent)
        card.setClickEnabled(False)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        header = QHBoxLayout()
        checkbox = CheckBox(card)
        checkbox.setFixedWidth(24)
        checkbox.setTristate(True)
        checkbox.setAccessibleName(" / ".join(branch) or "全部选项")
        checkbox.checkStateChanged.connect(partial(self._select_branch, branch))
        header.addWidget(checkbox)
        self.group_checks[branch] = checkbox
        title = StrongBodyLabel(branch[-1] if branch else "选项", card)
        title.setWordWrap(True)
        header.addWidget(title, 1)
        layout.addLayout(header)
        return card

    def _select_branch(self, branch: tuple[str, ...], state: Qt.CheckState) -> None:
        self.selectionRequested.emit(self._branches[branch], state != Qt.CheckState.Unchecked)

    def _select_option(self, index: int, state: Qt.CheckState) -> None:
        self.selectionRequested.emit([index], state == Qt.CheckState.Checked)

    def _change_weight(self, index: int, value: int) -> None:
        self.paths.select([index], True)
        self.paths.values[index] = value * self._weight_limit / 10000
        self.changed.emit()
