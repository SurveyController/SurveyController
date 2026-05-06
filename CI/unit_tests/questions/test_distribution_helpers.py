from __future__ import annotations

from types import SimpleNamespace

import software.core.questions.distribution as distribution


class _FakeCtx:
    def __init__(self, *, counts=(0, None), dimension_map=None) -> None:
        self._counts = counts
        self.config = SimpleNamespace(question_dimension_map=dimension_map or {})
        self.append_calls: list[tuple[str, int, int]] = []

    def snapshot_distribution_stats(self, stat_key: str, option_count: int):
        del stat_key, option_count
        return self._counts

    def append_pending_distribution_choice(self, stat_key: str, option_index: int, option_count: int) -> None:
        self.append_calls.append((stat_key, option_index, option_count))


class _FakePsychoPlan:
    def __init__(self, choice) -> None:
        self._choice = choice

    def get_choice(self, question_index, row_index):
        del question_index, row_index
        return self._choice


class DistributionHelperTests:
    def test_build_distribution_stat_key_formats_question_and_matrix_keys(self) -> None:
        assert distribution.build_distribution_stat_key(3) == "q:3"
        assert distribution.build_distribution_stat_key(3, 2) == "matrix:3:2"

    def test_resolve_distribution_probabilities_returns_target_when_no_runtime_context(self, monkeypatch) -> None:
        monkeypatch.setattr(distribution, "normalize_droplist_probs", lambda probabilities, option_count: [0.5, 0.5][:option_count])

        result = distribution.resolve_distribution_probabilities([1, 1], 2, None, 5)

        assert result == [0.5, 0.5]

    def test_resolve_distribution_probabilities_applies_runtime_correction(self, monkeypatch) -> None:
        monkeypatch.setattr(distribution, "normalize_droplist_probs", lambda probabilities, option_count: [0.7, 0.3][:option_count])
        ctx = _FakeCtx(counts=(10, [9, 1]))

        result = distribution.resolve_distribution_probabilities([7, 3], 2, ctx, 8)

        assert len(result) == 2
        assert abs(sum(result) - 1.0) < 1e-9
        assert result[0] < 0.7
        assert result[1] > 0.3

    def test_resolve_distribution_probabilities_uses_priority_profile_when_dimension_or_plan_active(self, monkeypatch) -> None:
        monkeypatch.setattr(distribution, "normalize_droplist_probs", lambda probabilities, option_count: [0.6, 0.4][:option_count])
        monkeypatch.setattr(distribution, "get_reliability_profile", lambda: SimpleNamespace(
            distribution_warmup_samples=3,
            distribution_gain=2.0,
            distribution_min_factor=0.5,
            distribution_max_factor=3.0,
            distribution_gap_limit=0.8,
        ))
        ctx = _FakeCtx(counts=(4, [4, 0]), dimension_map={9: "A"})

        result = distribution.resolve_distribution_probabilities(
            [6, 4],
            2,
            ctx,
            9,
            psycho_plan=_FakePsychoPlan(choice=1),
        )

        assert len(result) == 2
        assert abs(sum(result) - 1.0) < 1e-9

    def test_record_pending_distribution_choice_ignores_invalid_input_and_records_valid_choice(self) -> None:
        ctx = _FakeCtx()

        distribution.record_pending_distribution_choice(ctx, None, 0, 2)
        distribution.record_pending_distribution_choice(ctx, 1, -1, 2)
        distribution.record_pending_distribution_choice(ctx, 1, 5, 2)
        distribution.record_pending_distribution_choice(ctx, 1, 1, 2, row_index=3)

        assert ctx.append_calls == [("matrix:1:3", 1, 2)]

