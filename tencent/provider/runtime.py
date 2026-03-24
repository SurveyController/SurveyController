"""腾讯问卷运行时答题与提交辅助。"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Dict, List, Optional, Sequence

from software.core.ai.runtime import AIRuntimeError, generate_ai_answer
from software.core.persona.context import apply_persona_boost, record_answer
from software.core.questions.consistency import (
    apply_matrix_row_consistency,
    apply_single_like_consistency,
    get_multiple_rule_constraint,
)
from software.core.questions.distribution import (
    record_pending_distribution_choice,
    resolve_distribution_probabilities,
)
from software.core.questions.strict_ratio import (
    enforce_reference_rank_order,
    is_strict_ratio_question,
    stochastic_round,
    weighted_sample_without_replacement,
)
from software.core.questions.tendency import get_tendency_index
from software.core.questions.utils import (
    normalize_droplist_probs,
    normalize_probabilities,
    resolve_dynamic_text_token,
    weighted_index,
)
from software.core.task import TaskContext
from software.core.modes.duration_control import simulate_answer_duration_delay
from software.network.browser import BrowserDriver, NoSuchElementException
from software.app.config import DEFAULT_FILL_TEXT, HEADLESS_PAGE_BUFFER_DELAY, HEADLESS_PAGE_CLICK_DELAY

from software.core.engine.navigation import _click_next_page_button, _human_scroll_after_question
from software.core.engine.runtime_control import _is_headless_mode
from software.core.engine.submission import submit

QQ_COMPLETION_MARKERS = (
    "感谢您的参与",
    "提交成功",
    "问卷提交成功",
    "答卷已提交",
    "感谢填写",
    "我们已收到",
    "已收到您的回答",
)
QQ_VERIFICATION_MARKERS = (
    "验证码",
    "安全验证",
    "滑动验证",
    "请完成验证",
    "请先完成验证",
    "验证后继续",
)
QQ_VALIDATION_MARKERS = (
    "请选择",
    "请填写",
    "为必答题",
    "此题必填",
    "请先完成",
)


def _page(driver: BrowserDriver):
    page = getattr(driver, "page", None)
    if page is None:
        raise RuntimeError("当前浏览器驱动不支持腾讯问卷自动填写")
    return page


def _wait_for_question_visible(driver: BrowserDriver, provider_question_id: str, timeout_ms: int = 8000) -> bool:
    if not provider_question_id:
        return False
    selector = f'section.question[data-question-id="{provider_question_id}"]'
    try:
        _page(driver).wait_for_selector(selector, state="visible", timeout=timeout_ms)
        return True
    except Exception:
        return False


def _is_question_visible(driver: BrowserDriver, provider_question_id: str) -> bool:
    if not provider_question_id:
        return False
    try:
        return bool(
            _page(driver).evaluate(
                """(questionId) => {
                    const section = document.querySelector(`section.question[data-question-id="${questionId}"]`);
                    if (!section) return false;
                    const style = window.getComputedStyle(section);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = section.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }""",
                provider_question_id,
            )
        )
    except Exception:
        return False


def _click_choice_input(driver: BrowserDriver, provider_question_id: str, input_type: str, option_index: int) -> bool:
    return bool(
        _page(driver).evaluate(
            """({ questionId, inputType, optionIndex }) => {
                const section = document.querySelector(`section.question[data-question-id="${questionId}"]`);
                if (!section || optionIndex < 0) return false;
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const inputs = Array.from(section.querySelectorAll(`input[type="${inputType}"]`)).filter(visible);
                const target = inputs[optionIndex];
                if (!target) return false;
                const clickCandidates = [
                    target,
                    target.closest('label'),
                    target.closest('.question-option'),
                    target.closest('.option'),
                    target.closest('.t-radio'),
                    target.closest('.t-checkbox'),
                    target.parentElement,
                ].filter(Boolean);
                for (const node of clickCandidates) {
                    try { node.click(); } catch (e) {}
                    if (target.checked) return true;
                }
                try { target.checked = true; } catch (e) {}
                ['input', 'change', 'click'].forEach((name) => {
                    try { target.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                });
                return !!target.checked;
            }""",
            {
                "questionId": provider_question_id,
                "inputType": str(input_type or "radio"),
                "optionIndex": int(option_index),
            },
        )
    )


def _fill_text_question(driver: BrowserDriver, provider_question_id: str, value: str) -> bool:
    return bool(
        _page(driver).evaluate(
            """({ questionId, rawValue }) => {
                const section = document.querySelector(`section.question[data-question-id="${questionId}"]`);
                if (!section) return false;
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const isTextInput = (el) => {
                    if (!el) return false;
                    const tag = (el.tagName || '').toLowerCase();
                    if (tag === 'textarea') return true;
                    if (tag !== 'input') return false;
                    const type = String(el.getAttribute('type') || '').toLowerCase();
                    return !type || ['text', 'search', 'tel', 'number'].includes(type);
                };
                const target = Array.from(section.querySelectorAll('textarea, input')).find((el) => visible(el) && isTextInput(el));
                if (!target) return false;
                const nextValue = String(rawValue || '');
                try { target.focus(); } catch (e) {}
                try { target.value = nextValue; } catch (e) {}
                try { target.setAttribute('value', nextValue); } catch (e) {}
                ['input', 'change', 'blur'].forEach((name) => {
                    try { target.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                });
                return String(target.value || '') === nextValue;
            }""",
            {"questionId": provider_question_id, "rawValue": str(value or "")},
        )
    )


def _open_dropdown(driver: BrowserDriver, provider_question_id: str) -> bool:
    return bool(
        _page(driver).evaluate(
            """(questionId) => {
                const section = document.querySelector(`section.question[data-question-id="${questionId}"]`);
                if (!section) return false;
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const candidates = Array.from(section.querySelectorAll('input, .t-select, .t-select__wrap, .t-input')).filter(visible);
                for (const node of candidates) {
                    try { node.click(); } catch (e) {}
                    return true;
                }
                return false;
            }""",
            provider_question_id,
        )
    )


def _select_dropdown_option(driver: BrowserDriver, option_text: str) -> bool:
    page = _page(driver)
    try:
        page.wait_for_selector('[role="listitem"], .t-popup li, .t-select-option', state="visible", timeout=5000)
    except Exception:
        return False
    return bool(
        page.evaluate(
            """(targetText) => {
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const normalizedTarget = String(targetText || '').trim();
                const candidates = Array.from(document.querySelectorAll('[role="listitem"], .t-popup li, .t-select-option')).filter(visible);
                const match = candidates.find((el) => {
                    const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
                    return text === normalizedTarget;
                }) || candidates.find((el) => {
                    const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
                    return text.includes(normalizedTarget);
                });
                if (!match) return false;
                try { match.click(); } catch (e) {}
                return true;
            }""",
            str(option_text or "").strip(),
        )
    )


def _click_matrix_cell(driver: BrowserDriver, provider_question_id: str, row_index: int, column_index: int) -> bool:
    return bool(
        _page(driver).evaluate(
            """({ questionId, rowIndex, columnIndex }) => {
                const section = document.querySelector(`section.question[data-question-id="${questionId}"]`);
                if (!section || rowIndex < 0 || columnIndex < 0) return false;
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const rows = Array.from(section.querySelectorAll('.question-item, tbody tr')).filter((row) => {
                    if (!visible(row)) return false;
                    return row.querySelector('input[type="radio"]');
                });
                const row = rows[rowIndex];
                if (!row) return false;
                const inputs = Array.from(row.querySelectorAll('input[type="radio"]')).filter(visible);
                const target = inputs[columnIndex];
                if (!target) return false;
                const clickCandidates = [
                    target,
                    target.closest('label'),
                    target.closest('td'),
                    target.closest('.question-option'),
                    target.parentElement,
                ].filter(Boolean);
                for (const node of clickCandidates) {
                    try { node.click(); } catch (e) {}
                    if (target.checked) return true;
                }
                try { target.checked = true; } catch (e) {}
                ['input', 'change', 'click'].forEach((name) => {
                    try { target.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                });
                return !!target.checked;
            }""",
            {
                "questionId": provider_question_id,
                "rowIndex": int(row_index),
                "columnIndex": int(column_index),
            },
        )
    )


def _normalize_selected_indices(indices: Sequence[int], option_count: int) -> List[int]:
    result: List[int] = []
    seen = set()
    for raw in indices:
        try:
            idx = int(raw)
        except Exception:
            continue
        if idx < 0 or idx >= option_count or idx in seen:
            continue
        seen.add(idx)
        result.append(idx)
    return sorted(result)


def _apply_multiple_constraints(
    selected_indices: Sequence[int],
    option_count: int,
    min_required: int,
    max_allowed: int,
    required_indices: Sequence[int],
    blocked_indices: Sequence[int],
    positive_priority_indices: Sequence[int],
) -> List[int]:
    blocked = set(_normalize_selected_indices(blocked_indices, option_count))
    required = _normalize_selected_indices(required_indices, option_count)
    selected = [idx for idx in _normalize_selected_indices(selected_indices, option_count) if idx not in blocked]
    for idx in required:
        if idx not in selected:
            selected.append(idx)
    selected = _normalize_selected_indices(selected, option_count)
    max_allowed = max(1, min(max_allowed, option_count))
    min_required = max(1, min(min_required, option_count))
    if len(selected) > max_allowed:
        kept = list(required[:max_allowed])
        for idx in selected:
            if idx in kept:
                continue
            if len(kept) >= max_allowed:
                break
            kept.append(idx)
        selected = _normalize_selected_indices(kept, option_count)
    if len(selected) < min_required:
        for idx in list(positive_priority_indices) + list(range(option_count)):
            if idx in blocked or idx in selected:
                continue
            selected.append(idx)
            if len(selected) >= min_required:
                break
    if len(selected) > max_allowed:
        selected = selected[:max_allowed]
    return _normalize_selected_indices(selected, option_count)


def qq_submission_requires_verification(driver: BrowserDriver) -> bool:
    try:
        return bool(
            _page(driver).evaluate(
                """(markers) => {
                    const visible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (!style) return false;
                        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };
                    const bodyText = (document.body?.innerText || '').replace(/\\s+/g, ' ');
                    if (!markers.some((marker) => bodyText.includes(marker))) return false;
                    const strongMarkers = ['安全验证', '滑动验证', '请完成验证', '请先完成验证'];
                    if (strongMarkers.some((marker) => bodyText.includes(marker))) return true;
                    const modalSelectors = [
                        '.t-dialog',
                        '.t-popup',
                        '.captcha',
                        '.verify',
                        '[class*="captcha"]',
                        '[class*="verify"]',
                    ];
                    return modalSelectors.some((sel) => Array.from(document.querySelectorAll(sel)).some(visible));
                }""",
                list(QQ_VERIFICATION_MARKERS),
            )
        )
    except Exception:
        return False


def qq_submission_validation_message(driver: BrowserDriver) -> str:
    try:
        message = _page(driver).evaluate(
            """(markers) => {
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style) return false;
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const selectors = ['.error', '.question-error', '.t-form__error', '.t-message', '[class*="error"]'];
                const messages = [];
                for (const sel of selectors) {
                    for (const node of document.querySelectorAll(sel)) {
                        if (!visible(node)) continue;
                        const text = (node.innerText || node.textContent || '').trim().replace(/\\s+/g, ' ');
                        if (text) messages.push(text);
                    }
                }
                const bodyText = (document.body?.innerText || '').replace(/\\s+/g, ' ');
                for (const marker of markers) {
                    if (bodyText.includes(marker)) {
                        messages.push(marker);
                    }
                }
                return Array.from(new Set(messages)).slice(0, 3).join(' | ');
            }""",
            list(QQ_VALIDATION_MARKERS),
        ) or ""
        return str(message or "").strip()
    except Exception:
        return ""


def qq_is_completion_page(driver: BrowserDriver) -> bool:
    try:
        return bool(
            _page(driver).evaluate(
                """(markers) => {
                    const visible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (!style) return false;
                        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };
                    const bodyText = (document.body?.innerText || '').replace(/\\s+/g, ' ');
                    const hasMarker = markers.some((marker) => bodyText.includes(marker));
                    const hasVisibleAction = Array.from(document.querySelectorAll('.page-control button, .btn-next, .btn-submit')).some(visible);
                    const hasVisibleQuestion = Array.from(document.querySelectorAll('.question-list > section.question')).some(visible);
                    if (hasMarker && !hasVisibleAction) return true;
                    if (!hasVisibleAction && !hasVisibleQuestion && hasMarker) return true;
                    return false;
                }""",
                list(QQ_COMPLETION_MARKERS),
            )
        )
    except Exception:
        return False


def _answer_qq_single(
    driver: BrowserDriver,
    question: Dict[str, Any],
    config_index: int,
    ctx: TaskContext,
) -> None:
    current = int(question.get("num") or 0)
    option_texts = list(question.get("option_texts") or [])
    option_count = max(1, len(option_texts) or int(question.get("options") or 0))
    probabilities = ctx.single_prob[config_index] if config_index < len(ctx.single_prob) else -1
    probabilities = normalize_droplist_probs(probabilities, option_count)
    strict_ratio = is_strict_ratio_question(ctx, current)
    if not strict_ratio:
        probabilities = apply_persona_boost(option_texts, probabilities)
    probabilities = apply_single_like_consistency(probabilities, current)
    if strict_ratio:
        strict_reference = list(probabilities)
        probabilities = resolve_distribution_probabilities(probabilities, option_count, ctx, current)
        probabilities = enforce_reference_rank_order(probabilities, strict_reference)
    selected_index = weighted_index(probabilities)
    if not _click_choice_input(driver, str(question.get("provider_question_id") or ""), "radio", selected_index):
        logging.warning("腾讯问卷第%d题（单选）点击未生效，已跳过。", current)
        return
    if strict_ratio:
        record_pending_distribution_choice(ctx, current, selected_index, option_count)
    selected_text = option_texts[selected_index] if selected_index < len(option_texts) else ""
    record_answer(current, "single", selected_indices=[selected_index], selected_texts=[selected_text])


def _answer_qq_dropdown(
    driver: BrowserDriver,
    question: Dict[str, Any],
    config_index: int,
    ctx: TaskContext,
) -> None:
    current = int(question.get("num") or 0)
    option_texts = list(question.get("option_texts") or [])
    option_count = max(1, len(option_texts) or int(question.get("options") or 0))
    probabilities = ctx.droplist_prob[config_index] if config_index < len(ctx.droplist_prob) else -1
    probabilities = normalize_droplist_probs(probabilities, option_count)
    strict_ratio = is_strict_ratio_question(ctx, current)
    if not strict_ratio:
        probabilities = apply_persona_boost(option_texts, probabilities)
    if strict_ratio:
        strict_reference = list(probabilities)
        probabilities = resolve_distribution_probabilities(probabilities, option_count, ctx, current)
        probabilities = enforce_reference_rank_order(probabilities, strict_reference)
    selected_index = weighted_index(probabilities)
    selected_text = option_texts[selected_index] if selected_index < len(option_texts) else ""
    question_id = str(question.get("provider_question_id") or "")
    if not _open_dropdown(driver, question_id):
        logging.warning("腾讯问卷第%d题（下拉）无法打开选项面板。", current)
        return
    if not _select_dropdown_option(driver, selected_text):
        logging.warning("腾讯问卷第%d题（下拉）无法选中选项：%s", current, selected_text)
        return
    if strict_ratio:
        record_pending_distribution_choice(ctx, current, selected_index, option_count)
    record_answer(current, "dropdown", selected_indices=[selected_index], selected_texts=[selected_text])


def _answer_qq_text(
    driver: BrowserDriver,
    question: Dict[str, Any],
    config_index: int,
    ctx: TaskContext,
) -> None:
    current = int(question.get("num") or 0)
    answer_candidates = ctx.texts[config_index] if config_index < len(ctx.texts) else [DEFAULT_FILL_TEXT]
    probabilities = ctx.texts_prob[config_index] if config_index < len(ctx.texts_prob) else [1.0]
    if not answer_candidates:
        answer_candidates = [DEFAULT_FILL_TEXT]
    if len(probabilities) != len(answer_candidates):
        probabilities = normalize_probabilities([1.0] * len(answer_candidates))
    resolved_candidates = [resolve_dynamic_text_token(candidate) for candidate in answer_candidates]
    selected_index = weighted_index(probabilities)
    selected_answer = str(resolved_candidates[selected_index] or DEFAULT_FILL_TEXT).strip() or DEFAULT_FILL_TEXT
    ai_enabled = bool(ctx.text_ai_flags[config_index]) if config_index < len(ctx.text_ai_flags) else False
    title = str(question.get("title") or "")
    if ai_enabled:
        try:
            generated = generate_ai_answer(title, question_type="fill_blank", blank_count=1)
        except AIRuntimeError as exc:
            raise AIRuntimeError(f"腾讯问卷第{current}题 AI 生成失败：{exc}") from exc
        if isinstance(generated, list):
            selected_answer = str(generated[0]).strip() if generated else DEFAULT_FILL_TEXT
        else:
            selected_answer = str(generated or "").strip() or DEFAULT_FILL_TEXT
    if not _fill_text_question(driver, str(question.get("provider_question_id") or ""), selected_answer):
        logging.warning("腾讯问卷第%d题（文本）填写失败。", current)
        return
    record_answer(current, "text", text_answer=selected_answer)


def _answer_qq_score_like(
    driver: BrowserDriver,
    question: Dict[str, Any],
    config_index: int,
    ctx: TaskContext,
    *,
    psycho_plan: Optional[Any],
) -> None:
    current = int(question.get("num") or 0)
    option_count = max(2, int(question.get("options") or 0))
    probabilities = ctx.scale_prob[config_index] if config_index < len(ctx.scale_prob) else -1
    probs = normalize_droplist_probs(probabilities, option_count)
    probs = apply_single_like_consistency(probs, current)
    strict_ratio = is_strict_ratio_question(ctx, current)
    probs = resolve_distribution_probabilities(
        probs,
        option_count,
        ctx,
        current,
        psycho_plan=None if strict_ratio else psycho_plan,
    )
    if strict_ratio:
        probs = enforce_reference_rank_order(probs, normalize_droplist_probs(probabilities, option_count))
        selected_index = weighted_index(probs)
    else:
        selected_index = get_tendency_index(
            option_count,
            probs,
            dimension=ctx.question_dimension_map.get(current),
            psycho_plan=psycho_plan,
            question_index=current,
        )
    if not _click_choice_input(driver, str(question.get("provider_question_id") or ""), "radio", selected_index):
        logging.warning("腾讯问卷第%d题（评分）点击未生效。", current)
        return
    record_pending_distribution_choice(ctx, current, selected_index, option_count)
    record_answer(current, "score", selected_indices=[selected_index])


def _answer_qq_matrix(
    driver: BrowserDriver,
    question: Dict[str, Any],
    config_index: int,
    ctx: TaskContext,
    *,
    psycho_plan: Optional[Any],
) -> int:
    current = int(question.get("num") or 0)
    question_id = str(question.get("provider_question_id") or "")
    row_count = max(1, int(question.get("rows") or 1))
    option_count = max(2, int(question.get("options") or 0))
    strict_ratio = is_strict_ratio_question(ctx, current)
    next_index = config_index
    for row_index in range(row_count):
        raw_probabilities = ctx.matrix_prob[next_index] if next_index < len(ctx.matrix_prob) else -1
        next_index += 1
        strict_reference: Optional[List[float]] = None
        row_probabilities: Any = -1
        if isinstance(raw_probabilities, list):
            try:
                probs = [float(value) for value in raw_probabilities]
            except Exception:
                probs = []
            if len(probs) != option_count:
                probs = [1.0] * option_count
            strict_reference = list(probs)
            probs = apply_matrix_row_consistency(probs, current, row_index)
            if any(prob > 0 for prob in probs):
                row_probabilities = resolve_distribution_probabilities(
                    probs,
                    option_count,
                    ctx,
                    current,
                    row_index=row_index,
                    psycho_plan=None if strict_ratio else psycho_plan,
                )
        else:
            uniform_probs = apply_matrix_row_consistency([1.0] * option_count, current, row_index)
            if any(prob > 0 for prob in uniform_probs):
                row_probabilities = resolve_distribution_probabilities(
                    uniform_probs,
                    option_count,
                    ctx,
                    current,
                    row_index=row_index,
                    psycho_plan=None if strict_ratio else psycho_plan,
                )
        if strict_ratio:
            if isinstance(row_probabilities, list):
                row_probabilities = enforce_reference_rank_order(row_probabilities, strict_reference or row_probabilities)
            if isinstance(row_probabilities, list) and row_probabilities:
                selected_index = weighted_index(row_probabilities)
            else:
                selected_index = random.randrange(option_count)
        else:
            selected_index = get_tendency_index(
                option_count,
                row_probabilities,
                dimension=ctx.question_dimension_map.get(current),
                psycho_plan=psycho_plan,
                question_index=current,
                row_index=row_index,
            )
        if not _click_matrix_cell(driver, question_id, row_index, selected_index):
            logging.warning("腾讯问卷第%d题（矩阵）第%d行点击失败。", current, row_index + 1)
            continue
        record_pending_distribution_choice(ctx, current, selected_index, option_count, row_index=row_index)
        record_answer(current, "matrix", selected_indices=[selected_index], row_index=row_index)
    return next_index


def _answer_qq_multiple(
    driver: BrowserDriver,
    question: Dict[str, Any],
    config_index: int,
    ctx: TaskContext,
) -> None:
    current = int(question.get("num") or 0)
    option_texts = list(question.get("option_texts") or [])
    option_count = max(1, len(option_texts) or int(question.get("options") or 0))
    min_required = int(question.get("multi_min_limit") or 1)
    max_allowed = int(question.get("multi_max_limit") or option_count or 1)
    min_required = max(1, min(min_required, option_count))
    max_allowed = max(1, min(max_allowed, option_count))
    if min_required > max_allowed:
        min_required = max_allowed

    must_select_indices, must_not_select_indices, _ = get_multiple_rule_constraint(current, option_count)
    required_indices = _normalize_selected_indices(must_select_indices, option_count)
    blocked_indices = _normalize_selected_indices(must_not_select_indices, option_count)

    def _apply(selected_indices: Sequence[int]) -> List[int]:
        applied = []
        question_id = str(question.get("provider_question_id") or "")
        for option_idx in selected_indices:
            if _click_choice_input(driver, question_id, "checkbox", option_idx):
                applied.append(option_idx)
        return applied

    selection_probabilities = ctx.multiple_prob[config_index] if config_index < len(ctx.multiple_prob) else [50.0] * option_count
    if selection_probabilities == -1 or (
        isinstance(selection_probabilities, list)
        and len(selection_probabilities) == 1
        and selection_probabilities[0] == -1
    ):
        available_pool = [idx for idx in range(option_count) if idx not in blocked_indices and idx not in required_indices]
        min_total = max(min_required, len(required_indices))
        max_total = min(max_allowed, len(required_indices) + len(available_pool))
        if min_total > max_total:
            min_total = max_total
        extra_min = max(0, min_total - len(required_indices))
        extra_max = max(0, max_total - len(required_indices))
        extra_count = random.randint(extra_min, extra_max) if extra_max >= extra_min else 0
        sampled = random.sample(available_pool, extra_count) if extra_count > 0 else []
        selected = _apply_multiple_constraints(
            list(required_indices) + sampled,
            option_count,
            min_required,
            max_allowed,
            required_indices,
            blocked_indices,
            available_pool,
        )
        confirmed = _apply(selected)
        if confirmed:
            selected_texts = [option_texts[i] for i in confirmed if i < len(option_texts)]
            record_answer(current, "multiple", selected_indices=confirmed, selected_texts=selected_texts)
        return

    sanitized_probabilities: List[float] = []
    for raw_prob in selection_probabilities:
        try:
            prob_value = float(raw_prob)
        except Exception:
            prob_value = 0.0
        prob_value = max(0.0, min(100.0, prob_value))
        sanitized_probabilities.append(prob_value)
    if len(sanitized_probabilities) < option_count:
        sanitized_probabilities.extend([0.0] * (option_count - len(sanitized_probabilities)))
    elif len(sanitized_probabilities) > option_count:
        sanitized_probabilities = sanitized_probabilities[:option_count]

    strict_ratio = is_strict_ratio_question(ctx, current)
    if not strict_ratio:
        boosted = apply_persona_boost(option_texts, sanitized_probabilities)
        sanitized_probabilities = [min(100.0, prob) for prob in boosted]
    for idx in blocked_indices:
        sanitized_probabilities[idx] = 0.0
    for idx in required_indices:
        sanitized_probabilities[idx] = 0.0

    if strict_ratio:
        positive_optional = [
            idx for idx, prob in enumerate(sanitized_probabilities)
            if prob > 0 and idx not in blocked_indices and idx not in required_indices
        ]
        required_selected = _normalize_selected_indices(required_indices, option_count)
        if len(required_selected) > max_allowed:
            required_selected = required_selected[:max_allowed]
        min_total = max(min_required, len(required_selected))
        max_total = min(max_allowed, len(required_selected) + len(positive_optional))
        if min_total > max_total:
            min_total = max_total
        expected_optional = sum(sanitized_probabilities[idx] for idx in positive_optional) / 100.0
        total_target = len(required_selected) + stochastic_round(expected_optional)
        total_target = max(min_total, min(max_total, total_target))
        optional_target = max(0, total_target - len(required_selected))
        sampled_optional = weighted_sample_without_replacement(
            positive_optional,
            [sanitized_probabilities[idx] for idx in positive_optional],
            optional_target,
        )
        selected = _normalize_selected_indices(required_selected + sampled_optional, option_count)
        confirmed = _apply(selected)
        if confirmed:
            selected_texts = [option_texts[i] for i in confirmed if i < len(option_texts)]
            record_answer(current, "multiple", selected_indices=confirmed, selected_texts=selected_texts)
        return

    positive_indices = [idx for idx, prob in enumerate(sanitized_probabilities) if prob > 0]
    if not positive_indices and not required_indices:
        return
    selection_mask: List[int] = []
    attempts = 0
    max_attempts = 32
    if positive_indices:
        while sum(selection_mask) == 0 and attempts < max_attempts:
            selection_mask = [1 if random.random() < (prob / 100.0) else 0 for prob in sanitized_probabilities]
            attempts += 1
        if sum(selection_mask) == 0:
            selection_mask = [0] * option_count
            selection_mask[random.choice(positive_indices)] = 1
    selected = [
        idx for idx, selected_flag in enumerate(selection_mask)
        if selected_flag == 1 and sanitized_probabilities[idx] > 0
    ]
    selected = _apply_multiple_constraints(
        selected,
        option_count,
        min_required,
        max_allowed,
        required_indices,
        blocked_indices,
        positive_indices,
    )
    if not selected and positive_indices:
        selected = [random.choice(positive_indices)]
    confirmed = _apply(selected)
    if confirmed:
        selected_texts = [option_texts[i] for i in confirmed if i < len(option_texts)]
        record_answer(current, "multiple", selected_indices=confirmed, selected_texts=selected_texts)


def _group_questions_by_page(ctx: TaskContext) -> List[List[Dict[str, Any]]]:
    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for question_num in sorted(ctx.questions_metadata.keys()):
        item = dict(ctx.questions_metadata.get(question_num) or {})
        if not item or bool(item.get("is_description")):
            continue
        page_number = max(1, int(item.get("page") or 1))
        grouped.setdefault(page_number, []).append(item)
    return [grouped[key] for key in sorted(grouped.keys())]


def _wait_for_page_transition(
    driver: BrowserDriver,
    current_first_question_id: str,
    next_first_question_id: str,
    timeout_ms: int = 12000,
) -> None:
    page = _page(driver)
    current_selector = f'section.question[data-question-id="{current_first_question_id}"]'
    next_selector = f'section.question[data-question-id="{next_first_question_id}"]'
    try:
        page.wait_for_selector(current_selector, state="hidden", timeout=min(4000, timeout_ms))
    except Exception:
        pass
    page.wait_for_selector(next_selector, state="visible", timeout=timeout_ms)


def brush_qq(
    driver: BrowserDriver,
    ctx: TaskContext,
    *,
    stop_signal: Optional[threading.Event],
    thread_name: str,
    psycho_plan: Optional[Any],
) -> bool:
    unsupported = [item for item in list((ctx.questions_metadata or {}).values()) if bool(item.get("unsupported"))]
    if unsupported:
        raise RuntimeError("当前腾讯问卷仍包含未支持题型，已阻止启动")

    page_groups = _group_questions_by_page(ctx)
    total_steps = sum(len(group) for group in page_groups)
    try:
        ctx.update_thread_step(thread_name, 0, total_steps, status_text="答题中", running=True)
    except Exception:
        logging.info("初始化腾讯问卷步骤进度失败", exc_info=True)

    active_stop = stop_signal or ctx.stop_event
    step_index = 0
    headless_mode = _is_headless_mode(ctx)

    def _abort_requested() -> bool:
        return bool(active_stop and active_stop.is_set())

    for page_index, questions in enumerate(page_groups):
        for question in questions:
            if _abort_requested():
                try:
                    ctx.update_thread_status(thread_name, "已中断", running=False)
                except Exception:
                    logging.info("更新线程状态失败：已中断", exc_info=True)
                return False

            question_num = int(question.get("num") or 0)
            question_id = str(question.get("provider_question_id") or "")
            if question_num <= 0 or not question_id:
                continue
            if not _wait_for_question_visible(driver, question_id, timeout_ms=8000):
                logging.warning("腾讯问卷第%d题未出现在当前页面，已跳过。", question_num)
                continue
            if not _is_question_visible(driver, question_id):
                continue

            step_index += 1
            if total_steps > 0:
                try:
                    ctx.update_thread_step(
                        thread_name,
                        step_index,
                        total_steps,
                        status_text="答题中",
                        running=True,
                    )
                except Exception:
                    logging.info("更新腾讯问卷线程步骤失败", exc_info=True)

            config_entry = ctx.question_config_index_map.get(question_num)
            if not config_entry:
                logging.warning("腾讯问卷第%d题缺少配置映射，已跳过。", question_num)
                continue
            entry_type, config_index = config_entry
            if entry_type == "single":
                _answer_qq_single(driver, question, config_index, ctx)
            elif entry_type == "multiple":
                _answer_qq_multiple(driver, question, config_index, ctx)
            elif entry_type == "dropdown":
                _answer_qq_dropdown(driver, question, config_index, ctx)
            elif entry_type in {"text", "multi_text"}:
                _answer_qq_text(driver, question, config_index, ctx)
            elif entry_type in {"scale", "score"}:
                _answer_qq_score_like(driver, question, config_index, ctx, psycho_plan=psycho_plan)
            elif entry_type == "matrix":
                _answer_qq_matrix(driver, question, config_index, ctx, psycho_plan=psycho_plan)
            else:
                logging.warning("腾讯问卷第%d题暂未接入运行时类型：%s", question_num, entry_type)

        _human_scroll_after_question(driver)
        if _abort_requested():
            try:
                ctx.update_thread_status(thread_name, "已中断", running=False)
            except Exception:
                logging.info("更新线程状态失败：已中断", exc_info=True)
            return False

        buffer_delay = float(HEADLESS_PAGE_BUFFER_DELAY if headless_mode else 0.5)
        if buffer_delay > 0:
            if active_stop and active_stop.wait(buffer_delay):
                try:
                    ctx.update_thread_status(thread_name, "已中断", running=False)
                except Exception:
                    logging.info("更新线程状态失败：已中断", exc_info=True)
                return False
            if not active_stop:
                time.sleep(buffer_delay)

        is_last_page = page_index == len(page_groups) - 1
        if is_last_page:
            if simulate_answer_duration_delay(active_stop, ctx.answer_duration_range_seconds):
                try:
                    ctx.update_thread_status(thread_name, "已中断", running=False)
                except Exception:
                    logging.info("更新线程状态失败：已中断", exc_info=True)
                return False
            break

        current_first = str(questions[0].get("provider_question_id") or "")
        next_first = str(page_groups[page_index + 1][0].get("provider_question_id") or "")
        clicked = _click_next_page_button(driver)
        if not clicked:
            raise NoSuchElementException("腾讯问卷下一页按钮未找到")
        _wait_for_page_transition(driver, current_first, next_first)
        click_delay = float(HEADLESS_PAGE_CLICK_DELAY if headless_mode else 0.5)
        if click_delay > 0:
            if active_stop and active_stop.wait(click_delay):
                try:
                    ctx.update_thread_status(thread_name, "已中断", running=False)
                except Exception:
                    logging.info("更新线程状态失败：已中断", exc_info=True)
                return False
            if not active_stop:
                time.sleep(click_delay)

    if _abort_requested():
        try:
            ctx.update_thread_status(thread_name, "已中断", running=False)
        except Exception:
            logging.info("更新线程状态失败：已中断", exc_info=True)
        return False

    try:
        ctx.update_thread_status(thread_name, "提交中", running=True)
    except Exception:
        logging.info("更新线程状态失败：提交中", exc_info=True)
    submit(driver, ctx=ctx, stop_signal=active_stop)
    try:
        ctx.update_thread_status(thread_name, "等待结果确认", running=True)
    except Exception:
        logging.info("更新线程状态失败：等待结果确认", exc_info=True)
    return True


