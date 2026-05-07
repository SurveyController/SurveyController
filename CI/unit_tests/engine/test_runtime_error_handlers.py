from __future__ import annotations

import threading

from software.core.ai.runtime import AIRuntimeError
from software.core.engine import runtime_error_handlers
from software.core.engine.failure_reason import FailureReason
from software.core.engine.run_stop_policy import RunStopPolicy
from software.core.task import ExecutionConfig, ExecutionState


class RuntimeErrorHandlerTests:
    def test_ai_runtime_error_keeps_running_until_five_failures(self) -> None:
        config = ExecutionConfig(fail_threshold=5, stop_on_fail_enabled=True)
        state = ExecutionState(config=config)
        policy = RunStopPolicy(config, state)
        stop_signal = threading.Event()

        stopped = False
        for _ in range(runtime_error_handlers.AI_FILL_FAIL_THRESHOLD - 1):
            stopped = runtime_error_handlers.handle_ai_runtime_error(
                AIRuntimeError("AI 调用失败：临时故障"),
                stop_signal,
                thread_name="Worker-1",
                stop_policy=policy,
                state=state,
            )

        assert not stopped
        assert not stop_signal.is_set()
        assert state.cur_fail == runtime_error_handlers.AI_FILL_FAIL_THRESHOLD - 1
        assert state.get_terminal_stop_snapshot()[0] == ""

    def test_ai_runtime_error_stops_on_fifth_failure(self) -> None:
        config = ExecutionConfig(fail_threshold=5, stop_on_fail_enabled=True)
        state = ExecutionState(config=config, cur_fail=runtime_error_handlers.AI_FILL_FAIL_THRESHOLD - 1)
        policy = RunStopPolicy(config, state)
        stop_signal = threading.Event()

        stopped = runtime_error_handlers.handle_ai_runtime_error(
            AIRuntimeError("AI 调用失败：临时故障"),
            stop_signal,
            thread_name="Worker-1",
            stop_policy=policy,
            state=state,
        )

        assert stopped
        assert stop_signal.is_set()
        assert state.get_terminal_stop_snapshot()[0] == "free_ai_unstable"
        assert state.get_terminal_stop_snapshot()[1] == FailureReason.FILL_FAILED.value
