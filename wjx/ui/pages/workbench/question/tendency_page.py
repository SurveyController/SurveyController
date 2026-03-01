"""倾向设置页面：集中展示倾向题配置，同时支持填空题编辑。"""
from typing import List, Dict, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import (
    ScrollArea,
    BodyLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    SegmentedWidget,
    PushButton,
    LineEdit,
)

from wjx.core.questions.config import QuestionEntry
from wjx.utils.app.config import DEFAULT_FILL_TEXT
from wjx.ui.helpers.ai_fill import ensure_ai_ready
from wjx.ui.pages.workbench.question.psycho_config import (
    PSYCHO_SUPPORTED_TYPES,
    PSYCHO_BIAS_CHOICES,
)
from wjx.ui.pages.workbench.question.utils import _shorten_text, _apply_label_color
from wjx.ui.pages.workbench.question.constants import _get_entry_type_label
from wjx.ui.pages.workbench.question.wizard_sections import (
    _TEXT_RANDOM_NONE,
    _TEXT_RANDOM_NAME,
    _TEXT_RANDOM_MOBILE,
)

_TEXT_RANDOM_NAME_TOKEN = "__RANDOM_NAME__"
_TEXT_RANDOM_MOBILE_TOKEN = "__RANDOM_MOBILE__"


