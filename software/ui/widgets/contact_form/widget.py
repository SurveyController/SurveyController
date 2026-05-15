"""联系开发者表单组件，可嵌入页面或对话框。"""

import logging
import os
import tempfile
import threading
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Optional, cast

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, Signal, Slot
from PySide6.QtGui import (
    QKeyEvent,
    QKeySequence,
)
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    MessageBox,
)

from software.app.config import (
    CONTACT_API_URL,
    EMAIL_VERIFY_ENDPOINT,
)
from software.app.user_paths import get_fatal_crash_log_path, get_user_local_data_root
from software.app.version import __VERSION__
from software.io.config import RuntimeConfig, save_config
from software.logging.log_utils import (
    LOG_BUFFER_HANDLER,
    export_full_log_to_file,
    log_suppressed_exception,
)
from software.ui.helpers.contact_api import (
    get_session_snapshot,
    post as http_post,
)
from software.ui.helpers.image_attachments import ImageAttachmentManager
from software.ui.helpers.qfluent_compat import (
    set_indeterminate_progress_ring_active,
)

from .attachments import (
    build_bug_report_auto_files_payload,
    cleanup_pending_temp_files,
    fatal_crash_log_payload,
    read_file_bytes,
    remove_temp_file,
    renumber_files_payload,
)
from .message_builder import build_contact_message, build_contact_request_fields
from .rules import (
    clamp_quantity_text,
    get_allowed_amount_options,
    get_minimum_allowed_amount,
    is_amount_allowed,
    normalize_quantity_text,
    parse_amount_value,
    parse_quantity_value,
)
from .send_workflow import (
    QuotaRequestValidationInputs,
    compute_send_timeout_fallback_ms,
    validate_email,
    validate_quota_request,
)
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
from .constants import (
    MAX_REQUEST_QUOTA,
    REQUEST_MESSAGE_TYPE,
)


