"""联系开发者表单组件，可嵌入页面或对话框。"""

import json
import logging
import os
import re
import tempfile
import threading
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional, cast

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import (
    QDoubleValidator,
    QGuiApplication,
    QIntValidator,
    QKeyEvent,
    QKeySequence,
)
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CheckBox,
    ComboBox,
    EditableComboBox,
    FluentIcon,
    IconWidget,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    RadioButton,
    RoundMenu,
)

from software.app.config import (
    CONTACT_API_URL,
    DEFAULT_HTTP_HEADERS,
    EMAIL_VERIFY_ENDPOINT,
    PROXY_STATUS_TIMEOUT_SECONDS,
)
from software.app.user_paths import (
    get_fatal_crash_log_path,
    get_user_local_data_root,
)
from software.app.version import __VERSION__
from software.io.config import RuntimeConfig, save_config
from software.logging.log_utils import (
    LOG_BUFFER_HANDLER,
    export_full_log_to_file,
    log_suppressed_exception,
)
from software.ui.helpers.contact_api import (
    format_quota_value,
    get_session_snapshot,
    post as http_post,
)
from software.ui.helpers.fluent_tooltip import install_tooltip_filters
from software.ui.helpers.image_attachments import ImageAttachmentManager
from software.ui.helpers.qfluent_compat import (
    set_indeterminate_progress_ring_active,
)

from .constants import (
    DONATION_AMOUNT_BLOCK_MESSAGE,
    DONATION_AMOUNT_OPTIONS,
    DONATION_AMOUNT_RULES,
    MAX_REQUEST_QUOTA,
    PAYMENT_METHOD_OPTIONS,
    REQUEST_MESSAGE_TYPE,
    REQUEST_QUOTA_STEP,
)


class PasteOnlyLineEdit(LineEdit):
    """只显示 Fluent 风格“复制 / 粘贴 / 全选”菜单的 LineEdit。"""

    def __init__(self, parent=None, on_paste: Optional[Callable[[QWidget], bool]] = None):
        super().__init__(parent)
        self._on_paste = on_paste

    def contextMenuEvent(self, e):
        menu = RoundMenu(parent=self)
        copy_action = Action(FluentIcon.COPY, "复制", parent=menu)
        copy_action.setEnabled(self.hasSelectedText())
        copy_action.triggered.connect(self.copy)
        paste_action = Action(FluentIcon.PASTE, "粘贴", parent=menu)

        def _do_paste():
            if self._on_paste and self._on_paste(self):
                return
            self.paste()

        menu.addAction(copy_action)
        paste_action.triggered.connect(_do_paste)
        menu.addAction(paste_action)
        menu.exec(e.globalPos())
        e.accept()


class PasteOnlyPlainTextEdit(PlainTextEdit):
    """只显示 Fluent 风格“复制 / 粘贴 / 全选”菜单的 PlainTextEdit。"""

    def __init__(self, parent=None, on_paste: Optional[Callable[[QWidget], bool]] = None):
        super().__init__(parent)
        self._on_paste = on_paste

    def contextMenuEvent(self, e):
        menu = RoundMenu(parent=self)
        copy_action = Action(FluentIcon.COPY, "复制", parent=menu)
        copy_action.setEnabled(self.textCursor().hasSelection())
        copy_action.triggered.connect(self.copy)
        paste_action = Action(FluentIcon.PASTE, "粘贴", parent=menu)

        def _do_paste():
            if self._on_paste and self._on_paste(self):
                return
            self.paste()

        menu.addAction(copy_action)
        paste_action.triggered.connect(_do_paste)
        menu.addAction(paste_action)
        menu.exec(e.globalPos())
        e.accept()


def build_contact_message(
    *,
    version_str: str,
    message_type: str,
    issue_title: str,
    email: str,
    donated: bool,
    random_ip_user_id: int,
    message: str,
    request_payment_method: str,
    request_amount_text: str,
    request_quota_text: str,
    request_urgency_text: str,
) -> str:
    lines = [f"来源：SurveyController v{version_str}", f"类型：{message_type}"]
    if email:
        lines.append(f"联系邮箱： {email}")
    if issue_title and message_type == "报错反馈":
        lines.append(f"反馈标题： {issue_title}")
    if message_type == REQUEST_MESSAGE_TYPE:
        lines.append(f"已支付：{'是' if donated else '否'}")
    if random_ip_user_id > 0:
        lines.append(f"随机IP用户ID：{random_ip_user_id}")
    if message_type == REQUEST_MESSAGE_TYPE:
        lines.extend(
            [
                f"支付方式：{request_payment_method}",
                f"支付金额：￥{request_amount_text}",
                f"申请额度：{request_quota_text}",
                f"紧急程度：{request_urgency_text or '中'}",
                "",
                f"\n补充说明：{message or '未填写'}",
            ]
        )
    else:
        lines.extend(["", f"消息：{message}"])
    return "\n".join(lines)


def build_contact_request_fields(
    *,
    message: str,
    message_type: str,
    issue_title: str,
    timestamp: str,
    random_ip_user_id: int,
    files_payload: list[tuple[str, tuple[str, bytes, str]]],
) -> list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]]:
    fields: list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]] = [
        ("message", (None, message)),
        ("messageType", (None, message_type)),
        ("timestamp", (None, timestamp)),
    ]
    if issue_title:
        fields.append(("issueTitle", (None, issue_title)))
    if random_ip_user_id > 0:
        fields.append(("userId", (None, str(random_ip_user_id))))
    fields.extend(files_payload)
    return fields


