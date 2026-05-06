from __future__ import annotations

from wjx.provider.questions import multiple as multiple_module


class _FakeMultipleElement:
    def __init__(self, *, text: str = "") -> None:
        self.text = text


class _FakeMultipleDriver:
    pass


class WjxQuestionMultipleTests:
    def test_multiple_skips_when_no_option_found(self, patch_attrs) -> None:
        warnings: list[tuple[tuple[object, ...], dict[str, object]]] = []
        patch_attrs(
            (
                multiple_module,
                "_collect_multiple_option_elements",
                lambda _driver, _current: ([], "container-missing"),
            ),
            (
                multiple_module,
                "_warn_option_locator_once",
                lambda *args, **kwargs: warnings.append((args, kwargs)),
            ),
        )

        multiple_module.multiple(_FakeMultipleDriver(), 5, 0, [], [])

        assert len(warnings) == 1
        assert warnings[0][0][0] == 5

    def test_multiple_random_mode_records_clicked_required_and_sampled_options(self, patch_attrs) -> None:
        options = [_FakeMultipleElement(text="A"), _FakeMultipleElement(text="B"), _FakeMultipleElement(text="C")]
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        fill_calls: list[tuple[int, int, str | None]] = []
        patch_attrs(
            (
                multiple_module,
                "_collect_multiple_option_elements",
                lambda _driver, _current: (options, "css:#div .ui-controlgroup > div"),
            ),
            (multiple_module, "detect_multiple_choice_limit_range", lambda _driver, _current: (1, 3)),
            (multiple_module, "_log_multi_limit_once", lambda *_args, **_kwargs: None),
            (multiple_module, "extract_text_from_element", lambda elem: elem.text),
            (multiple_module, "get_multiple_rule_constraint", lambda *_args, **_kwargs: ({0}, set(), "R1")),
            (multiple_module, "_resolve_rule_sets", lambda must, blocked, *_args, **_kwargs: (sorted(must), blocked)),
            (multiple_module.random, "randint", lambda _min, _max: 1),
            (multiple_module.random, "sample", lambda population, count: list(population)[:count]),
            (multiple_module, "_apply_rule_constraints", lambda selected, *_args, **_kwargs: selected),
            (multiple_module, "_click_multiple_option", lambda *_args, **_kwargs: True),
            (
                multiple_module,
                "resolve_option_fill_text_from_config",
                lambda _entries, idx, **_kwargs: f"填充{idx}",
            ),
            (
                multiple_module,
                "fill_option_additional_text",
                lambda _driver, current, idx, value: fill_calls.append((current, idx, value)),
            ),
            (multiple_module, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs))),
        )

        multiple_module.multiple(
            _FakeMultipleDriver(),
            7,
            0,
            multiple_prob_config=[-1],
            multiple_option_fill_texts_config=[["甲", "乙", "丙"]],
        )

        assert fill_calls == [(7, 0, "填充0"), (7, 1, "填充1")]
        assert recorded == [((7, "multiple"), {"selected_indices": [0, 1], "selected_texts": ["A", "B"]})]

    def test_multiple_strict_ratio_uses_weighted_sampling_and_records_answer(self, patch_attrs) -> None:
        options = [_FakeMultipleElement(text="甲"), _FakeMultipleElement(text="乙"), _FakeMultipleElement(text="丙")]
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        patch_attrs(
            (
                multiple_module,
                "_collect_multiple_option_elements",
                lambda _driver, _current: (options, "css:#div .ui-controlgroup > div"),
            ),
            (multiple_module, "detect_multiple_choice_limit_range", lambda _driver, _current: (1, 3)),
            (multiple_module, "_log_multi_limit_once", lambda *_args, **_kwargs: None),
            (multiple_module, "extract_text_from_element", lambda elem: elem.text),
            (multiple_module, "get_multiple_rule_constraint", lambda *_args, **_kwargs: (set(), set(), None)),
            (multiple_module, "_resolve_rule_sets", lambda *_args, **_kwargs: ([], set())),
            (multiple_module, "is_strict_ratio_question", lambda *_args, **_kwargs: True),
            (multiple_module, "stochastic_round", lambda _value: 1),
            (
                multiple_module,
                "weighted_sample_without_replacement",
                lambda candidates, _weights, count: list(candidates)[:count],
            ),
            (multiple_module, "_normalize_selected_indices", lambda values, _count: list(dict.fromkeys(values))),
            (multiple_module, "_click_multiple_option", lambda *_args, **_kwargs: True),
            (multiple_module, "resolve_option_fill_text_from_config", lambda *_args, **_kwargs: None),
            (multiple_module, "fill_option_additional_text", lambda *_args, **_kwargs: None),
            (multiple_module, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs))),
        )

        multiple_module.multiple(
            _FakeMultipleDriver(),
            8,
            0,
            multiple_prob_config=[[10, 80, 0]],
            multiple_option_fill_texts_config=[],
            task_ctx=object(),
        )

        assert recorded == [((8, "multiple"), {"selected_indices": [0], "selected_texts": ["甲"]})]

    def test_multiple_pads_short_probability_config_and_falls_back_to_positive_choice(self, patch_attrs) -> None:
        options = [_FakeMultipleElement(text="A"), _FakeMultipleElement(text="B"), _FakeMultipleElement(text="C")]
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        patch_attrs(
            (
                multiple_module,
                "_collect_multiple_option_elements",
                lambda _driver, _current: (options, "css:#div .ui-controlgroup > div"),
            ),
            (multiple_module, "detect_multiple_choice_limit_range", lambda _driver, _current: (1, 3)),
            (multiple_module, "_log_multi_limit_once", lambda *_args, **_kwargs: None),
            (multiple_module, "extract_text_from_element", lambda elem: elem.text),
            (multiple_module, "get_multiple_rule_constraint", lambda *_args, **_kwargs: (set(), set(), None)),
            (multiple_module, "_resolve_rule_sets", lambda *_args, **_kwargs: ([], set())),
            (multiple_module, "is_strict_ratio_question", lambda *_args, **_kwargs: False),
            (multiple_module, "apply_persona_boost", lambda _texts, probs: probs),
            (multiple_module.random, "random", lambda: 0.99),
            (multiple_module.random, "choice", lambda values: values[0]),
            (multiple_module, "_apply_rule_constraints", lambda selected, *_args, **_kwargs: selected),
            (multiple_module, "_normalize_selected_indices", lambda values, _count: list(dict.fromkeys(values))),
            (multiple_module, "_click_multiple_option", lambda *_args, **_kwargs: True),
            (multiple_module, "resolve_option_fill_text_from_config", lambda *_args, **_kwargs: None),
            (multiple_module, "fill_option_additional_text", lambda *_args, **_kwargs: None),
            (multiple_module, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs))),
        )

        multiple_module.multiple(
            _FakeMultipleDriver(),
            9,
            0,
            multiple_prob_config=[[100]],
            multiple_option_fill_texts_config=[],
        )

        assert recorded == [((9, "multiple"), {"selected_indices": [0], "selected_texts": ["A"]})]
