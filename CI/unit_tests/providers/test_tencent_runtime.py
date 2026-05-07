from __future__ import annotations
import pytest
import threading
from software.providers.contracts import SurveyQuestionMeta
from tencent.provider import runtime

def _meta(num: int, *, page: int=1, provider_question_id: str | None=None, provider_type: str='', unsupported: bool=False) -> SurveyQuestionMeta:
    return SurveyQuestionMeta(num=num, title=f'Q{num}', page=page, provider='tencent', type_code='single', provider_question_id=provider_question_id or f'q{num}', provider_page_id=f'p{page}', provider_type=provider_type, unsupported=unsupported)

class TencentRuntimeTests:

    def test_brush_qq_blocks_unsupported_question_before_runtime_starts(self, make_runtime_state) -> None:
        ctx = make_runtime_state({1: _meta(1, unsupported=True)}, {1: ('single', 0)})
        with pytest.raises(RuntimeError, match='未支持题型'):
            runtime.brush_qq(object(), object(), ctx, stop_signal=threading.Event(), thread_name='Worker-1', psycho_plan=None)

    def test_brush_qq_routes_matrix_star_to_star_handler(self, make_runtime_state, patch_attrs) -> None:
        question = _meta(1, provider_type='matrix_star')
        ctx = make_runtime_state({1: question}, {1: ('matrix', 0)})
        calls: list[str] = []
        patch_attrs(
            (runtime, '_wait_for_question_visible', lambda *_args, **_kwargs: True),
            (runtime, '_is_question_visible', lambda *_args, **_kwargs: True),
            (runtime, '_human_scroll_after_question', lambda *_args, **_kwargs: None),
            (runtime, 'dismiss_resume_dialog_if_present', lambda *_args, **_kwargs: None),
            (runtime, '_is_headless_mode', lambda _ctx: True),
            (runtime, 'HEADLESS_PAGE_BUFFER_DELAY', 0.0),
            (runtime, 'has_configured_answer_duration', lambda _value: False),
            (runtime, 'simulate_answer_duration_delay', lambda *_args, **_kwargs: False),
            (runtime, '_answer_qq_matrix_star', lambda *_args, **_kwargs: calls.append('star')),
            (runtime, '_answer_qq_matrix', lambda *_args, **_kwargs: calls.append('plain')),
            (runtime, 'submit', lambda *_args, **_kwargs: calls.append('submit')),
        )
        result = runtime.brush_qq(object(), object(), ctx, stop_signal=threading.Event(), thread_name='Worker-1', psycho_plan=None)
        assert result
        assert calls == ['star', 'submit']

    def test_brush_qq_walks_pages_then_submits(self, make_runtime_state, patch_attrs) -> None:
        ctx = make_runtime_state({1: _meta(1, page=1, provider_question_id='page1-q1'), 2: _meta(2, page=2, provider_question_id='page2-q1')}, {1: ('single', 0), 2: ('text', 0)})
        calls: list[object] = []
        patch_attrs(
            (runtime, '_wait_for_question_visible', lambda *_args, **_kwargs: True),
            (runtime, '_is_question_visible', lambda *_args, **_kwargs: True),
            (runtime, '_human_scroll_after_question', lambda *_args, **_kwargs: calls.append('scroll')),
            (runtime, 'dismiss_resume_dialog_if_present', lambda *_args, **_kwargs: None),
            (runtime, '_is_headless_mode', lambda _ctx: True),
            (runtime, 'HEADLESS_PAGE_BUFFER_DELAY', 0.0),
            (runtime, 'HEADLESS_PAGE_CLICK_DELAY', 0.0),
            (runtime, 'has_configured_answer_duration', lambda _value: False),
            (runtime, 'simulate_answer_duration_delay', lambda *_args, **_kwargs: False),
            (runtime, '_answer_qq_single', lambda *_args, **_kwargs: calls.append('single')),
            (runtime, '_answer_qq_text', lambda *_args, **_kwargs: calls.append('text')),
            (runtime, '_click_next_page_button', lambda *_args, **_kwargs: calls.append('next') or True),
            (runtime, '_wait_for_page_transition', lambda *_args, **_kwargs: calls.append(('transition', _args[1], _args[2]))),
            (runtime, 'submit', lambda *_args, **_kwargs: calls.append('submit')),
        )
        result = runtime.brush_qq(object(), object(), ctx, stop_signal=threading.Event(), thread_name='Worker-1', psycho_plan=None)
        assert result
        assert 'single' in calls
        assert 'text' in calls
        assert 'next' in calls
        assert ('transition', 'page1-q1', 'page2-q1') in calls
        assert calls[-1] == 'submit'
        assert ('提交中', True) in ctx.status_updates

    def test_brush_qq_prefers_page_snapshot_over_per_question_wait(self, make_runtime_state, patch_attrs) -> None:
        ctx = make_runtime_state({1: _meta(1, page=1, provider_question_id='page1-q1'), 2: _meta(2, page=1, provider_question_id='page1-q2')}, {1: ('single', 0), 2: ('text', 0)})
        calls: list[object] = []
        patch_attrs(
            (runtime, '_supports_page_snapshot', lambda _driver: True),
            (runtime, '_wait_for_question_visibility_map', lambda *_args, **_kwargs: {'page1-q1': {'attached': True, 'visible': True}, 'page1-q2': {'attached': True, 'visible': True}}),
            (runtime, '_wait_for_question_visible', lambda *_args, **_kwargs: calls.append('fallback-wait') or True),
            (runtime, '_human_scroll_after_question', lambda *_args, **_kwargs: None),
            (runtime, 'dismiss_resume_dialog_if_present', lambda *_args, **_kwargs: None),
            (runtime, '_is_headless_mode', lambda _ctx: True),
            (runtime, 'HEADLESS_PAGE_BUFFER_DELAY', 0.0),
            (runtime, 'has_configured_answer_duration', lambda _value: False),
            (runtime, 'simulate_answer_duration_delay', lambda *_args, **_kwargs: False),
            (runtime, '_answer_qq_single', lambda *_args, **_kwargs: calls.append('single')),
            (runtime, '_answer_qq_text', lambda *_args, **_kwargs: calls.append('text')),
            (runtime, 'submit', lambda *_args, **_kwargs: calls.append('submit')),
        )
        result = runtime.brush_qq(object(), object(), ctx, stop_signal=threading.Event(), thread_name='Worker-1', psycho_plan=None)
        assert result
        assert 'fallback-wait' not in calls
        assert calls == ['single', 'text', 'submit']

    def test_brush_qq_aborts_during_final_duration_wait_before_submit(self, make_runtime_state, patch_attrs) -> None:
        ctx = make_runtime_state({1: _meta(1)}, {1: ('single', 0)})
        calls: list[str] = []
        patch_attrs(
            (runtime, '_wait_for_question_visible', lambda *_args, **_kwargs: True),
            (runtime, '_is_question_visible', lambda *_args, **_kwargs: True),
            (runtime, '_human_scroll_after_question', lambda *_args, **_kwargs: None),
            (runtime, 'dismiss_resume_dialog_if_present', lambda *_args, **_kwargs: None),
            (runtime, '_is_headless_mode', lambda _ctx: True),
            (runtime, 'HEADLESS_PAGE_BUFFER_DELAY', 0.0),
            (runtime, 'has_configured_answer_duration', lambda _value: True),
            (runtime, 'simulate_answer_duration_delay', lambda *_args, **_kwargs: True),
            (runtime, '_answer_qq_single', lambda *_args, **_kwargs: calls.append('single')),
            (runtime, 'submit', lambda *_args, **_kwargs: calls.append('submit')),
        )
        result = runtime.brush_qq(object(), object(), ctx, stop_signal=threading.Event(), thread_name='Worker-1', psycho_plan=None)
        assert not result
        assert calls == ['single']
        assert ('等待时长中', True) in ctx.status_updates
        assert ctx.status_updates[-1] == ('已中断', False)

    def test_brush_qq_skips_question_when_snapshot_says_not_visible_and_no_mapping(self, make_runtime_state, patch_attrs) -> None:
        ctx = make_runtime_state(
            {1: _meta(1, provider_question_id='page1-q1'), 2: _meta(2, provider_question_id='page1-q2')},
            {1: ('single', 0)},
        )
        calls: list[object] = []
        patch_attrs(
            (runtime, '_supports_page_snapshot', lambda _driver: True),
            (runtime, '_wait_for_question_visibility_map', lambda *_args, **_kwargs: {'page1-q1': {'visible': True}, 'page1-q2': {'visible': False}}),
            (runtime, '_wait_for_question_visible', lambda *_args, **_kwargs: calls.append('fallback-visible') or True),
            (runtime, '_is_question_visible', lambda *_args, **_kwargs: True),
            (runtime, '_human_scroll_after_question', lambda *_args, **_kwargs: None),
            (runtime, 'dismiss_resume_dialog_if_present', lambda *_args, **_kwargs: None),
            (runtime, '_is_headless_mode', lambda _ctx: True),
            (runtime, 'HEADLESS_PAGE_BUFFER_DELAY', 0.0),
            (runtime, 'has_configured_answer_duration', lambda _value: False),
            (runtime, 'simulate_answer_duration_delay', lambda *_args, **_kwargs: False),
            (runtime, '_answer_qq_single', lambda *_args, **_kwargs: calls.append('single')),
            (runtime, 'submit', lambda *_args, **_kwargs: calls.append('submit')),
        )

        result = runtime.brush_qq(object(), object(), ctx, stop_signal=threading.Event(), thread_name='Worker-1', psycho_plan=None)

        assert result
        assert calls == ['single', 'submit']

    def test_brush_qq_uses_fallback_visibility_and_routes_multiple_dropdown_score_matrix(self, make_runtime_state, patch_attrs) -> None:
        ctx = make_runtime_state(
            {
                1: _meta(1, provider_question_id='q1'),
                2: _meta(2, provider_question_id='q2'),
                3: _meta(3, provider_question_id='q3'),
                4: _meta(4, provider_question_id='q4', provider_type='matrix'),
            },
            {1: ('multiple', 0), 2: ('dropdown', 1), 3: ('score', 2), 4: ('matrix', 3)},
        )
        calls: list[str] = []
        patch_attrs(
            (runtime, '_supports_page_snapshot', lambda _driver: False),
            (runtime, '_wait_for_question_visible', lambda *_args, **_kwargs: True),
            (runtime, '_human_scroll_after_question', lambda *_args, **_kwargs: None),
            (runtime, 'dismiss_resume_dialog_if_present', lambda *_args, **_kwargs: None),
            (runtime, '_is_headless_mode', lambda _ctx: True),
            (runtime, 'HEADLESS_PAGE_BUFFER_DELAY', 0.0),
            (runtime, 'has_configured_answer_duration', lambda _value: False),
            (runtime, 'simulate_answer_duration_delay', lambda *_args, **_kwargs: False),
            (runtime, '_answer_qq_multiple', lambda *_args, **_kwargs: calls.append('multiple')),
            (runtime, '_answer_qq_dropdown', lambda *_args, **_kwargs: calls.append('dropdown')),
            (runtime, '_answer_qq_score_like', lambda *_args, **_kwargs: calls.append('score')),
            (runtime, '_answer_qq_matrix', lambda *_args, **_kwargs: calls.append('matrix')),
            (runtime, 'submit', lambda *_args, **_kwargs: calls.append('submit')),
        )

        result = runtime.brush_qq(object(), object(), ctx, stop_signal=threading.Event(), thread_name='Worker-1', psycho_plan='plan')

        assert result
        assert calls == ['multiple', 'dropdown', 'score', 'matrix', 'submit']

    def test_brush_qq_aborts_before_question_and_on_page_delay_and_raises_when_next_missing(self, make_runtime_state, patch_attrs) -> None:
        ctx = make_runtime_state(
            {1: _meta(1, page=1, provider_question_id='page1-q1'), 2: _meta(2, page=2, provider_question_id='page2-q1')},
            {1: ('single', 0), 2: ('single', 1)},
        )
        stop_signal = threading.Event()
        stop_signal.set()
        patch_attrs(
            (runtime, '_wait_for_question_visible', lambda *_args, **_kwargs: True),
            (runtime, '_human_scroll_after_question', lambda *_args, **_kwargs: None),
            (runtime, 'dismiss_resume_dialog_if_present', lambda *_args, **_kwargs: None),
            (runtime, '_is_headless_mode', lambda _ctx: True),
        )
        assert not runtime.brush_qq(object(), object(), ctx, stop_signal=stop_signal, thread_name='Worker-1', psycho_plan=None)
        assert ctx.status_updates[-1] == ('已中断', False)

        ctx2 = make_runtime_state({1: _meta(1)}, {1: ('single', 0)})
        wait_stop = threading.Event()
        setattr(wait_stop, 'wait', lambda _timeout: True)
        patch_attrs(
            (runtime, '_wait_for_question_visible', lambda *_args, **_kwargs: True),
            (runtime, '_human_scroll_after_question', lambda *_args, **_kwargs: None),
            (runtime, 'dismiss_resume_dialog_if_present', lambda *_args, **_kwargs: None),
            (runtime, '_is_headless_mode', lambda _ctx: True),
            (runtime, 'HEADLESS_PAGE_BUFFER_DELAY', 0.1),
            (runtime, '_answer_qq_single', lambda *_args, **_kwargs: None),
        )
        assert not runtime.brush_qq(object(), object(), ctx2, stop_signal=wait_stop, thread_name='Worker-2', psycho_plan=None)
        assert ctx2.status_updates[-1] == ('已中断', False)

        ctx3 = make_runtime_state(
            {1: _meta(1, page=1, provider_question_id='page1-q1'), 2: _meta(2, page=2, provider_question_id='page2-q1')},
            {1: ('single', 0), 2: ('single', 1)},
        )
        patch_attrs(
            (runtime, '_wait_for_question_visible', lambda *_args, **_kwargs: True),
            (runtime, '_human_scroll_after_question', lambda *_args, **_kwargs: None),
            (runtime, 'dismiss_resume_dialog_if_present', lambda *_args, **_kwargs: None),
            (runtime, '_is_headless_mode', lambda _ctx: True),
            (runtime, 'HEADLESS_PAGE_BUFFER_DELAY', 0.0),
            (runtime, '_answer_qq_single', lambda *_args, **_kwargs: None),
            (runtime, '_click_next_page_button', lambda *_args, **_kwargs: False),
        )
        with pytest.raises(Exception, match='下一页按钮未找到'):
            runtime.brush_qq(object(), object(), ctx3, stop_signal=threading.Event(), thread_name='Worker-3', psycho_plan=None)
