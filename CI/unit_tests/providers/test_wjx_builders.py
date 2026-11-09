from __future__ import annotations

import pytest

from software.core.task import ExecutionConfig, ExecutionState
from surveycore.providers.contracts import SurveyQuestionMeta
from wjx.provider import answering_builders as wjx_builders
from wjx.provider import http_runtime as wjx_http
from surveycore.core.persona.context import get_answered, reset_context
from surveycore.core.questions import consistency
from software.core.ai import batch_runtime

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
async def test_wjx_action_plan_records_previous_choice_before_consistency_rule(monkeypatch) -> None:
    reset_context()
    consistency.reset_consistency_context(
        [
            {
                "id": "q1-to-q2",
                "condition_question_num": 1,
                "condition_mode": "selected",
                "condition_option_indices": [0],
                "target_question_num": 2,
                "action_mode": "must_select",
                "target_option_indices": [1],
            }
        ]
    )
    config = ExecutionConfig(survey_provider="wjx")
    config.question_config_index_map = {1: ("single", 0), 2: ("single", 1)}
    config.single_prob = [[1.0, 0.0], [1.0, 1.0]]
    state = ExecutionState(config=config)
    q1 = SurveyQuestionMeta(num=1, title="Q1", type_code="3", options=2, option_texts=["A", "B"])
    q2 = SurveyQuestionMeta(num=2, title="Q2", type_code="3", options=2, option_texts=["A", "B"])
    config.questions_metadata = {1: q1, 2: q2}
    monkeypatch.setattr(
        wjx_builders,
        "weighted_index",
        lambda probabilities: probabilities.index(max(probabilities)),
    )
    plan = await wjx_http._build_action_plan(
        config, state, psycho_plan=None, stop_signal=None, thread_name="worker-1"
    )
    assert [action.selected_indices for action in plan.actions] == [(0,), (1,)]
    assert get_answered()[1].selected_indices == [0]


@pytest.mark.asyncio
async def test_wjx_action_plan_records_prefilled_ai_text_and_pending_once(monkeypatch) -> None:
    reset_context()
    config = ExecutionConfig(survey_provider="wjx")
    config.question_config_index_map = {1: ("single", 0), 2: ("text", 0)}
    config.single_prob = [[1.0, 0.0]]
    config.single_option_fill_texts = [["__AI_FILL__", None]]
    config.text_ai_flags = [True]
    config.question_dimension_map = {1: "dimension"}
    state = ExecutionState(config=config)
    q1 = SurveyQuestionMeta(num=1, title="Q1", type_code="3", options=2, option_texts=["A", "B"])
    q2 = SurveyQuestionMeta(num=2, title="职业", type_code="1", text_inputs=1)
    config.questions_metadata = {1: q1, 2: q2}

    async def resolve_texts(*_args):
        return ["A", "B"]

    async def generate_answer(_prompt, *, question_type="fill_blank", blank_count=None, ctx=None):
        return "真实职业"

    monkeypatch.setattr(wjx_builders, "_resolve_runtime_option_texts", resolve_texts)
    monkeypatch.setattr(wjx_builders, "weighted_index", lambda _probabilities: 0)
    monkeypatch.setattr(batch_runtime, "agenerate_answer", generate_answer)
    plan = await wjx_http._build_action_plan(
        config, state, psycho_plan=None, stop_signal=None, thread_name="worker-ai"
    )

    assert get_answered()[2].text_answer == "真实职业"
    assert "__AI_" not in get_answered()[2].text_answer
    assert plan.actions[1].text_values == ("真实职业",)
    assert state.distribution_pending_by_thread["worker-ai"] == [("q:1", 0, 2)]


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
