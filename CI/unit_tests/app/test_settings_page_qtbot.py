from __future__ import annotations

from PySide6.QtWidgets import QWidget

from software.app.config import (
    AUTO_SAVE_LOG_RETENTION_COUNT_SETTING_KEY,
    AUTO_SAVE_LOGS_SETTING_KEY,
    NAVIGATION_TEXT_VISIBLE_SETTING_KEY,
    TASK_RESULT_WINDOWS_NOTIFICATION_SETTING_KEY,
)
import software.ui.pages.settings.settings as settings_module
from software.ui.pages.settings.settings import SettingsPage


class _FakeSettings:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.removed: list[str] = []

    def value(self, key: str):
        return self.data.get(key)

    def setValue(self, key: str, value) -> None:
        self.data[key] = value

    def remove(self, key: str) -> None:
        self.removed.append(key)
        self.data.pop(key, None)


class _FakeNavigation:
    def __init__(self) -> None:
        self.visible = None

    def setSelectedTextVisible(self, enabled: bool) -> None:
        self.visible = bool(enabled)


class _FakeWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.navigationInterface = _FakeNavigation()
        self.topmost_calls: list[tuple[bool, bool]] = []

    def apply_topmost_state(self, checked: bool, show: bool = True) -> None:
        self.topmost_calls.append((bool(checked), bool(show)))


def test_settings_page_toggles_update_settings_and_related_widgets(qtbot, monkeypatch) -> None:
    fake_settings = _FakeSettings()
    fake_window = _FakeWindow()
    qtbot.addWidget(fake_window)
    monkeypatch.setattr(settings_module, "app_settings", lambda: fake_settings)
    monkeypatch.setattr(settings_module, "reset_ai_settings", lambda: None)
    monkeypatch.setattr(settings_module, "clear_survey_parse_cache", lambda: 0)

    page = SettingsPage(parent=fake_window)
    page.show()
    qtbot.waitUntil(lambda: page.navigation_text_card.isChecked() is True)

    page.auto_save_logs_combo.setCurrentIndex(page.auto_save_logs_combo.findData(3))
    page._on_navigation_text_toggled(False)
    page._on_topmost_toggled(True)
    page._on_auto_save_logs_toggled(True)
    page._on_auto_save_log_retention_changed()

    assert fake_settings.data[NAVIGATION_TEXT_VISIBLE_SETTING_KEY] is False
    assert fake_window.navigationInterface.visible is False
    assert fake_settings.data[AUTO_SAVE_LOGS_SETTING_KEY] is True
    assert fake_settings.data[AUTO_SAVE_LOG_RETENTION_COUNT_SETTING_KEY] == 3
    assert fake_window.topmost_calls[-1] == (True, True)


def test_settings_page_reset_restores_defaults(qtbot, monkeypatch) -> None:
    fake_settings = _FakeSettings()
    fake_window = _FakeWindow()
    qtbot.addWidget(fake_window)
    monkeypatch.setattr(settings_module, "app_settings", lambda: fake_settings)
    monkeypatch.setattr(settings_module, "reset_ai_settings", lambda: None)
    monkeypatch.setattr(settings_module, "clear_survey_parse_cache", lambda: 0)

    page = SettingsPage(parent=fake_window)
    page.show()
    qtbot.waitUntil(lambda: page.auto_update_card.isChecked() is True)

    page._on_reset_ui_settings = lambda: None
    page._reset_defined_settings()

    assert fake_settings.removed
    assert page.auto_save_logs_card.isChecked() is page._defaults[AUTO_SAVE_LOGS_SETTING_KEY]
    assert page.navigation_text_card.isChecked() is page._defaults[NAVIGATION_TEXT_VISIBLE_SETTING_KEY]
    assert page.task_result_notification_card.isChecked() is page._defaults[TASK_RESULT_WINDOWS_NOTIFICATION_SETTING_KEY]
