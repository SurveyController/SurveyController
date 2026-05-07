from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest

from tencent.provider import submission


class _FakeDriver:
    def __init__(self) -> None:
        self.browser_name = "edge"
        self.session_id = "test-session"
        self.browser_pid: int | None = None
        self.browser_pids: set[int] = set()
        self.current_url = ""
        self.page = None
        self.page_source = ""
        self.title = ""

    def find_element(self, *_args, **_kwargs):
        raise RuntimeError("unused")

    def find_elements(self, *_args, **_kwargs):
        return []

    def execute_script(self, script: str, *args: Any):
        del script
        del args
        return None

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


class TencentSubmissionTests:
    def test_submit_reads_runtime_state_when_submit_button_missing(self, patch_attrs) -> None:
        driver = _FakeDriver()
        reads: list[str] = []
        patch_attrs(
            (submission, "_click_submit_button", lambda *_args, **_kwargs: False),
            (submission, "_is_headless_mode", lambda _ctx: True),
            (submission, "HEADLESS_SUBMIT_INITIAL_DELAY", 0.0),
            (submission, "HEADLESS_SUBMIT_CLICK_SETTLE_DELAY", 0.0),
            (submission, "peek_qq_runtime_state", lambda _driver: reads.append("peek") or SimpleNamespace(page_index=2, page_question_ids=["q1"])),
        )

        with pytest.raises(Exception, match="Submit button not found"):
            submission.submit(driver, ctx=None, stop_signal=threading.Event())

        assert reads == ["peek"]

    def test_runtime_context_summary_reads_runtime_state_for_status_helpers(self, patch_attrs) -> None:
        driver = _FakeDriver()
        reads: list[str] = []
        patch_attrs(
            (submission, "peek_qq_runtime_state", lambda _driver: reads.append("peek") or None),
        )

        assert not submission.consume_submission_success_signal(driver)
        assert not submission.is_device_quota_limit_page(driver)
        assert reads == ["peek", "peek"]
