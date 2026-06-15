from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Callable, Protocol, cast

from PySide6.QtWidgets import QWidget
from qfluentwidgets import InfoBarPosition

from software.logging.log_utils import log_suppressed_exception
from .send_workflow import compute_send_timeout_fallback_ms


class _InfoBarLike(Protocol):
    def warning(self, *args, **kwargs) -> Any: ...
    def error(self, *args, **kwargs) -> Any: ...
    def success(self, *args, **kwargs) -> Any: ...


class _MessageBoxType(Protocol):
    def __call__(self, *args, **kwargs) -> Any: ...


class _TimerType(Protocol):
    def singleShot(self, *args, **kwargs) -> Any: ...


class _ResponseLike(Protocol):
    status_code: int


def _widget_module():
    from . import widget as widget_module

    return widget_module


def _info_bar(form: Any) -> _InfoBarLike:
    getter = getattr(form, "_info_bar", None)
    if callable(getter):
        return cast(_InfoBarLike, getter())
    return cast(_InfoBarLike, _widget_module().InfoBar)


def _message_box(form: Any) -> _MessageBoxType:
    getter = getattr(form, "_message_box", None)
    if callable(getter):
        return cast(_MessageBoxType, getter())
    return cast(_MessageBoxType, _widget_module().MessageBox)


def _qtimer(form: Any) -> _TimerType:
    getter = getattr(form, "_qtimer", None)
    if callable(getter):
        return cast(_TimerType, getter())
    return cast(_TimerType, _widget_module().QTimer)


def _contact_api_url(form: Any) -> str:
    getter = getattr(form, "_contact_api_url", None)
    if callable(getter):
        return cast(str, getter())
    return cast(str, _widget_module().CONTACT_API_URL)


def _contact_http_post(form: Any) -> Callable[..., _ResponseLike]:
    getter = getattr(form, "_contact_http_post", None)
    if callable(getter):
        return cast(Callable[..., _ResponseLike], getter)
    return cast(Callable[..., _ResponseLike], _widget_module().http_post)


def _app_version(form: Any) -> str:
    getter = getattr(form, "_app_version", None)
    if callable(getter):
        return cast(str, getter())
    return cast(str, _widget_module().__VERSION__)


def _build_contact_message(form: Any, **kwargs) -> str:
    builder = getattr(form, "_build_contact_message", None)
    if callable(builder):
        return cast(str, builder(**kwargs))
    return cast(str, _widget_module().build_contact_message(**kwargs))


def _build_contact_request_fields(form: Any, **kwargs):
    builder = getattr(form, "_build_contact_request_fields", None)
    if callable(builder):
        return builder(**kwargs)
    return _widget_module().build_contact_request_fields(**kwargs)


def clear_email_selection(form: Any) -> None:
    try:
        form.email_edit.setSelection(0, 0)
    except (RuntimeError, AttributeError) as exc:
        log_suppressed_exception(
            "_clear_email_selection: self.email_edit.setSelection(0, 0)",
            exc,
            level=logging.WARNING,
        )


def focus_send_button(form: Any) -> None:
    try:
        form.send_btn.setFocus()
    except (RuntimeError, AttributeError) as exc:
        log_suppressed_exception(
            "_focus_send_button: self.send_btn.setFocus()",
            exc,
            level=logging.WARNING,
        )


def emit_send_finished_if_current(form: Any, generation: int, success: bool, message: str) -> None:
    with form._send_state_lock:
        if generation != getattr(form, "_send_generation", 0):
            return
        if generation == getattr(form, "_send_finished_generation", 0):
            return
        if not getattr(form, "_send_in_progress", False):
            return
        form._send_finished_generation = generation
    form._sendFinished.emit(success, message)


def finish_stuck_send_if_needed(form: Any, generation: int) -> None:
    emit_send_finished_if_current(form, generation, False, "发送超时，请稍后重试")


def compute_send_timeout_fallback_ms_for_form(form: Any, read_timeout_seconds: int) -> int:
    return compute_send_timeout_fallback_ms(
        connect_timeout_seconds=form._SEND_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds=read_timeout_seconds,
        grace_ms=form._SEND_TIMEOUT_GRACE_MS,
    )


def _confirm_before_send(form: Any, mtype: str, email: str) -> bool:
    if email:
        return True

    confirm_box = _message_box(form)(
        "未填写邮箱",
        "当前未输入邮箱地址，开发者可能无法联系你回复处理进度。是否继续发送？",
        form.window() or form,
    )
    confirm_box.yesButton.setText("继续发送")
    confirm_box.cancelButton.setText("返回填写")
    return bool(confirm_box.exec())


