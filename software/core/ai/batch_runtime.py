from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from software.app.config import DEFAULT_FILL_TEXT
from software.core.ai.runtime import (
    build_ai_option_fill_prompt,
    build_ai_question_prompt,
    is_free_ai_option_fill_placeholder,
    is_free_ai_text_placeholder,
)
from software.core.task import ExecutionState
from software.integrations.ai.free_api import (
    FreeAIBatchItem,
    FreeAIBatchResolvedResult,
    wait_free_ai_batch_result_async,
)
from software.integrations.ai.client import agenerate_answer
from software.integrations.ai.settings import (
    AI_MODE_FREE,
    FREE_QUESTION_TYPE_FILL,
    FREE_QUESTION_TYPE_MULTI,
    _normalize_ai_mode,
    get_default_system_prompt,
)
from software.providers.answering import AnswerAction
from software.providers.contracts import SurveyQuestionMeta

_PROVIDER_BATCH_MAX_CONCURRENCY = 4


@dataclass(frozen=True)
class FreeAIPrefillSummary:
    requested: int = 0
    completed: int = 0
    failed: int = 0
    pending: int = 0


def _is_free_ai_mode(ctx: ExecutionState) -> bool:
    return _normalize_ai_mode(getattr(ctx.config, "ai_mode", AI_MODE_FREE)) == AI_MODE_FREE


def _item_id_for_question(question_num: int) -> str:
    return f"q{int(question_num or 0)}"


def _item_id_for_option_fill(question_num: int, option_index: int) -> str:
    return f"q{int(question_num or 0)}_opt{int(option_index or 0)}"


def _question_type_for_blank_count(blank_count: int) -> str:
    return FREE_QUESTION_TYPE_MULTI if int(blank_count or 0) > 1 else FREE_QUESTION_TYPE_FILL


def _system_prompt_for_free_mode(ctx: ExecutionState) -> str:
    return str(getattr(ctx.config, "ai_system_prompt", "") or "").strip() or get_default_system_prompt(AI_MODE_FREE)


def _prefill_label_for_ctx(ctx: ExecutionState) -> str:
    return "免费 AI" if _is_free_ai_mode(ctx) else "AI"


def _question_map(questions: Iterable[SurveyQuestionMeta]) -> Dict[int, SurveyQuestionMeta]:
    result: Dict[int, SurveyQuestionMeta] = {}
    for question in list(questions or []):
        question_num = int(getattr(question, "num", 0) or 0)
        if question_num > 0:
            result[question_num] = question
    return result


def _build_free_ai_batch_items_for_actions(
    questions: Iterable[SurveyQuestionMeta],
    actions: Sequence[AnswerAction],
) -> tuple[List[FreeAIBatchItem], Dict[str, int], Dict[str, Tuple[int, int]]]:
    items: List[FreeAIBatchItem] = []
    item_question_map: Dict[str, int] = {}
    item_option_fill_map: Dict[str, Tuple[int, int]] = {}
    question_by_num = _question_map(questions)

    for action in list(actions or []):
        question_num = int(getattr(action, "question_num", 0) or 0)
        if question_num <= 0:
            continue
        question = question_by_num.get(question_num)
        if question is None:
            continue

        placeholder_texts = [value for value in action.text_values if is_free_ai_text_placeholder(value)]
        if placeholder_texts:
            blank_count = len(tuple(action.text_values or ()))
            question_content = build_ai_question_prompt(
                str(getattr(question, "title", "") or ""),
                description=str(getattr(question, "description", "") or ""),
                question_number=question_num,
            )
            if question_content:
                item_id = _item_id_for_question(question_num)
                items.append(
                    FreeAIBatchItem(
                        item_id=item_id,
                        question_type=_question_type_for_blank_count(blank_count),
                        question_content=question_content,
                        blank_count=blank_count if blank_count > 1 else None,
                    )
                )
                item_question_map[item_id] = question_num

        option_texts = [str(item or "").strip() for item in list(getattr(question, "option_texts", []) or [])]
        for option_index, fill_value in tuple(action.option_fill_texts or ()):
            if not is_free_ai_option_fill_placeholder(fill_value):
                continue
            normalized_option_index = int(option_index)
            option_prompt = build_ai_option_fill_prompt(
                question_title=str(getattr(question, "title", "") or ""),
                question_number=question_num,
                option_text=option_texts[normalized_option_index] if normalized_option_index < len(option_texts) else "",
            )
            option_item_id = _item_id_for_option_fill(question_num, normalized_option_index)
            items.append(
                FreeAIBatchItem(
                    item_id=option_item_id,
                    question_type=FREE_QUESTION_TYPE_FILL,
                    question_content=option_prompt,
                )
            )
            item_option_fill_map[option_item_id] = (question_num, normalized_option_index)
    return items, item_question_map, item_option_fill_map


