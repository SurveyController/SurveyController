from __future__ import annotations

import threading

import pytest

from software.core.engine.runtime_actions import RuntimeActionKind
from software.core.task import ExecutionConfig, ExecutionState
from wjx.provider import submission


class _FakeElement:
    def __init__(self, *, displayed: bool = True) -> None:
        self._displayed = displayed

    async def is_displayed(self) -> bool:
        return self._displayed

    async def click(self) -> None:
        return None


class _FakeDriver:
    def __init__(self) -> None:
        self.browser_name = "edge"
        self.session_id = "test-session"
        self.browser_pid = None
        self.browser_pids: set[int] = set()

    async def find_element(self, *_args, **_kwargs):
        raise RuntimeError("unused")


class WjxSubmissionTests:
    @pytest.mark.asyncio
    async def test_submission_validation_message_returns_human_readable_copy(self) -> None:
        assert "阿里云智能验证" in await submission.submission_validation_message()

    @pytest.mark.asyncio
    async def test_submission_requires_verification_prefers_js_signal(self, monkeypatch) -> None:
        async def _js(_driver):
            return True

        async def _dom(_driver):
            return False

        monkeypatch.setattr(submission, "_aliyun_captcha_visible_with_js", _js)
        monkeypatch.setattr(submission, "_aliyun_captcha_element_exists", _dom)

        assert await submission.submission_requires_verification(_FakeDriver())

    @pytest.mark.asyncio
    async def test_wait_for_submission_verification_stops_when_stop_signal_is_set(self, monkeypatch) -> None:
        stop_signal = threading.Event()
        stop_signal.set()
        async def _verify(_driver):
            return True

        monkeypatch.setattr(submission, "submission_requires_verification", _verify)

        assert not await submission.wait_for_submission_verification(_FakeDriver(), timeout=3, stop_signal=stop_signal)

    @pytest.mark.asyncio
    async def test_handle_submission_verification_detected_respects_pause_switches(self, monkeypatch) -> None:
        calls: list[str] = []
        monkeypatch.setattr(submission, "_trigger_aliyun_captcha_stop", lambda *_args, **_kwargs: calls.append("stop"))

        ctx_random = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True))
        await submission.handle_submission_verification_detected(ctx_random, stop_signal=None)

        ctx_pause_off = ExecutionState(config=ExecutionConfig(pause_on_aliyun_captcha=False))
        await submission.handle_submission_verification_detected(ctx_pause_off, stop_signal=None)

        ctx_normal = ExecutionState(config=ExecutionConfig())
        await submission.handle_submission_verification_detected(ctx_normal, stop_signal=None)

        assert calls == ["stop"]

    def test_trigger_aliyun_captcha_stop_sets_flags_and_returns_runtime_actions(self, monkeypatch) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        stop_signal = threading.Event()

        monkeypatch.setattr(
            "software.network.proxy.policy.source.get_random_ip_counter_snapshot_local",
            lambda: (1.0, 5.0, False),
        )
        monkeypatch.setattr("software.network.proxy.session.has_authenticated_session", lambda: True)
        monkeypatch.setattr(
            "software.network.proxy.session.is_quota_exhausted",
            lambda _snapshot: False,
        )

        result = submission._trigger_aliyun_captcha_stop(ctx, stop_signal)

        assert ctx._aliyun_captcha_stop_triggered
        assert stop_signal.is_set()
        assert result.should_stop
        assert [action.kind for action in result.actions] == [
            RuntimeActionKind.PAUSE_RUN,
            RuntimeActionKind.CONFIRM_ENABLE_RANDOM_IP,
        ]

    @pytest.mark.asyncio
    async def test_attempt_submission_recovery_refills_questions_and_resubmits_once(self, monkeypatch) -> None:
        driver = _FakeDriver()
        state = ExecutionState(config=ExecutionConfig(survey_provider="wjx"))
        runtime_state = submission.get_wjx_runtime_state(driver)
        runtime_state.page_questions = [
            {"question_num": 3, "required": True},
            {"question_num": 4, "required": True},
        ]
        runtime_state.psycho_plan = "plan"
        refill_calls: list[tuple[list[int], str, object]] = []
        submit_calls: list[str] = []

        async def _verify(_driver):
            return False

        async def _questionnaire(_driver):
            return True

        async def _hint(_driver):
            return submission.SubmissionRecoveryHint((3, 4), "请填写")

        monkeypatch.setattr(submission._submission_recovery, "submission_requires_verification", _verify)
        monkeypatch.setattr(submission._submission_recovery, "_page_looks_like_wjx_questionnaire", _questionnaire)
        monkeypatch.setattr(submission._submission_recovery, "_extract_missing_answer_hint", _hint)
        async def _submit(_driver, *, ctx=None, stop_signal=None):
            del stop_signal
            submit_calls.append(ctx.config.survey_provider if ctx else "")

        monkeypatch.setattr(submission, "submit", _submit)

        from wjx.provider import runtime as wjx_runtime

        async def _refill(_driver, ctx, *, question_numbers, thread_name, psycho_plan):
            del ctx
            refill_calls.append((list(question_numbers), thread_name, psycho_plan))
            return 2

        monkeypatch.setattr(wjx_runtime, "refill_required_questions_on_current_page", _refill)

        recovered = await submission.attempt_submission_recovery(
            driver,
            state,
            None,
            threading.Event(),
            thread_name="Worker-1",
        )

        assert recovered is True
        assert runtime_state.submission_recovery_attempts == 1
        assert refill_calls == [([3, 4], "Worker-1", "plan")]
        assert submit_calls == ["wjx"]

    @pytest.mark.asyncio
    async def test_attempt_submission_recovery_falls_back_to_current_page_required_questions(self, monkeypatch) -> None:
        driver = _FakeDriver()
        state = ExecutionState(config=ExecutionConfig(survey_provider="wjx"))
        runtime_state = submission.get_wjx_runtime_state(driver)
        runtime_state.page_questions = [
            {"question_num": 7, "required": True},
            {"question_num": 8, "required": False},
        ]
        refill_calls: list[list[int]] = []

        async def _verify(_driver):
            return False

        async def _questionnaire(_driver):
            return True

        async def _hint(_driver):
            return submission.SubmissionRecoveryHint((), "请填写")

        async def _submit(*_args, **_kwargs):
            return None

        monkeypatch.setattr(submission._submission_recovery, "submission_requires_verification", _verify)
        monkeypatch.setattr(submission._submission_recovery, "_page_looks_like_wjx_questionnaire", _questionnaire)
        monkeypatch.setattr(submission._submission_recovery, "_extract_missing_answer_hint", _hint)
        monkeypatch.setattr(submission, "submit", _submit)

        from wjx.provider import runtime as wjx_runtime

        async def _refill(_driver, _ctx, *, question_numbers, thread_name, psycho_plan):
            del thread_name, psycho_plan
            refill_calls.append(list(question_numbers))
            return 1

        monkeypatch.setattr(wjx_runtime, "refill_required_questions_on_current_page", _refill)

        recovered = await submission.attempt_submission_recovery(
            driver,
            state,
            None,
            threading.Event(),
            thread_name="Worker-2",
        )

        assert recovered is True
        assert refill_calls == [[7]]

    @pytest.mark.asyncio
    async def test_submit_raises_when_submit_button_missing(self, monkeypatch) -> None:
        driver = _FakeDriver()
        monkeypatch.setattr(submission, "_is_headless_mode", lambda _ctx: True)
        monkeypatch.setattr(submission, "HEADLESS_SUBMIT_INITIAL_DELAY", 0.0)
        monkeypatch.setattr(submission, "HEADLESS_SUBMIT_CLICK_SETTLE_DELAY", 0.0)
        async def _click(*_args, **_kwargs):
            return False

        monkeypatch.setattr(submission, "_click_submit_button", _click)

        with pytest.raises(Exception, match="Submit button not found"):
            await submission.submit(driver, ctx=None, stop_signal=threading.Event())
