"""引擎主循环 - 任务执行与线程调度"""
import random
import threading
import time
import traceback
from typing import Any, Optional, Set
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception

import wjx.modes.duration_control as duration_control
import wjx.modes.timed_mode as timed_mode
from wjx.core.ai.runtime import AIRuntimeError
from wjx.core.captcha.control import _handle_aliyun_captcha_detected
from wjx.core.captcha.handler import AliyunCaptchaBypassError, EmptySurveySubmissionError, handle_aliyun_captcha
from wjx.core.engine.answering import brush
from wjx.core.engine.driver_factory import (
    create_browser_manager,
    create_playwright_driver,
    shutdown_browser_manager,
)
from wjx.core.engine.runtime_control import (
    _handle_submission_failure,
    _timed_mode_active,
    _trigger_target_reached_stop,
    _wait_if_paused,
)
from wjx.core.engine.submission import (
    _is_device_quota_limit_page,
    _normalize_url_for_compare,
    consume_headless_httpx_submit_success,
)
from wjx.core.task_context import TaskContext
from wjx.network.browser import (
    BrowserManager,
    BrowserDriver,
    ProxyConnectionError,
    TimeoutException,
)
from wjx.network.proxy import _proxy_is_responsive, handle_random_ip_submission
from wjx.network.session_policy import (
    _discard_unresponsive_proxy,
    _record_bad_proxy_and_maybe_pause,
    _reset_bad_proxy_streak,
    _select_proxy_for_session,
    _select_user_agent_for_session,
)
from wjx.utils.app.config import (
    BROWSER_PREFERENCE,
    HEADLESS_POST_SUBMIT_CLOSE_GRACE_SECONDS,
    POST_SUBMIT_CLOSE_GRACE_SECONDS,
    POST_SUBMIT_URL_MAX_WAIT,
    POST_SUBMIT_URL_POLL_INTERVAL,
)


def _submission_blocked_by_security_check(driver: BrowserDriver) -> bool:
    """检测提交后是否出现阿里云智能验证 DOM。"""

    script = r"""
        return (() => {
            const popupIds = [
                'aliyunCaptcha-window-popup',
                'aliyunCaptcha-title',
                'aliyunCaptcha-checkbox-wrapper',
                'aliyunCaptcha-checkbox-body',
                'aliyunCaptcha-checkbox-icon',
                'aliyunCaptcha-checkbox-left',
                'aliyunCaptcha-checkbox-text',
                'aliyunCaptcha-certifyId',
            ];

            const visible = (el, win) => {
                if (!el || !win) return false;
                const style = win.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };

            const docHasVisibleCaptchaDom = (doc) => {
                const win = doc.defaultView;
                if (!win) return false;
                for (const id of popupIds) {
                    const el = doc.getElementById(id);
                    if (visible(el, win)) return true;
                    }
                return false;
            };

            const scanDoc = (doc) => {
                if (!doc) return false;
                return docHasVisibleCaptchaDom(doc);
            };

            if (scanDoc(document)) return true;
            const frames = Array.from(document.querySelectorAll('iframe'));
            for (const frame of frames) {
                try {
                    const doc = frame.contentDocument || frame.contentWindow?.document;
                    if (scanDoc(doc)) return true;
                } catch (e) {}
            }
            return false;
        })();
    """
    try:
        return bool(driver.execute_script(script))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 浏览器生命周期管理（Phase 5 前临时封装）
# ---------------------------------------------------------------------------

