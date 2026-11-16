from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation
from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentWindow, InfoBarPosition
from shiboken6 import isValid

from software.ui.helpers.message_bar import replace_message_bar, show_message_bar
from software.ui.shell.main_window import MainWindow
from software.ui.widgets.indeterminate_progress import IndeterminateProgressBar


def test_application_notification_stack_handles_multiple_bars_and_resize(qtbot) -> None:
    host = QWidget()
    host.resize(520, 260)
    host.show()
    qtbot.addWidget(host)

    first = show_message_bar(
        parent=host,
        title="",
        message="第一条通知",
        level="info",
        position=InfoBarPosition.TOP,
        duration=-1,
    )
    second = show_message_bar(
        parent=host,
        title="警告",
        message="第二条通知包含更长的文本用于检查换行表现",
        level="warning",
        position=InfoBarPosition.TOP,
        duration=-1,
    )
    qtbot.waitUntil(lambda: first.isVisible() and second.isVisible(), timeout=1000)
    assert first.parentWidget() is host
    assert second.parentWidget() is host
    assert first.y() < second.y()

    host.resize(360, 260)
    qtbot.waitUntil(lambda: first.width() <= 360 and second.width() <= 360, timeout=1000)
    replace_message_bar(first)
    qtbot.waitUntil(lambda: not isValid(first), timeout=1000)
    replace_message_bar(second)
    qtbot.waitUntil(lambda: not isValid(second), timeout=1000)


def test_application_indeterminate_progress_bar_resumes_from_stopped_and_paused(qtbot) -> None:
    bar = IndeterminateProgressBar(start=False)
    qtbot.addWidget(bar)
    bar.show()

    bar.resume()
    qtbot.waitUntil(
        lambda: bar.aniGroup.state() == QAbstractAnimation.State.Running,
        timeout=1000,
    )
    bar.setPaused(True)
    qtbot.waitUntil(
        lambda: bar.aniGroup.state() == QAbstractAnimation.State.Paused,
        timeout=1000,
    )
    bar.setPaused(False)
    qtbot.waitUntil(
        lambda: bar.aniGroup.state() == QAbstractAnimation.State.Running,
        timeout=1000,
    )
    bar.stop()
    qtbot.waitUntil(
        lambda: bar.aniGroup.state() == QAbstractAnimation.State.Stopped,
        timeout=1000,
    )
    bar.resume()
    qtbot.waitUntil(
        lambda: bar.aniGroup.state() == QAbstractAnimation.State.Running,
        timeout=1000,
    )


def test_main_window_starts_without_mutating_qfluent_classes(monkeypatch, qtbot) -> None:
    monkeypatch.setenv("WJX_IMPORT_CHECK", "1")
    window = MainWindow()
    window._schedule_deferred_close_confirmation = lambda: None
    window.controller.request_shutdown_for_close = lambda timeout_seconds=5.0: None

    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.isVisible(), timeout=1000)

    assert window.windowTitle().startswith("SurveyController v")
    assert isinstance(window, FluentWindow)
    assert window.navigationInterface is not None
    assert 48 < window.navigationInterface.width() <= 193
    assert window.stackedWidget.count() >= 3
    assert window.workbench is not None

    window._close_request_confirmed = True
    window.close()
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=1000)
