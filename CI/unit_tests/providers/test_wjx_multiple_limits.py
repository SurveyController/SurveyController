from __future__ import annotations

from wjx.provider.questions import multiple_limits


class _FakeElement:
    def __init__(self, attributes: dict[str, str] | None = None) -> None:
        self.attributes = dict(attributes or {})

    def get_attribute(self, name: str):
        return self.attributes.get(name)


class WjxMultipleLimitsTests:
    def test_safe_positive_int_accepts_numbers_and_numeric_text(self) -> None:
        assert multiple_limits._safe_positive_int(3) == 3
        assert multiple_limits._safe_positive_int(" 7 ") == 7
        assert multiple_limits._safe_positive_int("最多选4项") == 4
        assert multiple_limits._safe_positive_int(0) is None
        assert multiple_limits._safe_positive_int(False) is None

    def test_extract_range_from_json_obj_and_possible_json(self) -> None:
        assert multiple_limits._extract_range_from_json_obj({"rules": {"min": 2, "max": 5}}) == (2, 5)
        assert multiple_limits._extract_range_from_possible_json('{"min":2,"max":5}') == (2, 5)
        assert multiple_limits._extract_range_from_possible_json("{'minValue':2,'maxValue':4}") == (2, 4)
        assert multiple_limits._extract_range_from_possible_json("min=1 max=3") == (1, 3)

    def test_extract_min_max_from_attributes_reads_supported_names(self) -> None:
        element = _FakeElement({"minvalue": "2", "maxvalue": "6"})
        assert multiple_limits._extract_min_max_from_attributes(element) == (2, 6)

    def test_extract_multi_limit_range_from_text_supports_cn_and_en_patterns(self) -> None:
        assert multiple_limits._extract_multi_limit_range_from_text("请选择2-4项你喜欢的功能") == (2, 4)
        assert multiple_limits._extract_multi_limit_range_from_text("至少选2项，最多选5项") == (2, 5)
        assert multiple_limits._extract_multi_limit_range_from_text("请选择3项") == (3, 3)
        assert multiple_limits._extract_multi_limit_range_from_text("Select between 2 and 4 options") == (2, 4)
        assert multiple_limits._extract_multi_limit_range_from_text("Select up to 3 options") == (None, 3)
        assert multiple_limits._extract_multi_limit_range_from_text("At least 2 choices") == (2, None)

    def test_extract_multi_limit_range_from_text_normalizes_swapped_range(self) -> None:
        assert multiple_limits._extract_multi_limit_range_from_text("请选择5到2项") == (2, 5)
        assert multiple_limits._extract_multi_limit_range_from_text("最多选择 4 项") == (None, 4)
        assert multiple_limits._extract_multi_limit_range_from_text("最少选择 2 项") == (2, None)

    def test_extract_range_from_json_obj_walks_nested_lists(self) -> None:
        payload = [{"ignore": 1}, {"rules": [{"minValue": "2"}, {"maxValue": "6"}]}]
        assert multiple_limits._extract_range_from_json_obj(payload) == (2, 6)

    def test_extract_range_from_possible_json_returns_empty_for_invalid_input(self) -> None:
        assert multiple_limits._extract_range_from_possible_json(None) == (None, None)
        assert multiple_limits._extract_range_from_possible_json("not-json") == (None, None)

    def test_extract_min_max_from_attributes_handles_missing_values(self) -> None:
        element = _FakeElement({"minvalue": "0", "maxvalue": ""})
        assert multiple_limits._extract_min_max_from_attributes(element) == (None, None)
