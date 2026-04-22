"""线程执行主循环。"""

from __future__ import annotations

import logging
import random
import threading
import traceback
from typing import Any

import software.core.modes.timed_mode as timed_mode
from software.app.config import BROWSER_PREFERENCE
from software.core.ai.runtime import AIRuntimeError
from software.core.engine.browser_session_service import BrowserSessionService
from software.core.engine.failure_reason import FailureReason
from software.core.engine.provider_common import ensure_joint_psychometric_answer_plan
from software.core.engine.run_stop_policy import RunStopPolicy
from software.core.engine.submission_service import SubmissionService
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser import (
    ProxyConnectionError,
    describe_playwright_startup_error,
    is_playwright_startup_environment_error,
)
from software.network.session_policy import _discard_unresponsive_proxy, _record_bad_proxy_and_maybe_pause
from software.providers.registry import fill_survey as _provider_fill_survey
from software.providers.registry import is_device_quota_limit_page as _provider_is_device_quota_limit_page


class _SkipPsychoPlan:
    """标记对象，表示跳过心理测量计划（用于反填模式）。"""
    pass


class ExecutionLoop:
    """单个工作线程的执行主循环。"""

    def __init__(self, config: ExecutionConfig, state: ExecutionState, gui_instance: Any = None):
        self.config = config
        self.state = state
        self.gui_instance = gui_instance
        self.stop_policy = RunStopPolicy(config, state, gui_instance)
        self.submission_service = SubmissionService(config, state, self.stop_policy)

    def _fill_survey_with_backfill(
        self,
        driver,
        sample,
        stop_signal: threading.Event,
        thread_name: str
    ) -> bool:
        """使用反填数据填写问卷。
        
        Args:
            driver: 浏览器驱动
            sample: 样本数据（包含 normalized_answers）
            stop_signal: 停止信号
            thread_name: 线程名称
            
        Returns:
            是否填写完成
        """
        from software.core.backfill.answer_provider import BackfillAnswerProvider
        from software.core.questions.answer_context import backfill_answer_context
        
        # 创建答案提供者
        provider = BackfillAnswerProvider(sample.normalized_answers)
        
        # 使用上下文管理器
        with backfill_answer_context(provider):
            # 调用 provider 填写问卷
            # 在上下文中，所有 smart_select_* 函数会自动使用反填数据
            # 传递 _SkipPsychoPlan() 跳过心理测量计划的构建
            finished = _provider_fill_survey(
                driver,
                self.config,
                self.state,
                stop_signal=stop_signal,
                thread_name=thread_name,
                psycho_plan=_SkipPsychoPlan(),
                provider=self.config.survey_provider,
            )
        
        return finished

    def run_thread(
        self,
        window_x_pos: int,
        window_y_pos: int,
        stop_signal: threading.Event,
    ) -> None:
        thread_name = threading.current_thread().name or "Worker-?"
        try:
            self.state.update_thread_status(thread_name, "线程启动", running=True)
        except Exception:
            logging.info("更新线程状态失败：线程启动", exc_info=True)

        timed_mode_on = bool(self.config.timed_mode_enabled)
        try:
            timed_refresh_interval = float(self.config.timed_mode_refresh_interval or timed_mode.DEFAULT_REFRESH_INTERVAL)
        except Exception:
            timed_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
        if timed_refresh_interval <= 0:
            timed_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL

        base_browser_preference = list(self.config.browser_preference or BROWSER_PREFERENCE)
        preferred_browsers = list(base_browser_preference)
        session = BrowserSessionService(self.config, self.state, self.gui_instance, thread_name)

        logging.info("目标份数: %s, 当前进度: %s/%s", self.config.target_num, self.state.cur_num, self.config.target_num)
        if timed_mode_on:
            logging.info("定时模式已启用")
        if self.config.random_proxy_ip_enabled:
            logging.info("随机IP已启用")
        if self.config.random_user_agent_enabled:
            logging.info("随机UA已启用")

        while True:
            self.stop_policy.wait_if_paused(stop_signal)
            if stop_signal.is_set():
                break
            
            # === 检查完成条件 ===
            if self.config.backfill_enabled:
                # 反填模式：检查是否所有样本都已完成
                if self.state.sample_dispatcher and self.state.sample_dispatcher.is_all_success():
                    logging.info(f"线程 {thread_name}: 所有样本已完成，线程退出")
                    break
            else:
                # 随机模式：检查是否达到目标数量
                with self.state.lock:
                    if stop_signal.is_set() or (self.config.target_num > 0 and self.state.cur_num >= self.config.target_num):
                        break
            
            # === 获取样本（仅反填模式）===
            current_sample = None
            if self.config.backfill_enabled:
                if not self.state.sample_dispatcher:
                    logging.error(f"线程 {thread_name}: 反填模式已启用但 dispatcher 未初始化")
                    break
                current_sample = self.state.sample_dispatcher.get_next_sample(thread_name)
                if current_sample is None:
                    # 没有更多样本，线程退出
                    logging.info(f"线程 {thread_name}: 没有更多待处理样本，退出")
                    break
                logging.info(f"线程 {thread_name}: 获取样本 行号={current_sample.row_no}")


            if session.driver is None:
                try:
                    self.state.update_thread_step(thread_name, 0, 0, status_text="准备浏览器", running=True)
                except Exception:
                    logging.info("更新线程状态失败：准备浏览器", exc_info=True)
                try:
                    active_browser = session.create_browser(preferred_browsers, window_x_pos, window_y_pos)
                except Exception as exc:
                    if stop_signal.is_set():
                        break
                    friendly_error = describe_playwright_startup_error(exc)
                    logging.error("启动浏览器失败：%s", friendly_error)
                    if is_playwright_startup_environment_error(exc):
                        logging.critical("检测到本机环境阻止 Playwright 启动，任务停止。")
                        try:
                            self.state.update_thread_status(thread_name, "本机环境阻止浏览器启动", running=False)
                        except Exception:
                            logging.info("更新线程状态失败：本机环境阻止浏览器启动", exc_info=True)
                        if not stop_signal.is_set():
                            stop_signal.set()
                        break
                    stopped = self.stop_policy.record_failure(
                        stop_signal,
                        thread_name=thread_name,
                        failure_reason=FailureReason.BROWSER_START_FAILED,
                        status_text="浏览器启动失败",
                        log_message=f"浏览器启动失败，本轮按失败处理：{friendly_error}",
                    )
                    if stopped or stop_signal.wait(1.0):
                        break
                    continue

                if active_browser is None:
                    if stop_signal.is_set():
                        break
                    if self.config.random_proxy_ip_enabled:
                        stopped = self.stop_policy.record_failure(
                            stop_signal,
                            thread_name=thread_name,
                            failure_reason=FailureReason.PROXY_UNAVAILABLE,
                            status_text="代理不可用",
                            log_message="代理不可用，本轮按失败处理",
                        )
                        if stopped:
                            break
                    stop_signal.wait(0.8)
                    continue
                preferred_browsers = [active_browser] + [b for b in base_browser_preference if b != active_browser]

            assert session.driver is not None
            driver_had_error = False
            try:
                if stop_signal.is_set():
                    break
                if not self.config.url:
                    logging.error("无法启动：问卷链接为空")
                    break

                self.stop_policy.wait_if_paused(stop_signal)
                try:
                    self.state.update_thread_status(thread_name, "加载问卷", running=True)
                except Exception:
                    logging.info("更新线程状态失败：加载问卷", exc_info=True)

                try:
                    if timed_mode_on:
                        ready = timed_mode.wait_until_open(
                            session.driver,
                            self.config.url,
                            stop_signal,
                            refresh_interval=timed_refresh_interval,
                            logger=logging.info,
                        )
                        if not ready:
                            if not stop_signal.is_set():
                                stop_signal.set()
                            break
                    else:
                        session.driver.get(self.config.url)
                except Exception as exc:
                    stopped = self.stop_policy.record_failure(
                        stop_signal,
                        thread_name=thread_name,
                        failure_reason=FailureReason.PAGE_LOAD_FAILED,
                        status_text="加载问卷失败",
                        log_message=f"加载问卷失败，本轮按失败处理：{exc}",
                    )
                    driver_had_error = True
                    if stopped:
                        break
                    continue

                if _provider_is_device_quota_limit_page(session.driver, provider=self.config.survey_provider):
                    stopped = self.stop_policy.record_failure(
                        stop_signal,
                        thread_name=thread_name,
                        failure_reason=FailureReason.DEVICE_QUOTA_LIMIT,
                        status_text="设备达到填写次数上限",
                        log_message="设备达到填写次数上限，本轮按失败处理",
                    )
                    try:
                        self.state.update_thread_status(thread_name, "设备达到填写次数上限", running=True)
                    except Exception:
                        logging.info("更新线程状态失败：设备达到填写次数上限", exc_info=True)
                    session.dispose()
                    if stopped or stop_signal.is_set():
                        break
                    if self.config.random_proxy_ip_enabled:
                        try:
                            handler = getattr(self.gui_instance, "handle_random_ip_submission", None)
                            if callable(handler):
                                handler(stop_signal)
                        except Exception:
                            logging.info("设备上限失败后处理随机IP提交流程失败", exc_info=True)
                    continue

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
                        try:
                            self.state.update_thread_status(thread_name, "等待信效度配额槽位", running=True)
                        except Exception:
                            logging.info("更新线程状态失败：等待信效度配额槽位", exc_info=True)
                        if stop_signal.wait(0.2):
                            break
                        continue

                # === 填写问卷 ===
                if self.config.backfill_enabled and current_sample:
                    # 反填模式：使用反填答题逻辑
                    finished = self._fill_survey_with_backfill(
                        session.driver,
                        current_sample,
                        stop_signal,
                        thread_name
                    )
                else:
                    # 随机模式：使用原有逻辑
                    finished = _provider_fill_survey(
                        session.driver,
                        self.config,
                        self.state,
                        stop_signal=stop_signal,
                        thread_name=thread_name,
                        provider=self.config.survey_provider,
                    )
                
                if stop_signal.is_set() or not finished:
                    try:
                        self.state.release_joint_sample(thread_name)
                    except Exception:
                        logging.info("释放联合信效度样本槽位失败", exc_info=True)
                    # 反填模式：标记样本失败
                    if self.config.backfill_enabled and current_sample and self.state.sample_dispatcher:
                        self.state.sample_dispatcher.mark_sample_failed(
                            current_sample.row_no,
                            "填写未完成",
                            retry=True
                        )
                    continue

                outcome = self.submission_service.finalize_after_submit(
                    session.driver,
                    stop_signal=stop_signal,
                    gui_instance=self.gui_instance,
                    thread_name=thread_name,
                )
                if outcome.status == "success":
                    # 反填模式：标记样本成功
                    if self.config.backfill_enabled and current_sample and self.state.sample_dispatcher:
                        self.state.sample_dispatcher.mark_sample_success(current_sample.row_no)
                        logging.info(f"样本 {current_sample.row_no} 提交成功")
                    session.dispose()
                    if outcome.should_stop:
                        break
                elif outcome.status == "aborted":
                    try:
                        self.state.release_joint_sample(thread_name)
                    except Exception:
                        logging.info("释放联合信效度样本槽位失败", exc_info=True)
                    # 反填模式：标记样本失败
                    if self.config.backfill_enabled and current_sample and self.state.sample_dispatcher:
                        self.state.sample_dispatcher.mark_sample_failed(
                            current_sample.row_no,
                            "提交中止",
                            retry=False
                        )
                    break
                else:
                    # 反填模式：标记样本失败，允许重试
                    if self.config.backfill_enabled and current_sample and self.state.sample_dispatcher:
                        self.state.sample_dispatcher.mark_sample_failed(
                            current_sample.row_no,
                            "提交失败",
                            retry=True
                        )
                    driver_had_error = True

            except AIRuntimeError as exc:
                driver_had_error = True
                logging.error("AI 填空失败，已停止任务：%s", exc, exc_info=True)
                # 反填模式：标记样本失败
                if self.config.backfill_enabled and current_sample and self.state.sample_dispatcher:
                    self.state.sample_dispatcher.mark_sample_failed(
                        current_sample.row_no,
                        f"AI填空失败: {exc}",
                        retry=False
                    )
                if not stop_signal.is_set():
                    stop_signal.set()
                break
            except ProxyConnectionError:
                driver_had_error = True
                if stop_signal.is_set():
                    break
                logging.warning("提取到的代理质量过低，自动弃用更换下一个")
                if session.proxy_address:
                    _discard_unresponsive_proxy(self.state, session.proxy_address)
                # 反填模式：标记样本失败，允许重试
                if self.config.backfill_enabled and current_sample and self.state.sample_dispatcher:
                    self.state.sample_dispatcher.mark_sample_failed(
                        current_sample.row_no,
                        "代理连接失败",
                        retry=True
                    )
                if self.config.random_proxy_ip_enabled and session.proxy_address:
                    if _record_bad_proxy_and_maybe_pause(self.state, self.gui_instance):
                        break
                    stopped = self.stop_policy.record_failure(
                        stop_signal,
                        thread_name=thread_name,
                        failure_reason=FailureReason.PROXY_UNAVAILABLE,
                        status_text="代理不可用",
                        log_message="代理质量过低，本轮按失败处理",
                    )
                    if stopped:
                        break
                    stop_signal.wait(0.8)
                    continue
                if self.stop_policy.record_failure(stop_signal, thread_name=thread_name, failure_reason=FailureReason.PROXY_UNAVAILABLE):
                    break
            except Exception:
                driver_had_error = True
                if stop_signal.is_set():
                    break
                traceback.print_exc()
                # 反填模式：标记样本失败，允许重试
                if self.config.backfill_enabled and current_sample and self.state.sample_dispatcher:
                    self.state.sample_dispatcher.mark_sample_failed(
                        current_sample.row_no,
                        "未知异常",
                        retry=True
                    )
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
                    self.state.update_thread_status(thread_name, "等待提交间隔", running=True)
                except Exception:
                    logging.info("更新线程状态失败：等待提交间隔", exc_info=True)
                wait_seconds = min_wait if max_wait == min_wait else random.uniform(min_wait, max_wait)
                if stop_signal.wait(wait_seconds):
                    break

        try:
            self.state.release_joint_sample(thread_name)
        except Exception:
            logging.info("线程结束时释放联合信效度样本槽位失败", exc_info=True)
        try:
            self.state.mark_thread_finished(thread_name, status_text="已停止")
        except Exception:
            logging.info("更新线程状态失败：已停止", exc_info=True)
        session.shutdown()


__all__ = ["ExecutionLoop"]
