from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from software.core.questions import utils


class _Element:
    def __init__(self, text: str = "", attrs: dict[str, str] | None = None, displayed: bool = True) -> None:
        self.text = text
        self.attrs = attrs or {}
        self.displayed = displayed
        self.sent: list[str] = []
        self.cleared = 0

    def get_attribute(self, name: str):
        return self.attrs.get(name)

    def is_displayed(self) -> bool:
        return self.displayed

    def clear(self) -> None:
        self.cleared += 1

    def send_keys(self, value: str) -> None:
        self.sent.append(value)


class _QuestionDiv:
    def __init__(self, mapping: dict[str, list[object]]) -> None:
        self.mapping = mapping

    def find_elements(self, _by, selector: str):
        return list(self.mapping.get(selector, []))


class _Driver:
    def __init__(self, question_div: object | None = None) -> None:
        self.question_div = question_div
        self.scripts: list[tuple[str, tuple[object, ...]]] = []
        self.values: list[object] = []

    def find_element(self, _by, _selector: str):
        if self.question_div is None:
            raise RuntimeError("not found")
        return self.question_div

    def execute_script(self, script: str, *args):
        self.scripts.append((script, args))
        if self.values:
            value = self.values.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        return None


class QuestionUtilsRuntimeTests:
    def test_weighted_index_sanitizes_invalid_weights(self, patch_attrs) -> None:
        patch_attrs((utils.random, "random", lambda: 0.0), (utils.random, "randrange", lambda count: count - 1))
        assert utils.weighted_index([0, float("nan"), -1, 2]) == 3
        assert utils.weighted_index([0, 0]) == 1
        with pytest.raises(ValueError):
            utils.weighted_index([])

    def test_random_int_helpers_round_trip_and_validate(self, patch_attrs) -> None:
        assert utils.try_parse_random_int_range({"min": "9", "max": "3"}) == (3, 9)
        assert utils.try_parse_random_int_range(["", 3]) is None
        assert utils.serialize_random_int_range(["2", "5"]) == [2, 5]
        assert utils.describe_random_int_range([2, 5]) == "2-5"
        token = utils.build_random_int_token(9, 3)
        assert token == "__RANDOM_INT__:3:9"
        assert utils.parse_random_int_token(token) == (3, 9)
        patch_attrs((utils.random, "randint", lambda a, _b: a))
        assert utils.resolve_dynamic_text_token(token) == "3"
        with pytest.raises(ValueError):
            utils.normalize_random_int_range("bad")

    def test_random_identity_generators_use_persona_and_checksum(self, patch_attrs) -> None:
        patch_attrs(
            (utils, "_load_id_card_area_codes", lambda: ("110100",)),
            (utils, "_choose_random_birth_date_for_id_card", lambda: date(2000, 1, 2)),
            (utils, "_choose_id_card_sequence_tail", lambda: "123"),
        )
        card = utils.generate_random_id_card()
        assert card.startswith("11010020000102123")
        assert len(card) == 18
        assert card[-1] == utils._calculate_id_card_checksum(card[:17])

    def test_resolve_dynamic_text_token_handles_builtin_tokens(self, patch_attrs) -> None:
        patch_attrs(
            (utils, "generate_random_chinese_name", lambda: "张三"),
            (utils, "generate_random_mobile", lambda: "13900000000"),
            (utils, "generate_random_id_card", lambda: "110100200001011234"),
            (utils, "generate_random_generic_text", lambda: "随机文本"),
        )

        assert utils.resolve_dynamic_text_token("__RANDOM_NAME__") == "张三"
        assert utils.resolve_dynamic_text_token("__RANDOM_MOBILE__") == "13900000000"
        assert utils.resolve_dynamic_text_token("__RANDOM_ID_CARD__") == "110100200001011234"
        assert utils.resolve_dynamic_text_token("__RANDOM_TEXT__") == "随机文本"
        assert utils.resolve_dynamic_text_token("") == utils.DEFAULT_FILL_TEXT
        assert utils.resolve_dynamic_text_token(" 固定 ") == "固定"

    def test_option_fill_text_config_and_ai_errors(self) -> None:
        assert utils.get_fill_text_from_config(["A"], 0) == "A"
        assert utils.get_fill_text_from_config([""], 0) is None
        assert utils.get_fill_text_from_config(["A"], 2) is None
        assert utils.resolve_option_fill_text_from_config(["__RANDOM_INT__:1:1"], 0) == "1"

        with pytest.raises(Exception, match="缺少运行时上下文"):
            utils.resolve_option_fill_text_from_config([utils.OPTION_FILL_AI_TOKEN], 0)

    def test_extract_text_from_element_uses_text_then_text_content(self) -> None:
        assert utils.extract_text_from_element(_Element(text="  文本  ")) == "文本"
        assert utils.extract_text_from_element(_Element(attrs={"textContent": "  属性文本  "})) == "属性文本"

    def test_fill_option_additional_text_uses_option_scoped_visible_input(self, patch_attrs) -> None:
        input_element = _Element()
        option = SimpleNamespace(find_elements=lambda _by, selector: [input_element] if "input" in selector else [])
        question_div = _QuestionDiv({"div.ui-controlgroup > div": [option]})
        driver = _Driver(question_div)
        patch_attrs((utils, "smooth_scroll_to_element", lambda *_args, **_kwargs: None), (utils.time, "sleep", lambda *_args: None))

        utils.fill_option_additional_text(driver, 1, 0, "补充")

        assert input_element.cleared == 1
        assert input_element.sent == ["补充"]

    def test_fill_option_additional_text_falls_back_to_question_inputs_and_skips_hidden(self, patch_attrs) -> None:
        hidden = _Element(displayed=False)
        visible = _Element()
        question_div = _QuestionDiv(
            {
                "div.ui-controlgroup > div": [],
                ".ui-other input, .ui-other textarea": [],
                "input[type='text'], input[type='search'], textarea": [hidden, visible],
            }
        )
        driver = _Driver(question_div)
        patch_attrs((utils, "smooth_scroll_to_element", lambda *_args, **_kwargs: None), (utils.time, "sleep", lambda *_args: None))

        utils.fill_option_additional_text(driver, 1, 0, "兜底")

        assert hidden.sent == []
        assert visible.sent == ["兜底"]

    def test_smooth_scroll_quick_and_full_simulation_paths(self, patch_attrs) -> None:
        driver = _Driver()
        element = object()
        utils.smooth_scroll_to_element(driver, element, "center", full_simulation_active=False)
        assert "scrollIntoView" in driver.scripts[-1][0]

        driver = _Driver()
        driver.values = [300, 0, 600]
        patch_attrs((utils.random, "uniform", lambda _a, _b: 0.0), (utils.time, "sleep", lambda *_args: None))
        utils.smooth_scroll_to_element(driver, element, "start", full_simulation_active=True)
        assert any("window.scrollTo" in script for script, _args in driver.scripts)

    def test_probability_config_helpers(self) -> None:
        assert utils.normalize_droplist_probs(None, 2) == [0.5, 0.5]
        assert utils.normalize_droplist_probs([1, None, -1], 3) == [1.0, 0.0, 0.0]
        assert utils.normalize_droplist_probs("bad", 2) == [0.5, 0.5]
        assert utils.normalize_droplist_probs([0, 0], 2) == [0.5, 0.5]
        assert utils.normalize_single_like_prob_config(None, 2) == -1
        assert utils.normalize_option_fill_texts([" A ", "", None], 3) == ["A", None, None]
        assert utils.normalize_option_fill_texts(["", None], 2) is None
        assert utils.resolve_prob_config(None, [0, 5], prefer_custom=True) == [0, 5]
        assert utils.resolve_prob_config([0, 0], [1, 0], prefer_custom=True) == [1, 0]
        assert utils.resolve_prob_config([1, 0], [0, 5], prefer_custom=True) == [1, 0]
