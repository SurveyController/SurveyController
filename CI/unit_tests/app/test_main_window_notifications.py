from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from software.ui.shell.main_window_parts.notifications import MainWindowNotificationsMixin


class _FakeTrayIcon:
    class MessageIcon:
        Information = object()

    def __init__(self, icon=None, parent=None) -> None:
        self.icon = icon
        self.parent = parent
        self.tooltip = ""
        self.shown = False
        self.messages: list[tuple[str, str, object, int]] = []
        self.hidden = False
        self.deleted = False

    @staticmethod
    def isSystemTrayAvailable() -> bool:
        return True

    def setToolTip(self, text: str) -> None:
        self.tooltip = text

    def show(self) -> None:
        self.shown = True

    def hide(self) -> None:
        self.hidden = True

    def deleteLater(self) -> None:
        self.deleted = True

    def showMessage(self, title: str, message: str, icon, timeout: int) -> None:
        self.messages.append((title, message, icon, timeout))


class _FakeNotificationsWindow(MainWindowNotificationsMixin):
    def __init__(self) -> None:
        self._completion_notification_sent = False
        self._failure_notification_sent = False
        self._base_window_title = "SurveyController"
        self._system_tray_icon = None
        self.controller = SimpleNamespace(_execution_state=None)
        self.visible = True
        self.minimized = False
        self.active = False

    def isVisible(self) -> bool:
        return self.visible

    def isMinimized(self) -> bool:
        return self.minimized

    def isActiveWindow(self) -> bool:
        return self.active

    def windowIcon(self) -> QIcon:
        return SimpleNamespace(isNull=lambda: False)


class MainWindowNotificationsTests:
    def test_ensure_system_tray_icon_creates_and_reuses_tray(self) -> None:
        window = _FakeNotificationsWindow()
        fake_app = SimpleNamespace(applicationState=lambda: Qt.ApplicationState.ApplicationInactive)
        with patch(
            "software.ui.shell.main_window_parts.notifications.QSystemTrayIcon",
            _FakeTrayIcon,
        ), patch(
            "software.ui.shell.main_window_parts.notifications.get_resource_path",
            return_value="missing.ico",
        ), patch(
            "software.ui.shell.main_window_parts.notifications.QApplication.instance",
            return_value=fake_app,
        ):
            tray1 = window._ensure_system_tray_icon()
            tray2 = window._ensure_system_tray_icon()
        assert tray1 is tray2
        assert tray1 is not None
        assert tray1.parent is window
        assert tray1.tooltip == "SurveyController"
        assert tray1.shown is True

    def test_is_user_away_from_app_uses_application_state_when_window_not_active(self) -> None:
        window = _FakeNotificationsWindow()
        fake_app = SimpleNamespace(applicationState=lambda: Qt.ApplicationState.ApplicationInactive)
        with patch("software.ui.shell.main_window_parts.notifications.QApplication.instance", return_value=fake_app):
            assert window._is_user_away_from_app() is True
        fake_active_app = SimpleNamespace(applicationState=lambda: Qt.ApplicationState.ApplicationActive)
        with patch("software.ui.shell.main_window_parts.notifications.QApplication.instance", return_value=fake_active_app):
            assert window._is_user_away_from_app() is True
        window.active = True
        with patch("software.ui.shell.main_window_parts.notifications.QApplication.instance", return_value=fake_active_app):
            assert window._is_user_away_from_app() is False

    def test_show_windows_notification_respects_setting_and_sends_message(self) -> None:
        window = _FakeNotificationsWindow()
        tray = _FakeTrayIcon()
        settings = SimpleNamespace(value=lambda _key: True)
        with patch("software.ui.shell.main_window_parts.notifications.app_settings", return_value=settings), patch(
            "software.ui.shell.main_window_parts.notifications.get_bool_from_qsettings",
            return_value=True,
        ), patch.object(
            window,
            "_is_user_away_from_app",
            return_value=True,
        ), patch.object(
            window,
            "_ensure_system_tray_icon",
            return_value=tray,
        ):
            shown = window._show_windows_notification("Title", "Body")
        assert shown is True
        assert len(tray.messages) == 1
        title, body, _icon, timeout = tray.messages[0]
        assert (title, body, timeout) == ("Title", "Body", 8000)

    def test_dispose_system_tray_icon_hides_and_deletes_tray(self) -> None:
        window = _FakeNotificationsWindow()
        tray = _FakeTrayIcon()
        window._system_tray_icon = tray
        window._dispose_system_tray_icon()
        assert window._system_tray_icon is None
        assert tray.hidden is True
        assert tray.deleted is True
