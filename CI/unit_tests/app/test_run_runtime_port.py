from __future__ import annotations

import threading

from software.application.runtime_port import RunRuntimePort


class _FakeSubmissionHandler:
    def __init__(self) -> None:
        self.calls: list[threading.Event | None] = []

    def __call__(self, *, stop_signal: threading.Event | None = None) -> None:
        self.calls.append(stop_signal)


def test_random_ip_submission_forwards_stop_signal_as_keyword() -> None:
    stop_signal = threading.Event()
    handler = _FakeSubmissionHandler()
    port = RunRuntimePort(
        stop_signal=threading.Event(),
        notify_random_ip_loading=lambda *_args, **_kwargs: None,
        handle_random_ip_submission=handler,
    )

    port.on_random_ip_submission(stop_signal)

    assert handler.calls == [stop_signal]


def test_pause_and_loading_controls_forward_state() -> None:
    loading: list[tuple[bool, str]] = []
    port = RunRuntimePort(
        stop_signal=threading.Event(),
        notify_random_ip_loading=lambda active, message: loading.append((active, message)),
        handle_random_ip_submission=lambda **_kwargs: None,
    )

    port.pause_run("维护中")
    assert port.is_paused()
    assert port.get_pause_reason() == "维护中"
    stop_signal = threading.Event()
    stop_signal.set()
    port.wait_if_paused(stop_signal)
    port.on_random_ip_loading_changed(True, "正在获取")
    port.resume_run()

    assert not port.is_paused()
    assert port.get_pause_reason() == ""
    assert loading == [(True, "正在获取")]
