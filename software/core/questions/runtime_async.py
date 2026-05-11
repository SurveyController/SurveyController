"""异步运行时题目辅助函数。"""

from __future__ import annotations

import asyncio
from typing import Any, Optional, Sequence

from software.app.config import DEFAULT_FILL_TEXT
from software.core.ai.runtime import AIRuntimeError, agenerate_ai_answer
from software.core.questions.utils import (
    OPTION_FILL_AI_TOKEN,
    extract_text_from_element,
    get_fill_text_from_config,
    resolve_dynamic_text_token,
)
from software.network.browser.runtime_async import BrowserDriver


async def extract_text_from_runtime_element(element: Any) -> str:
    for reader in (
        lambda: element.text(),
        lambda: element.get_attribute("textContent"),
        lambda: element.get_attribute("value"),
    ):
        try:
            value = reader()
            if asyncio.iscoroutine(value):
                value = await value
        except Exception:
            value = ""
        text = str(value or "").strip()
        if text:
            return text
    try:
        fallback = extract_text_from_element(element)
    except Exception:
        fallback = ""
    return str(fallback or "").strip()


async def smooth_scroll_to_runtime_element(
    driver: BrowserDriver,
    element: Any,
    block: str = "center",
) -> None:
    await driver.execute_script(
        f"arguments[0].scrollIntoView({{block:'{block}', behavior:'auto'}});",
        element,
    )


async def extract_runtime_question_title(driver: BrowserDriver, question_number: int) -> str:
    selectors = (
        f"#div{question_number} .topichtml",
        f"#div{question_number} .field-label",
        f"#div{question_number} .title",
        f"#div{question_number} .topic",
    )
    for selector in selectors:
        try:
            element = await driver.find_element("css", selector)
        except Exception:
            element = None
        if element is None:
            continue
        text = await extract_text_from_runtime_element(element)
        if text:
            return text
    return ""


async def resolve_runtime_question_title_for_ai(
    driver: BrowserDriver,
    question_number: int,
    fallback_title: Optional[str] = None,
) -> str:
    title = str(fallback_title or "").strip()
    if not title:
        title = await extract_runtime_question_title(driver, question_number)
    if not title:
        raise AIRuntimeError(f"无法获取第{question_number}题题干，无法调用 AI")
    return title


async def resolve_runtime_option_fill_text_from_config(
    fill_entries: Optional[Sequence[Optional[str]]],
    option_index: int,
    *,
    driver: Optional[BrowserDriver] = None,
    question_number: int = 0,
    option_text: Optional[str] = None,
) -> Optional[str]:
    raw_value = get_fill_text_from_config(fill_entries, option_index)
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    if text != OPTION_FILL_AI_TOKEN:
        return resolve_dynamic_text_token(text)

    if driver is None or question_number <= 0:
        raise AIRuntimeError("AI 选项附加填空缺少运行时上下文")

    question_title = await resolve_runtime_question_title_for_ai(driver, question_number)
    option_hint = str(option_text or "").strip()
    ai_prompt = (
        f"{question_title}\n\n"
        "当前需要填写的是某个选择题选项后面的补充输入框。"
    )
    if option_hint:
        ai_prompt += f"\n已选择的选项是：{option_hint}"
    ai_prompt += "\n请只输出最终要填写的内容，不要解释。"

    try:
        answer = await agenerate_ai_answer(ai_prompt, question_type="fill_blank")
    except AIRuntimeError as exc:
        raise AIRuntimeError(f"第{question_number}题附加填空 AI 生成失败：{exc}") from exc
    return str(answer).strip() or DEFAULT_FILL_TEXT


__all__ = [
    "extract_runtime_question_title",
    "extract_text_from_runtime_element",
    "resolve_runtime_option_fill_text_from_config",
    "resolve_runtime_question_title_for_ai",
    "smooth_scroll_to_runtime_element",
]
