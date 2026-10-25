from __future__ import annotations

import pytest

from software.core.task import ExecutionConfig, ExecutionState
from surveycore.providers.answering import AnswerAction
from surveycore.providers.contracts import SurveyQuestionMeta
from wjx.provider import http_runtime as wjx_http


@pytest.mark.asyncio
async def test_wjx_http_runtime_builds_only_visible_questions_after_logic(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(
            num=1,
            title="Q1",
            type_code="3",
            has_jump=True,
            logic_parse_status="complete",
            jump_rules=[{"option_index": 1, "jumpto": 3}],
            option_texts=["A", "B"],
            options=2,
        ),
        2: SurveyQuestionMeta(
            num=2,
            title="Q2",
            type_code="3",
            has_display_condition=True,
            logic_parse_status="complete",
            display_conditions=[
                {
                    "condition_question_num": 1,
                    "condition_mode": "selected",
                    "condition_option_indices": [0],
                }
            ],
            option_texts=["C", "D"],
            options=2,
        ),
        3: SurveyQuestionMeta(num=3, title="Q3", type_code="3", option_texts=["E", "F"], options=2),
    }
    state = ExecutionState(config=config)
    built_questions: list[int] = []

    async def fake_build_action(_driver, question, _ctx, **_kwargs):
        built_questions.append(int(question.num))
        if int(question.num) == 1:
            return AnswerAction(
                question_num=1, kind="choice", selected_indices=(1,), record_type="single"
            )
        if int(question.num) == 3:
            return AnswerAction(
                question_num=3, kind="choice", selected_indices=(0,), record_type="single"
            )
        raise AssertionError("隐藏题不该进 HTTP 构建")

    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)

    actions = await wjx_http._build_actions(config, state, psycho_plan=None, stop_signal=None)

    assert built_questions == [1, 3]
    assert [action.question_num for action in actions] == [1, 3]


@pytest.mark.asyncio
async def test_wjx_http_runtime_skips_jump_hidden_questions(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(
            num=1,
            title="Q1",
            type_code="3",
            has_jump=True,
            logic_parse_status="complete",
            jump_rules=[{"option_index": 1, "jumpto": 3}],
            option_texts=["A", "B"],
            options=2,
        ),
        2: SurveyQuestionMeta(
            num=2,
            title="Q2",
            type_code="3",
            option_texts=["C", "D"],
            options=2,
        ),
        3: SurveyQuestionMeta(
            num=3,
            title="Q3",
            type_code="3",
            option_texts=["E", "F"],
            options=2,
        ),
    }
    state = ExecutionState(config=config)
    built_questions: list[int] = []

    async def fake_build_action(_driver, question, _ctx, **_kwargs):
        built_questions.append(int(question.num))
        if int(question.num) == 1:
            return AnswerAction(
                question_num=1, kind="choice", selected_indices=(1,), record_type="single"
            )
        return AnswerAction(
            question_num=int(question.num),
            kind="choice",
            selected_indices=(0,),
            record_type="single",
        )

    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)

    actions = await wjx_http._build_actions(config, state, psycho_plan=None, stop_signal=None)

    assert built_questions == [1, 3]
    assert [action.question_num for action in actions] == [1, 3]


@pytest.mark.asyncio
async def test_wjx_http_runtime_accepts_legacy_saved_jump_rules_without_status(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://v.wjx.cn/vm/tgRSrWd.aspx",
        survey_provider="wjx",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(
            num=1,
            title="这是一个单选题",
            type_code="3",
            has_jump=True,
            jump_rules=[{"option_index": 1, "jumpto": 5, "option_text": "我才是B"}],
            option_texts=["其他", "我才是B"],
            options=2,
        ),
        2: SurveyQuestionMeta(
            num=2, title="排序题", type_code="11", option_texts=["A", "B"], options=2
        ),
        3: SurveyQuestionMeta(
            num=3, title="量表题", type_code="5", option_texts=["0", "1"], options=2
        ),
        4: SurveyQuestionMeta(num=4, title="填空题", type_code="1", options=1),
        5: SurveyQuestionMeta(
            num=5, title="多选题", type_code="4", option_texts=["A", "B"], options=2
        ),
    }
    state = ExecutionState(config=config)
    built_questions: list[int] = []

    async def fake_build_action(_driver, question, _ctx, **_kwargs):
        question_num = int(question.num)
        built_questions.append(question_num)
        if question_num == 1:
            return AnswerAction(
                question_num=1, kind="choice", selected_indices=(1,), record_type="single"
            )
        return AnswerAction(
            question_num=question_num, kind="choice", selected_indices=(0,), record_type="multiple"
        )

    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)

    actions = await wjx_http._build_actions(config, state, psycho_plan=None, stop_signal=None)

    assert built_questions == [1, 5]
    assert [action.question_num for action in actions] == [1, 5]