class StatusPollingMixin:
    """使用 Qt 异步网络请求轮询在线状态。"""

    _status_endpoint: str
    _status_formatter: Optional[Callable]
    _status_timer: Optional[QTimer]
    _polling_interval: int
    _status_fetch_in_progress: bool
    _status_session_id: int
    _status_manager: Optional[QNetworkAccessManager]
    _status_reply: Optional[QNetworkReply]

    def _init_status_polling(
        self,
        status_endpoint: str = "",
        status_formatter: Optional[Callable] = None,
        interval_ms: int = 5000,
    ):
        self._status_endpoint = (status_endpoint or "").strip()
        self._status_formatter = status_formatter
        self._status_timer = None
        self._polling_interval = interval_ms
        self._status_fetch_in_progress = False
        self._status_session_id = 0
        self._status_manager = None
        self._status_reply = None

        status_signal: Any = getattr(self, "_statusLoaded", None)
        if status_signal is not None:
            status_signal.connect(self._on_status_loaded)

    def _ensure_status_manager(self) -> QNetworkAccessManager:
        if self._status_manager is None:
            self._status_manager = QNetworkAccessManager(self)  # type: ignore[arg-type]
        return self._status_manager

    def _ensure_status_timer(self) -> QTimer:
        if self._status_timer is None:
            self._status_timer = QTimer(self)  # type: ignore[arg-type]
            self._status_timer.setInterval(self._polling_interval)
            self._status_timer.timeout.connect(self._fetch_status_once)
        return self._status_timer

    def _start_status_polling(self):
        if not self._status_endpoint:
            self._emit_status_loaded("未知：状态接口未配置", "#666666")
            return

        self._status_session_id += 1
        self._status_fetch_in_progress = False
        self._abort_status_reply()
        self._fetch_status_once()
        self._ensure_status_timer().start()

    def _fetch_status_once(self):
        if not self._status_endpoint or self._status_fetch_in_progress:
            return
        if self._status_reply is not None and self._status_reply.isRunning():
            return

        request = QNetworkRequest(QUrl(self._status_endpoint))
        for key, value in DEFAULT_HTTP_HEADERS.items():
            request.setRawHeader(str(key).encode("utf-8"), str(value).encode("utf-8"))
        try:
            request.setTransferTimeout(int(PROXY_STATUS_TIMEOUT_SECONDS * 1000))
        except AttributeError:
            pass

        self._status_fetch_in_progress = True
        session_id = self._status_session_id
        reply = self._ensure_status_manager().get(request)
        reply.setProperty("_status_session_id", int(session_id))
        self._status_reply = reply
        reply.finished.connect(self._on_status_reply_finished)

    def _on_status_reply_finished(self):
        sender_callable = getattr(self, "sender", None)
        reply = sender_callable() if callable(sender_callable) else None
        if not isinstance(reply, QNetworkReply):
            return
        session_id = reply.property("_status_session_id")
        try:
            current_session_id = int(session_id)
        except (TypeError, ValueError):
            current_session_id = self._status_session_id
        self._handle_status_reply_finished(current_session_id, reply)

    def _handle_status_reply_finished(self, session_id: int, reply: QNetworkReply):
        is_current_reply = self._status_reply is reply
        if is_current_reply:
            self._status_reply = None
            self._status_fetch_in_progress = False

        text, color = self._parse_status_reply(reply)
        self._release_status_reply(reply)

        if session_id != self._status_session_id:
            return
        self._emit_status_loaded(text, color)

    def _parse_status_reply(self, reply: QNetworkReply) -> tuple[str, str]:
        if reply.error() != QNetworkReply.NetworkError.NoError:
            return "未知：状态获取失败", "#666666"

        status_code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        try:
            parsed_status_code = int(status_code) if status_code is not None else 0
        except (TypeError, ValueError):
            parsed_status_code = 0
        if parsed_status_code >= 400:
            return "未知：状态获取失败", "#666666"

        raw_bytes = bytes(reply.readAll().data())
        if not raw_bytes:
            return "未知：状态未知", "#666666"

        try:
            payload = json.loads(raw_bytes.decode("utf-8", errors="replace"))
        except Exception:
            return "未知：状态未知", "#666666"

        return self._format_status_payload(payload)

    def _format_status_payload(self, payload: Any) -> tuple[str, str]:
        if callable(self._status_formatter):
            try:
                result = self._status_formatter(payload)
                if isinstance(result, tuple) and len(result) >= 2:
                    return str(result[0]), str(result[1])
            except Exception:
                pass

        if isinstance(payload, dict):
            online = payload.get("online", None)
            message = str(payload.get("message") or "").strip()
            if not message:
                if online is True:
                    message = "系统正常运行中"
                elif online is False:
                    message = "系统当前不在线"
                else:
                    message = "状态未知"
            if online is True:
                return f"在线：{message}", "#228B22"
            if online is False:
                return f"离线：{message}", "#cc0000"
            return f"未知：{message}", "#666666"

        return "未知：状态未知", "#666666"

    def _release_status_reply(self, reply: QNetworkReply):
        try:
            reply.finished.disconnect()
        except Exception:
            pass
        try:
            reply.deleteLater()
        except Exception:
            pass

    def _abort_status_reply(self):
        reply = self._status_reply
        self._status_reply = None
        if reply is None:
            return

        try:
            reply.finished.disconnect()
        except Exception:
            pass
        try:
            reply.abort()
        except Exception:
            pass
        try:
            reply.deleteLater()
        except Exception:
            pass

    def _stop_status_polling(self):
        if self._status_timer is not None:
            self._status_timer.stop()

        self._status_session_id += 1
        self._status_fetch_in_progress = False
        self._abort_status_reply()

    def _emit_status_loaded(self, text: str, color: str):
        status_signal: Any = getattr(self, "_statusLoaded", None)
        if status_signal is not None:
            status_signal.emit(text, color)
            return
        self._on_status_loaded(text, color)

    def _on_status_loaded(self, text: str, color: str):
        raise NotImplementedError("子类必须实现 _on_status_loaded 方法")


