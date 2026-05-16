"""Credamo 见数运行时页面识别、导航与通用 DOM 操作。"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

from software.core.engine.async_wait import sleep_or_stop
from software.network.browser.runtime_async import BrowserDriver, BrowserElement


_CREDAMO_DYNAMIC_WAIT_TIMEOUT_MS = 6000
_CREDAMO_DYNAMIC_WAIT_POLL_SECONDS = 0.15
_CREDAMO_PAGE_TRANSITION_TIMEOUT_MS = 5000
_CREDAMO_DYNAMIC_REVEAL_TIMEOUT_MS = 800
_CREDAMO_LOADING_SHELL_EXTRA_WAIT_TIMEOUT_MS = 4000
_QUESTION_NUMBER_RE = re.compile(r"\d+")
_NEXT_BUTTON_MARKERS = ("下一页", "next", "继续")
_SUBMIT_BUTTON_MARKERS = ("提交", "完成", "交卷", "submit", "finish", "done")


async def _page(driver: BrowserDriver) -> Any:
    return await driver.page()


def _abort_requested(stop_signal: Any) -> bool:
    if stop_signal is None:
        return False
    checker = getattr(stop_signal, "is_set", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    return False


async def _question_roots(page: Any) -> list[BrowserElement]:
    try:
        handles = await page.eval_on_selector_all(
            ".answer-page .question",
            r"""
            (roots) => {
              const visible = (el, minWidth = 8, minHeight = 8) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
                const rect = el.getBoundingClientRect();
                return rect.width >= minWidth && rect.height >= minHeight;
              };
              return roots
                .filter((root) => visible(root))
                .map((_root, index) => index);
            }
            """,
        )
    except Exception:
        handles = None
    if isinstance(handles, list):
        try:
            visible_roots = await page.query_selector_all(".answer-page .question")
        except Exception:
            return []
        resolved: list[BrowserElement] = []
        for index in handles:
            try:
                numeric_index = int(index)
            except Exception:
                continue
            if 0 <= numeric_index < len(visible_roots):
                resolved.append(visible_roots[numeric_index])
        if resolved:
            return resolved
    try:
        return await page.query_selector_all(".answer-page .question")
    except Exception:
        return []


async def _collect_question_root_snapshot(page: Any) -> list[dict[str, Any]]:
    script = r"""
