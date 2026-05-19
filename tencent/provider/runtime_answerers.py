"""腾讯问卷题型执行逻辑。"""
from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from software.app.config import DEFAULT_FILL_TEXT
from software.core.ai.runtime import AIRuntimeError, agenerate_ai_answer
from software.core.persona.context import apply_persona_boost, record_answer
from software.core.questions.consistency import apply_matrix_row_consistency, apply_single_like_consistency, get_multiple_rule_constraint
from software.core.questions.distribution import record_pending_distribution_choice, resolve_distribution_probabilities
from software.core.questions.runtime_async import (
    resolve_runtime_option_fill_text_from_config,
    resolve_runtime_text_values_from_config,
)
from software.core.questions.strict_ratio import enforce_reference_rank_order, is_strict_ratio_question, stochastic_round, weighted_sample_without_replacement
from software.core.questions.tendency import get_tendency_index
from software.core.questions.utils import (
    normalize_droplist_probs,
    weighted_index,
)
from software.core.task import ExecutionState
from software.network.browser.runtime_async import BrowserDriver
from software.providers.contracts import SurveyQuestionMeta

from .runtime_interactions import (
    _apply_multiple_constraints,
    _click_choice_input,
    _click_matrix_cell,
    _click_star_cell,
    _describe_dropdown_state,
    _fill_choice_option_additional_text,
    _fill_text_question,
    _normalize_selected_indices,
    _open_dropdown,
    _prepare_question_interaction,
    _select_dropdown_option,
)


def _format_matrix_weight_value(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return str(value or "").strip() or "随机"
    if math.isnan(number) or math.isinf(number):
        return "随机"
    text = f"{number:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _resolve_selected_weight_text(
    selected_index: int,
    resolved_probabilities: Any,
    raw_probabilities: Any,
) -> str:
    if isinstance(resolved_probabilities, list) and 0 <= selected_index < len(resolved_probabilities):
        return _format_matrix_weight_value(resolved_probabilities[selected_index])
    if isinstance(raw_probabilities, list) and 0 <= selected_index < len(raw_probabilities):
        return _format_matrix_weight_value(raw_probabilities[selected_index])
    return "随机"


def _log_qq_matrix_row_choice(
    current: int,
    row_number: int,
    selected_index: int,
    option_texts: List[str],
    resolved_probabilities: Any,
    raw_probabilities: Any,
) -> None:
    _ = current, row_number, selected_index, option_texts, resolved_probabilities, raw_probabilities


@dataclass(frozen=True)
class AnswerAction:
    question_num: int
    question_id: str
    kind: str
    input_type: str = ""
    selected_indices: tuple[int, ...] = ()
    matrix_indices: tuple[int, ...] = ()
    text_values: tuple[str, ...] = ()
    option_fill_texts: tuple[tuple[int, str], ...] = ()
    selected_texts: tuple[str, ...] = ()
    record_type: str = ""
    pending_distribution_choices: tuple[tuple[int, int, Optional[int]], ...] = ()


@dataclass(frozen=True)
class BatchFillResult:
    applied: tuple[int, ...] = ()
    failed: tuple[int, ...] = ()
    skipped: tuple[int, ...] = ()


def _action_payload(action: AnswerAction) -> dict[str, Any]:
    return {
        "questionNum": int(action.question_num),
        "questionId": str(action.question_id or ""),
        "kind": str(action.kind or ""),
        "inputType": str(action.input_type or ""),
        "selectedIndices": [int(item) for item in action.selected_indices],
        "matrixIndices": [int(item) for item in action.matrix_indices],
        "textValues": [str(item or "") for item in action.text_values],
        "optionFillTexts": [
            {"optionIndex": int(option_index), "value": str(value or "")}
            for option_index, value in action.option_fill_texts
            if str(value or "").strip()
        ],
    }


def _record_answer_action(ctx: ExecutionState, action: AnswerAction) -> None:
    current = int(action.question_num or 0)
    if current <= 0:
        return
    record_type = str(action.record_type or action.kind or "").strip()
    for option_index, option_count, row_index in action.pending_distribution_choices:
        record_pending_distribution_choice(
            ctx,
            current,
            int(option_index),
            int(option_count),
            row_index=row_index,
        )
    if record_type == "matrix":
        for row_index, selected_index in enumerate(action.matrix_indices):
            record_answer(current, "matrix", selected_indices=[int(selected_index)], row_index=row_index)
        return
    if record_type == "text":
        text_values = [str(item or "").strip() or DEFAULT_FILL_TEXT for item in action.text_values]
        if not text_values:
            text_values = [DEFAULT_FILL_TEXT]
        record_answer(current, "text", text_answer=" | ".join(text_values) if len(text_values) > 1 else text_values[0])
        return
    record_answer(
        current,
        record_type,
        selected_indices=[int(item) for item in action.selected_indices],
        selected_texts=[str(item or "") for item in action.selected_texts],
    )


