from __future__ import annotations

import pytest

from software.core.ai import batch_runtime
from software.core.ai.runtime import (
    build_free_ai_option_fill_placeholder,
    build_free_ai_text_placeholder,
)
from software.core.task import ExecutionConfig, ExecutionState
from software.integrations.ai import free_api
from software.providers.answering import AnswerAction
from software.providers.contracts import SurveyQuestionMeta


@pytest.mark.asyncio
async def test_wait_free_ai_batch_result_async_marks_only_invalid_item_failed(monkeypatch) -> None:
    async def fake_identity():
        return 73952, "device-1"

    async def fake_submit(items, *, user_id, device_id, system_prompt="", timeout=0, ctx=None):
        assert user_id == 73952
        assert device_id == "device-1"
        assert [item.item_id for item in items] == ["q1", "q2"]
        assert ctx is None
        return free_api.FreeAIBatchCreateResult(
            task_id="task-1",
            status="queued",
            total_items=2,
            batch_count=1,
            poll_after_ms=0,
        )

    async def fake_poll(task_id, *, device_id, timeout=0, ctx=None):
        assert task_id == "task-1"
        assert device_id == "device-1"
        assert ctx is None
        return free_api.FreeAIBatchPollResult(
            task_id="task-1",
            status="completed",
            total_items=2,
            completed_items=2,
            failed_items=0,
            pending_items=0,
            poll_after_ms=0,
            items=[
                free_api.FreeAIBatchItemResult(
                    item_id="q1",
                    status="completed",
                    answers=["只有一个"],
                    detail="ai_ok",
                ),
                free_api.FreeAIBatchItemResult(
                    item_id="q2",
                    status="completed",
                    answers=["正常答案"],
                    detail="ai_ok",
                ),
            ],
        )

    monkeypatch.setattr(free_api, "_ensure_free_ai_identity_async", fake_identity)
    monkeypatch.setattr(free_api, "_submit_free_ai_batch_task_with_identity_async", fake_submit)
    monkeypatch.setattr(free_api, "_poll_free_ai_batch_task_with_identity_async", fake_poll)

    result = await free_api.wait_free_ai_batch_result_async(
        [
            free_api.FreeAIBatchItem(
                item_id="q1",
                question_type="multi_fill_blank",
                question_content="请依次填写两个答案",
                blank_count=2,
            ),
            free_api.FreeAIBatchItem(
                item_id="q2",
                question_type="fill_blank",
                question_content="请填写一个答案",
            ),
        ]
    )

    assert result.completed == {"q2": ["正常答案"]}
    assert "q1" in result.failed
    assert "期望 2 个答案" in result.failed["q1"]
    assert result.pending == set()
    assert result.task_ids == ["task-1"]


def test_build_free_ai_batch_items_includes_only_action_matched_ai_items() -> None:
    questions = [
        SurveyQuestionMeta(num=1, title="你喜欢的水果", option_texts=["苹果", "香蕉"], options=2),
        SurveyQuestionMeta(num=2, title="请填写职业", text_inputs=1),
    ]
    actions = [
        AnswerAction(
            question_num=1,
            kind="choice",
            selected_indices=(0,),
            option_fill_texts=((0, build_free_ai_option_fill_placeholder(1, 0)),),
        ),
        AnswerAction(
            question_num=2,
            kind="text",
            text_values=(build_free_ai_text_placeholder(2, 0),),
        ),
    ]

    items, item_question_map, item_option_fill_map = batch_runtime._build_free_ai_batch_items_for_actions(questions, actions)

    assert [item.item_id for item in items] == ["q1_opt0", "q2"]
    assert item_question_map == {"q2": 2}
    assert item_option_fill_map == {"q1_opt0": (1, 0)}


