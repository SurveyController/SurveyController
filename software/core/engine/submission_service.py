"""提交结果判定服务。"""

from __future__ import annotations

import logging
import random
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
from software.core.engine.failure_snapshot import capture_submission_failure_snapshot
from software.core.engine.run_stop_policy import RunStopPolicy
from software.core.engine.stop_signal import StopSignalLike
from software.core.task import ExecutionConfig, ExecutionState
from software.logging.log_utils import log_suppressed_exception
from software.network.browser import BrowserDriver
from software.providers.registry import (
    attempt_submission_recovery_sync as _provider_attempt_submission_recovery,
    handle_submission_verification_detected_sync as _provider_handle_submission_verification_detected,
    submission_requires_verification_sync as _provider_submission_requires_verification,
    submission_validation_message_sync as _provider_submission_validation_message,
    wait_for_submission_verification_sync as _provider_wait_for_submission_verification,
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

    def _survey_provider_key(self) -> str:
        return str(self.config.survey_provider or "wjx").strip().lower()

    def _is_wjx_provider(self) -> bool:
        return self._survey_provider_key() == "wjx"

    def _mark_successful_submit_proxies(self, driver: BrowserDriver) -> None:
        for attr_name in ("_session_proxy_address", "_submit_proxy_address"):
            proxy_address = str(getattr(driver, attr_name, "") or "").strip()
            if not proxy_address:
                continue
            try:
                self.state.mark_successful_proxy_address(proxy_address)
            except Exception as exc:
                log_suppressed_exception(
                    f"SubmissionService._mark_successful_submit_proxies {attr_name}",
                    exc,
                    level=logging.WARNING,
                )
        try:
            thread_name = str(getattr(driver, "_thread_name", "") or "").strip()
            if thread_name:
                self.state.release_proxy_in_use(thread_name)
        except Exception as exc:
            log_suppressed_exception(
                "SubmissionService._mark_successful_submit_proxies release_proxy_in_use",
                exc,
                level=logging.WARNING,
            )

    def _build_success_outcome(
        self,
        driver: BrowserDriver,
        stop_signal: StopSignalLike,
        *,
        thread_name: str,
    ) -> SubmissionOutcome:
        self._mark_successful_submit_proxies(driver)
        grace_seconds = self._resolve_post_submit_close_grace_seconds()
        if grace_seconds > 0 and stop_signal.wait(grace_seconds):
            return SubmissionOutcome("aborted", FailureReason.USER_STOPPED, "任务已停止", False, True, False)
        should_stop = self.stop_policy.record_success(stop_signal, thread_name=thread_name)
        return SubmissionOutcome("success", None, "提交成功", True, should_stop, self.config.random_proxy_ip_enabled)

    def _detect_completion_once(self, driver: BrowserDriver) -> bool:
        try:
            current_url = driver.current_url
        except Exception:
            current_url = ""
        if "complete" in str(current_url).lower():
            return True
        try:
            return bool(duration_control.is_survey_completion_page(driver, provider=self.config.survey_provider))
        except Exception as exc:
            log_suppressed_exception("SubmissionService._detect_completion_once", exc, level=logging.WARNING)
            return False

    def _wait_for_completion_page(
        self,
        driver: BrowserDriver,
        stop_signal: StopSignalLike,
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
        stop_signal: StopSignalLike,
        gui_instance: Any,
        thread_name: Optional[str] = None,
    ) -> SubmissionOutcome:
        survey_provider = self._survey_provider_key()
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
        stop_signal: StopSignalLike,
        gui_instance: Any,
        thread_name: Optional[str] = None,
    ) -> Optional[SubmissionOutcome]:
        survey_provider = self._survey_provider_key()
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

    def _attempt_submission_recovery(
        self,
        driver: BrowserDriver,
        stop_signal: StopSignalLike,
        gui_instance: Any,
        *,
        thread_name: str,
    ) -> bool:
        try:
            recovered = _provider_attempt_submission_recovery(
                driver,
                self.state,
                gui_instance,
                stop_signal,
                provider=self.config.survey_provider,
                thread_name=thread_name,
            )
        except Exception as exc:
            logging.warning("提交后自动补答恢复失败：%s", exc)
            return False
        if recovered:
            logging.info("提交后自动补答已执行，准备重新等待完成页。")
        return bool(recovered)

    def finalize_after_submit(
        self,
        driver: BrowserDriver,
        *,
        stop_signal: StopSignalLike,
        gui_instance: Any,
        thread_name: str,
    ) -> SubmissionOutcome:
        if stop_signal.wait(random.uniform(0.2, 0.6)):
            return SubmissionOutcome("aborted", FailureReason.USER_STOPPED, "任务已停止", False, True, False)

        if self._is_wjx_provider():
            if self._detect_completion_once(driver):
                return self._build_success_outcome(driver, stop_signal, thread_name=thread_name)
            wait_seconds = max(1.0, float(POST_SUBMIT_URL_MAX_WAIT or 0.0) * 2.0)
        else:
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

        if completion_detected:
            return self._build_success_outcome(driver, stop_signal, thread_name=thread_name)

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
                completion_detected = self._detect_completion_once(driver)
            except Exception:
                completion_detected = False

        while not completion_detected and not stop_signal.is_set():
            recovered = self._attempt_submission_recovery(
                driver,
                stop_signal,
                gui_instance,
                thread_name=thread_name,
            )
            if not recovered or stop_signal.is_set():
                break

            if recovered and not stop_signal.is_set():
                recovery_wait_seconds = max(2.0, float(POST_SUBMIT_URL_MAX_WAIT or 0.0) * 4.0)
                recovery_poll = max(0.05, float(POST_SUBMIT_URL_POLL_INTERVAL or 0.1))
                completion_detected = self._wait_for_completion_page(
                    driver,
                    stop_signal,
                    recovery_wait_seconds,
                    recovery_poll,
                )
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
                    try:
                        completion_detected = self._detect_completion_once(driver)
                    except Exception:
                        completion_detected = False

        if not completion_detected:
            snapshot_dir = capture_submission_failure_snapshot(
                driver,
                thread_name=thread_name,
                provider=self.config.survey_provider,
                reason="post_submit_no_completion",
            )
            if snapshot_dir:
                logging.warning("提交失败现场快照已保存：%s", snapshot_dir)
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

        return self._build_success_outcome(driver, stop_signal, thread_name=thread_name)


__all__ = ["SubmissionOutcome", "SubmissionService"]
