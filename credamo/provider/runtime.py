"""Credamo 见数问卷运行时作答实现。"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, List, Optional

from software.app.config import DEFAULT_FILL_TEXT
from software.core.modes.duration_control import simulate_answer_duration_delay
from software.core.questions.utils import (
    get_fill_text_from_config,
    normalize_droplist_probs,
    weighted_index,
)
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser import BrowserDriver


_CREDAMO_DYNAMIC_WAIT_TIMEOUT_MS = 20000
_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS = 0.5


def _page(driver: BrowserDriver) -> Any:
    return getattr(driver, "page")


def _abort_requested(stop_signal: Optional[threading.Event]) -> bool:
    return bool(stop_signal and stop_signal.is_set())


def _question_roots(page: Any) -> List[Any]:
    script = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const findRoot = (input) => {
    let current = input;
    for (let depth = 0; current && depth < 8; depth += 1) {
      if (/^Q\s*\d+\b/i.test(clean(current.innerText || ''))) return current;
      current = current.parentElement;
    }
    return input.closest('.answer-content, .question, [class*="question"], [class*="Question"], [class*="answer"]') || input.parentElement;
  };
  const roots = [];
  const seen = new Set();
  Array.from(document.querySelectorAll('input, textarea, [role="radio"], [role="checkbox"]')).forEach((input) => {
    if (!visible(input)) return;
    const root = findRoot(input);
    if (!root || seen.has(root)) return;
    seen.add(root);
    roots.push(root);
  });
  return roots;
}
"""
    roots = page.evaluate_handle(script)
    try:
        properties = roots.get_properties()
        return [prop.as_element() for prop in properties.values() if prop.as_element() is not None]
    finally:
        try:
            roots.dispose()
        except Exception:
            pass


def _wait_for_question_roots(
    page: Any,
    stop_signal: Optional[threading.Event],
    *,
    timeout_ms: int = _CREDAMO_DYNAMIC_WAIT_TIMEOUT_MS,
) -> List[Any]:
    deadline = time.monotonic() + max(0.0, timeout_ms / 1000)
    last_roots: List[Any] = []
    while not _abort_requested(stop_signal):
        try:
            last_roots = _question_roots(page)
        except Exception:
            logging.info("Credamo 等待题目加载时读取页面失败", exc_info=True)
            last_roots = []
        if last_roots:
            return last_roots
        if time.monotonic() >= deadline:
            return last_roots
        if stop_signal is not None:
            stop_signal.wait(_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS)
        else:
            time.sleep(_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS)
    return last_roots


def _click_element(page: Any, element: Any) -> bool:
    try:
        element.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    try:
        element.click(timeout=3000)
        return True
    except Exception:
        pass
    try:
        return bool(page.evaluate("el => { el.click(); return true; }", element))
    except Exception:
        return False


def _option_inputs(root: Any, kind: str) -> List[Any]:
    selector = f"input[type='{kind}'], [role='{kind}']"
    try:
        return root.query_selector_all(selector)
    except Exception:
        return []


def _text_inputs(root: Any) -> List[Any]:
    try:
        return root.query_selector_all("textarea, input[type='text'], input[type='number'], input[type='tel'], input[type='email'], input:not([type])")
    except Exception:
        return []


def _answer_single_like(page: Any, root: Any, weights: Any, option_count: int) -> bool:
    inputs = _option_inputs(root, "radio")
    if not inputs:
        return False
    probabilities = normalize_droplist_probs(weights, len(inputs))
    target_index = weighted_index(probabilities)
    target = inputs[min(target_index, len(inputs) - 1)]
    return _click_element(page, target)


def _positive_multiple_indexes(weights: Any, option_count: int) -> List[int]:
    count = max(0, int(option_count or 0))
    if count <= 0:
        return []
    if not isinstance(weights, list) or not weights:
        return [random.randrange(count)]
    normalized: List[float] = []
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


def _answer_multiple(page: Any, root: Any, weights: Any) -> bool:
    inputs = _option_inputs(root, "checkbox")
    if not inputs:
        return False
    clicked = False
    for index in _positive_multiple_indexes(weights, len(inputs)):
        if index < len(inputs):
            clicked = _click_element(page, inputs[index]) or clicked
    return clicked


