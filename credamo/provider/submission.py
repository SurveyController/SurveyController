"""Credamo 见数提交结果与验证识别。"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

from software.core.engine.async_wait import sleep_or_stop
from software.core.engine.runtime_actions import RuntimeActionResult
from software.core.task import ExecutionState
from software.network.browser.runtime_async import BrowserDriver
from credamo.provider.runtime_dom import _page, _question_number_from_root, _question_roots, _unanswered_question_roots
from credamo.provider.runtime_state import get_credamo_runtime_state, peek_credamo_runtime_state

_COMPLETION_MARKERS = (
    "答卷已经提交",
    "已提交",
    "提交成功",
    "作答完成",
    "问卷已完成",
    "已完成本次问卷",
    "已完成本次答卷",
    "感谢您的宝贵时间",
    "感谢参与",
    "感谢作答",
    "感谢您的参与",
    "thank",
    "success",
)
_VERIFICATION_MARKERS = (
    "验证码",
    "安全验证",
    "滑块验证",
    "captcha",
    "请完成验证",
    "请先完成验证",
)
_VISIBLE_FEEDBACK_SELECTORS = (
    ".el-message",
    ".el-message__content",
    ".el-message-box",
    ".el-message-box__message",
    ".el-form-item__error",
    ".el-notification",
    ".el-notification__content",
    "[role='alert']",
    ".ant-message",
    ".ant-message-notice-content",
    ".ant-notification-notice-message",
    ".ant-notification-notice-description",
    ".toast",
    ".toast-message",
    ".van-toast",
    ".ivu-message-notice-content",
)
_SELECTION_VALIDATION_PATTERNS = (
    re.compile(r"(?:请|需)?(?:至少|最少|不少于)\s*(?:选择|选)\s*\d+\s*(?:个)?(?:选项|答案|项)"),
    re.compile(r"(?:请|需)?(?:至多|最多|不超过)\s*(?:选择|选)\s*\d+\s*(?:个)?(?:选项|答案|项)"),
    re.compile(r"(?:请|需)?(?:选择|选)\s*\d+\s*(?:[-~～至到]\s*\d+)\s*(?:个)?(?:选项|答案|项)"),
    re.compile(r"(?:还需|还要|还差)\s*(?:选择|选)\s*\d+\s*(?:个)?(?:选项|答案|项)"),
)
_COMPLETION_URL_MARKERS = ("complete", "success", "finish", "done", "submitted", "result")
_ACTION_SELECTORS = (
    "#credamo-submit-btn",
    ".page-control button",
    ".btn-next",
    ".btn-submit",
    "button[type='submit']",
    "input[type='submit']",
    "input[type='button']",
    "[role='button']",
)


@dataclass(frozen=True)
class SubmissionRecoveryHint:
    question_numbers: tuple[int, ...]
    message: str


def _runtime_context_summary(driver: BrowserDriver) -> str:
    state = peek_credamo_runtime_state(driver)
    if state is None:
        return ""
    page_index = max(0, int(getattr(state, "page_index", 0) or 0))
    answered_keys = [str(item or "").strip() for item in list(getattr(state, "answered_question_keys", []) or []) if str(item or "").strip()]
    parts: list[str] = []
    if page_index > 0:
        parts.append(f"page={page_index}")
    if answered_keys:
        parts.append(f"answered={len(answered_keys)}")
    return " ".join(parts)


async def _body_text(driver: BrowserDriver) -> str:
    try:
        return str(await driver.execute_script("return document.body ? document.body.innerText || '' : ''; ") or "")
    except Exception:
        return ""


async def _visible_feedback_text(driver: BrowserDriver) -> str:
    selector = ",".join(_VISIBLE_FEEDBACK_SELECTORS)
    script = f"""
