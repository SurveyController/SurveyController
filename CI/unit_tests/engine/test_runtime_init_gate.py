from __future__ import annotations
from threading import Event, Lock
from software.core.task import ExecutionConfig
from software.core.task import ProxyLease
from software.io.config import RuntimeConfig
from software.providers.contracts import SurveyQuestionMeta
from software.network.proxy.pool.free_pool import FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS
from software.ui.controller.run_controller_parts.runtime_init_gate import RunControllerInitializationMixin, _extract_startup_service_warnings, _parse_status_page_monitor_names
from software.ui.controller.run_controller_parts.runtime_preparation import PreparedExecutionArtifacts
from software.ui.controller.run_controller_parts.runtime_random_ip import RunControllerRandomIPMixin

class _DummyInitGate(RunControllerInitializationMixin):

    def __init__(self) -> None:
        self.stop_event = Event()
        self._initializing = True
        self._starting = True
        self.running = True
        self.worker_threads = [object()]
        self._execution_state = object()
        self._init_stage_text = '正在初始化'
        self._init_steps = []
        self._init_completed_steps = set()
        self._init_current_step_key = ''
        self._init_gate_stop_event = Event()
        self._status_timer = _FakeTimer()
        self._prepared_execution_artifacts = None
        self._startup_status_check_lock = Lock()
        self._startup_status_check_active = False
        self._startup_service_warnings: list[str] = []
        self._free_proxy_pool: list = []
        self._free_proxy_pool_built_at = 0.0
        self._free_proxy_pool_build_active = False
        self._free_proxy_pool_stop_event = None
        self.started_workers: list[tuple[RuntimeConfig, list, bool]] = []
        self.dispatched_callbacks: list[object] = []
        self.emit_status_calls = 0
        self.startup_hint_events: list[tuple[str, str, int]] = []
        self.survey_title = '测试问卷'
        self.custom_confirm_dialog_handler = None
        self.confirm_dialog_handler = None
        self.run_state_events: list[bool] = []
        self.status_events: list[tuple[str, int, int]] = []
        self.thread_progress_events: list[dict] = []
        self.run_failed_events: list[str] = []
        self.runStateChanged = _FakeSignal(self.run_state_events)
        self.statusUpdated = _FakeSignal(self.status_events)
        self.threadProgressUpdated = _FakeSignal(self.thread_progress_events)
        self.runFailed = _FakeSignal(self.run_failed_events)
        self.startupHintEmitted = _FakeSignal(self.startup_hint_events)

    def _start_workers_with_proxy_pool(self, config: RuntimeConfig, proxy_pool: list, *, emit_run_state: bool=True) -> None:
        self.started_workers.append((config, list(proxy_pool), emit_run_state))

    def _emit_status(self) -> None:
        self.emit_status_calls += 1

    def _dispatch_to_ui_async(self, callback) -> None:
        self.dispatched_callbacks.append(callback)
        callback()

class _FakeSignal:

    def __init__(self, events: list) -> None:
        self.events = events

    def emit(self, *args) -> None:
        if len(args) == 1:
            self.events.append(args[0])
        else:
            self.events.append(args)

class _FakeTimer:

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

class _FakeThread:

    def __init__(self, *, target=None, args=(), daemon: bool=False, name: str='') -> None:
        self.target = target
        self.args = args
        self.daemon = daemon
        self.name = name
        self.started = False

    def start(self) -> None:
        self.started = True


class _ImmediateThread:

    def __init__(self, target=None, args=(), **_kwargs) -> None:
        self.target = target
        self.args = args

    def start(self) -> None:
        if self.target is not None:
            self.target(*self.args)


class _DummyRandomIP(RunControllerRandomIPMixin):

    def __init__(self) -> None:
        self._free_proxy_pool = []
        self._free_proxy_pool_built_at = 0.0
        self._free_proxy_pool_build_active = False
        self._free_proxy_pool_stop_event = None
        self.progress_events: list[dict] = []
        self.finished_events: list[tuple[bool, str, int]] = []
        self.freeProxyPoolProgressChanged = _FakeSignal(self.progress_events)
        self.freeProxyPoolBuildFinished = _FakeSignal(self.finished_events)

    def _dispatch_to_ui_async(self, callback) -> None:
        callback()

    def notify_random_ip_loading(self, loading: bool, message: str = '') -> None:
        _ = loading, message

