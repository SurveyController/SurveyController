"""浏览器会话服务。"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from software.core.engine.stop_signal import StopSignalLike
from software.network.browser.manager import (
    BrowserManager,
    create_browser_manager,
    shutdown_browser_manager,
)
from software.network.browser.session import BrowserDriver
from software.network.browser.transient import create_playwright_driver
from software.core.task import ExecutionConfig, ExecutionState
from software.logging.log_utils import log_suppressed_exception
from software.network.browser.owner_pool import BrowserOwnerLease, BrowserOwnerPool
from software.network.proxy.pool import is_http_proxy_connect_responsive
from software.network.session_policy import (
    _lease_skips_generic_connect_check,
    _lease_needs_preuse_recheck,
    _discard_unresponsive_proxy,
    _record_bad_proxy_and_maybe_pause,
    _select_proxy_for_session,
    _select_user_agent_for_session,
)

_HEADED_RUNTIME_WINDOW_SIZE = (550, 650)
_BROWSER_CREATE_RETRY_DELAYS_SECONDS = (0.35,)
_PROXY_LAUNCH_ERROR_MARKERS = (
    "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_PROXY_CONNECTION_FAILED",
    "ERR_NO_SUPPORTED_PROXIES",
    "ERR_CONNECTION_CLOSED",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_TIMED_OUT",
    "ERR_TIMED_OUT",
    "ERR_NAME_NOT_RESOLVED",
    "ERR_ADDRESS_UNREACHABLE",
)
_TRANSIENT_BROWSER_CREATE_ERROR_MARKERS = (
    "Target page, context or browser has been closed",
    "browser has been closed",
    "connection closed",
    "has been disconnected",
    "closed unexpectedly",
    "pipe closed",
)


def _resolve_runtime_window_size(config: ExecutionConfig) -> Optional[tuple[int, int]]:
    """无头模式保留较大视口，避免部分站点在小视口下退化为空白页。"""
    if bool(getattr(config, "headless_mode", False)):
        return None
    return _HEADED_RUNTIME_WINDOW_SIZE


def _exception_summary(exc: BaseException) -> str:
    text = str(exc or "").strip()
    if text:
        return text
    return type(exc).__name__


def _looks_like_proxy_launch_error(exc: BaseException) -> bool:
    message = _exception_summary(exc)
    return any(marker in message for marker in _PROXY_LAUNCH_ERROR_MARKERS)


def _looks_like_transient_browser_create_error(exc: BaseException) -> bool:
    message = _exception_summary(exc)
    lowered = message.lower()
    if any(marker.lower() in lowered for marker in _TRANSIENT_BROWSER_CREATE_ERROR_MARKERS):
        return True
    return type(exc).__name__ in {"TimeoutError", "CancelledError"}


class BrowserSessionService:
    """封装单次浏览器会话的创建、注册、销毁逻辑。"""

    def __init__(
        self,
        config: ExecutionConfig,
        state: ExecutionState,
        gui_instance: Any,
        thread_name: str,
        *,
        browser_owner_pool: Optional[BrowserOwnerPool] = None,
    ):
        self.config = config
        self.state = state
        self.gui_instance = gui_instance
        self.thread_name = str(thread_name or "").strip()
        self.driver: Optional[BrowserDriver] = None
        self._browser_manager: Optional[BrowserManager] = None
        self._browser_owner_pool = browser_owner_pool
        self._browser_owner_lease: Optional[BrowserOwnerLease] = None
        self.proxy_address: Optional[str] = None
        self.sem_acquired = False
        self._browser_sem = state.get_browser_semaphore(max(1, int(config.num_threads or 1)))

    def _update_phase(self, status_text: str) -> None:
        if not self.thread_name:
            return
        try:
            self.state.update_thread_step(
                self.thread_name,
                0,
                0,
                status_text=str(status_text or ""),
                running=True,
            )
        except Exception as exc:
            log_suppressed_exception("BrowserSessionService._update_phase", exc, level=logging.INFO)

    def _register_driver(self, instance: BrowserDriver) -> None:
        register = getattr(self.gui_instance, "register_cleanup_target", None)
        if callable(register):
            register(instance)
            return
        if self.gui_instance and hasattr(self.gui_instance, "active_drivers"):
            self.gui_instance.active_drivers.append(instance)

    def _unregister_driver(self, instance: BrowserDriver) -> None:
        unregister = getattr(self.gui_instance, "unregister_cleanup_target", None)
        if callable(unregister):
            unregister(instance)
            return
        if self.gui_instance and hasattr(self.gui_instance, "active_drivers"):
            try:
                self.gui_instance.active_drivers.remove(instance)
            except ValueError as exc:
                log_suppressed_exception("BrowserSessionService._unregister_driver remove", exc, level=logging.WARNING)

    def dispose(self) -> None:
        if not self.driver:
            self._release_owner_lease()
            if self.thread_name:
                self.state.release_proxy_in_use(self.thread_name)
                self.proxy_address = None
            if self.sem_acquired:
                try:
                    self._browser_sem.release()
                    self.sem_acquired = False
                    logging.info("已释放浏览器信号量（无浏览器实例）")
                except Exception as exc:
                    log_suppressed_exception("BrowserSessionService.dispose release semaphore (no driver)", exc, level=logging.WARNING)
            return

        if not self.driver.mark_cleanup_done():
            logging.info("浏览器实例已被其他线程清理，跳过")
            self._unregister_driver(self.driver)
            self._release_owner_lease()
            if self.thread_name:
                self.state.release_proxy_in_use(self.thread_name)
            self.proxy_address = None
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
            logging.info("已关闭浏览器 context/page")
        except Exception as exc:
            log_suppressed_exception("BrowserSessionService.dispose driver.quit", exc, level=logging.WARNING)
        finally:
            self._release_owner_lease()

        if self.thread_name:
            self.state.release_proxy_in_use(self.thread_name)
        self.proxy_address = None

        if self.sem_acquired:
            try:
                self._browser_sem.release()
                self.sem_acquired = False
                logging.info("已释放浏览器信号量")
            except Exception as exc:
                log_suppressed_exception("BrowserSessionService.dispose release semaphore", exc, level=logging.WARNING)

    def shutdown(self) -> None:
        self.dispose()
        if self._browser_owner_pool is not None:
            return
        if self._browser_manager is not None:
            try:
                shutdown_browser_manager(self._browser_manager)
                logging.info("已关闭 BrowserManager 底座")
            except Exception as exc:
                log_suppressed_exception("BrowserSessionService.shutdown manager.close", exc, level=logging.WARNING)
            finally:
                self._browser_manager = None

    @staticmethod
    def _is_stop_requested(stop_signal: Optional[StopSignalLike]) -> bool:
        return bool(stop_signal is not None and stop_signal.is_set())

    def _release_owner_lease(self) -> None:
        lease = self._browser_owner_lease
        self._browser_owner_lease = None
        if lease is None:
            return
        try:
            lease.release()
        except Exception as exc:
            log_suppressed_exception("BrowserSessionService._release_owner_lease", exc, level=logging.WARNING)

    def create_browser(
        self,
        preferred_browsers: list,
        window_x_pos: int,
        window_y_pos: int,
        *,
        stop_signal: Optional[StopSignalLike] = None,
        acquire_browser_semaphore: bool = True,
    ) -> Optional[str]:
        should_wait_for_proxy = bool(self.config.random_proxy_ip_enabled and stop_signal is not None)
        create_attempt = 0
        max_create_attempts = 1 + len(_BROWSER_CREATE_RETRY_DELAYS_SECONDS)

        while True:
            if self._is_stop_requested(stop_signal):
                return None

            if self.config.random_proxy_ip_enabled:
                self._update_phase("获取代理")
            self.proxy_address = _select_proxy_for_session(
                self.state,
                self.thread_name,
                stop_signal=stop_signal,
                wait=should_wait_for_proxy,
            )
            if self.config.random_proxy_ip_enabled and not self.proxy_address:
                if should_wait_for_proxy or self._is_stop_requested(stop_signal):
                    return None
                if _record_bad_proxy_and_maybe_pause(self.state, self.gui_instance):
                    return None

            selected_lease = None
            proxy_map = getattr(self.state, "proxy_in_use_by_thread", None)
            if self.proxy_address and self.thread_name and isinstance(proxy_map, dict):
                selected_lease = proxy_map.get(self.thread_name)
            if (
                self.proxy_address
                and not _lease_skips_generic_connect_check(selected_lease)
                and not _lease_needs_preuse_recheck(selected_lease)
                and not is_http_proxy_connect_responsive(
                    self.proxy_address,
                    target_url=str(getattr(self.config, "url", "") or ""),
                    timeout=1.0,
                    log_failures=False,
                    log_success=False,
                )
            ):
                logging.warning("提取到的代理质量过低，自动弃用更换下一个")
                _discard_unresponsive_proxy(self.state, self.proxy_address)
                if self.thread_name:
                    self.state.release_proxy_in_use(self.thread_name)
                self.proxy_address = None
                if self.config.random_proxy_ip_enabled:
                    if should_wait_for_proxy:
                        continue
                    _record_bad_proxy_and_maybe_pause(self.state, self.gui_instance)
                return None

            browser_proxy_address = self.proxy_address

            ua_value, _ = _select_user_agent_for_session(self.state)
            if acquire_browser_semaphore and not self.sem_acquired:
                self._browser_sem.acquire()
                self.sem_acquired = True
                logging.info("已获取浏览器信号量")

            try:
                if self._browser_owner_pool is not None:
                    self._update_phase("等待浏览器容量")
                    lease = self._browser_owner_pool.acquire_owner_lease(
                        stop_signal=stop_signal,
                        wait=True,
                    )
                    if lease is None:
                        if self.sem_acquired:
                            self._browser_sem.release()
                            self.sem_acquired = False
                            logging.info("等待 owner 容量时任务结束，已释放信号量")
                        if self.thread_name:
                            self.state.release_proxy_in_use(self.thread_name)
                        self.proxy_address = None
                        return None
                    self._browser_owner_lease = lease
                    self._update_phase("创建浏览器会话")
                    self.driver = lease.owner.open_session(
                        proxy_address=browser_proxy_address,
                        user_agent=ua_value,
                        lease=lease,
                    )
                    active_browser = lease.owner.browser_name or "edge"
                else:
                    if self._browser_manager is None:
                        self._browser_manager = create_browser_manager(
                            headless=self.config.headless_mode,
                            prefer_browsers=list(preferred_browsers) if preferred_browsers else None,
                            window_position=(window_x_pos, window_y_pos),
                        )
                    self._update_phase("创建浏览器会话")
                    self.driver, active_browser = create_playwright_driver(
                        headless=self.config.headless_mode,
                        prefer_browsers=list(preferred_browsers) if preferred_browsers else None,
                        proxy_address=browser_proxy_address,
                        user_agent=ua_value,
                        window_position=(window_x_pos, window_y_pos),
                        manager=self._browser_manager,
                        persistent_browser=True,
                    )
            except Exception as exc:
                create_attempt += 1
                if self.sem_acquired:
                    self._browser_sem.release()
                    self.sem_acquired = False
                    logging.info("创建浏览器失败，已释放信号量")
                if self.thread_name:
                    self.state.release_proxy_in_use(self.thread_name)
                failed_proxy = self.proxy_address
                self.proxy_address = None
                self._release_owner_lease()
                if self._browser_manager is not None and self._browser_owner_pool is None:
                    try:
                        shutdown_browser_manager(self._browser_manager)
                    except Exception as shutdown_exc:
                        log_suppressed_exception(
                            "BrowserSessionService.create_browser shutdown broken manager",
                            shutdown_exc,
                            level=logging.WARNING,
                        )
                    finally:
                        self._browser_manager = None

                if self.config.random_proxy_ip_enabled and failed_proxy:
                    if _looks_like_proxy_launch_error(exc) or _looks_like_transient_browser_create_error(exc):
                        logging.warning(
                            "随机IP建立浏览器会话失败，已废弃当前代理并继续尝试下一只：%s",
                            _exception_summary(exc),
                        )
                        _discard_unresponsive_proxy(self.state, failed_proxy)
                        if should_wait_for_proxy:
                            continue
                        if create_attempt < max_create_attempts:
                            continue

                if (
                    not self.config.random_proxy_ip_enabled
                    and create_attempt < max_create_attempts
                    and _looks_like_transient_browser_create_error(exc)
                ):
                    wait_seconds = _BROWSER_CREATE_RETRY_DELAYS_SECONDS[create_attempt - 1]
                    logging.warning(
                        "浏览器会话创建命中瞬时异常，%.2f 秒后重试：%s",
                        wait_seconds,
                        _exception_summary(exc),
                    )
                    if stop_signal is not None:
                        if stop_signal.wait(wait_seconds):
                            return None
                    else:
                        time.sleep(wait_seconds)
                    continue
                raise

            driver = self.driver
            if driver is None:
                raise RuntimeError("浏览器创建完成后 driver 为空")
            self._register_driver(driver)
            setattr(driver, "_thread_name", self.thread_name)
            setattr(driver, "_session_state", self.state)
            setattr(driver, "_session_proxy_address", self.proxy_address)
            runtime_window_size = _resolve_runtime_window_size(self.config)
            if runtime_window_size is not None:
                width, height = runtime_window_size
                driver.set_window_size(width, height)
            return active_browser


__all__ = ["BrowserSessionService"]
