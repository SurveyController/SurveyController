from __future__ import annotations

from types import SimpleNamespace

from software.core.questions.schema import QuestionEntry, _infer_option_count


class SchemaHelperTests:
    def test_infer_option_count_prefers_matrix_nested_lengths(self) -> None:
        entry = QuestionEntry(
            question_type="matrix",
            probabilities=[[0.1, 0.2, 0.7]],
            custom_weights=[[1, 2, 3, 4]],
        )

        assert _infer_option_count(entry) == 4

    def test_infer_option_count_uses_explicit_option_count_then_weights_probabilities_and_texts(self) -> None:
        explicit = QuestionEntry(question_type="single", probabilities=None, option_count=6)
        weighted = QuestionEntry(question_type="single", probabilities=None, custom_weights=[1, 2, 3])
        probabilistic = QuestionEntry(question_type="single", probabilities=[0.2, 0.8])
        text_based = QuestionEntry(question_type="text", probabilities=None, texts=["a", "b", "c"])

        assert _infer_option_count(explicit) == 6
        assert _infer_option_count(weighted) == 3
        assert _infer_option_count(probabilistic) == 2
        assert _infer_option_count(text_based) == 3

    def test_infer_option_count_uses_scale_default_and_falls_back_to_zero(self) -> None:
        scale = QuestionEntry(question_type="scale", probabilities=None)
        other = QuestionEntry(question_type="single", probabilities=None)

        assert _infer_option_count(scale) == 5
        assert _infer_option_count(other) == 0
