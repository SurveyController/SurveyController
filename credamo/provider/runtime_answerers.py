"""Credamo 见数运行时各题型作答实现。"""

from __future__ import annotations

import logging
import random
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
    previous_value = await _input_value(page, value_input)
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
                if current_value and current_value != previous_value:
                    return True
        target = visible_options[min(target_index, len(visible_options) - 1)]
        if await _click_element(page, target):
            await sleep_or_stop(None, 0.12)
            current_value = await _input_value(page, value_input)
            if current_value and current_value != previous_value:
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
        if current_value and current_value != previous_value:
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
    return bool(current_value and current_value != previous_value)


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
