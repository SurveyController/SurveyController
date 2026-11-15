from __future__ import annotations

from concurrent.futures import Future
from typing import TYPE_CHECKING, Any, Callable, cast

from PySide6.QtCore import QObject, QThread, QTimer, Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QDialog
from qfluentwidgets import MessageBox

from software.app.config import (
    TASK_RESULT_SYSTEM_NOTIFICATION_SETTING_KEY,
    app_settings,
    get_bool_from_qsettings,
)
from software.logging.action_logger import log_action
from software.ui.helpers.message_bar import show_message_bar


class MainWindowDialogsMixin:
    if TYPE_CHECKING:
        _task_result_tray_icon: Any
        _async_dialog_refs: Any

        def thread(self) -> QThread: ...
        def isVisible(self) -> bool: ...
        def isMinimized(self) -> bool: ...
        def window(self) -> Any: ...
        def windowIcon(self) -> QIcon: ...

    def _qt_timer_context(self) -> QObject:

        return cast(QObject, self)

    def _toast(self, text: str, level: str = "info", duration: int = 2000):
        show_message_bar(parent=self, message=text, level=level, duration=duration)

    def _dispatch_to_ui_async(self, func: Callable[[], Any]) -> None:
        if cast(QObject, self).thread() == QThread.currentThread():
            func()
            return
        QTimer.singleShot(0, self._qt_timer_context(), func)

    def _is_window_activated(self) -> bool:
        try:
            if not self.isVisible() or self.isMinimized():
                return False
        except Exception:
            return False
        try:
            window = self.window()
            if window is not None and hasattr(window, "isActiveWindow") and window.isActiveWindow():
                return True
        except Exception:
            pass
        try:
            active = QApplication.activeWindow() or QGuiApplication.focusWindow()
            return active is not None
        except Exception:
            return False

    def _should_show_task_result_system_notification(self) -> bool:
        settings = app_settings()
        return (
            get_bool_from_qsettings(
                settings.value(TASK_RESULT_SYSTEM_NOTIFICATION_SETTING_KEY),
                True,
            )
            and not self._is_window_activated()
        )

    def _should_show_task_result_windows_notification(self) -> bool:
        return self._should_show_task_result_system_notification()

    def show_task_result_system_notification(self, title: str, message: str) -> None:
        if not self._should_show_task_result_system_notification():
            return
        try:
            from PySide6.QtWidgets import QSystemTrayIcon
        except Exception:
            return

        tray = getattr(self, "_task_result_tray_icon", None)
        if tray is None:
            tray = QSystemTrayIcon(cast(QObject, self))
            tray.setIcon(self.windowIcon())
            tray.setVisible(True)
            self._task_result_tray_icon = tray
        tray.showMessage(
            str(title or ""),
            str(message or ""),
            QSystemTrayIcon.MessageIcon.Information,
            5000,
        )

    def show_task_result_windows_notification(self, title: str, message: str) -> None:
        self.show_task_result_system_notification(title, message)

    def _open_async_dialog(self, dialog: QDialog, result: Future[bool]) -> None:
        self._async_dialog_refs.append(dialog)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        def _finish(code: int) -> None:
            if not result.done():
                result.set_result(code == QDialog.DialogCode.Accepted)

        def _destroyed(*_args) -> None:
            self._async_dialog_refs.remove(dialog)
            if not result.done():
                result.set_result(False)

        dialog.finished.connect(_finish)
        dialog.destroyed.connect(_destroyed)
        dialog.open()

    def _request_message_box(
        self,
        title: str,
        message: str,
        *,
        yes_text: str,
        cancel_text: str | None,
    ) -> Future[bool]:
        result: Future[bool] = Future()

        def _cancel(*_args) -> None:
            if not result.done():
                result.set_result(False)

        cast(QObject, self).destroyed.connect(_cancel)

        def _show() -> None:
            if result.done():
                return
            log_action(
                "DIALOG",
                "confirm",
                "message_box",
                "main_window",
                result="shown",
                detail=title,
            )
            box = MessageBox(title, message, self)
            box.yesButton.setText(yes_text)
            if cancel_text is None:
                box.cancelButton.hide()
            else:
                box.cancelButton.setText(cancel_text)

            def _complete(future: Future[bool]) -> None:
                cast(QObject, self).destroyed.disconnect(_cancel)
                log_action(
                    "DIALOG",
                    "confirm",
                    "message_box",
                    "main_window",
                    result="confirmed" if future.result() else "cancelled",
                    detail=title,
                )

            result.add_done_callback(_complete)
            self._open_async_dialog(box, result)

        self._dispatch_to_ui_async(_show)
        return result

    def request_confirm_dialog(
        self,
        title: str,
        message: str,
        *,
        yes_text: str = "确定",
        cancel_text: str = "取消",
    ) -> Future[bool]:
        return self._request_message_box(
            title,
            message,
            yes_text=yes_text,
            cancel_text=cancel_text,
        )

    def show_message_dialog(self, title: str, message: str, *, level: str = "info") -> Future[bool]:
        return self._request_message_box(title, message, yes_text="确定", cancel_text=None)
