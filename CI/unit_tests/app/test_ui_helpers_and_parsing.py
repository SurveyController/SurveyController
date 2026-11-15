from __future__ import annotations

import queue
import threading

import pytest
from PySide6.QtCore import QAbstractAnimation
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import IndeterminateProgressRing

import software.ui.controller.ui_dispatcher as ui_dispatcher_module
import software.ui.helpers.qfluent_compat as qfluent_compat


class _FakeQtApp:
    def processEvents(self) -> None:
        return


class UiHelperTests:
    def test_indeterminate_progress_ring_active_state_is_explicit(self, qtbot) -> None:
        parent = QWidget()
        parent.resize(240, 120)
        ring = IndeterminateProgressRing(parent, start=False)
        qtbot.addWidget(parent)
        parent.show()

        qfluent_compat.set_indeterminate_progress_ring_active(ring, True)
        assert ring.isVisible()
        assert ring.aniGroup.state() == QAbstractAnimation.State.Running

        qfluent_compat.set_indeterminate_progress_ring_active(ring, False)
        assert not ring.isVisible()
        assert ring.aniGroup.state() == QAbstractAnimation.State.Stopped
        assert ring.property("surveycontroller_active") is False

    def test_mask_dialog_parent_resolves_to_owner_window(self, qtbot, monkeypatch) -> None:
        window = QWidget()
        child = QWidget(window)
        qtbot.addWidget(window)

        assert qfluent_compat.resolve_mask_dialog_parent(child) is window
        monkeypatch.setattr(QApplication, "activeWindow", lambda: window)
        assert qfluent_compat.resolve_mask_dialog_parent(None) is window

    def test_ui_callback_dispatcher_covers_enqueue_drain_and_async_paths(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        emitted: list[str] = []
        dispatcher = ui_dispatcher_module.UiCallbackDispatcher(lambda: emitted.append("emit"))
        calls: list[str] = []

        assert dispatcher.enqueue(lambda: calls.append("queued")) is True
        dispatcher.drain()
        assert emitted == ["emit"]
        assert calls == ["queued"]

        dispatcher._queue.put_nowait("not-callable")
        dispatcher.drain()

        monkeypatch.setattr(ui_dispatcher_module.QCoreApplication, "instance", lambda: None)
        dispatcher.dispatch_async(lambda: calls.append("no-app"))

        monkeypatch.setattr(
            ui_dispatcher_module.QCoreApplication,
            "instance",
            lambda: _FakeQtApp(),
        )
        monkeypatch.setattr(ui_dispatcher_module.threading, "current_thread", threading.main_thread)
        dispatcher.dispatch_async(lambda: calls.append("main-thread"))

        queued: list = []
        monkeypatch.setattr(ui_dispatcher_module.threading, "current_thread", lambda: object())
        monkeypatch.setattr(dispatcher, "enqueue", lambda callback: queued.append(callback) or True)
        dispatcher.dispatch_async(lambda: calls.append("background"))
        assert len(queued) == 1
        queued[0]()

        assert calls == ["queued", "no-app", "main-thread", "background"]

    def test_ui_callback_dispatcher_handles_enqueue_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dispatcher = ui_dispatcher_module.UiCallbackDispatcher(lambda: None)

        def _boom(_callback) -> None:
            raise queue.Full

        monkeypatch.setattr(dispatcher._queue, "put_nowait", _boom)
        assert dispatcher.enqueue(lambda: None) is False
