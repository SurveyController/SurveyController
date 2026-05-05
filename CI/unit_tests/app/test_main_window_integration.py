from __future__ import annotations

import os
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

import software.ui.shell.main_window as main_window_module


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeBootSplash:
    def update_layout(self, *_args, **_kwargs) -> None:
        return None

    def cleanup(self) -> None:
        return None


class _FakeCloseEvent:
    def __init__(self) -> None:
        self.accepted = False
        self.ignored = False

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


class _FakeTrayIcon:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, object, int]] = []

    def showMessage(self, title: str, message: str, icon, timeout: int) -> None:
        self.messages.append((title, message, icon, timeout))


def _create_real_main_window():
    app = QApplication.instance() or QApplication([])
    stack = ExitStack()
    stack.enter_context(patch("software.ui.shell.main_window.create_boot_splash", return_value=_FakeBootSplash()))
    stack.enter_context(patch("software.ui.shell.main_window.finish_boot_splash", return_value=None))
    stack.enter_context(patch.object(main_window_module.MainWindow, "_check_update_on_startup", lambda self: None))
    stack.enter_context(patch.object(main_window_module.MainWindow, "_start_random_ip_quota_auto_sync", lambda self: None))
    stack.enter_context(patch.object(main_window_module.MainWindow, "_load_saved_config", lambda self: None))
    stack.enter_context(patch.object(main_window_module.MainWindow, "_refresh_title_random_ip_user_id", lambda self: None))
    stack.enter_context(patch.object(main_window_module.MainWindow, "_sync_reverse_fill_context", lambda self: None))
    window = main_window_module.create_window()
    window.hide()
    return app, window, stack


def _cleanup_window(app: QApplication, window, stack: ExitStack) -> None:
    try:
        try:
            timer = getattr(window, "_random_ip_quota_auto_sync_timer", None)
            if timer is not None:
                timer.stop()
        except Exception:
            pass
        window.deleteLater()
        app.processEvents()
    finally:
        stack.close()


class MainWindowIntegrationTests:
    def test_real_main_window_close_event_defers_confirmation_then_requests_close(self) -> None:
        app, window, stack = _create_real_main_window()
        try:
            event = _FakeCloseEvent()
            close_calls: list[str] = []
            with patch.object(window, "_confirm_close_with_optional_save", return_value=True), patch.object(
                window,
                "close",
                side_effect=lambda: close_calls.append("close"),
            ), patch(
                "software.ui.shell.main_window_parts.lifecycle.QTimer.singleShot",
                side_effect=lambda _ms, _receiver, func: func(),
            ):
                window.closeEvent(event)
            assert event.ignored is True
            assert window._close_request_pending is False
            assert window._close_request_confirmed is True
            assert close_calls == ["close"]
        finally:
            _cleanup_window(app, window, stack)

    def test_real_main_window_close_event_accepts_after_confirmation(self) -> None:
        app, window, stack = _create_real_main_window()
        try:
            event = _FakeCloseEvent()
            finalize_calls: list[str] = []
            window._close_request_confirmed = True
            with patch.object(
                window,
                "_finalize_confirmed_close",
                side_effect=lambda: finalize_calls.append("finalized"),
            ):
                window.closeEvent(event)
            assert event.accepted is True
            assert finalize_calls == ["finalized"]
        finally:
            _cleanup_window(app, window, stack)

    def test_real_main_window_failure_notification_updates_flag_when_notification_sent(self) -> None:
        app, window, stack = _create_real_main_window()
        try:
            execution_state = SimpleNamespace(
                get_terminal_stop_snapshot=lambda: ("proxy_unavailable_threshold", "fill_failed", "代理耗尽"),
            )
            window.controller._execution_state = execution_state
            with patch.object(window, "_show_windows_notification", return_value=True) as show_notification:
                window._notify_run_failed_if_needed()
            show_notification.assert_called_once_with("SurveyController", "任务失败：代理耗尽")
            assert window._failure_notification_sent is True
        finally:
            _cleanup_window(app, window, stack)

    def test_real_main_window_show_notification_uses_real_window_instance(self) -> None:
        app, window, stack = _create_real_main_window()
        try:
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
                shown = window._show_windows_notification("SurveyController", "任务已完成")
            assert shown is True
            assert len(tray.messages) == 1
            assert tray.messages[0][0:2] == ("SurveyController", "任务已完成")
            assert tray.messages[0][3] == 8000
        finally:
            _cleanup_window(app, window, stack)

    def test_real_main_window_finalize_close_calls_controller_sidecar_and_tray_cleanup(self) -> None:
        app, window, stack = _create_real_main_window()
        try:
            shutdown_calls: list[str] = []
            sidecar_calls: list[str] = []
            tray_calls: list[str] = []
            timer_calls: list[str] = []
            window._close_request_confirmed = True
            window._random_ip_quota_auto_sync_timer = SimpleNamespace(stop=lambda: timer_calls.append("timer"))
            window.controller = SimpleNamespace(request_shutdown_for_close=lambda: shutdown_calls.append("controller"))
            window._boot_splash = None
            window._log_page = None
            window._contact_dialog = None
            window._async_dialog_refs = []
            with patch(
                "software.ui.shell.main_window_parts.lifecycle.stop_proxy_sidecar",
                side_effect=lambda: sidecar_calls.append("sidecar"),
            ), patch.object(
                window,
                "_dispose_system_tray_icon",
                side_effect=lambda: tray_calls.append("tray"),
            ):
                window._finalize_confirmed_close()
            assert window._close_request_confirmed is False
            assert timer_calls == ["timer"]
            assert shutdown_calls == ["controller"]
            assert sidecar_calls == ["sidecar"]
            assert tray_calls == ["tray"]
        finally:
            _cleanup_window(app, window, stack)
