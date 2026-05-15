"""运行参数页 UI 组装。"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, FluentIcon, SettingCardGroup

from software.ui.pages.workbench.runtime_panel.ai import RuntimeAISection
from software.ui.pages.workbench.runtime_panel.cards import (
    RandomUASettingCard,
    ReliabilitySettingCard,
    TimeRangeSettingCard,
    TimedModeSettingCard,
)
from software.ui.pages.workbench.runtime_panel.random_ip_card import RandomIPSettingCard
from software.ui.widgets.setting_cards import (
    SliderSettingCard,
    SpinBoxSettingCard,
    SwitchSettingCard,
)


def build_runtime_page_ui(page) -> None:
    """把运行参数页的布局一次性装好。"""
    layout = QVBoxLayout(page.view)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.setSpacing(20)

    feature_group = SettingCardGroup("特性开关", page.view)
    page.random_ip_card = RandomIPSettingCard(parent=feature_group)
    page.random_ua_card = RandomUASettingCard(parent=feature_group)
    feature_group.addSettingCard(page.random_ip_card)
    feature_group.addSettingCard(page.random_ua_card)
    layout.addWidget(feature_group)

    run_group = SettingCardGroup("作答设置", page.view)
    page.target_card = SpinBoxSettingCard(
        FluentIcon.DOCUMENT,
        "目标份数",
        "设置要提交的问卷数量",
        min_val=1,
        max_val=9999,
        default=10,
        parent=run_group,
    )
    page.thread_card = SliderSettingCard(
        FluentIcon.APPLICATION,
        "并发会话",
        "控制同时运行的独立问卷会话数量，程序会自动复用更少的浏览器底座",
        min_val=page.MIN_THREADS,
        max_val=page.NON_HEADLESS_MAX_THREADS,
        default=2,
        parent=run_group,
    )
    page.target_card.setSpinBoxWidth(page.target_card.suggestSpinBoxWidthForDigits(4))
    page.reliability_card = ReliabilitySettingCard(parent=run_group)
    page.reliability_card.setChecked(True)
    page.reliability_card.set_alpha(0.85)
    page.headless_card = SwitchSettingCard(
        FluentIcon.SPEED_HIGH,
        "无头模式",
        "开启后浏览器在后台运行，不显示窗口，可提高并发性能",
        parent=run_group,
    )
    page.headless_card.setChecked(True)
    for card in (
        page.target_card,
        page.thread_card,
        page.reliability_card,
        page.headless_card,
    ):
        run_group.addSettingCard(card)
    layout.addWidget(run_group)

    time_group = SettingCardGroup("时间控制", page.view)
    time_hint = BodyLabel("（其实官方并不会因为你提交过快就封你号）", time_group)
    time_hint.setStyleSheet("color: green; font-size: 12px;")
    title_container = QWidget(time_group)
    title_layout = QHBoxLayout(title_container)
    title_layout.setContentsMargins(0, 0, 0, 0)
    title_layout.setSpacing(8)
    time_group.titleLabel.setParent(title_container)
    title_layout.addWidget(time_group.titleLabel)
    title_layout.addWidget(time_hint)
    title_layout.addStretch()
    time_group.vBoxLayout.insertWidget(0, title_container)

    page.interval_card = TimeRangeSettingCard(
        FluentIcon.HISTORY,
        "提交间隔",
        f"两次提交之间的等待时间（0-{page.SUBMIT_INTERVAL_MAX_SECONDS} 秒）",
        max_seconds=page.SUBMIT_INTERVAL_MAX_SECONDS,
        parent=time_group,
    )
    page.answer_card = TimeRangeSettingCard(
        FluentIcon.STOP_WATCH,
        "作答时长",
        "设置单份作答耗时（大于等于 0 秒），按20%比例随机上下抖动",
        max_seconds=None,
        parent=time_group,
    )
    page.timed_card = TimedModeSettingCard(
        FluentIcon.RINGER,
        "定时模式",
        "启用后忽略时间设置，在开放后立即提交",
        parent=time_group,
    )
    for card in (page.interval_card, page.answer_card, page.timed_card):
        time_group.addSettingCard(card)
    layout.addWidget(time_group)

    page.ai_section = RuntimeAISection(page.view, page)
    page.ai_section.bind_to_layout(layout)
    layout.addStretch(1)