() => {
  const visible = (el, minWidth = 8, minHeight = 8) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = el.getBoundingClientRect();
    return rect.width >= minWidth && rect.height >= minHeight;
  };
  const normalize = (text) => String(text || '').replace(/\s+/g, ' ').trim();
  return Array.from(document.querySelectorAll('.answer-page .question')).map((root, index) => {
    const titleNode = root.querySelector('.question-title, .qstTitle, .title, [class*="title"]');
    const questionNo = root.querySelector('.question-title .qstNo');
    return {
      index,
      id: String(root.getAttribute('id') || root.getAttribute('data-id') || '').trim(),
      visible: visible(root),
      title: normalize(titleNode?.innerText || titleNode?.textContent || ''),
      rawNumber: normalize(questionNo?.textContent || ''),
      text: normalize(root.innerText || root.textContent || '').slice(0, 240),
    };
  }).filter((item) => item.visible);
}
"""
    try:
        payload = await page.evaluate(script) or []
    except Exception:
        return []
    snapshot: list[dict[str, Any]] = []
    if not isinstance(payload, list):
        return snapshot
    for item in payload:
        if not isinstance(item, dict):
            continue
        snapshot.append(
            {
                "index": int(item.get("index") or 0),
                "id": str(item.get("id") or "").strip(),
                "visible": bool(item.get("visible")),
                "title": str(item.get("title") or "").strip(),
                "raw_number": str(item.get("rawNumber") or "").strip(),
                "text": str(item.get("text") or "").strip(),
            }
        )
    return snapshot


async def _page_loading_snapshot(page: Any) -> tuple[str, str]:
    try:
        title = str(await page.title() or "").strip()
    except Exception:
        title = ""
    try:
        body_text = str(await page.locator("body").inner_text(timeout=1000) or "").strip()
    except Exception:
        body_text = ""
    return title, re.sub(r"\s+", " ", body_text).strip()


def _looks_like_loading_shell(title: str, body_text: str) -> bool:
    normalized_title = str(title or "").strip()
    normalized_body = str(body_text or "").strip()
    if not normalized_body:
        return normalized_title in {"", "答卷"}
    compact_body = normalized_body.replace(" ", "")
    if compact_body in {"载入中", "载入中...", "载入中..", "loading", "loading..."}:
        return True
    if normalized_title == "答卷" and len(compact_body) <= 16:
        return True
    return False


async def _wait_for_question_roots(
    page: Any,
    stop_signal: Any,
    *,
    timeout_ms: int = _CREDAMO_DYNAMIC_WAIT_TIMEOUT_MS,
    loading_shell_extra_timeout_ms: int = _CREDAMO_LOADING_SHELL_EXTRA_WAIT_TIMEOUT_MS,
) -> list[BrowserElement]:
    deadline = time.monotonic() + max(0.0, timeout_ms / 1000)
    last_roots: list[BrowserElement] = []
    loading_shell_retry_used = False
    while not _abort_requested(stop_signal):
        try:
            last_roots = await _question_roots(page)
        except Exception:
            logging.info("Credamo 等待题目加载时读取页面失败", exc_info=True)
            last_roots = []
        if last_roots:
            return last_roots
        if time.monotonic() >= deadline:
            title, body_text = await _page_loading_snapshot(page)
            if (
                not loading_shell_retry_used
                and loading_shell_extra_timeout_ms > 0
                and _looks_like_loading_shell(title, body_text)
            ):
                loading_shell_retry_used = True
                deadline = time.monotonic() + max(0.0, loading_shell_extra_timeout_ms / 1000)
                logging.warning(
                    "Credamo 页面仍在载入壳页，延长等待题目：title=%s body=%s",
                    title or "<empty>",
                    (body_text[:80] or "<empty>"),
                )
                continue
            logging.warning(
                "Credamo 等待题目超时：title=%s body=%s",
                title or "<empty>",
                (body_text[:120] or "<empty>"),
            )
            return last_roots
        await sleep_or_stop(stop_signal, _CREDAMO_DYNAMIC_WAIT_POLL_SECONDS)
    return last_roots


async def _root_text(page: Any, root: BrowserElement) -> str:
    try:
        return str(await page.evaluate("el => (el.innerText || '').replace(/\\s+/g, ' ').trim()", root) or "")
    except Exception:
        return ""


async def _question_number_from_root(page: Any, root: BrowserElement, fallback_num: int) -> int:
    try:
        raw = str(await page.evaluate("el => (el.querySelector('.question-title .qstNo')?.textContent || '')", root) or "")
    except Exception:
        raw = ""
    match = _QUESTION_NUMBER_RE.search(raw)
    if match:
        try:
            return max(1, int(match.group(0)))
        except Exception:
            pass
    return max(1, int(fallback_num or 1))


async def _question_kind_from_root(page: Any, root: BrowserElement) -> str:
    script = r"""
