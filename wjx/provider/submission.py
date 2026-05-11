"""问卷星提交流程能力。"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from software.app.config import (
    HEADLESS_SUBMIT_CLICK_SETTLE_DELAY,
    HEADLESS_SUBMIT_INITIAL_DELAY,
    SUBMIT_CLICK_SETTLE_DELAY,
    SUBMIT_INITIAL_DELAY,
)
from software.core.engine.runtime_control import _is_headless_mode, _sleep_with_stop
from software.core.task import ExecutionState
from software.logging.log_utils import log_popup_confirm, log_popup_warning
from software.network.browser import By, NoSuchElementException
from software.network.browser.runtime_async import BrowserDriver

from .runtime_interactions import _click_submit_button
from .runtime_state import get_wjx_runtime_state, peek_wjx_runtime_state
from .submission_pages import (
    _is_device_quota_limit_page,
    _is_wjx_domain,
    _looks_like_wjx_survey_url,
    _normalize_url_for_compare,
    _page_looks_like_wjx_questionnaire,
)

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
_WJX_MISSING_ANSWER_MARKERS = (
    "此题未作答",
    "本题未作答",
    "请选择",
    "请填写",
    "必答题",
)


class AliyunCaptchaBypassError(RuntimeError):
    """检测到问卷星阿里云智能验证（需要人工交互）时抛出。"""


@dataclass(frozen=True)
class SubmissionRecoveryHint:
    question_numbers: tuple[int, ...]
    message: str


def _runtime_context_summary(driver: BrowserDriver) -> str:
    state = peek_wjx_runtime_state(driver)
    if state is None:
        return ""
    page_number = max(0, int(getattr(state, "page_number", 0) or 0))
    question_numbers: list[int] = []
    for item in list(getattr(state, "page_questions", []) or []):
        if not isinstance(item, dict):
            continue
        try:
            question_num = int(item.get("question_num") or 0)
        except Exception:
            question_num = 0
        if question_num > 0:
            question_numbers.append(question_num)
    parts: list[str] = []
    if page_number > 0:
        parts.append(f"page={page_number}")
    if question_numbers:
        parts.append(f"questions={question_numbers}")
    return " ".join(parts)


async def _click_submit_confirm_button(driver: BrowserDriver, settle_delay: float = 0.0) -> None:
    confirm_candidates = [
        (By.XPATH, '//*[@id="layui-layer1"]/div[3]/a'),
        (By.CSS_SELECTOR, "#layui-layer1 .layui-layer-btn a"),
        (By.CSS_SELECTOR, ".layui-layer .layui-layer-btn a.layui-layer-btn0"),
    ]
    for by, value in confirm_candidates:
        try:
            element = await driver.find_element(by, value)
        except Exception:
            element = None
        if not element:
            continue
        try:
            if not await element.is_displayed():
                continue
        except Exception:
            continue
        try:
            await element.click()
            if settle_delay > 0:
                await asyncio.sleep(settle_delay)
            return
        except Exception:
            continue


async def submit(
    driver: BrowserDriver,
    ctx: Optional[ExecutionState] = None,
    stop_signal: Optional[Any] = None,
) -> None:
    headless_mode = _is_headless_mode(ctx)
    settle_delay = float(HEADLESS_SUBMIT_CLICK_SETTLE_DELAY if headless_mode else SUBMIT_CLICK_SETTLE_DELAY)
    pre_submit_delay = float(HEADLESS_SUBMIT_INITIAL_DELAY if headless_mode else SUBMIT_INITIAL_DELAY)

    if pre_submit_delay > 0 and await _sleep_with_stop(stop_signal, pre_submit_delay):
        return
    if stop_signal is not None and getattr(stop_signal, "is_set", lambda: False)():
        return

    clicked = await _click_submit_button(driver, timeout_ms=10000)
    if not clicked:
        runtime_context = _runtime_context_summary(driver)
        if runtime_context:
            logging.warning("问卷星提交按钮未找到：%s", runtime_context)
        raise NoSuchElementException("Submit button not found")
    if settle_delay > 0:
        await asyncio.sleep(settle_delay)
    await _click_submit_confirm_button(driver, settle_delay=settle_delay)


async def submission_validation_message(driver: Optional[BrowserDriver] = None) -> str:
    if driver is not None:
        _runtime_context_summary(driver)
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


async def _extract_missing_answer_hint(driver: BrowserDriver) -> Optional[SubmissionRecoveryHint]:
    script = r"""
        return (() => {
            const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };
            const normalize = (text) => String(text || '').replace(/\s+/g, ' ').trim();
            const markers = ['此题未作答', '本题未作答', '请选择', '请填写', '必答题'];
            const selectors = [
                '.error',
                '.field-error',
                '.data__error',
                '.ui-input-error',
                '.wjx-error',
                '.req-tip',
                '.validate-error',
                '.layui-layer-content',
            ];
            const messages = [];
            const questionNumbers = [];

            const pushQuestionNumber = (node) => {
                if (!node) return;
                const root = node.closest('#divQuestion [topic], #divQuestion div[id^="div"]');
                if (!root) return;
                const rawTopic = String(root.getAttribute('topic') || '').trim();
                const idMatch = String(root.getAttribute('id') || '').trim().match(/^div(\d+)$/);
                const value = rawTopic && /^\d+$/.test(rawTopic)
                    ? Number.parseInt(rawTopic, 10)
                    : (idMatch ? Number.parseInt(idMatch[1], 10) : 0);
                if (value > 0 && !questionNumbers.includes(value)) {
                    questionNumbers.push(value);
                }
            };

            for (const sel of selectors) {
                for (const node of document.querySelectorAll(sel)) {
                    if (!visible(node)) continue;
                    const text = normalize(node.innerText || node.textContent || '');
                    if (!text) continue;
                    if (!markers.some((marker) => text.includes(marker))) continue;
                    messages.push(text);
                    pushQuestionNumber(node);
                }
            }

            for (const marker of markers) {
                const bodyText = normalize(document.body?.innerText || '');
                if (bodyText.includes(marker) && !messages.some((item) => item.includes(marker))) {
                    messages.push(marker);
                }
            }

            return {
                questionNumbers,
                messages: Array.from(new Set(messages)).slice(0, 5),
            };
        })();
    """
    try:
        payload = await driver.execute_script(script) or {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return None

    question_numbers: list[int] = []
    for raw_num in list(payload.get("questionNumbers") or []):
        try:
            question_num = int(raw_num)
        except Exception:
            continue
        if question_num > 0 and question_num not in question_numbers:
            question_numbers.append(question_num)

    messages: list[str] = []
    for raw_message in list(payload.get("messages") or []):
        text = str(raw_message or "").strip()
        if not text:
            continue
        if not any(marker in text for marker in _WJX_MISSING_ANSWER_MARKERS):
            continue
        if text not in messages:
            messages.append(text)

    if not question_numbers and not messages:
        return None
    message = " | ".join(messages[:3]).strip() or "提交后检测到未作答提示"
    return SubmissionRecoveryHint(tuple(question_numbers), message)


def _trigger_aliyun_captcha_stop(
    ctx: ExecutionState,
    gui_instance: Optional[Any],
    stop_signal: Optional[threading.Event],
) -> None:
    with ctx._aliyun_captcha_stop_lock:
        if ctx._aliyun_captcha_stop_triggered:
            return
        ctx._aliyun_captcha_stop_triggered = True

    logging.warning("检测到问卷星阿里云智能验证，已触发全局暂停。")

    if stop_signal and not stop_signal.is_set():
        stop_signal.set()
        logging.warning("智能验证命中：已设置 stop_signal，任务将立即停止")

    try:
        if gui_instance:
            gui_instance.pause_run("触发智能验证")
            logging.warning("智能验证命中：已调用 pause_run")
    except Exception:
        logging.info("阿里云智能验证触发暂停失败", exc_info=True)

    def _notify() -> None:
        try:
            if threading.current_thread() is not threading.main_thread():
                return

            from software.network.proxy.policy.source import get_random_ip_counter_snapshot_local
            from software.network.proxy.session import has_authenticated_session, is_quota_exhausted

            is_enabled = bool(gui_instance.is_random_ip_enabled()) if gui_instance else False

            if is_enabled:
                message = (
                    "检测到问卷星阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                    "请尝试重新启动任务。"
                )
                if gui_instance:
                    gui_instance.show_message_dialog("智能验证提示", message, level="warning")
                else:
                    log_popup_warning("智能验证提示", message)
                return

            used, total, custom_api = get_random_ip_counter_snapshot_local()
            if custom_api:
                message = (
                    "检测到问卷星阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                    "你当前使用的是自定义代理接口，请自行排查解决后重新启动任务。"
                )
                if gui_instance:
                    gui_instance.show_message_dialog("智能验证提示", message, level="warning")
                else:
                    log_popup_warning("智能验证提示", message)
                return

            if not has_authenticated_session():
                message = (
                    "检测到问卷星阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                    "默认随机 IP 现已需要先领取免费试用或提交额度申请。\n"
                    "请先完成试用激活或额度申请，或切换自定义代理接口后再试。"
                )
                if gui_instance:
                    gui_instance.show_message_dialog("智能验证提示", message, level="warning")
                else:
                    log_popup_warning("智能验证提示", message)
                return

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
                if gui_instance:
                    gui_instance.show_message_dialog("智能验证提示", message, level="warning")
                else:
                    log_popup_warning("智能验证提示", message)
                return

            message = (
                "检测到问卷星阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                "启用随机 IP 能解决这个问题。\n"
                "是否立即启用随机 IP 功能？"
            )
            if gui_instance:
                confirmed = bool(gui_instance.show_confirm_dialog("智能验证提示", message))
            else:
                confirmed = bool(log_popup_confirm("智能验证提示", message))

            if confirmed and gui_instance:
                try:
                    gui_instance.set_random_ip_enabled(True)
                    refresh_counter = getattr(gui_instance, "refresh_random_ip_counter", None)
                    if callable(refresh_counter):
                        refresh_counter()
                    logging.info("智能验证触发：用户已确认启用随机IP")
                except Exception:
                    logging.warning("自动启用随机IP失败", exc_info=True)
        except Exception:
            logging.warning("弹窗提示用户启用随机IP失败", exc_info=True)

    if gui_instance:
        try:
            gui_instance.dispatch_to_ui_async(_notify)
            return
        except Exception:
            logging.info("派发阿里云停止事件到主线程失败", exc_info=True)
    _notify()


async def handle_submission_verification_detected(
    ctx: ExecutionState,
    gui_instance: Optional[Any],
    stop_signal: Optional[Any],
) -> None:
    config = getattr(ctx, "config", None)
    random_proxy_ip_enabled = bool(
        getattr(ctx, "random_proxy_ip_enabled", getattr(config, "random_proxy_ip_enabled", False))
    )
    pause_on_aliyun_captcha = bool(
        getattr(ctx, "pause_on_aliyun_captcha", getattr(config, "pause_on_aliyun_captcha", True))
    )

    if random_proxy_ip_enabled:
        logging.warning("随机IP模式命中问卷星阿里云智能验证：仅记录日志，不暂停。")
        return
    if not pause_on_aliyun_captcha:
        logging.warning("检测到问卷星阿里云智能验证：pause_on_aliyun_captcha=False，仅记录告警。")
        return
    _trigger_aliyun_captcha_stop(ctx, gui_instance, stop_signal)


async def is_device_quota_limit_page(driver: BrowserDriver) -> bool:
    return bool(await _is_device_quota_limit_page(driver))


async def attempt_submission_recovery(
    driver: BrowserDriver,
    ctx: ExecutionState,
    gui_instance: Optional[Any],
    stop_signal: Optional[Any],
    *,
    thread_name: str = "",
) -> bool:
    del gui_instance
    if stop_signal is not None and getattr(stop_signal, "is_set", lambda: False)():
        return False
    if await submission_requires_verification(driver):
        return False
    if not await _page_looks_like_wjx_questionnaire(driver):
        return False

    runtime_state = get_wjx_runtime_state(driver)
    recovery_attempts = int(runtime_state.submission_recovery_attempts or 0)
    if recovery_attempts >= 1:
        return False

    hint = await _extract_missing_answer_hint(driver)
    if hint is None:
        return False

    runtime_page_questions = list(runtime_state.page_questions or [])
    current_page_required: list[int] = []
    for item in runtime_page_questions:
        if not isinstance(item, dict):
            continue
        try:
            question_num = int(item.get("question_num") or 0)
        except Exception:
            question_num = 0
        if question_num > 0 and bool(item.get("required")) and question_num not in current_page_required:
            current_page_required.append(question_num)

    target_questions: list[int] = []
    for question_num in hint.question_numbers:
        if question_num > 0 and question_num not in target_questions:
            target_questions.append(question_num)
    if not target_questions:
        target_questions = list(current_page_required)
    if not target_questions:
        logging.warning("WJX 提交补救放弃：识别到未作答提示，但当前页没有可补题目。message=%s", hint.message)
        return False

    logging.warning("WJX 提交命中未作答提示，准备补答并重提：questions=%s message=%s", target_questions, hint.message)
    try:
        ctx.update_thread_status(thread_name or "Worker-?", "补答必答题", running=True)
    except Exception:
        logging.info("更新线程状态失败：补答必答题", exc_info=True)

    from wjx.provider.runtime import refill_required_questions_on_current_page

    filled_count = await refill_required_questions_on_current_page(
        driver,
        ctx,
        question_numbers=target_questions,
        thread_name=thread_name or "Worker-?",
        psycho_plan=runtime_state.psycho_plan,
    )
    if filled_count <= 0:
        logging.warning("WJX 提交补救失败：未成功补答任何题目。questions=%s", target_questions)
        return False

    runtime_state.submission_recovery_attempts = recovery_attempts + 1
    await submit(driver, ctx=ctx, stop_signal=stop_signal)
    return True


__all__ = [
    "AliyunCaptchaBypassError",
    "_ALIYUN_CAPTCHA_DOM_IDS",
    "_is_wjx_domain",
    "_looks_like_wjx_survey_url",
    "_normalize_url_for_compare",
    "_page_looks_like_wjx_questionnaire",
    "attempt_submission_recovery",
    "handle_submission_verification_detected",
    "is_device_quota_limit_page",
    "submission_requires_verification",
    "submission_validation_message",
    "submit",
    "wait_for_submission_verification",
]
