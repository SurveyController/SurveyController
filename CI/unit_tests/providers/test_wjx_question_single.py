from __future__ import annotations

from types import SimpleNamespace

from wjx.provider.questions import single as single_module


class _FakeSingleElement:
    def __init__(
        self,
        *,
        text: str = "",
        attrs: dict[str, str] | None = None,
        displayed: bool = True,
        children: dict[str, list["_FakeSingleElement"]] | None = None,
        click_side_effect: Exception | None = None,
    ) -> None:
        self.text = text
        self.attrs = dict(attrs or {})
        self.displayed = displayed
        self.children = dict(children or {})
        self.click_side_effect = click_side_effect
        self.clicks = 0

    def get_attribute(self, name: str):
        return self.attrs.get(name)

    def find_elements(self, _by, selector: str):
        return list(self.children.get(selector, []))

    def is_displayed(self) -> bool:
        return self.displayed

    def click(self) -> None:
        self.clicks += 1
        if self.click_side_effect is not None:
            raise self.click_side_effect


class _FakeSingleDriver:
    def __init__(
        self,
        *,
        find_element_map: dict[tuple[object, str], object] | None = None,
        find_elements_map: dict[tuple[object, str], list[object]] | None = None,
        execute_script_result: object = None,
    ) -> None:
        self.find_element_map = dict(find_element_map or {})
        self.find_elements_map = dict(find_elements_map or {})
        self.execute_script_result = execute_script_result
        self.scripts: list[tuple[str, tuple[object, ...]]] = []

    def find_element(self, by, selector: str):
        key = (by, selector)
        if key not in self.find_element_map:
            raise RuntimeError("not found")
        return self.find_element_map[key]

    def find_elements(self, by, selector: str):
        return list(self.find_elements_map.get((by, selector), []))

    def execute_script(self, script: str, *args):
        self.scripts.append((script, args))
        return self.execute_script_result


