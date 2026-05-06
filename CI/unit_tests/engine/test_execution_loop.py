from __future__ import annotations
import pytest
import threading
from contextlib import ExitStack
from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock
import software.core.engine.execution_loop as execution_loop_module
from software.core.engine.execution_loop import ExecutionLoop, _load_survey_page
from software.core.engine.page_load_probe import PAGE_LOAD_PROBE_ANSWERABLE, PAGE_LOAD_PROBE_BUSINESS_PAGE, PAGE_LOAD_PROBE_PROXY_UNUSABLE, PageLoadProbeResult
from software.core.reverse_fill.schema import REVERSE_FILL_KIND_CHOICE, ReverseFillAnswer, ReverseFillSampleRow, ReverseFillSpec
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser import BrowserStartupErrorInfo

class _FakePreloadedPool:
    last_created: '_FakePreloadedPool | None' = None

    def __init__(self, *_args, **_kwargs):
        self.warm_async_calls: list[tuple[list[str], int, int]] = []
        self.acquire_calls = 0
        self.shutdown_called = 0
        self.next_lease = SimpleNamespace(session=None, browser_name='', preloaded=False)
        _FakePreloadedPool.last_created = self

    def warm_async(self, preferred_browsers, window_x_pos: int, window_y_pos: int) -> None:
        self.warm_async_calls.append((list(preferred_browsers or []), int(window_x_pos), int(window_y_pos)))

    def acquire(self, _stop_signal: threading.Event, *, wait: bool=True):
        self.acquire_calls += 1
        return self.next_lease

    def shutdown(self) -> None:
        self.shutdown_called += 1

class _FakeStopPolicy:

    def __init__(self, *, stop_on_failure: bool=True, success_should_stop: bool=True):
        self.stop_on_failure = stop_on_failure
        self.success_should_stop = success_should_stop
        self.failure_calls: list[object] = []
        self.failure_kwargs: list[dict[str, object]] = []
        self.success_calls = 0

    def wait_if_paused(self, _stop_signal: threading.Event) -> None:
        return None

    def record_failure(self, stop_signal: threading.Event, **kwargs):
        self.failure_calls.append(kwargs.get('failure_reason'))
        self.failure_kwargs.append(dict(kwargs))
        if self.stop_on_failure and (not stop_signal.is_set()):
            stop_signal.set()
        return self.stop_on_failure

    def record_success(self, _stop_signal: threading.Event, **_kwargs):
        self.success_calls += 1
        return self.success_should_stop

class _FakeSubmissionService:

    def __init__(self, outcome: SimpleNamespace, before_return=None):
        self.outcome = outcome
        self.before_return = before_return
        self.calls = 0

    def finalize_after_submit(self, _driver, *, stop_signal: threading.Event, **_kwargs):
        self.calls += 1
        if callable(self.before_return):
            self.before_return(stop_signal)
        return self.outcome

