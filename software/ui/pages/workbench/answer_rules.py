"""作答规则页：配置条件触发的答题约束规则。"""
from __future__ import annotations

import copy
import uuid
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    RadioButton,
    ScrollArea,
    SubtitleLabel,
    TableWidget,
)
from software.core.questions.consistency import (
    normalize_rule_dict,
    sanitize_answer_rules,
)


_ALLOWED_TYPE_CODES = {"3", "4", "5", "6"}  # 单选 / 多选 / 量表(含评价) / 矩阵
_TYPE_CODE_LABELS = {"3": "单选题", "4": "多选题", "5": "量表题", "6": "矩阵题"}
_CONDITION_MODE_LABELS = {
    "selected": "选择了以下选项",
    "not_selected": "未选择以下选项",
}
_ACTION_MODE_LABELS = {
    "must_select": "一定选择以下选项",
    "must_not_select": "一定不选择以下选项",
}


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _to_int_list(values: Any) -> List[int]:
    if not isinstance(values, list):
        return []
    result: List[int] = []
    seen = set()
    for item in values:
        try:
            idx = int(item)
        except Exception:
            continue
        if idx < 0 or idx in seen:
            continue
        seen.add(idx)
        result.append(idx)
    return sorted(result)


def _normalize_question_type_code(value: Any) -> str:
    try:
        return str(value or "").strip()
    except Exception:
        return ""


def _build_question_label(question: Dict[str, Any]) -> str:
    q_num = _to_int(question.get("num"), 0)
    title = str(question.get("title") or "").strip()
    type_code = _normalize_question_type_code(question.get("type_code"))
    if type_code == "5" and question.get("is_rating"):
        type_label = "评价题"
    else:
        type_label = _TYPE_CODE_LABELS.get(type_code, "")
    suffix = f" [{type_label}]" if type_label else ""
    if title:
        return f"第{q_num}题：{title}{suffix}"
    return f"第{q_num}题{suffix}"


def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            continue
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.hide()
            widget.deleteLater()
        if child_layout is not None:
            while child_layout.count():
                nested = child_layout.takeAt(0)
                if nested is None:
                    continue
                nested_widget = nested.widget()
                if nested_widget is not None:
                    nested_widget.hide()
                    nested_widget.deleteLater()