class TendencySettingsPage(QWidget):
    """倾向设置页面：集中管理潜变量配置，并允许直接编辑填空题答案。"""

    def __init__(
        self,
        entries: List[QuestionEntry],
        info: List[Dict[str, Any]],
        psycho_check_map: Dict[int, CheckBox],
        psycho_bias_map: Dict[int, ComboBox],
        text_edit_map: Dict[int, List[LineEdit]],
        text_random_mode_map: Dict[int, str],
        text_random_name_check_map: Dict[int, CheckBox],
        text_random_mobile_check_map: Dict[int, CheckBox],
        ai_check_map: Dict[int, CheckBox],
        text_container_map: Dict[int, QWidget],
        text_add_btn_map: Dict[int, PushButton],
        parent=None,
    ):
        super().__init__(parent)
        self.entries = entries
        self.info = info
        self.psycho_check_map = psycho_check_map
        self.psycho_bias_map = psycho_bias_map
        self.local_bias_map: Dict[int, ComboBox] = {}

        self.text_edit_map = text_edit_map
        self.text_random_mode_map = text_random_mode_map
        self.text_random_name_check_map = text_random_name_check_map
        self.text_random_mobile_check_map = text_random_mobile_check_map
        self.ai_check_map = ai_check_map
        self.text_container_map = text_container_map
        self.text_add_btn_map = text_add_btn_map

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        supported_entries = [
            (idx, entry)
            for idx, entry in enumerate(self.entries)
            if entry.question_type in PSYCHO_SUPPORTED_TYPES
        ]
        text_entries = [
            (idx, entry)
            for idx, entry in enumerate(self.entries)
            if entry.question_type in ("text", "multi_text")
        ]

        if supported_entries:
            batch_card = CardWidget(self)
            batch_layout = QHBoxLayout(batch_card)
            batch_layout.setContentsMargins(16, 12, 16, 12)
            batch_layout.setSpacing(12)

            batch_label = BodyLabel("一键设置总体倾向：", batch_card)
            batch_label.setStyleSheet("font-size: 13px; font-weight: 500;")
            batch_layout.addWidget(batch_label)

            self.batch_seg = SegmentedWidget(batch_card)
            for value, text in PSYCHO_BIAS_CHOICES:
                self.batch_seg.addItem(routeKey=value, text=text)
            self.batch_seg.setCurrentItem("center")
            self.batch_seg.currentItemChanged.connect(self._on_batch_bias_changed)
            batch_layout.addWidget(self.batch_seg)

            batch_layout.addStretch(1)
            layout.addWidget(batch_card)
        else:
            self.batch_seg = None

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.enableTransparentBackground()
        container = QWidget(self)
        scroll.setWidget(container)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(4, 4, 12, 4)
        inner.setSpacing(8)

        if supported_entries:
            section = BodyLabel("倾向题配置（单选 / 量表 / 评分 / 下拉 / 矩阵）", container)
            section.setStyleSheet("font-size: 13px; font-weight: 600; padding: 4px 0;")
            _apply_label_color(section, "#d97706", "#e5a00d")
            inner.addWidget(section)
            for idx, entry in supported_entries:
                self._build_question_row(idx, entry, container, inner)

        if text_entries:
            section = BodyLabel("填空题配置（与权重模式一致）", container)
            section.setStyleSheet("font-size: 13px; font-weight: 600; padding: 8px 0 4px 0;")
            _apply_label_color(section, "#0078d4", "#4da6ff")
            inner.addWidget(section)
            for idx, entry in text_entries:
                self._build_text_row(idx, entry, container, inner)

        if not supported_entries and not text_entries:
            empty_label = BodyLabel(
                "当前问卷中没有可在倾向模式配置的题目\n（支持：单选、量表、评分、下拉、矩阵、填空）",
                container,
            )
            empty_label.setStyleSheet("color: #888; font-size: 14px; padding: 40px;")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setWordWrap(True)
            inner.addWidget(empty_label)

        inner.addStretch(1)
        layout.addWidget(scroll, 1)

    def _build_question_row(
        self, idx: int, entry: QuestionEntry, container: QWidget, layout: QVBoxLayout
    ):
        # 切到倾向模式时默认全部启用
        entry.psycho_enabled = True

        qnum = ""
        title_text = ""
        if idx < len(self.info):
            qnum = str(self.info[idx].get("num") or "")
            title_text = str(self.info[idx].get("title") or "")

        card = CardWidget(container)
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(12, 8, 12, 8)
        card_layout.setSpacing(12)

        num_label = BodyLabel(f"第{qnum or idx + 1}题", card)
        num_label.setFixedWidth(60)
        num_label.setStyleSheet("font-size: 13px; font-weight: 500;")
        card_layout.addWidget(num_label)

        type_label = BodyLabel(f"[{_get_entry_type_label(entry)}]", card)
        type_label.setFixedWidth(70)
        type_label.setStyleSheet("font-size: 12px;")
        _apply_label_color(type_label, "#d97706", "#e5a00d")
        card_layout.addWidget(type_label)

        title_label = BodyLabel(_shorten_text(title_text, 50), card)
        title_label.setStyleSheet("font-size: 13px;")
        title_label.setWordWrap(False)
        _apply_label_color(title_label, "#333333", "#e0e0e0")
        card_layout.addWidget(title_label, 1)

        bias_combo = ComboBox(card)
        bias_combo.setFixedWidth(160)
        for value, text in PSYCHO_BIAS_CHOICES:
            bias_combo.addItem(text, userData=value)

        current_bias = getattr(entry, "psycho_bias", "center")
        for i, (value, _) in enumerate(PSYCHO_BIAS_CHOICES):
            if value == current_bias:
                bias_combo.setCurrentIndex(i)
                break

        bias_combo.currentIndexChanged.connect(
            lambda index, i=idx: self._on_bias_changed(i, index)
        )
        card_layout.addWidget(bias_combo)

        layout.addWidget(card)

        self.local_bias_map[idx] = bias_combo
        self.psycho_bias_map[idx] = bias_combo

    def _build_text_row(
        self, idx: int, entry: QuestionEntry, container: QWidget, layout: QVBoxLayout
    ) -> None:
        qnum = ""
        title_text = ""
        if idx < len(self.info):
            qnum = str(self.info[idx].get("num") or "")
            title_text = str(self.info[idx].get("title") or "")

        card = CardWidget(container)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(12)
        num_label = BodyLabel(f"第{qnum or idx + 1}题", card)
        num_label.setFixedWidth(60)
        num_label.setStyleSheet("font-size: 13px; font-weight: 500;")
        header.addWidget(num_label)

        type_label = BodyLabel(f"[{_get_entry_type_label(entry)}]", card)
        type_label.setFixedWidth(70)
        type_label.setStyleSheet("font-size: 12px;")
        _apply_label_color(type_label, "#0078d4", "#4da6ff")
        header.addWidget(type_label)

        title_label = BodyLabel(_shorten_text(title_text, 60), card)
        title_label.setStyleSheet("font-size: 13px;")
        _apply_label_color(title_label, "#333333", "#e0e0e0")
        header.addWidget(title_label, 1)
        card_layout.addLayout(header)

        hint = BodyLabel("答案列表（随机选择一个填入）：", card)
        hint.setStyleSheet("font-size: 12px;")
        _apply_label_color(hint, "#666666", "#bfbfbf")
        card_layout.addWidget(hint)

        text_rows_container = QWidget(card)
        text_rows_layout = QVBoxLayout(text_rows_container)
        text_rows_layout.setContentsMargins(0, 0, 0, 0)
        text_rows_layout.setSpacing(4)
        card_layout.addWidget(text_rows_container)

        texts = list(entry.texts or [DEFAULT_FILL_TEXT])
        edits: List[LineEdit] = []

        def add_row(initial_text: str = "") -> None:
            row_widget = QWidget(card)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(8)

            num_lbl = BodyLabel(f"{len(edits) + 1}.", card)
            num_lbl.setFixedWidth(24)
            num_lbl.setStyleSheet("font-size: 12px;")
            _apply_label_color(num_lbl, "#888888", "#a6a6a6")
            row_layout.addWidget(num_lbl)

            edit = LineEdit(card)
            edit.setText(initial_text)
            edit.setPlaceholderText("输入答案")
            row_layout.addWidget(edit, 1)

            del_btn = PushButton("×", card)
            del_btn.setFixedWidth(32)
            row_layout.addWidget(del_btn)
            text_rows_layout.addWidget(row_widget)
            edits.append(edit)

            def remove_row() -> None:
                if len(edits) > 1:
                    edits.remove(edit)
                    row_widget.deleteLater()

            del_btn.clicked.connect(remove_row)

        for txt in texts:
            add_row(txt)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        add_btn = PushButton("+ 添加答案", card)
        add_btn.setFixedWidth(100)
        add_btn.clicked.connect(lambda checked=False: add_row(""))
        btn_row.addWidget(add_btn)

        self.text_container_map[idx] = text_rows_container
        self.text_add_btn_map[idx] = add_btn
        self.text_edit_map[idx] = edits

        if entry.question_type == "text":
            random_row = QHBoxLayout()
            random_row.setSpacing(8)
            random_hint = BodyLabel("随机处理：", card)
            random_hint.setStyleSheet("font-size: 12px;")
            _apply_label_color(random_hint, "#666666", "#bfbfbf")
            random_row.addWidget(random_hint)

            random_name_cb = CheckBox("随机姓名", card)
            random_mobile_cb = CheckBox("随机手机号", card)
            random_row.addWidget(random_name_cb)
            random_row.addWidget(random_mobile_cb)
            random_row.addStretch(1)
            card_layout.addLayout(random_row)

            self.text_random_name_check_map[idx] = random_name_cb
            self.text_random_mobile_check_map[idx] = random_mobile_cb

            random_name_cb.toggled.connect(
                lambda checked, i=idx: self._on_text_random_mode_toggled(i, _TEXT_RANDOM_NAME, checked)
            )
            random_mobile_cb.toggled.connect(
                lambda checked, i=idx: self._on_text_random_mode_toggled(i, _TEXT_RANDOM_MOBILE, checked)
            )

            ai_cb = CheckBox("启用 AI", card)
            ai_cb.setToolTip("运行时每次填空都会调用 AI")
            ai_cb.setChecked(bool(getattr(entry, "ai_enabled", False)))
            ai_cb.toggled.connect(lambda checked, i=idx: self._on_entry_ai_toggled(i, checked))
            btn_row.addWidget(ai_cb)
            self.ai_check_map[idx] = ai_cb

            random_mode = self._resolve_text_random_mode(entry)
            self.text_random_mode_map[idx] = random_mode
            if random_mode == _TEXT_RANDOM_NAME:
                random_name_cb.setChecked(True)
            elif random_mode == _TEXT_RANDOM_MOBILE:
                random_mobile_cb.setChecked(True)
            self._sync_text_section_state(idx)
        else:
            self._set_text_answer_enabled(idx, True)

        btn_row.addStretch(1)
        card_layout.addLayout(btn_row)
        layout.addWidget(card)

    def _on_bias_changed(self, idx: int, index: int):
        if 0 <= index < len(PSYCHO_BIAS_CHOICES):
            if idx < len(self.entries):
                self.entries[idx].psycho_bias = PSYCHO_BIAS_CHOICES[index][0]

    def _on_batch_bias_changed(self, route_key: str):
        if not self.local_bias_map:
            return
        for i, (value, _) in enumerate(PSYCHO_BIAS_CHOICES):
            if value == route_key:
                bias_index, bias_value = i, value
                break
        else:
            return
        for idx, combo in self.local_bias_map.items():
            combo.blockSignals(True)
            combo.setCurrentIndex(bias_index)
            combo.blockSignals(False)
            if idx < len(self.entries):
                self.entries[idx].psycho_bias = bias_value

    def _set_text_answer_enabled(self, idx: int, enabled: bool) -> None:
        container = self.text_container_map.get(idx)
        if container:
            container.setEnabled(enabled)
        add_btn = self.text_add_btn_map.get(idx)
        if add_btn:
            add_btn.setEnabled(enabled)

    @staticmethod
    def _resolve_text_random_mode(entry: QuestionEntry) -> str:
        mode = str(getattr(entry, "text_random_mode", _TEXT_RANDOM_NONE) or _TEXT_RANDOM_NONE).strip().lower()
        if mode in (_TEXT_RANDOM_NAME, _TEXT_RANDOM_MOBILE):
            return mode
        for raw in (entry.texts or []):
            token = str(raw or "").strip()
            if token == _TEXT_RANDOM_NAME_TOKEN:
                return _TEXT_RANDOM_NAME
            if token == _TEXT_RANDOM_MOBILE_TOKEN:
                return _TEXT_RANDOM_MOBILE
        return _TEXT_RANDOM_NONE

    def _sync_text_section_state(self, idx: int) -> None:
        random_mode = self.text_random_mode_map.get(idx, _TEXT_RANDOM_NONE)
        ai_cb = self.ai_check_map.get(idx)
        if random_mode != _TEXT_RANDOM_NONE:
            if ai_cb:
                ai_cb.blockSignals(True)
                ai_cb.setChecked(False)
                ai_cb.blockSignals(False)
                ai_cb.setEnabled(False)
            self._set_text_answer_enabled(idx, False)
            return
        if ai_cb:
            ai_cb.setEnabled(True)
            self._set_text_answer_enabled(idx, not ai_cb.isChecked())
            return
        self._set_text_answer_enabled(idx, True)

    def _on_text_random_mode_toggled(self, idx: int, mode: str, checked: bool) -> None:
        if checked:
            name_cb = self.text_random_name_check_map.get(idx)
            mobile_cb = self.text_random_mobile_check_map.get(idx)
            if mode == _TEXT_RANDOM_NAME and mobile_cb and mobile_cb.isChecked():
                mobile_cb.blockSignals(True)
                mobile_cb.setChecked(False)
                mobile_cb.blockSignals(False)
            if mode == _TEXT_RANDOM_MOBILE and name_cb and name_cb.isChecked():
                name_cb.blockSignals(True)
                name_cb.setChecked(False)
                name_cb.blockSignals(False)
            self.text_random_mode_map[idx] = mode
        else:
            current_mode = _TEXT_RANDOM_NONE
            name_cb = self.text_random_name_check_map.get(idx)
            mobile_cb = self.text_random_mobile_check_map.get(idx)
            if name_cb and name_cb.isChecked():
                current_mode = _TEXT_RANDOM_NAME
            elif mobile_cb and mobile_cb.isChecked():
                current_mode = _TEXT_RANDOM_MOBILE
            self.text_random_mode_map[idx] = current_mode
        self._sync_text_section_state(idx)

    def _on_entry_ai_toggled(self, idx: int, checked: bool) -> None:
        random_mode = self.text_random_mode_map.get(idx, _TEXT_RANDOM_NONE)
        if random_mode != _TEXT_RANDOM_NONE:
            cb = self.ai_check_map.get(idx)
            if cb:
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)
                cb.setEnabled(False)
            self._set_text_answer_enabled(idx, False)
            return
        if checked and not ensure_ai_ready(self.window() or self):
            cb = self.ai_check_map.get(idx)
            if cb:
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)
            self._set_text_answer_enabled(idx, True)
            return
        self._set_text_answer_enabled(idx, not checked)
