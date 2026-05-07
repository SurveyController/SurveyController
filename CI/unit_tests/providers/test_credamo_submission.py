from unittest.mock import patch
from typing import Any

from credamo.provider import submission


class _FakeDriver:

    def __init__(self, body_text: str = '', current_url: str = 'https://example.com/form') -> None:
        self.browser_name = "edge"
        self.session_id = "test-session"
        self.browser_pid: int | None = None
        self.browser_pids: set[int] = set()
        self.body_text = body_text
        self.current_url = current_url
        self.page = None
        self.page_source = ""
        self.title = ""

    def execute_script(self, script: str, *args: Any):
        del args
        if 'document.body ? document.body.innerText' in script:
            return self.body_text
        if 'document.querySelectorAll' in script:
            return False
        return ''

    def find_element(self, *_args, **_kwargs):
        raise RuntimeError("unused")

    def find_elements(self, *_args, **_kwargs):
        return []

    def get(self, *_args, **_kwargs) -> None:
        return None

    def set_window_size(self, *_args, **_kwargs) -> None:
        return None

    def refresh(self) -> None:
        return None

    def mark_cleanup_done(self) -> bool:
        return True

    def quit(self) -> None:
        return None


class CredamoSubmissionTests:

    def test_submission_requires_verification_reads_runtime_state_when_feedback_hits(self, patch_attrs) -> None:
        driver = _FakeDriver(body_text='问卷正文')
        reads: list[str] = []
        patch_attrs(
            (submission, "peek_credamo_runtime_state", lambda _driver: reads.append("peek") or type("State", (), {"page_index": 3, "answered_question_keys": ["q1", "q2"]})()),
        )
        with patch('credamo.provider.submission._visible_feedback_text', return_value='请完成验证码验证后继续提交'):
            assert submission.submission_requires_verification(driver)
        assert reads == ['peek']

    def test_submission_validation_message_reads_runtime_state_when_driver_is_given(self, patch_attrs) -> None:
        driver = _FakeDriver(body_text='问卷正文')
        reads: list[str] = []
        patch_attrs(
            (submission, "peek_credamo_runtime_state", lambda _driver: reads.append("peek") or None),
        )
        assert "暂不支持自动处理" in submission.submission_validation_message(driver)
        assert reads == ['peek']

    def test_submission_requires_verification_ignores_selection_validation_feedback(self) -> None:
        driver = _FakeDriver(body_text='问卷正文')
        with patch('credamo.provider.submission._visible_feedback_text', return_value='本题至少选择2项后才能继续'):
            assert not submission.submission_requires_verification(driver)

    def test_submission_requires_verification_detects_real_verification_feedback(self) -> None:
        driver = _FakeDriver(body_text='问卷正文')
        with patch('credamo.provider.submission._visible_feedback_text', return_value='请完成验证码验证后继续提交'):
            assert submission.submission_requires_verification(driver)

    def test_submission_requires_verification_can_fall_back_to_body_text(self) -> None:
        driver = _FakeDriver(body_text='系统提示：请先完成滑块验证')
        with patch('credamo.provider.submission._visible_feedback_text', return_value=''):
            assert submission.submission_requires_verification(driver)

    def test_submission_requires_verification_does_not_treat_completion_text_as_verification(self) -> None:
        driver = _FakeDriver(body_text='感谢您的参与，答卷已经提交')
        with patch('credamo.provider.submission._visible_feedback_text', return_value=''):
            assert not submission.submission_requires_verification(driver)

    def test_is_completion_page_accepts_body_completion_text_without_special_url(self) -> None:
        driver = _FakeDriver(body_text='感谢您的宝贵时间，问卷已完成')
        with patch('credamo.provider.submission._visible_feedback_text', return_value=''):
            assert submission.is_completion_page(driver)

    def test_is_completion_page_ignores_completion_text_when_submit_controls_still_visible(self) -> None:
        driver = _FakeDriver(body_text='感谢您的参与')
        with patch('credamo.provider.submission._visible_feedback_text', return_value=''), patch('credamo.provider.submission._has_visible_action_controls', return_value=True):
            assert not submission.is_completion_page(driver)
