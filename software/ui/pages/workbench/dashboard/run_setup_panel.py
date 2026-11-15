from __future__ import annotations

from typing import Any, Optional, cast

from PySide6.QtCore import QSignalBlocker, QTime, Qt, Signal
from PySide6.QtGui import QColor, QDoubleValidator
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ExpandGroupSettingCard,
    FluentIcon,
    LineEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    ScrollArea,
    SettingCard,
    SettingCardGroup,
    SubtitleLabel,
    SwitchButton,
    TransparentToolButton,
    themeColor,
)
from qfluentwidgets.components.widgets.switch_button import IndicatorPosition
from software.core.engine.constants import HTTP_MAX_THREADS
from software.core.config.schema import RuntimeConfig
from software.providers.common import detect_survey_provider, supports_answer_datetime_window
from surveycore.core.questions.utils import OPTION_FILL_AI_TOKEN
from software.ui.helpers.proxy_access import (
    format_quota_value,
    has_authenticated_session,
    has_unknown_local_quota,
    is_quota_exhausted,
)
from software.ui.pages.workbench.runtime_panel.ai import RuntimeAISection
from software.ui.pages.workbench.runtime_panel.cards import (
    AnswerDateTimeWindowSettingCard,
    DurationTimePicker,
)
from software.ui.pages.workbench.runtime_panel.proxy_source import normalize_proxy_source
from software.ui.pages.workbench.runtime_panel.random_ip_card import RandomIPSettingCard
from software.ui.widgets.no_wheel import NoWheelSpinBox
from software.ui.widgets.ratio_slider import RatioSlider
from software.ui.widgets.setting_cards import (
    SliderSettingCard,
    set_widget_enabled_with_opacity,
)


