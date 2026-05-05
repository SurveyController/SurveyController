from __future__ import annotations

from typing import Any

from wjx.provider.questions import multiple_rules


class MultipleRulesTests:
    def test_normalize_selected_indices_deduplicates_and_filters_out_of_range(self) -> None:
        result = multiple_rules._normalize_selected_indices([2, 2, -1, 1, 5, 0, 1], 3)

        assert result == [2, 1, 0]

    def test_resolve_rule_sets_prefers_required_when_required_and_blocked_overlap(self, caplog) -> None:
        with caplog.at_level("WARNING"):
            required, blocked = multiple_rules._resolve_rule_sets(
                {3, 1, 10},
                {1, 2, 8},
                option_count=4,
                current=6,
                rule_id="R-1",
            )

        assert required == [1, 3]
        assert blocked == {2}
        assert "必选和禁选" in caplog.text

    def test_apply_rule_constraints_truncates_required_and_keeps_required_first(self, monkeypatch, caplog) -> None:
        monkeypatch.setattr(multiple_rules.random, "shuffle", lambda values: values.reverse())

        with caplog.at_level("WARNING"):
            result = multiple_rules._apply_rule_constraints(
                selected_indices=[4, 3, 2, 2, 1],
                option_count=5,
                min_required=1,
                max_allowed=2,
                required_indices=[4, 0, 1],
                blocked_indices={3},
                positive_priority_indices=None,
                current=9,
                rule_id="limit",
            )

        assert result == [4, 0]
        assert "已截断必选集合" in caplog.text

    def test_apply_rule_constraints_fills_with_priority_then_random_fallback(self, monkeypatch) -> None:
        shuffled_values: list[list[int]] = []

        def fake_shuffle(values: list[int]) -> None:
            shuffled_values.append(list(values))
            values[:] = list(reversed(values))

        monkeypatch.setattr(multiple_rules.random, "shuffle", fake_shuffle)

        result = multiple_rules._apply_rule_constraints(
            selected_indices=[2],
            option_count=6,
            min_required=4,
            max_allowed=5,
            required_indices=[0],
            blocked_indices={5},
            positive_priority_indices=[4, 2, 9, 4, 1],
            current=12,
            rule_id="fill",
        )

        assert result == [0, 2, 4, 1]
        assert shuffled_values == [[3]]

    def test_apply_rule_constraints_warns_when_available_options_are_insufficient(self, monkeypatch, caplog) -> None:
        monkeypatch.setattr(multiple_rules.random, "shuffle", lambda _values: None)

        with caplog.at_level("WARNING"):
            result = multiple_rules._apply_rule_constraints(
                selected_indices=[],
                option_count=3,
                min_required=3,
                max_allowed=3,
                required_indices=[0],
                blocked_indices={1, 2},
                positive_priority_indices=[],
                current=15,
                rule_id=None,
            )

        assert result == [0]
        assert "可用选项不足" in caplog.text
