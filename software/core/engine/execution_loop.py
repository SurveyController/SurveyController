"""线程执行主循环。"""

from __future__ import annotations

import logging
import random
import threading
import traceback
from typing import Any, Callable

import software.core.modes.timed_mode as timed_mode
from software.app.config import BROWSER_PREFERENCE
from software.core.ai.runtime import AIRuntimeError
from software.core.engine.attempt_dispatcher import AttemptDispatcher
from software.core.engine.browser_session_service import BrowserSessionService
from software.core.engine.failure_reason import FailureReason
from software.core.engine.page_loader import (
    exception_summary as _page_load_exception_summary,
    load_survey_page as _page_loader_load_survey_page,
)
from software.core.engine.page_load_probe import wait_for_page_probe
from software.core.engine.preloaded_session_pool import PreloadedBrowserSessionPool
from software.core.engine.provider_common import ensure_joint_psychometric_answer_plan
from software.core.engine.runtime_error_handlers import (
    handle_ai_runtime_error as _handle_ai_runtime_error_impl,
    handle_proxy_connection_error as _handle_proxy_connection_error_impl,
)
from software.core.engine.run_stop_policy import RunStopPolicy
from software.core.engine.submission_service import SubmissionService
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser import (
    ProxyConnectionError,
    classify_playwright_startup_error,
)
from software.network.session_policy import (
    _mark_proxy_temporarily_bad,
    _record_bad_proxy_and_maybe_pause,
)
from software.providers.registry import fill_survey as _provider_fill_survey
from software.providers.registry import is_device_quota_limit_page as _provider_is_device_quota_limit_page
from software.network.browser.owner_pool import BrowserOwnerPool

def _exception_summary(exc: BaseException) -> str:
    return _page_load_exception_summary(exc)


def _load_survey_page(
    driver: Any,
    config: ExecutionConfig,
    *,
    phase_updater: Callable[[str], None] | None = None,
) -> None:
    return _page_loader_load_survey_page(
        driver,
        config,
        phase_updater=phase_updater,
        probe_waiter=wait_for_page_probe,
    )