class WjxQuestionSingleTests:
    def test_option_shape_and_text_helpers(self, patch_attrs) -> None:
        label = _FakeSingleElement(text="标签文本")
        option = _FakeSingleElement(
            text="整体文本",
            attrs={"class": "ui-radio", "type": "radio"},
            children={".label, label": [label]},
        )
        patch_attrs((single_module, "extract_text_from_element", lambda element: element.text))

        assert single_module._looks_like_single_option(option)
        assert single_module._extract_single_option_text(option) == "标签文本"

    def test_looks_like_single_option_accepts_nested_radio(self) -> None:
        option = _FakeSingleElement(children={
            "input[type='radio'], .jqradio, a.jqradio, .jqradiowrapper": [_FakeSingleElement()]
        })

        assert single_module._looks_like_single_option(option)

    def test_single_option_selected_uses_js_result(self) -> None:
        driver = _FakeSingleDriver(execute_script_result=True)
        assert single_module._is_single_option_selected(driver, _FakeSingleElement())

    def test_single_option_selected_returns_false_on_js_error(self) -> None:
        class _BrokenDriver(_FakeSingleDriver):
            def execute_script(self, script: str, *args):
                raise RuntimeError("boom")

        assert not single_module._is_single_option_selected(_BrokenDriver(), _FakeSingleElement())

    def test_single_option_free_text_detection_and_required_check(self) -> None:
        free_text = _FakeSingleElement(attrs={"type": "text"})
        target = _FakeSingleElement(children={
            "select": [],
            "input.OtherRadioText, input[type='text'], input[type='search'], input[type='tel'], input[type='number'], textarea": [free_text],
        })
        driver = _FakeSingleDriver(execute_script_result=True)

        assert single_module._single_option_has_free_text_input(target)
        assert single_module._single_option_free_text_input_is_required(driver, target)

    def test_single_option_has_free_text_input_returns_false_when_only_select_exists(self) -> None:
        target = _FakeSingleElement(children={"select": [_FakeSingleElement()]})

        assert not single_module._single_option_has_free_text_input(target)

    def test_extract_attached_select_options_skips_placeholder(self) -> None:
        option1 = _FakeSingleElement(text="请选择", attrs={"value": ""})
        option2 = _FakeSingleElement(text="上海", attrs={"value": "shanghai"})
        select = _FakeSingleElement(children={"option": [option1, option2]})
        target = _FakeSingleElement(children={"select": [select]})

        select_element, options = single_module._extract_attached_select_options(target)

        assert select_element is select
        assert options == [("shanghai", "上海")]

    def test_select_attached_option_via_js_returns_bool(self) -> None:
        driver = _FakeSingleDriver(execute_script_result=True)
        assert single_module._select_attached_option_via_js(driver, object(), "beijing", "北京")

    def test_handle_attached_select_uses_fill_value_match_first(self, patch_attrs) -> None:
        driver = _FakeSingleDriver()
        target = _FakeSingleElement()
        patch_attrs(
            (
                single_module,
                "_extract_attached_select_options",
                lambda _target: (object(), [("beijing", "北京"), ("shanghai", "上海")]),
            ),
            (single_module, "_select_attached_option_via_js", lambda *_args, **_kwargs: True),
            (single_module, "weighted_index", lambda _weights: 1),
        )

        result = single_module._handle_attached_select(
            driver,
            5,
            0,
            target,
            "上海",
            attached_selects_config=[{"option_index": 0, "weights": [0.0, 1.0]}],
        )

        assert result == "上海"

    def test_click_single_option_accepts_direct_click_success(self, patch_attrs) -> None:
        target = _FakeSingleElement()
        label = _FakeSingleElement()
        target.children = {
            ".label, label, .jqradio, a.jqradio, .jqradiowrapper, input[type='radio']": [label]
        }
        driver = _FakeSingleDriver()
        patch_attrs(
            (single_module, "smooth_scroll_to_element", lambda *_args, **_kwargs: None),
            (single_module, "_is_single_option_selected", lambda *_args, **_kwargs: True),
        )

        assert single_module._click_single_option(driver, 3, 1, target)
        assert target.clicks == 1

    def test_single_main_flow_uses_reverse_fill_and_records_answer(self, patch_attrs) -> None:
        option1 = _FakeSingleElement(text="选项A")
        option2 = _FakeSingleElement(text="选项B")
        driver = _FakeSingleDriver(find_elements_map={
            (single_module.By.CSS_SELECTOR, "#div7 > div.ui-controlgroup > div"): [option1, option2],
            (single_module.By.CSS_SELECTOR, "#div7 .ui-controlgroup > div.ui-radio"): [],
            (single_module.By.CSS_SELECTOR, "#div7 .ui-controlgroup > div"): [],
            (single_module.By.XPATH, '//*[@id="div7"]//div[contains(@class,"ui-radio")]'): [],
            (single_module.By.XPATH, '//*[@id="div7"]//li[.//input[@type="radio"] or .//a[contains(@class,"jqradio")]]'): [],
            (single_module.By.XPATH, '//*[@id="div7"]//label[.//input[@type="radio"]]'): [],
        })
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        patch_attrs(
            (single_module, "_looks_like_single_option", lambda _elem: True),
            (single_module, "_extract_single_option_text", lambda elem: elem.text),
            (single_module, "normalize_droplist_probs", lambda _config, length: [1.0 / length] * length),
            (single_module, "resolve_current_reverse_fill_answer", lambda _ctx, _current: SimpleNamespace(kind=single_module.REVERSE_FILL_KIND_CHOICE, choice_index=1)),
            (single_module, "_click_single_option", lambda *_args, **_kwargs: True),
            (single_module, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs))),
        )

        single_module.single(
            driver,
            7,
            0,
            single_prob_config=[[0.5, 0.5]],
            single_option_fill_texts_config=[],
            task_ctx=object(),
        )

        assert recorded == [((7, "single"), {"selected_indices": [1], "selected_texts": ["选项B"]})]

    def test_single_main_flow_skips_out_of_range_reverse_fill(self, patch_attrs) -> None:
        option1 = _FakeSingleElement(text="选项A")
        driver = _FakeSingleDriver(find_elements_map={
            (single_module.By.CSS_SELECTOR, "#div7 > div.ui-controlgroup > div"): [option1],
            (single_module.By.CSS_SELECTOR, "#div7 .ui-controlgroup > div.ui-radio"): [],
            (single_module.By.CSS_SELECTOR, "#div7 .ui-controlgroup > div"): [],
            (single_module.By.XPATH, '//*[@id="div7"]//div[contains(@class,"ui-radio")]'): [],
            (single_module.By.XPATH, '//*[@id="div7"]//li[.//input[@type="radio"] or .//a[contains(@class,"jqradio")]]'): [],
            (single_module.By.XPATH, '//*[@id="div7"]//label[.//input[@type="radio"]]'): [],
        })
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        patch_attrs(
            (single_module, "_looks_like_single_option", lambda _elem: True),
            (single_module, "_extract_single_option_text", lambda elem: elem.text),
            (single_module, "normalize_droplist_probs", lambda _config, length: [1.0 / length] * length),
            (
                single_module,
                "resolve_current_reverse_fill_answer",
                lambda _ctx, _current: SimpleNamespace(kind=single_module.REVERSE_FILL_KIND_CHOICE, choice_index=3),
            ),
            (single_module, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs))),
        )

        single_module.single(
            driver,
            7,
            0,
            single_prob_config=[[1.0]],
            single_option_fill_texts_config=[],
            task_ctx=object(),
        )

        assert recorded == []

    def test_single_main_flow_fills_required_free_text_and_attached_select(self, patch_attrs) -> None:
        option = _FakeSingleElement(text="其他")
        driver = _FakeSingleDriver(find_elements_map={
            (single_module.By.CSS_SELECTOR, "#div8 > div.ui-controlgroup > div"): [option],
            (single_module.By.CSS_SELECTOR, "#div8 .ui-controlgroup > div.ui-radio"): [],
            (single_module.By.CSS_SELECTOR, "#div8 .ui-controlgroup > div"): [],
            (single_module.By.XPATH, '//*[@id="div8"]//div[contains(@class,"ui-radio")]'): [],
            (single_module.By.XPATH, '//*[@id="div8"]//li[.//input[@type="radio"] or .//a[contains(@class,"jqradio")]]'): [],
            (single_module.By.XPATH, '//*[@id="div8"]//label[.//input[@type="radio"]]'): [],
        })
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        fill_calls: list[str] = []
        patch_attrs(
            (single_module, "_looks_like_single_option", lambda _elem: True),
            (single_module, "_extract_single_option_text", lambda elem: elem.text),
            (single_module, "normalize_droplist_probs", lambda _config, _length: [1.0]),
            (single_module, "resolve_current_reverse_fill_answer", lambda _ctx, _current: None),
            (single_module, "apply_persona_boost", lambda _texts, probs: probs),
            (single_module, "apply_single_like_consistency", lambda probs, _current: probs),
            (single_module, "weighted_index", lambda _weights: 0),
            (single_module, "_click_single_option", lambda *_args, **_kwargs: True),
            (single_module, "_single_option_has_free_text_input", lambda _elem: True),
            (single_module, "_single_option_free_text_input_is_required", lambda *_args, **_kwargs: True),
            (single_module, "resolve_option_fill_text_from_config", lambda *_args, **_kwargs: ""),
            (single_module, "_handle_attached_select", lambda *_args, **_kwargs: "北京"),
            (single_module, "fill_option_additional_text", lambda _driver, _current, _index, value: fill_calls.append(value)),
            (single_module, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs))),
            (single_module, "resolve_distribution_probabilities", lambda probs, _len, _ctx, _current: probs),
            (single_module, "record_pending_distribution_choice", lambda *_args, **_kwargs: None),
            (single_module, "is_strict_ratio_question", lambda *_args, **_kwargs: False),
        )

        single_module.single(
            driver,
            8,
            0,
            single_prob_config=[[1.0]],
            single_option_fill_texts_config=[[]],
            single_attached_selects_config=[[{"option_index": 0, "weights": [1.0]}]],
            task_ctx=object(),
        )

        assert fill_calls == ["无"]
        assert recorded == [((8, "single"), {"selected_indices": [0], "selected_texts": ["其他 / 北京"]})]

    def test_single_main_flow_skips_when_click_not_effective(self, patch_attrs) -> None:
        option = _FakeSingleElement(text="选项A")
        driver = _FakeSingleDriver(find_elements_map={
            (single_module.By.CSS_SELECTOR, "#div9 > div.ui-controlgroup > div"): [option],
            (single_module.By.CSS_SELECTOR, "#div9 .ui-controlgroup > div.ui-radio"): [],
            (single_module.By.CSS_SELECTOR, "#div9 .ui-controlgroup > div"): [],
            (single_module.By.XPATH, '//*[@id="div9"]//div[contains(@class,"ui-radio")]'): [],
            (single_module.By.XPATH, '//*[@id="div9"]//li[.//input[@type="radio"] or .//a[contains(@class,"jqradio")]]'): [],
            (single_module.By.XPATH, '//*[@id="div9"]//label[.//input[@type="radio"]]'): [],
        })
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        patch_attrs(
            (single_module, "_looks_like_single_option", lambda _elem: True),
            (single_module, "_extract_single_option_text", lambda elem: elem.text),
            (single_module, "normalize_droplist_probs", lambda _config, _length: [1.0]),
            (single_module, "resolve_current_reverse_fill_answer", lambda _ctx, _current: None),
            (single_module, "apply_persona_boost", lambda _texts, probs: probs),
            (single_module, "apply_single_like_consistency", lambda probs, _current: probs),
            (single_module, "weighted_index", lambda _weights: 0),
            (single_module, "_click_single_option", lambda *_args, **_kwargs: False),
            (single_module, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs))),
            (single_module, "resolve_distribution_probabilities", lambda probs, _len, _ctx, _current: probs),
            (single_module, "record_pending_distribution_choice", lambda *_args, **_kwargs: None),
            (single_module, "is_strict_ratio_question", lambda *_args, **_kwargs: False),
        )

        single_module.single(
            driver,
            9,
            0,
            single_prob_config=[[1.0]],
            single_option_fill_texts_config=[[]],
            task_ctx=object(),
        )

        assert recorded == []
