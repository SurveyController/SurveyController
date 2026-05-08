from __future__ import annotations

from software.core.persona.context import record_answer, reset_context
from software.core.questions import consistency
from software.providers.contracts import SurveyQuestionMeta


class ConsistencyRulesTests:
    def test_normalize_rule_dict_sorts_deduplicates_and_keeps_matrix_rows(self) -> None:
        normalized = consistency.normalize_rule_dict(
            {
                "id": "",
                "condition_question_num": "1",
                "condition_mode": "selected",
                "condition_option_indices": [2, "1", 2, -1, "bad"],
                "target_question_num": "3",
                "action_mode": "must_not_select",
                "target_option_indices": ["4", 0, 4],
                "condition_row_index": "2",
                "target_row_index": "0",
            }
        )

        assert normalized == {
            "id": "rule-1-3-2-2",
            "condition_question_num": 1,
            "condition_mode": "selected",
            "condition_option_indices": [1, 2],
            "target_question_num": 3,
            "action_mode": "must_not_select",
            "target_option_indices": [0, 4],
            "condition_row_index": 2,
            "target_row_index": 0,
        }

    def test_sanitize_answer_rules_counts_invalid_and_unsupported_items(self) -> None:
        questions = [
            SurveyQuestionMeta(num=1, title="单选", type_code="3"),
            SurveyQuestionMeta(num=2, title="填空", type_code="1"),
            SurveyQuestionMeta(num=3, title="矩阵", type_code="6"),
        ]
        rules = [
            {
                "condition_question_num": 1,
                "condition_mode": "selected",
                "condition_option_indices": [0],
                "target_question_num": 3,
                "action_mode": "must_select",
                "target_option_indices": [1],
            },
            {
                "condition_question_num": 2,
                "condition_mode": "selected",
                "condition_option_indices": [0],
                "target_question_num": 3,
                "action_mode": "must_select",
                "target_option_indices": [1],
            },
            {"bad": "rule"},
        ]

        sanitized, stats = consistency.sanitize_answer_rules(rules, questions)

        assert len(sanitized) == 1
        assert stats == {"invalid": 1, "unsupported": 1}

    def test_single_like_consistency_applies_latest_triggered_rule(self) -> None:
        reset_context()
        record_answer(1, "single", selected_indices=[1], selected_texts=["B"])
        consistency.reset_consistency_context(
            [
                {
                    "id": "first",
                    "condition_question_num": 1,
                    "condition_mode": "selected",
                    "condition_option_indices": [1],
                    "target_question_num": 3,
                    "action_mode": "must_select",
                    "target_option_indices": [0],
                },
                {
                    "id": "latest",
                    "condition_question_num": 1,
                    "condition_mode": "selected",
                    "condition_option_indices": [1],
                    "target_question_num": 3,
                    "action_mode": "must_select",
                    "target_option_indices": [2],
                },
            ]
        )

        assert consistency.apply_single_like_consistency([1, 1, 1], 3) == [0.0, 0.0, 1.0]

    def test_rule_does_not_trigger_for_future_or_unmatched_condition(self) -> None:
        reset_context()
        record_answer(3, "single", selected_indices=[1])
        consistency.reset_consistency_context(
            [
                {
                    "id": "future",
                    "condition_question_num": 3,
                    "condition_mode": "selected",
                    "condition_option_indices": [1],
                    "target_question_num": 2,
                    "action_mode": "must_select",
                    "target_option_indices": [0],
                }
            ]
        )

        assert consistency.apply_single_like_consistency([1, -2, "bad"], 2) == [1.0, 0.0, 0.0]

    def test_matrix_row_consistency_uses_row_answers_and_target_row(self) -> None:
        reset_context()
        record_answer(1, "matrix", selected_indices=[2], row_index=1)
        consistency.reset_consistency_context(
            [
                {
                    "id": "row-rule",
                    "condition_question_num": 1,
                    "condition_row_index": 1,
                    "condition_mode": "selected",
                    "condition_option_indices": [2],
                    "target_question_num": 4,
                    "target_row_index": 0,
                    "action_mode": "must_not_select",
                    "target_option_indices": [1],
                }
            ]
        )

        assert consistency.apply_matrix_row_consistency([2, 5, 3], 4, 0) == [2.0, 0.0, 3.0]
        assert consistency.apply_matrix_row_consistency([2, 5, 3], 4, 1) == [2.0, 5.0, 3.0]

    def test_multiple_constraint_returns_required_or_forbidden_sets(self) -> None:
        reset_context()
        record_answer(1, "multiple", selected_indices=[0])
        consistency.reset_consistency_context(
            [
                {
                    "id": "must",
                    "condition_question_num": 1,
                    "condition_mode": "selected",
                    "condition_option_indices": [0],
                    "target_question_num": 2,
                    "action_mode": "must_select",
                    "target_option_indices": [1, 9],
                }
            ]
        )

        assert consistency.get_multiple_rule_constraint(2, 3) == ({1}, set(), "must")

        consistency.reset_consistency_context(
            [
                {
                    "id": "ban",
                    "condition_question_num": 1,
                    "condition_mode": "not_selected",
                    "condition_option_indices": [2],
                    "target_question_num": 2,
                    "action_mode": "must_not_select",
                    "target_option_indices": [0],
                }
            ]
        )

        assert consistency.get_multiple_rule_constraint(2, 3) == (set(), {0}, "ban")

    def test_invalid_target_indices_are_ignored_with_rule_id_for_multiple(self) -> None:
        reset_context()
        record_answer(1, "single", selected_indices=[0])
        consistency.reset_consistency_context(
            [
                {
                    "id": "bad-target",
                    "condition_question_num": 1,
                    "condition_mode": "selected",
                    "condition_option_indices": [0],
                    "target_question_num": 2,
                    "action_mode": "must_select",
                    "target_option_indices": [99],
                }
            ]
        )

        assert consistency.get_multiple_rule_constraint(2, 3) == (set(), set(), "bad-target")
