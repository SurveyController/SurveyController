from __future__ import annotations
import threading
from contextlib import ExitStack
from types import SimpleNamespace
from wjx.provider import runtime
from wjx.provider import runtime_dispatch
from software.core.engine.dom_helpers import _driver_question_looks_like_reorder
from software.providers.contracts import SurveyQuestionMeta

class _FakeQuestionDiv:

    def __init__(self, question_type: str, *, displayed: bool=True, text: str='') -> None:
        self._question_type = question_type
        self._displayed = displayed
        self.text = text or f'type={question_type}'

    def is_displayed(self) -> bool:
        return self._displayed

    def get_attribute(self, name: str):
        if name == 'type':
            return self._question_type
        return None

    def find_elements(self, _by=None, _selector=None):
        return []

class _FakeQuestionDivWithSelectors(_FakeQuestionDiv):

    def __init__(self, question_type: str, selector_map=None, **kwargs) -> None:
        super().__init__(question_type, **kwargs)
        self.selector_map = dict(selector_map or {})

    def find_elements(self, _by=None, selector=None):
        return list(self.selector_map.get(selector, []))

class _FakeDriver:

    def __init__(self, question_map):
        self.question_map = dict(question_map)

    def find_element(self, _by, selector: str):
        return self.question_map.get(selector)

class _FakeState(SimpleNamespace):

    def __init__(self, **kwargs) -> None:
        config_defaults = dict(question_dimension_map={}, question_config_index_map={}, questions_metadata={}, single_prob=[], single_option_fill_texts=[], single_attached_option_selects=[], multiple_prob=[], multiple_option_fill_texts=[], scale_prob=[], matrix_prob=[], droplist_prob=[], droplist_option_fill_texts=[], slider_targets=[], texts=[], texts_prob=[], text_entry_types=[], text_ai_flags=[], text_titles=[], multi_text_blank_modes=[], multi_text_blank_ai_flags=[], multi_text_blank_int_ranges=[], answer_duration_range_seconds=[0, 0])
        base_defaults = dict(stop_event=threading.Event(), step_updates=[], status_updates=[])
        config_overrides = dict(kwargs.pop('config', {}) or {})
        for key in list(kwargs.keys()):
            if key in config_defaults:
                config_overrides[key] = kwargs.pop(key)
        config_defaults.update(config_overrides)
        base_defaults.update(kwargs)
        base_defaults['config'] = SimpleNamespace(**config_defaults)
        super().__init__(**base_defaults)

    def update_thread_step(self, _thread_name: str, current: int, total: int, *, status_text: str, running: bool) -> None:
        self.step_updates.append((current, total, status_text, running))

    def update_thread_status(self, _thread_name: str, status_text: str, *, running: bool) -> None:
        self.status_updates.append((status_text, running))

