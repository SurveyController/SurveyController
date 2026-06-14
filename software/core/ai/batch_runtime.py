"""AI 批量作答运行时保护。"""

from __future__ import annotations

from typing import Iterable

from software.core.questions.utils import OPTION_FILL_AI_TOKEN
from software.providers.answering import AnswerAction

_AI_PLACEHOLDER_TOKENS = frozenset(
    {
        OPTION_FILL_AI_TOKEN,
        "__FREE_AI__",
        "__FREE_AI_FILL__",
        "__AI_PLACEHOLDER__",
    }
)


_AI_PLACEHOLDER_PREFIXES = (
    "__FREE_AI_TEXT__",
    "__FREE_AI_OPTION_FILL__",
)


def _contains_ai_placeholder(value: object) -> bool:
    text = str(value or "").strip()
    return bool(
        text
        and (
            text in _AI_PLACEHOLDER_TOKENS
            or any(text.startswith(prefix) for prefix in _AI_PLACEHOLDER_PREFIXES)
        )
    )


def _iter_action_text_values(action: AnswerAction) -> Iterable[object]:
    yield from tuple(getattr(action, "text_values", ()) or ())
    for item in tuple(getattr(action, "option_fill_texts", ()) or ()):
        value = item[1] if isinstance(item, (tuple, list)) and len(item) >= 2 else item
        yield value
    yield from tuple(getattr(action, "selected_texts", ()) or ())


def assert_no_free_ai_placeholders_in_actions(
    actions: Iterable[AnswerAction],
    *,
    provider_label: str = "问卷",
) -> None:
    question_nums: set[int] = set()
    for action in list(actions or []):
        if any(_contains_ai_placeholder(value) for value in _iter_action_text_values(action)):
            question_num = int(getattr(action, "question_num", 0) or 0)
            if question_num > 0:
                question_nums.add(question_num)

    if question_nums:
        labels = "、".join(f"第{num}题" for num in sorted(question_nums)[:8])
        raise RuntimeError(f"{provider_label}存在未替换的 AI 占位符，已停止提交：{labels}")


async def prefill_free_ai_answers_for_questions(*_args, **_kwargs) -> None:
    return None


__all__ = [
    "assert_no_free_ai_placeholders_in_actions",
    "prefill_free_ai_answers_for_questions",
]
