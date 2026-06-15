import logging
import os
import tempfile
import threading
from datetime import datetime
from typing import Any, Callable, Optional, cast

from PySide6.QtCore import QEvent, QTimer, Qt, Signal, Slot
from PySide6.QtGui import (
    QKeyEvent,
    QKeySequence,
)
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    FluentIcon,
    InfoBar,
    MessageBox,
)

from software.app.config import (
    CONTACT_API_URL,
)
from software.app.user_paths import get_fatal_crash_log_path, get_user_local_data_root
from software.app.version import __VERSION__
from software.core.config.schema import RuntimeConfig
from software.io.config.store import save_config
from software.logging.log_utils import (
    LOG_BUFFER_HANDLER,
    export_full_log_to_file,
    log_suppressed_exception,
)
from software.ui.helpers.contact_api import get_session_snapshot, post
from software.ui.helpers.image_attachments import ImageAttachmentManager
from software.ui.helpers.qfluent_compat import set_indeterminate_progress_ring_active

from .attachments import (
    build_bug_report_auto_files_payload,
    cleanup_pending_temp_files,
    fatal_crash_log_payload,
    read_file_bytes,
    remove_temp_file,
    renumber_files_payload,
)
from .message_builder import build_contact_message, build_contact_request_fields
from .send_workflow import validate_email
from .status_polling import StatusPollingMixin
from .ui_behavior import (
    attachments_enabled,
    choose_files,
    clear_attachments,
    handle_clipboard_image,
    on_context_paste,
    on_type_changed,
    remove_attachment,
    render_attachments_ui,
    sync_message_type_lock_state,
    update_send_button_state,
)
from .ui_builder import build_contact_form_ui
from .lifecycle import (
    close_all_infobars,
    find_controller_host,
    has_pending_async_work,
    refresh_random_ip_user_id_hint,
    set_send_loading,
    set_status_loading,
    show_pending_async_warning,
    start_status_polling,
    stop_activity_indicators,
    stop_status_polling,
)
from .send_actions import (
    clear_email_selection,
    compute_send_timeout_fallback_ms_for_form,
    emit_send_finished_if_current,
    finish_stuck_send_if_needed,
    focus_send_button,
    on_send_clicked,
    on_send_finished,
)
http_post = post


