from __future__ import annotations

from types import SimpleNamespace

from wjx.provider.questions import text as text_module


class _FakeTextElement:
    def __init__(
        self,
        *,
        tag_name: str = "input",
        attrs: dict[str, str] | None = None,
        displayed: bool = True,
        sibling: "_FakeTextElement | None" = None,
        children: dict[str, list["_FakeTextElement"]] | None = None,
    ) -> None:
        self.tag_name = tag_name
        self.attrs = dict(attrs or {})
        self.displayed = displayed
        self.sibling = sibling
        self.children = dict(children or {})
        self.cleared = 0
        self.sent_keys: list[str] = []
        self.clicked = 0

    def get_attribute(self, name: str):
        return self.attrs.get(name)

    def is_displayed(self) -> bool:
        return self.displayed

    def find_element(self, _by, selector: str):
        if selector == "following-sibling::*[1]" and self.sibling is not None:
            return self.sibling
        raise RuntimeError("not found")

    def find_elements(self, _by, selector: str):
        return list(self.children.get(selector, []))

    def clear(self) -> None:
        self.cleared += 1

    def send_keys(self, value: str) -> None:
        self.sent_keys.append(value)

    def click(self) -> None:
        self.clicked += 1


class _FakeTextDriver:
    def __init__(
        self,
        *,
        find_element_map: dict[tuple[object, str], object] | None = None,
        find_elements_map: dict[tuple[object, str], list[object]] | None = None,
    ) -> None:
        self.find_element_map = dict(find_element_map or {})
        self.find_elements_map = dict(find_elements_map or {})
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
        if "return (function()" in script:
            return True
        return None


