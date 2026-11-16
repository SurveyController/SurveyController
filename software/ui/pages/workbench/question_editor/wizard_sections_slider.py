from typing import TYPE_CHECKING, Any, Dict, List, cast

from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QPropertyAnimation,
    QTimer,
    Qt,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QSizePolicy, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    InfoBadge,
    LineEdit,
    SegmentedWidget,
)

from surveycore.core.questions.config import QuestionEntry
from surveycore.providers.contracts import SurveyQuestionMeta
from software.ui.widgets.no_wheel import NoWheelSlider

from .fill_mode_selector import (
    FILL_MODE_AI,
    FILL_MODE_ID_CARD,
    FILL_MODE_INTEGER,
    FILL_MODE_MOBILE,
    FILL_MODE_NAME,
    FILL_MODE_NONE,
    FillModeSelector,
)
from .psycho_config import (
    BIAS_PRESET_CHOICES,
    build_bias_weights,
    entry_supports_psycho_presets,
)
from .constants import ANSWER_WEIGHT_MAX, ANSWER_WEIGHT_MIN, MULTIPLE_OPTION_WEIGHT_MAX
from .utils import _apply_label_color, _bind_slider_input
from .wizard_sections_common import _TEXT_RANDOM_NONE


class WizardSectionsSliderMixin:
    if TYPE_CHECKING:
        _has_content: bool
        entries: List[QuestionEntry]
        bias_preset_map: Dict[int, Any]
        slider_map: Dict[int, List[NoWheelSlider]]
        option_fill_edit_map: Dict[int, Dict[int, LineEdit]]
        option_fill_state_map: Dict[int, Dict[int, Dict[str, Any]]]

        def _resolve_slider_bounds(self, idx: int, entry: QuestionEntry) -> tuple[int, int]: ...
        def _get_entry_info(self, idx: int) -> SurveyQuestionMeta: ...
        @staticmethod
        def _normalize_fillable_option_indices(
            raw_indices: Any, option_count: int
        ) -> List[int]: ...
        @staticmethod
        def _resolve_option_fill_mode(raw_value: Any) -> tuple[str, bool]: ...
        @staticmethod
        def _resolve_option_fill_int_range(
            raw_value: Any,
        ) -> tuple[int | None, int | None]: ...
        def _refresh_ratio_preview_label(
            self,
            label: BodyLabel,
            sliders: List[NoWheelSlider],
            option_names: List[str],
            prefix: str,
        ) -> None: ...
        def _build_media_text_widget(
            self,
            parent: QWidget,
            *,
            idx: int,
            scope: str,
            media_index: int | None,
            text: str,
            text_width: int,
            font_style: str,
        ) -> QWidget: ...

    def _build_slider_section(
        self,
        idx: int,
        entry: QuestionEntry,
        card: CardWidget,
        card_layout: QVBoxLayout,
        option_texts: List[str],
    ) -> None:
        self._has_content = True
        slider_min, slider_max = (0, 100)
        if entry.question_type == "slider":
            slider_min, slider_max = self._resolve_slider_bounds(idx, entry)
        options = max(1, int(entry.option_count or 1))

        _preset_seg = None
        if entry_supports_psycho_presets(entry, option_texts):
            preset_row = QHBoxLayout()
            preset_row.setSpacing(8)
            preset_label = BodyLabel("倾向预设：", card)
            preset_label.setStyleSheet("font-size: 12px;")
            _apply_label_color(preset_label, "#666666", "#bfbfbf")
            preset_row.addWidget(preset_label)
            _preset_seg = SegmentedWidget(card)
            for value, text in BIAS_PRESET_CHOICES:
                _preset_seg.addItem(routeKey=value, text=text)
            current_bias = getattr(entry, "psycho_bias", "custom") or "custom"
            _preset_seg.setCurrentItem(current_bias)
            preset_row.addWidget(_preset_seg)
            preset_row.addStretch(1)
            card_layout.addLayout(preset_row)
            self.bias_preset_map[idx] = _preset_seg
        if entry.question_type == "multiple":
            default_weight = 50
        elif entry.question_type == "slider":
            default_weight = int(round((slider_min + slider_max) / 2))
        else:
            default_weight = 1
        raw_weights: Any = entry.custom_weights
        if not isinstance(raw_weights, (list, tuple)) or not raw_weights:
            if isinstance(entry.probabilities, (list, tuple)):
                raw_weights = entry.probabilities
            else:
                raw_weights = []
        weights = cast(List[float], list(raw_weights or []))
        if len(weights) < options:
            weights += [default_weight] * (options - len(weights))

        sliders: List[NoWheelSlider] = []
        is_multiple = entry.question_type == "multiple"

        jump_map: Dict[int, int] = {}
        info_entry = self._get_entry_info(idx)
        fillable_option_indices = self._normalize_fillable_option_indices(
            info_entry.get("fillable_options"), options
        )
        if not fillable_option_indices:
            fillable_option_indices = self._normalize_fillable_option_indices(
                getattr(entry, "fillable_option_indices", None),
                options,
            )
        fillable_option_set = set(fillable_option_indices)
        saved_option_fill_texts = list(getattr(entry, "option_fill_texts", []) or [])
        option_fill_edits: Dict[int, LineEdit] = {}
        option_fill_states: Dict[int, Dict[str, Any]] = {}
        for rule in info_entry.get("jump_rules") or []:
            oi = rule.get("option_index")
            jt = rule.get("jumpto")
            if oi is not None and jt is not None:
                jump_map[oi] = jt

        for opt_idx in range(options):
            opt_widget = QWidget(card)
            opt_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            opt_layout = QVBoxLayout(opt_widget)
            opt_layout.setContentsMargins(0, 0, 0, 2)
            opt_layout.setSpacing(2)
            opt_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)

            header_row = QHBoxLayout()
            header_row.setContentsMargins(0, 0, 0, 0)
            header_row.setSpacing(8)

            num_label = BodyLabel(f"{opt_idx + 1}.", card)
            num_label.setFixedWidth(24)
            num_label.setStyleSheet("font-size: 12px;")
            _apply_label_color(num_label, "#888888", "#a6a6a6")
            header_row.addWidget(num_label)

            opt_text = option_texts[opt_idx] if opt_idx < len(option_texts) else "选项"
            option_widget = self._build_media_text_widget(
                card,
                idx=idx,
                scope="option",
                media_index=opt_idx,
                text=opt_text,
                text_width=0,
                font_style="font-size: 13px;",
            )
            header_row.addWidget(option_widget)

            if opt_idx in fillable_option_set:
                fill_badge = InfoBadge.custom(
                    "附带填空",
                    QColor("#038387"),
                    QColor("#4fd1c5"),
                    parent=card,
                )
                header_row.addWidget(fill_badge)

            has_jump = bool(info_entry.get("has_jump"))
            if has_jump and opt_idx in jump_map:
                jumpto = jump_map[opt_idx]
                total_questions = len(self.entries)
                jump_text = "提前结束" if jumpto > total_questions else f"跳至第{jumpto}题"
                jump_badge = InfoBadge.custom(
                    jump_text,
                    QColor("#d93025"),
                    QColor("#ff6b6b"),
                    parent=card,
                )
                header_row.addWidget(jump_badge)

            slider = NoWheelSlider(Qt.Orientation.Horizontal, card)
            if entry.question_type == "slider":
                slider.setRange(slider_min, slider_max)
            elif is_multiple:
                slider.setRange(ANSWER_WEIGHT_MIN, MULTIPLE_OPTION_WEIGHT_MAX)
            else:
                slider.setRange(ANSWER_WEIGHT_MIN, ANSWER_WEIGHT_MAX)
            slider.setValue(
                int(
                    min(
                        slider.maximum(),
                        max(slider.minimum(), int(weights[opt_idx])),
                    )
                )
            )
            header_row.addStretch(1)

            control_row = QHBoxLayout()
            control_row.setContentsMargins(18, 0, 0, 0)
            control_row.setSpacing(8)

            value_input = LineEdit(card)
            value_input.setFixedWidth(52)
            value_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value_input.setText(str(slider.value()))
            _bind_slider_input(slider, value_input)
            percent_label = None
            if is_multiple:
                percent_label = BodyLabel("%", card)
                percent_label.setFixedWidth(12)
                percent_label.setAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                _apply_label_color(percent_label, "#666666", "#bfbfbf")

            slider.setMinimumWidth(48)
            slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            opt_layout.addLayout(header_row)
            control_row.addWidget(slider, 1)
            control_row.addWidget(value_input)
            if percent_label is not None:
                control_row.addWidget(percent_label)
            opt_layout.addLayout(control_row)

            card_layout.addWidget(opt_widget)
            sliders.append(slider)

            if opt_idx in fillable_option_set:
                raw_fill_value = (
                    saved_option_fill_texts[opt_idx]
                    if opt_idx < len(saved_option_fill_texts)
                    else None
                )
                fill_mode, fill_ai_enabled = self._resolve_option_fill_mode(raw_fill_value)
                range_min, range_max = self._resolve_option_fill_int_range(raw_fill_value)

                fill_container = QWidget(card)
                fill_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
                fill_container.setAutoFillBackground(False)
                fill_layout = QVBoxLayout(fill_container)
                fill_layout.setContentsMargins(18, 2, 0, 6)
                fill_layout.setSpacing(0)

                selector = FillModeSelector(
                    fill_container,
                    list_label="指定文本",
                    min_value=range_min,
                    max_value=range_max,
                )

                fill_edit = LineEdit(selector)
                existing_fill = ""
                if (
                    fill_mode == _TEXT_RANDOM_NONE
                    and not fill_ai_enabled
                    and opt_idx < len(saved_option_fill_texts)
                ):
                    existing_fill = str(saved_option_fill_texts[opt_idx] or "").strip()
                if existing_fill:
                    fill_edit.setText(existing_fill)
                default_placeholder = (
                    "例如：无"
                    if entry.question_type == "single"
                    else "输入命中该选项时要填写的内容"
                )
                mode_placeholders = {
                    FILL_MODE_NONE: default_placeholder,
                    FILL_MODE_AI: "AI 生成",
                    FILL_MODE_NAME: "随机姓名",
                    FILL_MODE_MOBILE: "随机手机号",
                    FILL_MODE_ID_CARD: "随机身份证",
                }
                fill_edit.setPlaceholderText(default_placeholder)
                selector.add_inline_widget(fill_edit, 1)

                active_mode = FILL_MODE_AI if fill_ai_enabled else fill_mode
                selector.set_mode(active_mode, emit=False)

                def _sync_option_fill(
                    mode: str,
                    edit: LineEdit = fill_edit,
                    sel: FillModeSelector = selector,
                    placeholders: Dict[str, str] = mode_placeholders,
                ) -> None:
                    is_text = mode == FILL_MODE_NONE
                    is_integer = mode == FILL_MODE_INTEGER
                    edit.setVisible(not is_integer)
                    edit.setEnabled(is_text)
                    edit.setPlaceholderText(placeholders.get(mode, ""))
                    sel.set_trailing_stretch(is_integer)

                _sync_option_fill(active_mode)
                selector.modeChanged.connect(_sync_option_fill)

                fill_layout.addWidget(selector)
                card_layout.addWidget(fill_container)
                option_fill_edits[opt_idx] = fill_edit
                option_fill_states[opt_idx] = {
                    "edit": fill_edit,
                    "group": selector.group_proxy(),
                    "min_edit": selector.min_edit,
                    "max_edit": selector.max_edit,
                    "ai_cb": selector.ai_proxy(),
                    "selector": selector,
                }

        self.slider_map[idx] = sliders
        if option_fill_edits:
            self.option_fill_edit_map[idx] = option_fill_edits
        if option_fill_states:
            self.option_fill_state_map[idx] = option_fill_states

        if entry.question_type in ("single", "dropdown", "scale", "score"):
            ratio_preview_label = BodyLabel("", card)
            ratio_preview_label.setWordWrap(True)
            ratio_preview_label.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Maximum,
            )
            ratio_preview_label.setStyleSheet("font-size: 12px;")
            _apply_label_color(ratio_preview_label, "#666666", "#bfbfbf")
            card_layout.addWidget(ratio_preview_label)

            def _update_option_preview(_value: int = 0):
                self._refresh_ratio_preview_label(
                    ratio_preview_label,
                    sliders,
                    option_texts,
                    "预计占比（仅供参考）：",
                )

            for slider in sliders:
                slider.valueChanged.connect(_update_option_preview)
            _update_option_preview()

        if _preset_seg is not None:
            _applying_preset = [False]

            _slider_anims: Dict[object, QPropertyAnimation] = {}

            def _on_preset_changed(
                route_key: str,
                _sliders=sliders,
                _flag=_applying_preset,
                _sa=_slider_anims,
            ):
                if route_key == "custom":
                    return
                _flag[0] = True
                weights = build_bias_weights(len(_sliders), route_key)
                for si, sl in enumerate(_sliders):
                    old = _sa.get(sl)
                    if old:
                        old.stop()
                    target = int(weights[si]) if si < len(weights) else 1
                    anim = QPropertyAnimation(sl, QByteArray(b"value"), sl)
                    anim.setDuration(300)
                    anim.setStartValue(sl.value())
                    anim.setEndValue(target)
                    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                    anim.start()
                    _sa[sl] = anim
                QTimer.singleShot(320, lambda: _flag.__setitem__(0, False))

            _preset_seg.currentItemChanged.connect(_on_preset_changed)

            def _make_slider_cb(_seg=_preset_seg, _flag=_applying_preset):
                def _cb(value):
                    _ = value
                    if _flag[0]:
                        return
                    if _seg.currentRouteKey() != "custom":
                        _seg.setCurrentItem("custom")

                return _cb

            _slider_cb = _make_slider_cb()
            for sl in sliders:
                sl.valueChanged.connect(_slider_cb)
