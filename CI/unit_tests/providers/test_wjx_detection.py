from __future__ import annotations

import threading

from wjx.provider import detection


class _Element:
    def __init__(self, topic: str | None = None) -> None:
        self.topic = topic

    def get_attribute(self, name: str):
        return self.topic if name == "topic" else None


class _Driver:
    def __init__(self, elements: dict[tuple[object, str], list[object]] | None = None, scripts: list[object] | None = None) -> None:
        self.elements = elements or {}
        self.scripts = list(scripts or [])

    def find_elements(self, by, selector: str):
        return list(self.elements.get((by, selector), []))

    def execute_script(self, _script: str):
        if not self.scripts:
            return {}
        value = self.scripts.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class WjxDetectionTests:
    def test_count_questions_by_fieldset_counts_numeric_topics_per_page(self) -> None:
        driver = _Driver(
            {
                (detection.By.XPATH, '//*[@id="divQuestion"]/fieldset'): [object(), object()],
                (detection.By.XPATH, '//*[@id="fieldset1"]/div'): [_Element("1"), _Element("x"), _Element("2")],
                (detection.By.XPATH, '//*[@id="fieldset2"]/div'): [_Element("3")],
            }
        )

        assert detection._count_questions_by_fieldset(driver) == [2, 1]

    def test_count_questions_by_script_handles_payload_and_bad_values(self) -> None:
        driver = _Driver(scripts=[{"pages": [2, "3", -1, "bad"], "inputs": "5"}])
        assert detection._count_questions_by_script(driver) == ([], 0, 5)

        driver = _Driver(scripts=[{"pages": [2, "3"], "inputs": "5"}])
        assert detection._count_questions_by_script(driver) == ([2, 3], 5, 5)

        driver = _Driver(scripts=[RuntimeError("js failed")])
        assert detection._count_questions_by_script(driver) == ([], 0, 0)

    def test_detect_prefers_fieldset_counts_after_start_button(self, patch_attrs, make_mock_event) -> None:
        stop_signal = make_mock_event()
        driver = _Driver(
            {
                (detection.By.XPATH, '//*[@id="divQuestion"]/fieldset'): [object()],
                (detection.By.XPATH, '//*[@id="fieldset1"]/div'): [_Element("1"), _Element("2")],
            }
        )
        patch_attrs(
            (detection, "dismiss_resume_dialog_if_present", lambda *_args, **_kwargs: None),
            (detection, "try_click_start_answer_button", lambda *_args, **_kwargs: True),
        )

        assert detection.detect(driver, stop_signal=stop_signal) == [2]
        stop_signal.wait.assert_called_once_with(0.5)

    def test_detect_uses_script_fallback_and_delayed_retry(self, patch_attrs) -> None:
        patch_attrs(
            (detection, "dismiss_resume_dialog_if_present", lambda *_args, **_kwargs: None),
            (detection, "try_click_start_answer_button", lambda *_args, **_kwargs: False),
            (detection.time, "sleep", lambda *_args: None),
        )
        driver = _Driver(
            {
                (detection.By.XPATH, '//*[@id="divQuestion"]/fieldset'): [],
            },
            scripts=[{"pages": [], "inputs": 4}, {"pages": [4], "inputs": 4}],
        )

        assert detection.detect(driver) == [4]

    def test_detect_returns_one_when_only_inputs_found_and_respects_stopped_signal(self, patch_attrs) -> None:
        patch_attrs(
            (detection, "dismiss_resume_dialog_if_present", lambda *_args, **_kwargs: None),
            (detection, "try_click_start_answer_button", lambda *_args, **_kwargs: False),
            (detection.time, "sleep", lambda *_args: None),
        )
        driver = _Driver(
            {
                (detection.By.XPATH, '//*[@id="divQuestion"]/fieldset'): [],
            },
            scripts=[{"pages": [], "inputs": 3}, {"pages": [], "inputs": 3}],
        )
        assert detection.detect(driver) == [1]

        stopped = threading.Event()
        stopped.set()
        driver = _Driver({(detection.By.XPATH, '//*[@id="divQuestion"]/fieldset'): []}, scripts=[{"pages": [], "inputs": 3}])
        assert detection.detect(driver, stop_signal=stopped) == []
