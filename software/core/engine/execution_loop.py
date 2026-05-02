"""线程执行主循环。"""

from __future__ import annotations

import logging
import random
import threading
import traceback
from typing import Any

import software.core.modes.timed_mode as timed_mode
from software.app.config import BROWSER_PREFERENCE
from software.core.ai.runtime import AIRuntimeError, is_ai_timeout_runtime_error, is_free_ai_runtime_error
from software.core.engine.browser_session_service import BrowserSessionService
from software.core.engine.failure_reason import FailureReason
from software.core.engine.preloaded_session_pool import PreloadedBrowserSessionPool
from software.core.engine.provider_common import ensure_joint_psychometric_answer_plan
from software.core.engine.run_stop_policy import RunStopPolicy
from software.core.engine.submission_service import SubmissionService
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser import (
    ProxyConnectionError,
    classify_playwright_startup_error,
)
from software.network.session_policy import _discard_unresponsive_proxy, _record_bad_proxy_and_maybe_pause
from software.providers.common import SURVEY_PROVIDER_CREDAMO, normalize_survey_provider
from software.providers.registry import fill_survey as _provider_fill_survey
from software.providers.registry import is_device_quota_limit_page as _provider_is_device_quota_limit_page
from software.network.browser.owner_pool import AsyncBrowserOwner

_DEFAULT_PAGE_LOAD_TIMEOUT_MS = 20000
_CREDAMO_PAGE_LOAD_TIMEOUT_MS = 45000
_FREE_AI_TIMEOUT_FAIL_THRESHOLD = 5


def _load_survey_page(driver: Any, config: ExecutionConfig) -> None:
    provider = normalize_survey_provider(getattr(config, "survey_provider", None))
    if provider != SURVEY_PROVIDER_CREDAMO:
        driver.get(config.url, timeout=_DEFAULT_PAGE_LOAD_TIMEOUT_MS)
        return

    last_exc: Exception | None = None
    attempts = (
        (_CREDAMO_PAGE_LOAD_TIMEOUT_MS, "domcontentloaded"),
        (_CREDAMO_PAGE_LOAD_TIMEOUT_MS, "commit"),
    )
    for attempt_index, (timeout_ms, wait_until) in enumerate(attempts, start=1):
        try:
            driver.get(config.url, timeout=timeout_ms, wait_until=wait_until)
            if attempt_index > 1:
                logging.info("Credamo 问卷加载重试成功：wait_until=%s timeout=%sms", wait_until, timeout_ms)
            return
        except Exception as exc:
            last_exc = exc
            logging.warning(
                "Credamo 问卷加载第%s次失败：wait_until=%s timeout=%sms，准备%s",
                attempt_index,
                wait_until,
                timeout_ms,
                "重试" if attempt_index < len(attempts) else "结束",
            )
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Credamo 问卷加载失败")


