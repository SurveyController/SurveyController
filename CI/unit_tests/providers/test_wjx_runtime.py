from __future__ import annotations
import threading
from types import SimpleNamespace
from unittest.mock import Mock
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

    def __init__(self, question_map, *, script_result=None, script_exception: Exception | None=None):
        self.question_map = dict(question_map)
        self.script_result = script_result
        self.script_exception = script_exception

    def find_element(self, _by, selector: str):
        return self.question_map.get(selector)

    def execute_script(self, _script: str):
        if self.script_exception is not None:
            raise self.script_exception
        return self.script_result

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

    def test_build_initial_indices_returns_all_supported_counters(self) -> None:
        assert runtime._build_initial_indices() == {
            'single': 0,
            'text': 0,
            'dropdown': 0,
            'multiple': 0,
            'matrix': 0,
            'scale': 0,
            'slider': 0,
        }

    def test_collect_visible_question_snapshot_normalizes_payload_and_ignores_invalid_items(self) -> None:
        driver = _FakeDriver(
            {},
            script_result={
                '1': {'visible': 1, 'type': '3', 'title': '  标题一  '},
                '2': {'visible': 0, 'type': None, 'title': None},
                'x': {'visible': True},
                '-1': {'visible': True},
                '3': 'bad',
            },
        )

        assert runtime._collect_visible_question_snapshot(driver) == {
            1: {'visible': True, 'type': '3', 'title': '标题一'},
            2: {'visible': False, 'type': '', 'title': ''},
        }

    def test_collect_visible_question_snapshot_returns_empty_when_script_fails_or_payload_is_not_dict(self) -> None:
        assert runtime._collect_visible_question_snapshot(_FakeDriver({}, script_exception=RuntimeError('boom'))) == {}
        assert runtime._collect_visible_question_snapshot(_FakeDriver({}, script_result=['bad'])) == {}

    def test_snapshot_visible_numbers_and_metadata_helpers_normalize_inputs(self) -> None:
        ctx = _FakeState(
            questions_metadata={
                '2': SurveyQuestionMeta(num=2, title='Q2', type_code='3', page=2),
                'x': SurveyQuestionMeta(num=3, title='Q3', type_code='3', page=1),
                '-1': SurveyQuestionMeta(num=4, title='Q4', type_code='3', page=1),
                '5': None,
                1: SurveyQuestionMeta(num=1, title='A', type_code='3', page='bad'),
            }
        )

        assert runtime._snapshot_visible_numbers({1: {'visible': True}, 2: {'visible': False}, 3: None}) == {1}
        metadata = runtime._question_metadata_map(ctx)
        assert sorted(metadata) == [1, 2]
        page_plan = runtime._build_metadata_page_plan(ctx)
        assert [page for page, _questions in page_plan] == [1, 2]
        assert [q.num for q in page_plan[0][1]] == [1]
        assert [q.num for q in page_plan[1][1]] == [2]

    def test_question_requires_snapshot_refresh_checks_three_flags(self) -> None:
        assert not runtime._question_requires_snapshot_refresh(None)
        assert runtime._question_requires_snapshot_refresh(SimpleNamespace(has_jump=True))
        assert runtime._question_requires_snapshot_refresh(SimpleNamespace(has_dependent_display_logic=True))
        assert not runtime._question_requires_snapshot_refresh(SimpleNamespace(has_display_condition=True))

    def test_question_refresh_candidate_numbers_prefers_next_question_and_control_targets(self) -> None:
        question_meta = SimpleNamespace(
            jump_rules=[{"jumpto": 8}],
            controls_display_targets=[{"target_question_num": 5}, {"target_question_num": "9"}],
        )
        page_questions = [
            SurveyQuestionMeta(num=1, title='Q1', type_code='3', page=1),
            SurveyQuestionMeta(num=2, title='Q2', type_code='3', page=1),
            SurveyQuestionMeta(num=3, title='Q3', type_code='3', page=1),
        ]

        assert runtime._question_refresh_candidate_numbers(question_meta, page_questions, 0) == [2, 5, 8, 9]

    def test_refresh_snapshot_if_visibility_changed_only_refreshes_when_candidate_visibility_differs(self, monkeypatch) -> None:
        driver = _FakeDriver({
            '#div2': _FakeQuestionDiv('3', displayed=True),
            '#div5': _FakeQuestionDiv('3', displayed=False),
        })
        refresh_calls: list[str] = []
        monkeypatch.setattr(runtime, '_refresh_visible_question_snapshot', lambda _driver, *, reason: refresh_calls.append(reason) or {2: {'visible': True, 'type': '3', 'title': 'Q2'}, 5: {'visible': False, 'type': '3', 'title': 'Q5'}})

        snapshot, changed = runtime._refresh_snapshot_if_visibility_changed(
            driver,
            {2: {'visible': True, 'type': '3', 'title': 'Q2'}, 5: {'visible': False, 'type': '3', 'title': 'Q5'}},
            [2, 5],
            reason='test',
        )

        assert not changed
        assert snapshot[2]['visible']
        assert refresh_calls == []

        driver2 = _FakeDriver({
            '#div2': _FakeQuestionDiv('3', displayed=True),
            '#div5': _FakeQuestionDiv('3', displayed=True),
        })
        monkeypatch.setattr(runtime, '_refresh_visible_question_snapshot', lambda _driver, *, reason: refresh_calls.append(reason) or {2: {'visible': True, 'type': '3', 'title': 'Q2'}, 5: {'visible': True, 'type': '3', 'title': 'Q5'}})

        snapshot2, changed2 = runtime._refresh_snapshot_if_visibility_changed(
            driver2,
            {2: {'visible': True, 'type': '3', 'title': 'Q2'}, 5: {'visible': False, 'type': '3', 'title': 'Q5'}},
            [2, 5],
            reason='test-refresh',
        )

        assert changed2
        assert snapshot2[5]['visible']
        assert refresh_calls == ['test-refresh']

    def test_ensure_question_snapshot_visibility_refreshes_only_on_dom_mismatch(self, monkeypatch) -> None:
        driver = _FakeDriver({'#div2': _FakeQuestionDiv('3', displayed=False)})
        refresh_calls: list[str] = []
        monkeypatch.setattr(runtime, '_refresh_visible_question_snapshot', lambda _driver, *, reason: refresh_calls.append(reason) or {2: {'visible': False, 'type': '3', 'title': 'Q2'}})

        snapshot = runtime._ensure_question_snapshot_visibility(
            driver,
            {2: {'visible': False, 'type': '3', 'title': 'Q2'}},
            question_num=2,
            reason='no-refresh',
        )
        assert snapshot[2]['visible'] is False
        assert refresh_calls == []

        driver2 = _FakeDriver({'#div2': _FakeQuestionDiv('3', displayed=True)})
        refreshed = runtime._ensure_question_snapshot_visibility(
            driver2,
            {2: {'visible': False, 'type': '3', 'title': 'Q2'}},
            question_num=2,
            reason='need-refresh',
        )
        assert refreshed[2]['visible'] is False
        assert refresh_calls == ['need-refresh']

    def test_update_abort_status_swallows_status_update_failure(self) -> None:
        ctx = SimpleNamespace(update_thread_status=Mock(side_effect=RuntimeError('fail')))

        runtime._update_abort_status(ctx, 'Worker-1')

        ctx.update_thread_status.assert_called_once_with('Worker-1', '已中断', running=False)

    def test_prepare_runtime_entry_gate_waits_after_start_click_and_respects_stop_signal(self, patch_attrs) -> None:
        stop_signal = Mock()
        stop_signal.wait.return_value = True
        calls: list[tuple[str, float]] = []
        patch_attrs(
            (runtime, 'dismiss_resume_dialog_if_present', lambda *_args, timeout=0.0, **_kwargs: calls.append(('resume', timeout))),
            (runtime, 'try_click_start_answer_button', lambda *_args, timeout=0.0, **_kwargs: calls.append(('start', timeout)) or True),
        )

        result = runtime._prepare_runtime_entry_gate(object(), stop_signal)

        assert not result
        assert calls == [('resume', 0.2), ('start', 0.35)]
        stop_signal.wait.assert_called_once_with(0.15)

    def test_prepare_runtime_entry_gate_sleeps_when_no_stop_signal(self, patch_attrs) -> None:
        sleep_calls: list[float] = []
        patch_attrs(
            (runtime, 'dismiss_resume_dialog_if_present', lambda *_args, **_kwargs: None),
            (runtime, 'try_click_start_answer_button', lambda *_args, **_kwargs: True),
            (runtime.time, 'sleep', lambda seconds: sleep_calls.append(seconds)),
        )

        assert runtime._prepare_runtime_entry_gate(object(), None)
        assert sleep_calls == [0.15]

    def test_fallback_unknown_question_routes_checkbox_and_radio_questions(self, patch_attrs) -> None:
        ctx = _FakeState()
        indices = runtime._build_initial_indices()
        calls: list[tuple[str, int, int]] = []
        patch_attrs(
            (runtime, '_count_choice_inputs_driver', lambda _div: (3, 1)),
            (runtime, '_multiple_impl', lambda _driver, question_num, idx, *_args: calls.append(('multiple', question_num, idx))),
            (runtime, '_single_impl', lambda _driver, question_num, idx, *_args, **_kwargs: calls.append(('single', question_num, idx))),
        )

        runtime._fallback_unknown_question(object(), ctx, question_num=4, question_type='x', question_div=object(), indices=indices)
        patch_attrs((runtime, '_count_choice_inputs_driver', lambda _div: (1, 3)))
        runtime._fallback_unknown_question(object(), ctx, question_num=5, question_type='x', question_div=object(), indices=indices)

        assert calls == [('multiple', 4, 0), ('single', 5, 0)]
        assert indices['multiple'] == 1
        assert indices['single'] == 1

    def test_fallback_unknown_question_routes_text_like_and_respects_reverse_fill(self, monkeypatch, capsys) -> None:
        question_div = _FakeQuestionDivWithSelectors('1', selector_map={'.ui-controlgroup > div': [object(), object()]})
        ctx = _FakeState()
        indices = runtime._build_initial_indices()
        text_calls: list[tuple[int, int]] = []
        monkeypatch.setattr(runtime, '_count_choice_inputs_driver', lambda _div: (0, 0))
        monkeypatch.setattr(runtime, '_count_visible_text_inputs_driver', lambda _div: 2)
        monkeypatch.setattr(runtime, '_driver_question_looks_like_slider_matrix', lambda _div: False)
        monkeypatch.setattr(runtime, '_should_treat_question_as_text_like', lambda *_args, **_kwargs: True)
        monkeypatch.setattr(runtime, '_text_impl', lambda _driver, question_num, idx, *_args, **_kwargs: text_calls.append((question_num, idx)))
        monkeypatch.setattr(runtime, 'resolve_current_reverse_fill_answer', lambda *_args, **_kwargs: None)

        runtime._fallback_unknown_question(object(), ctx, question_num=7, question_type='1', question_div=question_div, indices=indices)
        assert text_calls == [(7, 0)]
        assert indices['text'] == 1

        monkeypatch.setattr(runtime, 'resolve_current_reverse_fill_answer', lambda *_args, **_kwargs: object())
        runtime._fallback_unknown_question(object(), ctx, question_num=8, question_type='1', question_div=question_div, indices=indices)
        assert text_calls[-1] == (8, 1)
        assert indices['text'] == 1

        monkeypatch.setattr(runtime, '_should_treat_question_as_text_like', lambda *_args, **_kwargs: False)
        runtime._fallback_unknown_question(object(), ctx, question_num=9, question_type='99', question_div=question_div, indices=indices)
        assert '第9题为不支持类型(type=99)' in capsys.readouterr().out

    def test_refresh_questions_metadata_updates_changed_questions_and_handles_failures(self, monkeypatch) -> None:
        meta_old = SurveyQuestionMeta(num=1, title='Q1', type_code='3', page=1)
        meta_new = SurveyQuestionMeta(num=1, title='Q1-new', type_code='3', page=1)
        ctx = _FakeState(config={'url': 'https://demo'}, questions_metadata={1: meta_old})
        monkeypatch.setattr(runtime, 'parse_survey_sync', lambda _url: SimpleNamespace(questions=[meta_new, SimpleNamespace(num='x')]))

        assert runtime._refresh_questions_metadata(ctx)
        assert ctx.config.questions_metadata[1] == meta_new

        monkeypatch.setattr(runtime, 'parse_survey_sync', lambda _url: SimpleNamespace(questions=[]))
        assert not runtime._refresh_questions_metadata(ctx)

        monkeypatch.setattr(runtime, 'parse_survey_sync', lambda _url: (_ for _ in ()).throw(RuntimeError('boom')))
        assert not runtime._refresh_questions_metadata(ctx)

        ctx_no_url = _FakeState(config={'url': ''})
        assert not runtime._refresh_questions_metadata(ctx_no_url)

    def test_refresh_metadata_when_snapshot_drifts_only_refreshes_on_unknown_visible_questions(self, monkeypatch) -> None:
        ctx = _FakeState(questions_metadata={1: SurveyQuestionMeta(num=1, title='Q1', type_code='3', page=1)})
        refresh_calls: list[str] = []
        monkeypatch.setattr(runtime, '_refresh_questions_metadata', lambda _ctx: refresh_calls.append('refresh') or True)

        assert not runtime._refresh_metadata_when_snapshot_drifts(ctx, {1: {'visible': True}})
        assert runtime._refresh_metadata_when_snapshot_drifts(ctx, {1: {'visible': True}, 2: {'visible': True}})
        assert refresh_calls == ['refresh']

    def test_question_is_visible_uses_snapshot_or_dom_probe(self, monkeypatch) -> None:
        visible_div = _FakeQuestionDiv('3', displayed=True)
        hidden_div = _FakeQuestionDiv('3', displayed=False)
        broken_div = SimpleNamespace(is_displayed=Mock(side_effect=RuntimeError('boom')))
        sleep_calls: list[float] = []
        monkeypatch.setattr(runtime.time, 'sleep', lambda seconds: sleep_calls.append(seconds))

        assert runtime._question_is_visible(visible_div, {'visible': True})
        assert runtime._question_is_visible(visible_div, None)
        assert not runtime._question_is_visible(hidden_div, None)
        assert not runtime._question_is_visible(None, None)
        assert not runtime._question_is_visible(broken_div, None)
        assert sleep_calls == [0.04]

    def test_finalize_page_covers_last_page_and_next_page_branches(self, monkeypatch) -> None:
        ctx = _FakeState()
        runtime_config = ctx.config
        stop_signal = Mock()
        stop_signal.is_set.return_value = False
        stop_signal.wait.return_value = False
        calls: list[str] = []
        monkeypatch.setattr(runtime, '_human_scroll_after_question', lambda *_args: calls.append('scroll'))
        monkeypatch.setattr(runtime, 'HEADLESS_PAGE_BUFFER_DELAY', 0.2)
        monkeypatch.setattr(runtime, 'HEADLESS_PAGE_CLICK_DELAY', 0.3)
        monkeypatch.setattr(runtime, 'has_configured_answer_duration', lambda _value: True)
        monkeypatch.setattr(runtime, 'simulate_answer_duration_delay', lambda *_args, **_kwargs: False)
        monkeypatch.setattr(runtime, '_click_next_page_button', lambda *_args, **_kwargs: calls.append('next') or True)

        assert runtime._finalize_page(object(), stop_signal, headless_mode=True, is_last_page=True, runtime_config=runtime_config, thread_name='Worker-1', ctx=ctx)
        assert runtime._finalize_page(object(), stop_signal, headless_mode=True, is_last_page=False, runtime_config=runtime_config, thread_name='Worker-1', ctx=ctx)
        assert calls == ['scroll', 'scroll', 'next']
        assert ('等待时长中', True) in ctx.status_updates

    def test_finalize_page_handles_abort_and_missing_next_button(self, monkeypatch) -> None:
        ctx = _FakeState()
        updates: list[str] = []
        monkeypatch.setattr(runtime, '_human_scroll_after_question', lambda *_args: None)
        monkeypatch.setattr(runtime, '_update_abort_status', lambda _ctx, _name: updates.append('abort'))
        stop_set = Mock()
        stop_set.is_set.return_value = True

        assert not runtime._finalize_page(object(), stop_set, headless_mode=True, is_last_page=False, runtime_config=ctx.config, thread_name='Worker-1', ctx=ctx)
        assert updates == ['abort']

        stop_wait = Mock()
        stop_wait.is_set.return_value = False
        stop_wait.wait.return_value = True
        monkeypatch.setattr(runtime, 'HEADLESS_PAGE_BUFFER_DELAY', 0.1)
        assert not runtime._finalize_page(object(), stop_wait, headless_mode=True, is_last_page=False, runtime_config=ctx.config, thread_name='Worker-1', ctx=ctx)

        stop_ok = Mock()
        stop_ok.is_set.return_value = False
        stop_ok.wait.return_value = False
        monkeypatch.setattr(runtime, '_click_next_page_button', lambda *_args, **_kwargs: False)
        try:
            runtime._finalize_page(object(), stop_ok, headless_mode=True, is_last_page=False, runtime_config=ctx.config, thread_name='Worker-1', ctx=ctx)
        except Exception as exc:
            assert exc.__class__.__name__ == 'NoSuchElementException'
        else:
            raise AssertionError('expected NoSuchElementException')

    def test_run_question_dispatch_falls_back_when_dispatcher_returns_false(self, monkeypatch) -> None:
        ctx = _FakeState(question_config_index_map={4: ('single', 1)})
        indices = runtime._build_initial_indices()
        fallback_calls: list[tuple[int, str]] = []
        monkeypatch.setattr(runtime._dispatcher, 'fill', lambda **_kwargs: False)
        monkeypatch.setattr(runtime, '_fallback_unknown_question', lambda _driver, _ctx, *, question_num, question_type, question_div, indices: fallback_calls.append((question_num, question_type)))

        runtime._run_question_dispatch(object(), ctx, question_num=4, question_type='3', question_div=object(), indices=indices, psycho_plan=None)

        assert fallback_calls == [(4, '3')]

    def test_refill_required_questions_uses_mapped_index_without_mutating_snapshot_indices(self, monkeypatch) -> None:
        question_div = _FakeQuestionDiv('3', displayed=True)
        driver = _FakeDriver({'#div1': question_div})
        ctx = _FakeState(
            question_config_index_map={1: ('single', 0)},
            questions_metadata={1: SurveyQuestionMeta(num=1, title='Q1', type_code='3', page=1, required=True)},
        )
        state = runtime.get_wjx_runtime_state(driver)
        state.indices_snapshot = {'single': 6, 'text': 0, 'dropdown': 0, 'multiple': 0, 'matrix': 0, 'scale': 0, 'slider': 0}
        dispatch_calls: list[tuple[int, dict[str, int]]] = []
        monkeypatch.setattr(runtime, '_refresh_visible_question_snapshot', lambda *_args, **_kwargs: {1: {'visible': True, 'type': '3', 'title': 'Q1'}})
        monkeypatch.setattr(runtime, '_driver_question_looks_like_description', lambda *_args, **_kwargs: False)
        monkeypatch.setattr(
            runtime,
            '_run_question_dispatch',
            lambda _driver, _ctx, *, question_num, question_type, question_div, indices, psycho_plan: dispatch_calls.append((question_num, dict(indices))),
        )

        filled = runtime.refill_required_questions_on_current_page(
            driver,
            ctx,
            question_numbers=[1],
            thread_name='Worker-1',
        )

        assert filled == 1
        assert dispatch_calls == [(1, {'single': 0, 'text': 0, 'dropdown': 0, 'multiple': 0, 'matrix': 0, 'scale': 0, 'slider': 0})]
        assert state.indices_snapshot['single'] == 6

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

    def test_brush_detect_fallback_handles_description_hidden_and_missing_type_then_submits(self, monkeypatch) -> None:
        ctx = _FakeState()
        driver = _FakeDriver({
            '#div1': _FakeQuestionDiv('3', text='Q1'),
            '#div2': _FakeQuestionDiv('3', displayed=False, text='Q2'),
            '#div3': _FakeQuestionDiv(None, text='Q3'),
            '#div4': _FakeQuestionDiv('4', text='说明'),
        })
        calls: list[object] = []
        snapshots = iter([
            {1: {'visible': True, 'type': '3', 'title': 'Q1'}, 2: {'visible': False, 'type': '3', 'title': 'Q2'}, 3: {'visible': True, 'type': '', 'title': 'Q3'}, 4: {'visible': True, 'type': '4', 'title': '说明'}},
            {1: {'visible': True, 'type': '3', 'title': 'Q1'}, 2: {'visible': False, 'type': '3', 'title': 'Q2'}, 3: {'visible': True, 'type': '', 'title': 'Q3'}, 4: {'visible': True, 'type': '4', 'title': '说明'}},
            {1: {'visible': True, 'type': '3', 'title': 'Q1'}, 2: {'visible': False, 'type': '3', 'title': 'Q2'}, 3: {'visible': True, 'type': '', 'title': 'Q3'}, 4: {'visible': True, 'type': '4', 'title': '说明'}},
            {1: {'visible': True, 'type': '3', 'title': 'Q1'}, 2: {'visible': False, 'type': '3', 'title': 'Q2'}, 3: {'visible': True, 'type': '', 'title': 'Q3'}, 4: {'visible': True, 'type': '4', 'title': '说明'}},
        ])
        monkeypatch.setattr(runtime, '_wjx_detect', lambda *_args, **_kwargs: [4])
        monkeypatch.setattr(runtime, '_refresh_visible_question_snapshot', lambda _driver, **_kwargs: next(snapshots))
        monkeypatch.setattr(runtime, '_is_headless_mode', lambda _ctx: True)
        monkeypatch.setattr(runtime, 'HEADLESS_PAGE_BUFFER_DELAY', 0.0)
        monkeypatch.setattr(runtime, '_driver_question_looks_like_description', lambda _div, question_type: question_type == '4')
        monkeypatch.setattr(runtime, '_question_title_for_log', lambda *_args, **_kwargs: '标题')
        monkeypatch.setattr(runtime, '_run_question_dispatch', lambda *_args, **kwargs: calls.append(('dispatch', kwargs['question_num'])))
        monkeypatch.setattr(runtime, '_finalize_page', lambda *_args, **_kwargs: True)
        monkeypatch.setattr(runtime, 'submit', lambda *_args, **_kwargs: calls.append('submit'))

        assert runtime._brush_with_detect_fallback(driver, ctx, thread_name='Worker-1', psycho_plan=None)
        assert calls == [('dispatch', 1), 'submit']

    def test_brush_detect_fallback_does_not_refresh_snapshot_for_every_question(self, monkeypatch) -> None:
        ctx = _FakeState()
        driver = _FakeDriver({
            '#div1': _FakeQuestionDiv('3', displayed=True, text='Q1'),
            '#div2': _FakeQuestionDiv('3', displayed=True, text='Q2'),
            '#div3': _FakeQuestionDiv('3', displayed=True, text='Q3'),
        })
        refresh_reasons: list[str] = []
        monkeypatch.setattr(runtime, '_wjx_detect', lambda *_args, **_kwargs: [3])
        monkeypatch.setattr(runtime, '_refresh_visible_question_snapshot', lambda _driver, **kwargs: refresh_reasons.append(kwargs['reason']) or {
            1: {'visible': True, 'type': '3', 'title': 'Q1'},
            2: {'visible': True, 'type': '3', 'title': 'Q2'},
            3: {'visible': True, 'type': '3', 'title': 'Q3'},
        })
        monkeypatch.setattr(runtime, '_is_headless_mode', lambda _ctx: True)
        monkeypatch.setattr(runtime, 'HEADLESS_PAGE_BUFFER_DELAY', 0.0)
        monkeypatch.setattr(runtime, '_driver_question_looks_like_description', lambda *_args, **_kwargs: False)
        monkeypatch.setattr(runtime, '_run_question_dispatch', lambda *_args, **_kwargs: None)
        monkeypatch.setattr(runtime, '_finalize_page', lambda *_args, **_kwargs: True)
        monkeypatch.setattr(runtime, 'submit', lambda *_args, **_kwargs: None)

        assert runtime._brush_with_detect_fallback(driver, ctx, thread_name='Worker-1', psycho_plan=None)
        assert refresh_reasons == ['fallback_page_1']

    def test_brush_with_metadata_falls_back_when_no_page_plan(self, monkeypatch) -> None:
        ctx = _FakeState()
        monkeypatch.setattr(runtime, '_build_metadata_page_plan', lambda _ctx: [])
        monkeypatch.setattr(runtime, '_brush_with_detect_fallback', lambda *_args, **_kwargs: 'fallback-result')

        assert runtime._brush_with_metadata(object(), ctx, thread_name='Worker-1', psycho_plan=None) == 'fallback-result'

    def test_brush_with_metadata_refreshes_on_visibility_miss_and_display_logic(self, monkeypatch) -> None:
        q1 = SurveyQuestionMeta(num=1, title='Q1', type_code='3', page=1)
        q2 = SurveyQuestionMeta(num=2, title='Q2', type_code='3', page=1, has_display_condition=True)
        ctx = _FakeState(question_config_index_map={1: ('single', 0), 2: ('single', 1)}, questions_metadata={1: q1, 2: q2})
        driver = _FakeDriver({'#div1': _FakeQuestionDiv('3', displayed=True), '#div2': _FakeQuestionDiv('3', displayed=False)})
        calls: list[object] = []
        snapshots = iter([
            {1: {'visible': True, 'type': '3', 'title': 'Q1'}, 2: {'visible': False, 'type': '3', 'title': 'Q2'}},
            {1: {'visible': True, 'type': '3', 'title': 'Q1'}, 2: {'visible': True, 'type': '3', 'title': 'Q2'}},
            {1: {'visible': True, 'type': '3', 'title': 'Q1'}, 2: {'visible': True, 'type': '3', 'title': 'Q2'}},
        ])
        monkeypatch.setattr(runtime, '_is_headless_mode', lambda _ctx: True)
        monkeypatch.setattr(runtime, '_refresh_visible_question_snapshot', lambda _driver, **_kwargs: next(snapshots))
        monkeypatch.setattr(runtime, '_refresh_metadata_when_snapshot_drifts', lambda *_args, **_kwargs: False)
        monkeypatch.setattr(runtime, '_driver_question_looks_like_description', lambda *_args, **_kwargs: False)
        monkeypatch.setattr(runtime, '_question_is_visible', lambda question_div, snapshot_item: bool(snapshot_item and snapshot_item.get('visible')))
        monkeypatch.setattr(runtime, '_run_question_dispatch', lambda *_args, **kwargs: calls.append(('dispatch', kwargs['question_num'])))
        monkeypatch.setattr(runtime, '_finalize_page', lambda *_args, **_kwargs: True)
        monkeypatch.setattr(runtime, 'submit', lambda *_args, **_kwargs: calls.append('submit'))

        assert runtime._brush_with_metadata(driver, ctx, thread_name='Worker-1', psycho_plan=None)
        assert calls == [('dispatch', 1), ('dispatch', 2), 'submit']

    def test_brush_returns_false_when_stop_already_set_or_gate_rejects_and_wrapper_delegates(self, monkeypatch) -> None:
        ctx = _FakeState()
        stop_signal = threading.Event()
        stop_signal.set()
        updates: list[str] = []
        monkeypatch.setattr(runtime, '_update_abort_status', lambda _ctx, _thread_name: updates.append(_thread_name))

        assert not runtime.brush(object(), ctx, stop_signal=stop_signal, thread_name=' Worker-9 ', psycho_plan=None)
        assert updates == ['Worker-9']

        ctx2 = _FakeState()
        monkeypatch.setattr(runtime, '_prepare_runtime_entry_gate', lambda *_args, **_kwargs: False)
        monkeypatch.setattr(runtime, '_update_abort_status', lambda _ctx, _thread_name: updates.append(f'gate:{_thread_name}'))
        assert not runtime.brush(object(), ctx2, stop_signal=threading.Event(), thread_name=None, psycho_plan=None)

        calls: list[tuple[object, object, object, str, object]] = []
        monkeypatch.setattr(runtime, 'brush', lambda driver, ctx, *, stop_signal, thread_name, psycho_plan: calls.append((driver, ctx, stop_signal, thread_name, psycho_plan)) or True)
        assert runtime.brush_wjx('driver', object(), 'ctx', stop_signal='stop', thread_name='Worker-X', psycho_plan='plan')
        assert calls == [('driver', 'ctx', 'stop', 'Worker-X', 'plan')]

    def test_brush_without_intro_gate_starts_answering_immediately(self, patch_attrs) -> None:
        ctx = _FakeState(
            question_config_index_map={1: ('single', 0)},
            questions_metadata={1: SurveyQuestionMeta(num=1, title='Q1', type_code='3', page=1)},
        )
        driver = _FakeDriver({'#div1': _FakeQuestionDiv('3', text='Q1')})
        calls: list[object] = []

        def _fake_fill(*, question_num: int, **_kwargs):
            calls.append(('fill', question_num))
            return None

        patch_attrs(
            (runtime, 'dismiss_resume_dialog_if_present', lambda *_args, **_kwargs: calls.append('dismiss_resume')),
            (runtime, 'try_click_start_answer_button', lambda *_args, **_kwargs: calls.append('try_start_gate') or False),
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
        assert calls[:2] == ['dismiss_resume', 'try_start_gate']
        assert ('fill', 1) in calls
        assert calls[-1] == 'submit'

    def test_prepare_runtime_entry_gate_uses_short_timeouts(self, patch_attrs) -> None:
        calls: list[tuple[str, float | None]] = []

        patch_attrs(
            (runtime, 'dismiss_resume_dialog_if_present', lambda _driver, timeout=0.0, **_kwargs: calls.append(('resume', timeout)) or False),
            (runtime, 'try_click_start_answer_button', lambda _driver, timeout=0.0, **_kwargs: calls.append(('start', timeout)) or False),
        )

        result = runtime._prepare_runtime_entry_gate(object(), None)

        assert result is True
        assert calls == [('resume', 0.2), ('start', 0.35)]

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
