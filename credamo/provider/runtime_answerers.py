"""Credamo 见数运行时各题型作答实现。"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any, Optional

from software.app.config import DEFAULT_FILL_TEXT
from software.core.engine.async_wait import sleep_or_stop
from software.core.questions.runtime_async import resolve_runtime_text_values_from_config
from software.core.questions.utils import (
    normalize_droplist_probs,
    weighted_index,
)

from .runtime_dom import (
    _click_element,
    _element_text,
    _input_value,
    _is_checked,
    _option_click_targets,
    _option_inputs,
    _question_title_text,
    _root_text,
    _text_inputs,
)


@dataclass(frozen=True)
class AnswerAction:
    root_index: int
    question_num: int
    kind: str
    selected_indices: tuple[int, ...] = ()
    matrix_indices: tuple[int, ...] = ()
    text_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class BatchFillResult:
    applied: tuple[int, ...] = ()
    failed: tuple[int, ...] = ()
    skipped: tuple[int, ...] = ()


async def _resolve_forced_choice_index(page: Any, root: Any, option_texts: list[str]) -> Optional[int]:
    if not option_texts:
        return None
    try:
        from credamo.provider import parser as credamo_parser
    except Exception:
        return None

    title_text = await _question_title_text(page, root)
    extra_fragments = [await _root_text(page, root)]
    forced_index, _forced_text = credamo_parser._extract_force_select_option(
        title_text,
        option_texts,
        extra_fragments=extra_fragments,
    )
    if forced_index is None:
        forced_index, _forced_text = credamo_parser._extract_arithmetic_option(
            title_text,
            option_texts,
            extra_fragments=extra_fragments,
        )
    if forced_index is None or forced_index < 0:
        return None
    if forced_index >= len(option_texts):
        return None
    return forced_index


async def _single_choice_options(page: Any, root: Any) -> list[tuple[Any, Any, str]]:
    row_selectors = (
        ".single-choice .choice-row",
        ".single-choice .choice",
        ".choice-row",
        ".choice",
    )
    options: list[tuple[Any, Any, str]] = []

    for selector in row_selectors:
        try:
            rows = await root.query_selector_all(selector)
        except Exception:
            rows = []
        if not rows:
            continue
        for row in rows:
            try:
                input_element = await row.query_selector("input[type='radio'], [role='radio']")
            except Exception:
                input_element = None
            row_text = await _element_text(page, row)
            if input_element is None and not row_text:
                continue
            click_target = row if row is not None else input_element
            if click_target is None:
                continue
            options.append((input_element, click_target, row_text))
        if options:
            return options

    for input_element in await _option_inputs(root, "radio"):
        row_text = await _element_text(page, input_element)
        options.append((input_element, input_element, row_text))
    return options


async def _click_single_choice_option(page: Any, option: tuple[Any, Any, str]) -> bool:
    input_element, click_target, _text = option
    for candidate in (click_target, input_element):
        if candidate is None:
            continue
        if await _click_element(page, candidate):
            if input_element is None or await _is_checked(page, input_element):
                return True
    if input_element is not None:
        try:
            if bool(await page.evaluate("el => { el.click(); return !!el.checked; }", input_element)):
                return True
        except Exception:
            pass
    return False


async def _answer_single_like(page: Any, root: Any, weights: Any, option_count: int) -> bool:
    del option_count
    options = await _single_choice_options(page, root)
    target_count = len(options)
    if target_count <= 0:
        return False
    forced_option_texts = [text for _input, _target, text in options]
    forced_index = await _resolve_forced_choice_index(page, root, forced_option_texts)
    if forced_index is not None and forced_index < target_count and await _click_single_choice_option(page, options[forced_index]):
        return True
    probabilities = normalize_droplist_probs(weights, target_count)
    target_index = weighted_index(probabilities)
    return await _click_single_choice_option(page, options[min(target_index, target_count - 1)])


def _positive_multiple_indexes(weights: Any, option_count: int) -> list[int]:
    count = max(0, int(option_count or 0))
    if count <= 0:
        return []
    if not isinstance(weights, list) or not weights:
        return [random.randrange(count)]
    normalized: list[float] = []
    for idx in range(count):
        raw = weights[idx] if idx < len(weights) else 0.0
        try:
            normalized.append(max(0.0, float(raw)))
        except Exception:
            normalized.append(0.0)
    selected = [idx for idx, weight in enumerate(normalized) if weight > 0 and random.uniform(0, 100) <= weight]
    if not selected:
        positive = [idx for idx, weight in enumerate(normalized) if weight > 0]
        selected = [random.choice(positive)] if positive else [random.randrange(count)]
    return selected


async def _resolve_multi_select_limits(page: Any, root: Any, option_count: int) -> tuple[Optional[int], Optional[int]]:
    try:
        from credamo.provider import parser as credamo_parser
    except Exception:
        return None, None

    title_text = await _question_title_text(page, root)
    extra_fragments = [await _root_text(page, root)]
    try:
        return credamo_parser._extract_multi_select_limits(
            title_text,
            option_count=option_count,
            extra_fragments=extra_fragments,
        )
    except Exception:
        return None, None


def _positive_multiple_indexes_with_limits(
    weights: Any,
    option_count: int,
    *,
    min_limit: Optional[int] = None,
    max_limit: Optional[int] = None,
) -> list[int]:
    count = max(0, int(option_count or 0))
    if count <= 0:
        return []

    resolved_min = max(0, min(count, int(min_limit or 0)))
    resolved_max = count if max_limit is None else max(0, min(count, int(max_limit or 0)))
    if resolved_max <= 0:
        resolved_max = count
    if resolved_min > resolved_max:
        resolved_min = resolved_max

    selected = list(dict.fromkeys(_positive_multiple_indexes(weights, count)))
    if resolved_max < len(selected):
        selected = random.sample(selected, resolved_max)

    remaining_positive: list[int] = []
    remaining_any: list[int] = []
    if isinstance(weights, list) and weights:
        for idx in range(count):
            raw = weights[idx] if idx < len(weights) else 0.0
            try:
                weight = max(0.0, float(raw))
            except Exception:
                weight = 0.0
            if idx not in selected and weight > 0:
                remaining_positive.append(idx)
    remaining_any = [idx for idx in range(count) if idx not in selected and idx not in remaining_positive]
    random.shuffle(remaining_positive)
    random.shuffle(remaining_any)

    while len(selected) < resolved_min and (remaining_positive or remaining_any):
        if remaining_positive:
            selected.append(remaining_positive.pop())
            continue
        selected.append(remaining_any.pop())

    return sorted(dict.fromkeys(selected))


async def _answer_multiple(
    page: Any,
    root: Any,
    weights: Any,
    *,
    min_limit: Optional[int] = None,
    max_limit: Optional[int] = None,
) -> bool:
    inputs = await _option_inputs(root, "checkbox")
    targets = await _option_click_targets(root, "checkbox")
    total = len(inputs) if inputs else len(targets)
    if total <= 0:
        return False
    live_min_limit, live_max_limit = await _resolve_multi_select_limits(page, root, total)
    resolved_min_limit = min_limit if min_limit is not None else live_min_limit
    resolved_max_limit = max_limit if max_limit is not None else live_max_limit
    clicked = False
    for index in _positive_multiple_indexes_with_limits(
        weights,
        total,
        min_limit=resolved_min_limit,
        max_limit=resolved_max_limit,
    ):
        if index < len(inputs):
            clicked_now = await _click_element(page, inputs[index]) and await _is_checked(page, inputs[index])
            if not clicked_now:
                try:
                    clicked_now = bool(await page.evaluate("el => { el.click(); return !!el.checked; }", inputs[index]))
                except Exception:
                    clicked_now = False
            clicked = clicked_now or clicked
            continue
        if targets and index < len(targets):
            if await _click_element(page, targets[index]):
                refreshed_inputs = await _option_inputs(root, "checkbox")
                if index < len(refreshed_inputs) and await _is_checked(page, refreshed_inputs[index]):
                    clicked = True
    return clicked


async def _answer_text(
    root: Any,
    text_config: Any,
    text_probabilities: Any = None,
    *,
    entry_type: str = "text",
    blank_modes: Optional[list[Any]] = None,
    blank_int_ranges: Optional[list[Any]] = None,
) -> bool:
    inputs = await _text_inputs(root)
    if not inputs:
        return False
    values = resolve_runtime_text_values_from_config(
        text_config if isinstance(text_config, list) and text_config else [DEFAULT_FILL_TEXT],
        text_probabilities if isinstance(text_probabilities, list) else None,
        blank_count=len(inputs),
        entry_type=entry_type,
        blank_modes=blank_modes,
        blank_int_ranges=blank_int_ranges,
    )
    changed = False
    for index, input_element in enumerate(inputs):
        value = values[index] if index < len(values) else values[-1]
        try:
            await input_element.fill(str(value), timeout=3000)
            changed = True
        except Exception:
            try:
                await input_element.type(str(value), timeout=3000)
                changed = True
            except Exception:
                logging.info("Credamo 填空输入失败", exc_info=True)
    return changed


async def _answer_dropdown(page: Any, root: Any, weights: Any) -> bool:
    trigger = None
    for selector in (".pc-dropdown .el-input", ".pc-dropdown .el-select", ".el-input", ".el-select", ".el-input__inner"):
        try:
            trigger = await root.query_selector(selector)
        except Exception:
            trigger = None
        if trigger is not None:
            break
    try:
        value_input = await root.query_selector(".el-input__inner")
    except Exception:
        value_input = None
    if trigger is None or value_input is None:
        return False
    def _dropdown_value_selected(current_value: Any) -> bool:
        return bool(str(current_value or "").strip())
    try:
        await trigger.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    if not await _click_element(page, trigger):
        return False
    await sleep_or_stop(None, 0.12)
    options = page.locator(".el-select-dropdown__item")
    try:
        option_count = int(await options.count())
    except Exception:
        option_count = 0
    if option_count <= 0:
        try:
            option_count = max(1, len(await root.query_selector_all(".el-select-dropdown__item, option")))
        except Exception:
            option_count = 1
    probabilities = normalize_droplist_probs(weights, option_count)
    target_index = min(weighted_index(probabilities), option_count - 1)

    async def visible_dropdown_options() -> list[Any]:
        try:
            handles = await page.query_selector_all(".el-select-dropdown__item")
        except Exception:
            return []
        visible_items: list[Any] = []
        for handle in handles:
            try:
                box = await handle.bounding_box()
            except Exception:
                box = None
            if not box:
                continue
            if float(box.get("width") or 0) < 4 or float(box.get("height") or 0) < 4:
                continue
            visible_items.append(handle)
        return visible_items

    visible_options = await visible_dropdown_options()
    if visible_options:
        forced_option_texts = [await _element_text(page, item) for item in visible_options]
        forced_index = await _resolve_forced_choice_index(page, root, forced_option_texts)
        if forced_index is not None and forced_index < len(visible_options):
            target = visible_options[forced_index]
            if await _click_element(page, target):
                await sleep_or_stop(None, 0.12)
                current_value = await _input_value(page, value_input)
                if _dropdown_value_selected(current_value):
                    return True
        target = visible_options[min(target_index, len(visible_options) - 1)]
        if await _click_element(page, target):
            await sleep_or_stop(None, 0.12)
            current_value = await _input_value(page, value_input)
            if _dropdown_value_selected(current_value):
                return True

    try:
        await value_input.focus()
    except Exception:
        pass
    try:
        for _ in range(target_index + 1):
            await page.keyboard.press("ArrowDown")
        await page.keyboard.press("Enter")
        await sleep_or_stop(None, 0.12)
        current_value = await _input_value(page, value_input)
        if _dropdown_value_selected(current_value):
            return True
    except Exception:
        pass
    target = options.nth(target_index)
    try:
        await target.click(timeout=3000, force=True)
    except Exception:
        try:
            handle = await target.element_handle(timeout=1000)
            if handle is None:
                return False
            await page.evaluate("el => { el.click(); return true; }", handle)
        except Exception:
            return False
    current_value = await _input_value(page, value_input)
    return _dropdown_value_selected(current_value)


async def _answer_scale(page: Any, root: Any, weights: Any) -> bool:
    try:
        options = await root.query_selector_all(".scale .nps-item, .nps-item, .el-rate__item")
    except Exception:
        options = []
    if not options:
        return False
    probabilities = normalize_droplist_probs(weights, len(options))
    target_index = min(weighted_index(probabilities), len(options) - 1)
    if not await _click_element(page, options[target_index]):
        return False
    try:
        selected = await page.evaluate(
            "el => !!el.querySelector('.scale .nps-item.selected, .nps-item.selected')",
            root,
        )
    except Exception:
        selected = None
    if selected is None:
        return True
    return bool(selected)


async def _matrix_rows(root: Any) -> list[tuple[Any, list[Any]]]:
    row_selectors = ("tbody tr", ".matrix-row", ".el-table__row")
    rows: list[tuple[Any, list[Any]]] = []
    for selector in row_selectors:
        try:
            row_nodes = await root.query_selector_all(selector)
        except Exception:
            row_nodes = []
        for row in row_nodes:
            try:
                controls = await row.query_selector_all("input[type='radio'], [role='radio'], .el-radio, .el-radio__input")
            except Exception:
                controls = []
            if len(controls) >= 2:
                rows.append((row, controls))
        if rows:
            return rows
    return rows


async def _answer_matrix(page: Any, root: Any, weights: Any, start_index: int = 0) -> bool:
    del start_index
    rows = await _matrix_rows(root)
    if not rows:
        return False
    clicked = False
    for row_offset, (_row, controls) in enumerate(rows):
        if not controls:
            continue
        row_weights = weights
        if isinstance(weights, list) and weights and any(isinstance(item, (list, tuple)) for item in weights):
            source_index = min(row_offset, len(weights) - 1)
            row_weights = weights[source_index]
        probabilities = normalize_droplist_probs(row_weights, len(controls))
        target_index = min(weighted_index(probabilities), len(controls) - 1)
        target = controls[target_index]
        clicked_now = await _click_element(page, target)
        if not clicked_now:
            try:
                clicked_now = bool(await page.evaluate("el => { el.click(); return true; }", target))
            except Exception:
                clicked_now = False
        clicked = clicked_now or clicked
        await sleep_or_stop(None, random.uniform(0.03, 0.08))
    return clicked


async def _answer_order(page: Any, root: Any) -> bool:
    try:
        items = await root.query_selector_all(".rank-order .choice-row, .choice-row")
    except Exception:
        items = []
    if not items:
        return False
    order = list(range(len(items)))
    random.shuffle(order)
    clicked = False
    for index in order:
        clicked = await _click_element(page, items[index]) or clicked
        await sleep_or_stop(None, random.uniform(0.05, 0.12))
    return clicked


def _normalize_positive_indices(weights: Any, option_count: int) -> list[int]:
    return _positive_multiple_indexes_with_limits(weights, option_count)


def build_answer_action(
    *,
    root_index: int,
    question_num: int,
    entry_type: str,
    config_index: int,
    config: Any,
    question_meta: Any = None,
) -> Optional[AnswerAction]:
    kind = str(entry_type or "").strip()
    if kind == "single":
        raw_option_count = int(getattr(question_meta, "options", 0) or 0)
        if raw_option_count <= 0:
            return None
        option_count = max(1, raw_option_count)
        weights = config.single_prob[config_index] if config_index < len(config.single_prob) else -1
        selected_index = weighted_index(normalize_droplist_probs(weights, option_count))
        return AnswerAction(root_index=int(root_index), question_num=int(question_num), kind="single", selected_indices=(selected_index,))
    if kind == "multiple":
        raw_option_count = int(getattr(question_meta, "options", 0) or 0)
        if raw_option_count <= 0:
            return None
        option_count = max(1, raw_option_count)
        weights = config.multiple_prob[config_index] if config_index < len(config.multiple_prob) else []
        selected = _normalize_positive_indices(weights, option_count)
        if not selected:
            return None
        return AnswerAction(root_index=int(root_index), question_num=int(question_num), kind="multiple", selected_indices=tuple(selected))
    if kind in {"scale", "score"}:
        raw_option_count = int(getattr(question_meta, "options", 0) or 0)
        if raw_option_count <= 0:
            return None
        option_count = max(2, raw_option_count)
        weights = config.scale_prob[config_index] if config_index < len(config.scale_prob) else -1
        selected_index = weighted_index(normalize_droplist_probs(weights, option_count))
        return AnswerAction(root_index=int(root_index), question_num=int(question_num), kind="scale", selected_indices=(selected_index,))
    if kind == "matrix":
        row_count = max(1, int(getattr(question_meta, "rows", 1) or 1))
        raw_option_count = int(getattr(question_meta, "options", 0) or 0)
        if raw_option_count <= 0:
            return None
        option_count = max(2, raw_option_count)
        selected: list[int] = []
        for row_offset in range(row_count):
            matrix_index = config_index + row_offset
            weights = config.matrix_prob[matrix_index] if matrix_index < len(config.matrix_prob) else -1
            selected.append(weighted_index(normalize_droplist_probs(weights, option_count)))
        return AnswerAction(root_index=int(root_index), question_num=int(question_num), kind="matrix", matrix_indices=tuple(selected))
    if kind in {"text", "multi_text"}:
        text_config = config.texts[config_index] if config_index < len(config.texts) else [DEFAULT_FILL_TEXT]
        texts_prob = list(getattr(config, "texts_prob", []) or [])
        text_probabilities = texts_prob[config_index] if config_index < len(texts_prob) else [1.0]
        multi_text_blank_modes = list(getattr(config, "multi_text_blank_modes", []) or [])
        multi_text_blank_ranges = list(getattr(config, "multi_text_blank_int_ranges", []) or [])
        blank_count = max(1, int(getattr(question_meta, "text_inputs", 1) or 1))
        text_values = resolve_runtime_text_values_from_config(
            text_config,
            text_probabilities,
            blank_count=blank_count,
            entry_type=kind,
            blank_modes=multi_text_blank_modes[config_index] if config_index < len(multi_text_blank_modes) else [],
            blank_int_ranges=multi_text_blank_ranges[config_index] if config_index < len(multi_text_blank_ranges) else [],
        )
        return AnswerAction(
            root_index=int(root_index),
            question_num=int(question_num),
            kind="text" if kind == "text" else "multi_text",
            text_values=tuple(text_values),
        )
    return None


async def apply_answer_actions(page: Any, actions: list[AnswerAction]) -> BatchFillResult:
    normalized = [action for action in list(actions or []) if int(action.root_index) >= 0 and int(action.question_num or 0) > 0]
    if not normalized:
        return BatchFillResult()
    payload = [
        {
            "rootIndex": int(action.root_index),
            "questionNum": int(action.question_num),
            "kind": str(action.kind or ""),
            "selectedIndices": [int(item) for item in action.selected_indices],
            "matrixIndices": [int(item) for item in action.matrix_indices],
            "textValues": [str(item or "") for item in action.text_values],
        }
        for action in normalized
    ]
    try:
        raw_result = await page.evaluate(
            r"""(actions) => {
                const roots = Array.from(document.querySelectorAll('.answer-page .question')).filter((root) => {
                    const style = window.getComputedStyle(root);
                    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = root.getBoundingClientRect();
                    return rect.width >= 8 && rect.height >= 8;
                });
                const visible = (node, minWidth = 4, minHeight = 4) => {
                    if (!node) return false;
                    const style = window.getComputedStyle(node);
                    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = node.getBoundingClientRect();
                    return rect.width >= minWidth && rect.height >= minHeight;
                };
                const dispatch = (target, names = ['input', 'change', 'click']) => {
                    for (const name of names) {
                        try { target.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                    }
                };
                const setNativeValue = (target, value) => {
                    const nextValue = String(value ?? '');
                    try {
                        const proto = target.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement?.prototype : window.HTMLInputElement?.prototype;
                        const descriptor = proto ? Object.getOwnPropertyDescriptor(proto, 'value') : null;
                        if (descriptor && descriptor.set) descriptor.set.call(target, nextValue);
                        else target.value = nextValue;
                    } catch (e) {
                        try { target.value = nextValue; } catch (err) {}
                    }
                    try { target.setAttribute('value', nextValue); } catch (e) {}
                    dispatch(target, ['input', 'change', 'blur']);
                };
                const isTextInput = (el) => {
                    if (!el) return false;
                    const tag = String(el.tagName || '').toLowerCase();
                    if (tag === 'textarea') return true;
                    if (tag !== 'input') return false;
                    const type = String(el.getAttribute('type') || '').toLowerCase();
                    return !type || ['text', 'search', 'number', 'tel', 'email'].includes(type);
                };
                const clickOption = (root, selector, index) => {
                    const controls = Array.from(root.querySelectorAll(selector)).filter(visible);
                    const target = controls[index] || null;
                    if (!target) return false;
                    const candidates = [
                        target.closest('label'),
                        target.closest('.choice-row'),
                        target.closest('.choice'),
                        target.closest('.el-radio'),
                        target.closest('.el-checkbox'),
                        target.parentElement,
                        target,
                    ].filter(Boolean);
                    for (const node of candidates) {
                        try { node.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                        try { node.click(); } catch (e) {}
                        if (target.checked || target.getAttribute('aria-checked') === 'true') return true;
                    }
                    try { target.checked = true; } catch (e) {}
                    try { target.setAttribute('aria-checked', 'true'); } catch (e) {}
                    dispatch(target);
                    return !!target.checked || target.getAttribute('aria-checked') === 'true';
                };
                const applyText = (root, values) => {
                    const textValues = Array.isArray(values) && values.length ? values.map((item) => String(item ?? '')) : [''];
                    const inputs = Array.from(
                        root.querySelectorAll("textarea, input:not([readonly])[type='text'], input:not([readonly])[type='search'], input:not([readonly])[type='number'], input:not([readonly])[type='tel'], input:not([readonly])[type='email'], input:not([readonly]):not([type])")
                    ).filter(visible);
                    if (!inputs.length) return false;
                    let applied = 0;
                    inputs.forEach((target, index) => {
                        const value = textValues[index] ?? textValues[textValues.length - 1] ?? '';
                        try { target.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                        try { target.focus(); } catch (e) {}
                        setNativeValue(target, value);
                        if (String(target.value || '') === value) applied += 1;
                    });
                    return applied > 0 && applied >= Math.min(inputs.length, textValues.length);
                };
                const applyScale = (root, index) => {
                    const options = Array.from(root.querySelectorAll('.scale .nps-item, .nps-item, .el-rate__item')).filter(visible);
                    const target = options[index] || null;
                    if (!target) return false;
                    try { target.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                    try { target.click(); } catch (e) {}
                    try { target.classList.add('selected'); } catch (e) {}
                    return true;
                };
                const applyMatrix = (root, indices) => {
                    const rows = Array.from(root.querySelectorAll('tbody tr, .matrix-row, .el-table__row')).filter((row) => visible(row));
                    let answerableRows = rows.filter((row) => row.querySelectorAll("input[type='radio'], [role='radio'], .el-radio, .el-radio__input").length >= 2);
                    if (!answerableRows.length) return false;
                    let applied = 0;
                    indices.forEach((rawIndex, rowIndex) => {
                        const row = answerableRows[rowIndex];
                        const colIndex = Number(rawIndex);
                        if (!row || colIndex < 0) return;
                        const controls = Array.from(row.querySelectorAll("input[type='radio'], [role='radio'], .el-radio, .el-radio__input")).filter(visible);
                        const target = controls[colIndex] || null;
                        if (!target) return;
                        const candidates = [target.closest('label'), target.closest('.el-radio'), target.parentElement, target].filter(Boolean);
                        for (const node of candidates) {
                            try { node.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                            try { node.click(); } catch (e) {}
                            if (target.checked || target.getAttribute('aria-checked') === 'true' || target.classList.contains('is-checked')) break;
                        }
                        try { target.checked = true; } catch (e) {}
                        try { target.setAttribute('aria-checked', 'true'); } catch (e) {}
                        try { target.classList.add('is-checked'); } catch (e) {}
                        dispatch(target);
                        applied += 1;
                    });
                    return applied === indices.length;
                };
                const applied = [];
                const failed = [];
                for (const action of actions || []) {
                    const rootIndex = Number(action.rootIndex);
                    const questionNum = Number(action.questionNum || 0);
                    const root = roots[rootIndex] || null;
                    if (!root) {
                        failed.push(questionNum);
                        continue;
                    }
                    let ok = false;
                    try {
                        if (action.kind === 'single') {
                            ok = clickOption(root, "input[type='radio'], [role='radio']", Number((action.selectedIndices || [])[0] ?? -1));
                        } else if (action.kind === 'multiple') {
                            const selected = Array.isArray(action.selectedIndices) ? action.selectedIndices : [];
                            ok = selected.length > 0 && selected.every((index) => clickOption(root, "input[type='checkbox'], [role='checkbox']", Number(index)));
                        } else if (action.kind === 'scale') {
                            ok = applyScale(root, Number((action.selectedIndices || [])[0] ?? -1));
                        } else if (action.kind === 'matrix') {
                            ok = applyMatrix(root, action.matrixIndices || []);
                        } else if (action.kind === 'text' || action.kind === 'multi_text') {
                            ok = applyText(root, action.textValues);
                        }
                    } catch (e) {
                        ok = false;
                    }
                    if (ok) applied.push(questionNum);
                    else failed.push(questionNum);
                }
                return { applied, failed };
            }""",
            payload,
        ) or {}
    except Exception:
        return BatchFillResult(failed=tuple(int(action.question_num) for action in normalized))
    applied = tuple(int(item) for item in list(raw_result.get("applied") or []) if int(item or 0) > 0) if isinstance(raw_result, dict) else ()
    failed = tuple(int(item) for item in list(raw_result.get("failed") or []) if int(item or 0) > 0) if isinstance(raw_result, dict) else tuple(int(action.question_num) for action in normalized)
    return BatchFillResult(applied=applied, failed=failed)
