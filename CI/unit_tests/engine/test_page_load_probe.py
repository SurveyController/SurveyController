from __future__ import annotations
import software.core.engine.page_load_probe as probe_module
from software.core.engine.page_load_probe import PAGE_LOAD_PROBE_ANSWERABLE, PAGE_LOAD_PROBE_BUSINESS_PAGE, PAGE_LOAD_PROBE_PROXY_UNUSABLE, PageLoadProbeResult, probe_loaded_page, wait_for_page_probe

class _ProbeDriver:

    def __init__(self, *, script_results: dict[str, object] | None=None):
        self.script_results = dict(script_results or {})
        self.execute_calls: list[str] = []

    def execute_script(self, script: str, *_args):
        self.execute_calls.append(script)
        if "const hasQuestions = Array.from(document.querySelectorAll('.question-list > section.question')).some(visible);" in script:
            return self.script_results.get('qq', {})
        if 'const selectors = {' in script:
            return self.script_results.get('generic', {})
        if "const title = document.title || '';" in script and "const bodyText = (document.body && document.body.innerText) || '';" in script:
            return self.script_results.get('snapshot', {})
        return self.script_results.get('default')

class PageLoadProbeTests:

    def test_probe_loaded_page_marks_wjx_questionnaire_as_answerable(self, patch_attrs) -> None:
        driver = _ProbeDriver()
        patch_attrs(
            (probe_module, '_provider_is_device_quota_limit_page', lambda *_args, **_kwargs: False),
            (probe_module, '_page_looks_like_wjx_questionnaire', lambda *_args, **_kwargs: True),
        )
        result = probe_loaded_page(driver, provider='wjx')
        assert result.status == PAGE_LOAD_PROBE_ANSWERABLE
        assert result.detail == 'wjx_questionnaire'

    def test_probe_loaded_page_marks_qq_questionnaire_as_answerable(self, patch_attrs) -> None:
        driver = _ProbeDriver(script_results={'qq': {'title': '腾讯问卷', 'bodyText': '开始填写', 'readyState': 'complete', 'hasQuestions': True, 'hasInputs': False, 'hasActions': True}})
        patch_attrs(
            (probe_module, '_provider_is_device_quota_limit_page', lambda *_args, **_kwargs: False),
            (probe_module.timed_mode, '_page_status', lambda *_args, **_kwargs: (False, False, False, '')),
        )
        result = probe_loaded_page(driver, provider='qq')
        assert result.status == PAGE_LOAD_PROBE_ANSWERABLE
        assert result.detail == 'qq_dom_ready'

    def test_probe_loaded_page_marks_device_quota_as_business_page(self, patch_attrs) -> None:
        driver = _ProbeDriver()
        patch_attrs(
            (probe_module, '_provider_is_device_quota_limit_page', lambda *_args, **_kwargs: True),
        )
        result = probe_loaded_page(driver, provider='wjx')
        assert result.status == PAGE_LOAD_PROBE_BUSINESS_PAGE
        assert result.detail == 'device_quota_limit'

    def test_probe_loaded_page_marks_blank_shell_as_proxy_unusable(self, patch_attrs) -> None:
        driver = _ProbeDriver(script_results={'generic': {'title': '', 'bodyText': '', 'readyState': 'interactive', 'hasQuestionBlock': False, 'hasInputs': False, 'hasActions': False}})
        patch_attrs(
            (probe_module, '_provider_is_device_quota_limit_page', lambda *_args, **_kwargs: False),
            (probe_module, '_page_looks_like_wjx_questionnaire', lambda *_args, **_kwargs: False),
            (probe_module.timed_mode, '_page_status', lambda *_args, **_kwargs: (False, False, False, '')),
        )
        result = probe_loaded_page(driver, provider='wjx')
        assert result.status == PAGE_LOAD_PROBE_PROXY_UNUSABLE
        assert result.detail == 'blank_page'
        assert result.retryable

    def test_probe_loaded_page_marks_proxy_error_page_as_proxy_unusable(self, patch_attrs) -> None:
        driver = _ProbeDriver(script_results={'qq': {'title': "This site can't be reached", 'bodyText': 'ERR_PROXY_CONNECTION_FAILED', 'readyState': 'complete', 'hasQuestions': False, 'hasInputs': False, 'hasActions': False}})
        patch_attrs(
            (probe_module, '_provider_is_device_quota_limit_page', lambda *_args, **_kwargs: False),
            (probe_module.timed_mode, '_page_status', lambda *_args, **_kwargs: (False, False, False, '')),
        )
        result = probe_loaded_page(driver, provider='qq')
        assert result.status == PAGE_LOAD_PROBE_PROXY_UNUSABLE
        assert result.detail == 'proxy_error_page'
        assert not result.retryable

    def test_wait_for_page_probe_polls_until_answerable(self, patch_attrs) -> None:
        probe_results = iter([PageLoadProbeResult(PAGE_LOAD_PROBE_PROXY_UNUSABLE, detail='blank_page', retryable=True), PageLoadProbeResult(PAGE_LOAD_PROBE_ANSWERABLE, detail='generic_ready')])
        patch_attrs(
            (probe_module, 'probe_loaded_page', lambda *_args, **_kwargs: next(probe_results)),
        )
        result = wait_for_page_probe(object(), provider='wjx', timeout_ms=200, poll_interval_seconds=0.01)
        assert result.status == PAGE_LOAD_PROBE_ANSWERABLE
        assert result.detail == 'generic_ready'