(el) => {
  const visible = (node, minWidth = 4, minHeight = 4) => {
    if (!node) return false;
    const style = window.getComputedStyle(node);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = node.getBoundingClientRect();
    return rect.width >= minWidth && rect.height >= minHeight;
  };
  const editableInputs = Array.from(
    el.querySelectorAll(
      'textarea, input:not([readonly])[type="text"], input:not([readonly])[type="search"], input:not([readonly])[type="number"], input:not([readonly])[type="tel"], input:not([readonly])[type="email"], input:not([readonly]):not([type])'
    )
  ).filter((node) => visible(node));
  if (el.querySelector('.multi-choice, input[type="checkbox"], [role="checkbox"]')) return 'multiple';
  if (el.querySelector('.pc-dropdown, .el-select')) return 'dropdown';
  if (el.querySelector('.scale, .nps-item, .el-rate__item')) return 'scale';
  if (el.querySelector('.rank-order')) return 'order';
  if (editableInputs.length > 1) return 'multi_text';
  if (editableInputs.length > 0) return 'text';
  if (el.querySelector('.single-choice, input[type="radio"], [role="radio"]')) return 'single';
  return '';
}
"""
    try:
        return str(await page.evaluate(script, root) or "").strip().lower()
    except Exception:
        return ""


async def _question_signature(page: Any) -> tuple[tuple[str, str], ...]:
    signature: list[tuple[str, str]] = []
    for root in await _question_roots(page):
        try:
            question_id = str(await root.get_attribute("id") or await root.get_attribute("data-id") or "")
        except Exception:
            question_id = ""
        signature.append((question_id, await _root_text(page, root)))
    return tuple(signature)


async def _is_answerable_root(page: Any, root: BrowserElement) -> bool:
    kind = await _question_kind_from_root(page, root)
    if kind in {"single", "multiple", "dropdown", "scale", "order", "matrix", "text", "multi_text"}:
        return True
    try:
        option_like_count = int(
            await page.evaluate(
                r"""
                (el) => {
                  const selectors = [
                    '.choice-text',
                    '.single-choice',
                    '.multi-choice',
                    '.pc-dropdown',
                    '.el-select',
                    '.scale',
                    '.nps-item',
                    '.el-rate__item',
                    '.rank-order',
                    'input[type="radio"]',
                    'input[type="checkbox"]',
                    '[role="radio"]',
                    '[role="checkbox"]'
                  ];
                  return selectors.reduce((total, selector) => total + el.querySelectorAll(selector).length, 0);
                }
                """,
                root,
            )
            or 0
        )
    except Exception:
        option_like_count = 0
    if option_like_count > 0:
        return True
    try:
        text_input_count = len(await _text_inputs(root))
    except Exception:
        text_input_count = 0
    return text_input_count > 0


async def _question_answer_state(page: Any, root: BrowserElement, *, kind: str = "") -> Optional[bool]:
    resolved_kind = str(kind or "").strip().lower()
    if not resolved_kind:
        resolved_kind = await _question_kind_from_root(page, root)
    script = r"""
