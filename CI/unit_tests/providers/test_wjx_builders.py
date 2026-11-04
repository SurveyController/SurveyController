from __future__ import annotations

import pytest

from software.core.task import ExecutionConfig, ExecutionState
from surveycore.providers.contracts import SurveyQuestionMeta
from wjx.provider import answering_builders as wjx_builders
from wjx.provider import http_runtime as wjx_http

from .http_runtime_fakes import _async_result


@pytest.mark.asyncio
async def test_wjx_builder_allows_logic_question_for_http(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="wjx")
    config.question_config_index_map = {1: ("single", 0)}
    config.single_prob = [[0.0, 1.0]]
    config.single_option_fill_texts = [None]
    state = ExecutionState(config=config)
    question = SurveyQuestionMeta(
        num=1,
        title="Q1",
        type_code="3",
        has_jump=True,
        logic_parse_status="complete",
        jump_rules=[{"option_index": 1, "jumpto": 2}],
        option_texts=["A", "B"],
        options=2,
    )

    monkeypatch.setattr(wjx_builders, "weighted_index", lambda _probs: 1)
    monkeypatch.setattr(wjx_builders, "resolve_option_fill_text_from_config", _async_result(None))

    action = await wjx_builders.build_answer_action(None, question, state, psycho_plan=None)

    assert action is not None
    assert action.selected_indices == (1,)


@pytest.mark.asyncio
async def test_wjx_builder_defaults_selected_fillable_option_text() -> None:
    config = ExecutionConfig(survey_provider="wjx")
    config.question_config_index_map = {9: ("single", 0)}
    config.single_prob = [[0.0, 1.0, 0.0]]
    config.single_option_fill_texts = [None]
    state = ExecutionState(config=config)
    question = SurveyQuestionMeta(
        num=9,
        title="您对乌江寨整体的满意度如何？",
        type_code="3",
        option_texts=["非常满意", "一般（需要我们改进的地方）", "不满意（需要我们改进的地方）"],
        options=3,
        fillable_options=[1, 2],
    )

    action = await wjx_builders.build_answer_action(None, question, state, psycho_plan=None)

    assert action is not None
    assert action.selected_indices == (1,)
    assert action.option_fill_texts == ((1, "无"),)
    assert wjx_http._submitdata_from_actions([action], questions=[question]) == "9$2^无"


@pytest.mark.asyncio
async def test_wjx_builder_uses_prefilled_ai_text_answer(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="wjx")
    config.question_config_index_map = {1: ("text", 0)}
    config.text_ai_flags = [True]
    state = ExecutionState(config=config)
    state.set_ai_prefill_answers("slot-1", {1: ("预填答案",)})
    question = SurveyQuestionMeta(
        num=1,
        title="请填写职业",
        type_code="1",
        text_inputs=1,
    )

    async def fail_generate(*_args, **_kwargs):
        raise AssertionError("命中预取答案后不该再调用单题 AI")

    monkeypatch.setattr(wjx_builders, "agenerate_ai_answer", fail_generate)

    action = await wjx_builders.build_answer_action(
        None,
        question,
        state,
        psycho_plan=None,
        thread_name="slot-1",
    )

    assert action is not None
    assert action.kind == "text"
    assert action.text_values == ("预填答案",)


@pytest.mark.asyncio
async def test_wjx_builder_uses_prefilled_ai_option_fill_answer(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="wjx")
    config.question_config_index_map = {1: ("single", 0)}
    config.single_prob = [[1.0, 0.0]]
    config.single_option_fill_texts = [["__AI_FILL__", None]]
    state = ExecutionState(config=config)
    state.set_ai_option_fill_prefill_answers("slot-opt-1", {(1, 0): "补充说明"})
    question = SurveyQuestionMeta(
        num=1,
        title="请选择水果",
        type_code="3",
        option_texts=["苹果", "香蕉"],
        options=2,
    )

    async def fail_option_fill(*_args, **_kwargs):
        raise AssertionError("命中附加填空预取后不该再调用单题 AI")

    monkeypatch.setattr(wjx_builders, "weighted_index", lambda _probs: 0)
    monkeypatch.setattr(wjx_builders, "agenerate_ai_answer", fail_option_fill)

    action = await wjx_builders.build_answer_action(
        None,
        question,
        state,
        psycho_plan=None,
        thread_name="slot-opt-1",
    )

    assert action is not None
    assert action.option_fill_texts == ((0, "补充说明"),)
