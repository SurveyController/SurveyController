from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    HorizontalSeparator,
    LineEdit,
    PushButton,
)

from software.app.config import DEFAULT_FILL_TEXT
from surveycore.core.questions.config import QuestionEntry
from surveycore.core.questions.utils import try_parse_random_int_range
from surveycore.providers.contracts import SurveyQuestionMeta

from .fill_mode_selector import (
    FILL_MODE_AI,
    FILL_MODE_ID_CARD,
    FILL_MODE_INTEGER,
    FILL_MODE_MOBILE,
    FILL_MODE_NAME,
    FILL_MODE_NONE,
    FillModeSelector,
)
from .utils import _apply_label_color
from .wizard_sections_common import _TEXT_RANDOM_NONE

_MODE_PLACEHOLDERS = {
    FILL_MODE_NONE: DEFAULT_FILL_TEXT,
    FILL_MODE_AI: "AI 生成",
    FILL_MODE_NAME: "随机姓名",
    FILL_MODE_MOBILE: "随机手机号",
    FILL_MODE_ID_CARD: "随机身份证",
    FILL_MODE_INTEGER: "随机整数",
}


class WizardSectionsTextMixin:
    if TYPE_CHECKING:
        _has_content: bool
        text_container_map: Dict[int, QWidget]
        text_add_btn_map: Dict[int, PushButton]
        text_random_mode_map: Dict[int, str]
        text_random_int_min_edit_map: Dict[int, LineEdit]
        text_random_int_max_edit_map: Dict[int, LineEdit]
        ai_check_map: Dict[int, Any]
        text_edit_map: Dict[int, Any]
        multi_text_blank_integer_range_edits: Dict[int, List[Tuple[LineEdit, LineEdit]]]
        multi_text_blank_radio_groups: Dict[int, List[Any]]
        multi_text_blank_ai_checkboxes: Dict[int, List[Any]]

        def _get_entry_info(self, idx: int) -> SurveyQuestionMeta: ...
        @staticmethod
        def _resolve_text_random_int_range(
            entry: QuestionEntry,
        ) -> Tuple[Optional[int], Optional[int]]: ...
        @staticmethod
        def _resolve_text_random_mode(entry: QuestionEntry) -> str: ...

    def _build_text_section(
        self,
        idx: int,
        entry: QuestionEntry,
        card: CardWidget,
        card_layout: QVBoxLayout,
    ) -> None:
        self._has_content = True

        info_entry = self._get_entry_info(idx)
        text_input_count = info_entry.get("text_inputs", 0)
        is_multi_text_flag = info_entry.get("is_multi_text", False)
        if is_multi_text_flag or entry.question_type == "multi_text":
            blank_count = max(1, text_input_count)
            self._build_multi_text_matrix_input(idx, entry, card, card_layout, blank_count)
            return

        random_mode = self._resolve_text_random_mode(entry)
        random_int_min, random_int_max = self._resolve_text_random_int_range(entry)
        ai_enabled = bool(getattr(entry, "ai_enabled", False)) and random_mode == _TEXT_RANDOM_NONE
        initial_mode = FILL_MODE_AI if ai_enabled else random_mode

        selector = FillModeSelector(
            card,
            list_label="答案列表",
            min_value=random_int_min,
            max_value=random_int_max,
        )
        selector.set_mode(initial_mode, emit=False)

        add_btn = PushButton("+ 添加答案", selector)
        add_btn.setFixedWidth(100)
        selector.add_inline_widget(add_btn)

        symbolic_edit = LineEdit(selector)
        symbolic_edit.setEnabled(False)
        selector.add_inline_widget(symbolic_edit, 1)
        card_layout.addWidget(selector)

        text_rows_container = QWidget(card)
        text_rows_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        text_rows_container.setAutoFillBackground(False)
        text_rows_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        text_rows_layout = QVBoxLayout(text_rows_container)
        text_rows_layout.setContentsMargins(0, 2, 0, 0)
        text_rows_layout.setSpacing(4)
        card_layout.addWidget(text_rows_container)

        texts = list(entry.texts or [DEFAULT_FILL_TEXT])
        edits: List[LineEdit] = []

        def renumber_single_text_rows() -> None:
            for row_index in range(text_rows_layout.count()):
                row_item = text_rows_layout.itemAt(row_index)
                row_widget = row_item.widget() if row_item is not None else None
                if row_widget is None:
                    continue
                labels = row_widget.findChildren(BodyLabel)
                if labels:
                    labels[0].setText(f"{row_index + 1}.")

        def add_row(initial_text: str = "") -> None:
            row_widget = QWidget(text_rows_container)
            row_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
            row_widget.setAutoFillBackground(False)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(8)

            num_lbl = BodyLabel(f"{len(edits) + 1}.", row_widget)
            num_lbl.setFixedWidth(24)
            num_lbl.setStyleSheet("font-size: 12px;")
            _apply_label_color(num_lbl, "#888888", "#a6a6a6")
            row_layout.addWidget(num_lbl)

            edit = LineEdit(row_widget)
            normalized_initial = str(initial_text or "").strip()
            edit.setText("" if normalized_initial == DEFAULT_FILL_TEXT else normalized_initial)
            edit.setPlaceholderText(DEFAULT_FILL_TEXT)
            row_layout.addWidget(edit, 1)

            del_btn = PushButton("×", row_widget)
            del_btn.setFixedWidth(32)
            row_layout.addWidget(del_btn)

            text_rows_layout.addWidget(row_widget)
            edits.append(edit)

            def remove_row() -> None:
                if len(edits) > 1:
                    edits.remove(edit)
                    row_widget.deleteLater()
                    QTimer.singleShot(0, renumber_single_text_rows)

            del_btn.clicked.connect(remove_row)

        for txt in texts:
            add_row(txt)

        add_btn.clicked.connect(lambda checked=False: add_row(""))

        def sync_single_text_visibility(mode: str) -> None:
            is_list = mode == FILL_MODE_NONE
            is_integer = mode == FILL_MODE_INTEGER
            show_symbolic = not is_list and not is_integer
            add_btn.setVisible(is_list)
            text_rows_container.setVisible(is_list)
            symbolic_edit.setVisible(show_symbolic)
            symbolic_edit.setPlaceholderText(_MODE_PLACEHOLDERS.get(mode, ""))
            selector.set_trailing_stretch(is_list or is_integer)

        sync_single_text_visibility(initial_mode)

        def on_mode_changed(mode: str) -> None:
            self.text_random_mode_map[idx] = selector.random_mode()
            sync_single_text_visibility(mode)

        selector.modeChanged.connect(on_mode_changed)

        self.text_container_map[idx] = text_rows_container
        self.text_add_btn_map[idx] = add_btn
        self.text_random_mode_map[idx] = selector.random_mode()
        self.text_random_int_min_edit_map[idx] = selector.min_edit
        self.text_random_int_max_edit_map[idx] = selector.max_edit
        self.ai_check_map[idx] = selector.ai_proxy()
        self.text_edit_map[idx] = edits

    def _build_multi_text_matrix_input(
        self,
        idx: int,
        entry: QuestionEntry,
        card: CardWidget,
        card_layout: QVBoxLayout,
        blank_count: int,
    ) -> None:
        from surveycore.core.questions.text_shared import MULTI_TEXT_DELIMITER

        saved_modes = getattr(entry, "multi_text_blank_modes", None) or []
        if not isinstance(saved_modes, list):
            saved_modes = []
        while len(saved_modes) < blank_count:
            saved_modes.append(_TEXT_RANDOM_NONE)

        saved_ai_flags = getattr(entry, "multi_text_blank_ai_flags", None) or []
        if not isinstance(saved_ai_flags, list):
            saved_ai_flags = []
        while len(saved_ai_flags) < blank_count:
            saved_ai_flags.append(False)

        saved_int_ranges = getattr(entry, "multi_text_blank_int_ranges", None) or []
        if not isinstance(saved_int_ranges, list):
            saved_int_ranges = []
        while len(saved_int_ranges) < blank_count:
            saved_int_ranges.append([])

        selectors_container = QWidget(card)
        selectors_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        selectors_container.setAutoFillBackground(False)
        selectors_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        selectors_layout = QVBoxLayout(selectors_container)
        selectors_layout.setContentsMargins(0, 0, 0, 0)
        selectors_layout.setSpacing(6)

        blank_selectors: List[FillModeSelector] = []
        for blank_idx in range(blank_count):
            parsed_range = try_parse_random_int_range(saved_int_ranges[blank_idx])
            range_min, range_max = parsed_range if parsed_range is not None else (None, None)
            current_mode = (
                str(saved_modes[blank_idx] or _TEXT_RANDOM_NONE).strip().lower()
                if blank_idx < len(saved_modes)
                else _TEXT_RANDOM_NONE
            )
            ai_flag = bool(saved_ai_flags[blank_idx]) if blank_idx < len(saved_ai_flags) else False
            initial_mode = (
                FILL_MODE_AI if ai_flag and current_mode == _TEXT_RANDOM_NONE else current_mode
            )

            selector = FillModeSelector(
                selectors_container,
                leading_label=f"填空{blank_idx + 1}",
                leading_width=48,
                list_label="答案列表",
                min_value=range_min,
                max_value=range_max,
            )
            selector.set_mode(initial_mode, emit=False)
            selectors_layout.addWidget(selector)
            blank_selectors.append(selector)

        card_layout.addWidget(selectors_container)

        matrix_panel = QWidget(card)
        matrix_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        matrix_panel.setAutoFillBackground(False)
        matrix_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        matrix_layout = QVBoxLayout(matrix_panel)
        matrix_layout.setContentsMargins(0, 4, 0, 0)
        matrix_layout.setSpacing(4)

        matrix_layout.addWidget(HorizontalSeparator(matrix_panel))

        header_widget = QWidget(matrix_panel)
        header_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        header_widget.setAutoFillBackground(False)
        header_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 4, 0, 2)
        header_layout.setSpacing(8)

        num_spacer = QWidget(header_widget)
        num_spacer.setFixedWidth(24)
        header_layout.addWidget(num_spacer)

        for i in range(blank_count):
            col_label = BodyLabel(f"填空{i + 1}", header_widget)
            col_label.setStyleSheet("font-size: 11px; font-weight: bold;")
            _apply_label_color(col_label, "#888888", "#a6a6a6")
            header_layout.addWidget(col_label, 1)

        del_spacer = QWidget(header_widget)
        del_spacer.setFixedWidth(32)
        header_layout.addWidget(del_spacer)
        matrix_layout.addWidget(header_widget)

        rows_container = QWidget(matrix_panel)
        rows_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        rows_container.setAutoFillBackground(False)
        rows_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        rows_layout = QVBoxLayout(rows_container)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(4)
        matrix_layout.addWidget(rows_container)

        row_edits: List[List[LineEdit]] = []
        texts = list(entry.texts or [DEFAULT_FILL_TEXT])

        def renumber_multi_text_rows() -> None:
            for row_index in range(rows_layout.count()):
                row_item = rows_layout.itemAt(row_index)
                row_widget = row_item.widget() if row_item is not None else None
                if row_widget is None:
                    continue
                labels = row_widget.findChildren(BodyLabel)
                if labels:
                    labels[0].setText(f"{row_index + 1}.")

        def sync_column_states() -> None:
            any_list = any(sel.current_mode() == FILL_MODE_NONE for sel in blank_selectors)
            matrix_panel.setVisible(any_list)
            for col_idx, sel in enumerate(blank_selectors):
                mode = sel.current_mode()
                use_list = mode == FILL_MODE_NONE
                placeholder = _MODE_PLACEHOLDERS.get(mode, DEFAULT_FILL_TEXT)
                for row in row_edits:
                    if col_idx < len(row):
                        row[col_idx].setEnabled(use_list)
                        row[col_idx].setPlaceholderText(placeholder)

        def add_row(initial_values: Optional[List[str]] = None) -> None:
            values: List[str] = initial_values if initial_values is not None else [""] * blank_count

            row_widget = QWidget(rows_container)
            row_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
            row_widget.setAutoFillBackground(False)
            row_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(8)

            num_lbl = BodyLabel(f"{len(row_edits) + 1}.", row_widget)
            num_lbl.setFixedWidth(24)
            num_lbl.setStyleSheet("font-size: 12px;")
            _apply_label_color(num_lbl, "#888888", "#a6a6a6")
            row_layout.addWidget(num_lbl)

            edits_in_row: List[LineEdit] = []
            for i in range(blank_count):
                edit = LineEdit(row_widget)
                normalized_value = str(values[i] if i < len(values) else "").strip()
                edit.setText("" if normalized_value == DEFAULT_FILL_TEXT else normalized_value)
                edit.setPlaceholderText(DEFAULT_FILL_TEXT)
                edit.setMinimumWidth(72)
                edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                row_layout.addWidget(edit, 1)
                edits_in_row.append(edit)

            del_btn = PushButton("×", row_widget)
            del_btn.setFixedWidth(32)
            row_layout.addWidget(del_btn)

            rows_layout.addWidget(row_widget)
            row_edits.append(edits_in_row)

            def remove_row() -> None:
                if len(row_edits) > 1:
                    row_edits.remove(edits_in_row)
                    row_widget.deleteLater()
                    QTimer.singleShot(0, renumber_multi_text_rows)

            del_btn.clicked.connect(remove_row)
            sync_column_states()

        for text in texts:
            parts = text.split(MULTI_TEXT_DELIMITER) if MULTI_TEXT_DELIMITER in text else [text]
            while len(parts) < blank_count:
                parts.append("")
            parts = parts[:blank_count]
            add_row(parts)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        add_btn = PushButton("+ 添加答案组", matrix_panel)
        add_btn.setFixedWidth(120)
        add_btn.clicked.connect(lambda checked=False: add_row(None))
        btn_row.addWidget(add_btn)
        btn_row.addStretch(1)
        matrix_layout.addLayout(btn_row)
        card_layout.addWidget(matrix_panel)

        for sel in blank_selectors:
            sel.modeChanged.connect(lambda _mode: sync_column_states())
        sync_column_states()

        if not hasattr(self, "multi_text_blank_radio_groups"):
            self.multi_text_blank_radio_groups = {}
        if not hasattr(self, "multi_text_blank_ai_checkboxes"):
            self.multi_text_blank_ai_checkboxes = {}
        if not hasattr(self, "multi_text_blank_integer_range_edits"):
            self.multi_text_blank_integer_range_edits = {}

        self.text_edit_map[idx] = row_edits
        self.text_container_map[idx] = rows_container
        self.text_add_btn_map[idx] = add_btn
        self.multi_text_blank_radio_groups[idx] = [sel.group_proxy() for sel in blank_selectors]
        self.multi_text_blank_ai_checkboxes[idx] = [sel.ai_proxy() for sel in blank_selectors]
        self.multi_text_blank_integer_range_edits[idx] = [
            (sel.min_edit, sel.max_edit) for sel in blank_selectors
        ]
