"""免费 AI 批量预取运行时辅助。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from software.core.ai.runtime import build_ai_question_prompt
from software.core.questions.text_values import OPTION_FILL_AI_TOKEN
from software.core.task import ExecutionState
from software.integrations.ai.free_api import (
    FreeAIBatchItem,
    FreeAIBatchResolvedResult,
    wait_free_ai_batch_result_async,
)
from software.integrations.ai.settings import (
    AI_MODE_FREE,
    FREE_QUESTION_TYPE_FILL,
    FREE_QUESTION_TYPE_MULTI,
    _normalize_ai_mode,
    get_default_system_prompt,
)
from software.providers.contracts import SurveyQuestionMeta


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


def _question_type_for_blank_count(blank_count: int) -> str:
    return FREE_QUESTION_TYPE_MULTI if int(blank_count or 0) > 1 else FREE_QUESTION_TYPE_FILL


def _build_free_ai_batch_items(
    questions: Iterable[SurveyQuestionMeta],
    ctx: ExecutionState,
) -> tuple[List[FreeAIBatchItem], Dict[str, int], Dict[str, Tuple[int, int]]]:
    items: List[FreeAIBatchItem] = []
    item_question_map: Dict[str, int] = {}
    item_option_fill_map: Dict[str, Tuple[int, int]] = {}
    config = ctx.config
    text_ai_flags = list(getattr(config, "text_ai_flags", []) or [])
    for question in list(questions or []):
        question_num = int(getattr(question, "num", 0) or 0)
        if question_num <= 0:
            continue
        config_entry = (config.question_config_index_map or {}).get(question_num)
        if not config_entry:
            continue
        entry_type, config_index = config_entry
        normalized_entry_type = str(entry_type or "").strip()
        if normalized_entry_type in {"text", "multi_text"}:
            ai_enabled = bool(text_ai_flags[config_index]) if config_index < len(text_ai_flags) else False
            if ai_enabled:
                blank_count = max(1, int(getattr(question, "text_inputs", 1) or 1))
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
        fill_entries = _option_fill_entries_for_question(config, normalized_entry_type, config_index)
        if not fill_entries:
            continue
        option_texts = [str(item or "").strip() for item in list(getattr(question, "option_texts", []) or [])]
        for option_index, raw_value in enumerate(fill_entries):
            if str(raw_value or "").strip() != OPTION_FILL_AI_TOKEN:
                continue
            option_prompt = _build_option_fill_prompt(
                question_title=str(getattr(question, "title", "") or ""),
                question_number=question_num,
                option_text=option_texts[option_index] if option_index < len(option_texts) else "",
            )
            option_item_id = _item_id_for_option_fill(question_num, option_index)
            items.append(
                FreeAIBatchItem(
                    item_id=option_item_id,
                    question_type=FREE_QUESTION_TYPE_FILL,
                    question_content=option_prompt,
                )
            )
            item_option_fill_map[option_item_id] = (question_num, option_index)
    return items, item_question_map, item_option_fill_map


def _item_id_for_option_fill(question_num: int, option_index: int) -> str:
    return f"q{int(question_num or 0)}_opt{int(option_index or 0)}"


def _option_fill_entries_for_question(
    config: object,
    entry_type: str,
    config_index: int,
) -> List[str | None]:
    if entry_type == "single":
        raw_entries = getattr(config, "single_option_fill_texts", [])
    elif entry_type == "dropdown":
        raw_entries = getattr(config, "droplist_option_fill_texts", [])
    elif entry_type == "multiple":
        raw_entries = getattr(config, "multiple_option_fill_texts", [])
    else:
        return []
    if config_index >= len(raw_entries):
        return []
    entries = raw_entries[config_index]
    if not isinstance(entries, list):
        return []
    return [None if item is None else str(item) for item in entries]


def _build_option_fill_prompt(
    *,
    question_title: str,
    question_number: int,
    option_text: str,
) -> str:
    title = str(question_title or "").strip() or f"第{int(question_number or 0)}题"
    prompt = f"{title}\n\n当前需要填写的是某个选择题选项后面的补充输入框。"
    normalized_option_text = str(option_text or "").strip()
    if normalized_option_text:
        prompt += f"\n已选择的选项是：{normalized_option_text}"
    prompt += "\n请只输出最终要填写的内容，不要解释。"
    return prompt


def _system_prompt_for_free_mode(ctx: ExecutionState) -> str:
    return str(getattr(ctx.config, "ai_system_prompt", "") or "").strip() or get_default_system_prompt(AI_MODE_FREE)


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
    raise RuntimeError(f"免费 AI 批量预取未完成，已停止本轮提交：{detail}")


async def prefill_free_ai_answers_for_questions(
    questions: Iterable[SurveyQuestionMeta],
    ctx: ExecutionState,
    *,
    thread_name: str = "",
) -> FreeAIPrefillSummary:
    ctx.clear_free_ai_prefill_answers(thread_name)
    if not _is_free_ai_mode(ctx):
        return FreeAIPrefillSummary()
    items, item_question_map, item_option_fill_map = _build_free_ai_batch_items(questions, ctx)
    if not items:
        return FreeAIPrefillSummary()
    result = await wait_free_ai_batch_result_async(
        items,
        system_prompt=_system_prompt_for_free_mode(ctx),
    )
    if result.failed or result.pending:
        _raise_prefill_incomplete_error(result, item_question_map, item_option_fill_map)
    resolved_answers = _resolved_answers_by_question_num(result, item_question_map)
    resolved_option_fill_answers = _resolved_option_fill_answers(result, item_option_fill_map)
    ctx.set_free_ai_prefill_answers(thread_name, resolved_answers)
    ctx.set_free_ai_option_fill_prefill_answers(thread_name, resolved_option_fill_answers)
    return FreeAIPrefillSummary(
        requested=len(items),
        completed=len(result.completed),
        failed=len(result.failed),
        pending=len(result.pending),
    )


__all__ = [
    "FreeAIPrefillSummary",
    "prefill_free_ai_answers_for_questions",
]
