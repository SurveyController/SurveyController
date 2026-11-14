from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import QThread, QTime, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QDoubleValidator
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    ExpandGroupSettingCard,
    FluentIcon,
    InfoBarPosition,
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
from software.providers.common import detect_survey_provider, supports_answer_datetime_window
from software.ui.helpers.message_bar import show_message_bar
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
from software.ui.pages.workbench.runtime_panel.proxy_source import (
    PROXY_SOURCE_BENEFIT,
    PROXY_SOURCE_CUSTOM,
    PROXY_SOURCE_DEFAULT,
    normalize_proxy_source,
)
from software.ui.pages.workbench.runtime_panel.random_ip_card import (
    SearchableComboBox,
    _ProxyApiTestWorker,
)
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
        self._syncing = False
        self._test_thread: Optional[QThread] = None
        self._test_worker: Optional[_ProxyApiTestWorker] = None
        self.ai_section: Optional[RuntimeAISection] = None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self._build_ui()
        self._bind_events()
        self._bind_controller_signals()
        self.sync_from_runtime()

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

        self.random_ip_card = ExpandGroupSettingCard(
            FluentIcon.GLOBE,
            "随机 IP",
            "开启后可模拟不同地区访问并绕过智能验证",
            proxy_group,
        )
        self.random_ip_switch = SwitchButton(self.random_ip_card, IndicatorPosition.RIGHT)
        self.random_ip_switch.setOnText("开")
        self.random_ip_switch.setOffText("关")
        self.random_ip_card.addWidget(self.random_ip_switch)

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
        self.random_ip_card.setExpand(True)
        proxy_group.addSettingCard(self.random_ip_card)

        self.proxy_source_card = ExpandGroupSettingCard(
            FluentIcon.VPN,
            "代理源与地区",
            "选择代理节点、出口地区或自定义代理 API",
            proxy_group,
        )
        self.proxy_combo = ComboBox(self.proxy_source_card)
        self.proxy_combo.addItem("默认", userData=PROXY_SOURCE_DEFAULT)
        self.proxy_combo.addItem("限时福利", userData=PROXY_SOURCE_BENEFIT)
        self.proxy_combo.addItem("自定义", userData=PROXY_SOURCE_CUSTOM)
        self.proxy_combo.setMinimumWidth(160)
        self.proxy_source_card.addWidget(self.proxy_combo)

        proxy_detail = QWidget(self.proxy_source_card)
        proxy_detail_layout = QVBoxLayout(proxy_detail)
        proxy_detail_layout.setContentsMargins(48, 12, 48, 12)
        proxy_detail_layout.setSpacing(10)

        self.benefit_hint_label = CaptionLabel(
            "限时福利源仅支持少部分特定城市，如有更高需求请切换至默认或自定义代理源",
            proxy_detail,
        )
        self.benefit_hint_label.setWordWrap(True)
        self.benefit_hint_label.setStyleSheet("color: #D46B08;")
        self.benefit_hint_label.hide()
        proxy_detail_layout.addWidget(self.benefit_hint_label)

        self.area_row = QWidget(proxy_detail)
        area_layout = QHBoxLayout(self.area_row)
        area_layout.setContentsMargins(0, 0, 0, 0)
        area_layout.setSpacing(10)
        area_layout.addWidget(BodyLabel("出口地区", self.area_row))
        area_layout.addStretch(1)
        self.province_combo = SearchableComboBox(self.area_row)
        self.province_combo.setMinimumWidth(130)
        self.province_combo.setMaximumWidth(210)
        self.city_combo = SearchableComboBox(self.area_row)
        self.city_combo.setMinimumWidth(130)
        self.city_combo.setMaximumWidth(210)
        area_layout.addWidget(self.province_combo)
        area_layout.addWidget(self.city_combo)
        proxy_detail_layout.addWidget(self.area_row)

        self.custom_api_row = QWidget(proxy_detail)
        api_layout = QHBoxLayout(self.custom_api_row)
        api_layout.setContentsMargins(0, 0, 0, 0)
        api_layout.setSpacing(10)
        api_layout.addWidget(BodyLabel("API 地址", self.custom_api_row))
        self.custom_api_edit = LineEdit(self.custom_api_row)
        self.custom_api_edit.setPlaceholderText("请输入代理 API 地址（仅支持 JSON 返回格式）")
        api_layout.addWidget(self.custom_api_edit, 1)
        self.test_api_btn = PushButton("检测", self.custom_api_row)
        api_layout.addWidget(self.test_api_btn)
        proxy_detail_layout.addWidget(self.custom_api_row)

        self.proxy_source_card.addGroupWidget(proxy_detail)
        self.proxy_source_card.setExpand(True)
        proxy_group.addSettingCard(self.proxy_source_card)
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
        ua_hint = CaptionLabel(
            "配置不同设备类型的访问占比，三个滑块占比总和必须为 100%", self.ua_container
        )
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
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        ai_settings = getattr(getattr(runtime_page, "ai_section", None), "_ai_settings", None)
        if ai_settings is not None:
            self.ai_section = RuntimeAISection(
                self.ai_section_container,
                self.dashboard,
                ai_settings=ai_settings,
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
        self.proxy_combo.currentIndexChanged.connect(self._on_proxy_source_changed)
        self.province_combo.currentIndexChanged.connect(self._on_province_changed)
        self.city_combo.currentIndexChanged.connect(self._on_city_changed)
        self.custom_api_edit.editingFinished.connect(self._on_custom_api_finished)
        self.test_api_btn.clicked.connect(self._on_test_api_clicked)

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

        runtime_page = getattr(self.dashboard, "runtime_page", None)
        if runtime_page is not None:
            random_ip_card = getattr(runtime_page, "random_ip_card", None)
            if random_ip_card is not None and hasattr(random_ip_card, "areaOptionsUpdated"):
                random_ip_card.areaOptionsUpdated.connect(self._sync_area_from_runtime)

    def _bind_controller_signals(self) -> None:
        controller = getattr(self.dashboard, "controller", None)
        if controller is None:
            return
        signal = getattr(controller, "runtimeSnapshotChanged", None)
        if signal is not None and hasattr(signal, "connect"):
            signal.connect(self._on_runtime_snapshot_changed)

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
            if bool(getattr(entry, "ai_fill_enabled", False)):
                return True
            if any(bool(flag) for flag in (getattr(entry, "ai_blanks", None) or ())):
                return True
        return False

    def _refresh_conditional_sections(self) -> None:
        provider = self._detect_current_provider()
        self.answer_datetime_card.set_provider(provider)
        self.answer_datetime_card.setVisible(supports_answer_datetime_window(provider))

        has_ai = self._has_ai_fill_entries()
        self.ai_section_container.setVisible(has_ai)
        if has_ai and self.ai_section is not None:
            runtime_page = getattr(self.dashboard, "runtime_page", None)
            if runtime_page is not None:
                from software.core.config.schema import RuntimeConfig

                cfg = RuntimeConfig()
                cfg.ai_provider = (
                    runtime_page.ai_section.ai_provider_combo.currentData() or "deepseek"
                )
                cfg.ai_api_key = runtime_page.ai_section.ai_apikey_edit.text()
                cfg.ai_base_url = runtime_page.ai_section.ai_baseurl_edit.text()
                cfg.ai_model = runtime_page.ai_section._get_current_model_value()
                cfg.ai_system_prompt = runtime_page.ai_section._ai_system_prompt
                cfg.ai_config_mode = "override"
                self.ai_section._apply_ai_config(cfg)

    def sync_from_runtime(self) -> None:
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        if runtime_page is None:
            return
        self._syncing = True
        try:
            self.random_ip_switch.setChecked(runtime_page.random_ip_card.switchButton.isChecked())
            source = runtime_page.selected_proxy_source()
            idx = self.proxy_combo.findData(source)
            if idx >= 0:
                self.proxy_combo.setCurrentIndex(idx)
            self.custom_api_edit.setText(runtime_page.random_ip_card.customApiEdit.text())
            self._sync_area_combos_from_runtime(runtime_page.random_ip_card)
            self._update_proxy_detail_visibility(source)

            self.target_spin.setValue(runtime_page.target_card.spinBox.value())
            self.thread_card.slider.setRange(
                runtime_page.thread_card.slider.slider.minimum(),
                runtime_page.thread_card.slider.slider.maximum(),
            )
            self.thread_card.slider.setValue(runtime_page.thread_card.slider.value())

            interval_range = runtime_page.interval_card.getRange()
            self.interval_start_picker.setDurationSeconds(interval_range[0])
            self.interval_end_picker.setDurationSeconds(interval_range[1])

            duration_range = runtime_page.answer_duration_card.getRange()
            self.duration_start_picker.setDurationSeconds(duration_range[0])
            self.duration_end_picker.setDurationSeconds(duration_range[1])

            if hasattr(runtime_page, "answer_card"):
                self.answer_datetime_card.setDateTimeWindow(
                    runtime_page.answer_card.getDateTimeWindow()
                )

            ua_enabled = runtime_page.random_ua_card.isChecked()
            self.ua_switch.setChecked(ua_enabled)
            set_widget_enabled_with_opacity(self.ua_container, ua_enabled)
            ratios = runtime_page.random_ua_card.getRatios()
            self.ua_ratio_slider.setValues(ratios)

            reliability_enabled = runtime_page.reliability_card.isChecked()
            alpha = runtime_page.reliability_card.get_alpha()
            self.reliability_switch.setChecked(reliability_enabled)
            set_widget_enabled_with_opacity(self.reliability_container, reliability_enabled)
            self.alpha_edit.setText(f"{alpha:.2f}")

            self._refresh_quota_subtitle()
            self._refresh_conditional_sections()
        finally:
            self._syncing = False

    def _sync_area_from_runtime(self) -> None:
        if self._syncing:
            return
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        if runtime_page is None:
            return
        self._syncing = True
        try:
            self._sync_area_combos_from_runtime(runtime_page.random_ip_card)
        finally:
            self._syncing = False

    def _sync_area_combos_from_runtime(self, random_ip_card: Any) -> None:
        src_prov = random_ip_card.provinceCombo
        src_city = random_ip_card.cityCombo
        self.province_combo.clear()
        for i in range(src_prov.count()):
            self.province_combo.addItem(src_prov.itemText(i), userData=src_prov.itemData(i))
        if src_prov.count() > 0:
            self.province_combo.setCurrentIndex(max(0, src_prov.currentIndex()))

        self.city_combo.clear()
        for i in range(src_city.count()):
            self.city_combo.addItem(src_city.itemText(i), userData=src_city.itemData(i))
        self.city_combo.setEnabled(src_city.isEnabled())
        if src_city.count() > 0:
            self.city_combo.setCurrentIndex(max(0, src_city.currentIndex()))

    def _on_runtime_snapshot_changed(self, _snapshot: dict) -> None:
        self._refresh_quota_subtitle()

    def _refresh_quota_subtitle(self) -> None:
        controller = getattr(self.dashboard, "controller", None)
        if controller is None or not hasattr(controller, "get_random_ip_quota_snapshot"):
            self.quota_ratio_label.setText("--/--")
            self.quota_progress_bar.setPaused(True)
            self.quota_progress_bar.setError(False)
            self.quota_progress_bar.setValue(0)
            return
        snapshot = controller.get_random_ip_quota_snapshot() or {}
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

    def _update_proxy_detail_visibility(self, source: str) -> None:
        normalized = normalize_proxy_source(source)
        is_benefit = normalized == PROXY_SOURCE_BENEFIT
        is_custom = normalized == PROXY_SOURCE_CUSTOM
        self.benefit_hint_label.setVisible(is_benefit)
        self.area_row.setVisible(not is_custom)
        self.custom_api_row.setVisible(is_custom)
        if is_benefit or is_custom:
            self.proxy_source_card.setExpand(True)
        QTimer.singleShot(0, self.proxy_source_card._adjustViewSize)

    def _on_get_quota_clicked(self) -> None:
        for target in (self.window(), self.dashboard):
            opener = getattr(target, "_open_quota_redeem_dialog", None)
            if callable(opener):
                opener()
                self._refresh_quota_subtitle()
                return

    def _on_random_ip_toggled(self, checked: bool) -> None:
        if self._syncing:
            return
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        controller = getattr(self.dashboard, "controller", None)
        if controller is not None and hasattr(controller, "request_toggle_random_ip"):
            accepted = controller.request_toggle_random_ip(bool(checked))
            if not accepted:
                fallback = bool(
                    controller.get_runtime_snapshot()
                    .get("settings", {})
                    .get("random_ip_enabled", False)
                )
                self._syncing = True
                self.random_ip_switch.setChecked(fallback)
                self._syncing = False
                return
        if runtime_page is not None:
            runtime_page.random_ip_card.switchButton.setChecked(bool(checked))

    def _on_proxy_source_changed(self) -> None:
        if self._syncing:
            return
        source = normalize_proxy_source(str(self.proxy_combo.currentData() or PROXY_SOURCE_DEFAULT))
        self._update_proxy_detail_visibility(source)
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        if runtime_page is not None:
            runtime_page.set_proxy_source(
                source,
                custom_api_url=self.custom_api_edit.text().strip(),
                emit_state=True,
                show_tip=False,
            )

    def _on_province_changed(self) -> None:
        if self._syncing:
            return
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        if runtime_page is None:
            return
        idx = self.province_combo.currentIndex()
        if idx >= 0 and idx < runtime_page.random_ip_card.provinceCombo.count():
            runtime_page.random_ip_card.provinceCombo.setCurrentIndex(idx)

    def _on_city_changed(self) -> None:
        if self._syncing:
            return
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        if runtime_page is None:
            return
        idx = self.city_combo.currentIndex()
        if idx >= 0 and idx < runtime_page.random_ip_card.cityCombo.count():
            runtime_page.random_ip_card.cityCombo.setCurrentIndex(idx)

    def _on_custom_api_finished(self) -> None:
        if self._syncing:
            return
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        if runtime_page is not None:
            runtime_page.set_custom_proxy_api(self.custom_api_edit.text().strip())

    def _on_test_api_clicked(self) -> None:
        url = self.custom_api_edit.text().strip()
        if not url:
            show_message_bar(
                parent=self.window() or self,
                title="",
                message="请先输入代理 API 地址",
                level="warning",
                position=InfoBarPosition.TOP,
            )
            return
        if self._test_thread is not None:
            return
        self.test_api_btn.setEnabled(False)
        thread = QThread(self)
        worker = _ProxyApiTestWorker(url)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_test_api_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._test_thread = thread
        self._test_worker = worker
        thread.start()

    def _on_test_api_finished(self, success: bool, error: str, proxies: list) -> None:
        self._test_thread = None
        self._test_worker = None
        self.test_api_btn.setEnabled(True)
        parent = self.window() or self
        if success:
            show_message_bar(
                parent=parent,
                title="",
                message=f"代理检测成功，获取 {len(proxies)} 条代理",
                level="success",
                position=InfoBarPosition.TOP,
            )
        else:
            show_message_bar(
                parent=parent,
                title="",
                message=error or "代理检测失败",
                level="error",
                position=InfoBarPosition.TOP,
            )

    def _on_target_changed(self, value: int) -> None:
        if self._syncing:
            return
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        if runtime_page is not None:
            runtime_page.target_card.spinBox.setValue(int(value))

    def _on_threads_changed(self, value: int) -> None:
        if self._syncing:
            return
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        if runtime_page is not None:
            runtime_page.thread_card.slider.setValue(int(value))

    def _on_interval_changed(self, _time: QTime) -> None:
        if self._syncing:
            return
        low = self.interval_start_picker.getDurationSeconds()
        high = self.interval_end_picker.getDurationSeconds()
        if high < low:
            high = low
            self._syncing = True
            self.interval_end_picker.setDurationSeconds(high)
            self._syncing = False
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        if runtime_page is not None:
            runtime_page.interval_card.setRange((low, high))

    def _on_duration_changed(self, _time: QTime) -> None:
        if self._syncing:
            return
        low = self.duration_start_picker.getDurationSeconds()
        high = self.duration_end_picker.getDurationSeconds()
        if high < low:
            high = low
            self._syncing = True
            self.duration_end_picker.setDurationSeconds(high)
            self._syncing = False
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        if runtime_page is not None:
            runtime_page.answer_duration_card.setRange((low, high))

    def _on_answer_datetime_changed(self, window: tuple[str, str]) -> None:
        if self._syncing:
            return
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        if runtime_page is not None and hasattr(runtime_page, "answer_card"):
            runtime_page.answer_card.setDateTimeWindow(window)

    def _on_ua_switch_changed(self, checked: bool) -> None:
        set_widget_enabled_with_opacity(self.ua_container, bool(checked))
        if self._syncing:
            return
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        if runtime_page is not None:
            runtime_page.random_ua_card.setChecked(bool(checked))

    def _on_ua_ratio_changed(self, ratios: dict[str, int]) -> None:
        if self._syncing:
            return
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        if runtime_page is not None:
            runtime_page.random_ua_card.setRatios(dict(ratios))

    def _on_reliability_toggled(self, checked: bool) -> None:
        set_widget_enabled_with_opacity(self.reliability_container, bool(checked))
        if self._syncing:
            return
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        if runtime_page is not None:
            runtime_page.reliability_card.setChecked(bool(checked))

    def _current_alpha_value(self) -> float:
        try:
            val = float(self.alpha_edit.text().strip() or "0.85")
        except ValueError:
            val = 0.85
        return max(0.50, min(0.99, val))

    def _on_alpha_finished(self) -> None:
        alpha = self._current_alpha_value()
        self._syncing = True
        self.alpha_edit.setText(f"{alpha:.2f}")
        self._syncing = False
        runtime_page = getattr(self.dashboard, "runtime_page", None)
        if runtime_page is not None:
            runtime_page.reliability_card.set_alpha(alpha)
