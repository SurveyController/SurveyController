from __future__ import annotations

from types import SimpleNamespace

from wjx.provider.questions import matrix as matrix_module


class _FakeMatrixElement:
    def __init__(
        self,
        *,
        text: str = "",
        attrs: dict[str, str] | None = None,
        parent: "_FakeMatrixElement | None" = None,
    ) -> None:
        self.text = text
        self.attrs = dict(attrs or {})
        self.parent = parent
        self.clicks = 0

    def get_attribute(self, name: str):
        return self.attrs.get(name)

    def find_element(self, _by, selector: str):
        if selector == "./.." and self.parent is not None:
            return self.parent
        raise RuntimeError("not found")

    def click(self) -> None:
        self.clicks += 1


class _FakeMatrixDriver:
    def __init__(
        self,
        *,
        find_element_map: dict[tuple[object, str], object] | None = None,
        find_elements_map: dict[tuple[object, str], list[object]] | None = None,
    ) -> None:
        self.find_element_map = dict(find_element_map or {})
        self.find_elements_map = dict(find_elements_map or {})

    def find_element(self, by, selector: str):
        key = (by, selector)
        if key not in self.find_element_map:
            raise RuntimeError("not found")
        return self.find_element_map[key]

    def find_elements(self, by, selector: str):
        return list(self.find_elements_map.get((by, selector), []))