class AnswerRuleDialog(QDialog):
    """新增/编辑作答规则弹窗。"""

    def __init__(
        self,
        questions_info: List[Dict[str, Any]],
        parent=None,
        rule_data: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("添加规则" if not rule_data else "编辑规则")
        self.resize(860, 760)
        self._rule_data = copy.deepcopy(rule_data) if rule_data else None
        self._result_rule: Optional[Dict[str, Any]] = None
        self._questions_info = list(questions_info or [])
        self._question_map: Dict[int, Dict[str, Any]] = {}
        self._condition_checks: List[CheckBox] = []
        self._target_checks: List[CheckBox] = []
        self._build_question_map()
        self._build_ui()
        self._bind_events()
        self._apply_initial_rule()

    def _build_question_map(self) -> None:
        self._question_map.clear()
        for item in self._questions_info:
            q_num = _to_int(item.get("num"), 0)
            if q_num <= 0:
                continue
            type_code = _normalize_question_type_code(item.get("type_code"))
            if type_code not in _ALLOWED_TYPE_CODES:
                continue
            self._question_map[q_num] = item

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        title = SubtitleLabel("添加规则" if not self._rule_data else "编辑规则", self)
        root.addWidget(title)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.enableTransparentBackground()
        container = QWidget(self)
        scroll.setWidget(container)
        main = QVBoxLayout(container)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(14)

        self._condition_card = CardWidget(container)
        condition_layout = QVBoxLayout(self._condition_card)
        condition_layout.setContentsMargins(18, 16, 18, 16)
        condition_layout.setSpacing(12)
        condition_layout.addWidget(SubtitleLabel("条件设置", self._condition_card))

        condition_question_row = QHBoxLayout()
        condition_question_row.addWidget(BodyLabel("条件题目", self._condition_card))
        condition_question_row.addSpacing(8)
        self.condition_question_combo = ComboBox(self._condition_card)
        self.condition_question_combo.setMinimumWidth(560)
        self._fill_question_combo(self.condition_question_combo)
        condition_question_row.addWidget(self.condition_question_combo, 1)
        condition_layout.addLayout(condition_question_row)

        self._condition_row_widget = QWidget(self._condition_card)
        condition_row_row = QHBoxLayout(self._condition_row_widget)
        condition_row_row.setContentsMargins(0, 0, 0, 0)
        condition_row_row.addWidget(BodyLabel("条件行", self._condition_card))
        condition_row_row.addSpacing(8)
        self.condition_row_combo = ComboBox(self._condition_card)
        self.condition_row_combo.setMinimumWidth(560)
        condition_row_row.addWidget(self.condition_row_combo, 1)
        self._condition_row_widget.hide()
        condition_layout.addWidget(self._condition_row_widget)

        condition_type_row = QHBoxLayout()
        condition_type_row.addWidget(BodyLabel("条件类型", self._condition_card))
        condition_type_row.addSpacing(8)
        self.condition_selected_radio = RadioButton("选择了以下选项", self._condition_card)
        self.condition_not_selected_radio = RadioButton("未选择以下选项", self._condition_card)
        self.condition_mode_group = QButtonGroup(self._condition_card)
        self.condition_mode_group.addButton(self.condition_selected_radio)
        self.condition_mode_group.addButton(self.condition_not_selected_radio)
        self.condition_selected_radio.setChecked(True)
        condition_type_row.addWidget(self.condition_selected_radio)
        condition_type_row.addWidget(self.condition_not_selected_radio)
        condition_type_row.addStretch(1)
        condition_layout.addLayout(condition_type_row)

        condition_layout.addWidget(BodyLabel("条件选项", self._condition_card))
        self.condition_options_widget = QWidget(self._condition_card)
        self.condition_options_layout = QVBoxLayout(self.condition_options_widget)
        self.condition_options_layout.setContentsMargins(8, 4, 8, 4)
        self.condition_options_layout.setSpacing(8)
        condition_layout.addWidget(self.condition_options_widget)
        main.addWidget(self._condition_card)

        self._action_card = CardWidget(container)
        action_layout = QVBoxLayout(self._action_card)
        action_layout.setContentsMargins(18, 16, 18, 16)
        action_layout.setSpacing(12)
        action_layout.addWidget(SubtitleLabel("动作设置", self._action_card))

        target_question_row = QHBoxLayout()
        target_question_row.addWidget(BodyLabel("目标题目", self._action_card))
        target_question_row.addSpacing(8)
        self.target_question_combo = ComboBox(self._action_card)
        self.target_question_combo.setMinimumWidth(560)
        self._fill_question_combo(self.target_question_combo)
        target_question_row.addWidget(self.target_question_combo, 1)
        action_layout.addLayout(target_question_row)

        self._target_row_widget = QWidget(self._action_card)
        target_row_row = QHBoxLayout(self._target_row_widget)
        target_row_row.setContentsMargins(0, 0, 0, 0)
        target_row_row.addWidget(BodyLabel("目标行", self._action_card))
        target_row_row.addSpacing(8)
        self.target_row_combo = ComboBox(self._action_card)
        self.target_row_combo.setMinimumWidth(560)
        target_row_row.addWidget(self.target_row_combo, 1)
        self._target_row_widget.hide()
        action_layout.addWidget(self._target_row_widget)

        action_type_row = QHBoxLayout()
        action_type_row.addWidget(BodyLabel("动作类型", self._action_card))
        action_type_row.addSpacing(8)
        self.must_select_radio = RadioButton("一定选择以下选项", self._action_card)
        self.must_not_select_radio = RadioButton("一定不选择以下选项", self._action_card)
        self.action_mode_group = QButtonGroup(self._action_card)
        self.action_mode_group.addButton(self.must_select_radio)
        self.action_mode_group.addButton(self.must_not_select_radio)
        self.must_select_radio.setChecked(True)
        action_type_row.addWidget(self.must_select_radio)
        action_type_row.addWidget(self.must_not_select_radio)
        action_type_row.addStretch(1)
        action_layout.addLayout(action_type_row)

        action_layout.addWidget(BodyLabel("目标选项", self._action_card))
        self.target_options_widget = QWidget(self._action_card)
        self.target_options_layout = QVBoxLayout(self.target_options_widget)
        self.target_options_layout.setContentsMargins(8, 4, 8, 4)
        self.target_options_layout.setSpacing(8)
        action_layout.addWidget(self.target_options_widget)
        main.addWidget(self._action_card)

        main.addStretch(1)
        root.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = PushButton("取消", self)
        self.ok_btn = PrimaryPushButton("确定", self)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.ok_btn)
        root.addLayout(btn_row)

    def _fill_question_combo(self, combo: ComboBox) -> None:
        combo.clear()
        combo.addItem("请选择题目", userData=None)
        sorted_questions = sorted(self._question_map.values(), key=lambda x: _to_int(x.get("num"), 0))
        for question in sorted_questions:
            combo.addItem(_build_question_label(question), userData=_to_int(question.get("num"), 0))

    def _bind_events(self) -> None:
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self._on_confirm_clicked)
        self.condition_question_combo.currentIndexChanged.connect(self._on_condition_question_changed)
        self.target_question_combo.currentIndexChanged.connect(self._on_target_question_changed)
        self.condition_row_combo.currentIndexChanged.connect(self._on_condition_row_changed)
        self.target_row_combo.currentIndexChanged.connect(self._on_target_row_changed)

    def _apply_initial_rule(self) -> None:
        self._render_condition_options([], None, None)
        self._render_target_options([], None, None)
        if not self._rule_data:
            return
        condition_num = _to_int(self._rule_data.get("condition_question_num"), -1)
        target_num = _to_int(self._rule_data.get("target_question_num"), -1)
        condition_mode = str(self._rule_data.get("condition_mode") or "selected").strip()
        action_mode = str(self._rule_data.get("action_mode") or "must_select").strip()
        condition_indices = _to_int_list(self._rule_data.get("condition_option_indices"))
        target_indices = _to_int_list(self._rule_data.get("target_option_indices"))
        raw_cri = self._rule_data.get("condition_row_index")
        condition_row_index: Optional[int] = _to_int(raw_cri, -1) if raw_cri is not None else None
        if condition_row_index is not None and condition_row_index < 0:
            condition_row_index = None
        raw_tri = self._rule_data.get("target_row_index")
        target_row_index: Optional[int] = _to_int(raw_tri, -1) if raw_tri is not None else None
        if target_row_index is not None and target_row_index < 0:
            target_row_index = None

        condition_idx = self.condition_question_combo.findData(condition_num)
        if condition_idx >= 0:
            self.condition_question_combo.blockSignals(True)
            self.condition_question_combo.setCurrentIndex(condition_idx)
            self.condition_question_combo.blockSignals(False)
        target_idx = self.target_question_combo.findData(target_num)
        if target_idx >= 0:
            self.target_question_combo.blockSignals(True)
            self.target_question_combo.setCurrentIndex(target_idx)
            self.target_question_combo.blockSignals(False)

        # 恢复矩阵行选择器
        self._update_row_selector(self.condition_question_combo, self._condition_row_widget, self.condition_row_combo)
        self._update_row_selector(self.target_question_combo, self._target_row_widget, self.target_row_combo)
        if condition_row_index is not None:
            row_idx = self.condition_row_combo.findData(condition_row_index)
            if row_idx >= 0:
                self.condition_row_combo.blockSignals(True)
                self.condition_row_combo.setCurrentIndex(row_idx)
                self.condition_row_combo.blockSignals(False)
        if target_row_index is not None:
            row_idx = self.target_row_combo.findData(target_row_index)
            if row_idx >= 0:
                self.target_row_combo.blockSignals(True)
                self.target_row_combo.setCurrentIndex(row_idx)
                self.target_row_combo.blockSignals(False)

        if condition_mode == "not_selected":
            self.condition_not_selected_radio.setChecked(True)
        else:
            self.condition_selected_radio.setChecked(True)

        if action_mode == "must_not_select":
            self.must_not_select_radio.setChecked(True)
        else:
            self.must_select_radio.setChecked(True)

        self._render_condition_options(condition_indices, condition_num, condition_row_index)
        self._render_target_options(target_indices, target_num, target_row_index)

    def _on_condition_question_changed(self) -> None:
        q_num = self._get_combo_question_num(self.condition_question_combo)
        self._update_row_selector(self.condition_question_combo, self._condition_row_widget, self.condition_row_combo)
        row_index = self._get_combo_row_index(self.condition_row_combo)
        self._render_condition_options([], q_num, row_index)

    def _on_target_question_changed(self) -> None:
        q_num = self._get_combo_question_num(self.target_question_combo)
        self._update_row_selector(self.target_question_combo, self._target_row_widget, self.target_row_combo)
        row_index = self._get_combo_row_index(self.target_row_combo)
        self._render_target_options([], q_num, row_index)

    def _on_condition_row_changed(self) -> None:
        q_num = self._get_combo_question_num(self.condition_question_combo)
        row_index = self._get_combo_row_index(self.condition_row_combo)
        self._render_condition_options([], q_num, row_index)

    def _on_target_row_changed(self) -> None:
        q_num = self._get_combo_question_num(self.target_question_combo)
        row_index = self._get_combo_row_index(self.target_row_combo)
        self._render_target_options([], q_num, row_index)

    def _get_combo_question_num(self, combo: ComboBox) -> Optional[int]:
        idx = combo.currentIndex()
        if idx < 0:
            return None
        data = combo.itemData(idx)
        if data is None:
            return None
        q_num = _to_int(data, -1)
        if q_num <= 0:
            return None
        return q_num

    def _get_combo_row_index(self, combo: ComboBox) -> Optional[int]:
        idx = combo.currentIndex()
        if idx < 0:
            return None
        data = combo.itemData(idx)
        if data is None:
            return None
        row_idx = _to_int(data, -1)
        if row_idx < 0:
            return None
        return row_idx

    def _is_matrix_question(self, question_num: Optional[int]) -> bool:
        if not question_num:
            return False
        info = self._question_map.get(question_num) or {}
        return _normalize_question_type_code(info.get("type_code")) == "6"

    def _update_row_selector(self, question_combo: ComboBox, row_widget: QWidget, row_combo: ComboBox) -> None:
        """根据选中的题目类型，显示/隐藏矩阵行选择器并填充行列表。"""
        q_num = self._get_combo_question_num(question_combo)
        if q_num is not None and self._is_matrix_question(q_num):
            info = self._question_map.get(q_num) or {}
            raw_row_texts = info.get("row_texts")
            row_texts: List[Any] = raw_row_texts if isinstance(raw_row_texts, list) else []
            row_combo.clear()
            row_combo.addItem("请选择行", userData=None)
            for i, text in enumerate(row_texts):
                label = str(text or "").strip() or f"第{i + 1}行"
                row_combo.addItem(f"第{i + 1}行：{label}", userData=i)
            row_widget.show()
        else:
            row_combo.clear()
            row_widget.hide()

    def _render_condition_options(self, selected_indices: List[int], question_num: Optional[int], row_index: Optional[int]) -> None:
        self._condition_checks = self._render_option_checks(
            self.condition_options_layout,
            selected_indices,
            question_num,
            row_index,
            "请先选择条件题目",
        )

    def _render_target_options(self, selected_indices: List[int], question_num: Optional[int], row_index: Optional[int]) -> None:
        self._target_checks = self._render_option_checks(
            self.target_options_layout,
            selected_indices,
            question_num,
            row_index,
            "请先选择目标题目",
        )

    def _render_option_checks(
        self,
        layout: QVBoxLayout,
        selected_indices: List[int],
        question_num: Optional[int],
        row_index: Optional[int],
        empty_hint: str,
    ) -> List[CheckBox]:
        _clear_layout(layout)
        if not question_num:
            label = BodyLabel(empty_hint, self)
            label.setStyleSheet("color: #888888;")
            layout.addWidget(label)
            return []
        info = self._question_map.get(question_num) or {}
        type_code = _normalize_question_type_code(info.get("type_code"))
        # 矩阵题：需要先选行，再显示列选项
        if type_code == "6":
            if row_index is None:
                label = BodyLabel("请先选择行", self)
                label.setStyleSheet("color: #888888;")
                layout.addWidget(label)
                return []
        option_texts = info.get("option_texts") if isinstance(info.get("option_texts"), list) else []
        checks: List[CheckBox] = []
        if not option_texts:
            label = BodyLabel("该题未解析到选项，无法配置规则", self)
            label.setStyleSheet("color: #888888;")
            layout.addWidget(label)
            return checks
        selected_set = set(selected_indices or [])
        for idx, text in enumerate(option_texts):
            option_text = str(text or "").strip() or f"选项{idx + 1}"
            check = CheckBox(f"{idx + 1}. {option_text}", self)
            check.setChecked(idx in selected_set)
            layout.addWidget(check)
            checks.append(check)
        return checks

    def _collect_checked_indices(self, checks: List[CheckBox]) -> List[int]:
        result: List[int] = []
        for idx, check in enumerate(checks):
            if check.isChecked():
                result.append(idx)
        return result

    def _warn(self, message: str) -> None:
        InfoBar.warning("", message, parent=self, position=InfoBarPosition.TOP, duration=2200)

    def _on_confirm_clicked(self) -> None:
        rule = self._build_rule()
        if not rule:
            return
        self._result_rule = rule
        self.accept()

    def _build_rule(self) -> Optional[Dict[str, Any]]:
        condition_num = self._get_combo_question_num(self.condition_question_combo)
        target_num = self._get_combo_question_num(self.target_question_combo)
        if not condition_num:
            self._warn("请先选择条件题目")
            return None
        if not target_num:
            self._warn("请先选择目标题目")
            return None
        if condition_num == target_num:
            self._warn("条件题目和目标题目不能是同一题")
            return None
        if condition_num >= target_num:
            self._warn("仅支持前置条件：条件题号必须小于目标题号")
            return None

        condition_info = self._question_map.get(condition_num)
        target_info = self._question_map.get(target_num)
        if not condition_info or _normalize_question_type_code(condition_info.get("type_code")) not in _ALLOWED_TYPE_CODES:
            self._warn("条件题目类型不支持")
            return None
        if not target_info or _normalize_question_type_code(target_info.get("type_code")) not in _ALLOWED_TYPE_CODES:
            self._warn("目标题目类型不支持")
            return None

        # 矩阵题需要选择行
        condition_row_index: Optional[int] = None
        if self._is_matrix_question(condition_num):
            condition_row_index = self._get_combo_row_index(self.condition_row_combo)
            if condition_row_index is None:
                self._warn("请先选择条件行")
                return None

        target_row_index: Optional[int] = None
        if self._is_matrix_question(target_num):
            target_row_index = self._get_combo_row_index(self.target_row_combo)
            if target_row_index is None:
                self._warn("请先选择目标行")
                return None

        condition_indices = self._collect_checked_indices(self._condition_checks)
        if not condition_indices:
            self._warn("请至少勾选一个条件选项")
            return None
        target_indices = self._collect_checked_indices(self._target_checks)
        if not target_indices:
            self._warn("请至少勾选一个目标选项")
            return None

        condition_mode = "not_selected" if self.condition_not_selected_radio.isChecked() else "selected"
        action_mode = "must_not_select" if self.must_not_select_radio.isChecked() else "must_select"
        rule_id = ""
        if isinstance(self._rule_data, dict):
            rule_id = str(self._rule_data.get("id") or "").strip()
        if not rule_id:
            rule_id = uuid.uuid4().hex

        rule: Dict[str, Any] = {
            "id": rule_id,
            "condition_question_num": condition_num,
            "condition_mode": condition_mode,
            "condition_option_indices": condition_indices,
            "target_question_num": target_num,
            "action_mode": action_mode,
            "target_option_indices": target_indices,
        }
        if condition_row_index is not None:
            rule["condition_row_index"] = condition_row_index
        if target_row_index is not None:
            rule["target_row_index"] = target_row_index
        return normalize_rule_dict(rule)

    def get_rule(self) -> Optional[Dict[str, Any]]:
        return copy.deepcopy(self._result_rule)


