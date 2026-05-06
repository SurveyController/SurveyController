from __future__ import annotations
from unittest.mock import patch
from credamo.provider import runtime

class CredamoRuntimeWaitTests:

    def test_wait_for_question_roots_extends_when_page_is_loading_shell(self) -> None:
        monotonic_values = iter([0.0, 0.02, 0.04])
        with patch('credamo.provider.runtime._question_roots', side_effect=[[], ['root']]), patch('credamo.provider.runtime._page_loading_snapshot', return_value=('答卷', '载入中...')), patch('credamo.provider.runtime.time.monotonic', side_effect=lambda: next(monotonic_values)), patch('credamo.provider.runtime.time.sleep'):
            roots = runtime._wait_for_question_roots(object(), None, timeout_ms=10, loading_shell_extra_timeout_ms=10)
        assert roots == ['root']

    def test_wait_for_question_roots_returns_empty_after_extended_timeout(self) -> None:
        monotonic_values = iter([0.0, 0.02, 0.04, 0.06, 0.08])
        with patch('credamo.provider.runtime._question_roots', side_effect=[[], []]), patch('credamo.provider.runtime._page_loading_snapshot', return_value=('答卷', '载入中...')), patch('credamo.provider.runtime.time.monotonic', side_effect=lambda: next(monotonic_values)), patch('credamo.provider.runtime.time.sleep'):
            roots = runtime._wait_for_question_roots(object(), None, timeout_ms=10, loading_shell_extra_timeout_ms=10)
        assert roots == []