class _BrowserSession:
    """封装单次浏览器会话的创建、注册、销毁逻辑。"""

    def __init__(self, ctx: TaskContext, gui_instance: Any, thread_name: str):
        self.ctx = ctx
        self.gui_instance = gui_instance
        self.thread_name = str(thread_name or "").strip()
        self.driver: Optional[BrowserDriver] = None
        self._browser_manager: Optional[BrowserManager] = None
        self.proxy_address: Optional[str] = None
        self.sem_acquired = False
        self._browser_sem = ctx.get_browser_semaphore(max(1, int(ctx.num_threads or 1)))

    def _register_driver(self, instance: BrowserDriver) -> None:
        if self.gui_instance and hasattr(self.gui_instance, 'active_drivers'):
            self.gui_instance.active_drivers.append(instance)

    def _unregister_driver(self, instance: BrowserDriver) -> None:
        if self.gui_instance and hasattr(self.gui_instance, 'active_drivers'):
            try:
                self.gui_instance.active_drivers.remove(instance)
            except ValueError as exc:
                log_suppressed_exception("_BrowserSession._unregister_driver remove", exc, level=logging.WARNING)

    def dispose(self) -> None:
        """释放本轮浏览器资源（仅 context/page）。"""
        if not self.driver:
            if self.thread_name:
                self.ctx.release_proxy_in_use(self.thread_name)
                self.proxy_address = None
            if self.sem_acquired:
                try:
                    self._browser_sem.release()
                    self.sem_acquired = False
                    logging.debug("已释放浏览器信号量（无浏览器实例）")
                except Exception as exc:
                    log_suppressed_exception("_BrowserSession.dispose release semaphore (no driver)", exc, level=logging.WARNING)
            return

        if not self.driver.mark_cleanup_done():
            logging.debug("浏览器实例已被其他线程清理，跳过")
            self.driver = None
            if self.sem_acquired:
                self._browser_sem.release()
                self.sem_acquired = False
            return

        driver_instance = self.driver
        self._unregister_driver(driver_instance)
        self.driver = None

        try:
            driver_instance.quit()
            logging.debug("已关闭浏览器 context/page")
        except Exception as exc:
            log_suppressed_exception("_BrowserSession.dispose driver.quit", exc, level=logging.WARNING)

        if self.thread_name:
            self.ctx.release_proxy_in_use(self.thread_name)
        self.proxy_address = None

        if self.sem_acquired:
            try:
                self._browser_sem.release()
                self.sem_acquired = False
                logging.debug("已释放浏览器信号量")
            except Exception as exc:
                log_suppressed_exception("_BrowserSession.dispose release semaphore", exc, level=logging.WARNING)

    def shutdown(self) -> None:
        """线程退出前关闭常驻底座 Browser。"""
        self.dispose()
        if self._browser_manager is not None:
            try:
                shutdown_browser_manager(self._browser_manager)
                logging.debug("已关闭 BrowserManager 底座")
            except Exception as exc:
                log_suppressed_exception("_BrowserSession.shutdown manager.close", exc, level=logging.WARNING)
            finally:
                self._browser_manager = None

    def create_browser(
        self,
        preferred_browsers: list,
        window_x_pos: int,
        window_y_pos: int,
    ) -> Optional[str]:
        """创建一个新的浏览器实例。返回实际使用的浏览器名称，失败返回 None。"""
        self.proxy_address = _select_proxy_for_session(self.ctx, self.thread_name)

        if self.ctx.random_proxy_ip_enabled and not self.proxy_address:
            if _record_bad_proxy_and_maybe_pause(self.ctx, self.gui_instance):
                return None  # 触发暂停

        if self.proxy_address:
            if not _proxy_is_responsive(self.proxy_address):
                logging.warning("提取到的代理质量过低，自动弃用更换下一个")
                _discard_unresponsive_proxy(self.ctx, self.proxy_address)
                if self.thread_name:
                    self.ctx.release_proxy_in_use(self.thread_name)
                self.proxy_address = None
                if self.ctx.random_proxy_ip_enabled:
                    _record_bad_proxy_and_maybe_pause(self.ctx, self.gui_instance)
                return None
            else:
                _reset_bad_proxy_streak(self.ctx)

        browser_proxy_address = self.proxy_address
        submit_proxy_address = None
        if self.ctx.headless_mode and self.proxy_address:
            # 无头模式下将页面流量固定走本机，只让最终提交请求走代理。
            browser_proxy_address = None
            submit_proxy_address = self.proxy_address

        ua_value, _ = _select_user_agent_for_session(self.ctx)

        if not self.sem_acquired:
            self._browser_sem.acquire()
            self.sem_acquired = True
            logging.debug("已获取浏览器信号量")

        try:
            if self._browser_manager is None:
                self._browser_manager = create_browser_manager(
                    headless=self.ctx.headless_mode,
                    prefer_browsers=list(preferred_browsers) if preferred_browsers else None,
                    window_position=(window_x_pos, window_y_pos),
                )
            self.driver, active_browser = create_playwright_driver(
                headless=self.ctx.headless_mode,
                prefer_browsers=list(preferred_browsers) if preferred_browsers else None,
                proxy_address=browser_proxy_address,
                user_agent=ua_value,
                window_position=(window_x_pos, window_y_pos),
                manager=self._browser_manager,
                persistent_browser=True,
            )
        except Exception:
            if self.sem_acquired:
                self._browser_sem.release()
                self.sem_acquired = False
                logging.debug("创建浏览器失败，已释放信号量")
            if self.thread_name:
                self.ctx.release_proxy_in_use(self.thread_name)
            self.proxy_address = None
            raise

        self._register_driver(self.driver)
        setattr(self.driver, "_submit_proxy_address", submit_proxy_address)
        self.driver.set_window_size(550, 650)
        return active_browser


