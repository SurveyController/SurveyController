from __future__ import annotations

from types import SimpleNamespace

import pytest

from software.core.questions import tendency


class _Plan:
    def __init__(self, choices: dict[tuple[int, int | None], int], locked: bool = False, fail_locked: bool = False) -> None:
        self.choices = choices
        self.locked = locked
        self.fail_locked = fail_locked

    def get_choice(self, question_index: int, row_index: int | None):
        return self.choices.get((question_index, row_index))

    def is_distribution_locked(self, _question_index: int, _row_index: int | None) -> bool:
        if self.fail_locked:
            raise RuntimeError("locked failed")
        return self.locked


class TendencyRuntimeTests:
    def test_zero_weight_guard_clamps_and_chooses_nearest_positive_weight(self) -> None:
        assert tendency._enforce_zero_weight_guard(0, 4, [0, 0, 5, 1], anchor_index=0) == 2
        assert tendency._enforce_zero_weight_guard(3, 4, [0, 2, 2, 0], anchor_index=3) == 2
        assert tendency._enforce_zero_weight_guard(9, 4, [1, 1, 1, 1]) == 3

    def test_zero_weight_guard_rejects_all_zero_weights(self) -> None:
        with pytest.raises(ValueError, match="所有选项权重均为 0"):
            tendency._enforce_zero_weight_guard(0, 3, [0, 0, 0])

    def test_generate_base_ratio_uses_persona_when_random_probabilities(self, patch_attrs) -> None:
        patch_attrs(
            (tendency.random, "gauss", lambda _mu, _sigma: 0.05),
            (
                tendency,
                "log_suppressed_exception",
                lambda *_args, **_kwargs: None,
            ),
        )
        import software.core.persona.generator as generator

        patch_attrs((generator, "get_current_persona", lambda: SimpleNamespace(satisfaction_tendency=0.8)))

        assert tendency._generate_base_ratio(5, -1) == 0.8500000000000001

    def test_get_tendency_index_returns_plan_choice_when_distribution_locked(self) -> None:
        plan = _Plan({(2, None): 4}, locked=True)

        assert tendency.get_tendency_index(5, [0, 0, 1, 0, 1], psycho_plan=plan, question_index=2) == 4

    def test_get_tendency_index_blends_plan_choice_and_keeps_zero_weight_guard(self, patch_attrs) -> None:
        plan = _Plan({(2, 1): 3}, locked=False)
        patch_attrs((tendency, "_blend_psychometric_choice", lambda *_args, **_kwargs: 0))

        assert tendency.get_tendency_index(4, [0, 0, 5, 0], psycho_plan=plan, question_index=2, row_index=1) == 2

    def test_get_tendency_index_uses_random_for_ungrouped_dimension(self, patch_attrs) -> None:
        patch_attrs((tendency, "weighted_index", lambda _weights: 1))

        assert tendency.get_tendency_index(3, [0.2, 0.8, 0.0], dimension=None) == 1

    def test_get_tendency_index_reuses_dimension_base_across_option_counts(self, patch_attrs) -> None:
        tendency.reset_tendency()
        patch_attrs(
            (tendency, "_generate_base_ratio", lambda _count, _probabilities: 0.75),
            (tendency, "_apply_consistency", lambda base, _count, _probabilities: base),
        )

        first = tendency.get_tendency_index(5, [1, 1, 1, 1, 1], dimension="满意度")
        second = tendency.get_tendency_index(3, [1, 1, 1], dimension="满意度")

        assert first == 3
        assert second == 2

    def test_apply_consistency_uses_weighted_adjusted_probabilities(self, patch_attrs) -> None:
        patch_attrs(
            (tendency, "get_reliability_profile", lambda: SimpleNamespace(consistency_outside_decay=0.1, consistency_window_ratio=0.25, consistency_window_max=2, consistency_center_weight=3.0, consistency_edge_weight=1.0)),
            (tendency, "weighted_index", lambda weights: max(range(len(weights)), key=lambda idx: weights[idx])),
        )

        assert tendency._apply_consistency(2, 5, [1, 1, 5, 1, 1]) == 2

    def test_apply_consistency_falls_back_to_distance_weighted_random(self, patch_attrs) -> None:
        patch_attrs(
            (tendency, "get_reliability_profile", lambda: SimpleNamespace(consistency_outside_decay=0.1, consistency_window_ratio=0.25, consistency_window_max=2, consistency_center_weight=3.0, consistency_edge_weight=1.0)),
            (tendency.random, "random", lambda: 0.0),
        )

        assert tendency._apply_consistency(3, 7, -1) == 1

    def test_blend_psychometric_choice_limits_to_window_and_positive_weights(self, patch_attrs) -> None:
        patch_attrs(
            (tendency, "get_reliability_profile", lambda: SimpleNamespace(consistency_outside_decay=0.2, consistency_window_ratio=0.25, consistency_window_max=1, consistency_center_weight=3.0, consistency_edge_weight=1.0)),
            (tendency, "weighted_index", lambda weights: max(range(len(weights)), key=lambda idx: weights[idx])),
        )

        assert tendency._blend_psychometric_choice(2, 5, [10, 1, 2, 1, 10]) == 2

    def test_psychometric_plan_errors_fall_back_to_regular_logic(self, patch_attrs) -> None:
        class BrokenPlan:
            def get_choice(self, *_args, **_kwargs):
                raise RuntimeError("broken")

        patch_attrs((tendency.random, "randrange", lambda count: count - 1))

        assert tendency.get_tendency_index(3, -1, psycho_plan=BrokenPlan(), question_index=1) == 2
        assert not tendency._is_distribution_locked_plan(_Plan({(1, None): 0}, fail_locked=True), 1, None)

    def test_resolve_fluctuation_window_and_decay(self, patch_attrs) -> None:
        patch_attrs(
            (tendency, "get_reliability_profile", lambda: SimpleNamespace(consistency_window_ratio=0.2, consistency_window_max=3, consistency_center_weight=4.0, consistency_edge_weight=1.0)),
        )

        assert tendency._resolve_fluctuation_window(3) == 0
        assert tendency._resolve_fluctuation_window(10) == 2
        assert tendency._window_decay(0, 2) == 4.0
        assert tendency._window_decay(2, 2) == 1.0
