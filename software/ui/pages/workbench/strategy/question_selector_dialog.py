from __future__ import annotations

from typing import Any, Dict, List, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout
from qfluentwidgets import (
    BodyLabel,
    LineEdit,
    MessageBoxBase,
    PushButton,
    TableWidget,
    TitleLabel,
)
from software.ui.helpers.qfluent_compat import resolve_mask_dialog_parent


class QuestionSelectorDialog(MessageBoxBase):
    

    def __init__(
        self,
        title: str,
        questions: Sequence[Dict[str, Any]],
        parent=None,
    ):
        resolved_parent = resolve_mask_dialog_parent(parent)
        super().__init__(resolved_parent)
        self._fallback_parent = resolved_parent if resolved_parent is not parent else None
        if self._fallback_parent is not None:
            self.destroyed.connect(self._fallback_parent.deleteLater)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(title)
        self.widget.setFixedWidth(720)
        self.widget.setMinimumHeight(480)

        self._all_questions = list(questions or [])
        self._selected_indices: List[int] = []

        self._build_ui()
        self._populate_table()

    def _build_ui(self) -> None:
        self.titleLabel = TitleLabel("选择要添加的题目", self.widget)
        self.tipLabel = BodyLabel("可以多选题目，支持搜索过滤", self.widget)

        
        search_layout = QHBoxLayout()
        self.search_edit = LineEdit(self.widget)
        self.search_edit.setPlaceholderText("搜索题号或题干...")
        self.search_edit.textChanged.connect(self._on_search)
        search_layout.addWidget(self.search_edit)

        
        self.table = TableWidget(self.widget)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["题号", "题干", "题型", "当前维度"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, header.ResizeMode.Stretch)
        header.setSectionResizeMode(2, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, header.ResizeMode.ResizeToContents)

        
        button_layout = QHBoxLayout()
        self.select_all_btn = PushButton("全选", self.widget)
        self.select_none_btn = PushButton("取消全选", self.widget)
        button_layout.addWidget(self.select_all_btn)
        button_layout.addWidget(self.select_none_btn)
        button_layout.addStretch(1)

        self.select_all_btn.clicked.connect(self.table.selectAll)
        self.select_none_btn.clicked.connect(self.table.clearSelection)

        
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.tipLabel)
        self.viewLayout.addLayout(search_layout)
        self.viewLayout.addWidget(self.table, 1)
        self.viewLayout.addLayout(button_layout)

        self.yesButton.setText("确定添加")
        self.cancelButton.setText("取消")

    def _populate_table(self, filter_text: str = "") -> None:
        
        self.table.setRowCount(0)
        filter_lower = filter_text.lower().strip()

        for question in self._all_questions:
            question_num = str(question.get("question_num", ""))
            title = str(question.get("title", ""))
            type_label = str(question.get("type_label", ""))
            group_name = str(question.get("group_name", "未分组"))

            
            if filter_lower:
                if filter_lower not in question_num.lower() and filter_lower not in title.lower():
                    continue

            row_index = self.table.rowCount()
            self.table.insertRow(row_index)

            from PySide6.QtWidgets import QTableWidgetItem

            self.table.setItem(row_index, 0, QTableWidgetItem(question_num))
            self.table.setItem(row_index, 1, QTableWidgetItem(title))
            self.table.setItem(row_index, 2, QTableWidgetItem(type_label))
            self.table.setItem(row_index, 3, QTableWidgetItem(group_name))

            
            item = self.table.item(row_index, 0)
            if item is not None:
                item.setData(Qt.ItemDataRole.UserRole, question.get("entry_index", -1))

    def _on_search(self, text: str) -> None:
        
        self._populate_table(text)

    def validate(self) -> bool:
        
        self._selected_indices = []
        selection = self.table.selectionModel()
        if selection is None:
            return True

        for model_index in selection.selectedRows():
            item = self.table.item(model_index.row(), 0)
            if item is None:
                continue
            entry_index = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(entry_index, int) and entry_index >= 0:
                self._selected_indices.append(entry_index)

        return True

    def get_selected_indices(self) -> List[int]:
        
        return sorted(set(self._selected_indices))
