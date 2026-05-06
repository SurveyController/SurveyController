"""Credamo 见数提交结果与验证识别。"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

from software.network.browser import BrowserDriver


@dataclass
class PostSubmitError:
    error_text: str
    unanswered_question_ids: List[str] = field(default_factory=list)

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
_UNANSWERED_QUESTION_PATTERNS = (
    re.compile(r"请回答此问题"),
    re.compile(r"请(?:完成|填写|回答|作答)"),
    re.compile(r"(?:必答|必填|必须回答)"),
    re.compile(r"(?:此题|该题|本题)(?:未答|未填写|未回答|未完成)"),
)
_QUESTION_ERROR_SELECTOR = ".question-error, .el-form-item__error, .el-message--error"
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


def _body_text(driver: BrowserDriver) -> str:
    try:
        return str(driver.execute_script("return document.body ? document.body.innerText || '' : ''; ") or "")
    except Exception:
        return ""


def _visible_feedback_text(driver: BrowserDriver) -> str:
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
        return str(driver.execute_script(script) or "")
    except Exception:
        return ""


def _looks_like_selection_validation(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _SELECTION_VALIDATION_PATTERNS)


def _looks_like_unanswered_error(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _UNANSWERED_QUESTION_PATTERNS)


def detect_post_submit_errors(driver: BrowserDriver) -> Optional[PostSubmitError]:
    """Check for validation error messages after clicking submit.

    Returns a PostSubmitError with error text and unanswered question IDs, or None.
    """
    feedback_text = _visible_feedback_text(driver)
    if _contains_completion_marker(feedback_text):
        return None
    if _looks_like_unanswered_error(feedback_text) or _looks_like_selection_validation(feedback_text):
        return PostSubmitError(error_text=feedback_text)
    # Check for .question.error elements (Credamo adds 'error' class to unanswered questions)
    # and .question-error children, plus el-message toasts
    script = r"""
return (() => {
    const normalize = (s) => String(s || '').replace(/\s+/g, ' ').trim();
    const inDom = (el) => {
        if (!el) return false;
        // Check element is in the DOM tree (has a parent or is the document)
        return !!(el.parentNode || el.host);
    };
    const results = [];
    const seen = new Set();
    // Method 1: Find .question elements with .error class (most reliable)
    for (const qEl of document.querySelectorAll('.question.error')) {
        const qId = normalize(qEl.getAttribute('id') || qEl.getAttribute('data-id') || '');
        const qstNo = qEl.querySelector('.qstNo');
        const qNum = normalize(qstNo ? qstNo.textContent : '');
        const errorEl = qEl.querySelector('.question-error');
        const errorText = errorEl ? normalize(errorEl.innerText || errorEl.textContent) : '请回答此问题';
        const key = qId || qNum || errorText;
        if (seen.has(key)) continue;
        seen.add(key);
        results.push({ text: errorText, id: qId, num: qNum });
    }
    if (results.length > 0) return JSON.stringify(results);
    // Method 2: Find .question-error elements and walk up to .question
    for (const el of document.querySelectorAll('.question-error')) {
        const text = normalize(el.innerText || el.textContent);
        if (!text) continue;
        const questionEl = el.closest('.question');
        const qId = questionEl ? normalize(questionEl.getAttribute('id') || questionEl.getAttribute('data-id')) : '';
        const qstNo = questionEl ? questionEl.querySelector('.qstNo') : null;
        const qNum = normalize(qstNo ? qstNo.textContent : '');
        const key = qId || qNum || text;
        if (seen.has(key)) continue;
        seen.add(key);
        results.push({ text, id: qId, num: qNum });
    }
    if (results.length > 0) return JSON.stringify(results);
    // Method 3: el-message toasts (no question ID available)
    for (const el of document.querySelectorAll('.el-message, .el-message__content')) {
        const text = normalize(el.innerText || el.textContent);
        if (!text || seen.has(text)) continue;
        seen.add(text);
        results.push({ text, id: '', num: '' });
    }
    return JSON.stringify(results);
})()
"""
    try:
        raw = driver.execute_script(script)
        import json
        items = json.loads(str(raw or "[]"))
    except Exception:
        items = []
    if not items:
        return None
    error_texts = []
    question_ids = []
    for item in items:
        text = str(item.get("text") or "").strip()
        if not text or _contains_completion_marker(text):
            continue
        error_texts.append(text)
        q_id = str(item.get("id") or "").strip()
        q_num = str(item.get("num") or "").strip()
        if q_id:
            question_ids.append(q_id)
        elif q_num:
            question_ids.append(q_num)
    if not error_texts:
        return None
    return PostSubmitError(
        error_text="\n".join(dict.fromkeys(error_texts)),
        unanswered_question_ids=list(dict.fromkeys(question_ids)),
    )


def _contains_completion_marker(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(marker.lower() in normalized for marker in _COMPLETION_MARKERS)


def _contains_verification_marker(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(marker.lower() in normalized for marker in _VERIFICATION_MARKERS)


def _has_visible_action_controls(driver: BrowserDriver) -> bool:
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
        return bool(driver.execute_script(script))
    except Exception:
        return False


def is_completion_page(driver: BrowserDriver) -> bool:
    try:
        url = str(driver.current_url or "").lower()
    except Exception:
        url = ""
    if any(marker in url for marker in _COMPLETION_URL_MARKERS):
        return True
    feedback_text = _visible_feedback_text(driver)
    if _contains_completion_marker(feedback_text):
        return True
    text = _body_text(driver)
    if not _contains_completion_marker(text):
        return False
    return not _has_visible_action_controls(driver)


def submission_requires_verification(driver: BrowserDriver) -> bool:
    feedback_text = _visible_feedback_text(driver)
    if _contains_completion_marker(feedback_text):
        return False
    if _looks_like_selection_validation(feedback_text):
        return False
    if feedback_text and _contains_verification_marker(feedback_text):
        return True
    text = _body_text(driver)
    if _contains_completion_marker(text):
        return False
    return _contains_verification_marker(text)


def submission_validation_message(driver: Optional[BrowserDriver] = None) -> str:
    del driver
    return "Credamo 见数提交命中验证码/安全验证，当前版本暂不支持自动处理"


def wait_for_submission_verification(
    driver: BrowserDriver,
    *,
    timeout: int = 3,
    stop_signal: Any = None,
) -> bool:
    deadline = time.time() + max(1, int(timeout or 1))
    while time.time() < deadline:
        if stop_signal is not None and stop_signal.is_set():
            return False
        if submission_requires_verification(driver):
            return True
        time.sleep(0.15)
    return submission_requires_verification(driver)


def handle_submission_verification_detected(ctx: Any, gui_instance: Any, stop_signal: Any) -> None:
    del ctx, gui_instance, stop_signal


def consume_submission_success_signal(driver: BrowserDriver) -> bool:
    return is_completion_page(driver)


def is_device_quota_limit_page(driver: BrowserDriver) -> bool:
    text = _body_text(driver)
    return "已达上限" in text or "次数已满" in text or "名额已满" in text