class ContactForm(StatusPollingMixin, QWidget):
    """联系开发者表单，负责消息发送、状态轮询和附件处理。"""

    type_label_static: Any
    type_combo: Any
    type_locked_label: Any
    base_options: Any
    email_label: Any
    email_edit: Any
    verify_code_edit: Any
    send_verify_btn: Any
    verify_send_spinner: Any
    issue_title_label: Any
    issue_title_edit: Any
    amount_row: Any
    amount_label: Any
    amount_edit: Any
    quantity_label: Any
    quantity_edit: Any
    urgency_label: Any
    urgency_combo: Any
    amount_rule_hint: Any
    amount_rule_hint_icon: Any
    amount_rule_hint_text: Any
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
    request_payment_section: Any
    payment_method_label: Any
    payment_method_group: Any
    payment_method_wechat_radio: Any
    payment_method_alipay_radio: Any
    request_payment_confirm_section: Any
    donated_cb: Any
    open_donate_btn: Any
    status_spinner: Any
    status_icon: Any
    online_label: Any
    cancel_btn: Any
    send_btn: Any
    send_spinner: Any

    _statusLoaded = Signal(str, str)  # text, color
    _sendFinished = Signal(bool, str)  # success, message
    _verifyCodeFinished = Signal(bool, str, str)  # success, message, email

    sendSucceeded = Signal()
    quotaRequestSucceeded = Signal()
    cancelRequested = Signal()

    _SEND_TIMEOUT_GRACE_MS = 2_000
    _SEND_CONNECT_TIMEOUT_SECONDS = 10
    _SEND_READ_TIMEOUT_SECONDS = 10
    _SEND_READ_TIMEOUT_WITH_FILES_SECONDS = 20

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
        self._verifyCodeFinished.connect(
            self._on_verify_code_finished, Qt.ConnectionType.QueuedConnection
        )
        self._init_status_polling(status_endpoint, status_formatter)
        self._attachments = ImageAttachmentManager(max_count=3, max_size_bytes=10 * 1024 * 1024)
        self._current_message_type: str = ""
        self._current_has_email: bool = False
        self._send_in_progress: bool = False
        self._send_generation: int = 0
        self._send_finished_generation: int = 0
        self._send_state_lock = threading.Lock()
        self._verify_code_requested: bool = False
        self._verify_code_requested_email: str = ""
        self._verify_code_sending: bool = False
        self._cooldown_timer: Optional[QTimer] = None
        self._cooldown_remaining: int = 0
        self._polling_started = False
        self._auto_clear_on_success = auto_clear_on_success
        self._manage_polling = manage_polling
        self._lock_message_type = lock_message_type
        self._config_snapshot_provider = config_snapshot_provider
        self._random_ip_user_id: int = 0
        self._last_valid_quantity_text: str = ""
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
        donated_cb = getattr(self, "donated_cb", None)
        if (
            message_edit is not None
            and watched is message_edit
            and event.type() == QEvent.Type.KeyPress
        ):
            key_event = cast(QKeyEvent, event)
            if key_event.matches(QKeySequence.StandardKey.Paste):
                if self._handle_clipboard_image():
                    return True
        if donated_cb is not None and watched is donated_cb:
            block_reason = self._get_donation_check_block_reason()
            if block_reason and not donated_cb.isChecked():
                if event.type() == QEvent.Type.MouseButtonPress:
                    InfoBar.warning(
                        "",
                        block_reason,
                        parent=self,
                        position=InfoBarPosition.TOP,
                        duration=2600,
                    )
                    return True
                if event.type() == QEvent.Type.KeyPress:
                    key_event = cast(QKeyEvent, event)
                    if key_event.key() in (
                        Qt.Key.Key_Space,
                        Qt.Key.Key_Return,
                        Qt.Key.Key_Enter,
                        Qt.Key.Key_Select,
                    ):
                        InfoBar.warning(
                            "",
                            block_reason,
                            parent=self,
                            position=InfoBarPosition.TOP,
                            duration=2600,
                        )
                        return True
        if watched is self.amount_edit and event.type() == QEvent.Type.FocusOut:
            self._normalize_amount_if_needed()
        return super().eventFilter(watched, event)

    def _selected_payment_method(self) -> str:
        checked_button = self.payment_method_group.checkedButton()
        return checked_button.text() if checked_button is not None else ""

    def _clear_payment_method_selection(self) -> None:
        was_exclusive = self.payment_method_group.exclusive()
        self.payment_method_group.setExclusive(False)
        try:
            for button in self.payment_method_group.buttons():
                button.setChecked(False)
        finally:
            self.payment_method_group.setExclusive(was_exclusive)

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
        """关闭事件：停止轮询并清理界面状态。"""
        if self.has_pending_async_work():
            event.ignore()
            self.show_pending_async_warning()
            return
        self.stop_status_polling()
        self._stop_cooldown()
        self._stop_activity_indicators()

        # 关闭所有可能存在的 InfoBar，避免其内部线程导致崩溃
        self._close_all_infobars()
        super().closeEvent(event)

    def __del__(self):
        """析构函数：确保轮询请求被清理"""
        try:
            self.stop_status_polling()
        except Exception:
            pass

    def _close_all_infobars(self):
        """关闭所有子 InfoBar 组件，避免线程泄漏"""
        try:
            from qfluentwidgets import InfoBar

            # 遍历所有子组件，找到 InfoBar 并关闭
            for child in self.findChildren(InfoBar):
                try:
                    child.close()
                    child.deleteLater()
                except Exception:
                    pass
        except Exception as exc:
            log_suppressed_exception("_close_all_infobars", exc, level=logging.WARNING)
        finally:
            self.amount_rule_hint.hide()

    def has_pending_async_work(self) -> bool:
        return bool(self._send_in_progress or self._verify_code_sending)

    def show_pending_async_warning(self) -> None:
        if self._send_in_progress:
            message = "正在发送反馈，请等待完成后再关闭"
        elif self._verify_code_sending:
            message = "正在发送验证码，请等待完成后再关闭"
        else:
            return
        InfoBar.warning(
            "",
            message,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=2500,
        )

    def _set_status_loading(self, loading: bool) -> None:
        set_indeterminate_progress_ring_active(self.status_spinner, loading)

    def _set_send_loading(self, loading: bool) -> None:
        set_indeterminate_progress_ring_active(self.send_spinner, loading)

    def _set_verify_loading(self, loading: bool) -> None:
        set_indeterminate_progress_ring_active(self.verify_send_spinner, loading)

    def _stop_activity_indicators(self) -> None:
        self._set_status_loading(False)
        self._set_send_loading(False)
        self._set_verify_loading(False)

    def refresh_random_ip_user_id_hint(self) -> None:
        """刷新消息框下方的随机IP账号提示。"""
        try:
            snapshot = get_session_snapshot()
        except Exception as exc:
            log_suppressed_exception("refresh_random_ip_user_id_hint", exc, level=logging.WARNING)
            snapshot = {}
        user_id = int(snapshot.get("user_id") or 0)
        self._random_ip_user_id = user_id
        if user_id > 0:
            self.random_ip_user_id_label.setText(f"随机IP用户ID：{user_id}")
            self.random_ip_user_id_label.show()
        else:
            self.random_ip_user_id_label.hide()
        self._sync_donation_check_state()
        self._update_send_button_state()

    def start_status_polling(self):
        if self._polling_started:
            return
        self._polling_started = True
        self._set_status_loading(True)
        self.status_icon.hide()
        self.online_label.setText("作者当前在线状态：查询中...")
        self.online_label.setStyleSheet("color:#BA8303;")
        self._start_status_polling()

    def stop_status_polling(self):
        if not self._polling_started:
            return
        self._polling_started = False
        self._stop_status_polling()
        self._set_status_loading(False)

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

    def _parse_quantity_value(self, text: Optional[str] = None) -> Optional[Decimal]:
        return parse_quantity_value(self.quantity_edit.text() if text is None else text)

    def _normalize_quantity_text(self, text: str) -> str:
        return normalize_quantity_text(text)

    def _normalize_quantity_if_needed(self) -> None:
        raw_text = (self.quantity_edit.text() or "").strip()
        if not raw_text:
            return
        normalized_text = clamp_quantity_text(raw_text, self._last_valid_quantity_text)
        if normalized_text == raw_text:
            return
        self.quantity_edit.blockSignals(True)
        try:
            self.quantity_edit.setText(normalized_text)
        finally:
            self.quantity_edit.blockSignals(False)

    def _parse_amount_value(self, text: Optional[str] = None) -> Optional[Decimal]:
        return parse_amount_value(self.amount_edit.currentText() if text is None else text)

    def _get_donation_check_block_reason(self) -> str:
        current_type = self.type_combo.currentText() or ""
        if current_type != REQUEST_MESSAGE_TYPE:
            return ""
        if not self._selected_payment_method():
            return "请先选择你刚刚使用的支付方式（微信或支付宝）。"
        amount_text = (self.amount_edit.currentText() or "").strip()
        if not amount_text:
            return "请先填写支付金额后，再勾选“我已完成支付，且确认随机ip可用”。"
        if self._random_ip_user_id > 0:
            return ""
        return (
            "你还没有成功使用过随机IP，暂时不能勾选。"
            "请先启用并实际跑通一次随机IP，确认能正常用，再来申请。"
        )

    def _sync_donation_check_state(self) -> None:
        if not hasattr(self, "donated_cb"):
            return
        if self._get_donation_check_block_reason() and self.donated_cb.isChecked():
            previous_block_state = self.donated_cb.blockSignals(True)
            try:
                self.donated_cb.setChecked(False)
            finally:
                self.donated_cb.blockSignals(previous_block_state)

    def _open_donate_page(self) -> None:
        widget: Optional[QWidget] = cast(QWidget, self)
        while widget is not None:
            if hasattr(widget, "_get_donate_page") and hasattr(widget, "_switch_to_more_page"):
                try:
                    host = cast(Any, widget)
                    donate_page = host._get_donate_page()
                    host._switch_to_more_page(donate_page)
                    top_level = self.window()
                    if top_level is not None and top_level is not widget:
                        top_level.close()
                    return
                except Exception as exc:
                    log_suppressed_exception("_open_donate_page", exc, level=logging.WARNING)
                    break
            widget = widget.parentWidget()
        InfoBar.warning(
            "",
            "暂时打不开支付页，请从“更多 -> 捐助”进入",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=2500,
        )

    def _on_amount_changed(self, text: str):
        _ = text
        self._sync_amount_rule_warning()
        self._sync_donation_check_state()
        self._update_send_button_state()

    def _normalize_amount_if_needed(self) -> None:
        text = (self.amount_edit.currentText() or "").strip()
        if not text:
            return
        try:
            value = float(text)
        except ValueError:
            return
        if value == 0.0 and text != "0.01":
            self.amount_edit.setText("0.01")

    def _on_amount_editing_finished(self):
        self._normalize_amount_if_needed()
        self._sync_amount_rule_warning()

    def _on_quantity_changed(self, text: str):
        normalized_text = (text or "").strip()
        if not normalized_text:
            self._last_valid_quantity_text = ""
        else:
            quantity = self._parse_quantity_value(normalized_text)
            if quantity is not None and quantity <= Decimal(str(MAX_REQUEST_QUOTA)):
                self._last_valid_quantity_text = self._normalize_quantity_text(normalized_text)
            elif quantity is not None and quantity > Decimal(str(MAX_REQUEST_QUOTA)):
                self.quantity_edit.blockSignals(True)
                try:
                    self.quantity_edit.setText(self._last_valid_quantity_text)
                finally:
                    self.quantity_edit.blockSignals(False)
                return
        self._refresh_amount_options()
        self._sync_amount_rule_warning()

    def _on_quantity_editing_finished(self):
        self._normalize_quantity_if_needed()
        self._refresh_amount_options()
        self._sync_amount_rule_warning()

    def _on_urgency_changed(self):
        return

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

    def _get_minimum_allowed_amount(self, quantity: Decimal) -> Optional[Decimal]:
        return get_minimum_allowed_amount(quantity)

    def _get_allowed_amount_options(self, quantity: Decimal) -> list[str]:
        return get_allowed_amount_options(quantity)

    def _is_amount_allowed(self, amount_text: str, quantity_text: Optional[str] = None) -> bool:
        current_quantity_text = self.quantity_edit.text() if quantity_text is None else quantity_text
        return is_amount_allowed(amount_text, current_quantity_text)

    def _refresh_amount_options(self) -> None:
        current_text = (self.amount_edit.currentText() or "").strip()
        allowed_amounts = self._get_allowed_amount_options(
            self._parse_quantity_value() or Decimal("0")
        )

        previous_block_state = self.amount_edit.blockSignals(True)
        try:
            self.amount_edit.clear()
            for amount in allowed_amounts:
                self.amount_edit.addItem(amount)
            if not current_text:
                self.amount_edit._currentIndex = -1
                self.amount_edit.setText("")
            else:
                current_index = self.amount_edit.findText(current_text)
                if current_index >= 0:
                    self.amount_edit.setCurrentIndex(current_index)
                else:
                    self.amount_edit._currentIndex = -1
                    self.amount_edit.setText(current_text)
        finally:
            self.amount_edit.blockSignals(previous_block_state)

    def _show_amount_rule_infobar(self) -> None:
        self.amount_rule_hint.show()

    def _close_amount_rule_infobar(self) -> None:
        self.amount_rule_hint.hide()

    def _sync_amount_rule_warning(self) -> None:
        current_type = self.type_combo.currentText() or ""
        amount_text = (self.amount_edit.currentText() or "").strip()
        if current_type != REQUEST_MESSAGE_TYPE or not amount_text:
            self._close_amount_rule_infobar()
            return
        if self._is_amount_allowed(amount_text):
            self._close_amount_rule_infobar()
            return
        self._show_amount_rule_infobar()

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
        self._cleanup_pending_temp_files()
        email = (self.email_edit.text() or "").strip()
        self._current_has_email = bool(email)

        timer_context = cast(QWidget, self)
        QTimer.singleShot(10, timer_context, self._clear_email_selection)
        QTimer.singleShot(10, timer_context, self._focus_send_button)

        mtype = self.type_combo.currentText() or "报错反馈"
        issue_title = (self.issue_title_edit.text() or "").strip()

        request_amount_text = ""
        request_quota_text = ""
        request_urgency_text = ""
        request_payment_method = ""
        if mtype == REQUEST_MESSAGE_TYPE:
            self._normalize_amount_if_needed()
            self._normalize_quantity_if_needed()
            amount_text = (self.amount_edit.currentText() or "").strip()
            quantity_text = (self.quantity_edit.text() or "").strip()
            verify_code = (self.verify_code_edit.text() or "").strip()
            request_payment_method = self._selected_payment_method()
            request_amount_text = amount_text
            request_urgency_text = (self.urgency_combo.currentText() or "").strip()
            quota_validation = validate_quota_request(
                QuotaRequestValidationInputs(
                    email=email,
                    amount_text=amount_text,
                    quantity_text=quantity_text,
                    verify_code=verify_code,
                    payment_method=request_payment_method,
                    donated=self.donated_cb.isChecked(),
                    verify_code_requested=self._verify_code_requested,
                    verify_code_requested_email=self._verify_code_requested_email,
                )
            )
            request_quota_text = quota_validation.normalized_quota_text
            if quota_validation.error_message:
                if quota_validation.amount_rule_blocked:
                    self._show_amount_rule_infobar()
                if quota_validation.error_message in {
                    "请选择你刚刚使用的支付方式",
                    "请先勾选“我已完成支付”后再发送申请",
                }:
                    self._update_send_button_state()
                InfoBar.warning(
                    "",
                    quota_validation.error_message,
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2200,
                )
                return

        message = (self.message_edit.toPlainText() or "").strip()
        if not message and mtype != REQUEST_MESSAGE_TYPE:
            InfoBar.warning(
                "",
                "请输入消息内容",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000,
            )
            return

        if mtype == REQUEST_MESSAGE_TYPE and not email:
            InfoBar.warning(
                "",
                "额度申请必须填写邮箱地址",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000,
            )
            return

        if email and not self._validate_email(email):
            InfoBar.warning(
                "",
                "邮箱格式不正确",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000,
            )
            return

        self.refresh_random_ip_user_id_hint()
        if mtype == REQUEST_MESSAGE_TYPE and self._random_ip_user_id <= 0:
            InfoBar.warning(
                "",
                "暂时还不能申请额度。请先小测试一两份，确认能正常提交成功后，再来申请额度。",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3500,
            )
            return

        if mtype == REQUEST_MESSAGE_TYPE:
            confirm_email_box = MessageBox(
                "确认邮箱地址",
                f"当前输入的邮箱地址是：{email}\n\n请确认邮箱地址正确无误。开发者会在2小时内发放额度并通过邮件通知",
                self.window() or self,
            )
            confirm_email_box.yesButton.setText("确认发送")
            confirm_email_box.cancelButton.setText("返回检查")
            if not confirm_email_box.exec():
                return

        if mtype != REQUEST_MESSAGE_TYPE and not email:
            confirm_box = MessageBox(
                "未填写邮箱",
                "当前未输入邮箱地址，开发者可能无法联系你回复处理进度。是否继续发送？",
                self.window() or self,
            )
            confirm_box.yesButton.setText("继续发送")
            confirm_box.cancelButton.setText("返回填写")
            if not confirm_box.exec():
                return

        full_message = build_contact_message(
            version_str=__VERSION__,
            message_type=mtype,
            issue_title=issue_title,
            email=email,
            donated=self.donated_cb.isChecked(),
            random_ip_user_id=self._random_ip_user_id,
            message=message,
            request_payment_method=request_payment_method,
            request_amount_text=request_amount_text,
            request_quota_text=request_quota_text,
            request_urgency_text=request_urgency_text,
        )

        if not CONTACT_API_URL:
            InfoBar.error(
                "",
                "联系API未配置",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )
            return

        manual_files_payload = (
            [] if mtype == REQUEST_MESSAGE_TYPE else self._attachments.files_payload()
        )
        auto_files_payload: list[tuple[str, tuple[str, bytes, str]]] = []
        if self._is_bug_report_type(mtype):
            try:
                auto_files_payload, _ = self._build_bug_report_auto_files_payload()
            except Exception as exc:
                self._cleanup_pending_temp_files()
                InfoBar.error(
                    "",
                    f"自动导出附件失败：{exc}",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3500,
                )
                return
        payload = {
            "message": full_message,
            "timestamp": datetime.now().isoformat(),
        }
        files_payload = self._renumber_files_payload(manual_files_payload + auto_files_payload)

        self.send_btn.setFocus()
        self.send_btn.setEnabled(False)
        self.send_btn.setText("发送中...")
        self._send_in_progress = True
        self._set_send_loading(True)
        self._update_send_button_state()
        self._current_message_type = mtype
        with self._send_state_lock:
            self._send_generation += 1
            send_generation = self._send_generation
        def _send():
            try:
                multipart_fields = build_contact_request_fields(
                    message=payload["message"],
                    message_type=mtype,
                    issue_title=issue_title,
                    timestamp=payload["timestamp"],
                    random_ip_user_id=self._random_ip_user_id,
                    files_payload=files_payload,
                )
                read_timeout_seconds = (
                    self._SEND_READ_TIMEOUT_WITH_FILES_SECONDS
                    if files_payload
                    else self._SEND_READ_TIMEOUT_SECONDS
                )
                resp = http_post(
                    CONTACT_API_URL,
                    files=multipart_fields,
                    timeout=(self._SEND_CONNECT_TIMEOUT_SECONDS, read_timeout_seconds),
                )
                if resp.status_code == 200:
                    self._emit_send_finished_if_current(send_generation, True, "")
                else:
                    self._emit_send_finished_if_current(
                        send_generation,
                        False,
                        f"发送失败：{resp.status_code}",
                    )
            except Exception as exc:
                self._emit_send_finished_if_current(
                    send_generation,
                    False,
                    f"发送失败：{exc}",
                )

        send_timeout_fallback_ms = self._compute_send_timeout_fallback_ms(
            self._SEND_READ_TIMEOUT_WITH_FILES_SECONDS
            if files_payload
            else self._SEND_READ_TIMEOUT_SECONDS
        )
        QTimer.singleShot(
            send_timeout_fallback_ms,
            cast(QWidget, self),
            lambda generation=send_generation: self._finish_stuck_send_if_needed(generation),
        )

        threading.Thread(target=_send, daemon=True).start()

    def _emit_send_finished_if_current(
        self,
        generation: int,
        success: bool,
        message: str,
    ) -> None:
        with self._send_state_lock:
            if generation != getattr(self, "_send_generation", 0):
                return
            if generation == getattr(self, "_send_finished_generation", 0):
                return
            if not getattr(self, "_send_in_progress", False):
                return
            self._send_finished_generation = generation
        self._sendFinished.emit(success, message)

    def _finish_stuck_send_if_needed(self, generation: int) -> None:
        self._emit_send_finished_if_current(generation, False, "发送超时，请稍后重试")

    def _compute_send_timeout_fallback_ms(self, read_timeout_seconds: int) -> int:
        return compute_send_timeout_fallback_ms(
            connect_timeout_seconds=self._SEND_CONNECT_TIMEOUT_SECONDS,
            read_timeout_seconds=read_timeout_seconds,
            grace_ms=self._SEND_TIMEOUT_GRACE_MS,
        )

    def _clear_email_selection(self):
        try:
            self.email_edit.setSelection(0, 0)
        except (RuntimeError, AttributeError) as exc:
            log_suppressed_exception(
                "_clear_email_selection: self.email_edit.setSelection(0, 0)",
                exc,
                level=logging.WARNING,
            )

    def _focus_send_button(self):
        try:
            self.send_btn.setFocus()
        except (RuntimeError, AttributeError) as exc:
            log_suppressed_exception(
                "_focus_send_button: self.send_btn.setFocus()",
                exc,
                level=logging.WARNING,
            )

    @Slot(bool, str)
    def _on_send_finished(self, success: bool, error_msg: str):
        self._send_in_progress = False
        self._set_send_loading(False)
        self.send_btn.setText("发送")
        self._update_send_button_state()
        self._cleanup_pending_temp_files()

        if success:
            current_type = getattr(self, "_current_message_type", "")
            msg = (
                "申请已提交，请等待人工处理"
                if current_type == REQUEST_MESSAGE_TYPE
                else "消息已发送"
            )
            if getattr(self, "_current_has_email", False):
                msg += "，开发者会优先通过邮箱联系你"
            InfoBar.success(
                "",
                msg,
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2500,
            )
            if current_type == REQUEST_MESSAGE_TYPE:
                self.quotaRequestSucceeded.emit()
            if self._auto_clear_on_success:
                self._close_amount_rule_infobar()
                self.amount_edit.setText("")
                self.quantity_edit.clear()
                self.verify_code_edit.clear()
                self._clear_payment_method_selection()
                self._verify_code_requested = False
                self._verify_code_requested_email = ""
                urgency_default_index = self.urgency_combo.findText("中")
                if urgency_default_index >= 0:
                    self.urgency_combo.setCurrentIndex(urgency_default_index)
                self.message_edit.clear()
                self.issue_title_edit.clear()
                self._attachments.clear()
                self._render_attachments_ui()
                self._reset_bug_report_auto_attach_defaults()
            self.sendSucceeded.emit()
        else:
            InfoBar.error(
                "",
                error_msg,
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )

    def _find_controller_host(self) -> Optional[QWidget]:
        widget: Optional[QWidget] = cast(QWidget, self)
        while widget is not None:
            if hasattr(widget, "controller"):
                return widget
            widget = widget.parentWidget()
        win = self.window()
        if isinstance(win, QWidget) and hasattr(win, "controller"):
            return win
        return None

    def _set_verify_code_sending(self, sending: bool):
        self._verify_code_sending = sending
        self.send_verify_btn.setEnabled(not sending)
        self.send_verify_btn.setText("发送中..." if sending else "发送验证码")
        self._set_verify_loading(sending)

    def _start_cooldown(self):
        self._cooldown_remaining = 30
        self.send_verify_btn.setEnabled(False)
        self.send_verify_btn.setText(f"重新发送({self._cooldown_remaining}s)")
        self._cooldown_timer = QTimer(cast(QObject, self))
        self._cooldown_timer.setInterval(1000)
        self._cooldown_timer.timeout.connect(self._on_cooldown_tick)
        self._cooldown_timer.start()

    def _on_cooldown_tick(self):
        self._cooldown_remaining -= 1
        if self._cooldown_remaining <= 0:
            if self._cooldown_timer is not None:
                self._cooldown_timer.stop()
            self._cooldown_timer = None
            self.send_verify_btn.setEnabled(True)
            self.send_verify_btn.setText("发送验证码")
        else:
            self.send_verify_btn.setText(f"重新发送({self._cooldown_remaining}s)")

    def _stop_cooldown(self):
        if self._cooldown_timer is not None:
            self._cooldown_timer.stop()
            self._cooldown_timer = None
        self._cooldown_remaining = 0
        self.send_verify_btn.setEnabled(True)
        self.send_verify_btn.setText("发送验证码")

    def _on_send_verify_clicked(self):
        if self._verify_code_sending:
            return

        email = (self.email_edit.text() or "").strip()
        if not email:
            InfoBar.warning(
                "",
                "请先填写邮箱地址",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000,
            )
            return
        if not self._validate_email(email):
            InfoBar.warning(
                "",
                "邮箱格式不正确，请先检查",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000,
            )
            return

        if not EMAIL_VERIFY_ENDPOINT:
            InfoBar.error(
                "",
                "验证码接口未配置",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2500,
            )
            return

        self._verify_code_requested = False
        self._verify_code_requested_email = ""
        self._set_verify_code_sending(True)

        def _send_verify():
            try:
                resp = http_post(
                    EMAIL_VERIFY_ENDPOINT,
                    headers={"Content-Type": "application/json"},
                    json={"email": email},
                    timeout=10,
                )
                try:
                    data = resp.json()
                except Exception:
                    data = None

                if resp.status_code == 200 and isinstance(data, dict) and bool(data.get("ok")):
                    self._verifyCodeFinished.emit(True, "", email)
                    return

                if isinstance(data, dict):
                    error_msg = str(data.get("error") or f"发送失败：{resp.status_code}")
                else:
                    error_msg = f"发送失败：{resp.status_code}"
                self._verifyCodeFinished.emit(False, error_msg, email)
            except Exception as exc:
                self._verifyCodeFinished.emit(False, f"发送失败：{exc}", email)

        threading.Thread(target=_send_verify, daemon=True).start()

    @Slot(bool, str, str)
    def _on_verify_code_finished(self, success: bool, error_msg: str, email: str):
        self._set_verify_code_sending(False)

        if success:
            self._verify_code_requested = True
            self._verify_code_requested_email = email
            InfoBar.success(
                "",
                "验证码已发送，请查收并输入验证码",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2200,
            )
            self._start_cooldown()
            return

        self._verify_code_requested = False
        self._verify_code_requested_email = ""
        normalized = (error_msg or "").strip().lower()
        if normalized == "invalid request":
            ui_msg = "邮箱参数无效，请检查邮箱后重试"
        elif normalized == "send mail failed":
            ui_msg = "邮件发送失败，请稍后重试"
        else:
            ui_msg = error_msg or "验证码发送失败，请稍后重试"
        InfoBar.error(
            "",
            ui_msg,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=2500,
        )