class ExecutionLoop:
    """单个工作线程的执行主循环。"""

    def __init__(
        self,
        config: ExecutionConfig,
        state: ExecutionState,
        gui_instance: Any = None,
        *,
        browser_owner: AsyncBrowserOwner | None = None,
    ):
        self.config = config
        self.state = state
        self.gui_instance = gui_instance
        self.browser_owner = browser_owner
        self.stop_policy = RunStopPolicy(config, state, gui_instance)
        self.submission_service = SubmissionService(config, state, self.stop_policy)

    def _update_thread_status(self, thread_name: str, status_text: str, *, running: bool) -> None:
        try:
            self.state.update_thread_status(thread_name, status_text, running=running)
        except Exception:
            logging.info("更新线程状态失败：%s", status_text, exc_info=True)

    def _update_thread_step(self, thread_name: str, status_text: str) -> None:
        try:
            self.state.update_thread_step(thread_name, 0, 0, status_text=status_text, running=True)
        except Exception:
            logging.info("更新线程状态失败：%s", status_text, exc_info=True)

    @staticmethod
    def _reprioritize_browser_preference(active_browser: str, base_browser_preference: list[str]) -> list[str]:
        normalized = str(active_browser or "").strip().lower()
        if not normalized:
            return list(base_browser_preference or [])
        return [normalized] + [browser for browser in list(base_browser_preference or []) if browser != normalized]

    def _resolve_timed_refresh_interval(self) -> float:
        try:
            refresh_interval = float(
                self.config.timed_mode_refresh_interval or timed_mode.DEFAULT_REFRESH_INTERVAL
            )
        except Exception:
            refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
        if refresh_interval <= 0:
            refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
        return refresh_interval

    def _log_runtime_settings(self, *, timed_mode_on: bool) -> None:
        logging.info("目标份数: %s, 当前进度: %s/%s", self.config.target_num, self.state.cur_num, self.config.target_num)
        if timed_mode_on:
            logging.info("定时模式已启用")
        if self.config.random_proxy_ip_enabled:
            logging.info("随机IP已启用")
        if self.config.random_user_agent_enabled:
            logging.info("随机UA已启用")

    def _should_stop_loop(self, stop_signal: threading.Event) -> bool:
        self.stop_policy.wait_if_paused(stop_signal)
        if stop_signal.is_set():
            return True
        with self.state.lock:
            return bool(
                stop_signal.is_set()
                or (self.config.target_num > 0 and self.state.cur_num >= self.config.target_num)
            )

    def _prepare_browser_session(
        self,
        session: BrowserSessionService,
        preferred_browsers: list[str],
        base_browser_preference: list[str],
        *,
        window_x_pos: int,
        window_y_pos: int,
        stop_signal: threading.Event,
        thread_name: str,
    ) -> list[str]:
        if session.driver is not None:
            return preferred_browsers

        self._update_thread_step(thread_name, "准备浏览器")
        try:
            active_browser = session.create_browser(
                preferred_browsers,
                window_x_pos,
                window_y_pos,
                stop_signal=stop_signal,
            )
        except Exception as exc:
            if stop_signal.is_set():
                return preferred_browsers
            error_info = classify_playwright_startup_error(exc)
            friendly_error = error_info.message
            logging.error("启动浏览器失败：%s", friendly_error)
            if error_info.is_environment_error:
                logging.critical("检测到本机环境阻止 Playwright 启动，任务停止。")
                self._update_thread_status(thread_name, "本机环境阻止浏览器启动", running=False)
                self.state.mark_terminal_stop(
                    error_info.kind,
                    failure_reason=FailureReason.BROWSER_START_FAILED.value,
                    message=friendly_error,
                )
                if not stop_signal.is_set():
                    stop_signal.set()
                return preferred_browsers
            stopped = self.stop_policy.record_failure(
                stop_signal,
                thread_name=thread_name,
                failure_reason=FailureReason.BROWSER_START_FAILED,
                status_text="浏览器启动失败",
                log_message=f"浏览器启动失败，本轮按失败处理：{friendly_error}",
            )
            if stopped and not stop_signal.is_set():
                stop_signal.set()
            if not stopped:
                stop_signal.wait(1.0)
            return preferred_browsers

        if active_browser is None:
            if stop_signal.is_set():
                return preferred_browsers
            if self.config.random_proxy_ip_enabled:
                self._update_thread_status(thread_name, "等待可用代理", running=True)
                stop_signal.wait(0.1)
                return preferred_browsers
            stop_signal.wait(0.8)
            return preferred_browsers
        return [active_browser] + [browser for browser in base_browser_preference if browser != active_browser]

    def _load_survey_or_record_failure(
        self,
        session: BrowserSessionService,
        stop_signal: threading.Event,
        *,
        thread_name: str,
        timed_mode_on: bool,
        timed_refresh_interval: float,
    ) -> bool:
        if stop_signal.is_set():
            return False

        self.stop_policy.wait_if_paused(stop_signal)
        self._update_thread_status(thread_name, "加载问卷", running=True)

        try:
            driver = session.driver
            if driver is None:
                raise RuntimeError("浏览器会话未初始化")
            if timed_mode_on:
                ready = timed_mode.wait_until_open(
                    driver,
                    self.config.url,
                    stop_signal,
                    refresh_interval=timed_refresh_interval,
                    logger=logging.info,
                )
                if not ready:
                    if not stop_signal.is_set():
                        stop_signal.set()
                    return False
            else:
                _load_survey_page(driver, self.config)
        except Exception as exc:
            self.stop_policy.record_failure(
                stop_signal,
                thread_name=thread_name,
                failure_reason=FailureReason.PAGE_LOAD_FAILED,
                status_text="加载问卷失败",
                log_message=f"加载问卷失败，本轮按失败处理：{exc}",
            )
            return False
        return True

    def _handle_device_quota_limit(
        self,
        session: BrowserSessionService,
        stop_signal: threading.Event,
        *,
        thread_name: str,
    ) -> bool:
        if not _provider_is_device_quota_limit_page(session.driver, provider=self.config.survey_provider):
            return False

        stopped = self.stop_policy.record_failure(
            stop_signal,
            thread_name=thread_name,
            failure_reason=FailureReason.DEVICE_QUOTA_LIMIT,
            status_text="设备达到填写次数上限",
            log_message="设备达到填写次数上限，本轮按失败处理",
        )
        if stopped and not stop_signal.is_set():
            stop_signal.set()
        self._update_thread_status(thread_name, "设备达到填写次数上限", running=True)
        session.dispose()
        if not stopped and not stop_signal.is_set() and self.config.random_proxy_ip_enabled:
            try:
                handler = getattr(self.gui_instance, "handle_random_ip_submission", None)
                if callable(handler):
                    handler(stop_signal)
            except Exception:
                logging.info("设备上限失败后处理随机IP提交流程失败", exc_info=True)
        return True

    def _prepare_round_context(
        self,
        stop_signal: threading.Event,
        *,
        thread_name: str,
        session: BrowserSessionService | None,
    ) -> bool:
        try:
            self.state.reset_pending_distribution(thread_name)
        except Exception:
            logging.info("重置本轮比例统计缓存失败", exc_info=True)

        joint_answer_plan = ensure_joint_psychometric_answer_plan(self.config)
        if joint_answer_plan is not None:
            reserved_sample_index = self.state.reserve_joint_sample(
                int(getattr(joint_answer_plan, "sample_count", self.config.target_num) or self.config.target_num),
                thread_name=thread_name,
            )
            if reserved_sample_index is None:
                logging.info("线程[%s]等待联合信效度样本槽位释放", thread_name)
                self._update_thread_status(thread_name, "等待信效度配额槽位", running=True)
                if stop_signal.wait(0.2):
                    return False
                return False

        reverse_fill_sample = self.state.acquire_reverse_fill_sample(thread_name)
        if reverse_fill_sample.status == "waiting":
            logging.info("线程[%s]等待反填样本释放", thread_name)
            try:
                self.state.release_joint_sample(thread_name)
            except Exception:
                logging.info("等待反填样本时释放联合信效度样本槽位失败", exc_info=True)
            self._update_thread_status(thread_name, "等待反填样本", running=True)
            if session is not None:
                session.dispose()
            if stop_signal.wait(0.2):
                return False
            return False
        if reverse_fill_sample.status == "exhausted":
            message = "反填样本已耗尽，剩余样本不足以完成目标份数"
            try:
                self.state.release_joint_sample(thread_name)
            except Exception:
                logging.info("反填样本耗尽时释放联合信效度样本槽位失败", exc_info=True)
            self.state.mark_terminal_stop(
                "reverse_fill_exhausted",
                failure_reason=FailureReason.FILL_FAILED.value,
                message=message,
            )
            self._update_thread_status(thread_name, "反填样本不足", running=False)
            if not stop_signal.is_set():
                stop_signal.set()
            return False
        if reverse_fill_sample.status == "acquired" and reverse_fill_sample.sample is not None:
            logging.info(
                "线程[%s]已锁定反填样本：数据行=%s 工作表行=%s",
                thread_name,
                reverse_fill_sample.sample.data_row_number,
                reverse_fill_sample.sample.worksheet_row_number,
            )
        return True

    def _release_round_resources(self, thread_name: str, *, requeue_reverse_fill: bool) -> None:
        try:
            self.state.release_joint_sample(thread_name)
        except Exception:
            logging.info("释放联合信效度样本槽位失败", exc_info=True)
        try:
            self.state.release_reverse_fill_sample(thread_name, requeue=requeue_reverse_fill)
        except Exception:
            logging.info("释放反填样本失败", exc_info=True)

    def _handle_ai_runtime_error(self, exc: AIRuntimeError, stop_signal: threading.Event, *, thread_name: str) -> bool:
        if is_ai_timeout_runtime_error(exc):
            logging.warning("免费 AI 调用超时，本轮丢弃并继续下一轮：%s", exc)
            stopped = self.stop_policy.record_failure(
                stop_signal,
                thread_name=thread_name,
                failure_reason=FailureReason.FILL_FAILED,
                status_text="免费AI超时",
                log_message=(
                    f"免费AI调用超时，本轮按失败处理；连续达到 {_FREE_AI_TIMEOUT_FAIL_THRESHOLD} 次才停止：{exc}"
                ),
                threshold_override=_FREE_AI_TIMEOUT_FAIL_THRESHOLD,
                terminal_stop_category="free_ai_unstable",
                force_stop_when_threshold_reached=True,
            )
            if stopped:
                logging.error("免费 AI 连续超时达到阈值，任务停止：%s", exc, exc_info=True)
            return bool(stopped)
        logging.error("AI 填空失败，已停止任务：%s", exc, exc_info=True)
        stop_category = "free_ai_unstable" if is_free_ai_runtime_error(exc) else "ai_runtime"
        stop_message = "目前免费AI不稳定，请稍后再试" if stop_category == "free_ai_unstable" else str(exc)
        self.state.mark_terminal_stop(
            stop_category,
            failure_reason=FailureReason.FILL_FAILED.value,
            message=stop_message,
        )
        if not stop_signal.is_set():
            stop_signal.set()
        return True

    def _handle_proxy_connection_error(
        self,
        session: BrowserSessionService,
        stop_signal: threading.Event,
        *,
        thread_name: str,
    ) -> bool:
        if stop_signal.is_set():
            return True
        logging.warning("代理连接失败，当前会话将废弃并重新尝试")
        if session.proxy_address:
            _discard_unresponsive_proxy(self.state, session.proxy_address)
        if self.config.random_proxy_ip_enabled:
            self._update_thread_status(thread_name, "代理失效，等待新代理", running=True)
            if _record_bad_proxy_and_maybe_pause(self.state, self.gui_instance):
                return True
            return False
        return self.stop_policy.record_failure(
            stop_signal,
            thread_name=thread_name,
            failure_reason=FailureReason.PROXY_UNAVAILABLE,
        )

    def _should_use_preloaded_session_pool(self) -> bool:
        return bool(
            self.browser_owner is not None
            and self.config.url
            and not self.config.random_proxy_ip_enabled
            and not self.config.timed_mode_enabled
        )

    def _finalize_thread(
        self,
        session: BrowserSessionService | None,
        *,
        thread_name: str,
        preloaded_pool: PreloadedBrowserSessionPool | None = None,
    ) -> None:
        try:
            self.state.release_joint_sample(thread_name)
        except Exception:
            logging.info("线程结束时释放联合信效度样本槽位失败", exc_info=True)
        try:
            self.state.release_reverse_fill_sample(thread_name, requeue=True)
        except Exception:
            logging.info("线程结束时释放反填样本失败", exc_info=True)
        try:
            self.state.mark_thread_finished(thread_name, status_text="已停止")
        except Exception:
            logging.info("更新线程状态失败：已停止", exc_info=True)
        if session is not None:
            session.shutdown()
        if preloaded_pool is not None:
            preloaded_pool.shutdown()

    def _run_thread_with_preloaded_pool(
        self,
        *,
        window_x_pos: int,
        window_y_pos: int,
        stop_signal: threading.Event,
        thread_name: str,
        base_browser_preference: list[str],
        preferred_browsers: list[str],
    ) -> None:
        pool = PreloadedBrowserSessionPool(
            config=self.config,
            state=self.state,
            gui_instance=self.gui_instance,
            thread_name=thread_name,
            browser_owner=self.browser_owner,
            page_loader=_load_survey_page,
        )
        active_session: BrowserSessionService | None = None
        pool.warm_async(preferred_browsers, window_x_pos, window_y_pos)

        while True:
            if self._should_stop_loop(stop_signal):
                break

            lease = pool.acquire(stop_signal, wait=True)
            active_session = lease.session
            session_preloaded = bool(lease.preloaded and active_session is not None)
            if active_session is None:
                active_session = BrowserSessionService(
                    self.config,
                    self.state,
                    self.gui_instance,
                    thread_name,
                    browser_owner=self.browser_owner,
                )

            should_refill = False
            try:
                preferred_browsers = self._prepare_browser_session(
                    active_session,
                    preferred_browsers,
                    base_browser_preference,
                    window_x_pos=window_x_pos,
                    window_y_pos=window_y_pos,
                    stop_signal=stop_signal,
                    thread_name=thread_name,
                )
                if stop_signal.is_set():
                    break
                if active_session.driver is None:
                    continue

                if lease.browser_name:
                    preferred_browsers = self._reprioritize_browser_preference(
                        lease.browser_name,
                        base_browser_preference,
                    )

                should_refill = True

                if not session_preloaded and not self._load_survey_or_record_failure(
                    active_session,
                    stop_signal,
                    thread_name=thread_name,
                    timed_mode_on=False,
                    timed_refresh_interval=0.0,
                ):
                    if stop_signal.is_set():
                        should_refill = False
                        break
                    continue

                if self._handle_device_quota_limit(active_session, stop_signal, thread_name=thread_name):
                    active_session = None
                    if stop_signal.is_set():
                        should_refill = False
                        break
                    continue

                if not self._prepare_round_context(
                    stop_signal,
                    thread_name=thread_name,
                    session=active_session,
                ):
                    if stop_signal.is_set():
                        should_refill = False
                        break
                    continue

                finished = _provider_fill_survey(
                    active_session.driver,
                    self.config,
                    self.state,
                    stop_signal=stop_signal,
                    thread_name=thread_name,
                    provider=self.config.survey_provider,
                )
                if stop_signal.is_set() or not finished:
                    self._release_round_resources(thread_name, requeue_reverse_fill=True)
                    if stop_signal.is_set():
                        should_refill = False
                        break
                    continue

                outcome = self.submission_service.finalize_after_submit(
                    active_session.driver,
                    stop_signal=stop_signal,
                    gui_instance=self.gui_instance,
                    thread_name=thread_name,
                )
                if outcome.status == "success":
                    if outcome.should_stop:
                        should_refill = False
                        break
                elif outcome.status == "aborted":
                    self._release_round_resources(thread_name, requeue_reverse_fill=True)
                    should_refill = False
                    break

            except AIRuntimeError as exc:
                if self._handle_ai_runtime_error(exc, stop_signal, thread_name=thread_name):
                    should_refill = False
                    break
                continue
            except ProxyConnectionError:
                if self._handle_proxy_connection_error(active_session, stop_signal, thread_name=thread_name):
                    should_refill = False
                    break
                continue
            except Exception:
                if stop_signal.is_set():
                    should_refill = False
                    break
                traceback.print_exc()
                if self.stop_policy.record_failure(
                    stop_signal,
                    thread_name=thread_name,
                    failure_reason=FailureReason.FILL_FAILED,
                ):
                    should_refill = False
                    break
            finally:
                if active_session is not None:
                    active_session.dispose()
                    active_session = None
                if should_refill and not stop_signal.is_set():
                    pool.warm_async(preferred_browsers, window_x_pos, window_y_pos)

            if stop_signal.is_set():
                break
            min_wait, max_wait = self.config.submit_interval_range_seconds
            if max_wait > 0:
                try:
                    self.state.update_thread_step(
                        thread_name,
                        0,
                        0,
                        status_text="等待提交间隔",
                        running=True,
                    )
                except Exception:
                    logging.info("更新线程状态失败：等待提交间隔", exc_info=True)
                wait_seconds = min_wait if max_wait == min_wait else random.uniform(min_wait, max_wait)
                if stop_signal.wait(wait_seconds):
                    break

        self._finalize_thread(active_session, thread_name=thread_name, preloaded_pool=pool)

    def run_thread(
        self,
        window_x_pos: int,
        window_y_pos: int,
        stop_signal: threading.Event,
    ) -> None:
        thread_name = threading.current_thread().name or "Worker-?"
        self._update_thread_status(thread_name, "线程启动", running=True)
        timed_mode_on = bool(self.config.timed_mode_enabled)
        timed_refresh_interval = self._resolve_timed_refresh_interval()
        base_browser_preference = list(self.config.browser_preference or BROWSER_PREFERENCE)
        preferred_browsers = list(base_browser_preference)
        self._log_runtime_settings(timed_mode_on=timed_mode_on)

        if self._should_use_preloaded_session_pool():
            self._run_thread_with_preloaded_pool(
                window_x_pos=window_x_pos,
                window_y_pos=window_y_pos,
                stop_signal=stop_signal,
                thread_name=thread_name,
                base_browser_preference=base_browser_preference,
                preferred_browsers=preferred_browsers,
            )
            return

        session = BrowserSessionService(
            self.config,
            self.state,
            self.gui_instance,
            thread_name,
            browser_owner=self.browser_owner,
        )

        while True:
            if self._should_stop_loop(stop_signal):
                break

            preferred_browsers = self._prepare_browser_session(
                session,
                preferred_browsers,
                base_browser_preference,
                window_x_pos=window_x_pos,
                window_y_pos=window_y_pos,
                stop_signal=stop_signal,
                thread_name=thread_name,
            )
            if stop_signal.is_set():
                break
            if session.driver is None:
                continue

            assert session.driver is not None
            driver_had_error = False
            try:
                if not self.config.url:
                    logging.error("无法启动：问卷链接为空")
                    break
                if not self._load_survey_or_record_failure(
                    session,
                    stop_signal,
                    thread_name=thread_name,
                    timed_mode_on=timed_mode_on,
                    timed_refresh_interval=timed_refresh_interval,
                ):
                    driver_had_error = True
                    if stop_signal.is_set():
                        break
                    continue

                if self._handle_device_quota_limit(session, stop_signal, thread_name=thread_name):
                    if stop_signal.is_set():
                        break
                    continue

                if not self._prepare_round_context(stop_signal, thread_name=thread_name, session=session):
                    if stop_signal.is_set():
                        break
                    continue

                finished = _provider_fill_survey(
                    session.driver,
                    self.config,
                    self.state,
                    stop_signal=stop_signal,
                    thread_name=thread_name,
                    provider=self.config.survey_provider,
                )
                if stop_signal.is_set() or not finished:
                    self._release_round_resources(thread_name, requeue_reverse_fill=True)
                    continue

                outcome = self.submission_service.finalize_after_submit(
                    session.driver,
                    stop_signal=stop_signal,
                    gui_instance=self.gui_instance,
                    thread_name=thread_name,
                )
                if outcome.status == "success":
                    session.dispose()
                    if outcome.should_stop:
                        break
                elif outcome.status == "aborted":
                    self._release_round_resources(thread_name, requeue_reverse_fill=True)
                    break
                else:
                    driver_had_error = True

            except AIRuntimeError as exc:
                driver_had_error = True
                if self._handle_ai_runtime_error(exc, stop_signal, thread_name=thread_name):
                    break
                continue
            except ProxyConnectionError:
                driver_had_error = True
                if self._handle_proxy_connection_error(session, stop_signal, thread_name=thread_name):
                    break
                continue
            except Exception:
                driver_had_error = True
                if stop_signal.is_set():
                    break
                traceback.print_exc()
                if self.stop_policy.record_failure(
                    stop_signal,
                    thread_name=thread_name,
                    failure_reason=FailureReason.FILL_FAILED,
                ):
                    break
            finally:
                if driver_had_error:
                    session.dispose()

            if stop_signal.is_set():
                break
            min_wait, max_wait = self.config.submit_interval_range_seconds
            if max_wait > 0:
                try:
                    self.state.update_thread_step(
                        thread_name,
                        0,
                        0,
                        status_text="等待提交间隔",
                        running=True,
                    )
                except Exception:
                    logging.info("更新线程状态失败：等待提交间隔", exc_info=True)
                wait_seconds = min_wait if max_wait == min_wait else random.uniform(min_wait, max_wait)
                if stop_signal.wait(wait_seconds):
                    break

        self._finalize_thread(session, thread_name=thread_name)


__all__ = ["ExecutionLoop"]