@pytest.mark.asyncio
async def test_prefill_free_ai_answers_for_questions_raises_when_batch_incomplete(monkeypatch) -> None:
    state = ExecutionState(config=ExecutionConfig(survey_provider="wjx"))
    questions = [
        SurveyQuestionMeta(num=1, title="请填写职业", text_inputs=1),
        SurveyQuestionMeta(num=2, title="请选择水果", option_texts=["苹果"], options=1),
    ]
    actions = [
        AnswerAction(question_num=1, kind="text", text_values=(build_free_ai_text_placeholder(1, 0),)),
        AnswerAction(question_num=2, kind="choice", selected_indices=(0,), option_fill_texts=((0, build_free_ai_option_fill_placeholder(2, 0)),)),
    ]

    async def fake_wait(_items, *, system_prompt="", ctx=None):
        assert system_prompt
        return free_api.FreeAIBatchResolvedResult(
            completed={},
            failed={"q1": "ai_upstream_failed"},
            pending={"q2_opt0"},
            task_ids=["task-1"],
        )

    monkeypatch.setattr(batch_runtime, "wait_free_ai_batch_result_async", fake_wait)

    with pytest.raises(RuntimeError, match="免费 AI 批量预取未完成"):
        await batch_runtime.prefill_free_ai_answers_for_questions(
            questions,
            actions,
            state,
            thread_name="slot-1",
        )


@pytest.mark.asyncio
async def test_prefill_provider_ai_answers_for_questions_replaces_placeholders(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="wjx")
    config.ai_mode = "provider"
    state = ExecutionState(config=config)
    questions = [
        SurveyQuestionMeta(num=1, title="请填写职业", text_inputs=2),
        SurveyQuestionMeta(num=2, title="请选择水果", option_texts=["苹果"], options=1),
    ]
    actions = [
        AnswerAction(
            question_num=1,
            kind="text",
            text_values=(build_free_ai_text_placeholder(1, 0), build_free_ai_text_placeholder(1, 1)),
        ),
        AnswerAction(
            question_num=2,
            kind="choice",
            selected_indices=(0,),
            selected_texts=("苹果 / __FREE_AI_OPTION_FILL__2_0",),
            option_fill_texts=((0, build_free_ai_option_fill_placeholder(2, 0)),),
        ),
    ]
    calls: list[tuple[str, str, int | None]] = []

    async def fake_generate(question, *, question_type="fill_blank", blank_count=None, ctx=None):
        calls.append((question, question_type, blank_count))
        if question_type == "multi_fill_blank":
            return "教师||三年"
        return "很甜"

    monkeypatch.setattr(batch_runtime, "agenerate_answer", fake_generate)

    summary = await batch_runtime.prefill_free_ai_answers_for_questions(
        questions,
        actions,
        state,
        thread_name="slot-provider",
    )

    assert summary.requested == 2
    assert summary.completed == 2
    assert actions[0].text_values == ("教师", "三年")
    assert actions[1].option_fill_texts == ((0, "很甜"),)
    assert actions[1].selected_texts == ("苹果 / 很甜",)
    assert [item[1:] for item in calls] == [("multi_fill_blank", 2), ("fill_blank", None)]


@pytest.mark.asyncio
async def test_prefill_provider_ai_answers_for_questions_raises_when_incomplete(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="wjx")
    config.ai_mode = "provider"
    state = ExecutionState(config=config)
    questions = [SurveyQuestionMeta(num=1, title="请填写职业", text_inputs=2)]
    actions = [
        AnswerAction(
            question_num=1,
            kind="text",
            text_values=(build_free_ai_text_placeholder(1, 0), build_free_ai_text_placeholder(1, 1)),
        ),
    ]

    async def fake_generate(*_args, **_kwargs):
        return "只有一个"

    monkeypatch.setattr(batch_runtime, "agenerate_answer", fake_generate)

    with pytest.raises(RuntimeError, match="AI 批量预取未完成"):
        await batch_runtime.prefill_free_ai_answers_for_questions(
            questions,
            actions,
            state,
            thread_name="slot-provider",
        )


def test_assert_no_free_ai_placeholders_in_actions_blocks_submit_payload() -> None:
    actions = [
        AnswerAction(
            question_num=42,
            kind="text",
            text_values=(build_free_ai_text_placeholder(42, 0),),
        ),
    ]

    with pytest.raises(RuntimeError, match="第42题"):
        batch_runtime.assert_no_free_ai_placeholders_in_actions(actions, provider_label="问卷星")
