from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest

from software.providers.contracts import SurveyQuestionMeta
from tencent.provider import submission
from software.core.task import ExecutionConfig, ExecutionState


class _FakeDriver:
    def __init__(self) -> None:
        self.browser_name = "edge"
        self.session_id = "test-session"
        self.browser_pid: int | None = None
        self.browser_pids: set[int] = set()
        self.current_url = ""
        self.page = None
        self.page_source = ""
        self.title = ""

    def find_element(self, *_args, **_kwargs):
        raise RuntimeError("unused")

    def find_elements(self, *_args, **_kwargs):
        return []

    def execute_script(self, script: str, *args: Any):
        del script
        del args
        return None

    def get(self, *_args, **_kwargs) -> None:
        return None

    def set_window_size(self, *_args, **_kwargs) -> None:
        return None

    def refresh(self) -> None:
        return None

    def mark_cleanup_done(self) -> bool:
        return True

    def quit(self) -> None:
        return None


class TencentSubmissionTests:
    def test_submit_reads_runtime_state_when_submit_button_missing(self, patch_attrs) -> None:
        driver = _FakeDriver()
        reads: list[str] = []
        patch_attrs(
            (submission, "_click_submit_button", lambda *_args, **_kwargs: False),
            (submission, "_is_headless_mode", lambda _ctx: True),
            (submission, "HEADLESS_SUBMIT_INITIAL_DELAY", 0.0),
            (submission, "HEADLESS_SUBMIT_CLICK_SETTLE_DELAY", 0.0),
            (submission, "peek_qq_runtime_state", lambda _driver: reads.append("peek") or SimpleNamespace(page_index=2, page_question_ids=["q1"])),
        )

        with pytest.raises(Exception, match="Submit button not found"):
            submission.submit(driver, ctx=None, stop_signal=threading.Event())

        assert reads == ["peek"]

    def test_runtime_context_summary_reads_runtime_state_for_status_helpers(self, patch_attrs) -> None:
        driver = _FakeDriver()
        reads: list[str] = []
        patch_attrs(
            (submission, "peek_qq_runtime_state", lambda _driver: reads.append("peek") or None),
        )

        assert not submission.consume_submission_success_signal(driver)
        assert not submission.is_device_quota_limit_page(driver)
        assert reads == ["peek", "peek"]

    def test_attempt_submission_recovery_refills_questions_and_resubmits_once(self, patch_attrs) -> None:
        driver = _FakeDriver()
        state = ExecutionState(config=ExecutionConfig(survey_provider="qq"))
        state.config.questions_metadata = {
            3: SurveyQuestionMeta(num=3, title="Q3", provider="qq", provider_question_id="q3", required=True),
            4: SurveyQuestionMeta(num=4, title="Q4", provider="qq", provider_question_id="q4", required=True),
        }
        runtime_state = SimpleNamespace(
            page_index=1,
            page_question_ids=["q3", "q4"],
            psycho_plan="plan",
            submission_recovery_attempts=0,
        )
        refill_calls: list[tuple[list[int], str, Any]] = []
        submit_calls: list[str] = []
        patch_attrs(
            (submission, "qq_submission_requires_verification", lambda _driver: False),
            (submission, "peek_qq_runtime_state", lambda _driver: runtime_state),
            (submission, "_extract_submission_recovery_hint", lambda _driver: submission.SubmissionRecoveryHint((3, 4), "请填写")),
            (submission, "submit", lambda _driver, ctx=None, stop_signal=None: submit_calls.append(ctx.config.survey_provider if ctx else "")),
        )

        from tencent.provider import runtime as qq_runtime

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                qq_runtime,
                "refill_required_questions_on_current_page",
                lambda _driver, ctx, *, question_numbers, thread_name, psycho_plan: refill_calls.append((list(question_numbers), thread_name, psycho_plan)) or 2,
            )
            recovered = submission.attempt_submission_recovery(driver, state, None, threading.Event(), thread_name="Worker-1")

        assert recovered is True
        assert runtime_state.submission_recovery_attempts == 1
        assert refill_calls == [([3, 4], "Worker-1", "plan")]
        assert submit_calls == ["qq"]

    def test_attempt_submission_recovery_falls_back_to_current_page_required_questions(self, patch_attrs) -> None:
        driver = _FakeDriver()
        state = ExecutionState(config=ExecutionConfig(survey_provider="qq"))
        state.config.questions_metadata = {
            3: SurveyQuestionMeta(num=3, title="Q3", provider="qq", provider_question_id="q3", required=True),
            4: SurveyQuestionMeta(num=4, title="Q4", provider="qq", provider_question_id="q4", required=False),
        }
        runtime_state = SimpleNamespace(
            page_index=1,
            page_question_ids=["q3", "q4"],
            psycho_plan=None,
            submission_recovery_attempts=0,
        )
        refill_calls: list[list[int]] = []
        patch_attrs(
            (submission, "qq_submission_requires_verification", lambda _driver: False),
            (submission, "peek_qq_runtime_state", lambda _driver: runtime_state),
            (submission, "_extract_submission_recovery_hint", lambda _driver: submission.SubmissionRecoveryHint((), "此题必填")),
            (submission, "submit", lambda *_args, **_kwargs: None),
        )

        from tencent.provider import runtime as qq_runtime

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                qq_runtime,
                "refill_required_questions_on_current_page",
                lambda _driver, ctx, *, question_numbers, thread_name, psycho_plan: refill_calls.append(list(question_numbers)) or 1,
            )
            recovered = submission.attempt_submission_recovery(driver, state, None, threading.Event(), thread_name="Worker-1")

        assert recovered is True
        assert refill_calls == [[3]]

    def test_attempt_submission_recovery_stops_when_no_question_was_refilled(self, patch_attrs) -> None:
        driver = _FakeDriver()
        state = ExecutionState(config=ExecutionConfig(survey_provider="qq"))
        runtime_state = SimpleNamespace(
            page_index=1,
            page_question_ids=["q3"],
            psycho_plan=None,
            submission_recovery_attempts=0,
        )
        submit_calls: list[str] = []
        patch_attrs(
            (submission, "qq_submission_requires_verification", lambda _driver: False),
            (submission, "peek_qq_runtime_state", lambda _driver: runtime_state),
            (submission, "_extract_submission_recovery_hint", lambda _driver: submission.SubmissionRecoveryHint((3,), "请填写")),
            (submission, "submit", lambda *_args, **_kwargs: submit_calls.append("submit")),
        )

        from tencent.provider import runtime as qq_runtime

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                qq_runtime,
                "refill_required_questions_on_current_page",
                lambda *_args, **_kwargs: 0,
            )
            recovered = submission.attempt_submission_recovery(driver, state, None, threading.Event(), thread_name="Worker-1")

        assert recovered is False
        assert runtime_state.submission_recovery_attempts == 0
        assert submit_calls == []
