from __future__ import annotations

import logging
from typing import Any, cast

from software.logging.log_utils import log_suppressed_exception
from software.logging.action_logger import log_action
from software.ui.helpers.proxy_access import (
    apply_custom_proxy_api,
    apply_proxy_source_settings,
)
from software.ui.pages.workbench.runtime_panel.proxy_source import (
    PROXY_SOURCE_CUSTOM,
    PROXY_SOURCE_DEFAULT,
    normalize_proxy_source,
)


class RuntimeProxySyncMixin:
    controller: Any
    view: Any
    answer_card: Any
    answer_duration_card: Any
    interval_card: Any
    random_ip_card: Any

    @staticmethod
    def _normalize_proxy_source(source: str) -> str:
        return normalize_proxy_source(source)

    def selected_proxy_source(self) -> str:
        idx = self.random_ip_card.proxyCombo.currentIndex()
        source = (
            str(self.random_ip_card.proxyCombo.itemData(idx)) if idx >= 0 else PROXY_SOURCE_DEFAULT
        )
        return normalize_proxy_source(source)

    def _get_selected_proxy_source(self) -> str:
        return self.selected_proxy_source()

    def set_proxy_source(
        self,
        source: str,
        custom_api_url: str | None = None,
        *,
        emit_state: bool = True,
        show_tip: bool = True,
    ) -> str:
        normalized = normalize_proxy_source(source)
        combo = self.random_ip_card.proxyCombo
        index = combo.findData(normalized)
        if index < 0:
            normalized = PROXY_SOURCE_DEFAULT
            index = combo.findData(normalized)
        if index >= 0 and combo.currentIndex() != index:
            combo.blockSignals(True)
            try:
                combo.setCurrentIndex(index)
            finally:
                combo.blockSignals(False)
        if custom_api_url is not None:
            self.random_ip_card.customApiEdit.setText(str(custom_api_url or ""))
        self.random_ip_card._on_source_changed()
        self._apply_proxy_source_settings(normalized)
        if emit_state:
            self.controller.update_runtime_settings(proxy_source=normalized)
        return normalized

    def set_custom_proxy_api(self, api_url: str) -> None:
        value = str(api_url or "").strip()
        self.random_ip_card.customApiEdit.setText(value)
        if self.selected_proxy_source() == PROXY_SOURCE_CUSTOM:
            try:
                apply_custom_proxy_api(value if value else None)
            except Exception as exc:
                log_suppressed_exception(
                    "set_custom_proxy_api: apply_custom_proxy_api",
                    exc,
                    level=logging.WARNING,
                )
            self._apply_proxy_source_settings(PROXY_SOURCE_CUSTOM)

    def _apply_proxy_source_settings(self, source: str) -> None:
        try:
            if source == PROXY_SOURCE_CUSTOM:
                api_url = self.random_ip_card.customApiEdit.text().strip()
                apply_proxy_source_settings(source, custom_api_url=api_url if api_url else None)
                return
            apply_proxy_source_settings(source, custom_api_url=None)
        except Exception as exc:
            log_suppressed_exception(
                "_apply_proxy_source_settings",
                exc,
                level=logging.WARNING,
            )

    def _on_proxy_source_changed(self):
        source = self.set_proxy_source(
            self.selected_proxy_source(),
            emit_state=True,
            show_tip=True,
        )
        log_action(
            "CONFIG",
            "change_proxy_source",
            "proxy_source_combo",
            "runtime",
            result="changed",
            payload={"source": source},
        )

    def _on_time_settings_changed(self, _value: Any):
        page = cast(Any, self)
        self.controller.update_runtime_settings(
            submit_interval=page._card_value_as_range(self.interval_card),
            answer_duration=page._card_value_as_range(self.answer_duration_card),
        )

    def _on_answer_datetime_window_changed(self, _value: Any):
        self.controller.update_runtime_settings(
            answer_datetime_window=self.answer_card.getDateTimeWindow()
        )