async def _answer_qq_single(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> None:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = list(question.option_texts or [])
    option_count = max(1, len(option_texts) or int(question.options or 0))
    probabilities = config.single_prob[config_index] if config_index < len(config.single_prob) else -1
    probabilities = normalize_droplist_probs(probabilities, option_count)
    strict_ratio = is_strict_ratio_question(ctx, current)
    if not strict_ratio:
        probabilities = apply_persona_boost(option_texts, probabilities)
    probabilities = apply_single_like_consistency(probabilities, current)
    if strict_ratio:
        strict_reference = list(probabilities)
        probabilities = resolve_distribution_probabilities(probabilities, option_count, ctx, current)
        probabilities = enforce_reference_rank_order(probabilities, strict_reference)
    selected_index = weighted_index(probabilities)
    if not await _click_choice_input(driver, str(question.provider_question_id or ""), "radio", selected_index):
        logging.warning("腾讯问卷第%d题（单选）点击未生效，已跳过。", current)
        return
    if strict_ratio:
        record_pending_distribution_choice(ctx, current, selected_index, option_count)
    selected_text = option_texts[selected_index] if selected_index < len(option_texts) else ""
    fill_entries = (
        config.single_option_fill_texts[config_index]
        if config_index < len(config.single_option_fill_texts)
        else None
    )
    fill_value = await resolve_runtime_option_fill_text_from_config(
        fill_entries,
        selected_index,
        driver=driver,
        question_number=current,
        option_text=selected_text,
    )
    if fill_value and await _fill_choice_option_additional_text(
            driver,
            str(question.provider_question_id or ""),
            selected_index,
            fill_value,
            input_type="radio",
        ):
        selected_text = f"{selected_text} / {fill_value}" if selected_text else fill_value
    record_answer(current, "single", selected_indices=[selected_index], selected_texts=[selected_text])

async def _answer_qq_dropdown(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> None:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = list(question.option_texts or [])
    option_count = max(1, len(option_texts) or int(question.options or 0))
    probabilities = config.droplist_prob[config_index] if config_index < len(config.droplist_prob) else -1
    probabilities = normalize_droplist_probs(probabilities, option_count)
    strict_ratio = is_strict_ratio_question(ctx, current)
    dimension = config.question_dimension_map.get(current)
    has_reliability_dimension = isinstance(dimension, str) and bool(str(dimension).strip())
    if not strict_ratio:
        probabilities = apply_persona_boost(option_texts, probabilities)
    if strict_ratio or has_reliability_dimension:
        strict_reference = list(probabilities)
        probabilities = resolve_distribution_probabilities(
            probabilities,
            option_count,
            ctx,
            current,
            psycho_plan=psycho_plan,
        )
        if strict_ratio:
            probabilities = enforce_reference_rank_order(probabilities, strict_reference)
    if has_reliability_dimension:
        selected_index = get_tendency_index(
            option_count,
            probabilities,
            dimension=dimension,
            psycho_plan=psycho_plan,
            question_index=current,
        )
    else:
        selected_index = weighted_index(probabilities)
    selected_text = option_texts[selected_index] if selected_index < len(option_texts) else ""
    question_id = str(question.provider_question_id or "")
    selected_ok = False
    for attempt in range(2):
        await _prepare_question_interaction(
            driver,
            question_id,
            control_selectors=("input.t-input__inner", ".t-input", ".t-select__wrap"),
            settle_ms=220,
        )
        if not await _open_dropdown(driver, question_id):
            if attempt == 0:
                continue
            logging.warning(
                "腾讯问卷第%d题（下拉）无法打开选项面板。state=%s",
                current,
                await _describe_dropdown_state(driver, question_id),
            )
            return
        if await _select_dropdown_option(driver, question_id, selected_text):
            selected_ok = True
            break
    if not selected_ok:
        logging.warning(
            "腾讯问卷第%d题（下拉）无法选中选项：%s | state=%s",
            current,
            selected_text,
            await _describe_dropdown_state(driver, question_id),
        )
        return
    fill_entries = (
        config.droplist_option_fill_texts[config_index]
        if config_index < len(config.droplist_option_fill_texts)
        else None
    )
    fill_value = await resolve_runtime_option_fill_text_from_config(
        fill_entries,
        selected_index,
        driver=driver,
        question_number=current,
        option_text=selected_text,
    )
    if fill_value and await _fill_choice_option_additional_text(
            driver,
            question_id,
            selected_index,
            fill_value,
            input_type=None,
        ):
        selected_text = f"{selected_text} / {fill_value}" if selected_text else fill_value
    if strict_ratio or has_reliability_dimension:
        record_pending_distribution_choice(ctx, current, selected_index, option_count)
    record_answer(current, "dropdown", selected_indices=[selected_index], selected_texts=[selected_text])

async def _answer_qq_text(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> None:
    config = ctx.config
    current = int(question.num or 0)
    blank_count = max(1, int(getattr(question, "text_inputs", 1) or 1))
    text_entry_types = list(getattr(ctx.config, "text_entry_types", []) or [])
    multi_text_blank_modes = list(getattr(ctx.config, "multi_text_blank_modes", []) or [])
    multi_text_blank_ranges = list(getattr(ctx.config, "multi_text_blank_int_ranges", []) or [])
    text_values = resolve_runtime_text_values_from_config(
        config.texts[config_index] if config_index < len(config.texts) else [DEFAULT_FILL_TEXT],
        config.texts_prob[config_index] if config_index < len(config.texts_prob) else [1.0],
        blank_count=blank_count,
        entry_type=str(text_entry_types[config_index] if config_index < len(text_entry_types) else "text"),
        blank_modes=multi_text_blank_modes[config_index] if config_index < len(multi_text_blank_modes) else [],
        blank_int_ranges=multi_text_blank_ranges[config_index] if config_index < len(multi_text_blank_ranges) else [],
    )
    selected_answer: str | list[str] = text_values if blank_count > 1 else (text_values[0] if text_values else DEFAULT_FILL_TEXT)
    ai_enabled = bool(config.text_ai_flags[config_index]) if config_index < len(config.text_ai_flags) else False
    title = str(question.title or "")
    description = str(question.description or "").strip()
    ai_prompt = title.strip()
    if description and description not in ai_prompt:
        ai_prompt = f"{ai_prompt}\n补充说明：{description}"
    if ai_enabled:
        try:
            generated = await agenerate_ai_answer(ai_prompt, question_type="fill_blank", blank_count=1)
        except AIRuntimeError as exc:
            raise AIRuntimeError(f"腾讯问卷第{current}题 AI 生成失败：{exc}") from exc
        if isinstance(generated, list):
            if blank_count > 1:
                selected_answer = [str(item or "").strip() or DEFAULT_FILL_TEXT for item in list(generated or [])]
            else:
                selected_answer = str(generated[0]).strip() if generated else DEFAULT_FILL_TEXT
        else:
            selected_answer = str(generated or "").strip() or DEFAULT_FILL_TEXT
    if not await _fill_text_question(driver, str(question.provider_question_id or ""), selected_answer):
        logging.warning("腾讯问卷第%d题（文本）填写失败。", current)
        return
    if isinstance(selected_answer, list):
        record_answer(current, "text", text_answer=" | ".join(selected_answer))
    else:
        record_answer(current, "text", text_answer=selected_answer)

async def _answer_qq_score_like(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> None:
    config = ctx.config
    current = int(question.num or 0)
    option_count = max(2, int(question.options or 0))
    probabilities = config.scale_prob[config_index] if config_index < len(config.scale_prob) else -1
    probs = normalize_droplist_probs(probabilities, option_count)
    probs = apply_single_like_consistency(probs, current)
    probs = resolve_distribution_probabilities(
        probs,
        option_count,
        ctx,
        current,
        psycho_plan=psycho_plan,
    )
    selected_index = get_tendency_index(
        option_count,
        probs,
        dimension=config.question_dimension_map.get(current),
        psycho_plan=psycho_plan,
        question_index=current,
    )
    if not await _click_choice_input(driver, str(question.provider_question_id or ""), "radio", selected_index):
        logging.warning("腾讯问卷第%d题（评分）点击未生效。", current)
        return
    record_pending_distribution_choice(ctx, current, selected_index, option_count)
    record_answer(current, "score", selected_indices=[selected_index])

async def _answer_qq_matrix(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> int:
    config = ctx.config
    current = int(question.num or 0)
    question_id = str(question.provider_question_id or "")
    row_count = max(1, int(question.rows or 1))
    option_count = max(2, int(question.options or 0))
    option_texts = list(question.option_texts or [])
    strict_ratio_question = is_strict_ratio_question(ctx, current)
    next_index = config_index
    for row_index in range(row_count):
        raw_probabilities = config.matrix_prob[next_index] if next_index < len(config.matrix_prob) else -1
        next_index += 1
        strict_reference: Optional[List[float]] = None
        row_probabilities: Any = -1
        if isinstance(raw_probabilities, list):
            try:
                probs = [float(value) for value in raw_probabilities]
            except Exception:
                probs = []
            if len(probs) != option_count:
                probs = [1.0] * option_count
            strict_reference = list(probs)
            probs = apply_matrix_row_consistency(probs, current, row_index)
            if any(prob > 0 for prob in probs):
                row_probabilities = resolve_distribution_probabilities(
                    probs,
                    option_count,
                    ctx,
                    current,
                    row_index=row_index,
                    psycho_plan=psycho_plan,
                )
        else:
            uniform_probs = apply_matrix_row_consistency([1.0] * option_count, current, row_index)
            if any(prob > 0 for prob in uniform_probs):
                row_probabilities = resolve_distribution_probabilities(
                    uniform_probs,
                    option_count,
                    ctx,
                    current,
                    row_index=row_index,
                    psycho_plan=psycho_plan,
                )
        if strict_ratio_question and isinstance(row_probabilities, list):
            row_probabilities = enforce_reference_rank_order(row_probabilities, strict_reference or row_probabilities)
        selected_index = get_tendency_index(
            option_count,
            row_probabilities,
            dimension=config.question_dimension_map.get(current),
            psycho_plan=psycho_plan,
            question_index=current,
            row_index=row_index,
        )
        if not await _click_matrix_cell(driver, question_id, row_index, selected_index):
            logging.warning("腾讯问卷第%d题（矩阵）第%d行点击失败。", current, row_index + 1)
            continue
        record_pending_distribution_choice(ctx, current, selected_index, option_count, row_index=row_index)
        _log_qq_matrix_row_choice(
            current,
            row_index + 1,
            selected_index,
            option_texts,
            row_probabilities,
            raw_probabilities,
        )
        record_answer(current, "matrix", selected_indices=[selected_index], row_index=row_index)
    return next_index

async def _answer_qq_multiple(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> None:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = list(question.option_texts or [])
    option_count = max(1, len(option_texts) or int(question.options or 0))
    min_required = int(question.multi_min_limit or 1)
    max_allowed = int(question.multi_max_limit or option_count or 1)
    min_required = max(1, min(min_required, option_count))
    max_allowed = max(1, min(max_allowed, option_count))
    if min_required > max_allowed:
        min_required = max_allowed

    must_select_indices, must_not_select_indices, _ = get_multiple_rule_constraint(current, option_count)
    required_indices = _normalize_selected_indices(sorted(must_select_indices or []), option_count)
    blocked_indices = _normalize_selected_indices(sorted(must_not_select_indices or []), option_count)

    async def _apply(selected_indices: Sequence[int]) -> List[int]:
        applied = []
        question_id = str(question.provider_question_id or "")
        fill_entries = (
            config.multiple_option_fill_texts[config_index]
            if config_index < len(config.multiple_option_fill_texts)
            else None
        )
        for option_idx in selected_indices:
            if await _click_choice_input(driver, question_id, "checkbox", option_idx):
                fill_value = await resolve_runtime_option_fill_text_from_config(
                    fill_entries,
                    option_idx,
                    driver=driver,
                    question_number=current,
                    option_text=option_texts[option_idx] if option_idx < len(option_texts) else "",
                )
                if fill_value:
                    await _fill_choice_option_additional_text(
                        driver,
                        question_id,
                        option_idx,
                        fill_value,
                        input_type="checkbox",
                    )
                applied.append(option_idx)
        return applied

    selection_probabilities = (
        config.multiple_prob[config_index]
        if config_index < len(config.multiple_prob)
        else [50.0] * option_count
    )
    if selection_probabilities == -1 or (
        isinstance(selection_probabilities, list)
        and len(selection_probabilities) == 1
        and selection_probabilities[0] == -1
    ):
        available_pool = [idx for idx in range(option_count) if idx not in blocked_indices and idx not in required_indices]
        min_total = max(min_required, len(required_indices))
        max_total = min(max_allowed, len(required_indices) + len(available_pool))
        if min_total > max_total:
            min_total = max_total
        extra_min = max(0, min_total - len(required_indices))
        extra_max = max(0, max_total - len(required_indices))
        extra_count = random.randint(extra_min, extra_max) if extra_max >= extra_min else 0
        sampled = random.sample(available_pool, extra_count) if extra_count > 0 else []
        selected = _apply_multiple_constraints(
            list(required_indices) + sampled,
            option_count,
            min_required,
            max_allowed,
            required_indices,
            blocked_indices,
            available_pool,
        )
        confirmed = await _apply(selected)
        if confirmed:
            selected_texts = [option_texts[i] for i in confirmed if i < len(option_texts)]
            record_answer(current, "multiple", selected_indices=confirmed, selected_texts=selected_texts)
        return

    sanitized_probabilities: List[float] = []
    for raw_prob in selection_probabilities:
        try:
            prob_value = float(raw_prob)
        except Exception:
            prob_value = 0.0
        prob_value = max(0.0, min(100.0, prob_value))
        sanitized_probabilities.append(prob_value)
    if len(sanitized_probabilities) < option_count:
        sanitized_probabilities.extend([0.0] * (option_count - len(sanitized_probabilities)))
    elif len(sanitized_probabilities) > option_count:
        sanitized_probabilities = sanitized_probabilities[:option_count]

    strict_ratio = is_strict_ratio_question(ctx, current)
    if not strict_ratio:
        boosted = apply_persona_boost(option_texts, sanitized_probabilities)
        sanitized_probabilities = [min(100.0, prob) for prob in boosted]
    for idx in blocked_indices:
        sanitized_probabilities[idx] = 0.0
    for idx in required_indices:
        sanitized_probabilities[idx] = 0.0

    if strict_ratio:
        positive_optional = [
            idx for idx, prob in enumerate(sanitized_probabilities)
            if prob > 0 and idx not in blocked_indices and idx not in required_indices
        ]
        required_selected = _normalize_selected_indices(required_indices, option_count)
        if len(required_selected) > max_allowed:
            required_selected = required_selected[:max_allowed]
        min_total = max(min_required, len(required_selected))
        max_total = min(max_allowed, len(required_selected) + len(positive_optional))
        if min_total > max_total:
            min_total = max_total
        expected_optional = sum(sanitized_probabilities[idx] for idx in positive_optional) / 100.0
        total_target = len(required_selected) + stochastic_round(expected_optional)
        total_target = max(min_total, min(max_total, total_target))
        optional_target = max(0, total_target - len(required_selected))
        sampled_optional = weighted_sample_without_replacement(
            positive_optional,
            [sanitized_probabilities[idx] for idx in positive_optional],
            optional_target,
        )
        selected = _normalize_selected_indices(required_selected + sampled_optional, option_count)
        confirmed = await _apply(selected)
        if confirmed:
            selected_texts = [option_texts[i] for i in confirmed if i < len(option_texts)]
            record_answer(current, "multiple", selected_indices=confirmed, selected_texts=selected_texts)
        return

    positive_indices = [idx for idx, prob in enumerate(sanitized_probabilities) if prob > 0]
    if not positive_indices and not required_indices:
        return
    selection_mask: List[int] = []
    attempts = 0
    max_attempts = 32
    if positive_indices:
        while sum(selection_mask) == 0 and attempts < max_attempts:
            selection_mask = [1 if random.random() < (prob / 100.0) else 0 for prob in sanitized_probabilities]
            attempts += 1
        if sum(selection_mask) == 0:
            selection_mask = [0] * option_count
            selection_mask[random.choice(positive_indices)] = 1
    selected = [
        idx for idx, selected_flag in enumerate(selection_mask)
        if selected_flag == 1 and sanitized_probabilities[idx] > 0
    ]
    selected = _apply_multiple_constraints(
        selected,
        option_count,
        min_required,
        max_allowed,
        required_indices,
        blocked_indices,
        positive_indices,
    )
    if not selected and positive_indices:
        selected = [random.choice(positive_indices)]
    confirmed = await _apply(selected)
    if confirmed:
        selected_texts = [option_texts[i] for i in confirmed if i < len(option_texts)]
        record_answer(current, "multiple", selected_indices=confirmed, selected_texts=selected_texts)


async def _answer_qq_matrix_star(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> int:
    """处理腾讯问卷矩阵星级题（matrix_star）。

    逻辑与普通矩阵题相同，但用 _click_star_cell 代替 _click_matrix_cell，
    因为星级组件基于 TDesign t-rate，不含 input[type="radio"]。
    """
    config = ctx.config
    current = int(question.num or 0)
    question_id = str(question.provider_question_id or "")
    row_count = max(1, int(question.rows or 1))
    option_count = max(2, int(question.options or 0))
    option_texts = list(question.option_texts or [])
    strict_ratio_question = is_strict_ratio_question(ctx, current)
    next_index = config_index
    for row_index in range(row_count):
        raw_probabilities = config.matrix_prob[next_index] if next_index < len(config.matrix_prob) else -1
        next_index += 1
        strict_reference: Optional[List[float]] = None
        row_probabilities: Any = -1
        if isinstance(raw_probabilities, list):
            try:
                probs = [float(value) for value in raw_probabilities]
            except Exception:
                probs = []
            if len(probs) != option_count:
                probs = [1.0] * option_count
            strict_reference = list(probs)
            probs = apply_matrix_row_consistency(probs, current, row_index)
            if any(prob > 0 for prob in probs):
                row_probabilities = resolve_distribution_probabilities(
                    probs,
                    option_count,
                    ctx,
                    current,
                    row_index=row_index,
                    psycho_plan=psycho_plan,
                )
        else:
            uniform_probs = apply_matrix_row_consistency([1.0] * option_count, current, row_index)
            if any(prob > 0 for prob in uniform_probs):
                row_probabilities = resolve_distribution_probabilities(
                    uniform_probs,
                    option_count,
                    ctx,
                    current,
                    row_index=row_index,
                    psycho_plan=psycho_plan,
                )
        if strict_ratio_question and isinstance(row_probabilities, list):
            row_probabilities = enforce_reference_rank_order(row_probabilities, strict_reference or row_probabilities)
        selected_index = get_tendency_index(
            option_count,
            row_probabilities,
            dimension=config.question_dimension_map.get(current),
            psycho_plan=psycho_plan,
            question_index=current,
            row_index=row_index,
        )
        clicked = await _click_star_cell(driver, question_id, row_index, selected_index)
        if not clicked:
            clicked = await _click_matrix_cell(driver, question_id, row_index, selected_index)
            if not clicked:
                logging.warning("腾讯问卷第%d题（矩阵星级）第%d行点击失败。", current, row_index + 1)
                continue
        record_pending_distribution_choice(ctx, current, selected_index, option_count, row_index=row_index)
        _log_qq_matrix_row_choice(
            current,
            row_index + 1,
            selected_index,
            option_texts,
            row_probabilities,
            raw_probabilities,
        )
        record_answer(current, "matrix", selected_indices=[selected_index], row_index=row_index)
    return next_index


async def _build_qq_single_action(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    question_id = str(question.provider_question_id or "")
    option_texts = list(question.option_texts or [])
    raw_option_count = len(option_texts) or int(question.options or 0)
    if raw_option_count <= 0:
        return None
    option_count = max(1, raw_option_count)
    probabilities = config.single_prob[config_index] if config_index < len(config.single_prob) else -1
    probabilities = normalize_droplist_probs(probabilities, option_count)
    strict_ratio = is_strict_ratio_question(ctx, current)
    if not strict_ratio:
        probabilities = apply_persona_boost(option_texts, probabilities)
    probabilities = apply_single_like_consistency(probabilities, current)
    if strict_ratio:
        strict_reference = list(probabilities)
        probabilities = resolve_distribution_probabilities(probabilities, option_count, ctx, current)
        probabilities = enforce_reference_rank_order(probabilities, strict_reference)
    selected_index = weighted_index(probabilities)
    selected_text = option_texts[selected_index] if selected_index < len(option_texts) else ""
    fill_entries = config.single_option_fill_texts[config_index] if config_index < len(config.single_option_fill_texts) else None
    fill_value = await resolve_runtime_option_fill_text_from_config(
        fill_entries,
        selected_index,
        driver=driver,
        question_number=current,
        option_text=selected_text,
    )
    selected_texts = [f"{selected_text} / {fill_value}" if selected_text and fill_value else (fill_value or selected_text)]
    return AnswerAction(
        question_num=current,
        question_id=question_id,
        kind="choice",
        input_type="radio",
        selected_indices=(selected_index,),
        option_fill_texts=((selected_index, fill_value),) if fill_value else (),
        selected_texts=tuple(selected_texts),
        record_type="single",
        pending_distribution_choices=((selected_index, option_count, None),) if strict_ratio else (),
    )


async def _build_qq_text_action(
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    blank_count = max(1, int(getattr(question, "text_inputs", 1) or 1))
    text_entry_types = list(getattr(ctx.config, "text_entry_types", []) or [])
    multi_text_blank_modes = list(getattr(ctx.config, "multi_text_blank_modes", []) or [])
    multi_text_blank_ranges = list(getattr(ctx.config, "multi_text_blank_int_ranges", []) or [])
    text_values = resolve_runtime_text_values_from_config(
        config.texts[config_index] if config_index < len(config.texts) else [DEFAULT_FILL_TEXT],
        config.texts_prob[config_index] if config_index < len(config.texts_prob) else [1.0],
        blank_count=blank_count,
        entry_type=str(text_entry_types[config_index] if config_index < len(text_entry_types) else "text"),
        blank_modes=multi_text_blank_modes[config_index] if config_index < len(multi_text_blank_modes) else [],
        blank_int_ranges=multi_text_blank_ranges[config_index] if config_index < len(multi_text_blank_ranges) else [],
    )
    ai_enabled = bool(config.text_ai_flags[config_index]) if config_index < len(config.text_ai_flags) else False
    if ai_enabled:
        title = str(question.title or "")
        description = str(question.description or "").strip()
        ai_prompt = title.strip()
        if description and description not in ai_prompt:
            ai_prompt = f"{ai_prompt}\n补充说明：{description}"
        try:
            generated = await agenerate_ai_answer(ai_prompt, question_type="fill_blank", blank_count=1)
        except AIRuntimeError as exc:
            raise AIRuntimeError(f"腾讯问卷第{current}题 AI 生成失败：{exc}") from exc
        text_values = (
            [str(item or "").strip() or DEFAULT_FILL_TEXT for item in list(generated or [])]
            if isinstance(generated, list)
            else [str(generated or "").strip() or DEFAULT_FILL_TEXT]
        )
    if len(text_values) < blank_count:
        text_values.extend([text_values[-1] if text_values else DEFAULT_FILL_TEXT] * (blank_count - len(text_values)))
    return AnswerAction(
        question_num=current,
        question_id=str(question.provider_question_id or ""),
        kind="text",
        text_values=tuple(str(item or "").strip() or DEFAULT_FILL_TEXT for item in text_values[:blank_count]),
        record_type="text",
    )


async def _build_qq_score_like_action(
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    raw_option_count = int(question.options or 0)
    if raw_option_count <= 0:
        return None
    option_count = max(2, raw_option_count)
    probabilities = config.scale_prob[config_index] if config_index < len(config.scale_prob) else -1
    probs = normalize_droplist_probs(probabilities, option_count)
    probs = apply_single_like_consistency(probs, current)
    probs = resolve_distribution_probabilities(
        probs,
        option_count,
        ctx,
        current,
        psycho_plan=psycho_plan,
    )
    selected_index = get_tendency_index(
        option_count,
        probs,
        dimension=config.question_dimension_map.get(current),
        psycho_plan=psycho_plan,
        question_index=current,
    )
    return AnswerAction(
        question_num=current,
        question_id=str(question.provider_question_id or ""),
        kind="choice",
        input_type="radio",
        selected_indices=(selected_index,),
        record_type="score",
        pending_distribution_choices=((selected_index, option_count, None),),
    )


async def _build_qq_multiple_action(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = list(question.option_texts or [])
    raw_option_count = len(option_texts) or int(question.options or 0)
    if raw_option_count <= 0:
        return None
    option_count = max(1, raw_option_count)
    min_required = int(question.multi_min_limit or 1)
    max_allowed = int(question.multi_max_limit or option_count or 1)
    min_required = max(1, min(min_required, option_count))
    max_allowed = max(1, min(max_allowed, option_count))
    if min_required > max_allowed:
        min_required = max_allowed

    must_select_indices, must_not_select_indices, _ = get_multiple_rule_constraint(current, option_count)
    required_indices = _normalize_selected_indices(sorted(must_select_indices or []), option_count)
    blocked_indices = _normalize_selected_indices(sorted(must_not_select_indices or []), option_count)

    async def _finalize(selected_indices: Sequence[int]) -> Optional[AnswerAction]:
        selected = _normalize_selected_indices(selected_indices, option_count)
        if not selected:
            return None
        fill_entries = config.multiple_option_fill_texts[config_index] if config_index < len(config.multiple_option_fill_texts) else None
        fill_texts: list[tuple[int, str]] = []
        selected_texts: list[str] = []
        for option_idx in selected:
            selected_text = option_texts[option_idx] if option_idx < len(option_texts) else ""
            fill_value = await resolve_runtime_option_fill_text_from_config(
                fill_entries,
                option_idx,
                driver=driver,
                question_number=current,
                option_text=selected_text,
            )
            if fill_value:
                fill_texts.append((option_idx, fill_value))
                selected_text = f"{selected_text} / {fill_value}" if selected_text else fill_value
            selected_texts.append(selected_text)
        return AnswerAction(
            question_num=current,
            question_id=str(question.provider_question_id or ""),
            kind="choice",
            input_type="checkbox",
            selected_indices=tuple(selected),
            option_fill_texts=tuple(fill_texts),
            selected_texts=tuple(selected_texts),
            record_type="multiple",
        )

    selection_probabilities = config.multiple_prob[config_index] if config_index < len(config.multiple_prob) else [50.0] * option_count
    if selection_probabilities == -1 or (
        isinstance(selection_probabilities, list)
        and len(selection_probabilities) == 1
        and selection_probabilities[0] == -1
    ):
        available_pool = [idx for idx in range(option_count) if idx not in blocked_indices and idx not in required_indices]
        min_total = max(min_required, len(required_indices))
        max_total = min(max_allowed, len(required_indices) + len(available_pool))
        if min_total > max_total:
            min_total = max_total
        extra_min = max(0, min_total - len(required_indices))
        extra_max = max(0, max_total - len(required_indices))
        extra_count = random.randint(extra_min, extra_max) if extra_max >= extra_min else 0
        sampled = random.sample(available_pool, extra_count) if extra_count > 0 else []
        selected = _apply_multiple_constraints(
            list(required_indices) + sampled,
            option_count,
            min_required,
            max_allowed,
            required_indices,
            blocked_indices,
            available_pool,
        )
        return await _finalize(selected)

    sanitized_probabilities: List[float] = []
    for raw_prob in selection_probabilities:
        try:
            prob_value = float(raw_prob)
        except Exception:
            prob_value = 0.0
        sanitized_probabilities.append(max(0.0, min(100.0, prob_value)))
    if len(sanitized_probabilities) < option_count:
        sanitized_probabilities.extend([0.0] * (option_count - len(sanitized_probabilities)))
    elif len(sanitized_probabilities) > option_count:
        sanitized_probabilities = sanitized_probabilities[:option_count]

    strict_ratio = is_strict_ratio_question(ctx, current)
    if not strict_ratio:
        boosted = apply_persona_boost(option_texts, sanitized_probabilities)
        sanitized_probabilities = [min(100.0, prob) for prob in boosted]
    for idx in blocked_indices:
        sanitized_probabilities[idx] = 0.0
    for idx in required_indices:
        sanitized_probabilities[idx] = 0.0

    if strict_ratio:
        positive_optional = [
            idx for idx, prob in enumerate(sanitized_probabilities)
            if prob > 0 and idx not in blocked_indices and idx not in required_indices
        ]
        required_selected = _normalize_selected_indices(required_indices, option_count)
        if len(required_selected) > max_allowed:
            required_selected = required_selected[:max_allowed]
        min_total = max(min_required, len(required_selected))
        max_total = min(max_allowed, len(required_selected) + len(positive_optional))
        if min_total > max_total:
            min_total = max_total
        expected_optional = sum(sanitized_probabilities[idx] for idx in positive_optional) / 100.0
        total_target = len(required_selected) + stochastic_round(expected_optional)
        total_target = max(min_total, min(max_total, total_target))
        optional_target = max(0, total_target - len(required_selected))
        sampled_optional = weighted_sample_without_replacement(
            positive_optional,
            [sanitized_probabilities[idx] for idx in positive_optional],
            optional_target,
        )
        return await _finalize(required_selected + sampled_optional)

    positive_indices = [idx for idx, prob in enumerate(sanitized_probabilities) if prob > 0]
    if not positive_indices and not required_indices:
        return None
    selection_mask: List[int] = []
    attempts = 0
    max_attempts = 32
    if positive_indices:
        while sum(selection_mask) == 0 and attempts < max_attempts:
            selection_mask = [1 if random.random() < (prob / 100.0) else 0 for prob in sanitized_probabilities]
            attempts += 1
        if sum(selection_mask) == 0:
            selection_mask = [0] * option_count
            selection_mask[random.choice(positive_indices)] = 1
    selected = [
        idx for idx, selected_flag in enumerate(selection_mask)
        if selected_flag == 1 and sanitized_probabilities[idx] > 0
    ]
    selected = _apply_multiple_constraints(
        selected,
        option_count,
        min_required,
        max_allowed,
        required_indices,
        blocked_indices,
        positive_indices,
    )
    if not selected and positive_indices:
        selected = [random.choice(positive_indices)]
    return await _finalize(selected)


async def _build_qq_matrix_action(
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    row_count = max(1, int(question.rows or 1))
    raw_option_count = int(question.options or 0)
    if raw_option_count <= 0:
        return None
    option_count = max(2, raw_option_count)
    strict_ratio_question = is_strict_ratio_question(ctx, current)
    next_index = config_index
    selected_indices: list[int] = []
    pending: list[tuple[int, int, Optional[int]]] = []
    for row_index in range(row_count):
        raw_probabilities = config.matrix_prob[next_index] if next_index < len(config.matrix_prob) else -1
        next_index += 1
        strict_reference: Optional[List[float]] = None
        row_probabilities: Any = -1
        if isinstance(raw_probabilities, list):
            try:
                probs = [float(value) for value in raw_probabilities]
            except Exception:
                probs = []
            if len(probs) != option_count:
                probs = [1.0] * option_count
            strict_reference = list(probs)
            probs = apply_matrix_row_consistency(probs, current, row_index)
            if any(prob > 0 for prob in probs):
                row_probabilities = resolve_distribution_probabilities(
                    probs,
                    option_count,
                    ctx,
                    current,
                    row_index=row_index,
                    psycho_plan=psycho_plan,
                )
        else:
            uniform_probs = apply_matrix_row_consistency([1.0] * option_count, current, row_index)
            if any(prob > 0 for prob in uniform_probs):
                row_probabilities = resolve_distribution_probabilities(
                    uniform_probs,
                    option_count,
                    ctx,
                    current,
                    row_index=row_index,
                    psycho_plan=psycho_plan,
                )
        if strict_ratio_question and isinstance(row_probabilities, list):
            row_probabilities = enforce_reference_rank_order(row_probabilities, strict_reference or row_probabilities)
        selected_index = get_tendency_index(
            option_count,
            row_probabilities,
            dimension=config.question_dimension_map.get(current),
            psycho_plan=psycho_plan,
            question_index=current,
            row_index=row_index,
        )
        selected_indices.append(selected_index)
        pending.append((selected_index, option_count, row_index))
    return AnswerAction(
        question_num=current,
        question_id=str(question.provider_question_id or ""),
        kind="matrix",
        matrix_indices=tuple(selected_indices),
        record_type="matrix",
        pending_distribution_choices=tuple(pending),
    )


async def build_answer_action(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> Optional[AnswerAction]:
    if bool(getattr(question, "has_jump", False)) or bool(getattr(question, "has_dependent_display_logic", False)):
        return None
    question_id = str(getattr(question, "provider_question_id", "") or "").strip()
    if not question_id:
        return None
    config_entry = ctx.config.question_config_index_map.get(int(question.num or 0))
    if not config_entry:
        return None
    entry_type, config_index = config_entry
    required_config_fields = {
        "single": ("single_prob", "single_option_fill_texts"),
        "multiple": ("multiple_prob", "multiple_option_fill_texts"),
        "text": ("texts", "texts_prob", "text_ai_flags"),
        "multi_text": ("texts", "texts_prob", "text_ai_flags"),
        "scale": ("scale_prob",),
        "score": ("scale_prob",),
        "matrix": ("matrix_prob",),
    }.get(entry_type)
    if not required_config_fields or not all(hasattr(ctx.config, field_name) for field_name in required_config_fields):
        return None
    if entry_type == "single":
        return await _build_qq_single_action(driver, question, config_index, ctx)
    if entry_type == "multiple":
        return await _build_qq_multiple_action(driver, question, config_index, ctx)
    if entry_type in {"text", "multi_text"}:
        return await _build_qq_text_action(question, config_index, ctx)
    if entry_type in {"scale", "score"}:
        return await _build_qq_score_like_action(question, config_index, ctx, psycho_plan=psycho_plan)
    if entry_type == "matrix" and getattr(question, "provider_type", "") != "matrix_star":
        return await _build_qq_matrix_action(question, config_index, ctx, psycho_plan=psycho_plan)
    return None


async def apply_answer_actions(driver: BrowserDriver, actions: Sequence[AnswerAction]) -> BatchFillResult:
    normalized_actions = [
        action
        for action in list(actions or [])
        if int(action.question_num or 0) > 0 and str(action.question_id or "").strip()
    ]
    if not normalized_actions:
        return BatchFillResult()
    page = await driver.page()
    if page is None:
        return BatchFillResult(failed=tuple(int(action.question_num) for action in normalized_actions))
    payload = [_action_payload(action) for action in normalized_actions]
    try:
        raw_result = await page.evaluate(
            r"""(actions) => {
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const dispatch = (target, names = ['input', 'change', 'click']) => {
                    for (const name of names) {
                        try { target.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                    }
                };
                const setNativeValue = (target, value) => {
                    const nextValue = String(value ?? '');
                    try {
                        const proto = target.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement?.prototype : window.HTMLInputElement?.prototype;
                        const descriptor = proto ? Object.getOwnPropertyDescriptor(proto, 'value') : null;
                        if (descriptor && descriptor.set) descriptor.set.call(target, nextValue);
                        else target.value = nextValue;
                    } catch (e) {
                        try { target.value = nextValue; } catch (err) {}
                    }
                    try { target.setAttribute('value', nextValue); } catch (e) {}
                    dispatch(target, ['input', 'change', 'blur']);
                };
                const isTextInput = (el) => {
                    if (!el) return false;
                    const tag = String(el.tagName || '').toLowerCase();
                    if (tag === 'textarea') return true;
                    if (tag !== 'input') return false;
                    const type = String(el.getAttribute('type') || '').toLowerCase();
                    return !type || ['text', 'search', 'tel', 'number'].includes(type);
                };
                const clickChoice = (section, inputType, optionIndex) => {
                    const inputs = Array.from(section.querySelectorAll(`input[type="${inputType}"]`)).filter(visible);
                    const target = inputs[optionIndex] || null;
                    if (!target) return false;
                    const candidates = [
                        target.closest('label'),
                        target.closest('.question-option'),
                        target.closest('.option'),
                        target.closest('.t-radio'),
                        target.closest('.t-checkbox'),
                        target.parentElement,
                        target,
                    ].filter(Boolean);
                    for (const node of candidates) {
                        try { node.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                        try { node.click(); } catch (e) {}
                        if (target.checked) return true;
                    }
                    try { target.checked = true; } catch (e) {}
                    dispatch(target);
                    return !!target.checked;
                };
                const fillOptionText = (section, optionIndex, value, inputType) => {
                    const text = String(value || '').trim();
                    if (!text) return true;
                    const optionInputs = Array.from(section.querySelectorAll(`input[type="${inputType}"]`)).filter(visible);
                    const targetInput = optionInputs[optionIndex] || null;
                    const containers = [
                        targetInput?.closest('.question-option'),
                        targetInput?.closest('.option'),
                        targetInput?.closest('.t-radio'),
                        targetInput?.closest('.t-checkbox'),
                        targetInput?.closest('.question-item'),
                        targetInput?.closest('label'),
                        targetInput?.parentElement,
                    ].filter(Boolean);
                    for (const container of containers) {
                        const target = Array.from(container.querySelectorAll('textarea, input')).find((el) => visible(el) && isTextInput(el));
                        if (!target) continue;
                        setNativeValue(target, text);
                        return String(target.value || '') === text;
                    }
                    return false;
                };
                const applyText = (section, values) => {
                    const textValues = Array.isArray(values) && values.length ? values.map((item) => String(item ?? '')) : [''];
                    const inputs = Array.from(section.querySelectorAll('textarea, input')).filter((el) => visible(el) && isTextInput(el));
                    if (!inputs.length) return false;
                    let applied = 0;
                    inputs.forEach((target, index) => {
                        const value = textValues[index] ?? textValues[textValues.length - 1] ?? '';
                        try { target.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                        try { target.focus(); } catch (e) {}
                        setNativeValue(target, value);
                        if (String(target.value || '') === value) applied += 1;
                    });
                    return applied > 0 && applied >= Math.min(inputs.length, textValues.length);
                };
                const applyMatrix = (section, indices) => {
                    const tableRows = Array.from(section.querySelectorAll('tbody tr')).filter((row) => row && row.querySelector('input[type="radio"]') && visible(row));
                    const blockRows = Array.from(section.querySelectorAll('.question-item')).filter((row) => row && row.querySelector('input[type="radio"]') && visible(row));
                    const rows = tableRows.length ? tableRows : blockRows;
                    if (!rows.length) return false;
                    let applied = 0;
                    indices.forEach((rawIndex, rowIndex) => {
                        const colIndex = Number(rawIndex);
                        const row = rows[rowIndex];
                        if (!row || colIndex < 0) return;
                        const inputs = Array.from(row.querySelectorAll('input[type="radio"]')).filter(visible);
                        const target = inputs[colIndex] || null;
                        if (!target) return;
                        const candidates = [
                            target.closest('label'),
                            target.closest('.checkbtn'),
                            target.closest('.matrix-option'),
                            target.closest('td'),
                            target.parentElement,
                            target,
                        ].filter(Boolean);
                        for (const node of candidates) {
                            try { node.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                            try { node.click(); } catch (e) {}
                            if (target.checked) break;
                        }
                        if (!target.checked) {
                            try { target.checked = true; } catch (e) {}
                            dispatch(target);
                        }
                        if (target.checked) applied += 1;
                    });
                    return applied === indices.length;
                };
                const applied = [];
                const failed = [];
                for (const action of actions || []) {
                    const questionNum = Number(action.questionNum || 0);
                    const section = document.querySelector(`section.question[data-question-id="${action.questionId}"]`);
                    if (!section || !visible(section)) {
                        failed.push(questionNum);
                        continue;
                    }
                    let ok = false;
                    try {
                        if (action.kind === 'choice') {
                            const selected = Array.isArray(action.selectedIndices) ? action.selectedIndices : [];
                            ok = selected.length > 0 && selected.every((index) => clickChoice(section, action.inputType || 'radio', Number(index)));
                            if (ok && Array.isArray(action.optionFillTexts)) {
                                ok = action.optionFillTexts.every((item) => fillOptionText(section, Number(item.optionIndex), item.value, action.inputType || 'radio'));
                            }
                        } else if (action.kind === 'text') {
                            ok = applyText(section, action.textValues);
                        } else if (action.kind === 'matrix') {
                            ok = applyMatrix(section, action.matrixIndices || []);
                        }
                    } catch (e) {
                        ok = false;
                    }
                    if (ok) applied.push(questionNum);
                    else failed.push(questionNum);
                }
                return { applied, failed };
            }""",
            payload,
        ) or {}
    except Exception:
        return BatchFillResult(failed=tuple(int(action.question_num) for action in normalized_actions))
    applied = tuple(int(item) for item in list(raw_result.get("applied") or []) if int(item or 0) > 0) if isinstance(raw_result, dict) else ()
    failed = tuple(int(item) for item in list(raw_result.get("failed") or []) if int(item or 0) > 0) if isinstance(raw_result, dict) else tuple(int(action.question_num) for action in normalized_actions)
    return BatchFillResult(applied=applied, failed=failed)


async def answer_page_batch(
    driver: BrowserDriver,
    questions: Sequence[SurveyQuestionMeta],
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> BatchFillResult:
    actions: list[AnswerAction] = []
    skipped: list[int] = []
    for question in list(questions or []):
        question_num = int(getattr(question, "num", 0) or 0)
        if question_num <= 0:
            continue
        action = await build_answer_action(driver, question, ctx, psycho_plan=psycho_plan)
        if action is None:
            skipped.append(question_num)
            continue
        actions.append(action)
    if not actions:
        return BatchFillResult(skipped=tuple(skipped))
    result = await apply_answer_actions(driver, actions)
    action_by_num = {int(action.question_num): action for action in actions}
    for question_num in result.applied:
        action = action_by_num.get(int(question_num))
        if action is not None:
            _record_answer_action(ctx, action)
    return BatchFillResult(
        applied=tuple(result.applied),
        failed=tuple(result.failed),
        skipped=tuple(skipped),
    )
