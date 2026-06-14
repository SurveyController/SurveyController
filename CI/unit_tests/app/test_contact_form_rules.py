from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import software.ui.widgets.contact_form.widget as contact_widget
from software.ui.widgets.contact_form.attachments import (
    build_bug_report_auto_files_payload,
    cleanup_pending_temp_files,
    fatal_crash_log_payload,
    read_file_bytes,
    remove_temp_file,
    renumber_files_payload,
)
from software.ui.widgets.contact_form.send_workflow import (
    compute_send_timeout_fallback_ms,
    validate_email,
)


class _FakeLineEdit:
    def __init__(self, text: str = "") -> None:
        self._text = text
        self.selection = None
        self.focused = 0
        self.enabled = True

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = str(text)

    def clear(self) -> None:
        self._text = ""

    def setSelection(self, start: int, length: int) -> None:
        self.selection = (start, length)

    def setFocus(self) -> None:
        self.focused += 1

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class _FakeComboBox:
    def __init__(self, text: str = "报错反馈") -> None:
        self._text = text

    def currentText(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = str(text)


class _FakeCheckBox:
    def __init__(self, checked: bool = False) -> None:
        self.checked = checked

    def isChecked(self) -> bool:
        return self.checked

    def setChecked(self, checked: bool) -> None:
        self.checked = bool(checked)


class _FakeTextEdit:
    def __init__(self, text: str = "") -> None:
        self._text = text

    def toPlainText(self) -> str:
        return self._text

    def clear(self) -> None:
        self._text = ""


class _FakeAttachments:
    def __init__(self, payload: list[Any] | None = None) -> None:
        self._payload = list(payload or [])
        self.cleared = 0

    def files_payload(self) -> list[Any]:
        return list(self._payload)

    def clear(self) -> None:
        self.cleared += 1


class _FakeInfoBar:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def warning(self, *args, **kwargs) -> None:
        self.calls.append(("warning", args, kwargs))

    def error(self, *args, **kwargs) -> None:
        self.calls.append(("error", args, kwargs))

    def success(self, *args, **kwargs) -> None:
        self.calls.append(("success", args, kwargs))


class _FakeSignal:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def emit(self, *args) -> None:
        self.calls.append(args)


class _FakeTimer:
    def singleShot(self, _delay: int, *args) -> None:
        callback = args[-1]
        callback()


class _FakeLock:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeContactForm:
    _cleanup_pending_temp_files = contact_widget.ContactForm._cleanup_pending_temp_files
    _read_file_bytes = staticmethod(contact_widget.ContactForm._read_file_bytes)
    _remove_temp_file = staticmethod(contact_widget.ContactForm._remove_temp_file)
    _export_bug_report_config_snapshot = contact_widget.ContactForm._export_bug_report_config_snapshot
    _export_bug_report_log_snapshot = contact_widget.ContactForm._export_bug_report_log_snapshot
    _fatal_crash_log_payload = staticmethod(contact_widget.ContactForm._fatal_crash_log_payload)
    _renumber_files_payload = staticmethod(contact_widget.ContactForm._renumber_files_payload)
    _build_bug_report_auto_files_payload = contact_widget.ContactForm._build_bug_report_auto_files_payload
    _validate_email = contact_widget.ContactForm._validate_email
    _compute_send_timeout_fallback_ms = contact_widget.ContactForm._compute_send_timeout_fallback_ms
    _clear_email_selection = contact_widget.ContactForm._clear_email_selection
    _focus_send_button = contact_widget.ContactForm._focus_send_button
    _on_send_finished = contact_widget.ContactForm._on_send_finished
    _find_controller_host = contact_widget.ContactForm._find_controller_host
    _on_send_clicked = contact_widget.ContactForm._on_send_clicked

    _SEND_CONNECT_TIMEOUT_SECONDS = 5
    _SEND_READ_TIMEOUT_SECONDS = 10
    _SEND_READ_TIMEOUT_WITH_FILES_SECONDS = 30
    _SEND_TIMEOUT_GRACE_MS = 1500

    def __init__(self) -> None:
        self.type_combo = _FakeComboBox("报错反馈")
        self.message_edit = _FakeTextEdit("")
        self.email_edit = _FakeLineEdit("")
        self.issue_title_edit = _FakeLineEdit("")
        self.send_btn = _FakeLineEdit("")
        self.auto_attach_config_checkbox = _FakeCheckBox(False)
        self.auto_attach_log_checkbox = _FakeCheckBox(False)
        self._attachments = _FakeAttachments([])
        self._pending_temp_attachment_paths: list[str] = []
        self._random_ip_user_id = 0
        self._send_in_progress = False
        self._send_state_lock = _FakeLock()
        self._send_generation = 0
        self._send_finished_generation = 0
        self._current_message_type = ""
        self._current_has_email = False
        self._auto_clear_on_success = True
        self._config_snapshot_provider: Any = None
        self.sendSucceeded = _FakeSignal()
        self._sendFinished = _FakeSignal()
        self.parent_widget: Any = None
        self.controller: Any = None
        self.actions: list[str] = []

    def _update_send_button_state(self) -> None:
        self.actions.append("update")

    def refresh_random_ip_user_id_hint(self) -> None:
        return

    def _render_attachments_ui(self) -> None:
        return

    def _reset_bug_report_auto_attach_defaults(self) -> None:
        self.auto_attach_config_checkbox.setChecked(False)
        self.auto_attach_log_checkbox.setChecked(False)

    def _is_bug_report_type(self, message_type: str) -> bool:
        return message_type == "报错反馈"

    def _set_send_loading(self, loading: bool) -> None:
        self.actions.append(f"send:{loading}")

    def _qtimer(self) -> _FakeTimer:
        return _FakeTimer()

    def window(self):
        return self.parent_widget

    def parentWidget(self):
        return self.parent_widget


class ContactFormRuleTests:
    def test_send_workflow_helpers(self) -> None:
        assert compute_send_timeout_fallback_ms(
            connect_timeout_seconds=5,
            read_timeout_seconds=10,
            grace_ms=1500,
        ) == 26500
        assert validate_email("") is True
        assert validate_email("user@example.com") is True
        assert validate_email("bad@@mail") is False

    def test_attachment_helpers_module(self, tmp_path: Path) -> None:
        removed_errors: list[tuple[str, Exception]] = []
        file_path = tmp_path / "a.txt"
        file_path.write_bytes(b"abc")
        assert read_file_bytes(str(file_path)) == b"abc"
        remove_temp_file(
            str(file_path),
            on_error=lambda path, exc: removed_errors.append((path, exc)),
        )
        assert not file_path.exists()
        assert removed_errors == []

        temp_path = tmp_path / "temp.txt"
        temp_path.write_text("x", encoding="utf-8")
        remaining = cleanup_pending_temp_files(
            [str(temp_path)],
            on_error=lambda path, exc: removed_errors.append((path, exc)),
        )
        assert remaining == []
        assert not temp_path.exists()

        fatal = tmp_path / "fatal_crash.log"
        fatal.write_text("boom", encoding="utf-8")
        assert fatal_crash_log_payload(str(fatal)) == (
            "fatal_crash.log",
            ("fatal_crash.log", b"boom", "text/plain"),
        )
        assert renumber_files_payload(
            [
                ("配置快照", ("cfg.json", b"{}", "application/json")),
                ("日志快照", ("log.txt", b"log", "text/plain")),
            ]
        ) == [
            ("file1", ("cfg.json", b"{}", "application/json")),
            ("file2", ("log.txt", b"log", "text/plain")),
        ]

        payload, summary = build_bug_report_auto_files_payload(
            auto_attach_config=True,
            auto_attach_log=True,
            export_config_snapshot=lambda: ("配置快照", ("cfg.json", b"{}", "application/json")),
            export_log_snapshot=lambda: ("日志快照", ("log.txt", b"log", "text/plain")),
            get_fatal_payload=lambda: ("fatal_crash.log", ("fatal_crash.log", b"x", "text/plain")),
        )
        assert [item[0] for item in payload] == ["配置快照", "日志快照", "fatal_crash.log"]
        assert "fatal_crash.log：已附带" in summary

    def test_cleanup_temp_files_and_file_helpers(self, tmp_path: Path) -> None:
        form = _FakeContactForm()
        target = tmp_path / "temp.txt"
        target.write_text("abc", encoding="utf-8")
        form._pending_temp_attachment_paths = [str(target)]
        form._cleanup_pending_temp_files()
        assert not target.exists()
        assert form._pending_temp_attachment_paths == []

        target.write_bytes(b"123")
        assert form._read_file_bytes(str(target)) == b"123"
        form._remove_temp_file(str(target))
        assert not target.exists()

    def test_bug_report_auto_files_payload_and_email_validation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        form = _FakeContactForm()
        form.auto_attach_config_checkbox.setChecked(True)
        form.auto_attach_log_checkbox.setChecked(True)
        monkeypatch.setattr(form, "_export_bug_report_config_snapshot", lambda: ("配置快照", ("cfg.json", b"{}", "application/json")))
        monkeypatch.setattr(form, "_export_bug_report_log_snapshot", lambda: ("日志快照", ("log.txt", b"log", "text/plain")))
        monkeypatch.setattr(
            _FakeContactForm,
            "_fatal_crash_log_payload",
            staticmethod(lambda: ("fatal_crash.log", ("fatal_crash.log", b"x", "text/plain"))),
        )

        payload, summary = form._build_bug_report_auto_files_payload()
        assert [item[0] for item in payload] == ["配置快照", "日志快照", "fatal_crash.log"]
        assert "fatal_crash.log：已附带" in summary

        assert form._renumber_files_payload(payload) == [
            ("file1", ("cfg.json", b"{}", "application/json")),
            ("file2", ("log.txt", b"log", "text/plain")),
            ("file3", ("fatal_crash.log", b"x", "text/plain")),
        ]
        assert form._validate_email("") is True
        assert form._validate_email("user@example.com") is True
        assert form._validate_email("bad@@mail") is False

    def test_export_snapshot_helpers(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        form = _FakeContactForm()
        form._config_snapshot_provider = lambda: SimpleNamespace(name="cfg")
        monkeypatch.setattr(contact_widget, "save_config", lambda cfg, path: Path(path).write_text("{}", encoding="utf-8"))
        monkeypatch.setattr(contact_widget.tempfile, "gettempdir", lambda: str(tmp_path))
        label, (file_name, data, mime) = form._export_bug_report_config_snapshot()
        assert label == "配置快照"
        assert file_name.endswith(".json")
        assert data == b"{}"
        assert mime == "application/json"

        monkeypatch.setattr(contact_widget, "export_full_log_to_file", lambda _root, path, fallback_records: Path(path).write_text("log", encoding="utf-8"))
        monkeypatch.setattr(contact_widget, "get_user_local_data_root", lambda: str(tmp_path))
        monkeypatch.setattr(contact_widget.LOG_BUFFER_HANDLER, "get_records", lambda: ["x"])
        label2, (file_name2, data2, mime2) = form._export_bug_report_log_snapshot()
        assert label2 == "日志快照"
        assert file_name2.endswith(".txt")
        assert data2 == b"log"
        assert mime2 == "text/plain"

        fatal = tmp_path / "fatal_crash.log"
        fatal.write_text("boom", encoding="utf-8")
        monkeypatch.setattr(contact_widget, "get_fatal_crash_log_path", lambda: str(fatal))
        assert form._fatal_crash_log_payload() == (
            "fatal_crash.log",
            ("fatal_crash.log", b"boom", "text/plain"),
        )

    def test_send_timeout_and_send_finished_cleanup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        form = _FakeContactForm()
        info_bar = _FakeInfoBar()
        monkeypatch.setattr(contact_widget, "InfoBar", info_bar)

        assert form._compute_send_timeout_fallback_ms(10) == 26500

        form.email_edit.setText("test@example.com")
        form._clear_email_selection()
        assert form.email_edit.selection == (0, 0)
        form._focus_send_button()
        assert form.send_btn.focused == 1

        form._current_has_email = True
        form.message_edit = _FakeTextEdit("msg")
        form.issue_title_edit.setText("bug")
        form.auto_attach_config_checkbox.setChecked(True)
        form.auto_attach_log_checkbox.setChecked(True)
        form._attachments = _FakeAttachments([("file1", ("a.png", b"1", "image/png"))])

        form._on_send_finished(True, "")
        assert form.sendSucceeded.calls == [()]
        assert info_bar.calls[-1][0] == "success"
        assert form.message_edit.toPlainText() == ""
        assert form.issue_title_edit.text() == ""

        form._on_send_finished(False, "炸了")
        assert info_bar.calls[-1][0] == "error"
        assert info_bar.calls[-1][1] == ("", "炸了")
        assert info_bar.calls[-1][2]["parent"] is form
        assert info_bar.calls[-1][2]["duration"] == 3000

    def test_find_controller_host_and_send_clicked_validations(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        form = _FakeContactForm()
        info_bar = _FakeInfoBar()
        monkeypatch.setattr(contact_widget, "InfoBar", info_bar)

        parent = SimpleNamespace(parentWidget=lambda: None, controller=True)
        form.parent_widget = parent
        assert form._find_controller_host() is form

        form._on_send_clicked()
        assert info_bar.calls[-1][1][1] == "请输入消息内容"

        form.message_edit = _FakeTextEdit("hello")
        form.email_edit.setText("bad-email")
        form._on_send_clicked()
        assert info_bar.calls[-1][1][1] == "邮箱格式不正确"