class ExecutionLoopTests:

    def _build_reverse_fill_state(self, *, target_num: int=1) -> ExecutionState:
        spec = ReverseFillSpec(source_path='demo.xlsx', selected_format='wjx_sequence', detected_format='wjx_sequence', start_row=1, total_samples=1, available_samples=1, target_num=target_num, samples=[ReverseFillSampleRow(data_row_number=1, worksheet_row_number=2, answers={1: ReverseFillAnswer(question_num=1, kind=REVERSE_FILL_KIND_CHOICE, choice_index=0)})])
        state = ExecutionState(config=ExecutionConfig(url='https://example.com', reverse_fill_spec=spec, target_num=target_num))
        state.initialize_reverse_fill_runtime()
        return state

    def test_load_survey_page_keeps_default_timeout_for_non_credamo(self, make_navigation_driver) -> None:
        config = ExecutionConfig(url='https://example.com', survey_provider='wjx')
        driver = make_navigation_driver()
        _load_survey_page(driver, config)
        assert driver.calls == [('https://example.com', 20000, 'domcontentloaded')]

    def test_load_survey_page_retries_credamo_with_commit_after_timeout(self, make_navigation_driver) -> None:
        config = ExecutionConfig(url='https://www.credamo.com/answer.html#/s/demo', survey_provider='credamo')
        driver = make_navigation_driver(failures=1)
        _load_survey_page(driver, config)
        assert driver.calls == [('https://www.credamo.com/answer.html#/s/demo', 45000, 'domcontentloaded'), ('https://www.credamo.com/answer.html#/s/demo', 45000, 'commit')]

    def test_load_survey_page_retries_non_credamo_with_longer_timeout(self, make_navigation_driver) -> None:
        config = ExecutionConfig(url='https://example.com', survey_provider='wjx')
        driver = make_navigation_driver(failures=1)
        _load_survey_page(driver, config)
        assert driver.calls == [('https://example.com', 20000, 'domcontentloaded'), ('https://example.com', 35000, 'domcontentloaded')]

    def test_load_survey_page_random_proxy_timeout_is_not_marked_as_bad_proxy(self, make_navigation_driver) -> None:
        config = ExecutionConfig(url='https://www.credamo.com/answer.html#/s/demo', survey_provider='credamo', random_proxy_ip_enabled=True)
        driver = make_navigation_driver(failures=2, failure_message='Timeout 45000ms exceeded')
        with pytest.raises(TimeoutError):
            _load_survey_page(driver, config)

    def test_load_survey_page_random_proxy_network_error_marks_bad_proxy(self, make_navigation_driver) -> None:
        config = ExecutionConfig(url='https://www.credamo.com/answer.html#/s/demo', survey_provider='credamo', random_proxy_ip_enabled=True)
        driver = make_navigation_driver(failures=2, failure_message='net::ERR_PROXY_CONNECTION_FAILED')
        with pytest.raises(execution_loop_module.ProxyConnectionError):
            _load_survey_page(driver, config)

    def test_load_survey_page_random_proxy_uses_commit_probe_shortcut(self, patch_attrs, make_navigation_driver) -> None:
        config = ExecutionConfig(url='https://example.com', survey_provider='wjx', random_proxy_ip_enabled=True)
        driver = make_navigation_driver()
        patch_attrs(
            (execution_loop_module, 'wait_for_page_probe', lambda *_args, **_kwargs: PageLoadProbeResult(PAGE_LOAD_PROBE_ANSWERABLE, detail='wjx_questionnaire')),
        )
        _load_survey_page(driver, config)
        assert driver.calls == [('https://example.com', 8000, 'commit')]

    def test_load_survey_page_random_proxy_waits_on_original_page_before_reload(self, patch_attrs, make_navigation_driver) -> None:
        config = ExecutionConfig(url='https://example.com', survey_provider='wjx', random_proxy_ip_enabled=True)
        driver = make_navigation_driver()
        probe_results = iter([PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail='page_still_loading', retryable=False), PageLoadProbeResult(PAGE_LOAD_PROBE_ANSWERABLE, detail='wjx_questionnaire')])
        patch_attrs(
            (execution_loop_module, 'wait_for_page_probe', lambda *_args, **_kwargs: next(probe_results)),
        )
        _load_survey_page(driver, config)
        assert driver.calls == [('https://example.com', 8000, 'commit')]

    def test_load_survey_page_random_proxy_falls_back_to_domcontentloaded_after_probe_miss(self, patch_attrs, make_navigation_driver) -> None:
        config = ExecutionConfig(url='https://example.com', survey_provider='wjx', random_proxy_ip_enabled=True)
        driver = make_navigation_driver()
        probe_results = iter([PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail='blank_page', retryable=False), PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail='blank_page', retryable=False), PageLoadProbeResult(PAGE_LOAD_PROBE_ANSWERABLE, detail='wjx_dom_ready')])
        patch_attrs(
            (execution_loop_module, 'wait_for_page_probe', lambda *_args, **_kwargs: next(probe_results)),
        )
        _load_survey_page(driver, config)
        assert driver.calls == [('https://example.com', 8000, 'commit'), ('https://example.com', 6000, 'domcontentloaded')]

    def test_load_survey_page_random_proxy_raises_proxy_failure_after_two_probe_misses(self, patch_attrs, make_navigation_driver) -> None:
        config = ExecutionConfig(url='https://example.com', survey_provider='wjx', random_proxy_ip_enabled=True)
        driver = make_navigation_driver()
        probe_results = iter([PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail='blank_page', retryable=False), PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail='blank_page', retryable=False), PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail='proxy_error_page', retryable=False)])
        patch_attrs(
            (execution_loop_module, 'wait_for_page_probe', lambda *_args, **_kwargs: next(probe_results)),
        )
        with pytest.raises(execution_loop_module.ProxyConnectionError):
            _load_survey_page(driver, config)
        assert driver.calls == [('https://example.com', 8000, 'commit'), ('https://example.com', 6000, 'domcontentloaded')]

    def test_load_survey_page_random_proxy_grants_loading_grace_before_marking_proxy_bad(self, patch_attrs, make_navigation_driver) -> None:
        config = ExecutionConfig(url='https://example.com', survey_provider='wjx', random_proxy_ip_enabled=True)
        driver = make_navigation_driver()
        probe_results = iter([PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail='page_still_loading', retryable=False), PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail='page_still_loading', retryable=False), PageLoadProbeResult(PAGE_LOAD_PROBE_ANSWERABLE, detail='wjx_questionnaire')])
        patch_attrs(
            (execution_loop_module, 'wait_for_page_probe', lambda *_args, **_kwargs: next(probe_results)),
        )
        _load_survey_page(driver, config)
        assert driver.calls == [('https://example.com', 8000, 'commit'), ('https://example.com', 6000, 'domcontentloaded')]

    def test_load_survey_page_random_proxy_accepts_business_page_probe(self, patch_attrs, make_navigation_driver) -> None:
        config = ExecutionConfig(url='https://example.com', survey_provider='wjx', random_proxy_ip_enabled=True)
        driver = make_navigation_driver(failures=1)
        patch_attrs(
            (execution_loop_module, 'wait_for_page_probe', lambda *_args, **_kwargs: PageLoadProbeResult(PAGE_LOAD_PROBE_BUSINESS_PAGE, detail='device_quota_limit')),
        )
        _load_survey_page(driver, config)
        assert driver.calls == [('https://example.com', 8000, 'commit'), ('https://example.com', 6000, 'domcontentloaded')]

    def test_load_survey_or_record_failure_updates_phase_to_loading(self, patch_attrs) -> None:
        config = ExecutionConfig(url='https://example.com', survey_provider='wjx')
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = SimpleNamespace(driver=object())
        loop = ExecutionLoop(config, state)
        patch_attrs(
            (execution_loop_module, '_load_survey_page', lambda *_args, **_kwargs: None),
        )
        result = loop._load_survey_or_record_failure(session, stop_signal, thread_name='Slot-1', timed_mode_on=False, timed_refresh_interval=0.0)
        assert result
        assert state.thread_progress['Slot-1'].status_text == '加载问卷'

    def test_load_survey_or_record_failure_propagates_proxy_connection_error(self, patch_attrs) -> None:
        config = ExecutionConfig(url='https://example.com', survey_provider='wjx', random_proxy_ip_enabled=True)
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = SimpleNamespace(driver=object())
        loop = ExecutionLoop(config, state)
        loop.stop_policy = _FakeStopPolicy(stop_on_failure=True)
        patch_attrs(
            (execution_loop_module, '_load_survey_page', lambda *_args, **_kwargs: (_ for _ in ()).throw(execution_loop_module.ProxyConnectionError('proxy dead'))),
        )
        with pytest.raises(execution_loop_module.ProxyConnectionError):
            loop._load_survey_or_record_failure(session, stop_signal, thread_name='Slot-1', timed_mode_on=False, timed_refresh_interval=0.0)
        assert loop.stop_policy.failure_calls == []

    def test_prepare_browser_session_records_proxy_failure_when_random_proxy_returns_none(self, patch_attrs, make_browser_session) -> None:
        config = ExecutionConfig(url='https://example.com', random_proxy_ip_enabled=True)
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = make_browser_session(driver=None)
        session.create_browser = lambda *_args, **_kwargs: None
        loop = ExecutionLoop(config, state)
        loop.stop_policy = _FakeStopPolicy(stop_on_failure=False)
        patch_attrs(
            (execution_loop_module, '_record_bad_proxy_and_maybe_pause', lambda *_args, **_kwargs: False),
        )
        preferred = loop._prepare_browser_session(session, ['edge'], ['edge', 'chrome'], window_x_pos=0, window_y_pos=0, stop_signal=stop_signal, thread_name='Slot-1')
        assert preferred == ['edge']
        assert loop.stop_policy.failure_calls == [execution_loop_module.FailureReason.PROXY_UNAVAILABLE]
        assert loop.stop_policy.failure_kwargs[0].get('status_text') == '代理不可用'
        assert not bool(loop.stop_policy.failure_kwargs[0].get('consume_reverse_fill_attempt', True))
        assert state.thread_progress['Slot-1'].status_text == '代理不可用'
        assert not stop_signal.is_set()

    def test_handle_proxy_connection_error_records_failure_before_retrying_next_proxy(self, patch_attrs) -> None:
        config = ExecutionConfig(url='https://example.com', random_proxy_ip_enabled=True)
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = SimpleNamespace(proxy_address='http://1.1.1.1:8000')
        loop = ExecutionLoop(config, state)
        loop.stop_policy = _FakeStopPolicy(stop_on_failure=False)
        marked_bad: list[str] = []
        patch_attrs(
            (execution_loop_module, '_mark_proxy_temporarily_bad', lambda _state, proxy_address: marked_bad.append(proxy_address)),
            (execution_loop_module, '_record_bad_proxy_and_maybe_pause', lambda *_args, **_kwargs: False),
        )
        should_stop = loop._handle_proxy_connection_error(session, stop_signal, thread_name='Slot-1')
        assert not should_stop
        assert marked_bad == ['http://1.1.1.1:8000']
        assert loop.stop_policy.failure_calls == [execution_loop_module.FailureReason.PROXY_UNAVAILABLE]
        assert loop.stop_policy.failure_kwargs[0].get('status_text') == '代理不可用'
        assert not bool(loop.stop_policy.failure_kwargs[0].get('consume_reverse_fill_attempt', True))
        assert state.thread_progress['Slot-1'].status_text == '代理失效，切换中'
        assert not stop_signal.is_set()

    def test_run_thread_finishes_cleanly_when_url_is_empty(self, patch_attrs, make_browser_session) -> None:
        config = ExecutionConfig(url='')
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = make_browser_session(driver=object())
        patch_attrs(
            (execution_loop_module, 'BrowserSessionService', lambda *_args, **_kwargs: session),
        )
        loop = ExecutionLoop(config, state)
        loop.run_thread(0, 0, stop_signal)
        assert not stop_signal.is_set()
        assert session.shutdown_called == 1
        assert state.thread_progress['MainThread'].status_text == '已停止'
        assert not state.thread_progress['MainThread'].running

    def test_run_thread_stops_when_browser_environment_is_blocked(self, patch_attrs, make_browser_session) -> None:
        config = ExecutionConfig(url='https://example.com')
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = make_browser_session(create_browser_exception=RuntimeError('blocked'))
        patch_attrs(
            (execution_loop_module, 'BrowserSessionService', lambda *_args, **_kwargs: session),
            (execution_loop_module, 'classify_playwright_startup_error', lambda _exc: BrowserStartupErrorInfo('browser_environment', '环境阻止启动', True)),
        )
        loop = ExecutionLoop(config, state)
        loop.run_thread(0, 0, stop_signal)
        assert stop_signal.is_set()
        assert state.get_terminal_stop_snapshot()[0] == 'browser_environment'
        assert session.shutdown_called == 1

    def test_run_thread_disposes_driver_after_page_load_failure(self, patch_attrs, make_browser_session) -> None:
        config = ExecutionConfig(url='https://example.com')
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = make_browser_session(driver=object())
        patch_attrs(
            (execution_loop_module, 'BrowserSessionService', lambda *_args, **_kwargs: session),
        )
        loop = ExecutionLoop(config, state)
        loop.stop_policy = _FakeStopPolicy(stop_on_failure=True)
        loop.run_thread(0, 0, stop_signal)
        assert stop_signal.is_set()
        assert session.dispose_called == 1
        assert session.shutdown_called == 1

    def test_run_thread_handles_device_quota_limit_and_cleans_up_session(self, patch_attrs, make_browser_session) -> None:
        config = ExecutionConfig(url='https://example.com', survey_provider='wjx')
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = make_browser_session(driver=object())
        patch_attrs(
            (execution_loop_module, 'BrowserSessionService', lambda *_args, **_kwargs: session),
            (execution_loop_module, '_provider_is_device_quota_limit_page', lambda *_args, **_kwargs: True),
        )
        loop = ExecutionLoop(config, state)
        loop.stop_policy = _FakeStopPolicy(stop_on_failure=True)
        loop.run_thread(0, 0, stop_signal)
        assert stop_signal.is_set()
        assert session.dispose_called == 1
        assert session.shutdown_called == 1

    def test_run_thread_success_path_calls_submission_service(self, patch_attrs, make_browser_session, make_navigation_driver) -> None:
        config = ExecutionConfig(url='https://example.com', survey_provider='wjx')
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = make_browser_session(driver=make_navigation_driver())
        outcome = SimpleNamespace(status='success', should_stop=True)

        def _prepare_round_context(self, _stop_signal, *, thread_name: str, session) -> bool:
            del thread_name, session
            return True
        patch_attrs(
            (execution_loop_module, 'BrowserSessionService', lambda *_args, **_kwargs: session),
            (execution_loop_module, '_provider_is_device_quota_limit_page', lambda *_args, **_kwargs: False),
            (execution_loop_module, '_provider_fill_survey', lambda *_args, **_kwargs: True),
        )
        loop = ExecutionLoop(config, state)
        loop.stop_policy = _FakeStopPolicy(stop_on_failure=True, success_should_stop=True)
        loop.submission_service = _FakeSubmissionService(outcome)
        loop._prepare_round_context = MethodType(_prepare_round_context, loop)
        loop.run_thread(0, 0, stop_signal)
        assert loop.submission_service.calls == 1
        assert loop.stop_policy.success_calls == 0
        assert session.dispose_called == 1
        assert session.shutdown_called == 1

    def test_run_thread_submission_failure_disposes_driver(self, patch_attrs, make_browser_session, make_navigation_driver) -> None:
        config = ExecutionConfig(url='https://example.com', survey_provider='wjx')
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = make_browser_session(driver=make_navigation_driver())
        outcome = SimpleNamespace(status='failure', should_stop=False)

        def _prepare_round_context(self, _stop_signal, *, thread_name: str, session) -> bool:
            del thread_name, session
            return True
        patch_attrs(
            (execution_loop_module, 'BrowserSessionService', lambda *_args, **_kwargs: session),
            (execution_loop_module, '_provider_is_device_quota_limit_page', lambda *_args, **_kwargs: False),
            (execution_loop_module, '_provider_fill_survey', lambda *_args, **_kwargs: True),
        )
        loop = ExecutionLoop(config, state)
        loop.stop_policy = _FakeStopPolicy(stop_on_failure=True, success_should_stop=False)
        loop.submission_service = _FakeSubmissionService(outcome, before_return=lambda sig: sig.set())
        loop._prepare_round_context = MethodType(_prepare_round_context, loop)
        loop.run_thread(0, 0, stop_signal)
        assert stop_signal.is_set()
        assert loop.submission_service.calls == 1
        assert session.dispose_called == 1
        assert session.shutdown_called == 1

    def test_random_proxy_connection_error_retries_without_counting_business_failure(self, patch_attrs, make_browser_session) -> None:
        config = ExecutionConfig(url='https://example.com', survey_provider='wjx', random_proxy_ip_enabled=True)
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = make_browser_session(driver=object())
        session.proxy_address = 'http://1.1.1.1:8000'
        patch_attrs(
            (execution_loop_module, 'BrowserSessionService', lambda *_args, **_kwargs: session),
            (execution_loop_module, '_provider_is_device_quota_limit_page', lambda *_args, **_kwargs: False),
            (execution_loop_module, '_mark_proxy_temporarily_bad', lambda *_args, **_kwargs: None),
        )
        loop = ExecutionLoop(config, state)
        loop.stop_policy = _FakeStopPolicy(stop_on_failure=True)

        def _proxy_failure(self, *_args, **_kwargs):
            stop_signal.set()
            raise execution_loop_module.ProxyConnectionError('boom')
        loop._load_survey_or_record_failure = MethodType(_proxy_failure, loop)
        loop.run_thread(0, 0, stop_signal)
        assert stop_signal.is_set()
        assert loop.stop_policy.failure_calls == []
        assert session.dispose_called >= 1
        assert session.shutdown_called == 1

    def test_run_thread_uses_preloaded_session_without_reloading_page(self, patch_attrs, make_browser_session, make_navigation_driver) -> None:
        config = ExecutionConfig(url='https://example.com', survey_provider='wjx')
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = make_browser_session(driver=make_navigation_driver())
        outcome = SimpleNamespace(status='success', should_stop=True)
        _FakePreloadedPool.last_created = None

        def _prepare_round_context(self, _stop_signal, *, thread_name: str, session=None) -> bool:
            del thread_name, session
            return True

        def _unexpected_load(*_args, **_kwargs):
            raise AssertionError('预热 session 命中时不应重新加载问卷页')
        patch_attrs(
            (execution_loop_module, 'PreloadedBrowserSessionPool', _FakePreloadedPool),
            (execution_loop_module, '_provider_is_device_quota_limit_page', lambda *_args, **_kwargs: False),
            (execution_loop_module, '_provider_fill_survey', lambda *_args, **_kwargs: True),
        )
        loop = ExecutionLoop(config, state, browser_owner_pool=object())
        loop.stop_policy = _FakeStopPolicy(stop_on_failure=True, success_should_stop=True)
        loop.submission_service = _FakeSubmissionService(outcome)
        loop._prepare_round_context = MethodType(_prepare_round_context, loop)
        loop._load_survey_or_record_failure = MethodType(_unexpected_load, loop)
        pool_factory = _FakePreloadedPool
        original_init = pool_factory.__init__

        def _patched_init(self, *_args, **_kwargs):
            original_init(self, *_args, **_kwargs)
            self.next_lease = SimpleNamespace(session=session, browser_name='edge', preloaded=True)
        pool_factory.__init__ = _patched_init
        try:
            loop.run_thread(0, 0, stop_signal)
        finally:
            pool_factory.__init__ = original_init
        pool_instance = _FakePreloadedPool.last_created
        assert pool_instance is not None
        assert pool_instance is not None
        assert len(pool_instance.warm_async_calls) >= 1
        assert pool_instance.acquire_calls == 1
        assert pool_instance.shutdown_called == 1
        assert session.dispose_called == 1
        assert loop.submission_service.calls == 1

    def test_preloaded_path_prepares_round_context_before_page_ready(self, patch_attrs, make_browser_session) -> None:
        config = ExecutionConfig(url='https://example.com', survey_provider='wjx')
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = make_browser_session(driver=object())
        _FakePreloadedPool.last_created = None
        prepare_round_context_calls = 0

        def _prepare_round_context(self, _stop_signal, *, thread_name: str, session=None) -> bool:
            del self, _stop_signal, thread_name, session
            nonlocal prepare_round_context_calls
            prepare_round_context_calls += 1
            return True
        patch_attrs(
            (execution_loop_module, 'PreloadedBrowserSessionPool', _FakePreloadedPool),
            (execution_loop_module, '_provider_is_device_quota_limit_page', lambda *_args, **_kwargs: False),
        )
        loop = ExecutionLoop(config, state, browser_owner_pool=object())
        loop.stop_policy = _FakeStopPolicy(stop_on_failure=True)
        loop._prepare_round_context = MethodType(_prepare_round_context, loop)
        pool_factory = _FakePreloadedPool
        original_init = pool_factory.__init__

        def _patched_init(self, *_args, **_kwargs):
            original_init(self, *_args, **_kwargs)
            self.next_lease = SimpleNamespace(session=session, browser_name='', preloaded=False)
        pool_factory.__init__ = _patched_init
        try:
            loop.run_thread(0, 0, stop_signal)
        finally:
            pool_factory.__init__ = original_init
        assert stop_signal.is_set()
        assert prepare_round_context_calls == 1
        assert loop.stop_policy.failure_calls == [execution_loop_module.FailureReason.PAGE_LOAD_FAILED]

    def test_prepare_round_context_requeues_reverse_fill_when_joint_slot_unavailable(self, patch_attrs) -> None:
        state = self._build_reverse_fill_state()
        config = state.config
        loop = ExecutionLoop(config, state)
        stop_signal = threading.Event()
        state.wait_for_runtime_change = MagicMock(side_effect=lambda **_kwargs: stop_signal.set() or True)
        state.reserve_joint_sample(2, thread_name='Worker-8')
        state.reserve_joint_sample(2, thread_name='Worker-9')
        patch_attrs(
            (execution_loop_module, 'ensure_joint_psychometric_answer_plan', lambda _config: SimpleNamespace(sample_count=2)),
        )
        ready = loop._prepare_round_context(stop_signal, thread_name='Worker-1', session=None)
        assert not ready
        assert list(state.reverse_fill_runtime.queued_row_numbers) == [1]
        assert state.thread_progress['Worker-1'].status_text == '等待信效度配额槽位'
        state.wait_for_runtime_change.assert_called_once()

    def test_prepare_round_context_releases_joint_slot_while_waiting_for_reverse_fill(self, patch_attrs) -> None:
        state = self._build_reverse_fill_state()
        config = state.config
        loop = ExecutionLoop(config, state)
        stop_signal = threading.Event()
        state.acquire_reverse_fill_sample('Worker-9')
        release_joint = MagicMock(side_effect=state.release_joint_sample)
        wait_runtime_change = MagicMock(side_effect=lambda **_kwargs: stop_signal.set() or True)
        state.release_joint_sample = release_joint
        state.wait_for_runtime_change = wait_runtime_change
        patch_attrs(
            (execution_loop_module, 'ensure_joint_psychometric_answer_plan', lambda _config: SimpleNamespace(sample_count=1)),
        )
        ready = loop._prepare_round_context(stop_signal, thread_name='Worker-1', session=None)
        assert not ready
        release_joint.assert_called_once_with('Worker-1')
        assert state.thread_progress['Worker-1'].status_text == '等待反填样本'
        wait_runtime_change.assert_called_once()

    def test_prepare_round_context_stops_when_reverse_fill_target_is_exhausted(self) -> None:
        state = self._build_reverse_fill_state(target_num=2)
        config = state.config
        loop = ExecutionLoop(config, state)
        stop_signal = threading.Event()
        state.acquire_reverse_fill_sample('Worker-9')
        state.mark_reverse_fill_submission_failed('Worker-9', max_retries=0)
        ready = loop._prepare_round_context(stop_signal, thread_name='Worker-1', session=None)
        assert not ready
        assert stop_signal.is_set()
        assert state.get_terminal_stop_snapshot()[0] == 'reverse_fill_exhausted'
        assert state.thread_progress['Worker-1'].status_text == '反填样本不足'
