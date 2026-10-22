from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from threading import Event
from types import SimpleNamespace

import pytest

from CI.unit_tests.application.fakes import FakeEngine, FakePreferences, FakeRepository, Harness
from software.application.configuration import ConfigurationService
from software.application.errors import ProxyAuthenticationError
from software.application.events import ApplicationEventType
from software.application.interactions import InteractionKind, InteractionRequest
from software.application.preferences import PreferencesService
from software.application.run_parts import runtime_shutdown
from software.application.run_state_store import RunStateStore
from software.application.survey_parse_service import SurveyParseService
from software.core.config.schema import RuntimeConfig
from software.core.engine.execution_artifacts import RuntimePreparationError
from software.providers.contracts import (
    ProviderErrorCategory,
    ProviderFailure,
    ProviderParseResult,
)
from surveycore.providers.contracts import SurveyDefinition, SurveyQuestionMeta
from surveycore.providers.errors import SurveyPausedError


def test_configuration_and_preferences_use_injected_ports():
    repository = FakeRepository()
    configuration = ConfigurationService(repository)
    store = FakePreferences()
    preferences = PreferencesService(store)
    loaded = configuration.load("old.json", strict=True)
    assert configuration.save(loaded, "next.json") == "next.json"
    assert repository.load_args == ("old.json", True)
    assert repository.saved == (loaded, "next.json")
    preferences.set("config_directory", "D:/configs")
    assert preferences.get("config_directory") == "D:/configs"
    preferences.remove("config_directory")
    preferences.set("window_topmost", True)
    preferences.reset()
    assert store.values == {}
    assert store.sync_count == 4


def test_start_pause_resume_stop_and_close():
    harness = Harness()
    try:
        harness.start()
        service = harness.service
        assert service.running
        assert harness.state.get_runtime_snapshot()["progress"]["target"] == 3
        config, state, bridge = harness.engine.starts[0]
        assert config.num_threads == 2
        assert bridge is service.runtime_port
        assert state is service._execution_state
        service.start_run(RuntimeConfig())
        assert len(harness.engine.starts) == 1
        service.pause_run("等待继续")
        assert harness.state.get_runtime_snapshot()["phase"] == "paused"
        assert harness.engine.pause_calls == ["等待继续"]
        service.resume_run()
        assert harness.state.get_runtime_snapshot()["phase"] == "running"
        assert not bridge.is_paused()
        service.stop_run()
        assert service.stop_event.is_set()
        assert harness.engine.stop_calls == 1
        assert harness.state.get_runtime_snapshot()["phase"] == "stopping"
        harness.finish(category="user_stopped")
        assert harness.state.get_runtime_snapshot()["phase"] == "finished"
    finally:
        harness.close()
    assert harness.engine.shutdown_calls


@pytest.mark.parametrize("preparation_error", [RuntimePreparationError("配置无效"), ValueError("损坏")])
def test_preparation_failure_never_starts_engine(preparation_error):
    def fail(*args, **kwargs):
        raise preparation_error

    harness = Harness(fail)
    try:
        harness.start()
        snapshot = harness.state.get_runtime_snapshot()
        assert snapshot["phase"] == "failed"
        assert snapshot["terminal_stop"]["category"] == "run_preparation_failed"
        assert not snapshot["initialization"]["active"]
        assert not harness.engine.starts
        assert harness.events[-1].type == "run_failed"
    finally:
        harness.close()


def test_engine_initialization_failure_resets_state_and_schedules_cleanup():
    harness = Harness()
    harness.engine.start_error = RuntimeError("engine init")
    try:
        harness.start()
        assert harness.state.get_runtime_snapshot()["terminal_stop"]["category"] == "engine_start_failed"
        assert not harness.service.running
        assert harness.service.stop_event.is_set()
        assert len(harness.cleanup.tasks) == 1
    finally:
        harness.close()


def test_stop_during_preparation_ignores_late_result():
    entered, release = Event(), Event()

    def slow_prepare(config, **kwargs):
        from CI.unit_tests.application.fakes import prepare
        entered.set()
        assert release.wait(2)
        return prepare(config, **kwargs)

    harness = Harness(slow_prepare)
    try:
        harness.service.start_run(RuntimeConfig())
        assert entered.wait(2)
        harness.service.stop_run()
        assert harness.state.get_runtime_snapshot()["terminal_stop"]["category"] == "user_stopped"
        release.set()
        harness.service._init_gate_thread.join(2)
        harness.drain()
        assert not harness.engine.starts
        assert not harness.service.is_initializing()
    finally:
        release.set()
        harness.close()


