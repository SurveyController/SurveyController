from __future__ import annotations

import pytest

from software.core.ai import batch_runtime
from software.core.questions.utils import OPTION_FILL_AI_TOKEN
from software.core.task import ExecutionConfig, ExecutionState
from software.integrations.ai import free_api
from software.providers.contracts import SurveyQuestionMeta


@pytest.mark.asyncio
async def test_wait_free_ai_batch_result_async_marks_only_invalid_item_failed(monkeypatch) -> None:
    async def fake_identity():
        return 73952, "device-1"

    async def fake_submit(items, *, user_id, device_id, system_prompt="", timeout=0):
        assert user_id == 73952
        assert device_id == "device-1"
        assert [item.item_id for item in items] == ["q1", "q2"]
        return free_api.FreeAIBatchCreateResult(
            task_id="task-1",
            status="queued",
            total_items=2,
            batch_count=1,
            poll_after_ms=0,
        )

    async def fake_poll(task_id, *, device_id, timeout=0):
        assert task_id == "task-1"
        assert device_id == "device-1"
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


def test_build_free_ai_batch_items_includes_option_fill_ai_items() -> None:
    config = ExecutionConfig(survey_provider="wjx")
    config.question_config_index_map = {1: ("single", 0), 2: ("text", 0)}
    config.text_ai_flags = [True]
    config.single_option_fill_texts = [[OPTION_FILL_AI_TOKEN, None]]
    state = ExecutionState(config=config)
    questions = [
        SurveyQuestionMeta(num=1, title="你喜欢的水果", option_texts=["苹果", "香蕉"], options=2),
        SurveyQuestionMeta(num=2, title="请填写职业", text_inputs=1),
    ]

    items, item_question_map, item_option_fill_map = batch_runtime._build_free_ai_batch_items(questions, state)

    assert [item.item_id for item in items] == ["q1_opt0", "q2"]
    assert item_question_map == {"q2": 2}
    assert item_option_fill_map == {"q1_opt0": (1, 0)}


@pytest.mark.asyncio
async def test_prefill_free_ai_answers_for_questions_raises_when_batch_incomplete(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="wjx")
    config.question_config_index_map = {1: ("text", 0), 2: ("single", 0)}
    config.text_ai_flags = [True]
    config.single_option_fill_texts = [[OPTION_FILL_AI_TOKEN]]
    state = ExecutionState(config=config)
    questions = [
        SurveyQuestionMeta(num=1, title="请填写职业", text_inputs=1),
        SurveyQuestionMeta(num=2, title="请选择水果", option_texts=["苹果"], options=1),
    ]

    async def fake_wait(_items, *, system_prompt=""):
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
            state,
            thread_name="slot-1",
        )