class WjxQuestionMatrixTests:
    def test_format_and_weight_text_helpers(self) -> None:
        assert matrix_module._format_matrix_weight_value("3.5000") == "3.5"
        assert matrix_module._format_matrix_weight_value("nan") == "随机"
        assert matrix_module._resolve_selected_weight_text(1, [10, 20], None) == "20"
        assert matrix_module._resolve_selected_weight_text(0, None, ["7"]) == "7"

    def test_extract_matrix_column_texts_uses_fallback_header(self) -> None:
        driver = _FakeMatrixDriver(
            find_elements_map={
                (matrix_module.By.CSS_SELECTOR, "#drv5_1 > td"): [],
                (
                    matrix_module.By.CSS_SELECTOR,
                    "#divRefTab5 th",
                ): [_FakeMatrixElement(text="题头"), _FakeMatrixElement(text=" 很满意 "), _FakeMatrixElement(text="一般")],
            }
        )

        assert matrix_module._extract_matrix_column_texts(driver, 5, 3) == ["很满意", "一般", ""]

    def test_build_slider_matrix_values_prefers_marks_and_deduplicates(self) -> None:
        slider_input = _FakeMatrixElement(attrs={"min": "0", "max": "10", "step": "5"})
        driver = _FakeMatrixDriver(
            find_elements_map={
                (
                    matrix_module.By.CSS_SELECTOR,
                    "#div3 .ruler .cm[data-value]",
                ): [
                    _FakeMatrixElement(attrs={"data-value": "1"}),
                    _FakeMatrixElement(attrs={"data-value": "1.0"}),
                    _FakeMatrixElement(attrs={"data-value": "2.5"}),
                ]
            }
        )

        assert matrix_module._build_slider_matrix_values(driver, 3, slider_input) == [1.0, 2.5]

    def test_build_slider_matrix_values_falls_back_to_min_max_step(self) -> None:
        slider_input = _FakeMatrixElement(attrs={"min": "2", "max": "6", "step": "2"})
        driver = _FakeMatrixDriver(find_elements_map={(matrix_module.By.CSS_SELECTOR, "#div4 .ruler .cm[data-value]"): []})

        assert matrix_module._build_slider_matrix_values(driver, 4, slider_input) == [2.0, 4.0, 6.0]

    def test_read_slider_matrix_total_requires_all_rows_marked_sum(self) -> None:
        question_div = _FakeMatrixElement(attrs={"total": "10"})
        driver = _FakeMatrixDriver(
            find_element_map={(matrix_module.By.CSS_SELECTOR, "#div6"): question_div}
        )
        sliders = [
            _FakeMatrixElement(attrs={"issum": "1"}),
            _FakeMatrixElement(attrs={"issum": "1"}),
        ]

        assert matrix_module._read_slider_matrix_total(driver, 6, sliders) == 10.0
        sliders[1] = _FakeMatrixElement(attrs={"issum": "0"})
        assert matrix_module._read_slider_matrix_total(driver, 6, sliders) is None

    def test_normalize_row_probabilities_uses_uniform_when_raw_invalid(self, patch_attrs) -> None:
        patch_attrs(
            (matrix_module, "apply_matrix_row_consistency", lambda probs, *_args, **_kwargs: probs),
            (matrix_module, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: probs),
        )

        row_probabilities, strict_reference = matrix_module._normalize_row_probabilities(
            "bad",
            3,
            5,
            0,
            object(),
            5,
            None,
        )

        assert row_probabilities == [1.0, 1.0, 1.0]
        assert strict_reference is None

    def test_score_sum_constrained_paths_returns_best_exact_or_nearest_path(self) -> None:
        exact = matrix_module._score_sum_constrained_paths([[0.1, 0.9], [0.8, 0.2]], [1, 2], 3)
        nearest = matrix_module._score_sum_constrained_paths([[0.1, 0.9], [0.8, 0.2]], [2, 4], 5)

        assert exact == [1, 0]
        assert nearest == [1, 0]

    def test_fill_slider_matrix_uses_forced_row_indexes_and_total_constraint(self, patch_attrs) -> None:
        parent = _FakeMatrixElement()
        slider1 = _FakeMatrixElement(parent=parent)
        slider2 = _FakeMatrixElement(parent=parent)
        task_ctx = object()
        set_calls: list[tuple[object, ...]] = []
        pending_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        patch_attrs(
            (matrix_module, "_collect_slider_matrix_inputs", lambda _driver, _current: [slider1, slider2]),
            (matrix_module, "_build_slider_matrix_values", lambda *_args, **_kwargs: [10.0, 20.0, 30.0]),
            (matrix_module, "is_strict_ratio_question", lambda *_args, **_kwargs: False),
            (
                matrix_module,
                "resolve_current_reverse_fill_answer",
                lambda *_args, **_kwargs: SimpleNamespace(
                    kind=matrix_module.REVERSE_FILL_KIND_MATRIX,
                    matrix_choice_indexes=[2],
                ),
            ),
            (matrix_module, "_read_slider_matrix_total", lambda *_args, **_kwargs: 40.0),
            (
                matrix_module,
                "_normalize_row_probabilities",
                lambda *_args, **_kwargs: ([0.1, 0.2, 0.7], [0.1, 0.2, 0.7]),
            ),
            (matrix_module, "_score_sum_constrained_paths", lambda *_args, **_kwargs: [1, 2]),
            (matrix_module, "set_slider_value", lambda *args, **kwargs: set_calls.append(args)),
            (
                matrix_module,
                "record_pending_distribution_choice",
                lambda *args, **kwargs: pending_calls.append((args, kwargs)),
            ),
            (matrix_module, "_log_matrix_row_choice", lambda *_args, **_kwargs: None),
            (matrix_module, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs))),
        )

        next_index = matrix_module._fill_slider_matrix(
            _FakeMatrixDriver(),
            11,
            3,
            matrix_prob_config=[[1, 2, 3], [3, 2, 1]],
            task_ctx=task_ctx,
        )

        assert next_index == 5
        assert [call[2] for call in set_calls] == [30.0, 30.0]
        assert pending_calls == [((task_ctx, 11, 2, 3), {"row_index": 1})]
        assert recorded == [
            ((11, "matrix"), {"selected_indices": [2], "row_index": 0}),
            ((11, "matrix"), {"selected_indices": [2], "row_index": 1}),
        ]

    def test_matrix_main_flow_clicks_rows_and_records_choice(self, patch_attrs) -> None:
        row1 = _FakeMatrixElement(attrs={"rowindex": "1"})
        row2 = _FakeMatrixElement(attrs={"rowindex": "2"})
        header = [_FakeMatrixElement(text="题头"), _FakeMatrixElement(text="A"), _FakeMatrixElement(text="B")]
        cell1 = _FakeMatrixElement()
        cell2 = _FakeMatrixElement()
        task_ctx = object()
        driver = _FakeMatrixDriver(
            find_elements_map={
                (matrix_module.By.XPATH, '//*[@id="divRefTab12"]/tbody/tr'): [row1, row2],
                (matrix_module.By.XPATH, '//*[@id="drv12_1"]/td'): header,
            },
            find_element_map={
                (matrix_module.By.CSS_SELECTOR, "#drv12_1 > td:nth-child(2)"): cell1,
                (matrix_module.By.CSS_SELECTOR, "#drv12_2 > td:nth-child(3)"): cell2,
            },
        )
        pending_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        patch_attrs(
            (matrix_module, "_collect_slider_matrix_inputs", lambda *_args, **_kwargs: []),
            (matrix_module, "_extract_matrix_column_texts", lambda *_args, **_kwargs: ["A", "B"]),
            (matrix_module, "is_strict_ratio_question", lambda *_args, **_kwargs: False),
            (matrix_module, "resolve_current_reverse_fill_answer", lambda *_args, **_kwargs: None),
            (matrix_module, "apply_matrix_row_consistency", lambda probs, *_args, **_kwargs: probs),
            (matrix_module, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: probs),
            (matrix_module, "get_tendency_index", lambda _count, probs, **kwargs: 0 if kwargs["row_index"] == 0 else 1),
            (
                matrix_module,
                "record_pending_distribution_choice",
                lambda *args, **kwargs: pending_calls.append((args, kwargs)),
            ),
            (matrix_module, "_log_matrix_row_choice", lambda *_args, **_kwargs: None),
            (matrix_module, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs))),
        )

        next_index = matrix_module.matrix(
            driver,
            12,
            0,
            matrix_prob_config=[[0.6, 0.4], [0.2, 0.8]],
            task_ctx=task_ctx,
        )

        assert next_index == 2
        assert cell1.clicks == 1
        assert cell2.clicks == 1
        assert pending_calls == [
            ((task_ctx, 12, 0, 2), {"row_index": 0}),
            ((task_ctx, 12, 1, 2), {"row_index": 1}),
        ]
        assert recorded == [
            ((12, "matrix"), {"selected_indices": [0], "row_index": 0}),
            ((12, "matrix"), {"selected_indices": [1], "row_index": 1}),
        ]

    def test_matrix_main_flow_uses_forced_reverse_fill_indexes(self, patch_attrs) -> None:
        row1 = _FakeMatrixElement(attrs={"rowindex": "1"})
        row2 = _FakeMatrixElement(attrs={"rowindex": "2"})
        header = [
            _FakeMatrixElement(text="题头"),
            _FakeMatrixElement(text="A"),
            _FakeMatrixElement(text="B"),
            _FakeMatrixElement(text="C"),
        ]
        cell1 = _FakeMatrixElement()
        cell2 = _FakeMatrixElement()
        driver = _FakeMatrixDriver(
            find_elements_map={
                (matrix_module.By.XPATH, '//*[@id="divRefTab15"]/tbody/tr'): [row1, row2],
                (matrix_module.By.XPATH, '//*[@id="drv15_1"]/td'): header,
            },
            find_element_map={
                (matrix_module.By.CSS_SELECTOR, "#drv15_1 > td:nth-child(4)"): cell1,
                (matrix_module.By.CSS_SELECTOR, "#drv15_2 > td:nth-child(3)"): cell2,
            },
        )
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        patch_attrs(
            (matrix_module, "_collect_slider_matrix_inputs", lambda *_args, **_kwargs: []),
            (matrix_module, "_extract_matrix_column_texts", lambda *_args, **_kwargs: ["A", "B", "C"]),
            (matrix_module, "is_strict_ratio_question", lambda *_args, **_kwargs: False),
            (
                matrix_module,
                "resolve_current_reverse_fill_answer",
                lambda *_args, **_kwargs: SimpleNamespace(
                    kind=matrix_module.REVERSE_FILL_KIND_MATRIX,
                    matrix_choice_indexes=[2, 1],
                ),
            ),
            (matrix_module, "apply_matrix_row_consistency", lambda probs, *_args, **_kwargs: probs),
            (matrix_module, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: probs),
            (matrix_module, "get_tendency_index", lambda *_args, **_kwargs: 0),
            (matrix_module, "record_pending_distribution_choice", lambda *_args, **_kwargs: None),
            (matrix_module, "_log_matrix_row_choice", lambda *_args, **_kwargs: None),
            (matrix_module, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs))),
        )

        next_index = matrix_module.matrix(
            driver,
            15,
            0,
            matrix_prob_config=[[0.1, 0.2, 0.7], [0.3, 0.5, 0.2]],
            task_ctx=object(),
        )

        assert next_index == 2
        assert cell1.clicks == 1
        assert cell2.clicks == 1
        assert recorded == [
            ((15, "matrix"), {"selected_indices": [2], "row_index": 0}),
            ((15, "matrix"), {"selected_indices": [1], "row_index": 1}),
        ]
