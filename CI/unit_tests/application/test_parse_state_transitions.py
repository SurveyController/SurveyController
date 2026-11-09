from __future__ import annotations

from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from CI.unit_tests.application.fakes import FakeEngine
from software.application.run_state_store import RunStateStore
from software.application.survey_parse_service import SurveyParseService
from software.core.config.schema import RuntimeConfig
from software.providers.contracts import ProviderParseResult


@pytest.mark.parametrize("outcome", ["success", "failure", "queued_success", "queued_failure"])
@pytest.mark.parametrize("entry_point", ["service", "controller"])
def test_loading_config_rejects_previous_parse_results(outcome, entry_point, qtbot):
    engine = FakeEngine()
    callbacks = []
    controller = None
    if entry_point == "controller":
        from CI.unit_tests.application.fakes import FakeCleanup, FakePreferences
        from software.app.bootstrap import create_application_dependencies
        from software.ui.controller.run_controller import RunController

        controller = RunController(
            dependencies=create_application_dependencies(
                runtime_engine=engine,
                cleanup_runner=FakeCleanup(),
                preference_store=FakePreferences(),
            )
        )
        service = controller._parse_service
        state = controller._state_store
        hydrate = controller.hydrate_from_config
        service._dispatch_async = callbacks.append
    else:
        state = RunStateStore()
        service = SurveyParseService(
            async_engine_client=engine,
            state_store=state,
            emit_event=lambda event: None,
            dispatch_async=callbacks.append,
        )
        hydrate = service.hydrate_from_config

    service.parse_survey("https://v.wjx.cn/vm/previous.aspx")
    assert engine.parse_future.set_running_or_notify_cancel()

    def complete_parse():
        if outcome.endswith("success"):
            engine.parse_future.set_result(
                ProviderParseResult(
                    provider="wjx",
                    definition=SimpleNamespace(title="旧问卷", provider="wjx", questions=[]),
                )
            )
        else:
            engine.parse_future.set_exception(RuntimeError("旧问卷解析失败"))

    if outcome.startswith("queued_"):
        complete_parse()
        assert len(callbacks) == 1
    hydrate(
        RuntimeConfig(
            url="https://wj.qq.com/s2/loaded-config",
            survey_title="载入的问卷",
            survey_provider="qq",
        )
    )
    expected_survey = state.get_survey_snapshot()
    expected_runtime = state.get_runtime_snapshot()
    if not outcome.startswith("queued_"):
        complete_parse()
    for callback in callbacks:
        callback()

    assert state.get_survey_snapshot() == expected_survey
    assert state.get_runtime_snapshot() == expected_runtime
    service.close()
    if controller is not None:
        controller._command_service.shutdown_for_close(0)


def test_loading_config_cancels_pending_parse_and_allows_new_parse():
    state, engine = RunStateStore(), FakeEngine()
    service = SurveyParseService(
        async_engine_client=engine,
        state_store=state,
        emit_event=lambda event: None,
        dispatch_async=lambda callback: callback(),
    )
    service.parse_survey("https://v.wjx.cn/vm/previous.aspx")
    pending = engine.parse_future
    service.hydrate_from_config(RuntimeConfig(url="https://v.wjx.cn/vm/loaded.aspx"))

    assert pending.cancelled()
    assert state.get_survey_snapshot()["url"] == "https://v.wjx.cn/vm/loaded.aspx"
    engine.parse_future = Future()
    service.parse_survey("https://v.wjx.cn/vm/current.aspx")
    engine.parse_future.set_result(
        ProviderParseResult(
            provider="wjx",
            definition=SimpleNamespace(title="当前问卷", provider="wjx", questions=[]),
        )
    )

    snapshot = state.get_survey_snapshot()
    assert snapshot["phase"] == "ready"
    assert snapshot["url"] == "https://v.wjx.cn/vm/current.aspx"
    assert snapshot["survey_title"] == "当前问卷"
    service.close()