class RuntimeInitGateTests:

    def setup_method(self, _method) -> None:
        self.mixin = _DummyInitGate()

    def test_cancel_initialization_resets_ui_to_idle_state(self) -> None:
        self.mixin._cancel_initialization_startup()
        assert not self.mixin.running
        assert not self.mixin._starting
        assert not self.mixin._initializing
        assert self.mixin.worker_threads == []
        assert self.mixin._execution_state is None
        assert self.mixin._status_timer.stopped
        assert self.mixin.run_state_events == [False]
        assert self.mixin.status_events == [('已取消启动', 0, 0)]
        assert self.mixin.thread_progress_events[-1] == {'threads': [], 'target': 0, 'num_threads': 0, 'per_thread_target': 0, 'initializing': False}

    def test_parse_status_page_monitor_names_reads_public_group_monitors(self) -> None:
        payload = {'publicGroupList': [{'monitorList': [{'id': 12, 'name': '随机ip提取'}, {'id': 13, 'name': '免费AI填空'}]}]}
        assert _parse_status_page_monitor_names(payload) == {12: '随机ip提取', 13: '免费AI填空'}

    def test_extract_startup_service_warnings_only_flags_non_ok_status(self) -> None:
        payload = {'heartbeatList': {'12': [{'status': 0, 'msg': '接口超时', 'time': '2026-04-23 11:00:00'}], '13': [{'status': 1, 'msg': '', 'time': '2026-04-23 11:00:30'}]}}
        warnings = _extract_startup_service_warnings(payload, {12: '随机IP提取', 13: '免费AI填空'}, {12: '随机ip提取', 13: '免费AI填空'})
        assert warnings == ['随机ip提取 当前状态异常（接口超时；最近时间：2026-04-23 11:00:00）']

    def test_build_initialization_logs_marks_stage_and_completion(self) -> None:
        self.mixin._init_stage_text = '正在检查浏览器'
        self.mixin._init_steps = [{'key': 'probe', 'label': '浏览器快检'}, {'key': 'warmup', 'label': '预热'}]
        self.mixin._init_completed_steps = {'probe'}
        self.mixin._init_current_step_key = 'warmup'
        lines = self.mixin._build_initialization_logs()
        assert lines == ['当前阶段：正在检查浏览器', '[√] 浏览器快检', '[>] 预热']

    def test_start_with_initialization_gate_bypasses_gate_for_single_thread(self) -> None:
        config = RuntimeConfig()
        config.headless_mode = True
        config.threads = 1
        self.mixin._start_with_initialization_gate(config, proxy_pool=['proxy-a'])
        assert len(self.mixin.started_workers) == 1
        assert self.mixin.started_workers[0][1] == ['proxy-a']
        assert self.mixin.started_workers[0][2]

    def test_start_with_initialization_gate_starts_workers_directly(self) -> None:
        config = RuntimeConfig()
        config.headless_mode = True
        config.threads = 2
        self.mixin._start_with_initialization_gate(config, proxy_pool=['proxy-a'])
        assert len(self.mixin.started_workers) == 1
        assert self.mixin.started_workers[0][1] == ['proxy-a']
        assert self.mixin.started_workers[0][2]

    def test_start_with_initialization_gate_prefetches_random_proxy_pool_before_workers(self, monkeypatch) -> None:
        config = RuntimeConfig()
        config.headless_mode = True
        config.random_ip_enabled = True
        config.threads = 4
        config.target = 10
        config.proxy_source = 'free_pool'
        fetched = [ProxyLease(address='http://1.1.1.1:8000', source='free_pool')]
        captured = {}

        def fake_prefetch(expected_count, proxy_api_url=None, stop_signal=None, **_kwargs):
            captured['expected_count'] = expected_count
            captured['proxy_api_url'] = proxy_api_url
            captured['stop_signal'] = stop_signal
            captured.update(_kwargs)
            return fetched

        monkeypatch.setattr(
            'software.ui.controller.run_controller_parts.runtime_init_gate.prefetch_proxy_pool',
            fake_prefetch,
        )
        monkeypatch.setattr(
            'software.ui.controller.run_controller_parts.runtime_init_gate.threading.Thread',
            _ImmediateThread,
        )

        self.mixin._start_with_initialization_gate(config, proxy_pool=[])

        assert len(self.mixin.started_workers) == 1
        assert self.mixin.started_workers[0][1] == fetched
        assert captured['expected_count'] == 10
        assert captured['target_url'] == ''
        assert captured['probe_timeout_ms'] == FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS

    def test_initial_proxy_pool_target_count_prefetches_extra_for_local_pools(self) -> None:
        config = RuntimeConfig()
        config.random_ip_enabled = True
        config.proxy_source = 'free_pool'
        config.threads = 4
        config.target = 50
        assert self.mixin._initial_proxy_pool_target_count(config) == 16

        config.proxy_source = 'iplist'
        config.threads = 30
        config.target = 200
        assert self.mixin._initial_proxy_pool_target_count(config) == 80

    def test_start_with_initialization_gate_reuses_prebuilt_free_pool(self, monkeypatch) -> None:
        config = RuntimeConfig()
        config.random_ip_enabled = True
        config.proxy_source = 'free_pool'
        config.threads = 4
        config.target = 10
        prebuilt = [ProxyLease(address='http://8.8.8.8:8000', source='free_pool')]
        self.mixin._free_proxy_pool = list(prebuilt)
        monkeypatch.setattr(
            'software.ui.controller.run_controller_parts.runtime_init_gate.threading.Thread',
            _ImmediateThread,
        )

        self.mixin._start_with_initialization_gate(config, proxy_pool=[])

        assert len(self.mixin.started_workers) == 1
        assert self.mixin.started_workers[0][1] == prebuilt
        assert self.mixin._free_proxy_pool == []

    def test_prepare_engine_state_clones_prepared_template_and_injects_proxy_pool(self) -> None:
        template = ExecutionConfig(survey_provider='qq', num_threads=3, random_proxy_ip_enabled=True, questions_metadata={1: SurveyQuestionMeta(num=1, title='Q1')}, single_prob=[[1.0, 0.0]])
        self.mixin._prepared_execution_artifacts = PreparedExecutionArtifacts(execution_config_template=template, survey_provider='qq', question_entries=[], questions_info=[SurveyQuestionMeta(num=1, title='Q1')], reverse_fill_spec=None)
        execution_config, execution_state = self.mixin._prepare_engine_state(['proxy-a'])
        assert execution_config is not template
        assert execution_config.proxy_ip_pool == ['proxy-a']
        assert execution_config.questions_metadata[1].title == 'Q1'
        assert execution_state.config == execution_config
        template.single_prob[0][0] = 0.0
        assert execution_config.single_prob[0][0] == 1.0