class WjxRuntimeTests:

    def _build_dispatcher_ctx(self) -> _FakeState:
        return _FakeState(question_dimension_map={3: 'D1', 5: 'D2'})

    def test_dispatcher_routes_reorder_question(self, patch_attrs) -> None:
        dispatcher = runtime_dispatch._QuestionDispatcher()
        calls: list[int] = []
        indices = {'single': 0, 'text': 0, 'dropdown': 0, 'multiple': 0, 'matrix': 0, 'scale': 0, 'slider': 0}
        patch_attrs(
            (runtime_dispatch, 'resolve_current_reverse_fill_answer', lambda *_args, **_kwargs: None),
            (runtime_dispatch, '_reorder_impl', lambda _driver, question_num: calls.append(question_num)),
        )
        dispatcher.fill(object(), '11', 7, _FakeQuestionDiv('11'), None, indices, self._build_dispatcher_ctx())
        assert calls == [7]
        assert indices['text'] == 0

    def test_reorder_heuristic_does_not_misclassify_checkbox_list(self) -> None:
        question_div = _FakeQuestionDivWithSelectors('4', selector_map={'ul li, ol li': [object(), object()], ".ui-sortable, .ui-sortable-handle, [class*='sort']": [object()], "input[type='checkbox'], input[type='radio'], .jqcheck, .jqradio, .ui-checkbox, .ui-radio": [object()]})
        assert not _driver_question_looks_like_reorder(question_div)

    def test_dispatcher_routes_text_question_and_advances_text_index(self, patch_attrs) -> None:
        dispatcher = runtime_dispatch._QuestionDispatcher()
        ctx = self._build_dispatcher_ctx()
        indices = {'single': 0, 'text': 0, 'dropdown': 0, 'multiple': 0, 'matrix': 0, 'scale': 0, 'slider': 0}
        calls: list[tuple[int, int]] = []
        patch_attrs(
            (runtime_dispatch, 'resolve_current_reverse_fill_answer', lambda *_args, **_kwargs: None),
            (runtime_dispatch, '_driver_question_is_location', lambda _div: False),
            (runtime_dispatch, '_text_impl', lambda _driver, question_num, idx, *_args, **_kwargs: calls.append((question_num, idx))),
        )
        dispatcher.fill(object(), '1', 3, _FakeQuestionDiv('1'), ('text', 2), indices, ctx)
        assert calls == [(3, 2)]
        assert indices['text'] == 3

    def test_dispatcher_routes_rating_scale_to_score_handler(self, patch_attrs) -> None:
        dispatcher = runtime_dispatch._QuestionDispatcher()
        ctx = self._build_dispatcher_ctx()
        indices = {'single': 0, 'text': 0, 'dropdown': 0, 'multiple': 0, 'matrix': 0, 'scale': 0, 'slider': 0}
        calls: list[tuple[int, int, str | None]] = []
        patch_attrs(
            (runtime_dispatch, 'resolve_current_reverse_fill_answer', lambda *_args, **_kwargs: None),
            (runtime_dispatch, '_driver_question_looks_like_reorder', lambda _div: False),
            (runtime_dispatch, '_driver_question_looks_like_rating', lambda _div: True),
            (runtime_dispatch, '_score_impl', lambda _driver, question_num, idx, *_args, **kwargs: calls.append((question_num, idx, kwargs.get('dimension')))),
            (runtime_dispatch, '_scale_impl', lambda *_args, **_kwargs: calls.append((-1, -1, 'scale'))),
        )
        dispatcher.fill(object(), '5', 5, _FakeQuestionDiv('5'), ('score', 1), indices, ctx)
        assert calls == [(5, 1, 'D2')]
        assert indices['scale'] == 2

    def test_dispatcher_routes_matrix_and_uses_returned_index(self, patch_attrs) -> None:
        dispatcher = runtime_dispatch._QuestionDispatcher()
        ctx = self._build_dispatcher_ctx()
        indices = {'single': 0, 'text': 0, 'dropdown': 0, 'multiple': 0, 'matrix': 0, 'scale': 0, 'slider': 0}
        calls: list[tuple[int, int, str | None]] = []
        patch_attrs(
            (runtime_dispatch, 'resolve_current_reverse_fill_answer', lambda *_args, **_kwargs: None),
            (runtime_dispatch, '_driver_question_looks_like_reorder', lambda _div: False),
            (runtime_dispatch, '_matrix_impl', lambda _driver, question_num, idx, *_args, **kwargs: calls.append((question_num, idx, kwargs.get('dimension'))) or 6),
        )
        dispatcher.fill(object(), '6', 3, _FakeQuestionDiv('6'), ('matrix', 2), indices, ctx)
        assert calls == [(3, 2, 'D1')]
        assert indices['matrix'] == 6

    def test_brush_walks_pages_then_submits(self, patch_attrs) -> None:
        ctx = _FakeState(question_config_index_map={1: ('single', 0), 2: ('single', 1)}, questions_metadata={1: SurveyQuestionMeta(num=1, title='Q1', type_code='3', page=1), 2: SurveyQuestionMeta(num=2, title='Q2', type_code='3', page=2)})
        driver = _FakeDriver({'#div1': _FakeQuestionDiv('3', text='Q1'), '#div2': _FakeQuestionDiv('3', text='Q2')})
        calls: list[object] = []

        def _fake_fill(*, question_num: int, **_kwargs):
            calls.append(('fill', question_num))
            return None
        patch_attrs(
            (runtime, '_refresh_visible_question_snapshot', lambda _driver, **_kwargs: {1: {'visible': True, 'type': '3', 'title': 'Q1'}, 2: {'visible': True, 'type': '3', 'title': 'Q2'}}),
            (runtime, '_is_headless_mode', lambda _ctx: True),
            (runtime, 'HEADLESS_PAGE_BUFFER_DELAY', 0.0),
            (runtime, 'HEADLESS_PAGE_CLICK_DELAY', 0.0),
            (runtime, '_driver_question_looks_like_description', lambda *_args, **_kwargs: False),
            (runtime, '_human_scroll_after_question', lambda *_args, **_kwargs: calls.append('scroll')),
            (runtime, '_click_next_page_button', lambda *_args, **_kwargs: calls.append('next') or True),
            (runtime, 'has_configured_answer_duration', lambda _value: False),
            (runtime, 'simulate_answer_duration_delay', lambda *_args, **_kwargs: False),
            (runtime._dispatcher, 'fill', _fake_fill),
            (runtime, 'submit', lambda *_args, **_kwargs: calls.append('submit')),
        )
        result = runtime.brush(driver, ctx, stop_signal=threading.Event(), thread_name='Worker-1', psycho_plan=None)
        assert result
        assert calls.count('next') == 1
        assert calls[-1] == 'submit'
        assert ('fill', 1) in calls
        assert ('fill', 2) in calls
        assert ('提交中', True) in ctx.status_updates

    def test_brush_uses_page_snapshot_visibility_fast_path(self, patch_attrs) -> None:
        ctx = _FakeState(question_config_index_map={1: ('single', 0)}, questions_metadata={1: SurveyQuestionMeta(num=1, title='Q1', type_code='3', page=1)})
        driver = _FakeDriver({'#div1': _FakeQuestionDiv('3', displayed=False, text='Q1')})
        calls: list[object] = []

        def _fake_fill(*, question_num: int, **_kwargs):
            calls.append(('fill', question_num))
            return None
        patch_attrs(
            (runtime, '_refresh_visible_question_snapshot', lambda _driver, **_kwargs: {1: {'visible': True, 'type': '3', 'title': 'Q1'}}),
            (runtime, '_is_headless_mode', lambda _ctx: True),
            (runtime, 'HEADLESS_PAGE_BUFFER_DELAY', 0.0),
            (runtime, '_driver_question_looks_like_description', lambda *_args, **_kwargs: False),
            (runtime, '_human_scroll_after_question', lambda *_args, **_kwargs: None),
            (runtime, 'has_configured_answer_duration', lambda _value: False),
            (runtime, 'simulate_answer_duration_delay', lambda *_args, **_kwargs: False),
            (runtime._dispatcher, 'fill', _fake_fill),
            (runtime, 'submit', lambda *_args, **_kwargs: calls.append('submit')),
        )
        result = runtime.brush(driver, ctx, stop_signal=threading.Event(), thread_name='Worker-1', psycho_plan=None)
        assert result
        assert ('fill', 1) in calls

    def test_brush_refreshes_snapshot_after_skip_logic_changes_visibility(self, patch_attrs) -> None:
        ctx = _FakeState(question_config_index_map={1: ('single', 0), 3: ('single', 1)}, questions_metadata={1: SurveyQuestionMeta(num=1, title='Q1', type_code='3', page=1, has_dependent_display_logic=True), 2: SurveyQuestionMeta(num=2, title='Q2', type_code='4', page=1), 3: SurveyQuestionMeta(num=3, title='Q3', type_code='3', page=1)})
        driver = _FakeDriver({'#div1': _FakeQuestionDiv('3', displayed=True, text='Q1'), '#div2': _FakeQuestionDiv('4', displayed=False, text='Q2'), '#div3': _FakeQuestionDiv('3', displayed=True, text='Q3')})
        calls: list[object] = []
        snapshots = iter([{1: {'visible': True, 'type': '3', 'title': 'Q1'}, 2: {'visible': True, 'type': '4', 'title': 'Q2'}}, {1: {'visible': True, 'type': '3', 'title': 'Q1'}, 3: {'visible': True, 'type': '3', 'title': 'Q3'}}, {1: {'visible': True, 'type': '3', 'title': 'Q1'}, 3: {'visible': True, 'type': '3', 'title': 'Q3'}}])

        def _fake_fill(*, question_num: int, **_kwargs):
            calls.append(('fill', question_num))
            return None
        patch_attrs(
            (runtime, '_refresh_visible_question_snapshot', lambda _driver, **_kwargs: next(snapshots)),
            (runtime, '_is_headless_mode', lambda _ctx: True),
            (runtime, 'HEADLESS_PAGE_BUFFER_DELAY', 0.0),
            (runtime, '_driver_question_looks_like_description', lambda *_args, **_kwargs: False),
            (runtime, '_human_scroll_after_question', lambda *_args, **_kwargs: None),
            (runtime, 'has_configured_answer_duration', lambda _value: False),
            (runtime, 'simulate_answer_duration_delay', lambda *_args, **_kwargs: False),
            (runtime._dispatcher, 'fill', _fake_fill),
            (runtime, 'submit', lambda *_args, **_kwargs: calls.append('submit')),
        )
        result = runtime.brush(driver, ctx, stop_signal=threading.Event(), thread_name='Worker-1', psycho_plan=None)
        assert result
        assert ('fill', 1) in calls
        assert ('fill', 3) in calls
        assert ('fill', 2) not in calls

    def test_brush_refreshes_snapshot_after_jump_question_changes_visible_set(self, patch_attrs) -> None:
        ctx = _FakeState(question_config_index_map={1: ('single', 0), 2: ('single', 1), 3: ('single', 2)}, questions_metadata={1: SurveyQuestionMeta(num=1, title='Q1', type_code='3', page=1, has_jump=True), 2: SurveyQuestionMeta(num=2, title='Q2', type_code='3', page=1), 3: SurveyQuestionMeta(num=3, title='Q3', type_code='3', page=1)})
        driver = _FakeDriver({'#div1': _FakeQuestionDiv('3', displayed=True, text='Q1'), '#div2': _FakeQuestionDiv('3', displayed=False, text='Q2'), '#div3': _FakeQuestionDiv('3', displayed=True, text='Q3')})
        calls: list[object] = []
        snapshots = iter([{1: {'visible': True, 'type': '3', 'title': 'Q1'}, 2: {'visible': True, 'type': '3', 'title': 'Q2'}}, {1: {'visible': True, 'type': '3', 'title': 'Q1'}, 3: {'visible': True, 'type': '3', 'title': 'Q3'}}, {1: {'visible': True, 'type': '3', 'title': 'Q1'}, 3: {'visible': True, 'type': '3', 'title': 'Q3'}}])

        def _fake_fill(*, question_num: int, **_kwargs):
            calls.append(('fill', question_num))
            return None
        patch_attrs(
            (runtime, '_refresh_visible_question_snapshot', lambda _driver, **_kwargs: next(snapshots)),
            (runtime, '_is_headless_mode', lambda _ctx: True),
            (runtime, 'HEADLESS_PAGE_BUFFER_DELAY', 0.0),
            (runtime, '_driver_question_looks_like_description', lambda *_args, **_kwargs: False),
            (runtime, '_human_scroll_after_question', lambda *_args, **_kwargs: None),
            (runtime, 'has_configured_answer_duration', lambda _value: False),
            (runtime, 'simulate_answer_duration_delay', lambda *_args, **_kwargs: False),
            (runtime._dispatcher, 'fill', _fake_fill),
            (runtime, 'submit', lambda *_args, **_kwargs: calls.append('submit')),
        )
        result = runtime.brush(driver, ctx, stop_signal=threading.Event(), thread_name='Worker-1', psycho_plan=None)
        assert result
        assert ('fill', 1) in calls
        assert ('fill', 3) in calls
        assert ('fill', 2) not in calls
