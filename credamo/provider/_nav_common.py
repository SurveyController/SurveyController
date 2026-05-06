"""Credamo 导航按钮检测与点击的公共逻辑，供 parser 和 runtime_dom 共用。"""

from __future__ import annotations

from typing import Any, Callable, Optional

_NEXT_BUTTON_MARKERS = ("下一页", "next", "继续")
_SUBMIT_BUTTON_MARKERS = ("提交", "完成", "交卷", "submit", "finish", "done")


def _button_text(item: Any, text_fn: Callable[[Any], str], attr_fn: Callable[[Any], str]) -> str:
    text = text_fn(item)
    if not text:
        text = attr_fn(item)
    return text


def _detect_navigation_action(
    page: Any,
    *,
    locator_fn: Callable[[str], Any],
    count_fn: Callable[[Any], int],
    visible_fn: Callable[[Any], bool],
    text_fn: Callable[[Any], str],
    attr_fn: Callable[[Any], str],
) -> Optional[str]:
    locator = locator_fn("button, a, [role='button'], input[type='button'], input[type='submit']")
    count = count_fn(locator)
    found_next = False
    for index in range(count):
        item = locator.nth(index)
        if not visible_fn(item):
            continue
        text = _button_text(item, text_fn, attr_fn).casefold()
        if any(marker in text for marker in _SUBMIT_BUTTON_MARKERS):
            return "submit"
        if any(marker in text for marker in _NEXT_BUTTON_MARKERS):
            found_next = True
    return "next" if found_next else None


def _click_navigation_impl(
    page: Any,
    action: str,
    *,
    locator_fn: Callable[[str], Any],
    count_fn: Callable[[Any], int],
    visible_fn: Callable[[Any], bool],
    text_fn: Callable[[Any], str],
    attr_fn: Callable[[Any], str],
    scroll_fn: Optional[Callable[[Any], None]] = None,
) -> bool:
    # 优先尝试 #credamo-submit-btn
    primary_button = locator_fn("#credamo-submit-btn").first
    if count_fn(primary_button) > 0 and visible_fn(primary_button):
        primary_text = _button_text(primary_button, text_fn, attr_fn).casefold()
        targets = _NEXT_BUTTON_MARKERS if action == "next" else _SUBMIT_BUTTON_MARKERS
        if any(marker in primary_text for marker in targets):
            try:
                primary_button.click(timeout=3000)
                return True
            except Exception:
                try:
                    handle = primary_button.element_handle(timeout=1000)
                    if handle is not None and bool(page.evaluate("el => { el.click(); return true; }", handle)):
                        return True
                except Exception:
                    pass

    # 回退到通用按钮扫描
    targets = _NEXT_BUTTON_MARKERS if action == "next" else _SUBMIT_BUTTON_MARKERS
    locator = locator_fn("button, a, [role='button'], input[type='button'], input[type='submit']")
    count = count_fn(locator)
    for index in range(count):
        item = locator.nth(index)
        if not visible_fn(item):
            continue
        text = _button_text(item, text_fn, attr_fn).casefold()
        if not any(marker in text for marker in targets):
            continue
        if scroll_fn is not None:
            try:
                scroll_fn(item)
            except Exception:
                pass
        try:
            item.click(timeout=3000)
            return True
        except Exception:
            try:
                handle = item.element_handle(timeout=1000)
                if handle is not None and bool(page.evaluate("el => { el.click(); return true; }", handle)):
                    return True
            except Exception:
                continue
    return False
