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


def _contains_ai_placeholder(value: object) -> bool:
    text = str(value or "").strip()
    return bool(text and text in _AI_PLACEHOLDER_TOKENS)


def _iter_action_text_values(action: AnswerAction) -> Iterable[object]:
    yield from tuple(getattr(action, "text_values", ()) or ())
    yield from tuple(getattr(action, "option_fill_texts", ()) or ())
    yield from tuple(getattr(action, "selected_texts", ()) or ())


def assert_no_free_ai_placeholders_in_actions(actions: Iterable[AnswerAction]) -> None:
    for action in list(actions or []):
        for value in _iter_action_text_values(action):
            if _contains_ai_placeholder(value):
                question_num = int(getattr(action, "question_num", 0) or 0)
                raise RuntimeError(f"第{question_num}题仍有 AI 占位符，已停止提交")


async def prefill_free_ai_answers_for_questions(*_args, **_kwargs) -> None:
    return None


__all__ = [
    "assert_no_free_ai_placeholders_in_actions",
    "prefill_free_ai_answers_for_questions",
]