class ContactForm(StatusPollingMixin, QWidget):
    """联系开发者表单，负责消息发送、状态轮询和附件处理。"""

    _statusLoaded = Signal(str, str)  # text, color
    _sendFinished = Signal(bool, str)  # success, message
    _verifyCodeFinished = Signal(bool, str, str)  # success, message, email

    sendSucceeded = Signal()
    quotaRequestSucceeded = Signal()
    cancelRequested = Signal()

    _SEND_TIMEOUT_FALLBACK_MS = 12_000

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

        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.setSpacing(16)

        # 顶部表单区
        form_layout = QVBoxLayout()
        form_layout.setSpacing(12)
        form_layout.setContentsMargins(0, 0, 0, 0)

        LABEL_WIDTH = 75
        COMPACT_FIELD_WIDTH = 320

        # 1. 消息类型
        type_row = QHBoxLayout()
        self.type_label_static = BodyLabel("消息类型：", self)
        self.type_label_static.setFixedWidth(LABEL_WIDTH)
        self.type_combo = ComboBox(self)
        self.type_locked_label = BodyLabel("", self)
        self.type_locked_label.setFixedWidth(COMPACT_FIELD_WIDTH)
        self.base_options = [
            "报错反馈",
            REQUEST_MESSAGE_TYPE,
            "新功能建议",
            "纯聊天",
        ]
        for item in self.base_options:
            self.type_combo.addItem(item, item)
        self.type_combo.setFixedWidth(COMPACT_FIELD_WIDTH)
        type_row.addWidget(self.type_label_static)
        type_row.addWidget(self.type_combo)
        type_row.addWidget(self.type_locked_label)
        type_row.addStretch(1)
        form_layout.addLayout(type_row)

        # 2. 邮箱 + 验证码（同一行）
        email_row = QHBoxLayout()
        self.email_label = BodyLabel("联系邮箱：", self)
        self.email_label.setFixedWidth(LABEL_WIDTH)
        self.email_edit = PasteOnlyLineEdit(self)
        self.email_edit.setPlaceholderText("name@example.com")
        email_row.addWidget(self.email_label)
        email_row.addWidget(self.email_edit)

        self.verify_code_edit = LineEdit(self)
        self.verify_code_edit.setPlaceholderText("6位验证码")
        self.verify_code_edit.setMaxLength(6)
        self.verify_code_edit.setValidator(QIntValidator(0, 999999, self))
        self.verify_code_edit.setMaximumWidth(120)

        self.send_verify_btn = PushButton("发送验证码", self)
        self.verify_send_spinner = IndeterminateProgressRing(self, start=False)
        self.verify_send_spinner.setFixedSize(16, 16)
        self.verify_send_spinner.setStrokeWidth(2)
        self.verify_send_spinner.hide()

        email_row.addSpacing(4)
        email_row.addWidget(self.send_verify_btn)
        email_row.addWidget(self.verify_send_spinner)
        email_row.addWidget(self.verify_code_edit)
        form_layout.addLayout(email_row)

        self.verify_code_edit.hide()
        self.send_verify_btn.hide()
        self.verify_send_spinner.hide()

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self.issue_title_label = BodyLabel("反馈标题：", self)
        self.issue_title_label.setFixedWidth(LABEL_WIDTH)
        self.issue_title_edit = LineEdit(self)
        self.issue_title_edit.setPlaceholderText("可选")
        self.issue_title_edit.setClearButtonEnabled(True)
        self.issue_title_edit.setMaxLength(60)
        self.issue_title_edit.setFixedWidth(COMPACT_FIELD_WIDTH)
        title_row.addWidget(self.issue_title_label)
        title_row.addWidget(self.issue_title_edit)
        title_row.addStretch(1)
        form_layout.addLayout(title_row)

        self.issue_title_label.hide()
        self.issue_title_edit.hide()

        # 4. 额度申请参数
        self.amount_row = QHBoxLayout()
        self.amount_label = BodyLabel("支付金额：￥", self)
        self.amount_edit = EditableComboBox(self)
        self.amount_edit.setPlaceholderText("必填")
        self.amount_edit.setMaximumWidth(100)
        validator = QDoubleValidator(0.01, 9999.99, 2, self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        for amount in DONATION_AMOUNT_OPTIONS:
            self.amount_edit.addItem(amount)
        self.amount_edit.setText("11.45")
        self.amount_edit.setValidator(validator)
        self.amount_edit.currentTextChanged.connect(self._on_amount_changed)
        self.amount_edit.editingFinished.connect(self._on_amount_editing_finished)
        self.amount_edit.installEventFilter(self)

        self.quantity_label = BodyLabel("需求额度：", self)
        self.quantity_edit = LineEdit(self)
        self.quantity_edit.setPlaceholderText("按需填写")
        self.quantity_edit.setMaximumWidth(90)
        self.quantity_edit.setMaxLength(len(str(MAX_REQUEST_QUOTA)) + 2)
        quantity_validator = QDoubleValidator(0.0, float(MAX_REQUEST_QUOTA), 1, self)
        quantity_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.quantity_edit.setValidator(quantity_validator)
        self.quantity_edit.textChanged.connect(self._on_quantity_changed)
        self.quantity_edit.editingFinished.connect(self._on_quantity_editing_finished)

        self.urgency_label = BodyLabel("问卷紧急程度：", self)
        self.urgency_combo = ComboBox(self)
        self.urgency_combo.setMaximumWidth(140)
        for urgency in [
            "低",
            "中（本月内）",
            "高（本周内）",
            "紧急（两天内）",
        ]:
            self.urgency_combo.addItem(urgency, urgency)
        urgency_default_index = self.urgency_combo.findText("中（本月内）")
        if urgency_default_index >= 0:
            self.urgency_combo.setCurrentIndex(urgency_default_index)
        self.urgency_combo.currentIndexChanged.connect(lambda _: self._on_urgency_changed())

        self.amount_row.addWidget(self.quantity_label)
        self.amount_row.addWidget(self.quantity_edit)
        self.amount_row.addSpacing(16)
        self.amount_row.addWidget(self.amount_label)
        self.amount_row.addWidget(self.amount_edit)
        self.amount_row.addSpacing(16)
        self.amount_row.addWidget(self.urgency_label)
        self.amount_row.addWidget(self.urgency_combo)
        self.amount_row.addStretch(1)
        form_layout.addLayout(self.amount_row)

        self.amount_rule_hint = QWidget(self)
        self.amount_rule_hint.setObjectName("amountRuleHint")
        self.amount_rule_hint.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.amount_rule_hint.setStyleSheet(
            "#amountRuleHint {"
            "background-color: #FFF4CE;"
            "border: 1px solid #F2D58A;"
            "border-radius: 8px;"
            "}"
        )
        amount_rule_hint_layout = QHBoxLayout(self.amount_rule_hint)
        amount_rule_hint_layout.setContentsMargins(12, 8, 12, 8)
        amount_rule_hint_layout.setSpacing(8)
        self.amount_rule_hint_icon = IconWidget(FluentIcon.INFO, self.amount_rule_hint)
        self.amount_rule_hint_icon.setIcon(FluentIcon.INFO)
        self.amount_rule_hint_icon.setStyleSheet("color: #B57A00;")
        self.amount_rule_hint_text = BodyLabel(DONATION_AMOUNT_BLOCK_MESSAGE, self.amount_rule_hint)
        self.amount_rule_hint_text.setStyleSheet("color: #7A5200;")
        amount_rule_hint_layout.addWidget(self.amount_rule_hint_icon)
        amount_rule_hint_layout.addWidget(self.amount_rule_hint_text, 1)
        form_layout.addWidget(self.amount_rule_hint)

        self.amount_label.hide()
        self.amount_edit.hide()
        self.quantity_label.hide()
        self.quantity_edit.hide()
        self.urgency_label.hide()
        self.urgency_combo.hide()
        self.amount_rule_hint.hide()

        # 第二部分：消息内容
        msg_layout = QVBoxLayout()
        msg_layout.setSpacing(6)
        msg_label_row = QHBoxLayout()
        self.message_label = BodyLabel("消息内容：", self)
        msg_label_row.addWidget(self.message_label)
        msg_label_row.addStretch(1)

        self.message_edit = PasteOnlyPlainTextEdit(self, self._on_context_paste)
        self.message_edit.setPlaceholderText("请详细描述您的问题、需求或留言…")
        self.message_edit.setMinimumHeight(140)
        self.message_edit.installEventFilter(self)
        self.random_ip_user_id_label = BodyLabel("", self)
        self.random_ip_user_id_label.setWordWrap(True)
        self.random_ip_user_id_label.setStyleSheet("color: #666; font-size: 12px;")
        self.random_ip_user_id_label.hide()

        msg_layout.addLayout(msg_label_row)
        msg_layout.addWidget(self.message_edit, 1)
        msg_layout.addWidget(self.random_ip_user_id_label)

        # 第三部分：图片附件
        self.attachments_section = QWidget(self)
        attachments_box = QVBoxLayout(self.attachments_section)
        attachments_box.setContentsMargins(0, 0, 0, 0)
        attachments_box.setSpacing(6)

        attach_toolbar = QHBoxLayout()
        self.attach_title = BodyLabel(
            "图片附件 (最多3张，支持Ctrl+V粘贴，单张≤10MB):",
            self.attachments_section,
        )

        self.attach_add_btn = PushButton(FluentIcon.ADD, "添加图片", self.attachments_section)
        self.attach_clear_btn = PushButton(FluentIcon.DELETE, "清空附件", self.attachments_section)

        attach_toolbar.addWidget(self.attach_title)
        attach_toolbar.addStretch(1)
        attach_toolbar.addWidget(self.attach_add_btn)
        attach_toolbar.addWidget(self.attach_clear_btn)

        attachments_box.addLayout(attach_toolbar)

        self.attach_list_layout = QHBoxLayout()
        self.attach_list_layout.setSpacing(12)
        self.attach_list_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.attach_list_container = QWidget(self.attachments_section)
        self.attach_list_container.setLayout(self.attach_list_layout)

        self.attach_placeholder = BodyLabel("暂无附件", self.attachments_section)
        self.attach_placeholder.setStyleSheet("color: #888; padding: 6px;")

        attachments_box.addWidget(self.attach_list_container)
        attachments_box.addWidget(self.attach_placeholder)

        self.auto_attach_section = QWidget(self)
        auto_attach_layout = QHBoxLayout(self.auto_attach_section)
        auto_attach_layout.setContentsMargins(0, 0, 0, 0)
        auto_attach_layout.setSpacing(12)
        self.auto_attach_title = BodyLabel("附加排障文件：", self.auto_attach_section)
        self.auto_attach_config_checkbox = CheckBox("上传当前运行配置", self.auto_attach_section)
        self.auto_attach_log_checkbox = CheckBox("上传当前日志", self.auto_attach_section)
        self.auto_attach_config_checkbox.setChecked(self._auto_attach_config_default)
        self.auto_attach_log_checkbox.setChecked(self._auto_attach_log_default)
        auto_attach_layout.addWidget(self.auto_attach_title)
        auto_attach_layout.addWidget(self.auto_attach_config_checkbox)
        auto_attach_layout.addWidget(self.auto_attach_log_checkbox)
        auto_attach_layout.addStretch(1)
        self.auto_attach_section.hide()

        self.request_payment_section = QWidget(self)
        payment_layout = QVBoxLayout(self.request_payment_section)
        payment_layout.setContentsMargins(0, 0, 0, 0)
        payment_layout.setSpacing(6)

        payment_row = QHBoxLayout()
        payment_row.setSpacing(12)
        self.payment_method_label = BodyLabel("选择的支付方式：", self.request_payment_section)
        self.payment_method_group = QButtonGroup(self.request_payment_section)
        self.payment_method_group.setExclusive(True)
        self.payment_method_wechat_radio = RadioButton(
            PAYMENT_METHOD_OPTIONS[0], self.request_payment_section
        )
        self.payment_method_alipay_radio = RadioButton(
            PAYMENT_METHOD_OPTIONS[1], self.request_payment_section
        )
        self.payment_method_group.addButton(self.payment_method_wechat_radio, 1)
        self.payment_method_group.addButton(self.payment_method_alipay_radio, 2)
        payment_row.addWidget(self.payment_method_label)
        payment_row.addWidget(self.payment_method_wechat_radio)
        payment_row.addWidget(self.payment_method_alipay_radio)
        payment_row.addStretch(1)
        payment_layout.addLayout(payment_row)

        self.request_payment_section.hide()

        # 组装表单、消息、附件
        wrapper.addLayout(form_layout)
        wrapper.addLayout(msg_layout, 1)  # 给消息框最大的 stretch
        wrapper.addWidget(self.auto_attach_section)
        wrapper.addWidget(self.attachments_section)
        wrapper.addWidget(self.request_payment_section)

        self.request_payment_confirm_section = QWidget(self)
        donated_row = QHBoxLayout(self.request_payment_confirm_section)
        donated_row.setContentsMargins(0, 0, 0, 0)
        donated_row.setSpacing(8)
        self.donated_cb = CheckBox(
            "我已完成支付，且确认随机ip可用",
            self.request_payment_confirm_section,
        )
        self.open_donate_btn = PushButton(
            FluentIcon.HEART, "去支付", self.request_payment_confirm_section
        )
        self.open_donate_btn.setToolTip("打开支付页面")
        donated_row.addStretch(1)
        donated_row.addWidget(self.open_donate_btn)
        donated_row.addWidget(self.donated_cb)
        self.request_payment_confirm_section.hide()
        wrapper.addWidget(self.request_payment_confirm_section)

        # 第四部分：底部状态与按钮
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 8, 0, 0)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_spinner = IndeterminateProgressRing(self, start=False)
        self.status_spinner.setFixedSize(16, 16)
        self.status_spinner.setStrokeWidth(2)
        self.status_icon = IconWidget(FluentIcon.INFO, self)
        self.status_icon.setFixedSize(16, 16)
        self.status_icon.hide()
        self.online_label = BodyLabel("作者当前在线状态：查询中...", self)
        self.online_label.setStyleSheet("color:#BA8303;")
        status_row.addWidget(self.status_spinner)
        status_row.addWidget(self.status_icon)
        status_row.addWidget(self.online_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.cancel_btn: Optional[PushButton] = None
        if show_cancel_button:
            self.cancel_btn = PushButton("取消", self)
            btn_row.addWidget(self.cancel_btn)
        self.send_btn = PrimaryPushButton("发送", self)
        self.send_spinner = IndeterminateProgressRing(self, start=False)
        self.send_spinner.setFixedSize(20, 20)
        self.send_spinner.setStrokeWidth(3)
        self.send_spinner.hide()
        btn_row.addWidget(self.send_spinner)
        btn_row.addWidget(self.send_btn)

        bottom_layout.addLayout(status_row)
        bottom_layout.addStretch(1)
        bottom_layout.addLayout(btn_row)
        wrapper.addLayout(bottom_layout)

        self.type_combo.currentIndexChanged.connect(lambda _: self._on_type_changed())
        self.donated_cb.installEventFilter(self)
        self.donated_cb.toggled.connect(lambda _: self._update_send_button_state())
        self.open_donate_btn.clicked.connect(self._open_donate_page)
        install_tooltip_filters((self.open_donate_btn, self.donated_cb, self.send_btn))
        QTimer.singleShot(0, self._on_type_changed)
        if default_type:
            idx = self.type_combo.findText(default_type)
            if idx >= 0:
                self.type_combo.setCurrentIndex(idx)
        self._sync_message_type_lock_state()

        self.send_btn.clicked.connect(self._on_send_clicked)
        self.send_verify_btn.clicked.connect(self._on_send_verify_clicked)
        self.attach_add_btn.clicked.connect(self._on_choose_files)
        self.attach_clear_btn.clicked.connect(self._on_clear_attachments)
        self.payment_method_group.buttonToggled.connect(lambda *_: self._update_send_button_state())
        if self.cancel_btn is not None:
            self.cancel_btn.clicked.connect(self.cancelRequested.emit)
        self.refresh_random_ip_user_id_hint()

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
        current_type = self.type_combo.currentText()
        self._sync_message_type_lock_state()
        is_bug_report = self._is_bug_report_type(current_type)

        # 控制额度申请参数显示/隐藏
        if current_type == REQUEST_MESSAGE_TYPE:
            self.attachments_section.hide()
            self.auto_attach_section.hide()
            self.issue_title_label.hide()
            self.issue_title_edit.hide()
            self.issue_title_edit.clear()
            self.request_payment_section.show()
            self.request_payment_confirm_section.show()
            self.amount_label.show()
            self.amount_edit.show()
            self.quantity_label.show()
            self.quantity_edit.show()
            self.urgency_label.show()
            self.urgency_combo.show()
            self.verify_code_edit.show()
            self.send_verify_btn.show()
            self.email_edit.setPlaceholderText("name@example.com")
            self.message_label.setText("补充说明（选填）：")
            self.message_edit.setPlaceholderText(
                "请简单说明你的问卷紧急情况或使用场景...\n以及...是大学生吗（？"
            )
        else:
            self.attachments_section.show()
            self.auto_attach_section.setVisible(is_bug_report)
            self.issue_title_label.setVisible(is_bug_report)
            self.issue_title_edit.setVisible(is_bug_report)
            if not is_bug_report:
                self.issue_title_edit.clear()
            self.request_payment_section.hide()
            self.request_payment_confirm_section.hide()
            self.amount_label.hide()
            self.amount_edit.hide()
            self.quantity_label.hide()
            self.quantity_edit.hide()
            self.urgency_label.hide()
            self.urgency_combo.hide()
            self.verify_code_edit.hide()
            self.send_verify_btn.hide()
            self.verify_send_spinner.hide()
            self.verify_code_edit.clear()
            self._verify_code_requested = False
            self._verify_code_requested_email = ""
            self._verify_code_sending = False
            self._stop_cooldown()
            self.email_edit.setPlaceholderText("name@example.com")
            self.message_label.setText("消息内容：")
            self.message_edit.setPlaceholderText("请详细描述您的问题、需求或留言…")
            self._close_amount_rule_infobar()
        self._refresh_amount_options()
        self._sync_amount_rule_warning()
        self._sync_donation_check_state()
        self._update_send_button_state()

    def _sync_message_type_lock_state(self) -> None:
        current_type = self.type_combo.currentText() or ""
        self.type_locked_label.setText(current_type)
        self.type_combo.setVisible(not self._lock_message_type)
        self.type_combo.setEnabled(not self._lock_message_type)
        self.type_locked_label.setVisible(self._lock_message_type)

    def _is_bug_report_type(self, message_type: Optional[str]) -> bool:
        return (message_type or "").strip() == "报错反馈"

    def _reset_bug_report_auto_attach_defaults(self) -> None:
        self.auto_attach_config_checkbox.setChecked(self._auto_attach_config_default)
        self.auto_attach_log_checkbox.setChecked(self._auto_attach_log_default)

    def _update_send_button_state(self) -> None:
        if not hasattr(self, "send_btn"):
            return
        if self.send_spinner.isVisible():
            self.send_btn.setEnabled(False)
            self.send_btn.setToolTip("")
            return

        current_type = self.type_combo.currentText() or ""
        require_donation_check = current_type == REQUEST_MESSAGE_TYPE
        block_reason = self._get_donation_check_block_reason()
        can_send = (not require_donation_check) or (
            self.donated_cb.isChecked() and not block_reason
        )
        self.send_btn.setEnabled(can_send)
        if require_donation_check and block_reason:
            self.donated_cb.setToolTip(block_reason)
        else:
            self.donated_cb.setToolTip("")
        if require_donation_check and not can_send:
            if block_reason:
                self.send_btn.setToolTip(block_reason)
            else:
                self.send_btn.setToolTip("请先勾选“我已完成支付，且确认随机ip可用”后再发送申请")
        else:
            self.send_btn.setToolTip("")

    def _on_context_paste(self, target: QWidget) -> bool:
        if target is self.message_edit and self._handle_clipboard_image():
            return True
        return False

    def _attachments_enabled(self) -> bool:
        return (self.type_combo.currentText() or "") != REQUEST_MESSAGE_TYPE

    def _render_attachments_ui(self):
        parent_widget = cast(QWidget, self)
        while self.attach_list_layout.count():
            item = self.attach_list_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not self._attachments.attachments:
            self.attach_list_container.setVisible(False)
            self.attach_placeholder.setVisible(True)
            self.attach_clear_btn.setEnabled(False)
            return

        self.attach_list_container.setVisible(True)
        self.attach_placeholder.setVisible(False)
        self.attach_clear_btn.setEnabled(True)

        for idx, att in enumerate(self._attachments.attachments):
            card_widget = QWidget(parent_widget)
            card_layout = QVBoxLayout(card_widget)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(6)

            thumb_label = QLabel(parent_widget)
            thumb_label.setFixedSize(96, 96)
            thumb_label.setScaledContents(True)
            thumb_label.setStyleSheet("border: 1px solid #E0E0E0; border-radius: 4px;")
            if att.pixmap and not att.pixmap.isNull():
                thumb_label.setPixmap(att.pixmap)
            card_layout.addWidget(thumb_label)

            size_label = BodyLabel(f"{round(len(att.data) / 1024, 1)} KB", parent_widget)
            size_label.setStyleSheet("color: #666; font-size: 11px;")
            size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(size_label)

            remove_btn = PushButton("移除", parent_widget)
            remove_btn.setFixedWidth(96)
            remove_btn.clicked.connect(lambda _=False, i=idx: self._remove_attachment(i))
            card_layout.addWidget(remove_btn)

            self.attach_list_layout.addWidget(card_widget)
        self.attach_list_layout.addStretch(1)

    def _remove_attachment(self, index: int):
        self._attachments.remove_at(index)
        self._render_attachments_ui()

    def _on_clear_attachments(self):
        self._attachments.clear()
        self._render_attachments_ui()

    def _handle_clipboard_image(self) -> bool:
        if not self._attachments_enabled():
            return False
        clipboard = QGuiApplication.clipboard()
        mime = clipboard.mimeData()
        if mime is None or not mime.hasImage():
            return False

        image = clipboard.image()
        ok, msg = self._attachments.add_qimage(image, "clipboard.png")
        if ok:
            self._render_attachments_ui()
        else:
            InfoBar.error(
                "",
                msg,
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2500,
            )
        return True

    def _on_choose_files(self):
        if not self._attachments_enabled():
            return
        parent_widget = cast(QWidget, self)
        paths, _ = QFileDialog.getOpenFileNames(
            parent_widget,
            "选择图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;所有文件 (*.*)",
        )
        if not paths:
            return
        for path in paths:
            ok, msg = self._attachments.add_file_path(path)
            if not ok:
                InfoBar.error(
                    "",
                    msg,
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2500,
                )
                break
        self._render_attachments_ui()

    def _parse_quantity_value(self, text: Optional[str] = None) -> Optional[Decimal]:
        raw_text = (self.quantity_edit.text() if text is None else text) or ""
        raw_text = raw_text.strip()
        if not raw_text:
            return None
        try:
            value = Decimal(raw_text)
        except (InvalidOperation, ValueError):
            return None
        if value < 0:
            return None
        scaled = value / REQUEST_QUOTA_STEP
        if scaled != scaled.to_integral_value():
            return None
        return value

    def _normalize_quantity_text(self, text: str) -> str:
        quantity = self._parse_quantity_value(text)
        if quantity is None:
            return (text or "").strip()
        return format_quota_value(quantity)

    def _normalize_quantity_if_needed(self) -> None:
        raw_text = (self.quantity_edit.text() or "").strip()
        if not raw_text:
            return
        quantity = self._parse_quantity_value(raw_text)
        if quantity is None:
            return
        normalized_text = self._normalize_quantity_text(raw_text)
        if quantity > Decimal(str(MAX_REQUEST_QUOTA)):
            normalized_text = self._last_valid_quantity_text
        if normalized_text == raw_text:
            return
        self.quantity_edit.blockSignals(True)
        try:
            self.quantity_edit.setText(normalized_text)
        finally:
            self.quantity_edit.blockSignals(False)

    def _parse_amount_value(self, text: Optional[str] = None) -> Optional[Decimal]:
        raw_text = (self.amount_edit.currentText() if text is None else text) or ""
        raw_text = raw_text.strip()
        if not raw_text:
            return None
        try:
            value = Decimal(raw_text)
        except (InvalidOperation, ValueError):
            return None
        if value <= 0:
            return None
        return value

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
        for min_quantity, min_amount in DONATION_AMOUNT_RULES:
            if quantity >= min_quantity:
                return min_amount
        return self._parse_amount_value(DONATION_AMOUNT_OPTIONS[0])

    def _get_allowed_amount_options(self, quantity: Decimal) -> list[str]:
        minimum_allowed_amount = self._get_minimum_allowed_amount(quantity)
        if minimum_allowed_amount is None:
            return DONATION_AMOUNT_OPTIONS[:]
        return [
            amount
            for amount in DONATION_AMOUNT_OPTIONS
            if (self._parse_amount_value(amount) or Decimal("0")) >= minimum_allowed_amount
        ]

    def _is_amount_allowed(self, amount_text: str, quantity_text: Optional[str] = None) -> bool:
        amount_value = self._parse_amount_value(amount_text)
        if amount_value is None:
            return True

        quantity = self._parse_quantity_value(quantity_text) or Decimal("0")
        minimum_allowed_amount = self._get_minimum_allowed_amount(quantity)
        if minimum_allowed_amount is None:
            return True
        return amount_value >= minimum_allowed_amount

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
        for path in list(getattr(self, "_pending_temp_attachment_paths", [])):
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception as exc:
                log_suppressed_exception(
                    f"_cleanup_pending_temp_files: {path}",
                    exc,
                    level=logging.WARNING,
                )
        self._pending_temp_attachment_paths = []

    @staticmethod
    def _read_file_bytes(path: str) -> bytes:
        with open(path, "rb") as file:
            return file.read()

    @staticmethod
    def _remove_temp_file(path: str) -> None:
        if not path:
            return
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as exc:
            log_suppressed_exception(f"_remove_temp_file: {path}", exc, level=logging.WARNING)

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
        path = get_fatal_crash_log_path()
        if not os.path.exists(path) or os.path.getsize(path) <= 0:
            return None
        with open(path, "rb") as file:
            data = file.read()
        return "fatal_crash.log", ("fatal_crash.log", data, "text/plain")

    @staticmethod
    def _renumber_files_payload(
        items: list[tuple[str, tuple[str, bytes, str]]],
    ) -> list[tuple[str, tuple[str, bytes, str]]]:
        payload: list[tuple[str, tuple[str, bytes, str]]] = []
        for index, (_, file_tuple) in enumerate(items, start=1):
            payload.append((f"file{index}", file_tuple))
        return payload

    def _build_bug_report_auto_files_payload(
        self,
    ) -> tuple[list[tuple[str, tuple[str, bytes, str]]], list[str]]:
        auto_files: list[tuple[str, tuple[str, bytes, str]]] = []
        config_status = "已附带" if self.auto_attach_config_checkbox.isChecked() else "未附带"
        log_status = "已附带" if self.auto_attach_log_checkbox.isChecked() else "未附带"
        summary_lines = [
            f"当前运行配置快照：{config_status}",
            f"当前日志快照：{log_status}",
        ]

        if self.auto_attach_config_checkbox.isChecked():
            auto_files.append(self._export_bug_report_config_snapshot())

        if self.auto_attach_log_checkbox.isChecked():
            auto_files.append(self._export_bug_report_log_snapshot())
            fatal_payload = self._fatal_crash_log_payload()
            if fatal_payload is not None:
                auto_files.append(fatal_payload)
                summary_lines.append("fatal_crash.log：已附带")
            else:
                summary_lines.append("fatal_crash.log：未发现")
        else:
            summary_lines.append("fatal_crash.log：未附带")

        return auto_files, summary_lines

    def _validate_email(self, email: str) -> bool:
        if not email:
            return True
        return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) is not None

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
            request_quota_text = self._normalize_quantity_text(quantity_text)
            request_urgency_text = (self.urgency_combo.currentText() or "").strip()
            if not request_payment_method:
                InfoBar.warning(
                    "",
                    "请选择你刚刚使用的支付方式",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                )
                self._update_send_button_state()
                return
            if not amount_text:
                InfoBar.warning(
                    "",
                    "请输入支付金额",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                )
                return
            if not self.donated_cb.isChecked():
                InfoBar.warning(
                    "",
                    "请先勾选“我已完成支付”后再发送申请",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                )
                self._update_send_button_state()
                return
            if not quantity_text:
                InfoBar.warning(
                    "",
                    "请输入申请额度",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                )
                return
            quantity_value = self._parse_quantity_value(quantity_text)
            if quantity_value is None:
                InfoBar.warning(
                    "",
                    "申请额度必须 >= 0，且只能填 0.5 的倍数",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2200,
                )
                return
            if quantity_value > Decimal(str(MAX_REQUEST_QUOTA)):
                quota_text = format_quota_value(MAX_REQUEST_QUOTA)
                InfoBar.warning(
                    "",
                    f"申请额度不能超过 {quota_text}",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                )
                return
            if amount_text and not self._is_amount_allowed(amount_text, quantity_text):
                self._show_amount_rule_infobar()
                InfoBar.warning(
                    "",
                    DONATION_AMOUNT_BLOCK_MESSAGE,
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2200,
                )
                return
            if not self._verify_code_requested:
                InfoBar.warning(
                    "",
                    "请先点击发送验证码",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                )
                return
            if email != self._verify_code_requested_email:
                InfoBar.warning(
                    "",
                    "邮箱已变更，请重新发送验证码",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2200,
                )
                return
            if verify_code != "114514":
                InfoBar.warning(
                    "",
                    "验证码错误，请重试",
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
        QTimer.singleShot(
            self._SEND_TIMEOUT_FALLBACK_MS,
            cast(QWidget, self),
            lambda generation=send_generation: self._finish_stuck_send_if_needed(generation),
        )

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
                timeout = 20 if files_payload else 10
                resp = http_post(
                    CONTACT_API_URL,
                    files=multipart_fields,
                    timeout=(10, timeout),
                    proxies={},
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
