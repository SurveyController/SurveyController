"""页面导航 - 翻页、跳转与开屏处理。"""

from __future__ import annotations

import asyncio
from typing import Any

from software.core.engine.async_wait import sleep_or_stop
from software.network.browser.runtime_async import BrowserDriver

from .runtime_interactions import _click_js, _page, _resolve_current_page_number, _wait_for_page_number_change

_START_ACTION_TEXTS = (
    "开始作答",
    "开始答题",
    "开始填写",
    "Start answering",
    "Start survey",
    "Start questionnaire",
    "Begin answering",
    "Begin survey",
    "Begin questionnaire",
)
_RESUME_DIALOG_MARKERS = (
    "继续上次作答",
    "继续上次填写",
    "继续填写",
    "重新填写",
    "重新作答",
    "Continue previous answer",
    "Continue previous answers",
    "Continue answering",
    "Continue survey",
    "Resume answering",
    "Resume survey",
    "Start over",
    "Start again",
    "Restart survey",
)
_RESUME_ACTION_TEXTS = (
    "取消",
    "重新填写",
    "重新作答",
    "重新开始",
    "Start over",
    "Start again",
    "Restart",
    "Restart survey",
    "Cancel",
)
_NEXT_ACTION_TEXTS = ("下一页", "下一步", "下一题", "下一")


async def _element_text(target: Any) -> str:
    try:
        return str(await target.inner_text() or "").replace(" ", "").strip()
    except Exception:
        return ""


async def _body_text(driver: BrowserDriver) -> str:
    script = "return String(document.body?.innerText || '').replace(/\\s+/g, ' ').trim();"
    try:
        return str(await driver.execute_script(script) or "").strip()
    except Exception:
        return ""


def _contains_any(text: str, candidates: tuple[str, ...]) -> bool:
    normalized = str(text or "").replace(" ", "").strip()
    if not normalized:
        return False
    return any(str(candidate or "").replace(" ", "").strip() in normalized for candidate in candidates)


async def _page_contains_any_text(driver: BrowserDriver, candidates: tuple[str, ...]) -> bool:
    body_text = await _body_text(driver)
    return _contains_any(body_text, candidates)


async def try_click_start_answer_button(
    driver: BrowserDriver,
    *,
    timeout: float = 1.0,
    stop_signal: Any = None,
) -> bool:
    page = await _page(driver)
    selectors = (
        "#slideChunk",
        "#CoverStartGroup #slideChunk",
        "#CoverStartGroup .slideChunkWord",
        ".slideChunkWord",
    )
    text_selectors = ("a", "button", "div", "span", "[role='button']", "input[type='button']", "input[type='submit']")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.1, float(timeout or 0.0))
    while loop.time() < deadline:
        if stop_signal is not None and getattr(stop_signal, "is_set", lambda: False)():
            return False
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() <= 0:
                    continue
                await locator.scroll_into_view_if_needed(timeout=1200)
                try:
                    await locator.click(timeout=1200)
                except Exception:
                    try:
                        await locator.click(timeout=1200, force=True)
                    except Exception:
                        if not await _click_js(driver, selector):
                            continue
                await sleep_or_stop(stop_signal, 0.15)
                return True
            except Exception:
                continue
        if not await _page_contains_any_text(driver, _START_ACTION_TEXTS):
            if await sleep_or_stop(stop_signal, 0.15):
                return False
            continue
        for selector in text_selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
            except Exception:
                continue
            for index in range(count):
                target = locator.nth(index)
                try:
                    if not await target.is_visible():
                        continue
                except Exception:
                    continue
                text = await _element_text(target)
                if not text or not _contains_any(text, _START_ACTION_TEXTS):
                    continue
                try:
                    await target.scroll_into_view_if_needed(timeout=1200)
                    await target.click(timeout=1200)
                except Exception:
                    try:
                        await target.click(timeout=1200, force=True)
                    except Exception:
                        continue
                await sleep_or_stop(stop_signal, 0.15)
                return True
        try:
            triggered = bool(
                await driver.execute_script(
                    """
                    if (typeof initContentShow === 'function') {
                        initContentShow();
                        return true;
                    }
                    return false;
                    """
                )
            )
        except Exception:
            triggered = False
        if triggered:
            await sleep_or_stop(stop_signal, 0.15)
            return True
        if await sleep_or_stop(stop_signal, 0.15):
            return False
    return False