class ContactForm(StatusPollingMixin, QWidget):
    

    type_label_static: Any
    type_combo: Any
    type_locked_label: Any
    base_options: Any
    email_label: Any
    email_edit: Any
    issue_title_label: Any
    issue_title_edit: Any
    message_label: Any
    message_edit: Any
    random_ip_user_id_label: Any
    attachments_section: Any
    attach_title: Any
    attach_add_btn: Any
    attach_clear_btn: Any
    attach_list_layout: Any
    attach_list_container: Any
    attach_placeholder: Any
    auto_attach_section: Any
    auto_attach_title: Any
    auto_attach_config_checkbox: Any
    auto_attach_log_checkbox: Any
    status_spinner: Any
    status_icon: Any
    online_label: Any
    cancel_btn: Any
    send_btn: Any
    send_spinner: Any

    _statusLoaded = Signal(str, str)  
    _sendFinished = Signal(bool, str)  
    sendSucceeded = Signal()
    cancelRequested = Signal()

    _SEND_TIMEOUT_GRACE_MS = 2_000
    _SEND_CONNECT_TIMEOUT_SECONDS = 10
    _SEND_READ_TIMEOUT_SECONDS = 10
    _SEND_READ_TIMEOUT_WITH_FILES_SECONDS = 20
    http_post = staticmethod(post)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        default_type: str = "报错反馈",
        lock_message_type: bool = False,
        status_endpoint: str = "",
        status_formatter: Optional[Callable] = None,
        config_snapshot_provider: Optional[Callable[[], Any]] = None,
        show_cancel_button: bool = False,
        auto_clear_on_success: bool = True,
        manage_polling: bool = True,
    ):
        super().__init__(parent)
        self._sendFinished.connect(self._on_send_finished, Qt.ConnectionType.QueuedConnection)
        self._init_status_polling(status_endpoint, status_formatter)
        self._attachments = ImageAttachmentManager(max_count=3, max_size_bytes=10 * 1024 * 1024)
        self._current_message_type: str = ""
        self._current_has_email: bool = False
        self._send_in_progress: bool = False
        self._send_generation: int = 0
        self._send_finished_generation: int = 0
        self._send_state_lock = threading.Lock()
        self._polling_started = False
        self._auto_clear_on_success = auto_clear_on_success
        self._manage_polling = manage_polling
        self._lock_message_type = lock_message_type
        self._config_snapshot_provider = config_snapshot_provider
        self._random_ip_user_id: int = 0
        self._pending_temp_attachment_paths: list[str] = []
        self._auto_attach_config_default = True
        self._auto_attach_log_default = True

        build_contact_form_ui(
            self,
            default_type=default_type,
            show_cancel_button=show_cancel_button,
        )

    def eventFilter(self, watched, event):
        message_edit = getattr(self, "message_edit", None)
        if (
            message_edit is not None
            and watched is message_edit
            and event.type() == QEvent.Type.KeyPress
        ):
            key_event = cast(QKeyEvent, event)
            if key_event.matches(QKeySequence.StandardKey.Paste):
                if self._handle_clipboard_image():
                    return True
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_random_ip_user_id_hint()
        if self._manage_polling:
            self.start_status_polling()

    def hideEvent(self, event):
        if self._manage_polling:
            self.stop_status_polling()
        self._set_status_loading(False)
        super().hideEvent(event)

    def closeEvent(self, event):
        
        if self.has_pending_async_work():
            event.ignore()
            self.show_pending_async_warning()
            return
        self.stop_status_polling()
        self._stop_activity_indicators()

        
        self._close_all_infobars()
        super().closeEvent(event)

    def __del__(self):
        
        try:
            self.stop_status_polling()
        except Exception:
            pass

    def _close_all_infobars(self):
        close_all_infobars(self)

    @staticmethod
    def _info_bar():
        return InfoBar

    @staticmethod
    def _message_box():
        return MessageBox

    @staticmethod
    def _qtimer():
        return QTimer

    @staticmethod
    def _set_progress_ring_active(widget: QWidget, active: bool) -> None:
        set_indeterminate_progress_ring_active(widget, active)

    @staticmethod
    def _get_session_snapshot() -> dict[str, Any]:
        return get_session_snapshot()

    @staticmethod
    def _contact_api_url() -> str:
        return CONTACT_API_URL

    @staticmethod
    def _contact_http_post(*args, **kwargs):
        return ContactForm.http_post(*args, **kwargs)

    @staticmethod
    def _app_version() -> str:
        return __VERSION__

    @staticmethod
    def _build_contact_message(**kwargs) -> str:
        return build_contact_message(**kwargs)

    @staticmethod
    def _build_contact_request_fields(**kwargs):
        return build_contact_request_fields(**kwargs)

    def has_pending_async_work(self) -> bool:
        return has_pending_async_work(self)

    def show_pending_async_warning(self) -> None:
        show_pending_async_warning(self)

    def _set_status_loading(self, loading: bool) -> None:
        set_status_loading(self, loading)

    def _set_send_loading(self, loading: bool) -> None:
        set_send_loading(self, loading)

    def _stop_activity_indicators(self) -> None:
        stop_activity_indicators(self)

    def refresh_random_ip_user_id_hint(self) -> None:
        refresh_random_ip_user_id_hint(self)

    def start_status_polling(self):
        start_status_polling(self)

    def stop_status_polling(self):
        stop_status_polling(self)

    def _on_type_changed(self):
        on_type_changed(self)

    def _sync_message_type_lock_state(self) -> None:
        sync_message_type_lock_state(self)

    def _is_bug_report_type(self, message_type: Optional[str]) -> bool:
        return (message_type or "").strip() == "报错反馈"

    def _reset_bug_report_auto_attach_defaults(self) -> None:
        self.auto_attach_config_checkbox.setChecked(self._auto_attach_config_default)
        self.auto_attach_log_checkbox.setChecked(self._auto_attach_log_default)

    def _update_send_button_state(self) -> None:
        update_send_button_state(self)

    def _on_context_paste(self, target: QWidget) -> bool:
        return on_context_paste(self, target)

    def _attachments_enabled(self) -> bool:
        return attachments_enabled(self)

    def _render_attachments_ui(self):
        render_attachments_ui(self)

    def _remove_attachment(self, index: int):
        remove_attachment(self, index)

    def _on_clear_attachments(self):
        clear_attachments(self)

    def _handle_clipboard_image(self) -> bool:
        return handle_clipboard_image(self)

    def _on_choose_files(self):
        choose_files(self)

    def _on_status_loaded(self, text: str, color: str):
        try:
            self._set_status_loading(False)
            self.status_icon.show()
            if color.lower() == "#228b22":
                self.status_icon.setIcon(FluentIcon.ACCEPT)
            elif color.lower() == "#cc0000":
                self.status_icon.setIcon(FluentIcon.REMOVE_FROM)
            else:
                self.status_icon.setIcon(FluentIcon.INFO)
            self.online_label.setText(text)
            self.online_label.setStyleSheet(f"color:{color};")
        except RuntimeError as exc:
            log_suppressed_exception(
                "_on_status_loaded: self.status_spinner.hide()",
                exc,
                level=logging.WARNING,
            )

    def _cleanup_pending_temp_files(self) -> None:
        self._pending_temp_attachment_paths = cleanup_pending_temp_files(
            list(getattr(self, "_pending_temp_attachment_paths", [])),
            on_error=lambda path, exc: log_suppressed_exception(
                f"_cleanup_pending_temp_files: {path}",
                exc,
                level=logging.WARNING,
            ),
        )

    @staticmethod
    def _read_file_bytes(path: str) -> bytes:
        return read_file_bytes(path)

    @staticmethod
    def _remove_temp_file(path: str) -> None:
        remove_temp_file(
            path,
            on_error=lambda current_path, exc: log_suppressed_exception(
                f"_remove_temp_file: {current_path}",
                exc,
                level=logging.WARNING,
            ),
        )

    def _export_bug_report_config_snapshot(
        self,
    ) -> tuple[str, tuple[str, bytes, str]]:
        provider = getattr(self, "_config_snapshot_provider", None)
        if not callable(provider):
            host = self._find_controller_host()
            provider = (
                getattr(host, "_collect_current_config_snapshot", None)
                if host is not None
                else None
            )
        if not callable(provider):
            raise ValueError("当前窗口没有可导出的运行时配置")
        config_snapshot = cast(RuntimeConfig, provider())
        if config_snapshot is None:
            raise ValueError("当前运行时配置为空，无法导出")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"bug_report_config_{timestamp}.json"
        path = os.path.join(tempfile.gettempdir(), file_name)
        try:
            save_config(config_snapshot, path)
            data = self._read_file_bytes(path)
        finally:
            self._remove_temp_file(path)
        return "配置快照", (file_name, data, "application/json")

    def _export_bug_report_log_snapshot(
        self,
    ) -> tuple[str, tuple[str, bytes, str]]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"bug_report_log_{timestamp}.txt"
        path = os.path.join(tempfile.gettempdir(), file_name)
        try:
            export_full_log_to_file(
                get_user_local_data_root(),
                path,
                fallback_records=LOG_BUFFER_HANDLER.get_records(),
            )
            data = self._read_file_bytes(path)
        finally:
            self._remove_temp_file(path)
        return "日志快照", (file_name, data, "text/plain")

    @staticmethod
    def _fatal_crash_log_payload() -> Optional[tuple[str, tuple[str, bytes, str]]]:
        return fatal_crash_log_payload(get_fatal_crash_log_path())

    @staticmethod
    def _renumber_files_payload(
        items: list[tuple[str, tuple[str, bytes, str]]],
    ) -> list[tuple[str, tuple[str, bytes, str]]]:
        return renumber_files_payload(items)

    def _build_bug_report_auto_files_payload(
        self,
    ) -> tuple[list[tuple[str, tuple[str, bytes, str]]], list[str]]:
        return build_bug_report_auto_files_payload(
            auto_attach_config=self.auto_attach_config_checkbox.isChecked(),
            auto_attach_log=self.auto_attach_log_checkbox.isChecked(),
            export_config_snapshot=self._export_bug_report_config_snapshot,
            export_log_snapshot=self._export_bug_report_log_snapshot,
            get_fatal_payload=self._fatal_crash_log_payload,
        )

    def _validate_email(self, email: str) -> bool:
        return validate_email(email)

    def _on_send_clicked(self):
        on_send_clicked(self)

    def _emit_send_finished_if_current(
        self,
        generation: int,
        success: bool,
        message: str,
    ) -> None:
        emit_send_finished_if_current(self, generation, success, message)

    def _finish_stuck_send_if_needed(self, generation: int) -> None:
        finish_stuck_send_if_needed(self, generation)

    def _compute_send_timeout_fallback_ms(self, read_timeout_seconds: int) -> int:
        return compute_send_timeout_fallback_ms_for_form(self, read_timeout_seconds)

    def _clear_email_selection(self):
        clear_email_selection(self)

    def _focus_send_button(self):
        focus_send_button(self)

    @Slot(bool, str)
    def _on_send_finished(self, success: bool, error_msg: str):
        on_send_finished(self, success, error_msg)

    def _find_controller_host(self) -> Optional[QWidget]:
        return find_controller_host(self)

