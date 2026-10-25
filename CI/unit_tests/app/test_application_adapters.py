from __future__ import annotations

import json
import threading
from concurrent.futures import Future

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage

from CI.unit_tests.application.fakes import FakeCleanup, FakeEngine, FakePreferences
from software.app.bootstrap import create_application_dependencies
from software.app.preferences_adapter import QSettingsPreferences
from software.application.configuration import ConfigurationService
from software.application.events import event_payload
from software.application.interactions import InteractionBroker, InteractionKind, InteractionRequest
from software.application.preferences import PreferencesService
from software.application.run_state_store import RunStateStore
from software.core.config.codec import serialize_runtime_config
from software.core.config.schema import RuntimeConfig
from software.io.config.repository import JsonConfigRepository
from software.ui.adapters.qr_image import qr_pixel_buffer
from software.ui.controller.presentation import interaction_view, runtime_view, survey_view
from software.ui.controller.run_controller import RunController
from software.ui.controller.ui_dispatcher import UiCallbackDispatcher, UiDispatchError


def test_qsettings_adapter_keeps_existing_keys_and_python_values(tmp_path):
    path = str(tmp_path / "preferences.ini")
    old = QSettings(path, QSettings.Format.IniFormat)
    old.setValue("config_directory", "D:/已有配置")
    old.setValue("ai/provider", "custom")
    old.setValue("window_topmost", True)
    old.sync()
    preferences = PreferencesService(
        QSettingsPreferences(QSettings(path, QSettings.Format.IniFormat))
    )
    assert preferences.get("config_directory") == "D:/已有配置"
    assert preferences.get("ai/provider") == "custom"
    preferences.set("auto_save_log_retention_count", 20)
    assert old.value("auto_save_log_retention_count") == 20
    assert old.value("window_topmost") is True


def test_configuration_adapter_reads_existing_python_json_and_preserves_strict_errors(tmp_path):
    path = tmp_path / "saved.json"
    config = RuntimeConfig(url="https://wj.qq.com/s2/demo", target=7, threads=3)
    path.write_text(
        "// existing Python config\n" + json.dumps(serialize_runtime_config(config)),
        encoding="utf-8",
    )
    service = ConfigurationService(JsonConfigRepository())
    loaded = service.load(str(path), strict=True)
    assert loaded.target == 7
    assert loaded.url == config.url
    new_path = str(tmp_path / "new.json")
    assert service.save(loaded, new_path) == new_path
    expected_payload = json.loads(json.dumps(serialize_runtime_config(loaded)))
    assert json.loads((tmp_path / "new.json").read_text(encoding="utf-8")) == expected_payload
    path.write_text("{invalid", encoding="utf-8")
    with pytest.raises(ValueError, match="读取配置失败"):
        service.load(str(path), strict=True)


def test_ai_adapter_uses_injected_preferences_and_existing_keys():
    from software.app.ai_settings_adapter import PythonAiSettingsAdapter

    store = FakePreferences()
    store.setValue("ai/provider", "custom")
    store.setValue("ai/api_key", "legacy-key")
    store.setValue("ai/base_url", "https://example.test/v1")
    store.setValue("ai/model", "test-model")
    create_application_dependencies(
        runtime_engine=FakeEngine(), cleanup_runner=FakeCleanup(), preference_store=store
    )
    adapter = PythonAiSettingsAdapter()
    assert adapter.get_settings()["api_key"] == ""
    adapter.save_settings(api_key="fake-key")
    assert adapter.get_settings()["api_key"] == "fake-key"
    adapter.save_settings(model="next-model")
    assert store.values["ai/model"] == "next-model"
    adapter.reset_settings()
    assert store.values == {"ai/api_key": "legacy-key"}


def test_qt_controller_preserves_queued_snapshot_and_event_order(qtbot):
    dependencies = create_application_dependencies(
        runtime_engine=FakeEngine(),
        cleanup_runner=FakeCleanup(),
        preference_store=FakePreferences(),
    )
    controller = RunController(dependencies=dependencies)
    observed = []
    controller.runtimeSnapshotChanged.connect(lambda snapshot: observed.append(("state", snapshot)))
    controller.controllerEvent.connect(lambda event: observed.append(("event", event)))

    def worker():
        controller._command_service.apply_runtime_patch(
            {"phase": "initializing", "initialization": {"active": True, "stage": "preparing"}}
        )
        controller._command_service.emit_event(event_payload("cleanup_finished"))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(2)
    qtbot.waitUntil(lambda: len(observed) == 2)
    assert [kind for kind, _ in observed] == ["state", "event"]
    assert observed[0][1]["status_text"] == "正在初始化"
    assert observed[0][1]["initialization"]["logs"] == ["正在初始化"]
    assert observed[1][1] == {"type": "cleanup_finished"}
    controller._command_service.shutdown_for_close(0)