class AnswerRulesPage(ScrollArea):
    """作答规则列表页。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules: List[Dict[str, Any]] = []
        self._questions_info: List[Dict[str, Any]] = []
        self._question_map: Dict[int, Dict[str, Any]] = {}
        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(SubtitleLabel("作答规则", self.view))
        layout.addWidget(BodyLabel("按条件控制后续单选/多选/量表/评价/矩阵题答案。规则列表中越靠后优先级越高。", self.view))

        btn_row = QHBoxLayout()
        self.add_btn = PrimaryPushButton("新增规则", self.view)
        self.edit_btn = PushButton("编辑选中", self.view)
        self.del_btn = PushButton("删除选中", self.view)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.del_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.table = TableWidget(self.view)
        self.table.setRowCount(0)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["条件题目", "条件类型", "条件选项", "目标题目", "动作类型", "目标选项"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(420)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, header.ResizeMode.Stretch)
        header.setSectionResizeMode(1, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, header.ResizeMode.Stretch)
        header.setSectionResizeMode(3, header.ResizeMode.Stretch)
        header.setSectionResizeMode(4, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, header.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        self.add_btn.clicked.connect(self._on_add_rule)
        self.edit_btn.clicked.connect(self._on_edit_rule)
        self.del_btn.clicked.connect(self._on_delete_rule)
        self.table.doubleClicked.connect(lambda _idx: self._on_edit_rule())

    def set_questions_info(self, info: List[Dict[str, Any]]) -> None:
        self._questions_info = list(info or [])
        self._question_map.clear()
        for question in self._questions_info:
            q_num = _to_int(question.get("num"), 0)
            if q_num > 0:
                self._question_map[q_num] = question
        self._rules = self._sanitize_rules(self._rules, show_removed_toast=True)
        self._refresh_table()

    def set_rules(self, rules: List[Dict[str, Any]]) -> None:
        self._rules = self._sanitize_rules(rules, show_removed_toast=True)
        self._refresh_table()

    def get_rules(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._rules)

    def _sanitize_rules(self, rules: List[Dict[str, Any]], show_removed_toast: bool = False) -> List[Dict[str, Any]]:
        sanitized, stats = sanitize_answer_rules(rules or [], self._questions_info or None)
        if show_removed_toast and stats.get("unsupported", 0):
            count = int(stats["unsupported"])
            suffix = "已自动移除 1 条不再支持的作答规则" if count == 1 else f"已自动移除 {count} 条不再支持的作答规则"
            self._toast(suffix, "warning")
        return sanitized

    def _toast(self, message: str, level: str = "warning") -> None:
        parent = self.window() or self
        if level == "error":
            InfoBar.error("", message, parent=parent, position=InfoBarPosition.TOP, duration=2200)
            return
        if level == "success":
            InfoBar.success("", message, parent=parent, position=InfoBarPosition.TOP, duration=1800)
            return
        InfoBar.warning("", message, parent=parent, position=InfoBarPosition.TOP, duration=2200)

    def _selected_rows(self) -> List[int]:
        selection = self.table.selectionModel()
        if selection is None:
            return []
        return sorted({idx.row() for idx in selection.selectedRows()})

    def _get_selectable_questions(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for question in self._questions_info:
            type_code = _normalize_question_type_code(question.get("type_code"))
            if type_code not in _ALLOWED_TYPE_CODES:
                continue
            result.append(question)
        return result

    def _on_add_rule(self) -> None:
        selectable = self._get_selectable_questions()
        if len(selectable) < 2:
            self._toast("当前问卷可用题目不足（需要至少2道单选/多选/量表/评价/矩阵题）", "warning")
            return
        dialog = AnswerRuleDialog(self._questions_info, parent=self.window() or self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        rule = dialog.get_rule()
        if not rule:
            return
        self._rules.append(rule)
        self._refresh_table()

    def _on_edit_rule(self) -> None:
        rows = self._selected_rows()
        if not rows:
            self._toast("请先选择要编辑的规则", "warning")
            return
        if len(rows) > 1:
            self._toast("一次只能编辑一条规则", "warning")
            return
        row = rows[0]
        if row < 0 or row >= len(self._rules):
            return
        dialog = AnswerRuleDialog(
            self._questions_info,
            parent=self.window() or self,
            rule_data=self._rules[row],
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        rule = dialog.get_rule()
        if not rule:
            return
        self._rules[row] = rule
        self._refresh_table()

    def _on_delete_rule(self) -> None:
        rows = self._selected_rows()
        if not rows:
            self._toast("请先选择要删除的规则", "warning")
            return
        count = len(rows)
        msg = MessageBox(
            "确认删除",
            f"确定要删除选中的 {count} 条规则吗？此操作不可撤销。",
            self.window() or self,
        )
        msg.yesButton.setText("确认删除")
        msg.cancelButton.setText("取消")
        if msg.exec() != MessageBox.DialogCode.Accepted:
            return
        for row in sorted(rows, reverse=True):
            if 0 <= row < len(self._rules):
                self._rules.pop(row)
        self._refresh_table()

    def _question_label_by_num(self, question_num: int, row_index: Optional[int] = None) -> str:
        info = self._question_map.get(question_num)
        if not info:
            return f"第{question_num}题（题目不存在）"
        base = _build_question_label(info)
        if row_index is not None:
            raw_row_texts = info.get("row_texts")
            row_texts: List[Any] = raw_row_texts if isinstance(raw_row_texts, list) else []
            if row_index < len(row_texts):
                row_label = str(row_texts[row_index] or "").strip() or f"第{row_index + 1}行"
            else:
                row_label = f"第{row_index + 1}行"
            return f"{base} / {row_label}"
        return base

    def _option_label_text(self, question_num: int, option_indices: List[int]) -> str:
        info = self._question_map.get(question_num) or {}
        _raw_texts = info.get("option_texts")
        option_texts: List = _raw_texts if isinstance(_raw_texts, list) else []
        if not option_indices:
            return "-"
        labels: List[str] = []
        for idx in option_indices:
            if isinstance(idx, int) and 0 <= idx < len(option_texts):
                text = str(option_texts[idx] or "").strip() or f"选项{idx + 1}"
                labels.append(f"{idx + 1}. {text}")
            else:
                labels.append(f"{idx + 1}")
        return "；".join(labels)

    def _refresh_table(self) -> None:
        self.table.setRowCount(0)
        for row, rule in enumerate(self._rules):
            self.table.insertRow(row)
            condition_num = _to_int(rule.get("condition_question_num"), 0)
            target_num = _to_int(rule.get("target_question_num"), 0)
            condition_mode = str(rule.get("condition_mode") or "selected").strip()
            action_mode = str(rule.get("action_mode") or "must_select").strip()
            condition_options = _to_int_list(rule.get("condition_option_indices"))
            target_options = _to_int_list(rule.get("target_option_indices"))
            raw_cri = rule.get("condition_row_index")
            condition_row_index: Optional[int] = _to_int(raw_cri, -1) if raw_cri is not None else None
            if condition_row_index is not None and condition_row_index < 0:
                condition_row_index = None
            raw_tri = rule.get("target_row_index")
            target_row_index: Optional[int] = _to_int(raw_tri, -1) if raw_tri is not None else None
            if target_row_index is not None and target_row_index < 0:
                target_row_index = None

            self.table.setItem(row, 0, QTableWidgetItem(self._question_label_by_num(condition_num, condition_row_index)))
            self.table.setItem(row, 1, QTableWidgetItem(_CONDITION_MODE_LABELS.get(condition_mode, condition_mode)))
            self.table.setItem(row, 2, QTableWidgetItem(self._option_label_text(condition_num, condition_options)))
            self.table.setItem(row, 3, QTableWidgetItem(self._question_label_by_num(target_num, target_row_index)))
            self.table.setItem(row, 4, QTableWidgetItem(_ACTION_MODE_LABELS.get(action_mode, action_mode)))
            self.table.setItem(row, 5, QTableWidgetItem(self._option_label_text(target_num, target_options)))

