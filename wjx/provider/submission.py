"""问卷星提交流程公共出口。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from software.app.config import (
    HEADLESS_SUBMIT_CLICK_SETTLE_DELAY,
    HEADLESS_SUBMIT_INITIAL_DELAY,
    SUBMIT_CLICK_SETTLE_DELAY,
    SUBMIT_INITIAL_DELAY,
)
from software.core.engine.runtime_control import _is_headless_mode, _sleep_with_stop
from software.core.task import ExecutionState
from software.network.browser import NoSuchElementException
from software.network.browser.runtime_async import BrowserDriver

from .runtime_interactions import _click_submit_button
from .runtime_state import peek_wjx_runtime_state
from .submission_pages import (
    _is_device_quota_limit_page,
    _is_wjx_domain,
    _looks_like_wjx_survey_url,
    _normalize_url_for_compare,
    _page_looks_like_wjx_questionnaire,
)
from .submission_recovery import (
    SubmissionRecoveryHint,
)
from .submission_verification import (
    _ALIYUN_CAPTCHA_DOM_IDS,
    _aliyun_captcha_element_exists,
    _aliyun_captcha_visible_with_js,
    submission_validation_message,
)
from . import submission_recovery as _submission_recovery
from . import submission_verification as _submission_verification
from .runtime_state import get_wjx_runtime_state


class AliyunCaptchaBypassError(RuntimeError):
    """检测到问卷星阿里云智能验证（需要人工交互）时抛出。"""


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
        ("xpath", '//*[@id="layui-layer1"]/div[3]/a'),
        ("css selector", "#layui-layer1 .layui-layer-btn a"),
        ("css selector", ".layui-layer .layui-layer-btn a.layui-layer-btn0"),
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


async def is_device_quota_limit_page(driver: BrowserDriver) -> bool:
    return bool(await _is_device_quota_limit_page(driver))


async def submission_requires_verification(driver: BrowserDriver) -> bool:
    return bool(await _aliyun_captcha_visible_with_js(driver) or await _aliyun_captcha_element_exists(driver))


async def wait_for_submission_verification(
    driver: BrowserDriver,
    *,
    timeout: int = 3,
    stop_signal: Any = None,
) -> bool:
    deadline = __import__("time").time() + max(1, int(timeout or 1))
    while __import__("time").time() < deadline:
        if stop_signal is not None and getattr(stop_signal, "is_set", lambda: False)():
            return False
        if await submission_requires_verification(driver):
            return True
        await asyncio.sleep(0.15)
    return bool(await submission_requires_verification(driver))


def _trigger_aliyun_captcha_stop(
    ctx: ExecutionState,
    stop_signal: Optional[Any],
):
    return _submission_verification._trigger_aliyun_captcha_stop(ctx, stop_signal)


async def handle_submission_verification_detected(
    ctx: ExecutionState,
    stop_signal: Optional[Any],
):
    config = getattr(ctx, "config", None)
    random_proxy_ip_enabled = bool(
        getattr(ctx, "random_proxy_ip_enabled", getattr(config, "random_proxy_ip_enabled", False))
    )
    pause_on_aliyun_captcha = bool(
        getattr(ctx, "pause_on_aliyun_captcha", getattr(config, "pause_on_aliyun_captcha", True))
    )

    if random_proxy_ip_enabled:
        logging.warning("随机IP模式命中问卷星阿里云智能验证：仅记录日志，不暂停。")
        return _submission_verification.RuntimeActionResult.empty()
    if not pause_on_aliyun_captcha:
        logging.warning("检测到问卷星阿里云智能验证：pause_on_aliyun_captcha=False，仅记录告警。")
        return _submission_verification.RuntimeActionResult.empty()
    return _trigger_aliyun_captcha_stop(ctx, stop_signal)


async def _extract_missing_answer_hint(driver: BrowserDriver):
    return await _submission_recovery._extract_missing_answer_hint(driver)


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
    "SubmissionRecoveryHint",
    "_ALIYUN_CAPTCHA_DOM_IDS",
    "_aliyun_captcha_element_exists",
    "_aliyun_captcha_visible_with_js",
    "_extract_missing_answer_hint",
    "get_wjx_runtime_state",
    "_is_wjx_domain",
    "_looks_like_wjx_survey_url",
    "_normalize_url_for_compare",
    "_page_looks_like_wjx_questionnaire",
    "_trigger_aliyun_captcha_stop",
    "attempt_submission_recovery",
    "handle_submission_verification_detected",
    "is_device_quota_limit_page",
    "submission_requires_verification",
    "submission_validation_message",
    "submit",
    "wait_for_submission_verification",
]