def test_controller_submits_random_ip_health_check_to_engine(monkeypatch) -> None:
    engine = FakeEngine()
    submitted: list[str] = []
    task_future: Future[object] = Future()
    monkeypatch.setattr(
        engine,
        "submit_ui_task",
        lambda name, _factory: submitted.append(name) or task_future,
    )

    class FakeHealth:
        async def check(self) -> dict[str, str]:
            return {"level": "success"}

    dependencies = create_application_dependencies(
        runtime_engine=engine,
        cleanup_runner=FakeCleanup(),
        preference_store=FakePreferences(),
        random_ip_health=FakeHealth(),
    )
    controller = RunController(dependencies=dependencies)

    assert controller.submit_random_ip_health_check() is task_future
    assert submitted == ["random-ip-health-check"]
    controller._command_service.shutdown_for_close(0)


def test_qt_controller_responds_to_application_interaction(qtbot):
    dependencies = create_application_dependencies(
        runtime_engine=FakeEngine(),
        cleanup_runner=FakeCleanup(),
        preference_store=FakePreferences(),
    )
    controller = RunController(dependencies=dependencies)
    events = []
    controller.controllerEvent.connect(events.append)
    request = InteractionRequest.create(InteractionKind.QUOTA, "random_ip_required")
    reply = controller._interactions.request(request)
    assert events[-1]["type"] == "open_quota_request_form"
    assert not reply.done()
    controller.respond_to_interaction(events[-1]["request_id"], True)
    assert reply.result(0) is True
    controller._command_service.shutdown_for_close(0)


@pytest.mark.parametrize(
    "phase,prefix",
    [
        ("running", "已提交"),
        ("paused", "已暂停"),
        ("stopping", "正在停止"),
        ("finished", "已提交"),
        ("failed", "已提交"),
    ],
)
def test_semantic_snapshot_maps_to_existing_page_data(phase, prefix):
    state = RunStateStore()
    state.apply_runtime_patch(
        {
            "phase": phase,
            "running": phase in {"running", "paused", "stopping"},
            "paused": phase == "paused",
            "stopping": phase == "stopping",
            "pause_reason": "等待",
            "progress": {
                "current": 2,
                "target": 5,
                "consecutive_failures": 1,
                "device_quota_fail_count": 1,
            },
            "random_ip": {"loading": True, "loading_stage": "syncing_quota"},
        }
    )
    view = runtime_view(state.get_runtime_snapshot())
    assert view["status_text"].startswith(f"{prefix} 2/5 份")
    assert "设备限制拦截 1 次" in view["status_text"]
    assert view["random_ip"]["loading_message"] == "正在同步服务端额度..."
    if phase == "paused":
        assert view["status_text"].endswith(" | 等待")
    assert "status_text" not in state.get_runtime_snapshot()
    assert (
        survey_view({"phase": "error", "error_code": "url_required"})["parse_error"]
        == "请填写问卷链接"
    )


def test_dispatch_signal_failure_cancels_queued_work_and_never_runs_on_worker(qtbot):
    def fail():
        raise RuntimeError("receiver destroyed")

    dispatcher = UiCallbackDispatcher(fail)
    calls, errors = [], []

    def worker():
        try:
            dispatcher.dispatch_async(lambda: calls.append(threading.get_ident()))
        except UiDispatchError as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(2)
    dispatcher.drain()
    assert len(errors) == 1
    assert calls == []


def test_interaction_dispatch_failure_resolves_rejected_without_hanging():
    def fail(request):
        raise UiDispatchError("closed")

    broker = InteractionBroker(fail)
    reply = broker.request(InteractionRequest.create(InteractionKind.QUOTA, "random_ip_required"))
    assert reply.result(timeout=0) is False


def test_notice_maps_to_existing_dialog_event():
    request = InteractionRequest.create(InteractionKind.NOTICE, "quota_exhausted", level="warning")
    view = interaction_view(request)
    assert view["request_id"] == request.request_id
    assert view["type"] == "dialog_message"
    assert view["message"] == "随机IP已用额度已达到上限，请先补充额度后再启用。"
    assert view["level"] == "warning"


def test_qimage_conversion_owns_pixels_and_removes_row_padding(tmp_path):
    image = QImage(3, 2, QImage.Format.Format_Grayscale8)
    image.fill(127)
    pixels = qr_pixel_buffer(image)
    assert pixels is not None
    assert pixels.shape == (2, 3)
    assert pixels.tobytes() == bytes([127] * 6)
    image.fill(0)
    assert pixels.tobytes() == bytes([127] * 6)
    path = str(tmp_path / "image.png")
    assert image.save(path)
    loaded_pixels = qr_pixel_buffer(path)
    assert loaded_pixels is not None
    assert loaded_pixels.tobytes() == bytes(6)
    assert qr_pixel_buffer(QImage()) is None
