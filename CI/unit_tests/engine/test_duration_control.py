from __future__ import annotations

from types import SimpleNamespace

from software.core.modes import duration_control


class _Driver:
    def __init__(self, *, url: str = "", div_text: str = "", page_text: str = "", action_visible: bool = False) -> None:
        self.current_url = url
        self.div_text = div_text
        self.page_text = page_text
        self.action_visible = action_visible
        self.scripts: list[str] = []

    def find_element(self, by, value):
        if (by, value) == ("id", "divdsc") and self.div_text:
            return SimpleNamespace(is_displayed=lambda: True, text=self.div_text)
        raise RuntimeError("not found")

    def execute_script(self, script: str):
        self.scripts.append(script)
        if "innerText" in script:
            return self.page_text
        return self.action_visible


class DurationControlTests:
    def test_has_configured_answer_duration_accepts_any_positive_bound(self) -> None:
        assert not duration_control.has_configured_answer_duration((0, 0))
        assert not duration_control.has_configured_answer_duration(("bad",))
        assert duration_control.has_configured_answer_duration((0, 5))
        assert duration_control.has_configured_answer_duration((3, 0))

    def test_simulate_answer_duration_delay_skips_when_unconfigured(self, patch_attrs) -> None:
        slept: list[float] = []
        patch_attrs((duration_control.time, "sleep", lambda seconds: slept.append(seconds)))

        assert not duration_control.simulate_answer_duration_delay(answer_duration_range_seconds=(0, 0))
        assert slept == []

    def test_simulate_answer_duration_delay_uses_wait_on_stop_signal(self, make_mock_event, patch_attrs) -> None:
        stop_signal = make_mock_event(wait_return=True, is_set=True)
        patch_attrs(
            (duration_control, "_map_answer_seconds_to_proxy_minute", lambda _seconds: 1),
            (duration_control.random, "gauss", lambda center, _std: center),
        )

        interrupted = duration_control.simulate_answer_duration_delay(
            stop_signal=stop_signal,
            answer_duration_range_seconds=(20, 80),
        )

        assert interrupted is True
        waited = stop_signal.wait.call_args.args[0]
        assert 20 <= waited <= 59

    def test_simulate_answer_duration_delay_expands_equal_bounds_and_sleeps(self, patch_attrs) -> None:
        slept: list[float] = []
        patch_attrs(
            (duration_control, "_map_answer_seconds_to_proxy_minute", lambda _seconds: 0),
            (duration_control.random, "gauss", lambda center, _std: center),
            (duration_control.time, "sleep", lambda seconds: slept.append(seconds)),
        )

        assert not duration_control.simulate_answer_duration_delay(answer_duration_range_seconds=(10, 10))
        assert slept == [10.0]

    def test_completion_page_detects_complete_url_and_provider_signal(self, patch_attrs) -> None:
        assert duration_control.is_survey_completion_page(_Driver(url="https://example.com/complete"))

        patch_attrs(
            (
                duration_control,
                "_COMPLETION_MARKERS",
                duration_control._COMPLETION_MARKERS,
            )
        )

    def test_completion_page_detects_div_marker(self, patch_attrs) -> None:
        patch_attrs(
            (
                duration_control,
                "log_suppressed_exception",
                lambda *_args, **_kwargs: None,
            )
        )

        assert duration_control.is_survey_completion_page(_Driver(div_text="问卷提交成功"))

    def test_completion_page_uses_body_marker_only_when_no_action_button_visible(self) -> None:
        assert duration_control.is_survey_completion_page(_Driver(page_text="感谢您的参与", action_visible=False))
        assert not duration_control.is_survey_completion_page(_Driver(page_text="感谢您的参与", action_visible=True))
        assert not duration_control.is_survey_completion_page(_Driver(page_text="继续填写"))
