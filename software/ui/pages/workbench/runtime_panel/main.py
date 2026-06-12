from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QWidget
from qfluentwidgets import ExpandGroupSettingCard, ScrollArea, SettingCardGroup

from software.app.config import HTTP_MAX_THREADS
from software.ui.controller.run_controller import RunController
from software.ui.pages.workbench.runtime_panel.config_sync import RuntimeConfigSyncMixin
from software.ui.pages.workbench.runtime_panel.control_sync import RuntimeControlSyncMixin
from software.ui.pages.workbench.runtime_panel.events import bind_runtime_page_events
from software.ui.pages.workbench.runtime_panel.proxy_sync import RuntimeProxySyncMixin
from software.ui.pages.workbench.runtime_panel.ui_builder import build_runtime_page_ui

if TYPE_CHECKING:
    from software.ui.pages.workbench.runtime_panel.ai import RuntimeAISection
    from software.ui.pages.workbench.runtime_panel.cards import (
        AnswerDateTimeWindowSettingCard,
        RandomUASettingCard,
        ReliabilitySettingCard,
        TimeRangeSettingCard,
    )
    from software.ui.pages.workbench.runtime_panel.random_ip_card import RandomIPSettingCard
    from software.ui.widgets.setting_cards import (
        SliderSettingCard,
        SpinBoxSettingCard,
    )


class RuntimePage(
    RuntimeConfigSyncMixin,
    RuntimeControlSyncMixin,
    RuntimeProxySyncMixin,
    ScrollArea,
):
    

    MIN_THREADS = 1
    HTTP_MAX_THREADS = HTTP_MAX_THREADS
    SUBMIT_INTERVAL_MAX_SECONDS = 300
    view: QWidget
    target_card: "SpinBoxSettingCard"
    thread_card: "SliderSettingCard"
    random_ip_card: "RandomIPSettingCard"
    random_ua_card: "RandomUASettingCard"
    reliability_card: "ReliabilitySettingCard"
    interval_card: "TimeRangeSettingCard"
    answer_duration_card: "TimeRangeSettingCard"
    answer_card: "AnswerDateTimeWindowSettingCard"
    ai_section: "RuntimeAISection"

    def __init__(self, controller: RunController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._last_benefit_proxy_compatible = None
        self._layout_refresh_pending = False
        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self.view.setObjectName("settings_view")
        build_runtime_page_ui(self)
        bind_runtime_page_events(self)
        runtime_signal = getattr(self.controller, "runtimeSnapshotChanged", None)
        if runtime_signal is not None and hasattr(runtime_signal, "connect"):
            runtime_signal.connect(self._on_runtime_snapshot_changed)
        else:
            legacy_runtime_signal = getattr(self.controller, "runtimeUiStateChanged", None)
            if legacy_runtime_signal is not None and hasattr(legacy_runtime_signal, "connect"):
                legacy_runtime_signal.connect(self._apply_runtime_ui_state)
            legacy_run_signal = getattr(self.controller, "runStateChanged", None)
            if legacy_run_signal is not None and hasattr(legacy_run_signal, "connect"):
                legacy_run_signal.connect(self.on_run_state_changed)
            legacy_loading_signal = getattr(self.controller, "randomIpLoadingChanged", None)
            if legacy_loading_signal is not None and hasattr(legacy_loading_signal, "connect"):
                legacy_loading_signal.connect(self._apply_random_ip_loading)
        self._sync_random_ua(self.random_ua_card.isChecked())
        self._sync_answer_datetime_window_card()
        self._apply_thread_limit()
        updater = getattr(self.controller, "update_runtime_settings", None)
        if callable(updater):
            updater(
                emit=False,
                target=self.target_card.spinBox.value(),
                threads=self.thread_card.slider.value(),
                random_ip_enabled=self.random_ip_card.switchButton.isChecked(),
                proxy_source=self.selected_proxy_source(),
                submit_interval=self._card_value_as_range(self.interval_card),
                answer_duration=self._card_value_as_range(self.answer_duration_card),
                answer_datetime_window=self.answer_card.getDateTimeWindow(),
            )
        self.on_run_state_changed(self._thread_edit_locked())
        if hasattr(self.controller, "get_runtime_snapshot"):
            self._on_runtime_snapshot_changed(self.controller.get_runtime_snapshot())
        elif hasattr(self.controller, "get_runtime_ui_state"):
            self._apply_runtime_ui_state(self.controller.get_runtime_ui_state())
        self._queue_expanded_card_layout_refresh()

    def _on_runtime_snapshot_changed(self, snapshot: dict) -> None:
        runtime_snapshot = dict(snapshot or {})
        self._apply_runtime_ui_state(runtime_snapshot.get("settings") or {})
        random_ip = runtime_snapshot.get("random_ip") or {}
        self._apply_random_ip_loading(
            bool(random_ip.get("loading")),
            str(random_ip.get("loading_message") or ""),
        )
        self.on_run_state_changed(bool(runtime_snapshot.get("running")))
        self._queue_expanded_card_layout_refresh()

    def event(self, event) -> bool:
        handled = super().event(event)
        if event.type() in {QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.LayoutRequest}:
            self._queue_expanded_card_layout_refresh()
        return handled

    def _queue_expanded_card_layout_refresh(self) -> None:
        if self._layout_refresh_pending:
            return
        self._layout_refresh_pending = True
        QTimer.singleShot(0, self._refresh_expanded_card_layouts)

    def _refresh_expanded_card_layouts(self) -> None:
        self._layout_refresh_pending = False
        try:
            cards = self.view.findChildren(ExpandGroupSettingCard)
        except RuntimeError:
            return
        for card in cards:
            view = getattr(card, "view", None)
            if view is not None and view.layout() is not None:
                view.layout().activate()
            if getattr(card, "isExpand", False):
                adjust_view_size = getattr(card, "_adjustViewSize", None)
                if callable(adjust_view_size):
                    adjust_view_size()
                if view is not None:
                    view.adjustSize()
            card.updateGeometry()
            card.adjustSize()
        try:
            groups = self.view.findChildren(SettingCardGroup)
        except RuntimeError:
            return
        for group in groups:
            group_layout = group.layout()
            if group_layout is not None:
                group_layout.activate()
            group.updateGeometry()
            group.adjustSize()
        try:
            layout = self.view.layout()
        except RuntimeError:
            return
        if layout is not None:
            layout.invalidate()
            layout.activate()
        self.view.adjustSize()
        self.view.updateGeometry()
