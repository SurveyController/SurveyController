from __future__ import annotations

import threading

from software.core.engine.runtime_actions import RuntimeActionKind, RuntimeActionRequest, RuntimeActionResult
from software.ui.controller.engine_adapter import EngineGuiAdapter


class EngineGuiAdapterLargeTests:
    def _build_adapter(self, *, dispatcher=None, async_dispatcher=None) -> EngineGuiAdapter:
        return EngineGuiAdapter(
            dispatcher=dispatcher or (lambda callback: callback()),
            async_dispatcher=async_dispatcher or (lambda callback: callback()),
            stop_signal=threading.Event(),
        )

    def test_dispatch_fallbacks_and_pause_controls(self) -> None:
        events: list[str] = []
        adapter = self._build_adapter(
            dispatcher=lambda callback: (_ for _ in ()).throw(RuntimeError("ui down")),
            async_dispatcher=lambda callback: (_ for _ in ()).throw(RuntimeError("ui async down")),
        )

        adapter.dispatch_to_ui(lambda: events.append("sync"))
        adapter.dispatch_to_ui_async(lambda: events.append("async"))
        assert events == ["sync", "async"]

        adapter.pause_run("维护中")
        assert adapter.is_paused() is True
        assert adapter.get_pause_reason() == "维护中"
        adapter.resume_run()
        assert adapter.is_paused() is False

    def test_wait_stop_bind_ui_callbacks_and_dialogs(self) -> None:
        counters: list[tuple[float, float, bool]] = []
        loading: list[tuple[bool, str]] = []
        messages: list[tuple[str, str, str]] = []
        confirmed: list[tuple[str, str]] = []
        stop_signal = threading.Event()
        adapter = EngineGuiAdapter(
            dispatcher=lambda callback: callback(),
            async_dispatcher=lambda callback: callback(),
            stop_signal=stop_signal,
        )
        adapter.bind_ui_callbacks(
            quota_request_form_opener=lambda: True,
            on_ip_counter=lambda used, total, custom_api: counters.append((used, total, custom_api)),
            on_random_ip_loading=lambda enabled, message: loading.append((enabled, message)),
            message_handler=lambda title, message, level: messages.append((title, message, level)),
            confirm_handler=lambda title, message: confirmed.append((title, message)) or True,
        )

        wait_signal = threading.Event()
        wait_signal.set()
        adapter.pause_run("pause")
        adapter.wait_if_paused(wait_signal)
        adapter.resume_run()
        adapter.stop_run()

        assert adapter.open_quota_request_form() is True
        adapter.update_random_ip_counter(1, 5, True)
        adapter.set_random_ip_loading(True, "syncing")
        adapter.show_message_dialog("提示", "内容", level="warning")
        assert adapter.show_confirm_dialog("确认", "继续") is True
        adapter.set_random_ip_enabled(True)

        assert stop_signal.is_set()
        assert counters == [(1.0, 5.0, True)]
        assert loading == [(True, "syncing")]
        assert messages == [("提示", "内容", "warning")]
        assert confirmed == [("确认", "继续")]
        assert adapter.is_random_ip_enabled() is True

    def test_runtime_actions_are_handled_by_adapter(self) -> None:
        messages: list[tuple[str, str, str]] = []
        confirms: list[tuple[str, str]] = []
        toggles: list[bool] = []
        adapter = EngineGuiAdapter(
            dispatcher=lambda callback: callback(),
            async_dispatcher=lambda callback: callback(),
            stop_signal=threading.Event(),
            message_handler=lambda title, message, level: messages.append((title, message, level)),
            confirm_handler=lambda title, message: confirms.append((title, message)) or True,
        )
        adapter.bind_runtime_actions(
            toggle_random_ip=lambda enabled: toggles.append(bool(enabled)) or bool(enabled),
        )

        adapter.handle_runtime_actions(
            RuntimeActionResult.from_actions(
                [
                    RuntimeActionRequest(RuntimeActionKind.PAUSE_RUN, reason="触发智能验证"),
                    RuntimeActionRequest(RuntimeActionKind.SHOW_MESSAGE, "提示", "内容", "warning"),
                    RuntimeActionRequest(RuntimeActionKind.CONFIRM_ENABLE_RANDOM_IP, "确认", "启用吗", "warning"),
                ]
            )
        )

        assert adapter.is_paused()
        assert adapter.get_pause_reason() == "触发智能验证"
        assert messages == [("提示", "内容", "warning")]
        assert confirms == [("确认", "启用吗")]
        assert toggles == [True]