return (() => {{
    const visible = (el) => {{
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (!style) return false;
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }};
    const texts = [];
    for (const el of document.querySelectorAll({selector!r})) {{
        if (!visible(el)) continue;
        const text = String(el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
        if (text) texts.push(text);
    }}
    return texts.join('\\n');
}})();
"""
    try:
        return str(await driver.execute_script(script) or "")
    except Exception:
        return ""


async def _extract_submission_recovery_hint(driver: BrowserDriver) -> Optional[SubmissionRecoveryHint]:
    script = f"""
return (() => {{
    const visible = (el) => {{
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (!style) return false;
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }};
    const normalize = (text) => String(text || '').replace(/\\s+/g, ' ').trim();
    const selectors = {list(_VISIBLE_FEEDBACK_SELECTORS)!r};
    const messages = [];
    const questionNumbers = [];

    const pushQuestionNumber = (node) => {{
        const root = node?.closest?.('.answer-page .question');
        if (!root) return;
        const titleNode = root.querySelector('.question-title, .qstTitle, .title, [class*="title"]');
        const rawTitle = normalize(titleNode?.innerText || titleNode?.textContent || root.innerText || '');
        const match = rawTitle.match(/(?:^|\\D)(\\d{{1,4}})(?:[\\.、\\s]|$)/);
        if (!match) return;
        const value = Number.parseInt(match[1], 10);
        if (value > 0 && !questionNumbers.includes(value)) {{
            questionNumbers.push(value);
        }}
    }};

    for (const sel of selectors) {{
        for (const node of document.querySelectorAll(sel)) {{
            if (!visible(node)) continue;
            const text = normalize(node.innerText || node.textContent || '');
            if (!text) continue;
            messages.push(text);
            pushQuestionNumber(node);
        }}
    }}

    return {{
        questionNumbers,
        messages: Array.from(new Set(messages)).slice(0, 6),
    }};
}})();
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
        if _looks_like_selection_validation(text) or "必填" in text or "请选择" in text or "请填写" in text:
            if text not in messages:
                messages.append(text)

    page = await _page(driver)
    runtime_state = peek_credamo_runtime_state(driver)
    if page is not None:
        answered_keys = set(getattr(runtime_state, "answered_question_keys", []) or [])
        try:
            roots = await _question_roots(page)
        except Exception:
            roots = []
        pending = await _unanswered_question_roots(page, roots, answered_keys) if roots else []
        for root, fallback_num, _question_key in pending:
            question_num = await _question_number_from_root(page, root, fallback_num)
            if question_num > 0 and question_num not in question_numbers:
                question_numbers.append(question_num)
        if pending and not messages:
            messages.append("当前页存在未作答题目")

    if not question_numbers and not messages:
        return None
    message = " | ".join(messages[:3]).strip() or "提交后检测到未作答提示"
    return SubmissionRecoveryHint(tuple(question_numbers), message)


def _looks_like_selection_validation(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _SELECTION_VALIDATION_PATTERNS)


def _contains_completion_marker(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(marker.lower() in normalized for marker in _COMPLETION_MARKERS)


def _contains_verification_marker(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(marker.lower() in normalized for marker in _VERIFICATION_MARKERS)


async def _has_visible_action_controls(driver: BrowserDriver) -> bool:
    selector = ",".join(_ACTION_SELECTORS)
    script = f"""
return (() => {{
    const visible = (el) => {{
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (!style) return false;
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }};
    return Array.from(document.querySelectorAll({selector!r})).some(visible);
}})();
"""
    try:
        return bool(await driver.execute_script(script))
    except Exception:
        return False


async def is_completion_page(driver: BrowserDriver) -> bool:
    try:
        url = str(await driver.current_url() or "").lower()
    except Exception:
        url = ""
    if any(marker in url for marker in _COMPLETION_URL_MARKERS):
        return True
    feedback_text = await _visible_feedback_text(driver)
    if _contains_completion_marker(feedback_text):
        return True
    text = await _body_text(driver)
    if not _contains_completion_marker(text):
        return False
    return not await _has_visible_action_controls(driver)


async def submission_requires_verification(driver: BrowserDriver) -> bool:
    feedback_text = await _visible_feedback_text(driver)
    if _contains_completion_marker(feedback_text):
        return False
    if _looks_like_selection_validation(feedback_text):
        return False
    if feedback_text and _contains_verification_marker(feedback_text):
        runtime_context = _runtime_context_summary(driver)
        if runtime_context:
            logging.info("Credamo 提交命中验证提示：%s", runtime_context)
        return True
    text = await _body_text(driver)
    if _contains_completion_marker(text):
        return False
    matched = _contains_verification_marker(text)
    if matched:
        runtime_context = _runtime_context_summary(driver)
        if runtime_context:
            logging.info("Credamo 页面正文命中验证提示：%s", runtime_context)
    return matched


async def submission_validation_message(driver: Optional[BrowserDriver] = None) -> str:
    if driver is not None:
        _runtime_context_summary(driver)
    return "Credamo 见数提交命中验证码/安全验证，当前版本暂不支持自动处理"


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
        await sleep_or_stop(stop_signal, 0.15)
    return await submission_requires_verification(driver)


async def handle_submission_verification_detected(ctx: Any, stop_signal: Any) -> RuntimeActionResult:
    del ctx, stop_signal
    return RuntimeActionResult.empty()


async def consume_submission_success_signal(driver: BrowserDriver) -> bool:
    _runtime_context_summary(driver)
    return await is_completion_page(driver)


async def is_device_quota_limit_page(driver: BrowserDriver) -> bool:
    text = await _body_text(driver)
    return "已达上限" in text or "次数已满" in text or "名额已满" in text


async def attempt_submission_recovery(
    driver: BrowserDriver,
    ctx: ExecutionState,
    gui_instance: Any,
    stop_signal: Any,
    *,
    thread_name: str = "",
) -> bool:
    del gui_instance
    if stop_signal is not None and getattr(stop_signal, "is_set", lambda: False)():
        return False
    if await submission_requires_verification(driver):
        return False

    runtime_state = get_credamo_runtime_state(driver)
    recovery_attempts = int(runtime_state.submission_recovery_attempts or 0)
    if recovery_attempts >= 1:
        return False

    hint = await _extract_submission_recovery_hint(driver)
    if hint is None:
        return False

    target_questions: list[int] = []
    for question_num in hint.question_numbers:
        if question_num > 0 and question_num not in target_questions:
            target_questions.append(question_num)
    if not target_questions:
        return False

    logging.warning("Credamo 提交命中未作答提示，准备补答并重提：questions=%s message=%s", target_questions, hint.message)
    try:
        ctx.update_thread_status(thread_name or "Worker-?", "补答必答题", running=True)
    except Exception:
        logging.info("更新 Credamo 线程状态失败：补答必答题", exc_info=True)

    from credamo.provider.runtime import _click_submit, refill_required_questions_on_current_page

    filled_count = await refill_required_questions_on_current_page(
        driver,
        ctx.config,
        question_numbers=target_questions,
        thread_name=thread_name or "Worker-?",
        state=ctx,
    )
    if filled_count <= 0:
        logging.warning("Credamo 提交补救失败：未成功补答任何题目。questions=%s", target_questions)
        return False

    runtime_state.submission_recovery_attempts = recovery_attempts + 1
    page = await _page(driver)
    return bool(page is not None and await _click_submit(page, stop_signal))
