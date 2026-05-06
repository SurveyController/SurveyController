"""联系开发者对话框"""
from typing import cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QDialog, QVBoxLayout

from software.ui.widgets.contact_form import ContactForm


class ContactDialog(QDialog):
    """联系开发者（Qt 版本）。包装 ContactForm，保留原有对话框入口。"""

    def __init__(
        self,
        parent=None,
        default_type: str = "报错反馈",
        lock_message_type: bool = False,
        status_endpoint: str = "",
        status_formatter=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("联系开发者")
        self.resize(720, 520)
        self._status_poll_timer = QTimer(cast(QObject, self))
        self._status_poll_timer.setSingleShot(True)
        self._status_poll_timer.setInterval(700)
        self._status_poll_timer.timeout.connect(self._start_status_polling_if_ready)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self.form = ContactForm(
            self,
            default_type=default_type,
            lock_message_type=lock_message_type,
            status_endpoint=status_endpoint,
            status_formatter=status_formatter,
            config_snapshot_provider=getattr(parent, "_collect_current_config_snapshot", None),
            show_cancel_button=True,
            auto_clear_on_success=False,
            manage_polling=False,
        )
        layout.addWidget(self.form)

        self.form.sendSucceeded.connect(self._on_send_succeeded)
        self.form.cancelRequested.connect(self.reject)

    def showEvent(self, arg__1):
        super().showEvent(arg__1)
        self._schedule_status_polling()

    def _schedule_status_polling(self) -> None:
        self._status_poll_timer.stop()
        self._status_poll_timer.start()

    def _start_status_polling_if_ready(self) -> None:
        if not self.isVisible():
            return
        self.form.start_status_polling()

    def _stop_status_polling(self) -> None:
        self._status_poll_timer.stop()
        self.form.stop_status_polling()

    def _on_send_succeeded(self):
        """发送成功后延迟关闭，让InfoBar有时间显示"""
        QTimer.singleShot(2800, self.accept)

    def closeEvent(self, arg__1):
        if self.form.has_pending_async_work():
            self.form.show_pending_async_warning()
            arg__1.ignore()
            return
        self._stop_status_polling()
        super().closeEvent(arg__1)

    def reject(self):
        if self.form.has_pending_async_work():
            self.form.show_pending_async_warning()
            return
        self._stop_status_polling()
        super().reject()

    def accept(self):
        if self.form.has_pending_async_work():
            self.form.show_pending_async_warning()
            return
        self._stop_status_polling()
        super().accept()

