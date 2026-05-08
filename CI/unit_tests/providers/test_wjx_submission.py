from __future__ import annotations

import threading
from types import SimpleNamespace

from software.core.task import ExecutionConfig, ExecutionState
from wjx.provider import submission


class _FakeElement:
    def __init__(self, *, displayed: bool = True) -> None:
        self._displayed = displayed

    def is_displayed(self) -> bool:
        return self._displayed


class _FakeDriver:
    def __init__(
        self,
        *,
        js_visible: bool = False,
        js_error: Exception | None = None,
        locator_results: dict[tuple[object, str], object] | None = None,
    ) -> None:
        self.js_visible = js_visible
        self.js_error = js_error
        self.locator_results = dict(locator_results or {})
        self.find_calls: list[tuple[object, str]] = []
        self.script_payload = None

    def execute_script(self, script: str):
        if "questionNumbers" in script:
            if self.script_payload is not None:
                return self.script_payload
            return {
                "questionNumbers": [4, 5, 6],
                "messages": [
                    "您的输入小于最小输入字数30,当前字数为2",
                    "请选择选项",
                    "请回答此题",
                ],
            }
        if self.js_error is not None:
            raise self.js_error
        return self.js_visible

    def find_element(self, by, value):
        self.find_calls.append((by, value))
        result = self.locator_results.get((by, value))
        if isinstance(result, Exception):
            raise result
        return result


class WjxSubmissionTests:
    def test_submission_validation_message_returns_human_readable_copy(self) -> None:
        assert "阿里云智能验证" in submission.submission_validation_message()

    def test_submission_requires_verification_prefers_js_signal(self) -> None:
        driver = _FakeDriver(js_visible=True)
        assert submission.submission_requires_verification(driver)

    def test_submission_requires_verification_falls_back_to_dom_locators(self) -> None:
        locator = submission._ALIYUN_CAPTCHA_LOCATORS[0]
        driver = _FakeDriver(
            js_error=RuntimeError("js failed"),
            locator_results={locator: _FakeElement(displayed=True)},
        )
        assert submission.submission_requires_verification(driver)

    def test_submission_requires_verification_returns_false_when_all_checks_miss(self) -> None:
        driver = _FakeDriver(js_visible=False)
        assert not submission.submission_requires_verification(driver)

    def test_wait_for_submission_verification_stops_when_stop_signal_is_set(self, patch_attrs) -> None:
        stop_signal = threading.Event()
        stop_signal.set()
        patch_attrs((submission, "submission_requires_verification", lambda _driver: True))
        assert not submission.wait_for_submission_verification(object(), timeout=3, stop_signal=stop_signal)

    def test_wait_for_submission_verification_raises_when_requested(self, patch_attrs) -> None:
        patch_attrs(
            (submission, "submission_requires_verification", lambda _driver: True),
            (submission.time, "sleep", lambda *_args, **_kwargs: None),
        )
        try:
            submission.wait_for_submission_verification(object(), timeout=3, raise_on_detect=True)
            assert False, "expected AliyunCaptchaBypassError"
        except submission.AliyunCaptchaBypassError as exc:
            assert "阿里云智能验证" in str(exc)

    def test_wait_for_submission_verification_returns_true_when_detected(self, patch_attrs) -> None:
        patch_attrs(
            (submission, "submission_requires_verification", lambda _driver: True),
            (submission.time, "sleep", lambda *_args, **_kwargs: None),
        )
        assert submission.wait_for_submission_verification(object(), timeout=3)

    def test_handle_submission_verification_detected_skips_pause_in_random_proxy_mode(self, patch_attrs) -> None:
        calls: list[str] = []
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True))
        patch_attrs((submission, "_trigger_aliyun_captcha_stop", lambda *_args, **_kwargs: calls.append("stop")))
        submission.handle_submission_verification_detected(ctx, gui_instance=None, stop_signal=None)
        assert calls == []

    def test_handle_submission_verification_detected_respects_pause_toggle(self, patch_attrs) -> None:
        calls: list[str] = []
        ctx = ExecutionState(config=ExecutionConfig(pause_on_aliyun_captcha=False))
        patch_attrs((submission, "_trigger_aliyun_captcha_stop", lambda *_args, **_kwargs: calls.append("stop")))
        submission.handle_submission_verification_detected(ctx, gui_instance=None, stop_signal=None)
        assert calls == []

    def test_handle_submission_verification_detected_triggers_pause_when_enabled(self, patch_attrs) -> None:
        calls: list[str] = []
        ctx = ExecutionState(config=ExecutionConfig())
        patch_attrs((submission, "_trigger_aliyun_captcha_stop", lambda *_args, **_kwargs: calls.append("stop")))
        submission.handle_submission_verification_detected(ctx, gui_instance=None, stop_signal=None)
        assert calls == ["stop"]

    def test_trigger_aliyun_captcha_stop_sets_flags_and_pauses_gui(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        stop_signal = threading.Event()
        calls: list[str] = []

        gui = SimpleNamespace(
            pause_run=lambda reason: calls.append(f"pause:{reason}"),
            dispatch_to_ui_async=lambda callback: callback(),
            is_random_ip_enabled=lambda: True,
            show_message_dialog=lambda *_args, **_kwargs: calls.append("message"),
        )

        submission._trigger_aliyun_captcha_stop(ctx, gui, stop_signal)

        assert ctx._aliyun_captcha_stop_triggered
        assert stop_signal.is_set()
        assert "pause:触发智能验证" in calls
        assert "message" in calls

    def test_trigger_aliyun_captcha_stop_is_idempotent(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        stop_signal = threading.Event()
        calls: list[str] = []
        gui = SimpleNamespace(
            pause_run=lambda reason: calls.append(reason),
            dispatch_to_ui_async=lambda callback: callback(),
            is_random_ip_enabled=lambda: True,
            show_message_dialog=lambda *_args, **_kwargs: calls.append("message"),
        )

        submission._trigger_aliyun_captcha_stop(ctx, gui, stop_signal)
        submission._trigger_aliyun_captcha_stop(ctx, gui, stop_signal)

        assert calls.count("触发智能验证") == 1
        assert calls.count("message") == 1

    def test_is_device_quota_limit_page_proxies_inner_helper(self, patch_attrs) -> None:
        patch_attrs((submission, "_is_device_quota_limit_page", lambda _driver: True))
        assert submission.is_device_quota_limit_page(object())

    def test_extract_missing_answer_hint_reads_wjx_error_messages(self) -> None:
        hint = submission._extract_missing_answer_hint(_FakeDriver())

        assert hint is not None
        assert hint.question_numbers == (4, 5, 6)
        assert "最小输入字数" in hint.message

    def test_extract_missing_answer_hint_ignores_plain_min_word_body_text(self) -> None:
        driver = _FakeDriver()
        driver.script_payload = {
            "questionNumbers": [],
            "messages": ["不少于", "最少"],
        }

        assert submission._extract_missing_answer_hint(driver) is None
