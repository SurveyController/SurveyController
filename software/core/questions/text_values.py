from __future__ import annotations

from typing import Any, Optional, Sequence

from software.app.config import DEFAULT_FILL_TEXT
from software.core.ai.runtime import AIRuntimeError, agenerate_ai_answer, build_ai_option_fill_prompt
from software.core.task import ExecutionState
from surveycore.core.questions.text_values import resolve_text_values_from_config
from surveycore.core.questions.utils import (
    OPTION_FILL_AI_TOKEN,
    get_fill_text_from_config,
    resolve_dynamic_text_token,
)


async def resolve_option_fill_text_from_config(
    fill_entries: Optional[Sequence[Optional[str]]],
    option_index: int,
    *,
    question_title: str = "",
    question_number: int = 0,
    option_text: Optional[str] = None,
    driver: Any = None,
    ctx: Optional[ExecutionState] = None,
    thread_name: str = "",
    allow_ai_placeholder: bool = False,
    ai_placeholder_text: str = DEFAULT_FILL_TEXT,
) -> Optional[str]:
    del driver
    raw_value = get_fill_text_from_config(fill_entries, option_index)
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    if text != OPTION_FILL_AI_TOKEN:
        return resolve_dynamic_text_token(text)
    if ctx is not None:
        cached = ctx.get_free_ai_option_fill_prefill_answer(thread_name, question_number, option_index)
        if cached:
            return cached
    if allow_ai_placeholder:
        return str(ai_placeholder_text or "").strip() or DEFAULT_FILL_TEXT

    ai_prompt = build_ai_option_fill_prompt(
        question_title=question_title,
        question_number=question_number,
        option_text=str(option_text or ""),
    )

    try:
        answer = await agenerate_ai_answer(ai_prompt, question_type="fill_blank", ctx=ctx)
    except AIRuntimeError as exc:
        raise AIRuntimeError(f"第{question_number}题附加填空 AI 生成失败：{exc}") from exc
    return str(answer).strip() or DEFAULT_FILL_TEXT


__all__ = [
    "OPTION_FILL_AI_TOKEN",
    "resolve_option_fill_text_from_config",
    "resolve_text_values_from_config",
]