# ---------------------------------------------------------------------------
# 提交后验证逻辑
# ---------------------------------------------------------------------------

def _wait_for_completion_page(
    driver: BrowserDriver,
    stop_signal: threading.Event,
    max_wait_seconds: float,
    poll_interval: float,
) -> bool:
    """轮询等待完成页出现，返回 True 表示检测到完成页。"""
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
            if duration_control.is_survey_completion_page(driver):
                return True
        except Exception as exc:
            log_suppressed_exception("runner._wait_for_completion_page", exc, level=logging.WARNING)
        time.sleep(poll_interval)
    return False


def _resolve_post_submit_close_grace_seconds(ctx: TaskContext) -> float:
    """根据模式返回提交成功后的浏览器关闭缓冲时间。"""
    if bool(getattr(ctx, "headless_mode", False)):
        return float(HEADLESS_POST_SUBMIT_CLOSE_GRACE_SECONDS or 0.0)
    return float(POST_SUBMIT_CLOSE_GRACE_SECONDS or 0.0)


def _check_captcha_after_submit(
    driver: BrowserDriver,
    ctx: TaskContext,
    stop_signal: threading.Event,
    gui_instance: Any,
    thread_name: Optional[str] = None,
) -> bool:
    """提交后检测阿里云验证码。返回 True 表示命中验证码。"""
    try:
        random_ip_enabled = bool(getattr(ctx, "random_proxy_ip_enabled", False))
        detected = handle_aliyun_captcha(
            driver,
            timeout=3,
            stop_signal=stop_signal,
            raise_on_detect=not random_ip_enabled,
            notify_on_detect=not random_ip_enabled,
        )
        if detected and random_ip_enabled:
            logging.warning("随机IP模式命中阿里云智能验证：仅记录失败并继续任务（不暂停、不弹窗）")
            _handle_submission_failure(ctx, stop_signal, thread_name=thread_name)
            _handle_aliyun_captcha_detected(ctx, gui_instance, stop_signal)
            return True
        return False
    except AliyunCaptchaBypassError:
        logging.warning("提交后检测到阿里云智能验证，触发验证码处理流程")
        _handle_submission_failure(ctx, stop_signal, thread_name=thread_name)
        _handle_aliyun_captcha_detected(ctx, gui_instance, stop_signal)
        return True
    except Exception as exc:
        logging.warning(f"验证码检测过程出现异常：{exc}")
        return False


def _record_successful_submission(
    ctx: TaskContext,
    stop_signal: threading.Event,
    gui_instance: Any,
    thread_name: Optional[str] = None,
) -> bool:
    """记录一次成功提交。返回 True 表示应该停止（已达目标）。"""
    should_handle_random_ip = False
    trigger_target_stop = False
    should_break = False
    record_thread_success = False
    previous_consecutive_failures = 0

    with ctx.lock:
        if ctx.target_num <= 0 or ctx.cur_num < ctx.target_num:
            previous_consecutive_failures = int(ctx.cur_fail or 0)
            ctx.cur_num += 1
            # 连续失败计数：一旦出现成功提交，立即全局清零。
            ctx.cur_fail = 0
            record_thread_success = True
            logging.info(
                f"[OK] 已填写{ctx.cur_num}份 - 连续失败{ctx.cur_fail}次 - {time.strftime('%H:%M:%S', time.localtime(time.time()))}"
            )
            if previous_consecutive_failures > 0:
                logging.debug("提交成功，连续失败计数已清零（重置前=%s）", previous_consecutive_failures)
            should_handle_random_ip = ctx.random_proxy_ip_enabled
            if ctx.target_num > 0 and ctx.cur_num >= ctx.target_num:
                trigger_target_stop = True
        else:
            should_break = True

    if record_thread_success and thread_name:
        try:
            ctx.commit_pending_distribution(thread_name)
        except Exception:
            logging.debug("提交成功后写入比例统计失败", exc_info=True)
        try:
            ctx.increment_thread_success(thread_name, status_text="提交成功")
        except Exception:
            logging.debug("更新线程成功计数失败", exc_info=True)
    if should_break:
        stop_signal.set()
    if trigger_target_stop:
        stop_signal.set()
        _trigger_target_reached_stop(ctx, stop_signal, gui_instance)
    if should_handle_random_ip:
        handle_random_ip_submission(gui_instance, stop_signal)

    return should_break or trigger_target_stop


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------