def test_target_completion_cleans_once_and_keeps_semantic_snapshot():
    harness = Harness()
    try:
        harness.start()
        harness.service._execution_state.cur_num = 3
        harness.finish()
        harness.service.emit_status_snapshot()
        snapshot = harness.state.get_runtime_snapshot()
        assert snapshot["phase"] == "finished"
        assert snapshot["progress"]["current"] == 3
        assert snapshot["terminal_stop"]["category"] == "target_reached"
        assert "status_text" not in snapshot
        assert "text" not in snapshot["initialization"]
        assert len(harness.cleanup.tasks) == 1
        assert harness.requests == []
        harness.cleanup.tasks[0][0]()
        harness.drain()
        assert harness.events[-1].type == "cleanup_finished"
    finally:
        harness.close()


@pytest.mark.parametrize("category,reason", [
    ("runtime_failed", "other"),
    ("ai_unstable", ""),
    ("submission_verification", ""),
])
def test_failure_stop_preserves_engine_reason_without_feedback_request(category, reason):
    harness = Harness()
    try:
        harness.start()
        harness.service._execution_state.cur_fail = 5
        harness.finish(category=category, reason=reason)
        snapshot = harness.state.get_runtime_snapshot()
        assert snapshot["phase"] == "failed"
        assert snapshot["progress"]["consecutive_failures"] == 5
        assert snapshot["terminal_stop"]["failure_reason"] == reason
        harness.service._emit_terminal_notice_if_needed()
        assert harness.requests == []
        expected_event_type = {
            "ai_unstable": ApplicationEventType.AI_UNSTABLE,
            "submission_verification": ApplicationEventType.SUBMISSION_VERIFICATION_REQUIRED,
        }.get(category)
        if expected_event_type is not None:
            assert harness.events[-1].type == expected_event_type
    finally:
        harness.close()


def test_engine_future_failure_is_not_reported_as_success():
    harness = Harness()
    try:
        harness.start()
        harness.finish(category="", error=RuntimeError("engine crashed"))
        snapshot = harness.state.get_runtime_snapshot()
        assert snapshot["phase"] == "failed"
        assert snapshot["terminal_stop"]["category"] == "engine_failed"
        assert harness.events[0].payload["code"] == "engine_failed"
    finally:
        harness.close()


def test_close_cancels_interactions_and_cleans_resources_once():
    harness = Harness()
    closed = []
    harness.service.runtime_port.register_cleanup_target(SimpleNamespace(quit=lambda: closed.append(True)))
    request = InteractionRequest.create(InteractionKind.QUOTA, "random_ip_required")
    reply = harness.interactions.request(request)
    harness.close()
    assert reply.result(timeout=0) is False
    assert closed == [True]
    harness.service.shutdown_for_close(0)
    assert closed == [True]


def test_shutdown_requests_engine_close_before_joining_engine_thread(monkeypatch):
    order = []

    class EngineThread(threading.Thread):
        def __init__(self):
            super().__init__(name="AsyncRuntimeEngine")
            self.alive = True

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            order.append("join")

    thread = EngineThread()
    engine = FakeEngine()
    engine.thread = thread
    monkeypatch.setattr(runtime_shutdown, "collect_shutdown_threads", lambda _service: [thread])
    original_shutdown = engine.shutdown

    def shutdown(*, timeout=5.0):
        order.append("shutdown")
        thread.alive = False
        original_shutdown(timeout=timeout)

    engine.shutdown = shutdown
    harness = Harness()
    harness.service._async_engine_client = engine
    harness.service.worker_threads = [thread]
    try:
        assert runtime_shutdown.shutdown_for_close(harness.service, timeout_seconds=0.05)
        assert order[0] == "shutdown"
        assert "join" not in order
    finally:
        harness.drain()