def _answer_text(root: Any, text_config: Any) -> bool:
    inputs = _text_inputs(root)
    if not inputs:
        return False
    values = text_config if isinstance(text_config, list) and text_config else [DEFAULT_FILL_TEXT]
    changed = False
    for index, input_element in enumerate(inputs):
        value = get_fill_text_from_config(values, index) or DEFAULT_FILL_TEXT
        try:
            input_element.fill(str(value), timeout=3000)
            changed = True
        except Exception:
            try:
                input_element.type(str(value), timeout=3000)
                changed = True
            except Exception:
                logging.info("Credamo 填空输入失败", exc_info=True)
    return changed


def _click_submit_once(page: Any) -> bool:
    selectors = [
        "button:has-text('提交')",
        "button:has-text('完成')",
        "button:has-text('下一页')",
        "button:has-text('Next')",
        "button[type='submit']",
        ".btn-submit",
        ".submit-btn",
        "[class*='submit']",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() <= 0:
                continue
            locator.scroll_into_view_if_needed(timeout=1500)
            locator.click(timeout=3000)
            return True
        except Exception:
            continue
    try:
        return bool(
            page.evaluate(
                r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const nodes = Array.from(document.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]'));
  const target = nodes.find((node) => visible(node) && /提交|完成|下一页|submit|next/i.test(String(node.innerText || node.value || '')));
  if (!target) return false;
  target.click();
  return true;
}
"""
            )
        )
    except Exception:
        return False


def _click_submit(
    page: Any,
    stop_signal: Optional[threading.Event] = None,
    *,
    timeout_ms: int = _CREDAMO_DYNAMIC_WAIT_TIMEOUT_MS,
) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_ms / 1000)
    while not _abort_requested(stop_signal):
        if _click_submit_once(page):
            return True
        if time.monotonic() >= deadline:
            return False
        if stop_signal is not None:
            stop_signal.wait(_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS)
        else:
            time.sleep(_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS)
    return False


def brush_credamo(
    driver: BrowserDriver,
    config: ExecutionConfig,
    state: ExecutionState,
    *,
    stop_signal: Optional[threading.Event],
    thread_name: str,
    psycho_plan: Optional[Any] = None,
) -> bool:
    del psycho_plan
    active_stop = stop_signal or state.stop_event
    page = _page(driver)
    roots = _wait_for_question_roots(page, active_stop)
    total_steps = len(roots)
    try:
        state.update_thread_step(thread_name, 0, total_steps, status_text="答题中", running=True)
    except Exception:
        logging.info("初始化 Credamo 线程进度失败", exc_info=True)

    for index, root in enumerate(roots, start=1):
        if _abort_requested(active_stop):
            try:
                state.update_thread_status(thread_name, "已中断", running=False)
            except Exception:
                pass
            return False
        try:
            state.update_thread_step(thread_name, index, total_steps, status_text="答题中", running=True)
        except Exception:
            logging.info("更新 Credamo 线程进度失败", exc_info=True)
        config_entry = config.question_config_index_map.get(index)
        if not config_entry:
            continue
        entry_type, config_index = config_entry
        if entry_type in {"single", "scale", "score", "dropdown"}:
            source = {
                "single": config.single_prob,
                "scale": config.scale_prob,
                "score": config.scale_prob,
                "dropdown": config.droplist_prob,
            }.get(entry_type, [])
            weights = source[config_index] if config_index < len(source) else -1
            _answer_single_like(page, root, weights, 0)
        elif entry_type == "multiple":
            weights = config.multiple_prob[config_index] if config_index < len(config.multiple_prob) else []
            _answer_multiple(page, root, weights)
        elif entry_type in {"text", "multi_text"}:
            text_config = config.texts[config_index] if config_index < len(config.texts) else [DEFAULT_FILL_TEXT]
            _answer_text(root, text_config)
        else:
            logging.info("Credamo 第%s题暂未接入题型：%s", index, entry_type)
        time.sleep(random.uniform(0.08, 0.22))

    if simulate_answer_duration_delay(active_stop, config.answer_duration_range_seconds):
        return False
    try:
        state.update_thread_status(thread_name, "提交中", running=True)
    except Exception:
        logging.info("更新 Credamo 线程状态失败：提交中", exc_info=True)
    if not _click_submit(page, active_stop):
        raise RuntimeError("Credamo 提交按钮未找到")
    try:
        state.update_thread_status(thread_name, "等待结果确认", running=True)
    except Exception:
        logging.info("更新 Credamo 线程状态失败：等待结果确认", exc_info=True)
    return True
