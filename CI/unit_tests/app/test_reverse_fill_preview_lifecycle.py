from __future__ import annotations

from types import SimpleNamespace

from software.ui.pages.workbench.reverse_fill.preview import (
    PreviewCancellation,
    cancel_preview,
    preview_progress,
)


class _Button:
    def __init__(self) -> None:
        self.enabled = True
        self.text = "取消预检"

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def setText(self, text: str) -> None:
        self.text = text


class _Label:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = text


def test_preview_cancel_requests_cooperative_stop_without_waiting() -> None:
    control = PreviewCancellation()
    cancel_event = control.begin()
    page = SimpleNamespace(
        _preview_in_flight=True,
        _preview_cancel_requested=False,
        _preview_pending=(2, {}),
        _preview_cancellation=control,
        _preview_stage="reading",
        cancel_preview_btn=_Button(),
        state_hint_label=_Label(),
    )

    cancel_preview(page)

    assert cancel_event.is_set()
    assert page._preview_cancel_requested
    assert page._preview_pending is None
    assert not page.cancel_preview_btn.enabled
    assert page.cancel_preview_btn.text == "正在取消..."
    assert page.state_hint_label.text == "当前 Excel 读取结束后会停止预检"


def test_preview_progress_ignores_stale_result_and_shows_sample_count() -> None:
    page = SimpleNamespace(
        _preview_generation=4,
        _preview_cancel_requested=False,
        _preview_in_flight=True,
        _preview_stage="",
        detected_format_label=_Label(),
        state_hint_label=_Label(),
    )

    preview_progress(page, 3, "samples", 1, 2)
    assert page.detected_format_label.text == ""

    preview_progress(page, 4, "samples", 1, 2)
    assert page._preview_stage == "samples"
    assert page.detected_format_label.text == "正在校验样本 (1/2)"