@pytest.mark.asyncio
async def test_wjx_http_runtime_accepts_legacy_cached_terminate_jump_rule(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://v.wjx.cn/vm/hRLCS6n.aspx",
        survey_provider="wjx",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(
            num=1,
            title="您是否有参与过品牌快闪店的相关经历?",
            type_code="3",
            has_jump=True,
            jump_rules=[{"option_index": 1, "jumpto": 1, "option_text": "没有（结束作答）"}],
            option_texts=["有（继续作答）", "没有（结束作答）"],
            options=2,
        ),
        2: SurveyQuestionMeta(num=2, title="Q2", type_code="3", option_texts=["A", "B"], options=2),
    }
    state = ExecutionState(config=config)

    async def fake_build_action(_driver, question, _ctx, **_kwargs):
        if int(question.num) == 1:
            return AnswerAction(
                question_num=1, kind="choice", selected_indices=(1,), record_type="single"
            )
        raise AssertionError("结束作答后不该继续生成后续题目答案")

    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)

    actions = await wjx_http._build_actions(config, state, psycho_plan=None, stop_signal=None)

    assert [action.question_num for action in actions] == [1]


@pytest.mark.asyncio
async def test_wjx_http_runtime_blocks_unparsed_jump_logic(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(
            num=1,
            title="Q1",
            type_code="3",
            has_jump=True,
            logic_parse_status="unknown",
            option_texts=["A", "B"],
            options=2,
        ),
        2: SurveyQuestionMeta(num=2, title="Q2", type_code="3", option_texts=["C", "D"], options=2),
    }
    state = ExecutionState(config=config)

    async def fake_build_action(*_args, **_kwargs):
        raise AssertionError("未知跳题逻辑不该生成答案")

    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)

    with pytest.raises(RuntimeError, match="第1题逻辑规则未完整解析"):
        await wjx_http._build_actions(config, state, psycho_plan=None, stop_signal=None)


@pytest.mark.asyncio
async def test_wjx_http_runtime_blocks_unparsed_display_logic(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(num=1, title="Q1", type_code="3", option_texts=["A", "B"], options=2),
        2: SurveyQuestionMeta(
            num=2,
            title="Q2",
            type_code="3",
            has_display_condition=True,
            logic_parse_status="unknown",
            option_texts=["C", "D"],
            options=2,
        ),
    }
    state = ExecutionState(config=config)

    async def fake_build_action(*_args, **_kwargs):
        raise AssertionError("未知显隐逻辑不该生成答案")

    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)

    with pytest.raises(RuntimeError, match="第2题逻辑规则未完整解析"):
        await wjx_http._build_actions(config, state, psycho_plan=None, stop_signal=None)


@pytest.mark.asyncio
async def test_wjx_http_runtime_requires_all_distinct_display_sources(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(num=1, title="Q1", type_code="3", option_texts=["A", "B"], options=2),
        2: SurveyQuestionMeta(num=2, title="Q2", type_code="3", option_texts=["C", "D"], options=2),
        3: SurveyQuestionMeta(
            num=3,
            title="Q3",
            type_code="3",
            has_display_condition=True,
            logic_parse_status="complete",
            display_conditions=[
                {
                    "condition_question_num": 1,
                    "condition_mode": "selected",
                    "condition_option_indices": [0],
                },
                {
                    "condition_question_num": 2,
                    "condition_mode": "selected",
                    "condition_option_indices": [1],
                },
            ],
            option_texts=["E", "F"],
            options=2,
        ),
    }
    state = ExecutionState(config=config)
    built_questions: list[int] = []

    async def fake_build_action(_driver, question, _ctx, **_kwargs):
        built_questions.append(int(question.num))
        if int(question.num) == 1:
            return AnswerAction(
                question_num=1, kind="choice", selected_indices=(0,), record_type="single"
            )
        if int(question.num) == 2:
            return AnswerAction(
                question_num=2, kind="choice", selected_indices=(0,), record_type="single"
            )
        raise AssertionError("Q3 不该可见")

    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)

    actions = await wjx_http._build_actions(config, state, psycho_plan=None, stop_signal=None)

    assert built_questions == [1, 2]
    assert [action.question_num for action in actions] == [1, 2]