def test_close_waits_for_shutdown_worker_completion():
    harness = Harness()
    try:
        harness.service.request_shutdown_for_close(timeout_seconds=1.0)
        assert harness.service.wait_for_shutdown(timeout_seconds=2.0)
    finally:
        harness.drain()


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [True, False])
async def test_proxy_quota_waits_for_the_matching_ui_reply(accepted):
    harness = Harness()

    async def already_claimed():
        raise ProxyAuthenticationError("trial_already_claimed")

    harness.service._proxy_gateway.activate_trial = already_claimed
    pending = asyncio.create_task(harness.service._ensure_random_ip_ready_async(harness.service.adapter))
    try:
        await asyncio.sleep(0)
        request = next(request for request in harness.requests if request.kind == InteractionKind.QUOTA)
        assert not pending.done()
        harness.interactions.resolve(request.request_id, accepted)
        assert await asyncio.wait_for(pending, timeout=2) is accepted
    finally:
        harness.close()
        await asyncio.gather(pending, return_exceptions=True)


def test_parse_success_failure_invalid_url_and_engine_submission_failure(caplog):
    state = RunStateStore()
    engine = FakeEngine()
    service = SurveyParseService(async_engine_client=engine, state_store=state,
        emit_event=lambda event: None, dispatch_async=lambda callback: callback())
    service.parse_survey("")
    assert state.get_survey_snapshot()["error_code"] == "url_required"
    service.parse_survey("https://example.com")
    assert state.get_survey_snapshot()["error_code"] == "url_unsupported"
    service.parse_survey("https://v.wjx.cn/vm/demo.aspx")
    engine.parse_future.set_result(
        ProviderParseResult(
            provider="wjx",
            definition=SimpleNamespace(title="Demo", provider="wjx", questions=[]),
        )
    )
    assert state.get_survey_snapshot()["survey_title"] == "Demo"
    engine.parse_future = Future()
    service.parse_survey("https://v.wjx.cn/vm/demo.aspx")
    failure = RuntimeError("provider unavailable")
    engine.parse_future.set_result(
        ProviderParseResult(
            provider="wjx",
            failure=ProviderFailure(
                provider="wjx",
                category=ProviderErrorCategory.UNAVAILABLE,
                message=str(failure),
                exception=failure,
            ),
        )
    )
    assert state.get_survey_snapshot()["parse_error"] == "provider unavailable"
    assert any("category=unavailable" in record.message for record in caplog.records)
    assert failure.__notes__ == ["provider=wjx; category=unavailable"]
    engine.parse_future = Future()
    service.parse_survey("https://v.wjx.cn/vm/demo.aspx")
    engine.parse_future.set_exception(RuntimeError("unavailable"))
    assert state.get_survey_snapshot()["parse_error"] == "unavailable"
    engine.parse_error = RuntimeError("not initialized")
    service.parse_survey("https://v.wjx.cn/vm/demo.aspx")
    assert state.get_survey_snapshot()["phase"] == "error"


@pytest.mark.parametrize("provider,url", [
    ("wjx", "https://v.wjx.cn/vm/demo.aspx"), ("qq", "https://wj.qq.com/s2/123456/Abcd"),
])
def test_parse_filters_descriptions_and_updates_provider(provider, url):
    state, engine = RunStateStore(), FakeEngine()
    service = SurveyParseService(async_engine_client=engine, state_store=state,
        emit_event=lambda event: None, dispatch_async=lambda callback: callback())
    question = SurveyQuestionMeta(num=1, title="Q1", type_code="3", options=2, provider=provider)
    description = SurveyQuestionMeta(num=2, title="说明", is_description=True, provider=provider)
    service.parse_survey(url)
    engine.parse_future.set_result(
        ProviderParseResult(
            provider=provider,
            definition=SurveyDefinition(
                provider=provider,
                title="问卷",
                questions=[question, description],
            ),
        )
    )
    snapshot = state.get_survey_snapshot()
    assert len(snapshot["questions_info"]) == 1
    assert snapshot["questions_info"][0].title == "Q1"
    assert len(snapshot["question_entries"]) == 1
    assert state.runtime_settings()["survey_provider"] == provider
    engine.parse_future = Future()
    service.parse_survey(url)
    engine.parse_future.set_exception(SurveyPausedError("暂停中"))
    assert state.get_survey_snapshot()["parse_error"] == "暂停中"


