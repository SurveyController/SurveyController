from __future__ import annotations
import threading
from types import SimpleNamespace
from unittest.mock import patch
from software.core.engine.failure_reason import FailureReason
from software.core.engine.submission_service import SubmissionOutcome, SubmissionService
from software.core.task import ExecutionConfig, ExecutionState

class SubmissionServiceTests:

    def test_wait_for_completion_page_stops_immediately_when_stop_requested(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider='wjx')
        state = ExecutionState(config=config)
        service = SubmissionService(config, state, make_stop_policy_mock())
        stop_signal = make_mock_event(is_set=True)
        with patch('software.core.engine.submission_service.time.time', side_effect=[0.0, 0.0]):
            completed = service._wait_for_completion_page(driver=SimpleNamespace(current_url='https://example.com/form'), stop_signal=stop_signal, max_wait_seconds=3, poll_interval=0.1)
        assert not completed

    def test_finalize_after_submit_returns_fast_success_when_completion_is_detected_immediately(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=True, random_proxy_ip_enabled=True, survey_provider='wjx')
        state = ExecutionState(config=config)
        stop_policy = make_stop_policy_mock(record_success_return=False)
        service = SubmissionService(config, state, stop_policy)
        stop_signal = make_mock_event()
        driver = SimpleNamespace(_session_proxy_address='http://1.1.1.1:8000', _thread_name='Worker-1')
        with patch.object(service, '_detect_completion_once', return_value=True), patch('software.core.engine.submission_service.random.uniform', return_value=0.2):
            outcome = service.finalize_after_submit(driver, stop_signal=stop_signal, gui_instance=None, thread_name='Worker-1')
        assert outcome.status == 'success'
        assert outcome.completion_detected
        assert outcome.should_rotate_proxy
        assert state.is_successful_proxy_address('http://1.1.1.1:8000')
        stop_policy.record_success.assert_called_once_with(stop_signal, thread_name='Worker-1')
        assert stop_signal.wait.call_count >= 2
        assert stop_signal.wait.call_args_list[0].args[0] == 0.2
        assert stop_signal.wait.call_args_list[1].args[0] == 0.25

    def test_finalize_after_submit_marks_submit_proxy_address_when_present(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=False, random_proxy_ip_enabled=True, survey_provider='wjx')
        state = ExecutionState(config=config)
        stop_policy = make_stop_policy_mock(record_success_return=False)
        service = SubmissionService(config, state, stop_policy)
        stop_signal = make_mock_event()
        driver = SimpleNamespace(current_url='https://example.com/complete', _session_proxy_address='http://1.1.1.1:8000', _submit_proxy_address='http://2.2.2.2:8000', _thread_name='Worker-1')
        with patch('software.core.engine.submission_service._provider_submission_requires_verification', return_value=False), patch('software.core.engine.submission_service._provider_wait_for_submission_verification', return_value=False), patch.object(service, '_wait_for_completion_page', side_effect=[False, False]), patch('software.core.engine.submission_service.random.uniform', return_value=0.2), patch('software.core.engine.submission_service.time.sleep'):
            outcome = service.finalize_after_submit(driver, stop_signal=stop_signal, gui_instance=None, thread_name='Worker-1')
        assert outcome.status == 'success'
        assert state.snapshot_successful_proxy_addresses() == {'http://1.1.1.1:8000', 'http://2.2.2.2:8000'}

    def test_finalize_after_submit_returns_aborted_when_user_stops_during_initial_wait(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider='wjx')
        state = ExecutionState(config=config)
        stop_policy = make_stop_policy_mock()
        service = SubmissionService(config, state, stop_policy)
        stop_signal = make_mock_event(wait_return=True)
        driver = object()
        with patch('software.core.engine.submission_service.random.uniform', return_value=0.2):
            outcome = service.finalize_after_submit(driver, stop_signal=stop_signal, gui_instance=None, thread_name='Worker-1')
        assert outcome.status == 'aborted'
        assert outcome.failure_reason == FailureReason.USER_STOPPED
        assert outcome.should_stop
        stop_policy.record_success.assert_not_called()
        stop_policy.record_failure.assert_not_called()

    def test_finalize_after_submit_wjx_prefers_fast_completion_before_verification_wait(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider='wjx')
        state = ExecutionState(config=config)
        stop_policy = make_stop_policy_mock(record_success_return=False)
        service = SubmissionService(config, state, stop_policy)
        stop_signal = make_mock_event()
        with patch.object(service, '_detect_completion_once', return_value=True) as detect_mock, patch('software.core.engine.submission_service._provider_wait_for_submission_verification') as verification_wait_mock, patch('software.core.engine.submission_service._provider_submission_requires_verification') as verification_mock, patch('software.core.engine.submission_service.random.uniform', return_value=0.2), patch('software.core.engine.submission_service.time.sleep'):
            outcome = service.finalize_after_submit(object(), stop_signal=stop_signal, gui_instance=None, thread_name='Worker-1')
        assert outcome.status == 'success'
        assert outcome.completion_detected
        detect_mock.assert_called_once()
        verification_wait_mock.assert_not_called()
        verification_mock.assert_not_called()
        stop_policy.record_success.assert_called_once_with(stop_signal, thread_name='Worker-1')

    def test_finalize_after_submit_wjx_uses_short_completion_wait_before_verification(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider='wjx')
        state = ExecutionState(config=config)
        stop_policy = make_stop_policy_mock(record_success_return=True)
        service = SubmissionService(config, state, stop_policy)
        stop_signal = make_mock_event()
        with patch.object(service, '_detect_completion_once', return_value=False), patch.object(service, '_wait_for_completion_page', return_value=True) as wait_mock, patch('software.core.engine.submission_service._provider_submission_requires_verification') as verification_mock, patch('software.core.engine.submission_service._provider_wait_for_submission_verification') as verification_wait_mock, patch('software.core.engine.submission_service.random.uniform', return_value=0.2), patch('software.core.engine.submission_service.time.sleep'):
            outcome = service.finalize_after_submit(object(), stop_signal=stop_signal, gui_instance=None, thread_name='Worker-1')
        assert outcome.status == 'success'
        assert outcome.completion_detected
        wait_mock.assert_called_once()
        assert wait_mock.call_args.args[2] == 1.6
        verification_mock.assert_not_called()
        verification_wait_mock.assert_not_called()
        stop_policy.record_success.assert_called_once_with(stop_signal, thread_name='Worker-1')

    def test_finalize_after_submit_marks_failure_when_completion_never_appears(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider='wjx')
        state = ExecutionState(config=config)
        stop_policy = make_stop_policy_mock(record_failure_return=True)
        service = SubmissionService(config, state, stop_policy)
        stop_signal = make_mock_event()
        driver = SimpleNamespace(current_url='https://example.com/form')
        with patch('software.core.engine.submission_service._provider_submission_requires_verification', return_value=False), patch('software.core.engine.submission_service._provider_wait_for_submission_verification', return_value=False), patch.object(service, '_wait_for_completion_page', side_effect=[False, False]), patch('software.core.engine.submission_service.duration_control.is_survey_completion_page', return_value=False), patch('software.core.engine.submission_service.random.uniform', return_value=0.2):
            outcome = service.finalize_after_submit(driver, stop_signal=stop_signal, gui_instance=None, thread_name='Worker-1')
        assert outcome.status == 'failure'
        assert outcome.failure_reason == FailureReason.FILL_FAILED
        assert not outcome.completion_detected
        assert outcome.should_stop
        stop_policy.record_failure.assert_called_once()
        assert not bool(stop_policy.record_failure.call_args.kwargs.get('consume_reverse_fill_attempt', True))

    def test_finalize_after_submit_treats_complete_url_as_success_after_waits(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider='wjx')
        state = ExecutionState(config=config)
        stop_policy = make_stop_policy_mock(record_success_return=True)
        service = SubmissionService(config, state, stop_policy)
        stop_signal = make_mock_event()
        driver = SimpleNamespace(current_url='https://example.com/complete')
        with patch('software.core.engine.submission_service._provider_submission_requires_verification', return_value=False), patch('software.core.engine.submission_service._provider_wait_for_submission_verification', return_value=False), patch.object(service, '_wait_for_completion_page', side_effect=[False, False]), patch('software.core.engine.submission_service.random.uniform', return_value=0.2), patch('software.core.engine.submission_service.time.sleep'):
            outcome = service.finalize_after_submit(driver, stop_signal=stop_signal, gui_instance=None, thread_name='Worker-1')
        assert outcome.status == 'success'
        assert outcome.completion_detected
        assert outcome.should_stop
        stop_policy.record_success.assert_called_once_with(stop_signal, thread_name='Worker-1')

    def test_finalize_after_submit_treats_provider_completion_page_as_success_after_waits(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider='wjx')
        state = ExecutionState(config=config)
        stop_policy = make_stop_policy_mock(record_success_return=False)
        service = SubmissionService(config, state, stop_policy)
        stop_signal = make_mock_event()
        driver = SimpleNamespace(current_url='https://example.com/form')
        with patch('software.core.engine.submission_service._provider_submission_requires_verification', return_value=False), patch('software.core.engine.submission_service._provider_wait_for_submission_verification', return_value=False), patch.object(service, '_wait_for_completion_page', side_effect=[False, False]), patch('software.core.engine.submission_service.duration_control.is_survey_completion_page', return_value=True), patch('software.core.engine.submission_service.random.uniform', return_value=0.2), patch('software.core.engine.submission_service.time.sleep'):
            outcome = service.finalize_after_submit(driver, stop_signal=stop_signal, gui_instance=None, thread_name='Worker-1')
        assert outcome.status == 'success'
        assert outcome.completion_detected
        assert not outcome.should_stop
        stop_policy.record_success.assert_called_once_with(stop_signal, thread_name='Worker-1')

    def test_finalize_after_submit_reports_submission_verification(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(survey_provider='qq')
        state = ExecutionState(config=config)
        stop_policy = make_stop_policy_mock(record_failure_return=True)
        service = SubmissionService(config, state, stop_policy)
        stop_signal = make_mock_event()
        driver = object()
        with patch('software.core.engine.submission_service._provider_submission_requires_verification', return_value=True), patch('software.core.engine.submission_service._provider_submission_validation_message', return_value='命中腾讯安全验证'), patch('software.core.engine.submission_service._provider_handle_submission_verification_detected') as handle_mock, patch('software.core.engine.submission_service.random.uniform', return_value=0.2):
            outcome = service.finalize_after_submit(driver, stop_signal=stop_signal, gui_instance=object(), thread_name='Worker-1')
        assert outcome.status == 'failure'
        assert outcome.failure_reason == FailureReason.SUBMISSION_VERIFICATION_REQUIRED
        assert state.get_terminal_stop_snapshot()[0] == 'submission_verification'
        assert outcome.should_stop
        handle_mock.assert_called_once()
        assert not bool(stop_policy.record_failure.call_args.kwargs.get('consume_reverse_fill_attempt', True))

    def test_finalize_after_submit_returns_secondary_verification_outcome_after_waits_for_non_wjx(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider='credamo')
        state = ExecutionState(config=config)
        stop_policy = make_stop_policy_mock()
        service = SubmissionService(config, state, stop_policy)
        stop_signal = make_mock_event()
        expected = SubmissionOutcome(status='failure', failure_reason=FailureReason.SUBMISSION_VERIFICATION_REQUIRED, message='命中智能验证', completion_detected=False, should_stop=True, should_rotate_proxy=False)
        with patch('software.core.engine.submission_service._provider_submission_requires_verification', return_value=False), patch.object(service, '_check_submission_verification_after_submit', side_effect=[None, expected]), patch.object(service, '_wait_for_completion_page', side_effect=[False, False]), patch('software.core.engine.submission_service.random.uniform', return_value=0.2):
            outcome = service.finalize_after_submit(SimpleNamespace(current_url='https://example.com/form'), stop_signal=stop_signal, gui_instance=None, thread_name='Worker-1')
        assert outcome.status == 'failure'
        assert outcome.failure_reason == FailureReason.SUBMISSION_VERIFICATION_REQUIRED
        stop_policy.record_failure.assert_not_called()

    def test_check_submission_verification_after_submit_ignores_waiter_exception(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider='wjx')
        state = ExecutionState(config=config)
        service = SubmissionService(config, state, make_stop_policy_mock())
        stop_signal = make_mock_event()
        with patch('software.core.engine.submission_service._provider_wait_for_submission_verification', side_effect=RuntimeError('boom')):
            outcome = service._check_submission_verification_after_submit(driver=object(), stop_signal=stop_signal, gui_instance=None, thread_name='Worker-1')
        assert outcome is None
