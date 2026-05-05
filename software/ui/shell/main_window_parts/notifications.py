"""MainWindow Windows 通知相关方法。"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from software.app.config import (
    BACKGROUND_RUN_NOTIFICATION_SETTING_KEY,
    DEFAULT_BACKGROUND_RUN_NOTIFICATIONS,
    app_settings,
    get_bool_from_qsettings,
)
from software.app.config import APP_ICON_RELATIVE_PATH
from software.app.runtime_paths import get_resource_path


class MainWindowNotificationsMixin:
    """收口主窗口 Windows 桌面通知逻辑。"""

    if TYPE_CHECKING:
        _completion_notification_sent: bool
        _failure_notification_sent: bool
        _base_window_title: str
        _system_tray_icon: QSystemTrayIcon | None
        controller: object

        def isVisible(self) -> bool: ...
        def isMinimized(self) -> bool: ...
        def isActiveWindow(self) -> bool: ...
        def windowIcon(self) -> QIcon: ...

    def _ensure_system_tray_icon(self) -> QSystemTrayIcon | None:
        tray = cast(QSystemTrayIcon | None, getattr(self, "_system_tray_icon", None))
        if tray is not None:
            return tray
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None

        icon = self.windowIcon()
        if icon.isNull():
            icon_path = get_resource_path(APP_ICON_RELATIVE_PATH)
            icon = QIcon(icon_path)
        if icon.isNull():
            return None

        tray = QSystemTrayIcon(icon, cast(QObject, self))
        tray.setToolTip(str(getattr(self, "_base_window_title", "SurveyController") or "SurveyController"))
        tray.show()
        self._system_tray_icon = tray
        return tray

    def _is_user_away_from_app(self) -> bool:
        try:
            if not self.isVisible() or self.isMinimized():
                return True
        except Exception:
            return True

        try:
            if self.isActiveWindow():
                return False
        except Exception:
            pass

        app = QApplication.instance()
        if app is not None:
            try:
                gui_app = cast(QGuiApplication, app)
                if gui_app.applicationState() != Qt.ApplicationState.ApplicationActive:
                    return True
            except Exception:
                pass
        return True

    def _show_windows_notification(self, title: str, message: str) -> bool:
        settings = app_settings()
        if not get_bool_from_qsettings(
            settings.value(BACKGROUND_RUN_NOTIFICATION_SETTING_KEY),
            DEFAULT_BACKGROUND_RUN_NOTIFICATIONS,
        ):
            return False
        if not self._is_user_away_from_app():
            return False
        tray = self._ensure_system_tray_icon()
        if tray is None:
            return False
        try:
            tray.showMessage(
                str(title or "SurveyController"),
                str(message or ""),
                QSystemTrayIcon.MessageIcon.Information,
                8000,
            )
            return True
        except Exception:
            logging.info("显示 Windows 通知失败", exc_info=True)
            return False

    def _reset_run_notifications(self) -> None:
        self._completion_notification_sent = False
        self._failure_notification_sent = False

    def _notify_run_completed_if_needed(self) -> None:
        if bool(getattr(self, "_completion_notification_sent", False)):
            return
        if self._show_windows_notification("SurveyController", "任务已完成，目标份数已经跑满。"):
            self._completion_notification_sent = True

    def _notify_run_failed_if_needed(self) -> None:
        if bool(getattr(self, "_failure_notification_sent", False)):
            return

        ctx = getattr(self.controller, "_execution_state", None)
        if ctx is None:
            return

        try:
            category, failure_reason, message = ctx.get_terminal_stop_snapshot()
        except Exception:
            logging.info("读取任务结束原因失败", exc_info=True)
            return

        category = str(category or "").strip()
        failure_reason = str(failure_reason or "").strip()
        message = str(message or "").strip()
        if not category or category in {"target_reached", "user_stopped"}:
            return
        if failure_reason in {"user_stopped", "submission_verification_required", "device_quota_limit"}:
            return

        notify_message = message or "任务未完成，已停止运行。"
        if self._show_windows_notification("SurveyController", f"任务失败：{notify_message}"):
            self._failure_notification_sent = True

    def _dispose_system_tray_icon(self) -> None:
        tray = getattr(self, "_system_tray_icon", None)
        self._system_tray_icon = None
        if tray is None:
            return
        try:
            tray.hide()
        except Exception:
            pass
        try:
            tray.deleteLater()
        except Exception:
            pass
