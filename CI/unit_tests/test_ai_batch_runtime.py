from __future__ import annotations

import pytest

from software.core.ai.batch_runtime import assert_no_free_ai_placeholders_in_actions
from software.core.questions.utils import OPTION_FILL_AI_TOKEN
from software.providers.answering import AnswerAction


class AiBatchRuntimeTests:
    def test_assert_no_free_ai_placeholders_allows_resolved_text(self) -> None:
        assert_no_free_ai_placeholders_in_actions(
            [
                AnswerAction(
                    question_num=1,
                    kind="text",
                    text_values=("已生成答案",),
                )
            ]
        )

    def test_assert_no_free_ai_placeholders_blocks_unresolved_text(self) -> None:
        with pytest.raises(RuntimeError, match="问卷存在未替换的 AI 占位符.*第2题"):
            assert_no_free_ai_placeholders_in_actions(
                [
                    AnswerAction(
                        question_num=2,
                        kind="text",
                        text_values=(OPTION_FILL_AI_TOKEN,),
                    )
                ]
            )

    def test_assert_no_free_ai_placeholders_blocks_option_fill_tuple(self) -> None:
        with pytest.raises(RuntimeError, match="问卷星存在未替换的 AI 占位符.*第3题"):
            assert_no_free_ai_placeholders_in_actions(
                [
                    AnswerAction(
                        question_num=3,
                        kind="single",
                        option_fill_texts=((1, OPTION_FILL_AI_TOKEN),),
                    )
                ],
                provider_label="问卷星",
            )

    def test_assert_no_free_ai_placeholders_blocks_prefixed_placeholders(self) -> None:
        with pytest.raises(RuntimeError, match="第4题"):
            assert_no_free_ai_placeholders_in_actions(
                [
                    AnswerAction(
                        question_num=4,
                        kind="text",
                        text_values=("__FREE_AI_TEXT__4_0",),
                    )
                ]
            )
