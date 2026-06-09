from __future__ import annotations

from software.core.psychometrics.ordinal_options import infer_ordinal_option_mapping


class OrdinalOptionTests:
    def test_numeric_options_are_supported(self) -> None:
        mapping = infer_ordinal_option_mapping(["1", "2", "3", "4", "5"])
        assert mapping is not None
        assert mapping.score_by_choice_index == [0, 1, 2, 3, 4]

    def test_numeric_score_options_are_supported(self) -> None:
        mapping = infer_ordinal_option_mapping(["1分", "2分", "3分", "4分", "5分"])
        assert mapping is not None
        assert mapping.score_by_choice_index == [0, 1, 2, 3, 4]

    def test_satisfaction_options_are_supported(self) -> None:
        mapping = infer_ordinal_option_mapping(["非常不满意", "不满意", "一般", "满意", "非常满意"])
        assert mapping is not None
        assert mapping.score_by_choice_index == [0, 1, 2, 3, 4]

    def test_obvious_attitude_single_options_are_supported(self) -> None:
        mapping = infer_ordinal_option_mapping(["非常不同意", "比较不同意", "没意见", "比较同意", "非常同意"])
        assert mapping is not None
        assert mapping.score_by_choice_index == [0, 1, 2, 3, 4]

    def test_attitude_single_options_support_common_variants(self) -> None:
        samples = [
            ["非常不同意", "较不同意", "中立", "较同意", "非常同意"],
            ["非常不同意", "不太同意", "一般", "比较同意", "非常同意"],
            ["完全不支持", "不太支持", "说不清", "比较支持", "强烈支持"],
            ["非常少", "较少", "一般", "较多", "非常多"],
        ]
        for option_texts in samples:
            mapping = infer_ordinal_option_mapping(option_texts)
            assert mapping is not None
            assert mapping.score_by_choice_index == [0, 1, 2, 3, 4]

    def test_reversed_attitude_single_options_are_supported(self) -> None:
        mapping = infer_ordinal_option_mapping(["非常同意", "比较同意", "没意见", "比较不同意", "非常不同意"])
        assert mapping is not None
        assert mapping.score_by_choice_index == [4, 3, 2, 1, 0]

    def test_reversed_satisfaction_options_are_supported(self) -> None:
        mapping = infer_ordinal_option_mapping(["非常满意", "满意", "一般", "不满意", "非常不满意"])
        assert mapping is not None
        assert mapping.score_by_choice_index == [4, 3, 2, 1, 0]

    def test_nominal_options_are_not_supported(self) -> None:
        assert infer_ordinal_option_mapping(["男", "女"]) is None
        assert infer_ordinal_option_mapping(["北京", "上海", "广州"]) is None
        assert infer_ordinal_option_mapping(["学生", "教师", "企业员工"]) is None
