from __future__ import annotations

import pytest

from software.core.task import ExecutionConfig, ExecutionState
from surveycore.providers.contracts import SurveyQuestionMeta
from tencent.provider import answering_builders as qq_builders

from .http_runtime_fakes import _async_result


@pytest.mark.asyncio
async def test_qq_builder_supports_dropdown_and_matrix_star_for_http(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="qq")
    config.question_config_index_map = {
        1: ("dropdown", 0),
        2: ("matrix", 0),
    }
    config.droplist_prob = [[0.0, 1.0, 0.0]]
    config.droplist_option_fill_texts = [None]
    config.matrix_prob = [[0.0, 0.0, 1.0]]
    state = ExecutionState(config=config)

    dropdown_question = SurveyQuestionMeta(
        num=1,
        title="Q1",
        provider="qq",
        provider_question_id="q1",
        provider_type="select",
        type_code="7",
        has_jump=True,
        logic_parse_status="complete",
        jump_rules=[{"option_index": 1, "jumpto": 2}],
        option_texts=["A", "B", "C"],
        options=3,
    )
    matrix_star_question = SurveyQuestionMeta(
        num=2,
        title="Q2",
        provider="qq",
        provider_question_id="q2",
        provider_type="matrix_star",
        type_code="6",
        rows=1,
        options=3,
    )

    monkeypatch.setattr(qq_builders, "weighted_index", lambda _probs: 1)
    monkeypatch.setattr(qq_builders, "get_tendency_index", lambda *_args, **_kwargs: 2)
    monkeypatch.setattr(qq_builders, "resolve_option_fill_text_from_config", _async_result(None))

    dropdown_action = await qq_builders.build_answer_action(
        None, dropdown_question, state, psycho_plan=None
    )
    matrix_action = await qq_builders.build_answer_action(
        None, matrix_star_question, state, psycho_plan=None
    )

    assert dropdown_action is not None
    assert dropdown_action.kind == "select"
    assert dropdown_action.selected_indices == (1,)
    assert matrix_action is not None
    assert matrix_action.kind == "matrix"
    assert matrix_action.matrix_indices == (2,)


@pytest.mark.asyncio
async def test_qq_builder_uses_prefilled_ai_text_answer(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="qq")
    config.question_config_index_map = {1: ("text", 0)}
    config.text_ai_flags = [True]
    state = ExecutionState(config=config)
    state.set_ai_prefill_answers("slot-2", {1: ("上海", "羽毛球")})
    question = SurveyQuestionMeta(
        num=1,
        title="请依次填写城市和爱好",
        provider="qq",
        provider_question_id="q1",
        provider_type="text",
        text_inputs=2,
    )

    async def fail_generate(*_args, **_kwargs):
        raise AssertionError("命中预取答案后不该再调用单题 AI")

    monkeypatch.setattr(qq_builders, "agenerate_ai_answer", fail_generate)

    action = await qq_builders.build_answer_action(
        None,
        question,
        state,
        psycho_plan=None,
        thread_name="slot-2",
    )

    assert action is not None
    assert action.kind == "text"
    assert action.text_values == ("上海", "羽毛球")


@pytest.mark.asyncio
async def test_qq_builder_uses_prefilled_ai_option_fill_answer(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="qq")
    config.question_config_index_map = {1: ("single", 0)}
    config.single_prob = [[1.0, 0.0]]
    config.single_option_fill_texts = [["__AI_FILL__", None]]
    state = ExecutionState(config=config)
    state.set_ai_option_fill_prefill_answers("slot-opt-2", {(1, 0): "补充信息"})
    question = SurveyQuestionMeta(
        num=1,
        title="请选择职业方向",
        provider="qq",
        provider_question_id="q1",
        provider_type="radio",
        option_texts=["技术", "产品"],
        options=2,
    )

    async def fail_option_fill(*_args, **_kwargs):
        raise AssertionError("命中附加填空预取后不该再调用单题 AI")

    monkeypatch.setattr(qq_builders, "weighted_index", lambda _probs: 0)
    monkeypatch.setattr(qq_builders, "agenerate_ai_answer", fail_option_fill)

    action = await qq_builders.build_answer_action(
        None,
        question,
        state,
        psycho_plan=None,
        thread_name="slot-opt-2",
    )

    assert action is not None
    assert action.option_fill_texts == ((0, "补充信息"),)


@pytest.mark.asyncio
async def test_qq_builder_defaults_selected_fillable_option_text() -> None:
    config = ExecutionConfig(survey_provider="qq")
    config.question_config_index_map = {1: ("single", 0)}
    config.single_prob = [[0.0, 1.0]]
    config.single_option_fill_texts = [None]
    state = ExecutionState(config=config)
    question = SurveyQuestionMeta(
        num=1,
        title="其他说明",
        provider="qq",
        provider_question_id="q1",
        provider_type="radio",
        option_texts=["A", "其他"],
        options=2,
        fillable_options=[1],
    )

    action = await qq_builders.build_answer_action(None, question, state, psycho_plan=None)

    assert action is not None
    assert action.selected_indices == (1,)
    assert action.option_fill_texts == ((1, "无"),)