class ExecutionLoop:
    """单个工作线程的执行主循环。"""

    def __init__(
        self,
        config: ExecutionConfig,
        state: ExecutionState,
        gui_instance: Any = None,
        *,
        browser_owner_pool: BrowserOwnerPool | None = None,
        dispatcher: AttemptDispatcher | None = None,
    ):
        self.config = config
        self.state = state
        self.gui_instance = gui_instance
        self.browser_owner_pool = browser_owner_pool
        self.dispatcher = dispatcher
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

    def _acquire_dispatch_turn(self, thread_name: str, stop_signal: threading.Event) -> bool:
        if stop_signal.is_set():
            return False
        dispatcher = self._ensure_dispatcher(stop_signal)
        self._update_thread_status(thread_name, "等待调度", running=True)
        return bool(dispatcher.acquire())

    def _ensure_dispatcher(self, stop_signal: threading.Event) -> AttemptDispatcher:
        dispatcher = self.dispatcher
        if dispatcher is None:
            dispatcher = AttemptDispatcher(self.config, self.state, stop_signal)
            self.dispatcher = dispatcher
        return dispatcher

    def _resolve_dispatch_delay_seconds(self) -> float:
        min_wait, max_wait = self.config.submit_interval_range_seconds
        if max_wait <= 0:
            return 0.0
        if max_wait == min_wait:
            return float(min_wait)
        return float(random.uniform(min_wait, max_wait))

    def _handle_proxy_unavailable(
        self,
        stop_signal: threading.Event,
        *,
        thread_name: str,
        status_text: str,
        log_message: str,
    ) -> bool:
        stopped = self.stop_policy.record_failure(
            stop_signal,
            thread_name=thread_name,
            failure_reason=FailureReason.PROXY_UNAVAILABLE,
            status_text=status_text,
            log_message=log_message,
            consume_reverse_fill_attempt=False,
        )
        if stopped and not stop_signal.is_set():
            stop_signal.set()
        if stopped:
            return True
        if self.config.random_proxy_ip_enabled and _record_bad_proxy_and_maybe_pause(self.state, self.gui_instance):
            return True
        return False

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
                consume_reverse_fill_attempt=False,
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
                self._update_thread_status(thread_name, "代理不可用", running=True)
                if self._handle_proxy_unavailable(
                    stop_signal,
                    thread_name=thread_name,
                    status_text="代理不可用",
                    log_message="当前没有可用代理，本轮按失败处理",
                ):
                    return preferred_browsers
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
        self._update_thread_step(thread_name, "加载问卷")

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
                _load_survey_page(
                    driver,
                    self.config,
                    phase_updater=lambda status_text: self._update_thread_step(thread_name, status_text),
                )
        except ProxyConnectionError:
            raise
        except Exception as exc:
            self.stop_policy.record_failure(
                stop_signal,
                thread_name=thread_name,
                failure_reason=FailureReason.PAGE_LOAD_FAILED,
                status_text="加载问卷失败",
                log_message=f"加载问卷失败，本轮按失败处理：{exc}",
                consume_reverse_fill_attempt=False,
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
            consume_reverse_fill_attempt=False,
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
        session: BrowserSessionService | None = None,
    ) -> bool:
        del session
        try:
            self.state.reset_pending_distribution(thread_name)
        except Exception:
            logging.info("重置本轮比例统计缓存失败", exc_info=True)

        joint_answer_plan = ensure_joint_psychometric_answer_plan(self.config)
        sample_count = 0
        if joint_answer_plan is not None:
            sample_count = int(getattr(joint_answer_plan, "sample_count", self.config.target_num) or self.config.target_num)

        while True:
            if stop_signal.is_set():
                return False

            reserved_sample_index = None
            if sample_count > 0:
                reserved_sample_index = self.state.reserve_joint_sample(sample_count, thread_name=thread_name)

            reverse_fill_sample = self.state.acquire_reverse_fill_sample(thread_name)

            if sample_count > 0 and reserved_sample_index is None:
                if reverse_fill_sample.status == "acquired":
                    try:
                        self.state.release_reverse_fill_sample(thread_name, requeue=True)
                    except Exception:
                        logging.info("等待信效度配额时回收反填样本失败", exc_info=True)
                self._update_thread_status(thread_name, "等待信效度配额槽位", running=True)
                if self.state.wait_for_runtime_change(stop_signal=stop_signal, timeout=0.5):
                    return False
                continue

            if reverse_fill_sample.status == "waiting":
                if reserved_sample_index is not None:
                    try:
                        self.state.release_joint_sample(thread_name)
                    except Exception:
                        logging.info("等待反填样本时释放联合信效度样本槽位失败", exc_info=True)
                self._update_thread_status(thread_name, "等待反填样本", running=True)
                if self.state.wait_for_runtime_change(stop_signal=stop_signal, timeout=0.5):
                    return False
                continue

            if reverse_fill_sample.status == "exhausted":
                message = "反填样本已耗尽，剩余样本不足以完成目标份数"
                if reserved_sample_index is not None:
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
        return _handle_ai_runtime_error_impl(
            exc,
            stop_signal,
            thread_name=thread_name,
            stop_policy=self.stop_policy,
            state=self.state,
        )

    def _handle_proxy_connection_error(
        self,
        session: BrowserSessionService | None,
        stop_signal: threading.Event,
        *,
        thread_name: str,
    ) -> bool:
        return _handle_proxy_connection_error_impl(
            session,
            stop_signal,
            thread_name=thread_name,
            state=self.state,
            config=self.config,
            stop_policy=self.stop_policy,
            update_thread_status=lambda name, status_text: self._update_thread_status(name, status_text, running=True),
            handle_proxy_unavailable=self._handle_proxy_unavailable,
            mark_proxy_temporarily_bad=_mark_proxy_temporarily_bad,
        )

    def _should_use_preloaded_session_pool(self) -> bool:
        return bool(
            self.browser_owner_pool is not None
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
        browser_owner_pool = self.browser_owner_pool
        assert browser_owner_pool is not None
        pool = PreloadedBrowserSessionPool(
            config=self.config,
            state=self.state,
            gui_instance=self.gui_instance,
            thread_name=thread_name,
            browser_owner_pool=browser_owner_pool,
            page_loader=_load_survey_page,
        )
        active_session: BrowserSessionService | None = None
        pool.warm_async(preferred_browsers, window_x_pos, window_y_pos)

        while True:
            if self._should_stop_loop(stop_signal):
                break
            if not self._acquire_dispatch_turn(thread_name, stop_signal):
                break

            lease = None
            should_refill = False
            should_requeue_dispatch = True
            dispatch_delay_seconds = 0.0
            try:
                if not self._prepare_round_context(
                    stop_signal,
                    thread_name=thread_name,
                    session=None,
                ):
                    if stop_signal.is_set():
                        should_requeue_dispatch = False
                        break
                    continue

                lease = pool.acquire(stop_signal, wait=True)
                active_session = lease.session
                session_preloaded = bool(lease.preloaded and active_session is not None)
                if active_session is None:
                    active_session = BrowserSessionService(
                        self.config,
                        self.state,
                        self.gui_instance,
                        thread_name,
                        browser_owner_pool=browser_owner_pool,
                    )

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
                    self._release_round_resources(thread_name, requeue_reverse_fill=True)
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
                        should_requeue_dispatch = False
                        break
                    self._release_round_resources(thread_name, requeue_reverse_fill=True)
                    continue

                if self._handle_device_quota_limit(active_session, stop_signal, thread_name=thread_name):
                    self._release_round_resources(thread_name, requeue_reverse_fill=True)
                    active_session = None
                    if stop_signal.is_set():
                        should_refill = False
                        should_requeue_dispatch = False
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
                        should_requeue_dispatch = False
                        break
                    dispatch_delay_seconds = self._resolve_dispatch_delay_seconds()
                    if dispatch_delay_seconds > 0:
                        self._update_thread_step(thread_name, "等待提交间隔")
                elif outcome.status == "aborted":
                    self._release_round_resources(thread_name, requeue_reverse_fill=True)
                    should_refill = False
                    should_requeue_dispatch = False
                    break
                else:
                    dispatch_delay_seconds = self._resolve_dispatch_delay_seconds()
                    if dispatch_delay_seconds > 0:
                        self._update_thread_step(thread_name, "等待提交间隔")

            except AIRuntimeError as exc:
                if self._handle_ai_runtime_error(exc, stop_signal, thread_name=thread_name):
                    should_refill = False
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(thread_name, requeue_reverse_fill=True)
                continue
            except ProxyConnectionError:
                if self._handle_proxy_connection_error(active_session, stop_signal, thread_name=thread_name):
                    should_refill = False
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(thread_name, requeue_reverse_fill=True)
                continue
            except Exception:
                if stop_signal.is_set():
                    should_refill = False
                    should_requeue_dispatch = False
                    break
                traceback.print_exc()
                if self.stop_policy.record_failure(
                    stop_signal,
                    thread_name=thread_name,
                    failure_reason=FailureReason.FILL_FAILED,
                    consume_reverse_fill_attempt=False,
                ):
                    should_refill = False
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(thread_name, requeue_reverse_fill=True)
            finally:
                if active_session is not None:
                    active_session.dispose()
                    active_session = None
                if should_refill and not stop_signal.is_set():
                    pool.warm_async(preferred_browsers, window_x_pos, window_y_pos)
                self._ensure_dispatcher(stop_signal).release(
                    requeue=bool(should_requeue_dispatch and not stop_signal.is_set()),
                    delay_seconds=dispatch_delay_seconds,
                )

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
            browser_owner_pool=self.browser_owner_pool,
        )

        while True:
            if self._should_stop_loop(stop_signal):
                break
            if not self._acquire_dispatch_turn(thread_name, stop_signal):
                break

            should_requeue_dispatch = True
            dispatch_delay_seconds = 0.0
            driver_had_error = False
            try:
                if not self._prepare_round_context(stop_signal, thread_name=thread_name, session=session):
                    if stop_signal.is_set():
                        should_requeue_dispatch = False
                        break
                    continue

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
                    should_requeue_dispatch = False
                    break
                if session.driver is None:
                    self._release_round_resources(thread_name, requeue_reverse_fill=True)
                    continue

                assert session.driver is not None
                if not self.config.url:
                    logging.error("无法启动：问卷链接为空")
                    should_requeue_dispatch = False
                    break
                if not self._load_survey_or_record_failure(
                    session,
                    stop_signal,
                    thread_name=thread_name,
                    timed_mode_on=timed_mode_on,
                    timed_refresh_interval=timed_refresh_interval,
                ):
                    driver_had_error = True
                    self._release_round_resources(thread_name, requeue_reverse_fill=True)
                    if stop_signal.is_set():
                        should_requeue_dispatch = False
                        break
                    continue

                if self._handle_device_quota_limit(session, stop_signal, thread_name=thread_name):
                    self._release_round_resources(thread_name, requeue_reverse_fill=True)
                    if stop_signal.is_set():
                        should_requeue_dispatch = False
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
                        should_requeue_dispatch = False
                        break
                    dispatch_delay_seconds = self._resolve_dispatch_delay_seconds()
                    if dispatch_delay_seconds > 0:
                        self._update_thread_step(thread_name, "等待提交间隔")
                elif outcome.status == "aborted":
                    self._release_round_resources(thread_name, requeue_reverse_fill=True)
                    should_requeue_dispatch = False
                    break
                else:
                    driver_had_error = True
                    dispatch_delay_seconds = self._resolve_dispatch_delay_seconds()
                    if dispatch_delay_seconds > 0:
                        self._update_thread_step(thread_name, "等待提交间隔")

            except AIRuntimeError as exc:
                driver_had_error = True
                if self._handle_ai_runtime_error(exc, stop_signal, thread_name=thread_name):
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(thread_name, requeue_reverse_fill=True)
                continue
            except ProxyConnectionError:
                driver_had_error = True
                if self._handle_proxy_connection_error(session, stop_signal, thread_name=thread_name):
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(thread_name, requeue_reverse_fill=True)
                continue
            except Exception:
                driver_had_error = True
                if stop_signal.is_set():
                    should_requeue_dispatch = False
                    break
                traceback.print_exc()
                if self.stop_policy.record_failure(
                    stop_signal,
                    thread_name=thread_name,
                    failure_reason=FailureReason.FILL_FAILED,
                    consume_reverse_fill_attempt=False,
                ):
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(thread_name, requeue_reverse_fill=True)
            finally:
                if driver_had_error:
                    session.dispose()
                self._ensure_dispatcher(stop_signal).release(
                    requeue=bool(should_requeue_dispatch and not stop_signal.is_set()),
                    delay_seconds=dispatch_delay_seconds,
                )

        self._finalize_thread(session, thread_name=thread_name)


__all__ = ["ExecutionLoop"]
