"""提交结果判定服务。"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import software.core.modes.duration_control as duration_control
from software.app.config import (
    HEADLESS_POST_SUBMIT_CLOSE_GRACE_SECONDS,
    POST_SUBMIT_CLOSE_GRACE_SECONDS,
    POST_SUBMIT_URL_MAX_WAIT,
    POST_SUBMIT_URL_POLL_INTERVAL,
)
from software.core.engine.failure_reason import FailureReason
from software.core.engine.run_stop_policy import RunStopPolicy
from software.core.task import ExecutionConfig, ExecutionState
from software.logging.log_utils import log_suppressed_exception
from software.network.browser import BrowserDriver
from software.providers.registry import (
    consume_submission_success_signal as _provider_consume_submission_success_signal,
    handle_submission_verification_detected as _provider_handle_submission_verification_detected,
    submission_requires_verification as _provider_submission_requires_verification,
    submission_validation_message as _provider_submission_validation_message,
    wait_for_submission_verification as _provider_wait_for_submission_verification,
)


@dataclass(frozen=True)
class SubmissionOutcome:
    status: str
    failure_reason: Optional[FailureReason]
    message: str
    completion_detected: bool
    should_stop: bool
    should_rotate_proxy: bool


class SubmissionService:
    """统一处理提交后的成功、验证、完成页与失败归因。"""

    def __init__(self, config: ExecutionConfig, state: ExecutionState, stop_policy: RunStopPolicy):
        self.config = config
        self.state = state
        self.stop_policy = stop_policy

    def _resolve_post_submit_close_grace_seconds(self) -> float:
        if bool(self.config.headless_mode):
            return float(HEADLESS_POST_SUBMIT_CLOSE_GRACE_SECONDS or 0.0)
        return float(POST_SUBMIT_CLOSE_GRACE_SECONDS or 0.0)

    def _wait_for_completion_page(
        self,
        driver: BrowserDriver,
        stop_signal: threading.Event,
        max_wait_seconds: float,
        poll_interval: float,
    ) -> bool:
        deadline = time.time() + max_wait_seconds
        while time.time() < deadline:
            if stop_signal.is_set():
                return False
            try:
                current_url = driver.current_url
            except Exception:
                current_url = ""
            if "complete" in str(current_url).lower():
                return True
            try:
                if duration_control.is_survey_completion_page(driver, provider=self.config.survey_provider):
                    return True
            except Exception as exc:
                log_suppressed_exception("SubmissionService._wait_for_completion_page", exc, level=logging.WARNING)
            time.sleep(poll_interval)
        return False

    def _handle_detected_submission_verification(
        self,
        driver: BrowserDriver,
        stop_signal: threading.Event,
        gui_instance: Any,
        thread_name: Optional[str] = None,
    ) -> SubmissionOutcome:
        survey_provider = str(self.config.survey_provider or "wjx").strip().lower()
        fallback_message = "提交命中平台安全验证，当前版本暂不支持自动处理"
        message = _provider_submission_validation_message(driver, provider=survey_provider) or fallback_message
        logging.warning("%s", message)
        self.state.mark_terminal_stop(
            "submission_verification",
            failure_reason=FailureReason.SUBMISSION_VERIFICATION_REQUIRED.value,
            message=message,
        )
        stopped = self.stop_policy.record_failure(
            stop_signal,
            thread_name=thread_name,
            failure_reason=FailureReason.SUBMISSION_VERIFICATION_REQUIRED,
            status_text="腾讯安全验证" if survey_provider == "qq" else "智能验证",
            log_message=message,
            consume_reverse_fill_attempt=False,
        )
        _provider_handle_submission_verification_detected(
            self.state,
            gui_instance,
            stop_signal,
            provider=survey_provider,
        )
        return SubmissionOutcome(
            status="failure",
            failure_reason=FailureReason.SUBMISSION_VERIFICATION_REQUIRED,
            message=message,
            completion_detected=False,
            should_stop=bool(stopped or stop_signal.is_set()),
            should_rotate_proxy=False,
        )

    def _check_submission_verification_after_submit(
        self,
        driver: BrowserDriver,
        stop_signal: threading.Event,
        gui_instance: Any,
        thread_name: Optional[str] = None,
    ) -> Optional[SubmissionOutcome]:
        survey_provider = str(self.config.survey_provider or "wjx").strip().lower()
        if survey_provider == "qq":
            if _provider_submission_requires_verification(driver, provider=survey_provider):
                return self._handle_detected_submission_verification(driver, stop_signal, gui_instance, thread_name=thread_name)
            return None
        try:
            detected = _provider_wait_for_submission_verification(
                driver,
                provider=survey_provider,
                timeout=3,
                stop_signal=stop_signal,
            )
            if detected:
                return self._handle_detected_submission_verification(driver, stop_signal, gui_instance, thread_name=thread_name)
        except Exception as exc:
            logging.warning("提交后安全验证检测过程出现异常：%s", exc)
        return None

    def finalize_after_submit(
        self,
        driver: BrowserDriver,
        *,
        stop_signal: threading.Event,
        gui_instance: Any,
        thread_name: str,
    ) -> SubmissionOutcome:
        if self.config.headless_mode and _provider_consume_submission_success_signal(
            driver,
            provider=self.config.survey_provider,
        ):
            grace_seconds = self._resolve_post_submit_close_grace_seconds()
            if grace_seconds > 0 and not stop_signal.is_set():
                time.sleep(grace_seconds)
            should_stop = self.stop_policy.record_success(stop_signal, thread_name=thread_name)
            return SubmissionOutcome("success", None, "提交成功", True, should_stop, self.config.random_proxy_ip_enabled)

        if stop_signal.wait(random.uniform(0.2, 0.6)):
            return SubmissionOutcome("aborted", FailureReason.USER_STOPPED, "任务已停止", False, True, False)

        verification_outcome = self._check_submission_verification_after_submit(
            driver,
            stop_signal,
            gui_instance,
            thread_name=thread_name,
        )
        if verification_outcome is not None:
            return verification_outcome

        if not stop_signal.is_set() and _provider_submission_requires_verification(
            driver,
            provider=self.config.survey_provider,
        ):
            return self._handle_detected_submission_verification(driver, stop_signal, gui_instance, thread_name=thread_name)

        wait_seconds = max(3.0, float(POST_SUBMIT_URL_MAX_WAIT or 0.0) * 6.0)
        poll_interval = max(0.05, float(POST_SUBMIT_URL_POLL_INTERVAL or 0.1))
        completion_detected = self._wait_for_completion_page(driver, stop_signal, wait_seconds, poll_interval)

        if not completion_detected and not stop_signal.is_set():
            if _provider_submission_requires_verification(driver, provider=self.config.survey_provider):
                return self._handle_detected_submission_verification(driver, stop_signal, gui_instance, thread_name=thread_name)

        if not completion_detected and not stop_signal.is_set():
            verification_outcome = self._check_submission_verification_after_submit(
                driver,
                stop_signal,
                gui_instance,
                thread_name=thread_name,
            )
            if verification_outcome is not None:
                return verification_outcome

        if not completion_detected and not stop_signal.is_set():
            extra_wait_seconds = max(1.0, float(POST_SUBMIT_URL_MAX_WAIT or 0.0) * 3.0)
            extra_poll = max(0.05, float(POST_SUBMIT_URL_POLL_INTERVAL or 0.1))
            completion_detected = self._wait_for_completion_page(driver, stop_signal, extra_wait_seconds, extra_poll)

        if not completion_detected and not stop_signal.is_set():
            try:
                current_url = driver.current_url
            except Exception:
                current_url = ""
            if "complete" in str(current_url).lower():
                completion_detected = True
            else:
                try:
                    completion_detected = bool(
                        duration_control.is_survey_completion_page(driver, provider=self.config.survey_provider)
                    )
                except Exception:
                    completion_detected = False

        if not completion_detected:
            stopped = self.stop_policy.record_failure(
                stop_signal,
                thread_name=thread_name,
                failure_reason=FailureReason.FILL_FAILED,
                status_text="提交未完成",
                log_message="提交后未检测到完成页，本轮按失败处理",
                consume_reverse_fill_attempt=False,
            )
            return SubmissionOutcome(
                status="failure",
                failure_reason=FailureReason.FILL_FAILED,
                message="提交后未检测到完成页",
                completion_detected=False,
                should_stop=bool(stopped or stop_signal.is_set()),
                should_rotate_proxy=False,
            )

        grace_seconds = self._resolve_post_submit_close_grace_seconds()
        if grace_seconds > 0 and not stop_signal.is_set():
            time.sleep(grace_seconds)
        should_stop = self.stop_policy.record_success(stop_signal, thread_name=thread_name)
        return SubmissionOutcome("success", None, "提交成功", True, should_stop, self.config.random_proxy_ip_enabled)


__all__ = ["SubmissionOutcome", "SubmissionService"]