class RuntimeRandomIPTests:

    def test_build_free_proxy_pool_async_records_pool_and_emits_progress(self, monkeypatch) -> None:
        mixin = _DummyRandomIP()
        fetched = [ProxyLease(address='http://1.1.1.1:8000', source='free_pool')]
        captured = {}

        def fake_fetch(**kwargs):
            captured.update(kwargs)
            kwargs['progress_callback']({'stage': 'done', 'total': 1, 'checked': 1, 'passed': 1})
            return fetched

        monkeypatch.setattr(
            'software.ui.controller.run_controller_parts.runtime_random_ip.fetch_free_proxy_batch',
            fake_fetch,
        )
        monkeypatch.setattr(
            'software.ui.controller.run_controller_parts.runtime_random_ip.threading.Thread',
            lambda target, **_kwargs: type('ImmediateThread', (), {'start': lambda self: target()})(),
        )

        assert mixin.build_free_proxy_pool_async(
            expected_count=1,
            max_workers=200,
            candidate_count=1600,
            fetch_workers=120,
        )
        assert mixin._free_proxy_pool == fetched
        assert captured['candidate_count'] == 1600
        assert captured['fetch_workers'] == 120
        assert captured['max_workers'] == 200
        assert captured['target_url'] == ''
        assert mixin.progress_events[-1]['passed'] == 1
        assert mixin.finished_events == [(True, '免费代理池已构建：1 个可用代理', 1)]
