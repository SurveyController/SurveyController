"""Async-first fill runtime loop."""

from __future__ import annotations

import asyncio
import logging
import random
import traceback
from typing import Any, Optional, cast

import software.core.modes.timed_mode as timed_mode
from software.app.config import BROWSER_PREFERENCE
from software.core.ai.runtime import AIRuntimeError
from software.core.engine.async_events import AsyncRunContext, ThreadEventProxy
from software.core.engine.async_scheduler import AsyncScheduler
from software.core.engine.failure_reason import FailureReason
from software.core.engine.page_loader import exception_summary as _page_load_exception_summary
from software.core.engine.page_loader import load_survey_page as _page_loader_load_survey_page
from software.core.engine.page_load_probe import wait_for_page_probe
from software.core.engine.provider_common import ensure_joint_psychometric_answer_plan
from software.core.engine.run_stop_policy import RunStopPolicy
from software.core.engine.runtime_error_handlers import handle_ai_runtime_error as _handle_ai_runtime_error_impl
from software.core.engine.runtime_error_handlers import handle_proxy_connection_error as _handle_proxy_connection_error_impl
from software.core.engine.submission_service import SubmissionService
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser import ProxyConnectionError
from software.network.browser.async_owner_pool import AsyncBrowserOwnerPool, AsyncBrowserSession
from software.network.proxy.pool import is_proxy_responsive
from software.network.proxy.sidecar_manager import ProxySidecarError, get_proxy_sidecar_client
from software.network.session_policy import (
    _discard_unresponsive_proxy,
    _mark_proxy_temporarily_bad,
    _record_bad_proxy_and_maybe_pause,
    _select_proxy_for_session,
    _select_user_agent_for_session,
)
from software.providers.registry import fill_survey
from software.providers.registry import is_device_quota_limit_page as _provider_is_device_quota_limit_page


def _load_survey_page(driver: Any, config: ExecutionConfig, *, phase_updater: Any = None) -> None:
    return _page_loader_load_survey_page(
        driver,
        config,
        phase_updater=phase_updater,
        probe_waiter=wait_for_page_probe,
    )