def test_delayed_cleanup_remains_bound_to_finished_run():
    harness = Harness()
    first_closed, second_closed = [], []
    first_port = harness.service.runtime_port
    first_port.register_cleanup_target(SimpleNamespace(quit=lambda: first_closed.append(True)))
    harness.service._schedule_cleanup()
    from software.application.runtime_port import RunRuntimePort
    second_port = RunRuntimePort(stop_signal=Event(), notify_random_ip_loading=lambda *args: None,
        handle_random_ip_submission=lambda **kwargs: None)
    second_port.register_cleanup_target(SimpleNamespace(quit=lambda: second_closed.append(True)))
    harness.service.runtime_port = second_port
    harness.cleanup.tasks[0][0]()
    harness.drain()
    assert first_closed == [True]
    assert second_closed == []
    assert harness.events == []
    harness.close()
    assert second_closed == [True]


def test_preparation_dispatch_failure_records_failure_without_calling_ui():
    harness = Harness()

    def unavailable(callback):
        raise RuntimeError("dispatcher closed")

    harness.service._dispatch_async = unavailable
    harness.service.start_run(RuntimeConfig())
    harness.service._init_gate_thread.join(2)
    assert harness.state.get_runtime_snapshot()["terminal_stop"]["category"] == "dispatch_failed"
    assert len(harness.snapshots) >= 1
    assert harness.snapshots[-1]["phase"] == "initializing"
    assert not harness.engine.starts
    assert harness.service.stop_event.is_set()
    harness.close()


def test_prepared_config_is_cloned_before_injecting_proxy_leases():
    from software.core.engine.execution_artifacts import PreparedExecutionArtifacts
    from software.core.task import ExecutionConfig, ProxyLease

    harness = Harness()
    template = ExecutionConfig(random_proxy_ip_enabled=True, single_prob=[[1.0, 0.0]])
    harness.service._prepared_execution_artifacts = PreparedExecutionArtifacts(
        execution_config_template=template, survey_provider="wjx", question_entries=[],
        questions_info=[], reverse_fill_spec=None,
    )
    lease = ProxyLease(address="127.0.0.1:8080")
    config, state = harness.service._prepare_engine_state([lease])
    assert config is not template
    assert config.proxy_ip_pool == [lease]
    assert state.config is config
    template.single_prob[0][0] = 0.0
    assert config.single_prob[0][0] == 1.0
    harness.close()


def test_run_completion_dispatch_failure_cleans_without_emitting_from_worker():
    harness = Harness()
    try:
        harness.start()
        harness.drain()
        delivered = len(harness.snapshots)

        def unavailable(callback):
            raise RuntimeError("dispatcher closed")

        harness.service._dispatch_async = unavailable
        harness.finish()
        snapshot = harness.state.get_runtime_snapshot()
        assert snapshot["phase"] == "failed"
        assert snapshot["terminal_stop"]["category"] == "dispatch_failed"
        assert not harness.service.running
        assert len(harness.cleanup.tasks) == 1
        assert len(harness.snapshots) == delivered
        assert harness.events == []
    finally:
        harness.close()


def test_queued_cleanup_notification_does_not_affect_a_new_run():
    harness = Harness()
    try:
        harness.service._schedule_cleanup()
        harness.cleanup.tasks[0][0]()
        harness.start()
        assert harness.service.running
        assert harness.events == []
    finally:
        harness.close()


def test_close_drops_queued_proxy_state_and_ui_events():
    harness = Harness()
    harness.service.apply_runtime_patch({"random_ip": {"used_quota": 9}})
    from software.application.events import event_payload
    harness.service.emit_event(event_payload("cleanup_finished"))
    harness.close()
    assert harness.state.get_runtime_snapshot()["random_ip"]["used_quota"] == 0
    assert harness.events == []
    assert harness.snapshots == []


def test_parse_dispatch_failure_and_close_never_apply_late_results():
    state, engine = RunStateStore(), FakeEngine()

    def unavailable(callback):
        raise RuntimeError("dispatcher closed")

    service = SurveyParseService(async_engine_client=engine, state_store=state,
        emit_event=lambda event: None, dispatch_async=unavailable)
    service.parse_survey("https://v.wjx.cn/vm/demo.aspx")
    engine.parse_future.set_result(
        ProviderParseResult(
            provider="wjx",
            definition=SurveyDefinition(provider="wjx", title="late", questions=[]),
        )
    )
    assert state.get_survey_snapshot()["error_code"] == "dispatch_failed"
    engine.parse_future = Future()
    service.parse_survey("https://v.wjx.cn/vm/demo.aspx")
    service.close()
    assert engine.parse_future.cancelled()
    assert state.get_survey_snapshot()["phase"] == "parsing"