async def dismiss_resume_dialog_if_present(
    driver: BrowserDriver,
    *,
    timeout: float = 1.0,
    stop_signal: Any = None,
) -> bool:
    page = await _page(driver)
    specific_selectors = (
        "a.layui-layer-btn1",
        "#layui-layer1 .layui-layer-btn a",
        ".layui-layer .layui-layer-btn a",
    )
    selectors = (
        "button",
        "a",
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.1, float(timeout or 0.0))
    while loop.time() < deadline:
        if stop_signal is not None and getattr(stop_signal, "is_set", lambda: False)():
            return False
        dialog_visible = await _page_contains_any_text(driver, _RESUME_DIALOG_MARKERS)
        selectors_to_scan = specific_selectors if not dialog_visible else (specific_selectors + selectors)
        for selector in selectors_to_scan:
            try:
                locator = page.locator(selector)
                count = await locator.count()
            except Exception:
                continue
            for index in range(count):
                target = locator.nth(index)
                try:
                    if not await target.is_visible():
                        continue
                except Exception:
                    continue
                text = await _element_text(target)
                if not text:
                    continue
                if not _contains_any(text, _RESUME_ACTION_TEXTS):
                    continue
                try:
                    await target.scroll_into_view_if_needed(timeout=1200)
                    await target.click(timeout=1200)
                    return True
                except Exception:
                    try:
                        await target.click(timeout=1200, force=True)
                        return True
                    except Exception:
                        continue
        if await sleep_or_stop(stop_signal, 0.15):
            return False
    return False


async def _click_next_page_button(driver: BrowserDriver) -> bool:
    previous_page_number = await _resolve_current_page_number(driver)
    page = await _page(driver)
    selectors = (
        "#divNext",
        "#ctlNext",
        "#btnNext",
        "#next",
        "a.button.mainBgColor[onclick*='show_next_page']",
        ".next",
        ".next-btn",
        ".next-button",
        ".btn-next",
        "a.button.mainBgColor",
    )
    text_selectors = ("button", "a")
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = await locator.count()
        except Exception:
            continue
        for index in range(count):
            target = locator.nth(index)
            try:
                if not await target.is_visible():
                    continue
            except Exception:
                continue
            text = await _element_text(target)
            if text and not _contains_any(text, _NEXT_ACTION_TEXTS):
                continue
            try:
                await target.scroll_into_view_if_needed(timeout=1200)
                await target.click(timeout=1200)
            except Exception:
                try:
                    await target.click(timeout=1200, force=True)
                except Exception:
                    continue
            if await _wait_for_page_number_change(driver, previous_page_number, timeout_ms=5000):
                return True
            return True
    for selector in text_selectors:
        try:
            locator = page.locator(selector)
            count = await locator.count()
        except Exception:
            continue
        for index in range(count):
            target = locator.nth(index)
            try:
                if not await target.is_visible():
                    continue
            except Exception:
                continue
            text = await _element_text(target)
            if not text or not _contains_any(text, _NEXT_ACTION_TEXTS):
                continue
            try:
                await target.scroll_into_view_if_needed(timeout=1200)
                await target.click(timeout=1200)
            except Exception:
                try:
                    await target.click(timeout=1200, force=True)
                except Exception:
                    continue
            if await _wait_for_page_number_change(driver, previous_page_number, timeout_ms=5000):
                return True
            return True
    script = """
        if (typeof show_next_page === 'function') { show_next_page(); return true; }
        if (typeof next_page === 'function') { next_page(); return true; }
        if (typeof nextPage === 'function') { nextPage(); return true; }
        return false;
    """
    try:
        executed = bool(await driver.execute_script(script))
    except Exception:
        executed = False
    if not executed:
        return False
    await _wait_for_page_number_change(driver, previous_page_number, timeout_ms=5000)
    return True


__all__ = [
    "_click_next_page_button",
    "dismiss_resume_dialog_if_present",
    "try_click_start_answer_button",
]