class WjxQuestionTextTests:
    def test_preview_and_source_summary_helpers(self) -> None:
        assert text_module._preview_text_answer(["A", "", None]) == "A | 无 | 无"
        assert text_module._preview_text_answer("   ") == "无"
        assert text_module._summarize_multi_text_sources(["配置", "AI", "配置"]) == "混合(配置/AI)"
        assert text_module._summarize_multi_text_sources([]) == "配置"

    def test_log_text_answer_uses_preview(self, patch_attrs) -> None:
        messages: list[tuple[tuple[object, ...], dict[str, object]]] = []
        patch_attrs((text_module.logging, "info", lambda *args, **kwargs: messages.append((args, kwargs))))

        text_module._log_text_answer(5, "标题", "配置", ["甲", ""])

        assert messages
        assert "来源=%s 标题=%s 答案=%s" in messages[0][0][0]

    def test_fill_text_question_input_uses_send_keys_for_normal_input(self) -> None:
        driver = _FakeTextDriver()
        element = _FakeTextElement(attrs={"readonly": ""})

        text_module.fill_text_question_input(driver, element, "你好")

        assert element.cleared == 1
        assert element.sent_keys == ["你好"]
        assert len(driver.scripts) == 1

    def test_fill_text_question_input_uses_js_for_readonly_input(self) -> None:
        driver = _FakeTextDriver()
        element = _FakeTextElement(attrs={"readonly": "readonly"})

        text_module.fill_text_question_input(driver, element, "只读值")

        assert element.cleared == 0
        assert element.sent_keys == []
        assert len(driver.scripts) == 1

    def test_fill_contenteditable_element_updates_by_script_and_send_keys(self) -> None:
        driver = _FakeTextDriver()
        element = _FakeTextElement(tag_name="div", attrs={"contenteditable": "true"})

        text_module.fill_contenteditable_element(driver, element, "富文本答案")

        assert element.sent_keys == ["富文本答案"]
        assert len(driver.scripts) == 2

    def test_ensure_min_word_answer_extends_short_answer(self) -> None:
        answer = text_module.ensure_min_word_answer("AI答案", 30, "请简述您的个人发展目标和计划")

        assert answer.startswith("AI答案")
        assert text_module._visible_text_length(answer) >= 30

    def test_count_visible_text_inputs_skips_hidden_and_textedit_shadow_input(self) -> None:
        shadow_label = _FakeTextElement(tag_name="span", attrs={"class": "textedit"})
        candidates = [
            _FakeTextElement(tag_name="input", attrs={"type": "text"}),
            _FakeTextElement(tag_name="textarea"),
            _FakeTextElement(tag_name="div", attrs={"contenteditable": "true"}),
            _FakeTextElement(tag_name="input", attrs={"type": "hidden"}),
            _FakeTextElement(tag_name="input", attrs={"type": "text"}, sibling=shadow_label),
            _FakeTextElement(tag_name="input", attrs={"type": "text", "style": "display:none"}),
        ]
        question_div = _FakeTextElement(children={
            "input, textarea, span[contenteditable='true'], div[contenteditable='true'], .textCont, .textcont": candidates
        })

        assert text_module.count_visible_text_inputs(question_div) == 3

    def test_infer_text_entry_type_marks_multi_text_and_location_text(self, patch_attrs) -> None:
        driver = _FakeTextDriver(find_element_map={(text_module.By.CSS_SELECTOR, "#div7"): object()})
        patch_attrs(
            (text_module, "count_visible_text_inputs", lambda _div: 2),
            (text_module, "count_prefixed_text_inputs", lambda *_args, **_kwargs: 2),
            (text_module, "driver_question_is_location", lambda _div: False),
        )
        entry_type, answers = text_module.infer_text_entry_type(driver, 7)
        assert entry_type == "multi_text"
        assert answers == ["无||无"]

        patch_attrs((text_module, "driver_question_is_location", lambda _div: True))
        entry_type, answers = text_module.infer_text_entry_type(driver, 7)
        assert entry_type == "text"
        assert answers == ["无"]

    def test_resolve_multi_blank_count_uses_max_of_prefixed_and_visible_inputs(self, patch_attrs) -> None:
        driver = _FakeTextDriver(find_element_map={(text_module.By.CSS_SELECTOR, "#div9"): object()})
        patch_attrs(
            (text_module, "count_prefixed_text_inputs", lambda *_args, **_kwargs: 3),
            (text_module, "count_visible_text_inputs", lambda _div: 2),
        )
        assert text_module.resolve_multi_blank_count(driver, 9) == 3

    def test_driver_question_is_location_detects_css_marker_and_verify_attr(self) -> None:
        css_hit_div = _FakeTextElement(children={".get_Local": [_FakeTextElement()]})
        assert text_module.driver_question_is_location(css_hit_div)

        verify_input = _FakeTextElement(attrs={"verify": "腾讯地图定位"})
        verify_div = _FakeTextElement(children={"input[verify], .get_Local input, input": [verify_input]})
        assert text_module.driver_question_is_location(verify_div)

    def test_driver_question_is_location_returns_false_when_no_marker(self) -> None:
        normal_div = _FakeTextElement(children={"input[verify], .get_Local input, input": [_FakeTextElement()]})

        assert not text_module.driver_question_is_location(normal_div)

    def test_should_mark_as_multi_text_respects_type_count_and_location(self) -> None:
        assert text_module.should_mark_as_multi_text("1", 0, 2, False)
        assert text_module.should_mark_as_multi_text("9", 0, 2, False)
        assert not text_module.should_mark_as_multi_text("3", 0, 2, False)
        assert not text_module.should_mark_as_multi_text("1", 0, 1, False)
        assert not text_module.should_mark_as_multi_text("1", 0, 2, True)

    def test_handle_multi_text_applies_blank_modes_and_fills_inputs(self, patch_attrs) -> None:
        input1 = _FakeTextElement(tag_name="input", attrs={"type": "text"})
        input2 = _FakeTextElement(tag_name="textarea")
        question_div = _FakeTextElement(children={
            "input, textarea": [input1, input2],
            "span[contenteditable='true'], div[contenteditable='true'], .textCont": [],
            "input[id^='q11_'], textarea[id^='q11_']": [],
        })
        driver = _FakeTextDriver(find_element_map={(text_module.By.CSS_SELECTOR, "#div11"): question_div})
        patch_attrs(
            (text_module, "generate_random_integer_text", lambda _start, _end: "42"),
            (text_module, "try_parse_random_int_range", lambda _value: (10, 99)),
            (text_module, "describe_random_int_range", lambda _value: "10-99"),
        )

        values, sources = text_module._handle_multi_text(
            driver,
            11,
            "A||B",
            blank_modes=["integer", "text"],
            blank_ai_flags=[False, False],
            blank_int_ranges=[["10", "99"], []],
        )

        assert values == ["42", "B"]
        assert sources == ["随机整数(10-99)", "配置"]
        assert input1.sent_keys == ["42"]
        assert input2.sent_keys == ["B"]
        assert len(driver.scripts) >= 3

    def test_handle_single_text_falls_back_to_contenteditable(self, patch_attrs) -> None:
        editable = _FakeTextElement(tag_name="div", attrs={"contenteditable": "true"})
        question_div = _FakeTextElement(children={
            "input, textarea": [],
            "span[contenteditable='true'], div[contenteditable='true'], .textCont, .textcont": [editable],
        })
        driver = _FakeTextDriver(find_element_map={(text_module.By.CSS_SELECTOR, "#div12"): question_div})
        calls: list[str] = []
        patch_attrs(
            (text_module, "fill_contenteditable_element", lambda _driver, _element, value: calls.append(value)),
            (text_module, "smooth_scroll_to_element", lambda *_args, **_kwargs: None),
        )

        text_module._handle_single_text(driver, 12, "富文本")

        assert editable.clicked == 1
        assert calls == ["富文本"]

    def test_text_handles_reverse_fill_multi_text_branch(self, patch_attrs) -> None:
        captured: list[tuple[tuple[object, ...], dict[str, object]]] = []
        patch_attrs(
            (
                text_module,
                "resolve_current_reverse_fill_answer",
                lambda _ctx, _current: SimpleNamespace(
                    kind=text_module.REVERSE_FILL_KIND_MULTI_TEXT,
                    text_values=["甲", "乙"],
                ),
            ),
            (text_module, "_handle_multi_text", lambda *_args, **_kwargs: (["甲", "乙"], ["反填", "反填"])),
            (text_module, "_log_text_answer", lambda *_args, **_kwargs: None),
            (text_module, "record_answer", lambda *args, **kwargs: captured.append((args, kwargs))),
        )

        text_module.text(
            _FakeTextDriver(),
            3,
            0,
            texts_config=[],
            texts_prob_config=[],
            text_entry_types_config=[],
            task_ctx=object(),
        )

        assert captured == [((3, "text"), {"text_answer": "甲 | 乙"})]

    def test_text_handles_reverse_fill_single_text_branch(self, patch_attrs) -> None:
        captured: list[tuple[tuple[object, ...], dict[str, object]]] = []
        calls: list[str] = []
        patch_attrs(
            (
                text_module,
                "resolve_current_reverse_fill_answer",
                lambda _ctx, _current: SimpleNamespace(
                    kind=text_module.REVERSE_FILL_KIND_TEXT,
                    text_value="反填答案",
                ),
            ),
            (text_module, "_handle_single_text", lambda _driver, _current, answer: calls.append(answer)),
            (text_module, "_log_text_answer", lambda *_args, **_kwargs: None),
            (text_module, "record_answer", lambda *args, **kwargs: captured.append((args, kwargs))),
        )

        text_module.text(
            _FakeTextDriver(),
            6,
            0,
            texts_config=[],
            texts_prob_config=[],
            text_entry_types_config=[],
            task_ctx=object(),
        )

        assert calls == ["反填答案"]
        assert captured == [((6, "text"), {"text_answer": "反填答案"})]

    def test_text_ai_single_text_branch_records_generated_answer(self, patch_attrs) -> None:
        captured: list[tuple[tuple[object, ...], dict[str, object]]] = []
        calls: list[str] = []
        patch_attrs(
            (text_module, "resolve_current_reverse_fill_answer", lambda _ctx, _current: None),
            (text_module, "weighted_index", lambda _weights: 0),
            (text_module, "count_prefixed_text_inputs", lambda *_args, **_kwargs: 0),
            (text_module, "resolve_dynamic_text_token", lambda value: value),
            (text_module, "resolve_question_title_for_ai", lambda _driver, _current, fallback: fallback or "题目标题"),
            (text_module, "generate_ai_answer", lambda *_args, **_kwargs: "AI答案"),
            (text_module, "resolve_text_min_word_count", lambda *_args, **_kwargs: 30),
            (text_module, "_handle_single_text", lambda _driver, _current, answer: calls.append(answer)),
            (text_module, "_log_text_answer", lambda *_args, **_kwargs: None),
            (text_module, "record_answer", lambda *args, **kwargs: captured.append((args, kwargs))),
        )

        text_module.text(
            _FakeTextDriver(),
            10,
            0,
            texts_config=[["配置答案"]],
            texts_prob_config=[[1.0]],
            text_entry_types_config=["text"],
            text_ai_flags=[True],
            text_titles=["AI标题"],
            task_ctx=object(),
        )

        assert calls
        assert calls[0].startswith("AI答案")
        assert text_module._visible_text_length(calls[0]) >= 30
        assert captured == [((10, "text"), {"text_answer": calls[0]})]
