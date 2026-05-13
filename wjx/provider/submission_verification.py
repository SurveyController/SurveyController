"""问卷星提交后智能验证检测与动作生成。"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Optional

from software.core.engine.runtime_actions import (
    RuntimeActionKind,
    RuntimeActionRequest,
    RuntimeActionResult,
)
from software.core.task import ExecutionState
from software.network.browser import By
from software.network.browser.runtime_async import BrowserDriver

_ALIYUN_CAPTCHA_MESSAGE = "检测到问卷星阿里云智能验证，当前版本暂不支持自动处理，请更换或启用随机 IP 后重试。"
_ALIYUN_CAPTCHA_DOM_IDS = (
    "aliyunCaptcha-window-popup",
    "aliyunCaptcha-title",
    "aliyunCaptcha-checkbox",
    "aliyunCaptcha-checkbox-wrapper",
    "aliyunCaptcha-checkbox-body",
    "aliyunCaptcha-checkbox-icon",
    "aliyunCaptcha-checkbox-left",
    "aliyunCaptcha-checkbox-text",
    "aliyunCaptcha-loading",
    "aliyunCaptcha-certifyId",
)
_ALIYUN_CAPTCHA_LOCATORS = (
    (By.ID, "aliyunCaptcha-window-popup"),
    (By.ID, "aliyunCaptcha-checkbox-icon"),
    (By.ID, "aliyunCaptcha-checkbox-left"),
    (By.ID, "aliyunCaptcha-checkbox-text"),
)


async def submission_validation_message(driver: Optional[BrowserDriver] = None) -> str:
    del driver
    return _ALIYUN_CAPTCHA_MESSAGE


async def _aliyun_captcha_visible_with_js(driver: BrowserDriver) -> bool:
    script = r"""
        return (() => {
            const ids = [
                'aliyunCaptcha-window-popup',
                'aliyunCaptcha-title',
                'aliyunCaptcha-checkbox',
                'aliyunCaptcha-checkbox-wrapper',
                'aliyunCaptcha-checkbox-body',
                'aliyunCaptcha-checkbox-icon',
                'aliyunCaptcha-checkbox-left',
                'aliyunCaptcha-checkbox-text',
                'aliyunCaptcha-loading',
                'aliyunCaptcha-certifyId',
            ];

            const visible = (el, win) => {
                if (!el || !win) return false;
                const style = win.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };

            const checkDoc = (doc) => {
                if (!doc) return false;
                const win = doc.defaultView;
                if (!win) return false;
                for (const id of ids) {
                    const el = doc.getElementById(id);
                    if (visible(el, win)) return true;
                }
                return false;
            };

            if (checkDoc(document)) return true;
            const frames = Array.from(document.querySelectorAll('iframe'));
            for (const frame of frames) {
                try {
                    const doc = frame.contentDocument || frame.contentWindow?.document;
                    if (checkDoc(doc)) return true;
                } catch (e) {}
            }
            return false;
        })();
    """
    try:
        return bool(await driver.execute_script(script))
    except Exception:
        return False


async def _aliyun_captcha_element_exists(driver: BrowserDriver) -> bool:
    for locator in _ALIYUN_CAPTCHA_LOCATORS:
        try:
            element = await driver.find_element(*locator)
        except Exception:
            element = None
        if not element:
            continue
        try:
            if await element.is_displayed():
                return True
        except Exception:
            continue
    return False


async def submission_requires_verification(driver: BrowserDriver) -> bool:
    return bool(await _aliyun_captcha_visible_with_js(driver) or await _aliyun_captcha_element_exists(driver))


async def wait_for_submission_verification(
    driver: BrowserDriver,
    *,
    timeout: int = 3,
    stop_signal: Any = None,
) -> bool:
    deadline = time.time() + max(1, int(timeout or 1))
    while time.time() < deadline:
        if stop_signal is not None and getattr(stop_signal, "is_set", lambda: False)():
            return False
        if await submission_requires_verification(driver):
            return True
        await asyncio.sleep(0.15)
    return bool(await submission_requires_verification(driver))


def _trigger_aliyun_captcha_stop(
    ctx: ExecutionState,
    stop_signal: Optional[threading.Event],
) -> RuntimeActionResult:
    with ctx._aliyun_captcha_stop_lock:
        if ctx._aliyun_captcha_stop_triggered:
            return RuntimeActionResult.empty()
        ctx._aliyun_captcha_stop_triggered = True

    logging.warning("检测到问卷星阿里云智能验证，已触发全局暂停。")

    if stop_signal and not stop_signal.is_set():
        stop_signal.set()
        logging.warning("智能验证命中：已设置 stop_signal，任务将立即停止")

    actions: list[RuntimeActionRequest] = [
        RuntimeActionRequest(
            RuntimeActionKind.PAUSE_RUN,
            reason="触发智能验证",
        )
    ]
    try:
        from software.network.proxy.policy.source import get_random_ip_counter_snapshot_local
        from software.network.proxy.session import has_authenticated_session, is_quota_exhausted

        random_proxy_ip_enabled = bool(getattr(getattr(ctx, "config", None), "random_proxy_ip_enabled", False))
        if random_proxy_ip_enabled:
            message = (
                "检测到问卷星阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                "请尝试重新启动任务。"
            )
            actions.append(RuntimeActionRequest(RuntimeActionKind.SHOW_MESSAGE, "智能验证提示", message, "warning"))
            return RuntimeActionResult.from_actions(actions, should_stop=True)

        used, total, custom_api = get_random_ip_counter_snapshot_local()
        if custom_api:
            message = (
                "检测到问卷星阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                "你当前使用的是自定义代理接口，请自行排查解决后重新启动任务。"
            )
            actions.append(RuntimeActionRequest(RuntimeActionKind.SHOW_MESSAGE, "智能验证提示", message, "warning"))
            return RuntimeActionResult.from_actions(actions, should_stop=True)

        if not has_authenticated_session():
            message = (
                "检测到问卷星阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                "默认随机 IP 现已需要先领取免费试用或提交额度申请。\n"
                "请先完成试用激活或额度申请，或切换自定义代理接口后再试。"
            )
            actions.append(RuntimeActionRequest(RuntimeActionKind.SHOW_MESSAGE, "智能验证提示", message, "warning"))
            return RuntimeActionResult.from_actions(actions, should_stop=True)

        quota_exceeded = is_quota_exhausted(
            {
                "authenticated": True,
                "used_quota": float(used or 0.0),
                "total_quota": float(total or 0.0),
            }
        )
        if quota_exceeded:
            message = (
                "检测到问卷星阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                "启用随机 IP 可以解决该问题，但当前使用额度达到上限。\n"
                "请先补充额度后再启用随机 IP。"
            )
            actions.append(RuntimeActionRequest(RuntimeActionKind.SHOW_MESSAGE, "智能验证提示", message, "warning"))
            return RuntimeActionResult.from_actions(actions, should_stop=True)

        message = (
            "检测到问卷星阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
            "启用随机 IP 能解决这个问题。\n"
            "是否立即启用随机 IP 功能？"
        )
        actions.append(RuntimeActionRequest(RuntimeActionKind.CONFIRM_ENABLE_RANDOM_IP, "智能验证提示", message, "warning"))
    except Exception:
        logging.warning("生成阿里云智能验证运行事件失败", exc_info=True)
    return RuntimeActionResult.from_actions(actions, should_stop=True)


async def handle_submission_verification_detected(
    ctx: ExecutionState,
    stop_signal: Optional[Any],
) -> RuntimeActionResult:
    config = getattr(ctx, "config", None)
    random_proxy_ip_enabled = bool(
        getattr(ctx, "random_proxy_ip_enabled", getattr(config, "random_proxy_ip_enabled", False))
    )
    pause_on_aliyun_captcha = bool(
        getattr(ctx, "pause_on_aliyun_captcha", getattr(config, "pause_on_aliyun_captcha", True))
    )

    if random_proxy_ip_enabled:
        logging.warning("随机IP模式命中问卷星阿里云智能验证：仅记录日志，不暂停。")
        return RuntimeActionResult.empty()
    if not pause_on_aliyun_captcha:
        logging.warning("检测到问卷星阿里云智能验证：pause_on_aliyun_captcha=False，仅记录告警。")
        return RuntimeActionResult.empty()
    return _trigger_aliyun_captcha_stop(ctx, stop_signal)


__all__ = [
    "_ALIYUN_CAPTCHA_DOM_IDS",
    "_aliyun_captcha_element_exists",
    "_aliyun_captcha_visible_with_js",
    "_trigger_aliyun_captcha_stop",
    "handle_submission_verification_detected",
    "submission_requires_verification",
    "submission_validation_message",
    "wait_for_submission_verification",
]
