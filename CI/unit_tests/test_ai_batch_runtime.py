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
        with pytest.raises(RuntimeError, match="第2题仍有 AI 占位符"):
            assert_no_free_ai_placeholders_in_actions(
                [
                    AnswerAction(
                        question_num=2,
                        kind="text",
                        text_values=(OPTION_FILL_AI_TOKEN,),
                    )
                ]
            )

