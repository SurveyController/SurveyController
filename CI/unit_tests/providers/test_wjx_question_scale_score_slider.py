from __future__ import annotations

from types import SimpleNamespace

from software.network.browser import NoSuchElementException
from wjx.provider.questions import scale as scale_module
from wjx.provider.questions import score as score_module
from wjx.provider.questions import slider as slider_module


class _FakeClickable:
    def __init__(self, *, text: str = "", click_exception: Exception | None = None) -> None:
        self.text = text
        self.click_exception = click_exception
        self.click_calls = 0
        self.attributes: dict[str, str] = {}
        self.selector_map: dict[str, list[object]] = {}
        self.single_selector_map: dict[str, object] = {}

    def click(self) -> None:
        self.click_calls += 1
        if self.click_exception is not None:
            raise self.click_exception

    def get_attribute(self, name: str):
        return self.attributes.get(name)

    def is_displayed(self) -> bool:
        return True

    def find_elements(self, _by, selector: str):
        return list(self.selector_map.get(selector, []))

    def find_element(self, _by, selector: str):
        if selector in self.single_selector_map:
            result = self.single_selector_map[selector]
            if isinstance(result, Exception):
                raise result
            return result
        raise NoSuchElementException(selector)


class _FakeQuestionDiv:
    def __init__(self, *, selector_map: dict[str, list[object]] | None = None) -> None:
        self.selector_map = dict(selector_map or {})

    def find_elements(self, _by, selector: str):
        result = self.selector_map.get(selector, [])
        if isinstance(result, Exception):
            raise result
        return list(result)

    def find_element(self, _by, selector: str):
        values = self.selector_map.get(selector, [])
        if values:
            return values[0]
        raise NoSuchElementException(selector)


class _FakeScaleScoreDriver:
    def __init__(self, question_div=None, *, xpath_elements: list[object] | None = None) -> None:
        self.question_div = question_div
        self.xpath_elements = list(xpath_elements or [])
        self.executed_scripts: list[tuple[str, tuple[object, ...]]] = []

    def find_element(self, _by, selector: str):
        if selector.startswith("#div"):
            if self.question_div is None:
                raise NoSuchElementException(selector)
            return self.question_div
        raise NoSuchElementException(selector)

    def find_elements(self, _by, _selector: str):
        return list(self.xpath_elements)

    def execute_script(self, script: str, *args) -> None:
        self.executed_scripts.append((script, args))


class _FakeSliderInput:
    def __init__(
        self,
        attributes: dict[str, str] | None = None,
        *,
        parent=None,
        clear_exception: Exception | None = None,
        send_keys_exception: Exception | None = None,
    ) -> None:
        self.attributes = dict(attributes or {})
        self.parent = parent
        self.clear_exception = clear_exception
        self.send_keys_exception = send_keys_exception
        self.cleared = 0
        self.sent_values: list[str] = []

    def get_attribute(self, name: str):
        return self.attributes.get(name)

    def find_element(self, _by, selector: str):
        if selector == "./.." and self.parent is not None:
            return self.parent
        raise NoSuchElementException(selector)

    def clear(self) -> None:
        self.cleared += 1
        if self.clear_exception is not None:
            raise self.clear_exception

    def send_keys(self, value: str) -> None:
        self.sent_values.append(value)
        if self.send_keys_exception is not None:
            raise self.send_keys_exception


class _FakeTrack:
    def __init__(self, *, width: int, height: int, handle=None) -> None:
        self.size = {"width": width, "height": height}
        self._handle = handle


class _FakeMouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[float, float]] = []

    def click(self, x: float, y: float) -> None:
        self.clicks.append((x, y))


class _FakePage:
    def __init__(self) -> None:
        self.mouse = _FakeMouse()


class _FakeTrackHandle:
    def __init__(self, box: dict[str, float] | None) -> None:
        self._box = box

    def bounding_box(self):
        return self._box


class _FakeSliderContainer:
    def __init__(self, tracks: list[_FakeTrack] | None = None) -> None:
        self.tracks = list(tracks or [])

    def find_elements(self, _by, _selector: str):
        return list(self.tracks)


class _FakeSliderDriver:
    def __init__(self, *, question_div=None, slider_input=None, page=None) -> None:
        self.question_div = question_div
        self.slider_input = slider_input
        self.page = page
        self.executed_scripts: list[tuple[str, tuple[object, ...]]] = []

    def find_element(self, _by, selector: str):
        if selector.startswith("#div"):
            if self.question_div is None:
                raise NoSuchElementException(selector)
            return self.question_div
        if selector.startswith("#q"):
            if self.slider_input is None:
                raise NoSuchElementException(selector)
            return self.slider_input
        raise NoSuchElementException(selector)

    def execute_script(self, script: str, *args) -> None:
        self.executed_scripts.append((script, args))


