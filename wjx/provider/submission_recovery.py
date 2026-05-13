"""问卷星提交后补答恢复。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from software.core.task import ExecutionState
from software.network.browser.runtime_async import BrowserDriver

from .runtime_state import get_wjx_runtime_state
from .submission_pages import _page_looks_like_wjx_questionnaire
from .submission_verification import submission_requires_verification

_WJX_MISSING_ANSWER_MARKERS = (
    "此题未作答",
    "本题未作答",
    "请选择",
    "请填写",
    "必答题",
)


@dataclass(frozen=True)
class SubmissionRecoveryHint:
    question_numbers: tuple[int, ...]
    message: str


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
    from wjx.provider.submission import submit

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
    "SubmissionRecoveryHint",
    "_extract_missing_answer_hint",
    "attempt_submission_recovery",
]