class DashboardRunSetupPanel(QWidget):
    backRequested = Signal()
    startRequested = Signal()

    def __init__(self, dashboard: Any, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.dashboard = dashboard
        self.ai_section: RuntimeAISection
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self._build_ui()
        self._bind_events()
        self.apply_config(self.dashboard.workbench_state.snapshot())
        ai_config = RuntimeConfig()
        self.ai_section.update_config(ai_config)
        self.dashboard.workbench_state.update_settings(
            ai_mode=ai_config.ai_mode,
            ai_config_mode=ai_config.ai_config_mode,
            ai_provider=ai_config.ai_provider,
            ai_api_key=ai_config.ai_api_key,
            ai_base_url=ai_config.ai_base_url,
            ai_api_protocol=ai_config.ai_api_protocol,
            ai_model=ai_config.ai_model,
            ai_system_prompt=ai_config.ai_system_prompt,
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 16)
        root.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)

        self.back_btn = TransparentToolButton(FluentIcon.RETURN, self)
        self.back_btn.setFixedSize(34, 34)
        self.back_btn.setToolTip("返回修改题目配置")
        header_row.addWidget(self.back_btn)

        self.title_label = SubtitleLabel("运行设置", self)
        header_row.addWidget(self.title_label)

        self.summary_label = CaptionLabel("", self)
        header_row.addWidget(self.summary_label)
        header_row.addStretch(1)
        root.addLayout(header_row)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content_host = QWidget(scroll)
        content_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        content_host.setAutoFillBackground(False)
        scroll.setWidget(content_host)
        scroll.enableTransparentBackground()
        scroll.viewport().setAutoFillBackground(False)
        scroll.viewport().setStyleSheet("background: transparent;")

        host_layout = QHBoxLayout(content_host)
        host_layout.setContentsMargins(0, 4, 0, 12)
        host_layout.addStretch(1)

        container = QWidget(content_host)
        container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        container.setAutoFillBackground(False)
        container.setMaximumWidth(860)
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(18)

        scale_group = SettingCardGroup("执行与节奏", container)
        self.target_card = SettingCard(
            FluentIcon.DOCUMENT,
            "目标份数",
            "设置本次要提交的问卷数量",
            scale_group,
        )
        self.target_spin = NoWheelSpinBox(self.target_card)
        self.target_spin.setRange(1, 9999)
        self.target_spin.setValue(10)
        self.target_spin.setMinimumWidth(140)
        self.target_card.hBoxLayout.addWidget(self.target_spin, 0, Qt.AlignmentFlag.AlignRight)
        self.target_card.hBoxLayout.addSpacing(16)
        self.thread_card = SliderSettingCard(
            FluentIcon.APPLICATION,
            "并发数",
            "控制同时运行的独立 HTTP 会话数量",
            min_val=1,
            max_val=HTTP_MAX_THREADS,
            default=2,
            parent=scale_group,
        )
        scale_group.addSettingCard(self.target_card)
        scale_group.addSettingCard(self.thread_card)

        self.timing_card = ExpandGroupSettingCard(
            FluentIcon.HISTORY,
            "时间与节奏",
            "配置提交间隔与单份问卷作答时长",
            scale_group,
        )
        timing_detail = QWidget(self.timing_card)
        timing_layout = QVBoxLayout(timing_detail)
        timing_layout.setContentsMargins(48, 12, 48, 14)
        timing_layout.setSpacing(12)

        interval_row = QHBoxLayout()
        interval_row.setContentsMargins(0, 0, 0, 0)
        interval_row.setSpacing(10)
        interval_label = BodyLabel("提交间隔", timing_detail)
        interval_label.setFixedWidth(72)
        self.interval_start_picker = DurationTimePicker(timing_detail, max_seconds=300)
        self.interval_end_picker = DurationTimePicker(timing_detail, max_seconds=300)
        self.interval_start_picker.setFixedWidth(200)
        self.interval_end_picker.setFixedWidth(200)
        interval_row.addWidget(interval_label)
        interval_row.addStretch(1)
        interval_row.addWidget(self.interval_start_picker)
        interval_row.addWidget(CaptionLabel("至", timing_detail))
        interval_row.addWidget(self.interval_end_picker)
        timing_layout.addLayout(interval_row)

        duration_row = QHBoxLayout()
        duration_row.setContentsMargins(0, 0, 0, 0)
        duration_row.setSpacing(10)
        duration_label = BodyLabel("作答时长", timing_detail)
        duration_label.setFixedWidth(72)
        self.duration_start_picker = DurationTimePicker(timing_detail, max_seconds=86399)
        self.duration_end_picker = DurationTimePicker(timing_detail, max_seconds=86399)
        self.duration_start_picker.setFixedWidth(200)
        self.duration_end_picker.setFixedWidth(200)
        duration_row.addWidget(duration_label)
        duration_row.addStretch(1)
        duration_row.addWidget(self.duration_start_picker)
        duration_row.addWidget(CaptionLabel("至", timing_detail))
        duration_row.addWidget(self.duration_end_picker)
        timing_layout.addLayout(duration_row)

        self.timing_card.addGroupWidget(timing_detail)
        self.timing_card.setExpand(False)
        scale_group.addSettingCard(self.timing_card)

        self.answer_datetime_card = AnswerDateTimeWindowSettingCard(
            FluentIcon.DATE_TIME,
            "提交时间",
            "设置见数的提交日期时间范围",
            max_seconds=30 * 60,
            parent=scale_group,
        )
        self.answer_datetime_card.setVisible(False)
        scale_group.addSettingCard(self.answer_datetime_card)

        container_layout.addWidget(scale_group)

        proxy_group = SettingCardGroup("随机 IP 与代理", container)

        self.random_ip_card = RandomIPSettingCard(parent=proxy_group)
        self.random_ip_switch = self.random_ip_card.switchButton

        quota_detail = QWidget(self.random_ip_card)
        quota_layout = QVBoxLayout(quota_detail)
        quota_layout.setContentsMargins(48, 12, 48, 12)
        quota_layout.setSpacing(8)
        quota_header = QHBoxLayout()
        quota_header.setContentsMargins(0, 0, 0, 0)
        quota_header.setSpacing(10)
        quota_header.addWidget(BodyLabel("剩余额度", quota_detail))
        quota_header.addStretch(1)
        self.quota_ratio_label = CaptionLabel("--/--", quota_detail)
        quota_header.addWidget(self.quota_ratio_label)
        self.get_quota_btn = PushButton(FluentIcon.SHOPPING_CART, "获取额度", quota_detail)
        quota_header.addWidget(self.get_quota_btn)
        quota_layout.addLayout(quota_header)
        self.quota_progress_bar = ProgressBar(quota_detail)
        self.quota_progress_bar.setRange(0, 100)
        self.quota_progress_bar.setValue(0)
        quota_layout.addWidget(self.quota_progress_bar)
        self.random_ip_card.addGroupWidget(quota_detail)
        proxy_group.addSettingCard(self.random_ip_card)
        container_layout.addWidget(proxy_group)

        quality_group = SettingCardGroup("伪装与质量", container)
        self.ua_card = ExpandGroupSettingCard(
            FluentIcon.ROBOT,
            "随机 UA",
            "模拟微信、手机浏览器或桌面浏览器访问环境",
            quality_group,
        )
        self.ua_switch = SwitchButton(self.ua_card, IndicatorPosition.RIGHT)
        self.ua_switch.setOnText("开")
        self.ua_switch.setOffText("关")
        self.ua_card.addWidget(self.ua_switch)

        self.ua_container = QWidget(self.ua_card)
        ua_layout = QVBoxLayout(self.ua_container)
        ua_layout.setContentsMargins(48, 12, 48, 12)
        ua_layout.setSpacing(12)
        ua_hint = CaptionLabel("配置不同设备类型的访问占比", self.ua_container)
        ua_layout.addWidget(ua_hint)
        self.ua_ratio_slider = RatioSlider(
            labels={
                "wechat": "微信访问占比",
                "mobile": "手机访问占比",
                "pc": "链接访问占比",
            },
            parent=self.ua_container,
        )
        ua_layout.addWidget(self.ua_ratio_slider)
        self.ua_card.addGroupWidget(self.ua_container)
        self.ua_card.setExpand(True)
        quality_group.addSettingCard(self.ua_card)

        self.reliability_card = ExpandGroupSettingCard(
            FluentIcon.CHECKBOX,
            "提升问卷信度",
            "通过隐含态度模型调控量表与单选的一致性",
            quality_group,
        )
        self.reliability_switch = SwitchButton(self.reliability_card, IndicatorPosition.RIGHT)
        self.reliability_switch.setOnText("开")
        self.reliability_switch.setOffText("关")
        self.reliability_card.addWidget(self.reliability_switch)

        self.reliability_container = QWidget(self.reliability_card)
        reliability_layout = QHBoxLayout(self.reliability_container)
        reliability_layout.setContentsMargins(48, 12, 48, 12)
        reliability_layout.setSpacing(10)
        reliability_layout.addWidget(BodyLabel("目标 α 系数", self.reliability_container))
        reliability_layout.addStretch(1)
        self.alpha_edit = LineEdit(self.reliability_container)
        self.alpha_edit.setFixedWidth(100)
        self.alpha_edit.setPlaceholderText("0.85")
        validator = QDoubleValidator(0.50, 0.99, 2, self.alpha_edit)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.alpha_edit.setValidator(validator)
        reliability_layout.addWidget(self.alpha_edit)
        self.reliability_card.addGroupWidget(self.reliability_container)
        self.reliability_card.setExpand(True)
        quality_group.addSettingCard(self.reliability_card)

        container_layout.addWidget(quality_group)

        self.ai_section_container = QWidget(container)
        self.ai_section_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.ai_section_container.setAutoFillBackground(False)
        ai_container_layout = QVBoxLayout(self.ai_section_container)
        ai_container_layout.setContentsMargins(0, 0, 0, 0)
        ai_container_layout.setSpacing(0)
        self.ai_section = RuntimeAISection(
            self.ai_section_container,
            self.dashboard,
            ai_settings=self.dashboard.controller.ai_settings,
        )
        ai_container_layout.addWidget(self.ai_section.group)
        self.ai_section_container.setVisible(False)
        container_layout.addWidget(self.ai_section_container)

        container_layout.addStretch(1)
        host_layout.addWidget(container, 8)
        host_layout.addStretch(1)

        root.addWidget(scroll, 1)

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 4, 0, 0)
        footer_row.setSpacing(12)
        footer_row.addStretch(1)
        self.start_btn = PrimaryPushButton(FluentIcon.PLAY, "开始执行", self)
        self.start_btn.setFixedHeight(38)
        footer_row.addWidget(self.start_btn)
        root.addLayout(footer_row)

    def _bind_events(self) -> None:
        self.back_btn.clicked.connect(self.backRequested.emit)
        self.start_btn.clicked.connect(self.startRequested.emit)

        self.get_quota_btn.clicked.connect(self._on_get_quota_clicked)
        self.random_ip_switch.checkedChanged.connect(self._on_random_ip_toggled)
        self.random_ip_card.proxyCombo.currentIndexChanged.connect(self._on_proxy_source_changed)
        self.random_ip_card.provinceCombo.currentIndexChanged.connect(self._on_area_changed)
        self.random_ip_card.cityCombo.currentIndexChanged.connect(self._on_area_changed)
        self.random_ip_card.customApiEdit.editingFinished.connect(self._on_custom_api_finished)

        self.target_spin.valueChanged.connect(self._on_target_changed)
        self.thread_card.slider.valueChanged.connect(self._on_threads_changed)
        self.interval_start_picker.timeChanged.connect(self._on_interval_changed)
        self.interval_end_picker.timeChanged.connect(self._on_interval_changed)
        self.duration_start_picker.timeChanged.connect(self._on_duration_changed)
        self.duration_end_picker.timeChanged.connect(self._on_duration_changed)
        self.answer_datetime_card.datetimeWindowChanged.connect(self._on_answer_datetime_changed)

        self.ua_switch.checkedChanged.connect(self._on_ua_switch_changed)
        self.ua_ratio_slider.valueChanged.connect(self._on_ua_ratio_changed)
        self.reliability_switch.checkedChanged.connect(self._on_reliability_toggled)
        self.alpha_edit.editingFinished.connect(self._on_alpha_finished)
        self.ai_section.configurationChanged.connect(
            lambda changes: self.dashboard.workbench_state.update_settings(**changes)
        )

    def set_survey_summary(self, title: str, question_count: int) -> None:
        _ = title
        self.summary_label.setText(f"共 {max(0, int(question_count or 0))} 题")

    def _detect_current_provider(self) -> str:
        url_edit = getattr(self.dashboard, "url_edit", None)
        if url_edit is not None and hasattr(url_edit, "text"):
            url_text = str(url_edit.text() or "").strip()
            if url_text:
                return str(detect_survey_provider(url_text) or "")
        controller = getattr(self.dashboard, "controller", None)
        if controller is not None and hasattr(controller, "get_survey_snapshot"):
            provider = str(controller.get_survey_snapshot().get("survey_provider") or "").strip()
            if provider:
                return provider
        return ""

    def _has_ai_fill_entries(self) -> bool:
        state = getattr(self.dashboard, "workbench_state", None)
        if state is None or not hasattr(state, "get_entries"):
            return False
        for entry in state.get_entries() or []:
            if bool(getattr(entry, "ai_enabled", False)):
                return True
            if any(
                bool(flag) for flag in (getattr(entry, "multi_text_blank_ai_flags", None) or ())
            ):
                return True
            if any(
                str(value or "").strip() == OPTION_FILL_AI_TOKEN
                for value in (getattr(entry, "option_fill_texts", None) or ())
            ):
                return True
        return False

    def _refresh_conditional_sections(self) -> None:
        provider = self._detect_current_provider()
        self.answer_datetime_card.set_provider(provider)
        self.answer_datetime_card.setVisible(supports_answer_datetime_window(provider))

        has_ai = self._has_ai_fill_entries()
        self.ai_section_container.setVisible(has_ai)

    def apply_runtime_snapshot(self, snapshot: dict[str, Any]) -> None:
        settings = dict((snapshot or {}).get("settings") or {})
        if "random_ip_enabled" in settings:
            enabled = bool(settings["random_ip_enabled"])
            with QSignalBlocker(self.random_ip_switch):
                self.random_ip_switch.setChecked(enabled)
            self.random_ip_card._sync_ip_enabled(enabled)
        running = bool(
            (snapshot or {}).get("running")
            or (snapshot or {}).get("initialization", {}).get("active")
        )
        self.thread_card.setEnabled(not running)
        self._refresh_quota_subtitle()
        self._refresh_conditional_sections()

    def render_runtime_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.apply_runtime_snapshot(snapshot)

    @staticmethod
    def _set_duration_range(start_picker, end_picker, value) -> None:
        low = max(0, int(value[0] if len(value) else 0))
        high = max(low, int(value[1] if len(value) > 1 else low))
        with QSignalBlocker(start_picker), QSignalBlocker(end_picker):
            start_picker.setDurationSeconds(low)
            end_picker.setDurationSeconds(high)

    def _refresh_quota_subtitle(self) -> None:
        quota_reader = getattr(self.dashboard.controller, "get_random_ip_quota_snapshot", None)
        snapshot = quota_reader() if callable(quota_reader) else {}
        count = snapshot.get("used_quota")
        limit = snapshot.get("total_quota")
        if count is None or limit is None:
            self.quota_ratio_label.setText("--/--")
            self.quota_progress_bar.setPaused(True)
            self.quota_progress_bar.setError(False)
            self.quota_progress_bar.setValue(0)
            return

        authenticated = bool(snapshot.get("authenticated")) and has_authenticated_session()
        if not authenticated:
            self.quota_ratio_label.setText("--/--")
            self.quota_progress_bar.setPaused(True)
            self.quota_progress_bar.setError(False)
            self.quota_progress_bar.setValue(0)
            return

        if has_unknown_local_quota(snapshot):
            self.quota_ratio_label.setText("待校验")
            self.quota_progress_bar.setPaused(True)
            self.quota_progress_bar.setError(False)
            self.quota_progress_bar.setValue(0)
            return

        used = max(0.0, float(count or 0.0))
        total = max(0.0, float(limit or 0.0))
        remaining_snapshot = max(0.0, float(snapshot.get("remaining_quota") or 0.0))
        remaining = min(total, remaining_snapshot) if total > 0 else remaining_snapshot
        quota_exhausted = is_quota_exhausted(
            {
                "authenticated": authenticated,
                "user_id": int(snapshot.get("user_id") or 0),
                "used_quota": used,
                "total_quota": total,
                "remaining_quota": remaining,
            }
        )
        percent = 0 if total <= 0 else max(0, min(int(round((remaining / total) * 100)), 100))
        ratio_text = f"{format_quota_value(remaining)} / {format_quota_value(total)}"
        self.quota_ratio_label.setText(f"{ratio_text}（{percent}%）")
        self.quota_progress_bar.setValue(percent)
        if quota_exhausted or percent <= 5:
            self.quota_progress_bar.setCustomBarColor(QColor("#C42B1C"), QColor("#FF99A4"))
            self.quota_progress_bar.setPaused(False)
            self.quota_progress_bar.setError(True)
        elif percent <= 20:
            self.quota_progress_bar.setCustomBarColor(QColor("#C77900"), QColor("#FFB347"))
            self.quota_progress_bar.setPaused(False)
            self.quota_progress_bar.setError(False)
        else:
            accent = themeColor()
            self.quota_progress_bar.setCustomBarColor(accent, accent)
            self.quota_progress_bar.setPaused(False)
            self.quota_progress_bar.setError(False)

    def _on_get_quota_clicked(self) -> None:
        future = cast(Any, self.window())._open_quota_redeem_dialog_async()
        future.add_done_callback(lambda _future: self._refresh_quota_subtitle())

    def _on_random_ip_toggled(self, checked: bool) -> None:
        if not self.dashboard.controller.request_toggle_random_ip(bool(checked)):
            self.apply_runtime_snapshot(self.dashboard.controller.get_runtime_snapshot())

    def _on_proxy_source_changed(self) -> None:
        source = self.random_ip_card._get_selected_source()
        self.dashboard.workbench_state.update_settings(
            proxy_source=source,
            proxy_area_code=self.random_ip_card.get_area_code(),
            custom_proxy_api=self.random_ip_card.customApiEdit.text().strip(),
        )

    def _on_area_changed(self) -> None:
        self.dashboard.workbench_state.update_settings(
            proxy_area_code=self.random_ip_card.get_area_code(),
        )

    def _on_custom_api_finished(self) -> None:
        self.dashboard.workbench_state.update_settings(
            custom_proxy_api=self.random_ip_card.customApiEdit.text().strip(),
        )

    def _on_target_changed(self, value: int) -> None:
        self.dashboard.workbench_state.update_settings(target=int(value))

    def _on_threads_changed(self, value: int) -> None:
        self.dashboard.workbench_state.update_settings(threads=int(value))

    def _on_interval_changed(self, _time: QTime) -> None:
        low = self.interval_start_picker.getDurationSeconds()
        high = self.interval_end_picker.getDurationSeconds()
        if high < low:
            high = low
            with QSignalBlocker(self.interval_end_picker):
                self.interval_end_picker.setDurationSeconds(high)
        self.dashboard.workbench_state.update_settings(submit_interval=(low, high))

    def _on_duration_changed(self, _time: QTime) -> None:
        low = self.duration_start_picker.getDurationSeconds()
        high = self.duration_end_picker.getDurationSeconds()
        if high < low:
            high = low
            with QSignalBlocker(self.duration_end_picker):
                self.duration_end_picker.setDurationSeconds(high)
        self.dashboard.workbench_state.update_settings(answer_duration=(low, high))

    def _on_answer_datetime_changed(self, window: tuple[str, str]) -> None:
        self.dashboard.workbench_state.update_settings(answer_datetime_window=tuple(window))

    def _on_ua_switch_changed(self, checked: bool) -> None:
        set_widget_enabled_with_opacity(self.ua_container, bool(checked))
        self.dashboard.workbench_state.update_settings(random_ua_enabled=bool(checked))

    def _on_ua_ratio_changed(self, ratios: dict[str, int]) -> None:
        self.dashboard.workbench_state.update_settings(random_ua_ratios=dict(ratios))

    def _on_reliability_toggled(self, checked: bool) -> None:
        set_widget_enabled_with_opacity(self.reliability_container, bool(checked))
        self.dashboard.workbench_state.update_settings(reliability_mode_enabled=bool(checked))

    def _current_alpha_value(self) -> float:
        try:
            val = float(self.alpha_edit.text().strip() or "0.85")
        except ValueError:
            val = 0.85
        return max(0.50, min(0.99, val))

    def _on_alpha_finished(self) -> None:
        alpha = self._current_alpha_value()
        self.alpha_edit.setText(f"{alpha:.2f}")
        self.dashboard.workbench_state.update_settings(psycho_target_alpha=alpha)

    def selected_proxy_source(self) -> str:
        return normalize_proxy_source(
            str(self.random_ip_card.proxyCombo.currentData() or "default")
        )

    def set_proxy_source(
        self,
        source: str,
        custom_api_url: str | None = None,
        *,
        emit_state: bool = True,
        show_tip: bool = True,
    ) -> str:
        normalized = normalize_proxy_source(source)
        index = self.random_ip_card.proxyCombo.findData(normalized)
        if index < 0:
            index = self.random_ip_card.proxyCombo.findData("default")
            normalized = "default"
        with QSignalBlocker(self.random_ip_card.proxyCombo):
            self.random_ip_card.proxyCombo.setCurrentIndex(index)
        if custom_api_url is not None:
            with QSignalBlocker(self.random_ip_card.customApiEdit):
                self.random_ip_card.customApiEdit.setText(str(custom_api_url or ""))
        self.random_ip_card._on_source_changed()
        if emit_state:
            self.dashboard.workbench_state.update_settings(
                proxy_source=normalized,
                custom_proxy_api=self.random_ip_card.customApiEdit.text().strip(),
                proxy_area_code=self.random_ip_card.get_area_code(),
            )
        return normalized

    def set_custom_proxy_api(self, api_url: str) -> None:
        value = str(api_url or "").strip()
        with QSignalBlocker(self.random_ip_card.customApiEdit):
            self.random_ip_card.customApiEdit.setText(value)
        self.dashboard.workbench_state.update_settings(custom_proxy_api=value)

    def apply_config(self, cfg: Any) -> None:
        with QSignalBlocker(self.target_spin):
            self.target_spin.setValue(max(1, int(cfg.target or 1)))
        with QSignalBlocker(self.thread_card.slider):
            self.thread_card.slider.setValue(max(1, min(HTTP_MAX_THREADS, int(cfg.threads or 1))))
        with QSignalBlocker(self.random_ip_switch):
            self.random_ip_switch.setChecked(bool(cfg.random_ip_enabled))
        self.random_ip_card._sync_ip_enabled(bool(cfg.random_ip_enabled))
        with QSignalBlocker(self.ua_switch):
            self.ua_switch.setChecked(bool(cfg.random_ua_enabled))
        with QSignalBlocker(self.ua_ratio_slider):
            self.ua_ratio_slider.setValues(
                dict(cfg.random_ua_ratios or {"wechat": 33, "mobile": 33, "pc": 34})
            )
        with QSignalBlocker(self.reliability_switch):
            self.reliability_switch.setChecked(bool(cfg.reliability_mode_enabled))
        with QSignalBlocker(self.alpha_edit):
            self.alpha_edit.setText(f"{float(cfg.psycho_target_alpha or 0.85):.2f}")
        set_widget_enabled_with_opacity(self.ua_container, self.ua_switch.isChecked())
        set_widget_enabled_with_opacity(
            self.reliability_container, self.reliability_switch.isChecked()
        )
        self._set_duration_range(
            self.interval_start_picker, self.interval_end_picker, cfg.submit_interval
        )
        self._set_duration_range(
            self.duration_start_picker, self.duration_end_picker, cfg.answer_duration
        )
        with QSignalBlocker(self.answer_datetime_card):
            self.answer_datetime_card.setDateTimeWindow(
                tuple(cfg.answer_datetime_window or ("", ""))
            )
        source = normalize_proxy_source(str(cfg.proxy_source or "default"))
        self.set_proxy_source(source, custom_api_url=cfg.custom_proxy_api, emit_state=False)
        self.random_ip_card.set_area_code(cfg.proxy_area_code)
        self.ai_section.apply_config(cfg)
        self._refresh_quota_subtitle()
        self._refresh_conditional_sections()

    def get_reliability_mode_enabled(self) -> bool:
        return bool(self.reliability_switch.isChecked())

    def focus_answer_duration_setting(self) -> None:
        self.duration_start_picker.setFocus()
