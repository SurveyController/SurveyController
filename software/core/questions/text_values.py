from __future__ import annotations

from typing import Any, Optional, Sequence

from software.app.config import DEFAULT_FILL_TEXT
from software.core.ai.runtime import AIRuntimeError, agenerate_ai_answer, build_ai_option_fill_prompt
from software.core.task import ExecutionState
from software.core.questions.schema import (
    _TEXT_RANDOM_ID_CARD,
    _TEXT_RANDOM_ID_CARD_TOKEN,
    _TEXT_RANDOM_INTEGER,
    _TEXT_RANDOM_MOBILE,
    _TEXT_RANDOM_MOBILE_TOKEN,
    _TEXT_RANDOM_NAME,
    _TEXT_RANDOM_NAME_TOKEN,
)
from software.core.questions.text_shared import MULTI_TEXT_DELIMITER
from software.core.questions.utils import (
    OPTION_FILL_AI_TOKEN,
    build_random_int_token,
    get_fill_text_from_config,
    normalize_probabilities,
    resolve_dynamic_text_token,
    weighted_index,
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


def resolve_text_values_from_config(
    answer_candidates: Optional[Sequence[Any]],
    probabilities: Optional[Sequence[Any]],
    *,
    blank_count: int = 1,
    entry_type: str = "text",
    blank_modes: Optional[Sequence[Any]] = None,
    blank_int_ranges: Optional[Sequence[Any]] = None,
) -> list[str]:
    candidates = [str(item).strip() for item in list(answer_candidates or []) if str(item).strip()]
    if not candidates:
        candidates = [DEFAULT_FILL_TEXT]
    weights = list(probabilities or [])
    if len(weights) < len(candidates):
        weights.extend([0.0] * (len(candidates) - len(weights)))
    elif len(weights) > len(candidates):
        weights = weights[:len(candidates)]
    try:
        numeric_weights = [float(value) for value in weights]
        normalized = normalize_probabilities(numeric_weights)
    except Exception:
        normalized = normalize_probabilities([1.0] * len(candidates))

    selected_raw = candidates[weighted_index(normalized)]
    resolved_blank_count = max(1, int(blank_count or 1))
    if str(entry_type or "").strip() == "multi_text":
        text_values = [
            resolve_dynamic_text_token(part)
            for part in selected_raw.split(MULTI_TEXT_DELIMITER)
        ]
    else:
        text_values = [resolve_dynamic_text_token(selected_raw)]
    if not text_values:
        text_values = [DEFAULT_FILL_TEXT]
    if len(text_values) < resolved_blank_count:
        text_values.extend([text_values[-1]] * (resolved_blank_count - len(text_values)))
    text_values = text_values[:resolved_blank_count]

    modes = list(blank_modes or [])
    ranges = list(blank_int_ranges or [])
    for blank_index in range(resolved_blank_count):
        mode = str(modes[blank_index] if blank_index < len(modes) else "").strip().lower()
        if mode == _TEXT_RANDOM_NAME:
            text_values[blank_index] = resolve_dynamic_text_token(_TEXT_RANDOM_NAME_TOKEN)
        elif mode == _TEXT_RANDOM_MOBILE:
            text_values[blank_index] = resolve_dynamic_text_token(_TEXT_RANDOM_MOBILE_TOKEN)
        elif mode == _TEXT_RANDOM_ID_CARD:
            text_values[blank_index] = resolve_dynamic_text_token(_TEXT_RANDOM_ID_CARD_TOKEN)
        elif mode == _TEXT_RANDOM_INTEGER:
            int_range = ranges[blank_index] if blank_index < len(ranges) else []
            if isinstance(int_range, (list, tuple)) and len(int_range) >= 2:
                text_values[blank_index] = resolve_dynamic_text_token(
                    build_random_int_token(int_range[0], int_range[1])
                )

    return [str(value or "").strip() or DEFAULT_FILL_TEXT for value in text_values]


__all__ = [
    "OPTION_FILL_AI_TOKEN",
    "resolve_option_fill_text_from_config",
    "resolve_text_values_from_config",
]