class WjxScaleQuestionTests:
    def test_collect_scale_options_returns_first_non_empty_selector(self) -> None:
        first = _FakeClickable(text="A")
        question_div = _FakeQuestionDiv(
            selector_map={
                ".scale-rating ul li": [],
                "ul[tp='d'] li": [first],
                "ul[class*='modlen'] li": [_FakeClickable(text="B")],
            }
        )

        result = scale_module._collect_scale_options(question_div)

        assert result == [first]

    def test_scale_uses_xpath_fallback_and_click_script_when_dom_click_fails(self, monkeypatch) -> None:
        option = _FakeClickable(click_exception=RuntimeError("click failed"))
        driver = _FakeScaleScoreDriver(_FakeQuestionDiv(selector_map={}), xpath_elements=[option])
        pending_calls: list[tuple[object, ...]] = []
        answer_calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(scale_module, "normalize_droplist_probs", lambda probabilities, count: [0.1, 0.9][:count])
        monkeypatch.setattr(scale_module, "apply_single_like_consistency", lambda probs, _current: probs)
        monkeypatch.setattr(scale_module, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: probs)
        monkeypatch.setattr(scale_module, "get_tendency_index", lambda *_args, **_kwargs: 1)
        monkeypatch.setattr(scale_module, "resolve_current_reverse_fill_answer", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            scale_module,
            "record_pending_distribution_choice",
            lambda *args: pending_calls.append(args),
        )
        monkeypatch.setattr(scale_module, "record_answer", lambda *args, **kwargs: answer_calls.append((args, kwargs)))

        scale_module.scale(driver, 3, 0, scale_prob_config=[[1, 9]], task_ctx=object())

        assert option.click_calls == 1
        assert len(driver.executed_scripts) == 2
        assert driver.executed_scripts[0][0] == "arguments[0].click();"
        assert pending_calls == [(object(), 3, 0, 1)] or len(pending_calls) == 1
        assert answer_calls == [((3, "scale"), {"selected_indices": [0]})] or answer_calls == [((3, "scale"), {"selected_indices": [1]})]

    def test_scale_clicks_anchor_and_syncs_hidden_value(self, monkeypatch) -> None:
        anchor = _FakeClickable()
        anchor.attributes["val"] = "5"
        option = _FakeClickable()
        option.selector_map["a[val], a.rate-off, a.rate-on, a[class*='rate-']"] = [anchor]
        option.selector_map["a[val], [val]"] = [anchor]
        driver = _FakeScaleScoreDriver(
            _FakeQuestionDiv(selector_map={".scale-rating ul li": [option]})
        )
        monkeypatch.setattr(scale_module, "normalize_droplist_probs", lambda probabilities, count: [1.0][:count])
        monkeypatch.setattr(scale_module, "apply_single_like_consistency", lambda probs, _current: probs)
        monkeypatch.setattr(scale_module, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: probs)
        monkeypatch.setattr(scale_module, "get_tendency_index", lambda *_args, **_kwargs: 0)
        monkeypatch.setattr(scale_module, "resolve_current_reverse_fill_answer", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(scale_module, "record_pending_distribution_choice", lambda *args: None)
        monkeypatch.setattr(scale_module, "record_answer", lambda *args, **kwargs: None)

        scale_module.scale(driver, 6, 0, scale_prob_config=[[1]], task_ctx=object())

        assert anchor.click_calls == 1
        assert option.click_calls == 0
        assert driver.executed_scripts[-1][1] == (6, "5")

    def test_scale_forced_reverse_fill_skips_distribution_record_and_clamps_index(self, monkeypatch) -> None:
        option_a = _FakeClickable(text="A")
        option_b = _FakeClickable(text="B")
        driver = _FakeScaleScoreDriver(
            _FakeQuestionDiv(selector_map={".scale-rating ul li": [option_a, option_b]})
        )
        pending_calls: list[tuple[object, ...]] = []
        answer_calls: list[tuple[object, ...]] = []
        reverse_fill_answer = SimpleNamespace(
            kind=scale_module.REVERSE_FILL_KIND_CHOICE,
            choice_index="9",
        )
        monkeypatch.setattr(scale_module, "resolve_current_reverse_fill_answer", lambda *_args, **_kwargs: reverse_fill_answer)
        monkeypatch.setattr(
            scale_module,
            "record_pending_distribution_choice",
            lambda *args: pending_calls.append(args),
        )
        monkeypatch.setattr(scale_module, "record_answer", lambda *args, **kwargs: answer_calls.append((args, kwargs)))

        scale_module.scale(driver, 6, 0, scale_prob_config=[], task_ctx=object())

        assert option_a.click_calls == 0
        assert option_b.click_calls == 1
        assert pending_calls == []
        assert answer_calls == [((6, "scale"), {"selected_indices": [1]})]

    def test_scale_returns_when_tendency_index_is_negative(self, monkeypatch) -> None:
        option = _FakeClickable()
        driver = _FakeScaleScoreDriver(
            _FakeQuestionDiv(selector_map={".scale-rating ul li": [option]})
        )
        answer_calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(scale_module, "normalize_droplist_probs", lambda probabilities, count: [1.0][:count])
        monkeypatch.setattr(scale_module, "apply_single_like_consistency", lambda probs, _current: probs)
        monkeypatch.setattr(scale_module, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: probs)
        monkeypatch.setattr(scale_module, "get_tendency_index", lambda *_args, **_kwargs: -1)
        monkeypatch.setattr(scale_module, "resolve_current_reverse_fill_answer", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(scale_module, "record_answer", lambda *args, **kwargs: answer_calls.append((args, kwargs)))

        scale_module.scale(driver, 8, 0, scale_prob_config=[[1]])

        assert option.click_calls == 0
        assert answer_calls == []


class WjxScoreQuestionTests:
    def test_is_valid_score_option_rejects_tag_wrap_and_writer_class(self, monkeypatch) -> None:
        invalid_class = _FakeClickable()
        invalid_class.attributes["class"] = "writerValuate"
        wrapped = _FakeClickable()
        wrapped.single_selector_map["ancestor::*[contains(@class,'evaluateTagWrap')]"] = object()
        valid = _FakeClickable()
        monkeypatch.setattr(score_module, "log_suppressed_exception", lambda *_args, **_kwargs: None)

        assert not score_module._is_valid_score_option(invalid_class)
        assert not score_module._is_valid_score_option(wrapped)
        assert score_module._is_valid_score_option(valid)

    def test_collect_score_options_filters_invalid_anchors_and_falls_back_to_li(self, monkeypatch) -> None:
        valid = _FakeClickable(text="valid")
        invalid = _FakeClickable(text="invalid")
        question_div = _FakeQuestionDiv(
            selector_map={
                ".scale-rating ul li a": [invalid, valid],
            }
        )
        monkeypatch.setattr(score_module, "_is_valid_score_option", lambda elem: elem is valid)

        result = score_module._collect_score_options(question_div)

        assert result == [valid]

    def test_score_forced_reverse_fill_clicks_last_option_and_records_answer(self, monkeypatch) -> None:
        option_a = _FakeClickable(text="A")
        option_b = _FakeClickable(text="B")
        question_div = _FakeQuestionDiv(selector_map={".scale-rating ul li a": [option_a, option_b]})
        driver = _FakeScaleScoreDriver(question_div)
        answer_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        pending_calls: list[tuple[object, ...]] = []
        reverse_fill_answer = SimpleNamespace(
            kind=score_module.REVERSE_FILL_KIND_CHOICE,
            choice_index="5",
        )
        monkeypatch.setattr(score_module, "resolve_current_reverse_fill_answer", lambda *_args, **_kwargs: reverse_fill_answer)
        monkeypatch.setattr(score_module, "record_answer", lambda *args, **kwargs: answer_calls.append((args, kwargs)))
        monkeypatch.setattr(score_module, "record_pending_distribution_choice", lambda *args: pending_calls.append(args))

        score_module.score(driver, 4, 0, score_prob_config=[], task_ctx=object())

        assert option_a.click_calls == 0
        assert option_b.click_calls == 1
        assert pending_calls == []
        assert answer_calls == [((4, "score"), {"selected_indices": [1]})]

    def test_score_uses_distribution_flow_and_script_fallback(self, monkeypatch) -> None:
        option = _FakeClickable(click_exception=RuntimeError("click failed"))
        question_div = _FakeQuestionDiv(selector_map={".scale-rating ul li a": [option]})
        driver = _FakeScaleScoreDriver(question_div)
        pending_calls: list[tuple[object, ...]] = []
        answer_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        monkeypatch.setattr(score_module, "resolve_current_reverse_fill_answer", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(score_module, "normalize_droplist_probs", lambda probabilities, count: [1.0][:count])
        monkeypatch.setattr(score_module, "apply_single_like_consistency", lambda probs, _current: probs)
        monkeypatch.setattr(score_module, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: probs)
        monkeypatch.setattr(score_module, "get_tendency_index", lambda *_args, **_kwargs: 0)
        monkeypatch.setattr(score_module, "record_pending_distribution_choice", lambda *args: pending_calls.append(args))
        monkeypatch.setattr(score_module, "record_answer", lambda *args, **kwargs: answer_calls.append((args, kwargs)))

        score_module.score(driver, 5, 0, score_prob_config=[[1]], task_ctx=object())

        assert option.click_calls == 1
        assert len(driver.executed_scripts) == 1
        assert len(pending_calls) == 1
        assert answer_calls == [((5, "score"), {"selected_indices": [0]})]


class SliderQuestionTests:
    def test_read_slider_bounds_normalizes_invalid_step_and_range(self) -> None:
        slider_input = _FakeSliderInput({"min": "10", "max": "5", "step": "0"})

        assert slider_module._read_slider_bounds(slider_input) == (10.0, 110.0, 1.0)

    def test_normalize_slider_target_clamps_random_value_to_step(self, monkeypatch) -> None:
        monkeypatch.setattr(slider_module.random, "uniform", lambda start, end: (start + end) / 2)

        assert slider_module._normalize_slider_target(None, 0.0, 10.0, 2.0) == 4
        assert slider_module._normalize_slider_target(100.0, 0.0, 10.0, 2.0) == 4

    def test_slider_ratio_clamps_to_zero_and_one(self) -> None:
        assert slider_module._slider_ratio(-5, 0.0, 10.0) == 0.0
        assert slider_module._slider_ratio(15, 0.0, 10.0) == 1.0

    def test_click_slider_track_uses_page_mouse_coordinates(self) -> None:
        page = _FakePage()
        track = _FakeTrack(width=100, height=20, handle=_FakeTrackHandle({"x": 50, "y": 80}))
        container = _FakeSliderContainer([track])
        driver = _FakeSliderDriver(page=page)

        result = slider_module._click_slider_track(driver, container, 0.25)

        assert result is True
        assert page.mouse.clicks == [(75, 90)]

    def test_set_slider_value_clicks_track_paints_and_sets_input_value(self, monkeypatch) -> None:
        container = _FakeSliderContainer()
        slider_input = _FakeSliderInput({"min": "0", "max": "10", "step": "1"}, parent=container)
        driver = _FakeSliderDriver()
        calls: list[tuple[str, object]] = []
        monkeypatch.setattr(slider_module, "_click_slider_track", lambda *_args, **_kwargs: calls.append(("click", _args[2])) or True)
        monkeypatch.setattr(slider_module, "_paint_slider_track", lambda *_args, **_kwargs: calls.append(("paint", _args[2])))
        monkeypatch.setattr(slider_module, "_set_slider_input_value", lambda *_args, **_kwargs: calls.append(("set", _args[2])))

        result = slider_module.set_slider_value(driver, slider_input, 7)

        assert result == 7
        assert calls == [("click", 0.7), ("paint", 0.7), ("set", 7)]

    def test_slider_scrolls_question_and_sets_value(self, monkeypatch) -> None:
        question_div = object()
        slider_input = _FakeSliderInput({"min": "0", "max": "100", "step": "5"})
        driver = _FakeSliderDriver(question_div=question_div, slider_input=slider_input)
        scroll_calls: list[tuple[object, ...]] = []
        value_calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(slider_module, "smooth_scroll_to_element", lambda *args: scroll_calls.append(args))
        monkeypatch.setattr(slider_module, "set_slider_value", lambda *args, **kwargs: value_calls.append(args))

        slider_module.slider(driver, 11, 42)

        assert scroll_calls == [(driver, question_div, "center")]
        assert value_calls == [(driver, slider_input, 42)]

    def test_slider_returns_quietly_when_input_is_missing(self, monkeypatch) -> None:
        driver = _FakeSliderDriver(question_div=object(), slider_input=None)
        value_calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(slider_module, "smooth_scroll_to_element", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(slider_module, "set_slider_value", lambda *args, **kwargs: value_calls.append(args))

        slider_module.slider(driver, 12, 10)

        assert value_calls == []