class AsyncSlotRunner:
    """One logical slot running repeated fill attempts as coroutines."""

    def __init__(
        self,
        *,
        slot_id: int,
        config: ExecutionConfig,
        state: ExecutionState,
        run_context: AsyncRunContext,
        scheduler: AsyncScheduler,
        browser_pool: AsyncBrowserOwnerPool,
        gui_instance: Any = None,
    ) -> None:
        self.slot_id = max(1, int(slot_id or 1))
        self.slot_label = f"Slot-{self.slot_id}"
        self.config = config
        self.state = state
        self.run_context = run_context
        self.scheduler = scheduler
        self.browser_pool = browser_pool
        self.gui_instance = gui_instance
        self.stop_proxy = ThreadEventProxy(run_context.stop_event, loop=asyncio.get_running_loop())
        self.stop_policy = RunStopPolicy(config, state, gui_instance)
        self.submission_service = SubmissionService(config, state, self.stop_policy)
        self.proxy_address: Optional[str] = None

    def _update_status(self, status_text: str, *, running: bool = True) -> None:
        try:
            self.state.update_thread_status(self.slot_label, status_text, running=running)
        except Exception:
            logging.info("更新 slot 状态失败：%s", status_text, exc_info=True)

    def _update_step(self, status_text: str) -> None:
        try:
            self.state.update_thread_step(self.slot_label, 0, 0, status_text=status_text, running=True)
        except Exception:
            logging.info("更新 slot 步骤失败：%s", status_text, exc_info=True)

    def _resolve_timed_refresh_interval(self) -> float:
        try:
            refresh_interval = float(self.config.timed_mode_refresh_interval or timed_mode.DEFAULT_REFRESH_INTERVAL)
        except Exception:
            refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
        if refresh_interval <= 0:
            refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
        return refresh_interval

    async def _should_stop_loop(self) -> bool:
        await self.run_context.wait_if_paused()
        if self.run_context.stop_requested():
            return True
        with self.state.lock:
            return bool(self.config.target_num > 0 and self.state.cur_num >= self.config.target_num)

    async def _sleep_or_stop(self, seconds: float) -> bool:
        delay = max(0.0, float(seconds or 0.0))
        if delay <= 0:
            return self.run_context.stop_requested()
        try:
            await asyncio.wait_for(self.run_context.stop_event.wait(), timeout=delay)
            return True
        except asyncio.TimeoutError:
            return self.run_context.stop_requested()

    def _resolve_dispatch_delay_seconds(self) -> float:
        min_wait, max_wait = self.config.submit_interval_range_seconds
        if max_wait <= 0:
            return 0.0
        if max_wait == min_wait:
            return float(min_wait)
        return float(random.uniform(min_wait, max_wait))

    async def _prepare_round_context(self) -> bool:
        try:
            self.state.reset_pending_distribution(self.slot_label)
        except Exception:
            logging.info("重置本轮比例统计缓存失败", exc_info=True)

        joint_answer_plan = ensure_joint_psychometric_answer_plan(self.config)
        sample_count = 0
        if joint_answer_plan is not None:
            sample_count = int(getattr(joint_answer_plan, "sample_count", self.config.target_num) or self.config.target_num)

        while True:
            if self.run_context.stop_requested():
                return False

            reserved_sample_index = None
            if sample_count > 0:
                reserved_sample_index = self.state.reserve_joint_sample(sample_count, thread_name=self.slot_label)

            reverse_fill_sample = self.state.acquire_reverse_fill_sample(self.slot_label)

            if sample_count > 0 and reserved_sample_index is None:
                if reverse_fill_sample.status == "acquired":
                    try:
                        self.state.release_reverse_fill_sample(self.slot_label, requeue=True)
                    except Exception:
                        logging.info("等待信效度配额时回收反填样本失败", exc_info=True)
                self._update_status("等待信效度配额槽位")
                await asyncio.sleep(0.5)
                continue

            if reverse_fill_sample.status == "waiting":
                if reserved_sample_index is not None:
                    try:
                        self.state.release_joint_sample(self.slot_label)
                    except Exception:
                        logging.info("等待反填样本时释放联合信效度样本槽位失败", exc_info=True)
                self._update_status("等待反填样本")
                await asyncio.sleep(0.5)
                continue

            if reverse_fill_sample.status == "exhausted":
                message = "反填样本已耗尽，剩余样本不足以完成目标份数"
                if reserved_sample_index is not None:
                    try:
                        self.state.release_joint_sample(self.slot_label)
                    except Exception:
                        logging.info("反填样本耗尽时释放联合信效度样本槽位失败", exc_info=True)
                self.state.mark_terminal_stop(
                    "reverse_fill_exhausted",
                    failure_reason=FailureReason.FILL_FAILED.value,
                    message=message,
                )
                self._update_status("反填样本不足", running=False)
                self.run_context.stop_event.set()
                return False

            if reverse_fill_sample.status == "acquired" and reverse_fill_sample.sample is not None:
                logging.info(
                    "会话[%s]已锁定反填样本：数据行=%s 工作表行=%s",
                    self.slot_label,
                    reverse_fill_sample.sample.data_row_number,
                    reverse_fill_sample.sample.worksheet_row_number,
                )
            return True

    def _release_round_resources(self, *, requeue_reverse_fill: bool) -> None:
        try:
            self.state.release_joint_sample(self.slot_label)
        except Exception:
            logging.info("释放联合信效度样本槽位失败", exc_info=True)
        try:
            self.state.release_reverse_fill_sample(self.slot_label, requeue=requeue_reverse_fill)
        except Exception:
            logging.info("释放反填样本失败", exc_info=True)

    def _select_session_proxy_and_ua(self) -> tuple[Optional[str], Optional[str]]:
        should_wait_for_proxy = bool(self.config.random_proxy_ip_enabled)
        if self.config.random_proxy_ip_enabled:
            self._update_step("获取代理")
        proxy_address = _select_proxy_for_session(
            self.state,
            self.slot_label,
            stop_signal=self.stop_proxy,
            wait=should_wait_for_proxy,
        )
        if self.config.random_proxy_ip_enabled and not proxy_address:
            if _record_bad_proxy_and_maybe_pause(self.state, self.gui_instance):
                return None, None
        if proxy_address and not is_proxy_responsive(proxy_address):
            logging.warning("提取到的代理质量过低，自动弃用更换下一个")
            _discard_unresponsive_proxy(self.state, proxy_address)
            self.state.release_proxy_in_use(self.slot_label)
            try:
                get_proxy_sidecar_client().release_lease(thread_name=self.slot_label, requeue=False)
            except ProxySidecarError:
                logging.info("释放 sidecar 代理占用失败", exc_info=True)
            return None, None
        ua_value, _ = _select_user_agent_for_session(self.state)
        return proxy_address, ua_value

    async def _open_session(self) -> Optional[AsyncBrowserSession]:
        if self.run_context.stop_requested():
            return None
        proxy_address, ua_value = await asyncio.to_thread(self._select_session_proxy_and_ua)
        if self.run_context.stop_requested():
            return None
        if self.config.random_proxy_ip_enabled and not proxy_address:
            return None
        self.proxy_address = proxy_address
        self._update_step("创建浏览器会话")
        session = await self.browser_pool.open_session(proxy_address=proxy_address, user_agent=ua_value)
        driver = session.driver
        setattr(driver, "_thread_name", self.slot_label)
        setattr(driver, "_session_state", self.state)
        setattr(driver, "_session_proxy_address", proxy_address)
        return session

    async def _close_session(self, session: Optional[AsyncBrowserSession]) -> None:
        if session is not None:
            await session.close()
        if self.proxy_address:
            try:
                self.state.release_proxy_in_use(self.slot_label)
            except Exception:
                logging.info("释放代理占用失败", exc_info=True)
            try:
                await asyncio.to_thread(
                    get_proxy_sidecar_client().release_lease,
                    thread_name=self.slot_label,
                    requeue=False,
                )
            except ProxySidecarError:
                logging.info("释放 sidecar 代理占用失败", exc_info=True)
        self.proxy_address = None

    async def _load_survey_or_record_failure(self, session: AsyncBrowserSession) -> bool:
        if self.run_context.stop_requested():
            return False
        await self.run_context.wait_if_paused()
        self._update_step("加载问卷")
        try:
            if self.config.timed_mode_enabled:
                ready = await asyncio.to_thread(
                    timed_mode.wait_until_open,
                    session.driver,
                    self.config.url,
                    self.stop_proxy,
                    refresh_interval=self._resolve_timed_refresh_interval(),
                    logger=logging.info,
                )
                if not ready:
                    self.run_context.stop_event.set()
                    return False
            else:
                await asyncio.to_thread(
                    _load_survey_page,
                    session.driver,
                    self.config,
                    phase_updater=lambda status_text: self._update_step(status_text),
                )
        except ProxyConnectionError:
            raise
        except Exception as exc:
            self.stop_policy.record_failure(
                self.stop_proxy,
                thread_name=self.slot_label,
                failure_reason=FailureReason.PAGE_LOAD_FAILED,
                status_text="加载问卷失败",
                log_message=f"加载问卷失败，本轮按失败处理：{_page_load_exception_summary(exc)}",
                consume_reverse_fill_attempt=False,
            )
            return False
        return True

    async def _handle_device_quota_limit(self, session: AsyncBrowserSession) -> bool:
        hit = await _provider_is_device_quota_limit_page(
            session.driver,
            provider=self.config.survey_provider,
        )
        if not hit:
            return False
        stopped = self.stop_policy.record_failure(
            self.stop_proxy,
            thread_name=self.slot_label,
            failure_reason=FailureReason.DEVICE_QUOTA_LIMIT,
            status_text="设备达到填写次数上限",
            log_message="设备达到填写次数上限，本轮按失败处理",
            consume_reverse_fill_attempt=False,
        )
        if stopped:
            self.run_context.stop_event.set()
        self._update_status("设备达到填写次数上限")
        if not stopped and not self.run_context.stop_requested() and self.config.random_proxy_ip_enabled:
            handler = getattr(self.gui_instance, "handle_random_ip_submission", None)
            if callable(handler):
                await asyncio.to_thread(handler, self.stop_proxy)
        return True

    async def _finalize_after_submit(self, session: AsyncBrowserSession) -> Any:
        return await asyncio.to_thread(
            self.submission_service.finalize_after_submit,
            session.driver,
            stop_signal=self.stop_proxy,
            gui_instance=self.gui_instance,
            thread_name=self.slot_label,
        )

    async def _wait_for_next_unique_proxy(self) -> bool:
        if not self.config.random_proxy_ip_enabled:
            return True
        self._update_status("等待新代理")
        while not self.run_context.stop_requested():
            stopped = await asyncio.to_thread(
                self.state.wait_for_runtime_change,
                stop_signal=self.stop_proxy,
                timeout=0.5,
            )
            if stopped:
                return False
            return True
        return False

    def _handle_proxy_unavailable(self, *, status_text: str, log_message: str) -> bool:
        threshold_getter = getattr(self.stop_policy, "proxy_unavailable_threshold", None)
        threshold_value = threshold_getter() if callable(threshold_getter) else None
        threshold_override = (
            int(cast(int, threshold_value))
            if threshold_value is not None
            else max(1, int(self.config.fail_threshold or 1), int(self.config.num_threads or 1))
        )
        stopped = self.stop_policy.record_failure(
            self.stop_proxy,
            thread_name=self.slot_label,
            failure_reason=FailureReason.PROXY_UNAVAILABLE,
            status_text=status_text,
            log_message=log_message,
            threshold_override=threshold_override,
            terminal_stop_category="proxy_unavailable_threshold",
            consume_reverse_fill_attempt=False,
        )
        if stopped:
            self.run_context.stop_event.set()
            return True
        if self.config.random_proxy_ip_enabled and _record_bad_proxy_and_maybe_pause(self.state, self.gui_instance):
            return True
        return False

    def _handle_proxy_connection_error(self, session: Optional[AsyncBrowserSession]) -> bool:
        holder = type("_AsyncSessionHolder", (), {"proxy_address": self.proxy_address})()
        del session
        return _handle_proxy_connection_error_impl(
            holder,
            self.stop_proxy,
            thread_name=self.slot_label,
            state=self.state,
            config=self.config,
            stop_policy=self.stop_policy,
            update_thread_status=lambda name, status_text: self._update_status(status_text),
            handle_proxy_unavailable=lambda _stop_signal, **kwargs: self._handle_proxy_unavailable(
                status_text=str(kwargs.get("status_text") or "代理不可用"),
                log_message=str(kwargs.get("log_message") or "代理连接失败"),
            ),
            mark_proxy_temporarily_bad=_mark_proxy_temporarily_bad,
        )

    async def _handle_ai_runtime_error(self, exc: AIRuntimeError) -> bool:
        return await asyncio.to_thread(
            _handle_ai_runtime_error_impl,
            exc,
            self.stop_proxy,
            thread_name=self.slot_label,
            stop_policy=self.stop_policy,
            state=self.state,
        )

    async def run(self) -> None:
        self._update_status("会话启动", running=True)
        base_browser_preference = list(self.config.browser_preference or BROWSER_PREFERENCE)
        del base_browser_preference
        while True:
            if await self._should_stop_loop():
                break
            token_id = await self.scheduler.acquire()
            if token_id is None:
                break
            session: Optional[AsyncBrowserSession] = None
            should_requeue_dispatch = True
            dispatch_delay_seconds = 0.0
            try:
                if not await self._prepare_round_context():
                    should_requeue_dispatch = False
                    if self.run_context.stop_requested():
                        break
                    continue
                session = await self._open_session()
                if session is None:
                    self._release_round_resources(requeue_reverse_fill=True)
                    if self.run_context.stop_requested():
                        should_requeue_dispatch = False
                        break
                    continue
                if not await self._load_survey_or_record_failure(session):
                    self._release_round_resources(requeue_reverse_fill=True)
                    if self.run_context.stop_requested():
                        should_requeue_dispatch = False
                        break
                    continue
                if await self._handle_device_quota_limit(session):
                    self._release_round_resources(requeue_reverse_fill=True)
                    if self.run_context.stop_requested():
                        should_requeue_dispatch = False
                        break
                    continue
                finished = await fill_survey(
                    session.driver,
                    self.config,
                    self.state,
                    stop_signal=self.stop_proxy,
                    thread_name=self.slot_label,
                    provider=self.config.survey_provider,
                )
                if self.run_context.stop_requested() or not finished:
                    self._release_round_resources(requeue_reverse_fill=True)
                    if self.run_context.stop_requested():
                        should_requeue_dispatch = False
                        break
                    continue
                outcome = await self._finalize_after_submit(session)
                if outcome.status == "success":
                    if bool(getattr(outcome, "should_rotate_proxy", False)):
                        await self._close_session(session)
                        session = None
                        if not await self._wait_for_next_unique_proxy():
                            should_requeue_dispatch = False
                            break
                    if outcome.should_stop:
                        should_requeue_dispatch = False
                        break
                    dispatch_delay_seconds = self._resolve_dispatch_delay_seconds()
                    if dispatch_delay_seconds > 0:
                        self._update_step("等待提交间隔")
                elif outcome.status == "aborted":
                    self._release_round_resources(requeue_reverse_fill=True)
                    should_requeue_dispatch = False
                    break
                else:
                    dispatch_delay_seconds = self._resolve_dispatch_delay_seconds()
                    if dispatch_delay_seconds > 0:
                        self._update_step("等待提交间隔")
            except AIRuntimeError as exc:
                if await self._handle_ai_runtime_error(exc):
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(requeue_reverse_fill=True)
            except ProxyConnectionError:
                if self._handle_proxy_connection_error(session):
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(requeue_reverse_fill=True)
            except Exception:
                if self.run_context.stop_requested():
                    should_requeue_dispatch = False
                    break
                traceback.print_exc()
                if self.stop_policy.record_failure(
                    self.stop_proxy,
                    thread_name=self.slot_label,
                    failure_reason=FailureReason.FILL_FAILED,
                    consume_reverse_fill_attempt=False,
                ):
                    should_requeue_dispatch = False
                    break
                self._release_round_resources(requeue_reverse_fill=True)
            finally:
                await self._close_session(session)
                await self.scheduler.release(
                    int(token_id),
                    requeue=bool(should_requeue_dispatch and not self.run_context.stop_requested()),
                    delay_seconds=dispatch_delay_seconds,
                )
        try:
            self.state.release_joint_sample(self.slot_label)
            self.state.release_reverse_fill_sample(self.slot_label, requeue=True)
            self.state.mark_thread_finished(self.slot_label, status_text="已停止")
        except Exception:
            logging.info("slot 收尾状态更新失败", exc_info=True)


__all__ = ["AsyncSlotRunner"]