def _resolved_answers_by_question_num(
    result: FreeAIBatchResolvedResult,
    item_question_map: Dict[str, int],
) -> Dict[int, tuple[str, ...]]:
    resolved: Dict[int, tuple[str, ...]] = {}
    for item_id, answers in dict(result.completed or {}).items():
        question_num = item_question_map.get(item_id)
        if question_num is None:
            continue
        normalized = tuple(str(item or "").strip() for item in list(answers or []) if str(item or "").strip())
        if normalized:
            resolved[int(question_num)] = normalized
    return resolved


def _resolved_option_fill_answers(
    result: FreeAIBatchResolvedResult,
    item_option_fill_map: Dict[str, Tuple[int, int]],
) -> Dict[Tuple[int, int], str]:
    resolved: Dict[Tuple[int, int], str] = {}
    for item_id, answers in dict(result.completed or {}).items():
        option_key = item_option_fill_map.get(item_id)
        if option_key is None:
            continue
        normalized_answers = [str(item or "").strip() for item in list(answers or []) if str(item or "").strip()]
        if normalized_answers:
            resolved[option_key] = normalized_answers[0]
    return resolved


def _raise_prefill_incomplete_error(
    result: FreeAIBatchResolvedResult,
    item_question_map: Dict[str, int],
    item_option_fill_map: Dict[str, Tuple[int, int]],
    *,
    label: str = "AI",
) -> None:
    failed_labels: list[str] = []
    pending_labels: list[str] = []

    for item_id, detail in dict(result.failed or {}).items():
        question_num = item_question_map.get(item_id)
        option_key = item_option_fill_map.get(item_id)
        if question_num is not None:
            failed_labels.append(f"第{int(question_num)}题：{detail}")
            continue
        if option_key is not None:
            failed_labels.append(f"第{int(option_key[0])}题选项{int(option_key[1]) + 1}：{detail}")
            continue
        failed_labels.append(f"{item_id}：{detail}")

    for item_id in sorted(result.pending or set()):
        question_num = item_question_map.get(item_id)
        option_key = item_option_fill_map.get(item_id)
        if question_num is not None:
            pending_labels.append(f"第{int(question_num)}题")
            continue
        if option_key is not None:
            pending_labels.append(f"第{int(option_key[0])}题选项{int(option_key[1]) + 1}")
            continue
        pending_labels.append(item_id)

    parts: list[str] = []
    if failed_labels:
        parts.append("失败：" + "；".join(failed_labels[:5]))
    if pending_labels:
        parts.append("未完成：" + "；".join(pending_labels[:5]))
    detail = "；".join(parts) if parts else "存在未完成题目"
    raise RuntimeError(f"{label} 批量预取未完成，已停止本轮提交：{detail}")


def _normalize_provider_item_answers(item: FreeAIBatchItem, raw_answer: Any) -> List[str]:
    if item.question_type == FREE_QUESTION_TYPE_MULTI:
        if isinstance(raw_answer, list):
            answers = [str(value or "").strip() for value in raw_answer]
        else:
            answers = [part.strip() for part in str(raw_answer or "").split("||")]
        answers = [value for value in answers if value]
        expected = int(item.blank_count or 0)
        if expected > 0 and len(answers) != expected:
            raise RuntimeError(f"期望 {expected} 个答案，实际返回 {len(answers)} 个")
        if not answers:
            raise RuntimeError("AI 未返回有效答案")
        return answers

    answer = str(raw_answer or "").strip()
    if not answer:
        raise RuntimeError("AI 未返回有效答案")
    return [answer]


async def _wait_provider_batch_result_async(
    items: Iterable[FreeAIBatchItem],
    *,
    ctx: ExecutionState,
) -> FreeAIBatchResolvedResult:
    normalized_items = list(items or [])
    completed: Dict[str, List[str]] = {}
    failed: Dict[str, str] = {}
    semaphore = asyncio.Semaphore(_PROVIDER_BATCH_MAX_CONCURRENCY)

    async def _run_item(item: FreeAIBatchItem) -> None:
        async with semaphore:
            try:
                raw_answer = await agenerate_answer(
                    item.question_content,
                    question_type=item.question_type,
                    blank_count=item.blank_count,
                    ctx=ctx,
                )
                completed[item.item_id] = _normalize_provider_item_answers(item, raw_answer)
            except Exception as exc:
                failed[item.item_id] = str(exc or "AI 调用失败")

    await asyncio.gather(*(_run_item(item) for item in normalized_items))
    return FreeAIBatchResolvedResult(
        completed=completed,
        failed=failed,
        pending=set(),
        task_ids=[],
    )


def _rebuild_selected_texts(
    action: AnswerAction,
    question: SurveyQuestionMeta | None,
    fill_map: Dict[int, str],
) -> tuple[str, ...]:
    option_texts = [str(item or "").strip() for item in list(getattr(question, "option_texts", []) or [])]
    existing = list(action.selected_texts or ())
    rebuilt: list[str] = []
    for position, option_index in enumerate(tuple(action.selected_indices or ())):
        normalized_index = int(option_index)
        base_text = option_texts[normalized_index] if normalized_index < len(option_texts) else ""
        if not base_text and position < len(existing):
            base_text = str(existing[position] or "").split(" / ", 1)[0].strip()
        fill_value = str(fill_map.get(normalized_index) or "").strip()
        if fill_value:
            rebuilt.append(f"{base_text} / {fill_value}" if base_text else fill_value)
        else:
            rebuilt.append(base_text)
    return tuple(rebuilt)


