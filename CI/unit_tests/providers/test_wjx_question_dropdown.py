from __future__ import annotations

from types import SimpleNamespace

from wjx.provider.questions import dropdown as dropdown_module


class _FakeOptionElement:
    def __init__(
        self,
        *,
        text: str = "",
        attrs: dict[str, str] | None = None,
        displayed: bool = True,
    ) -> None:
        self.text = text
        self.attrs = dict(attrs or {})
        self.displayed = displayed
        self.clicks = 0

    def get_attribute(self, name: str):
        return self.attrs.get(name)

    def is_displayed(self) -> bool:
        return self.displayed

    def click(self) -> None:
        self.clicks += 1


class _FakeSelectElement:
    def __init__(self, options: list[_FakeOptionElement] | None = None) -> None:
        self.options = list(options or [])

    def find_elements(self, _by, selector: str):
        if selector == "option":
            return list(self.options)
        return []


class _FakeDropdownDriver:
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


class WjxQuestionDropdownTests:
    def test_extract_select_options_skips_placeholder_and_empty_option(self) -> None:
        select = _FakeSelectElement(
            [
                _FakeOptionElement(text="请选择", attrs={"value": ""}),
                _FakeOptionElement(text="", attrs={"value": ""}),
                _FakeOptionElement(text="上海", attrs={"value": "shanghai"}),
                _FakeOptionElement(text="", attrs={"value": "beijing"}),
            ]
        )
        driver = _FakeDropdownDriver(
            find_element_map={(dropdown_module.By.CSS_SELECTOR, "#q5"): select}
        )

        select_element, options = dropdown_module._extract_select_options(driver, 5)

        assert select_element is select
        assert options == [("shanghai", "上海"), ("beijing", "beijing")]

    def test_select_dropdown_option_via_js_returns_bool(self) -> None:
        driver = _FakeDropdownDriver(execute_script_result=True)

        assert dropdown_module._select_dropdown_option_via_js(driver, object(), "v1", "选项1")

    def test_fill_droplist_via_click_uses_forced_index_and_skips_fill(self, patch_attrs) -> None:
        opener = _FakeOptionElement()
        placeholder = _FakeOptionElement(text="请选择")
        option_a = _FakeOptionElement(text="A", attrs={"value": "a"})
        option_b = _FakeOptionElement(text="B", attrs={"value": "b"})
        driver = _FakeDropdownDriver(
            find_element_map={(dropdown_module.By.CSS_SELECTOR, "#select2-q9-container"): opener},
            find_elements_map={
                (dropdown_module.By.XPATH, "//*[@id='select2-q9-results']/li"): [placeholder, option_a, option_b]
            },
        )
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        fill_calls: list[tuple[int, int, str]] = []
        patch_attrs(
            (dropdown_module.time, "sleep", lambda _seconds: None),
            (dropdown_module, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs))),
            (
                dropdown_module,
                "fill_option_additional_text",
                lambda _driver, current, idx, value: fill_calls.append((current, idx, value)),
            ),
        )

        dropdown_module._fill_droplist_via_click(
            driver,
            9,
            prob_config=[0.2, 0.8],
            fill_entries=["甲", "乙"],
            forced_index=1,
        )

        assert opener.clicks == 1
        assert placeholder.clicks == 0
        assert option_a.clicks == 0
        assert option_b.clicks == 1
        assert recorded == [((9, "dropdown"), {"selected_indices": [1], "selected_texts": ["B"]})]
        assert fill_calls == []

    def test_dropdown_uses_reverse_fill_and_js_selection(self, patch_attrs) -> None:
        driver = _FakeDropdownDriver()
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        fill_calls: list[tuple[int, int, str]] = []
        patch_attrs(
            (
                dropdown_module,
                "resolve_current_reverse_fill_answer",
                lambda _ctx, _current: SimpleNamespace(
                    kind=dropdown_module.REVERSE_FILL_KIND_CHOICE,
                    choice_index=1,
                ),
            ),
            (
                dropdown_module,
                "_extract_select_options",
                lambda _driver, _current: (object(), [("a", "选项A"), ("b", "选项B")]),
            ),
            (dropdown_module, "_select_dropdown_option_via_js", lambda *_args, **_kwargs: True),
            (dropdown_module, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs))),
            (
                dropdown_module,
                "fill_option_additional_text",
                lambda _driver, current, idx, value: fill_calls.append((current, idx, value)),
            ),
        )

        dropdown_module.dropdown(
            driver,
            6,
            0,
            droplist_prob_config=[[0.5, 0.5]],
            droplist_option_fill_texts_config=[["甲", "乙"]],
            task_ctx=object(),
        )

        assert recorded == [((6, "dropdown"), {"selected_indices": [1], "selected_texts": ["选项B"]})]
        assert fill_calls == []

    def test_dropdown_falls_back_to_click_when_select_options_missing(self, patch_attrs) -> None:
        driver = _FakeDropdownDriver()
        fallback_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        patch_attrs(
            (dropdown_module, "resolve_current_reverse_fill_answer", lambda *_args, **_kwargs: None),
            (dropdown_module, "_extract_select_options", lambda _driver, _current: (None, [])),
            (
                dropdown_module,
                "_fill_droplist_via_click",
                lambda *args, **kwargs: fallback_calls.append((args, kwargs)),
            ),
        )

        dropdown_module.dropdown(
            driver,
            4,
            0,
            droplist_prob_config=[[1.0]],
            droplist_option_fill_texts_config=[["值"]],
            task_ctx=object(),
        )

        assert len(fallback_calls) == 1
        args, kwargs = fallback_calls[0]
        assert args[1:5] == (4, [1.0], ["值"],)
        assert kwargs["forced_index"] is None

    def test_dropdown_strict_ratio_records_pending_distribution(self, patch_attrs) -> None:
        driver = _FakeDropdownDriver()
        task_ctx = object()
        pending_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        patch_attrs(
            (dropdown_module, "resolve_current_reverse_fill_answer", lambda *_args, **_kwargs: None),
            (
                dropdown_module,
                "_extract_select_options",
                lambda _driver, _current: (object(), [("a", "选项A"), ("b", "选项B")]),
            ),
            (dropdown_module, "normalize_droplist_probs", lambda _cfg, _count: [0.4, 0.6]),
            (dropdown_module, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: probs),
            (dropdown_module, "enforce_reference_rank_order", lambda probs, _ref: probs),
            (dropdown_module, "weighted_index", lambda _weights: 1),
            (dropdown_module, "is_strict_ratio_question", lambda *_args, **_kwargs: True),
            (dropdown_module, "_select_dropdown_option_via_js", lambda *_args, **_kwargs: True),
            (
                dropdown_module,
                "record_pending_distribution_choice",
                lambda *args, **kwargs: pending_calls.append((args, kwargs)),
            ),
            (dropdown_module, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs))),
            (dropdown_module, "fill_option_additional_text", lambda *_args, **_kwargs: None),
            (dropdown_module, "resolve_option_fill_text_from_config", lambda *_args, **_kwargs: "填充值"),
        )

        dropdown_module.dropdown(
            driver,
            10,
            0,
            droplist_prob_config=[[40, 60]],
            droplist_option_fill_texts_config=[["甲", "乙"]],
            task_ctx=task_ctx,
        )

        assert recorded == [((10, "dropdown"), {"selected_indices": [1], "selected_texts": ["选项B"]})]
        assert pending_calls == [((task_ctx, 10, 1, 2), {})]