([el, kind]) => {
  const visible = (node, minWidth = 4, minHeight = 4) => {
    if (!node) return false;
    const style = window.getComputedStyle(node);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = node.getBoundingClientRect();
    return rect.width >= minWidth && rect.height >= minHeight;
  };
  const checkedCount = el.querySelectorAll(
    "input[type='radio']:checked, input[type='checkbox']:checked, " +
    "[role='radio'][aria-checked='true'], [role='checkbox'][aria-checked='true']"
  ).length;
  const textInputs = Array.from(
    el.querySelectorAll(
      "textarea, input:not([readonly])[type='text'], input:not([readonly])[type='search'], " +
      "input:not([readonly])[type='number'], input:not([readonly])[type='tel'], " +
      "input:not([readonly])[type='email'], input:not([readonly]):not([type])"
    )
  ).filter((node) => visible(node));
  const filledTextInputs = textInputs.filter((node) => String(node.value || '').trim()).length;
  const dropdownInputs = Array.from(
    el.querySelectorAll(".pc-dropdown .el-input__inner, .el-select .el-input__inner, .el-input__inner")
  ).filter((node) => visible(node));
  const filledDropdownInputs = dropdownInputs.filter((node) => String(node.value || '').trim()).length;
  const scaleSelectedCount = el.querySelectorAll(".scale .nps-item.selected, .nps-item.selected").length;
  const hasVisibleError = (() => {
    if (el.classList.contains('error')) return true;
    const nodes = el.querySelectorAll('.question-error, .el-form-item__error');
    return Array.from(nodes).some((node) => visible(node, 1, 1) && String(node.innerText || node.textContent || '').trim());
  })();
  if (hasVisibleError) return 'unanswered';
  if (kind === 'scale') return scaleSelectedCount > 0 ? 'answered' : 'unanswered';
  if (kind === 'single') return checkedCount > 0 ? 'answered' : 'unanswered';
  if (kind === 'multiple') return checkedCount > 0 ? 'answered' : 'unanswered';
  if (kind === 'dropdown') return filledDropdownInputs > 0 ? 'answered' : 'unanswered';
  if (kind === 'text') return textInputs.length > 0 && filledTextInputs > 0 ? 'answered' : 'unanswered';
  if (kind === 'multi_text') return textInputs.length > 0 && filledTextInputs === textInputs.length ? 'answered' : 'unanswered';
  if (kind === 'matrix') {
    const rows = Array.from(el.querySelectorAll('tbody tr, .matrix-row, .el-table__row')).filter((row) => visible(row));
    const answerableRows = rows
      .map((row) => {
        const controls = row.querySelectorAll(
          "input[type='radio'], [role='radio'], .el-radio, .el-radio__input"
        );
        return controls.length >= 2 ? row : null;
      })
      .filter(Boolean);
    if (!answerableRows.length) return checkedCount > 0 ? 'answered' : 'unanswered';
    const allRowsAnswered = answerableRows.every((row) => {
      return row.querySelector(
        "input[type='radio']:checked, [role='radio'][aria-checked='true'], .is-checked input[type='radio']"
      );
    });
    return allRowsAnswered ? 'answered' : 'unanswered';
  }
  if (scaleSelectedCount > 0 || checkedCount > 0 || filledDropdownInputs > 0 || filledTextInputs > 0) {
    return 'answered';
  }
  if (kind === 'order') return 'unknown';
  return 'unknown';
}
"""
    try:
        state = str(await page.evaluate(script, [root, resolved_kind]) or "").strip().lower()
    except Exception:
        return None
    if state == "answered":
        return True
    if state == "unanswered":
        return False
    return None


async def _has_answerable_question_roots(page: Any, roots: list[BrowserElement]) -> bool:
    for root in roots:
        if await _is_answerable_root(page, root):
            return True
    return False


async def _runtime_question_key(page: Any, root: BrowserElement, question_num: int) -> str:
    try:
        question_id = str(await root.get_attribute("id") or await root.get_attribute("data-id") or "").strip()
    except Exception:
        question_id = ""
    if question_id:
        return f"id:{question_id}"
    return f"num:{question_num}|text:{(await _root_text(page, root))[:120]}"


async def _unanswered_question_roots(
    page: Any,
    roots: list[BrowserElement],
    answered_keys: set[str],
    *,
    fallback_start: int = 0,
) -> list[tuple[BrowserElement, int, str]]:
    pending: list[tuple[BrowserElement, int, str]] = []
    for local_index, root in enumerate(roots, start=1):
        if not await _is_answerable_root(page, root):
            continue
        question_kind = await _question_kind_from_root(page, root)
        question_num = await _question_number_from_root(page, root, fallback_start + local_index)
        key = await _runtime_question_key(page, root, question_num)
        answer_state = await _question_answer_state(page, root, kind=question_kind)
        if answer_state is True:
            continue
        if key in answered_keys and answer_state is not False:
            continue
        pending.append((root, question_num, key))
    return pending


async def _wait_for_dynamic_question_roots(
    page: Any,
    answered_keys: set[str],
    stop_signal: Any,
    *,
    timeout_ms: int = _CREDAMO_DYNAMIC_REVEAL_TIMEOUT_MS,
    fallback_start: int = 0,
) -> list[BrowserElement]:
    deadline = time.monotonic() + max(0.0, timeout_ms / 1000)
    latest_roots: list[BrowserElement] = []
    while not _abort_requested(stop_signal):
        try:
            latest_roots = await _question_roots(page)
        except Exception:
            logging.info("Credamo 等待动态题目显示时读取页面失败", exc_info=True)
            latest_roots = []
        if await _unanswered_question_roots(page, latest_roots, answered_keys, fallback_start=fallback_start):
            return latest_roots
        if time.monotonic() >= deadline:
            return latest_roots
        await sleep_or_stop(stop_signal, _CREDAMO_DYNAMIC_WAIT_POLL_SECONDS)
    return latest_roots


async def _click_element(page: Any, element: Any) -> bool:
    try:
        await element.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    try:
        await element.click(timeout=3000)
        return True
    except Exception:
        pass
    try:
        return bool(await page.evaluate("el => { el.click(); return true; }", element))
    except Exception:
        return False


async def _is_checked(page: Any, element: Any) -> bool:
    try:
        return bool(await page.evaluate("el => !!el.checked", element))
    except Exception:
        return False


async def _input_value(page: Any, element: Any) -> str:
    try:
        return str(await page.evaluate("el => String(el.value || '')", element) or "")
    except Exception:
        return ""


async def _option_inputs(root: Any, kind: str) -> list[Any]:
    selector = f"input[type='{kind}'], [role='{kind}']"
    try:
        return await root.query_selector_all(selector)
    except Exception:
        return []


async def _option_click_targets(root: Any, kind: str) -> list[Any]:
    selectors = {
        "radio": ".single-choice .choice-row, .single-choice .choice, .choice-row, .choice",
        "checkbox": ".multi-choice .choice-row, .multi-choice .choice, .choice-row, .choice",
    }
    selector = selectors.get(kind, "")
    if not selector:
        return []
    try:
        return await root.query_selector_all(selector)
    except Exception:
        return []


async def _text_inputs(root: Any) -> list[Any]:
    try:
        return await root.query_selector_all(
            "textarea, input:not([readonly])[type='text'], input:not([readonly])[type='search'], "
            "input:not([readonly])[type='number'], input:not([readonly])[type='tel'], "
            "input:not([readonly])[type='email'], input:not([readonly]):not([type])"
        )
    except Exception:
        return []


def _normalize_runtime_text(value: Any) -> str:
    try:
        text = str(value or "").strip()
    except Exception:
        return ""
    return re.sub(r"\s+", " ", text)


async def _element_text(page: Any, element: Any) -> str:
    readers = (
        lambda: element.inner_text(timeout=500),
        lambda: element.text_content(timeout=500),
        lambda: element.get_attribute("value"),
        lambda: page.evaluate("el => (el.innerText || el.textContent || el.value || '').trim()", element),
    )
    for reader in readers:
        try:
            value = reader()
            if hasattr(value, "__await__"):
                value = await value
            text = _normalize_runtime_text(value)
        except Exception:
            text = ""
        if text:
            return text
    return ""


async def _question_title_text(page: Any, root: Any) -> str:
    for selector in (".question-title", ".qstTitle", ".title", "[class*='title']"):
        try:
            title_node = await root.query_selector(selector)
        except Exception:
            title_node = None
        if title_node is None:
            continue
        text = await _element_text(page, title_node)
        if text:
            return text
    return await _root_text(page, root)


async def _locator_is_visible(locator: Any) -> bool:
    try:
        return bool(await locator.is_visible(timeout=300))
    except Exception:
        return False


async def _navigation_action(page: Any) -> Optional[str]:
    locator = page.locator("button, a, [role='button'], input[type='button'], input[type='submit']")
    try:
        count = int(await locator.count())
    except Exception:
        count = 0
    found_next = False
    for index in range(count):
        item = locator.nth(index)
        if not await _locator_is_visible(item):
            continue
        try:
            text = str(await item.text_content(timeout=500) or "").strip()
        except Exception:
            text = ""
        if not text:
            try:
                text = str(await item.get_attribute("value") or "").strip()
            except Exception:
                text = ""
        lowered = text.casefold()
        if any(marker in lowered for marker in _SUBMIT_BUTTON_MARKERS):
            return "submit"
        if any(marker in lowered for marker in _NEXT_BUTTON_MARKERS):
            found_next = True
    return "next" if found_next else None


async def _click_navigation(page: Any, action: str) -> bool:
    primary_button = page.locator("#credamo-submit-btn").first
    try:
        primary_count = int(await primary_button.count())
    except Exception:
        primary_count = 0
    if primary_count > 0 and await _locator_is_visible(primary_button):
        try:
            primary_text = str(await primary_button.text_content(timeout=500) or "").strip()
        except Exception:
            primary_text = ""
        if not primary_text:
            try:
                primary_text = str(await primary_button.get_attribute("value") or "").strip()
            except Exception:
                primary_text = ""
        lowered_primary = primary_text.casefold()
        targets = _NEXT_BUTTON_MARKERS if action == "next" else _SUBMIT_BUTTON_MARKERS
        if any(marker in lowered_primary for marker in targets):
            try:
                await primary_button.click(timeout=3000)
                return True
            except Exception:
                try:
                    handle = await primary_button.element_handle(timeout=1000)
                    if handle is not None and bool(await page.evaluate("el => { el.click(); return true; }", handle)):
                        return True
                except Exception:
                    pass

    targets = _NEXT_BUTTON_MARKERS if action == "next" else _SUBMIT_BUTTON_MARKERS
    locator = page.locator("button, a, [role='button'], input[type='button'], input[type='submit']")
    try:
        count = int(await locator.count())
    except Exception:
        count = 0
    for index in range(count):
        item = locator.nth(index)
        if not await _locator_is_visible(item):
            continue
        try:
            text = str(await item.text_content(timeout=500) or "").strip()
        except Exception:
            text = ""
        if not text:
            try:
                text = str(await item.get_attribute("value") or "").strip()
            except Exception:
                text = ""
        lowered = text.casefold()
        if not any(marker in lowered for marker in targets):
            continue
        try:
            await item.scroll_into_view_if_needed(timeout=1500)
        except Exception:
            pass
        try:
            await item.click(timeout=3000)
            return True
        except Exception:
            try:
                handle = await item.element_handle(timeout=1000)
                if handle is not None and bool(await page.evaluate("el => { el.click(); return true; }", handle)):
                    return True
            except Exception:
                continue
    return False


async def _wait_for_page_change(
    page: Any,
    previous_signature: tuple[tuple[str, str], ...],
    stop_signal: Any,
    *,
    timeout_ms: int = _CREDAMO_PAGE_TRANSITION_TIMEOUT_MS,
) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_ms / 1000)
    while not _abort_requested(stop_signal):
        current_signature = await _question_signature(page)
        if current_signature and current_signature != previous_signature:
            return True
        if time.monotonic() >= deadline:
            return False
        await sleep_or_stop(stop_signal, _CREDAMO_DYNAMIC_WAIT_POLL_SECONDS)
    return False


async def _click_submit_once(page: Any) -> bool:
    return await _click_navigation(page, "submit")


async def _click_submit(
    page: Any,
    stop_signal: Any = None,
    *,
    timeout_ms: int = _CREDAMO_DYNAMIC_WAIT_TIMEOUT_MS,
) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_ms / 1000)
    while not _abort_requested(stop_signal):
        if await _click_submit_once(page):
            return True
        if time.monotonic() >= deadline:
            return False
        await sleep_or_stop(stop_signal, _CREDAMO_DYNAMIC_WAIT_POLL_SECONDS)
    return False