def _apply_prefilled_answers_to_actions(
    questions: Iterable[SurveyQuestionMeta],
    actions: Sequence[AnswerAction],
    resolved_answers: Dict[int, tuple[str, ...]],
    resolved_option_fill_answers: Dict[Tuple[int, int], str],
) -> List[AnswerAction]:
    question_by_num = _question_map(questions)
    updated_actions: List[AnswerAction] = []
    for action in list(actions or []):
        question_num = int(getattr(action, "question_num", 0) or 0)
        updated_action = action

        if question_num in resolved_answers and tuple(action.text_values or ()):
            updated_action = replace(
                updated_action,
                text_values=tuple(
                    str(item or "").strip() or DEFAULT_FILL_TEXT
                    for item in resolved_answers[question_num]
                ),
            )

        if tuple(updated_action.option_fill_texts or ()):
            fill_map: Dict[int, str] = {}
            option_fill_texts: list[tuple[int, str]] = []
            changed = False
            for option_index, raw_value in tuple(updated_action.option_fill_texts or ()):
                normalized_option_index = int(option_index)
                normalized_value = str(raw_value or "").strip()
                if is_free_ai_option_fill_placeholder(normalized_value):
                    normalized_value = str(
                        resolved_option_fill_answers.get((question_num, normalized_option_index), "")
                    ).strip()
                    changed = True
                if normalized_value:
                    fill_map[normalized_option_index] = normalized_value
                    option_fill_texts.append((normalized_option_index, normalized_value))
            if changed:
                updated_action = replace(
                    updated_action,
                    option_fill_texts=tuple(option_fill_texts),
                    selected_texts=_rebuild_selected_texts(
                        updated_action,
                        question_by_num.get(question_num),
                        fill_map,
                    ),
                )

        updated_actions.append(updated_action)
    return updated_actions


async def prefill_free_ai_answers_for_questions(
    questions: Iterable[SurveyQuestionMeta],
    actions: List[AnswerAction],
    ctx: ExecutionState,
    *,
    thread_name: str = "",
) -> FreeAIPrefillSummary:
    ctx.clear_free_ai_prefill_answers(thread_name)
    if not actions:
        return FreeAIPrefillSummary()

    items, item_question_map, item_option_fill_map = _build_free_ai_batch_items_for_actions(questions, actions)
    if not items:
        return FreeAIPrefillSummary()

    if _is_free_ai_mode(ctx):
        result = await wait_free_ai_batch_result_async(
            items,
            system_prompt=_system_prompt_for_free_mode(ctx),
            ctx=ctx,
        )
    else:
        result = await _wait_provider_batch_result_async(items, ctx=ctx)
    if result.failed or result.pending:
        _raise_prefill_incomplete_error(
            result,
            item_question_map,
            item_option_fill_map,
            label=_prefill_label_for_ctx(ctx),
        )

    resolved_answers = _resolved_answers_by_question_num(result, item_question_map)
    resolved_option_fill_answers = _resolved_option_fill_answers(result, item_option_fill_map)
    ctx.set_free_ai_prefill_answers(thread_name, resolved_answers)
    ctx.set_free_ai_option_fill_prefill_answers(thread_name, resolved_option_fill_answers)
    actions[:] = _apply_prefilled_answers_to_actions(
        questions,
        actions,
        resolved_answers,
        resolved_option_fill_answers,
    )
    return FreeAIPrefillSummary(
        requested=len(items),
        completed=len(result.completed),
        failed=len(result.failed),
        pending=len(result.pending),
    )


def assert_no_free_ai_placeholders_in_actions(
    actions: Sequence[AnswerAction],
    *,
    provider_label: str = "问卷",
) -> None:
    question_nums: set[int] = set()
    for action in list(actions or []):
        values = list(action.text_values or ())
        values.extend(value for _, value in tuple(action.option_fill_texts or ()))
        values.extend(action.selected_texts or ())
        if any(is_free_ai_text_placeholder(value) or is_free_ai_option_fill_placeholder(value) for value in values):
            question_num = int(getattr(action, "question_num", 0) or 0)
            if question_num > 0:
                question_nums.add(question_num)

    if question_nums:
        labels = "、".join(f"第{num}题" for num in sorted(question_nums)[:8])
        raise RuntimeError(f"{provider_label}存在未替换的 AI 占位符，已停止提交：{labels}")


__all__ = [
    "FreeAIPrefillSummary",
    "assert_no_free_ai_placeholders_in_actions",
    "prefill_free_ai_answers_for_questions",
]