def run(
    window_x_pos: int,
    window_y_pos: int,
    stop_signal: threading.Event,
    gui_instance: Any = None,
    ctx: Optional[TaskContext] = None,
):
    """引擎主循环 - 创建浏览器、填写问卷、处理结果。"""
    # 如果没传 ctx，从 gui_instance 获取
    if ctx is None and gui_instance and hasattr(gui_instance, 'task_ctx'):
        ctx = gui_instance.task_ctx
    if ctx is None:
        raise ValueError("run() 必须传入 TaskContext，全局 state 兼容层已移除")
    thread_name = threading.current_thread().name or "Worker-?"
    try:
        ctx.update_thread_status(thread_name, "线程启动", running=True)
    except Exception:
        logging.debug("更新线程状态失败：线程启动", exc_info=True)

    timed_mode_on = _timed_mode_active(ctx)
    try:
        timed_refresh_interval = float(ctx.timed_mode_refresh_interval or timed_mode.DEFAULT_REFRESH_INTERVAL)
    except Exception:
        timed_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
    if timed_refresh_interval <= 0:
        timed_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL

    base_browser_preference = list(ctx.browser_preference or BROWSER_PREFERENCE)
    preferred_browsers = list(base_browser_preference)

    session = _BrowserSession(ctx, gui_instance, thread_name)

    logging.debug(f"目标份数: {ctx.target_num}, 当前进度: {ctx.cur_num}/{ctx.target_num}")
    if timed_mode_on:
        logging.debug("定时模式已启用")
    if ctx.random_proxy_ip_enabled:
        logging.debug("随机IP已启用")
    if ctx.random_user_agent_enabled:
        logging.debug("随机UA已启用")

    while True:
        _wait_if_paused(gui_instance, stop_signal)
        if stop_signal.is_set():
            break
        with ctx.lock:
            if stop_signal.is_set() or (ctx.target_num > 0 and ctx.cur_num >= ctx.target_num):
                break

        if stop_signal.is_set():
            break
        _wait_if_paused(gui_instance, stop_signal)

        # ── 1. 准备浏览器 ────────────────────────────────────────
        if session.driver is None:
            try:
                ctx.update_thread_step(
                    thread_name,
                    0,
                    0,
                    status_text="准备浏览器",
                    running=True,
                )
            except Exception:
                logging.debug("更新线程状态失败：准备浏览器", exc_info=True)
            try:
                active_browser = session.create_browser(
                    preferred_browsers, window_x_pos, window_y_pos,
                )
            except Exception as exc:
                if stop_signal.is_set():
                    break
                logging.error(f"启动浏览器失败：{exc}")
                traceback.print_exc()
                if stop_signal.wait(1.0):
                    break
                continue

            if active_browser is None:
                # create_browser 返回 None 意味着代理不可用或触发暂停
                if stop_signal.is_set():
                    break
                stop_signal.wait(0.8)
                continue

            preferred_browsers = [active_browser] + [b for b in base_browser_preference if b != active_browser]

        assert session.driver is not None  # 经过上方 None 分支的 break/continue 保证
        driver_had_error = False
        try:
            if stop_signal.is_set():
                break
            if not ctx.url:
                logging.error("无法启动：问卷链接为空")
                driver_had_error = True
                break
            _wait_if_paused(gui_instance, stop_signal)

            # ── 2. 导航到问卷页面 ────────────────────────────────
            try:
                ctx.update_thread_status(thread_name, "加载问卷", running=True)
            except Exception:
                logging.debug("更新线程状态失败：加载问卷", exc_info=True)
            if timed_mode_on:
                logging.debug("[Action Log] 定时模式：开始刷新等待问卷开放")
                ready = timed_mode.wait_until_open(
                    session.driver,
                    ctx.url,
                    stop_signal,
                    refresh_interval=timed_refresh_interval,
                    logger=logging.info,
                )
                if not ready:
                    if not stop_signal.is_set():
                        stop_signal.set()
                    break
            else:
                session.driver.get(ctx.url)
                if stop_signal.is_set():
                    break

            # ── 3. 设备配额限制检查 ──────────────────────────────
            if _is_device_quota_limit_page(session.driver):
                logging.warning("检测到设备已达到最大填写次数提示页，本轮按失败处理，不计入成功份数。")
                stopped = _handle_submission_failure(
                    ctx,
                    stop_signal,
                    thread_name=thread_name,
                    failure_reason="device_quota_limit",
                    status_text="设备达到填写次数上限",
                    log_message="设备达到填写次数上限，本轮按失败处理",
                )
                try:
                    ctx.update_thread_status(
                        thread_name,
                        "设备达到填写次数上限",
                        running=True,
                    )
                except Exception:
                    logging.debug("更新线程状态失败：设备达到填写次数上限", exc_info=True)
                session.dispose()
                if stopped:
                    logging.warning("设备达到填写次数上限且连续失败达到阈值，任务停止。")
                    break
                if stop_signal.is_set():
                    break
                if ctx.random_proxy_ip_enabled:
                    try:
                        handle_random_ip_submission(gui_instance, stop_signal)
                    except Exception:
                        logging.debug("设备上限失败后处理随机IP提交流程失败", exc_info=True)
                continue

            visited_urls: Set[str] = set()
            try:
                visited_urls.add(_normalize_url_for_compare(session.driver.current_url))
            except Exception:
                visited_urls.add(_normalize_url_for_compare(ctx.url))

            # ── 4. 答题 + 提交 ───────────────────────────────────
            while True:
                if stop_signal.is_set():
                    break
                try:
                    ctx.reset_pending_distribution(thread_name)
                except Exception:
                    logging.debug("重置本轮比例统计缓存失败", exc_info=True)
                finished = brush(session.driver, ctx=ctx, stop_signal=stop_signal)
                if stop_signal.is_set() or not finished:
                    break

                # 无头+httpx 已经拿到业务成功码时，直接按成功提交处理，避免完成页加载超时误判失败
                if ctx.headless_mode and consume_headless_httpx_submit_success(session.driver):
                    grace_seconds = _resolve_post_submit_close_grace_seconds(ctx)
                    if grace_seconds > 0 and not stop_signal.is_set():
                        time.sleep(grace_seconds)
                    session.dispose()
                    stopped = _record_successful_submission(
                        ctx,
                        stop_signal,
                        gui_instance,
                        thread_name=thread_name,
                    )
                    if stopped:
                        pass
                    break

                # 提交后短暂等待
                post_submit_wait = random.uniform(0.2, 0.6)
                if stop_signal.wait(post_submit_wait):
                    break

                # ── 5. 验证提交结果 ──────────────────────────────
                # 5a. 立即检测阿里云验证码
                if not stop_signal.is_set():
                    if _check_captcha_after_submit(
                        session.driver,
                        ctx,
                        stop_signal,
                        gui_instance,
                        thread_name=thread_name,
                    ):
                        driver_had_error = True
                        break

                # 5b. 阿里云验证码 DOM 检测
                if not stop_signal.is_set() and _submission_blocked_by_security_check(session.driver):
                    driver_had_error = True
                    logging.warning("提交后检测到阿里云智能验证DOM，触发验证码处理流程")
                    _handle_submission_failure(ctx, stop_signal, thread_name=thread_name)
                    _handle_aliyun_captcha_detected(ctx, gui_instance, stop_signal)
                    break

                # 5c. 等待完成页出现
                wait_seconds = max(3.0, float(POST_SUBMIT_URL_MAX_WAIT or 0.0) * 6.0)
                poll_interval = max(0.05, float(POST_SUBMIT_URL_POLL_INTERVAL or 0.1))
                completion_detected = _wait_for_completion_page(
                    session.driver, stop_signal, wait_seconds, poll_interval,
                )

                # 等待期间再次检查阿里云验证码 DOM
                if not completion_detected and not stop_signal.is_set():
                    if _submission_blocked_by_security_check(session.driver):
                        driver_had_error = True
                        logging.warning("提交后等待完成页期间命中阿里云智能验证DOM，触发验证码处理流程")
                        _handle_submission_failure(ctx, stop_signal, thread_name=thread_name)
                        _handle_aliyun_captcha_detected(ctx, gui_instance, stop_signal)
                        break

                if driver_had_error or stop_signal.is_set():
                    break

                # 5d. 未检测到完成页时再次检测验证码
                if not completion_detected:
                    if _check_captcha_after_submit(
                        session.driver,
                        ctx,
                        stop_signal,
                        gui_instance,
                        thread_name=thread_name,
                    ):
                        driver_had_error = True
                        break

                if not completion_detected:
                    raise TimeoutException("提交后未检测到完成页")

                # ── 6. 记录成功 ──────────────────────────────────
                grace_seconds = _resolve_post_submit_close_grace_seconds(ctx)
                if grace_seconds > 0 and not stop_signal.is_set():
                    time.sleep(grace_seconds)
                session.dispose()
                stopped = _record_successful_submission(
                    ctx,
                    stop_signal,
                    gui_instance,
                    thread_name=thread_name,
                )
                if stopped:
                    pass  # 会在外层 while 检查 stop_signal 后 break
                break

        except AliyunCaptchaBypassError:
            driver_had_error = True
            _handle_submission_failure(ctx, stop_signal, thread_name=thread_name)
            _handle_aliyun_captcha_detected(ctx, gui_instance, stop_signal)
            break
        except AIRuntimeError as exc:
            driver_had_error = True
            logging.error("AI 填空失败，已停止任务：%s", exc, exc_info=True)
            if stop_signal and not stop_signal.is_set():
                stop_signal.set()
            break
        except TimeoutException as exc:
            if stop_signal.is_set():
                break
            logging.debug("提交未完成（未检测到完成页）：%s", exc)

            # 额外等待完成页
            extra_wait_seconds = max(1.0, float(POST_SUBMIT_URL_MAX_WAIT or 0.0) * 3.0)
            extra_poll = max(0.05, float(POST_SUBMIT_URL_POLL_INTERVAL or 0.1))
            completion_detected = _wait_for_completion_page(
                session.driver, stop_signal, extra_wait_seconds, extra_poll,
            )

            if not completion_detected and not stop_signal.is_set():
                if _check_captcha_after_submit(
                    session.driver,
                    ctx,
                    stop_signal,
                    gui_instance,
                    thread_name=thread_name,
                ):
                    driver_had_error = True
                    break

            if not completion_detected and not stop_signal.is_set():
                try:
                    current_url = session.driver.current_url
                except Exception:
                    current_url = ""
                if "complete" in str(current_url).lower():
                    completion_detected = True
                else:
                    try:
                        completion_detected = bool(duration_control.is_survey_completion_page(session.driver))
                    except Exception:
                        completion_detected = False

            if completion_detected:
                driver_had_error = False
                grace_seconds = _resolve_post_submit_close_grace_seconds(ctx)
                if grace_seconds > 0 and not stop_signal.is_set():
                    time.sleep(grace_seconds)
                session.dispose()
                stopped = _record_successful_submission(
                    ctx,
                    stop_signal,
                    gui_instance,
                    thread_name=thread_name,
                )
                if stopped:
                    continue  # 外层 while 会 break
                continue

            driver_had_error = True
            if _handle_submission_failure(ctx, stop_signal, thread_name=thread_name):
                break

        except ProxyConnectionError:
            driver_had_error = True
            if stop_signal.is_set():
                break
            logging.warning("提取到的代理质量过低，自动弃用更换下一个")
            if session.proxy_address:
                _discard_unresponsive_proxy(ctx, session.proxy_address)
            if ctx.random_proxy_ip_enabled and session.proxy_address:
                if _record_bad_proxy_and_maybe_pause(ctx, gui_instance):
                    break
                stop_signal.wait(0.8)
                continue
            if _handle_submission_failure(ctx, stop_signal, thread_name=thread_name):
                break
        except EmptySurveySubmissionError:
            driver_had_error = True
            if stop_signal.is_set():
                break
            if _handle_submission_failure(ctx, stop_signal, thread_name=thread_name):
                break
        except Exception:
            driver_had_error = True
            if stop_signal.is_set():
                break
            traceback.print_exc()
            if _handle_submission_failure(ctx, stop_signal, thread_name=thread_name):
                break
        finally:
            if driver_had_error:
                session.dispose()

        if stop_signal.is_set():
            break
        min_wait, max_wait = ctx.submit_interval_range_seconds
        if max_wait > 0:
            try:
                ctx.update_thread_status(thread_name, "等待提交间隔", running=True)
            except Exception:
                logging.debug("更新线程状态失败：等待提交间隔", exc_info=True)
            wait_seconds = min_wait if max_wait == min_wait else random.uniform(min_wait, max_wait)
            if stop_signal.wait(wait_seconds):
                break

    try:
        ctx.mark_thread_finished(thread_name, status_text="已停止")
    except Exception:
        logging.debug("更新线程状态失败：已停止", exc_info=True)
    session.shutdown()