def _validate_send_request(form: Any, mtype: str, email: str) -> tuple[bool, dict[str, str]]:
    issue_title = (form.issue_title_edit.text() or "").strip()

    message = (form.message_edit.toPlainText() or "").strip()
    if not message:
        _info_bar(form).warning("", "请输入消息内容", parent=form, position=InfoBarPosition.TOP, duration=2000)
        return False, {}

    if email and not form._validate_email(email):
        _info_bar(form).warning("", "邮箱格式不正确", parent=form, position=InfoBarPosition.TOP, duration=2000)
        return False, {}

    form.refresh_random_ip_user_id_hint()
    if not _confirm_before_send(form, mtype, email):
        return False, {}
    return True, {"issue_title": issue_title, "message": message}


def on_send_clicked(form: Any) -> None:
    form._cleanup_pending_temp_files()
    email = (form.email_edit.text() or "").strip()
    form._current_has_email = bool(email)

    timer_context = cast(QWidget, form)
    _qtimer(form).singleShot(10, timer_context, lambda current_form=form: clear_email_selection(current_form))
    _qtimer(form).singleShot(10, timer_context, lambda current_form=form: focus_send_button(current_form))

    mtype = form.type_combo.currentText() or "报错反馈"
    valid, request_data = _validate_send_request(form, mtype, email)
    if not valid:
        return

    full_message = _build_contact_message(
        form,
        version_str=_app_version(form),
        message_type=mtype,
        issue_title=request_data["issue_title"],
        email=email,
        random_ip_user_id=form._random_ip_user_id,
        message=request_data["message"],
    )

    if not _contact_api_url(form):
        _info_bar(form).error("", "联系API未配置", parent=form, position=InfoBarPosition.TOP, duration=3000)
        return

    manual_files_payload = form._attachments.files_payload()
    auto_files_payload: list[tuple[str, tuple[str, bytes, str]]] = []
    if form._is_bug_report_type(mtype):
        try:
            auto_files_payload, _ = form._build_bug_report_auto_files_payload()
        except Exception as exc:
            form._cleanup_pending_temp_files()
            _info_bar(form).error("", f"自动导出附件失败：{exc}", parent=form, position=InfoBarPosition.TOP, duration=3500)
            return
    payload = {"message": full_message, "timestamp": datetime.now().isoformat()}
    files_payload = form._renumber_files_payload(manual_files_payload + auto_files_payload)

    form.send_btn.setFocus()
    form.send_btn.setEnabled(False)
    form.send_btn.setText("发送中...")
    form._send_in_progress = True
    form._set_send_loading(True)
    form._update_send_button_state()
    form._current_message_type = mtype
    with form._send_state_lock:
        form._send_generation += 1
        send_generation = form._send_generation

    issue_title = request_data["issue_title"]

    def _send() -> None:
        try:
            multipart_fields = _build_contact_request_fields(
                form,
                message=payload["message"],
                message_type=mtype,
                issue_title=issue_title,
                timestamp=payload["timestamp"],
                random_ip_user_id=form._random_ip_user_id,
                files_payload=files_payload,
            )
            read_timeout_seconds = form._SEND_READ_TIMEOUT_WITH_FILES_SECONDS if files_payload else form._SEND_READ_TIMEOUT_SECONDS
            resp = _contact_http_post(form)(
                _contact_api_url(form),
                files=multipart_fields,
                timeout=(form._SEND_CONNECT_TIMEOUT_SECONDS, read_timeout_seconds),
            )
            if resp.status_code == 200:
                emit_send_finished_if_current(form, send_generation, True, "")
            else:
                emit_send_finished_if_current(form, send_generation, False, f"发送失败：{resp.status_code}")
        except Exception as exc:
            emit_send_finished_if_current(form, send_generation, False, f"发送失败：{exc}")

    send_timeout_fallback_ms = compute_send_timeout_fallback_ms_for_form(
        form,
        form._SEND_READ_TIMEOUT_WITH_FILES_SECONDS if files_payload else form._SEND_READ_TIMEOUT_SECONDS,
    )
    _qtimer(form).singleShot(
        send_timeout_fallback_ms,
        cast(QWidget, form),
        lambda generation=send_generation, current_form=form: finish_stuck_send_if_needed(current_form, generation),
    )
    threading.Thread(target=_send, daemon=True).start()


def on_send_finished(form: Any, success: bool, error_msg: str) -> None:
    form._send_in_progress = False
    form._set_send_loading(False)
    form.send_btn.setText("发送")
    form._update_send_button_state()
    form._cleanup_pending_temp_files()

    if success:
        msg = "消息已发送"
        if getattr(form, "_current_has_email", False):
            msg += "，开发者会优先通过邮箱联系你"
        _info_bar(form).success("", msg, parent=form, position=InfoBarPosition.TOP, duration=2500)
        if form._auto_clear_on_success:
            form.message_edit.clear()
            form.issue_title_edit.clear()
            form._attachments.clear()
            form._render_attachments_ui()
            form._reset_bug_report_auto_attach_defaults()
        form.sendSucceeded.emit()
        return

    _info_bar(form).error("", error_msg, parent=form, position=InfoBarPosition.TOP, duration=3000)
