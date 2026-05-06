from __future__ import annotations

from types import SimpleNamespace

import software.core.questions.strict_ratio as strict_ratio


class StrictRatioHelperTests:
    def test_has_positive_weight_values_supports_nested_collections(self) -> None:
        assert strict_ratio.has_positive_weight_values([[0, 0], [0.1]])
        assert not strict_ratio.has_positive_weight_values([[0, 0], ["bad"]])

    def test_is_strict_custom_ratio_mode_requires_custom_mode_and_positive_values(self) -> None:
        assert strict_ratio.is_strict_custom_ratio_mode("custom", [0, 1], None)
        assert strict_ratio.is_strict_custom_ratio_mode("custom", None, [0, 2])
        assert not strict_ratio.is_strict_custom_ratio_mode("random", [0, 1], None)

    def test_is_strict_ratio_question_reads_map_from_config(self) -> None:
        ctx = SimpleNamespace(config=SimpleNamespace(question_strict_ratio_map={3: True}))
        assert strict_ratio.is_strict_ratio_question(ctx, 3)
        assert not strict_ratio.is_strict_ratio_question(ctx, 4)

    def test_stochastic_round_handles_non_positive_and_fractional_values(self, monkeypatch) -> None:
        monkeypatch.setattr(strict_ratio.random, "random", lambda: 0.1)
        assert strict_ratio.stochastic_round(-1) == 0
        assert strict_ratio.stochastic_round(2.3) == 3
        monkeypatch.setattr(strict_ratio.random, "random", lambda: 0.9)
        assert strict_ratio.stochastic_round(2.3) == 2

    def test_weighted_sample_without_replacement_and_rank_order_helpers(self, monkeypatch) -> None:
        random_values = iter([0.0, 0.99])
        monkeypatch.setattr(strict_ratio.random, "random", lambda: next(random_values))

        sampled = strict_ratio.weighted_sample_without_replacement([1, 2, 3], [5, 1, 1], 2)
        groups = strict_ratio.build_rank_groups([0.4, 0.2, 0.4, 0.0])
        adjusted = strict_ratio.enforce_reference_rank_order([0.6, 0.3, 0.1], [0.5, 0.1, 0.1])

        assert len(sampled) == 2
        assert sampled[0] == 1
        assert groups == [[0, 2], [1]]
        assert abs(sum(adjusted) - 1.0) < 1e-9
        assert adjusted[1] <= adjusted[0]

