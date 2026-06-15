from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget
)
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    ComboBox,
    FluentIcon,
    IconWidget,
    IndeterminateProgressRing,
    PrimaryPushButton,
    PushButton,
    LineEdit,
)

from software.ui.helpers.fluent_tooltip import install_tooltip_filters

from .input_widgets import PasteOnlyLineEdit, PasteOnlyPlainTextEdit


def build_contact_form_ui(form: Any, *, default_type: str, show_cancel_button: bool) -> None:
    wrapper = QVBoxLayout(form)
    wrapper.setContentsMargins(0, 0, 0, 0)
    wrapper.setSpacing(16)

    form_layout = QVBoxLayout()
    form_layout.setSpacing(12)
    form_layout.setContentsMargins(0, 0, 0, 0)

    label_width = 75
    compact_field_width = 320

    type_row = QHBoxLayout()
    form.type_label_static = BodyLabel("消息类型：", form)
    form.type_label_static.setFixedWidth(label_width)
    form.type_combo = ComboBox(form)
    form.type_locked_label = BodyLabel("", form)
    form.type_locked_label.setFixedWidth(compact_field_width)
    form.base_options = [
        "报错反馈",
        "新功能建议",
        "纯聊天",
    ]
    for item in form.base_options:
        form.type_combo.addItem(item, item)
    form.type_combo.setFixedWidth(compact_field_width)
    type_row.addWidget(form.type_label_static)
    type_row.addWidget(form.type_combo)
    type_row.addWidget(form.type_locked_label)
    type_row.addStretch(1)
    form_layout.addLayout(type_row)

    email_row = QHBoxLayout()
    form.email_label = BodyLabel("联系邮箱：", form)
    form.email_label.setFixedWidth(label_width)
    form.email_edit = PasteOnlyLineEdit(form)
    form.email_edit.setPlaceholderText("name@example.com")
    form.email_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    email_row.addWidget(form.email_label)
    email_row.addWidget(form.email_edit, 1)

    form_layout.addLayout(email_row)

    title_row = QHBoxLayout()
    title_row.setSpacing(6)
    form.issue_title_label = BodyLabel("反馈标题：", form)
    form.issue_title_label.setFixedWidth(label_width)
    form.issue_title_edit = LineEdit(form)
    form.issue_title_edit.setPlaceholderText("可选")
    form.issue_title_edit.setClearButtonEnabled(True)
    form.issue_title_edit.setMaxLength(60)
    form.issue_title_edit.setFixedWidth(compact_field_width)
    title_row.addWidget(form.issue_title_label)
    title_row.addWidget(form.issue_title_edit)
    title_row.addStretch(1)
    form_layout.addLayout(title_row)

    form.issue_title_label.hide()
    form.issue_title_edit.hide()

    msg_layout = QVBoxLayout()
    msg_layout.setSpacing(6)
    msg_label_row = QHBoxLayout()
    form.message_label = BodyLabel("消息内容：", form)
    msg_label_row.addWidget(form.message_label)
    msg_label_row.addStretch(1)

    form.message_edit = PasteOnlyPlainTextEdit(form, form._on_context_paste)
    form.message_edit.setPlaceholderText("请详细描述您的问题、需求或留言…")
    form.message_edit.setMinimumHeight(140)
    form.message_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    form.message_edit.installEventFilter(form)
    form.random_ip_user_id_label = BodyLabel("", form)
    form.random_ip_user_id_label.setWordWrap(True)
    form.random_ip_user_id_label.setStyleSheet("color: #666; font-size: 12px;")
    form.random_ip_user_id_label.hide()

    msg_layout.addLayout(msg_label_row)
    msg_layout.addWidget(form.message_edit, 1)
    msg_layout.addWidget(form.random_ip_user_id_label)

    form.attachments_section = QWidget(form)
    attachments_box = QVBoxLayout(form.attachments_section)
    attachments_box.setContentsMargins(0, 0, 0, 0)
    attachments_box.setSpacing(6)

    attach_toolbar = QGridLayout()
    attach_toolbar.setContentsMargins(0, 0, 0, 0)
    attach_toolbar.setHorizontalSpacing(10)
    attach_toolbar.setVerticalSpacing(6)
    form.attach_title = BodyLabel(
        "图片附件 (最多3张，支持Ctrl+V粘贴，单张≤10MB):",
        form.attachments_section,
    )
    form.attach_title.setWordWrap(True)
    form.attach_add_btn = PushButton(FluentIcon.ADD, "添加图片", form.attachments_section)
    form.attach_clear_btn = PushButton(
        FluentIcon.DELETE,
        "清空附件",
        form.attachments_section,
    )
    form.attach_add_btn.setMinimumWidth(112)
    form.attach_clear_btn.setMinimumWidth(112)
    attach_toolbar.addWidget(form.attach_title, 0, 0)
    attach_toolbar.addWidget(form.attach_add_btn, 0, 1)
    attach_toolbar.addWidget(form.attach_clear_btn, 0, 2)
    attach_toolbar.setColumnStretch(0, 1)
    attachments_box.addLayout(attach_toolbar)

    form.attach_list_layout = QHBoxLayout()
    form.attach_list_layout.setSpacing(12)
    form.attach_list_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

    form.attach_list_container = QWidget(form.attachments_section)
    form.attach_list_container.setLayout(form.attach_list_layout)

    form.attach_placeholder = BodyLabel("暂无附件", form.attachments_section)
    form.attach_placeholder.setStyleSheet("color: #888; padding: 6px;")

    attachments_box.addWidget(form.attach_list_container)
    attachments_box.addWidget(form.attach_placeholder)

    form.auto_attach_section = QWidget(form)
    auto_attach_layout = QHBoxLayout(form.auto_attach_section)
    auto_attach_layout.setContentsMargins(0, 0, 0, 0)
    auto_attach_layout.setSpacing(12)
    form.auto_attach_title = BodyLabel("附加排障文件：", form.auto_attach_section)
    form.auto_attach_config_checkbox = CheckBox("上传当前运行配置", form.auto_attach_section)
    form.auto_attach_log_checkbox = CheckBox("上传当前日志", form.auto_attach_section)
    form.auto_attach_config_checkbox.setChecked(form._auto_attach_config_default)
    form.auto_attach_log_checkbox.setChecked(form._auto_attach_log_default)
    auto_attach_layout.addWidget(form.auto_attach_title)
    auto_attach_layout.addWidget(form.auto_attach_config_checkbox)
    auto_attach_layout.addWidget(form.auto_attach_log_checkbox)
    form.auto_attach_section.hide()

    wrapper.addLayout(form_layout)
    wrapper.addLayout(msg_layout, 1)
    wrapper.addWidget(form.auto_attach_section)
    wrapper.addWidget(form.attachments_section)

    bottom_layout = QHBoxLayout()
    bottom_layout.setContentsMargins(0, 8, 0, 0)

    status_row = QHBoxLayout()
    status_row.setSpacing(8)
    form.status_spinner = IndeterminateProgressRing(form, start=False)
    form.status_spinner.setFixedSize(16, 16)
    form.status_spinner.setStrokeWidth(2)
    form.status_icon = IconWidget(FluentIcon.INFO, form)
    form.status_icon.setFixedSize(16, 16)
    form.status_icon.hide()
    form.online_label = BodyLabel("作者当前在线状态：查询中...", form)
    form.online_label.setStyleSheet("color:#BA8303;")
    form.online_label.setWordWrap(True)
    status_row.addWidget(form.status_spinner)
    status_row.addWidget(form.status_icon)
    status_row.addWidget(form.online_label, 1)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(10)
    form.cancel_btn = None
    if show_cancel_button:
        form.cancel_btn = PushButton("取消", form)
        btn_row.addWidget(form.cancel_btn)
    form.send_btn = PrimaryPushButton("发送", form)
    form.send_spinner = IndeterminateProgressRing(form, start=False)
    form.send_spinner.setFixedSize(20, 20)
    form.send_spinner.setStrokeWidth(3)
    form.send_spinner.hide()
    btn_row.addWidget(form.send_spinner)
    btn_row.addWidget(form.send_btn)

    bottom_layout.addLayout(status_row, 1)
    bottom_layout.addLayout(btn_row)
    wrapper.addLayout(bottom_layout)

    form.type_combo.currentIndexChanged.connect(lambda _: form._on_type_changed())
    install_tooltip_filters((form.send_btn,))
    form.send_btn.clicked.connect(form._on_send_clicked)
    form.attach_add_btn.clicked.connect(form._on_choose_files)
    form.attach_clear_btn.clicked.connect(form._on_clear_attachments)
    if form.cancel_btn is not None:
        form.cancel_btn.clicked.connect(form.cancelRequested.emit)

    QTimer.singleShot(0, form._on_type_changed)
    if default_type:
        idx = form.type_combo.findText(default_type)
        if idx >= 0:
            form.type_combo.setCurrentIndex(idx)
    form._sync_message_type_lock_state()
    form.refresh_random_ip_user_id_hint()
