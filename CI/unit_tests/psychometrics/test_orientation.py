from __future__ import annotations
import math
from types import SimpleNamespace
from software.core.psychometrics.orientation import infer_dimension_orientation, infer_item_orientation, normalize_probability_list

class OrientationTests:

    def test_normalize_probability_list_replaces_invalid_values_and_zero_total(self) -> None:
        result = normalize_probability_list([float('nan'), -5, float('inf'), 0])
        assert result == [0.25, 0.25, 0.25, 0.25]

    def test_infer_item_orientation_detects_right_skew(self) -> None:
        item = SimpleNamespace(choice_key='q:1', option_count=5, target_probabilities=[0, 0, 0, 0, 1])
        orientation = infer_item_orientation(item)
        assert orientation.choice_key == 'q:1'
        assert orientation.direction == 'right'
        assert math.isclose(orientation.mean_ratio, 1.0)
        assert orientation.skew_strength > 0.45

    def test_infer_dimension_orientation_marks_reverse_items_when_anchor_is_clear(self) -> None:
        items = [SimpleNamespace(choice_key='q:1', option_count=5, target_probabilities=[1, 0, 0, 0, 0]), SimpleNamespace(choice_key='q:2', option_count=5, target_probabilities=[1, 0, 0, 0, 0]), SimpleNamespace(choice_key='q:3', option_count=5, target_probabilities=[0, 0, 0, 0, 1])]
        orientation = infer_dimension_orientation(items)
        assert orientation.anchor_direction == 'left'
        assert not orientation.ambiguous_anchor
        assert orientation.reversed_keys == {'q:3'}
        assert orientation.left_strength > orientation.right_strength

    def test_infer_dimension_orientation_keeps_reverse_set_empty_when_anchor_is_ambiguous(self) -> None:
        items = [SimpleNamespace(choice_key='q:1', option_count=5, target_probabilities=[1, 0, 0, 0, 0]), SimpleNamespace(choice_key='q:2', option_count=5, target_probabilities=[0, 0, 0, 0, 1])]
        orientation = infer_dimension_orientation(items)
        assert orientation.ambiguous_anchor
        assert orientation.reversed_keys == set()
