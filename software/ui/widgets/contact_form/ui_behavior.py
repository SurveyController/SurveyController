from typing import Any, cast

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget
from PySide6.QtCore import Qt
from qfluentwidgets import BodyLabel, ImageLabel, InfoBar, InfoBarPosition, PushButton


def sync_message_type_lock_state(form: Any) -> None:
    current_type = form.type_combo.currentText() or ""
    form.type_locked_label.setText(current_type)
    form.type_combo.setVisible(not form._lock_message_type)
    form.type_combo.setEnabled(not form._lock_message_type)
    form.type_locked_label.setVisible(form._lock_message_type)


def on_type_changed(form: Any) -> None:
    current_type = form.type_combo.currentText()
    sync_message_type_lock_state(form)
    is_bug_report = form._is_bug_report_type(current_type)
    form.attachments_section.show()
    form.auto_attach_section.setVisible(is_bug_report)
    form.issue_title_label.setVisible(is_bug_report)
    form.issue_title_edit.setVisible(is_bug_report)
    if not is_bug_report:
        form.issue_title_edit.clear()
    form.email_edit.setPlaceholderText("name@example.com")
    form.message_label.setText("消息内容：")
    form.message_edit.setPlaceholderText("请详细描述您的问题、需求或留言…")
    form._update_send_button_state()


def update_send_button_state(form: Any) -> None:
    if not hasattr(form, "send_btn"):
        return
    if form.send_spinner.isVisible():
        form.send_btn.setEnabled(False)
        form.send_btn.setToolTip("")
        return
    form.send_btn.setEnabled(True)
    form.send_btn.setToolTip("")


def on_context_paste(form: Any, target: QWidget) -> bool:
    if target is form.message_edit and form._handle_clipboard_image():
        return True
    return False


def attachments_enabled(form: Any) -> bool:
    return True


def render_attachments_ui(form: Any) -> None:
    parent_widget = cast(QWidget, form)
    while form.attach_list_layout.count():
        item = form.attach_list_layout.takeAt(0)
        if item is None:
            continue
        widget = item.widget()
        if widget:
            widget.deleteLater()

    if not form._attachments.attachments:
        form.attach_list_container.setVisible(False)
        form.attach_placeholder.setVisible(True)
        form.attach_clear_btn.setEnabled(False)
        return

    form.attach_list_container.setVisible(True)
    form.attach_placeholder.setVisible(False)
    form.attach_clear_btn.setEnabled(True)

    for idx, att in enumerate(form._attachments.attachments):
        card_widget = QWidget(parent_widget)
        card_layout = QVBoxLayout(card_widget)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(6)

        thumb_label = ImageLabel(parent_widget)
        thumb_label.setFixedSize(96, 96)
        thumb_label.setStyleSheet("border: 1px solid #E0E0E0; border-radius: 4px;")
        if att.pixmap and not att.pixmap.isNull():
            thumb_label.setPixmap(
                att.pixmap.scaled(
                    thumb_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        card_layout.addWidget(thumb_label)

        size_label = BodyLabel(f"{round(len(att.data) / 1024, 1)} KB", parent_widget)
        size_label.setStyleSheet("color: #666; font-size: 11px;")
        size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(size_label)

        remove_btn = PushButton("移除", parent_widget)
        remove_btn.setFixedWidth(96)
        remove_btn.clicked.connect(lambda _=False, i=idx: form._remove_attachment(i))
        card_layout.addWidget(remove_btn)

        form.attach_list_layout.addWidget(card_widget)
    form.attach_list_layout.addStretch(1)


def remove_attachment(form: Any, index: int) -> None:
    form._attachments.remove_at(index)
    form._render_attachments_ui()


def clear_attachments(form: Any) -> None:
    form._attachments.clear()
    form._render_attachments_ui()


def handle_clipboard_image(form: Any) -> bool:
    if not attachments_enabled(form):
        return False
    clipboard = QGuiApplication.clipboard()
    mime = clipboard.mimeData()
    if mime is None or not mime.hasImage():
        return False

    image = clipboard.image()
    ok, msg = form._attachments.add_qimage(image, "clipboard.png")
    if ok:
        form._render_attachments_ui()
    else:
        InfoBar.error(
            "",
            msg,
            parent=form,
            position=InfoBarPosition.TOP,
            duration=2500,
        )
    return True


def choose_files(form: Any) -> None:
    if not attachments_enabled(form):
        return
    parent_widget = cast(QWidget, form)
    paths, _ = QFileDialog.getOpenFileNames(
        parent_widget,
        "选择图片",
        "",
        "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;所有文件 (*.*)",
    )
    if not paths:
        return
    for path in paths:
        ok, msg = form._attachments.add_file_path(path)
        if not ok:
            InfoBar.error(
                "",
                msg,
                parent=form,
                position=InfoBarPosition.TOP,
                duration=2500,
            )
            break
    form._render_attachments_ui()
