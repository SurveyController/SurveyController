from __future__ import annotations


from surveycore.tencent.provider.answering_rules import (
    apply_multiple_constraints,
    normalize_selected_indices,
)


class TencentAnsweringRulesTests:
    def test_normalize_selected_indices_deduplicates_sorts_and_filters_out_of_range(self) -> None:
        assert normalize_selected_indices([2, 2, -1, 1, 5, 0, 1], 3) == [0, 1, 2]

    def test_normalize_selected_indices_skips_values_that_cannot_be_parsed_as_int(self) -> None:
        assert normalize_selected_indices(["a", None, "", 1], 4) == [1]

    def test_normalize_selected_indices_returns_empty_for_no_valid_input(self) -> None:
        assert normalize_selected_indices([], 3) == []
        assert normalize_selected_indices([-5, 99], 3) == []

    def test_apply_removes_blocked_selection_and_appends_missing_required(self) -> None:
        result = apply_multiple_constraints(
            selected_indices=[0, 1],
            option_count=4,
            min_required=1,
            max_allowed=3,
            required_indices=[2],
            blocked_indices=[1],
            positive_priority_indices=[],
        )

        assert result == [0, 2]

    def test_apply_truncates_to_max_allowed_while_keeping_required(self) -> None:
        result = apply_multiple_constraints(
            selected_indices=[3, 2, 1],
            option_count=5,
            min_required=1,
            max_allowed=2,
            required_indices=[4],
            blocked_indices=[],
            positive_priority_indices=[],
        )

        assert result == [1, 4]

    def test_apply_fills_to_min_required_preferring_positive_priorities(self) -> None:
        result = apply_multiple_constraints(
            selected_indices=[],
            option_count=6,
            min_required=3,
            max_allowed=5,
            required_indices=[0],
            blocked_indices=[5],
            positive_priority_indices=[4, 2],
        )

        assert result == [0, 2, 4]

    def test_apply_caps_result_when_min_required_exceeds_max_allowed(self) -> None:
        result = apply_multiple_constraints(
            selected_indices=[],
            option_count=5,
            min_required=4,
            max_allowed=2,
            required_indices=[],
            blocked_indices=[],
            positive_priority_indices=[],
        )

        assert result == [0, 1]

    def test_apply_clamps_limits_to_option_count(self) -> None:
        result = apply_multiple_constraints(
            selected_indices=[],
            option_count=2,
            min_required=0,
            max_allowed=99,
            required_indices=[],
            blocked_indices=[],
            positive_priority_indices=[],
        )

        assert result == [0]

    def test_apply_ignores_out_of_range_priorities_without_starving_min_fill(self) -> None:
        result = apply_multiple_constraints(
            selected_indices=[],
            option_count=2,
            min_required=2,
            max_allowed=2,
            required_indices=[],
            blocked_indices=[],
            positive_priority_indices=[9, -3],
        )

        assert result == [0, 1]

    def test_apply_required_wins_when_required_overlaps_blocked(self) -> None:
        result = apply_multiple_constraints(
            selected_indices=[1],
            option_count=3,
            min_required=1,
            max_allowed=3,
            required_indices=[1],
            blocked_indices=[1],
            positive_priority_indices=[],
        )

        assert result == [1]
