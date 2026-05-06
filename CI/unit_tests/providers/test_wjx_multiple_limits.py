from __future__ import annotations

from types import SimpleNamespace

from software.network.browser import NoSuchElementException
from wjx.provider.questions import multiple_limits


class _FakeElement:
    def __init__(self, attributes: dict[str, str] | None = None, *, texts: dict[str, list[str]] | None = None) -> None:
        self.attributes = dict(attributes or {})
        self.texts = dict(texts or {})

    def get_attribute(self, name: str):
        return self.attributes.get(name)

    def find_elements(self, _by, selector: str):
        return [SimpleNamespace(text=text) for text in self.texts.get(selector, [])]


class _FakeDriver:
    def __init__(self, element: _FakeElement | None, *, session_id: str = "session-1", js_text: str = "") -> None:
        self.element = element
        self.session_id = session_id
        self.js_text = js_text
        self.find_calls = 0

    def find_element(self, _by, _selector: str):
        self.find_calls += 1
        if self.element is None:
            raise NoSuchElementException("not found")
        return self.element

    def execute_script(self, _script: str, _container):
        return self.js_text


class WjxMultipleLimitsTests:
    def setup_method(self) -> None:
        multiple_limits._DETECTED_MULTI_LIMITS.clear()
        multiple_limits._DETECTED_MULTI_LIMIT_RANGES.clear()
        multiple_limits._REPORTED_MULTI_LIMITS.clear()

    def test_safe_positive_int_accepts_numbers_and_numeric_text(self) -> None:
        assert multiple_limits._safe_positive_int(3) == 3
        assert multiple_limits._safe_positive_int(" 7 ") == 7
        assert multiple_limits._safe_positive_int("最多选4项") == 4
        assert multiple_limits._safe_positive_int(0) is None
        assert multiple_limits._safe_positive_int(False) is None

    def test_extract_range_from_json_obj_and_possible_json(self) -> None:
        assert multiple_limits._extract_range_from_json_obj({"rules": {"min": 2, "max": 5}}) == (2, 5)
        assert multiple_limits._extract_range_from_possible_json('{"min":2,"max":5}') == (2, 5)
        assert multiple_limits._extract_range_from_possible_json("{'minValue':2,'maxValue':4}") == (2, 4)
        assert multiple_limits._extract_range_from_possible_json("min=1 max=3") == (1, 3)

    def test_extract_min_max_from_attributes_reads_supported_names(self) -> None:
        element = _FakeElement({"minvalue": "2", "maxvalue": "6"})
        assert multiple_limits._extract_min_max_from_attributes(element) == (2, 6)

    def test_extract_multi_limit_range_from_text_supports_cn_and_en_patterns(self) -> None:
        assert multiple_limits._extract_multi_limit_range_from_text("请选择2-4项你喜欢的功能") == (2, 4)
        assert multiple_limits._extract_multi_limit_range_from_text("至少选2项，最多选5项") == (2, 5)
        assert multiple_limits._extract_multi_limit_range_from_text("请选择3项") == (3, 3)
        assert multiple_limits._extract_multi_limit_range_from_text("Select between 2 and 4 options") == (2, 4)
        assert multiple_limits._extract_multi_limit_range_from_text("Select up to 3 options") == (None, 3)
        assert multiple_limits._extract_multi_limit_range_from_text("At least 2 choices") == (2, None)

    def test_collect_multi_limit_text_fragments_from_container_dedupes_texts(self) -> None:
        container = _FakeElement(
            texts={
                ".topichtml": ["至少选2项"],
                ".question-tip": ["至少选2项", "最多选4项"],
            }
        )
        driver = _FakeDriver(container, js_text="至少选2项 最多选4项")

        fragments = multiple_limits._collect_multi_limit_text_fragments_from_container(driver, container)

        assert fragments == ["至少选2项", "最多选4项", "至少选2项 最多选4项"]

    def test_get_driver_session_key_prefers_session_id(self) -> None:
        driver = _FakeDriver(None, session_id="abc")
        assert multiple_limits._get_driver_session_key(driver) == "abc"
        driver_without_session = SimpleNamespace()
        assert multiple_limits._get_driver_session_key(driver_without_session).startswith("id-")

    def test_detect_multiple_choice_limit_range_prefers_attributes_then_caches(self) -> None:
        element = _FakeElement({"minvalue": "2", "maxvalue": "4"})
        driver = _FakeDriver(element, session_id="cache-test")

        first = multiple_limits.detect_multiple_choice_limit_range(driver, 8)
        second = multiple_limits.detect_multiple_choice_limit_range(driver, 8)

        assert first == (2, 4)
        assert second == (2, 4)
        assert driver.find_calls == 1
        assert multiple_limits.detect_multiple_choice_limit(driver, 8) == 4

    def test_detect_multiple_choice_limit_range_can_fall_back_to_json_and_text(self) -> None:
        element = _FakeElement(
            {
                "data-setting": '{"validate":{"min":1,"max":3}}',
                "outerHTML": "<div>至少选1项，最多选3项</div>",
            },
            texts={".topichtml": ["至少选1项，最多选3项"]},
        )
        driver = _FakeDriver(element, session_id="json-text", js_text="至少选1项，最多选3项")

        assert multiple_limits.detect_multiple_choice_limit_range(driver, 9) == (1, 3)

    def test_detect_multiple_choice_limit_range_handles_missing_container(self) -> None:
        driver = _FakeDriver(None, session_id="missing")
        assert multiple_limits.detect_multiple_choice_limit_range(driver, 10) == (None, None)

    def test_log_multi_limit_once_records_only_once(self) -> None:
        driver = _FakeDriver(None, session_id="log-once")
        multiple_limits._log_multi_limit_once(driver, 3, 1, 2)
        multiple_limits._log_multi_limit_once(driver, 3, 1, 2)
        assert len(multiple_limits._REPORTED_MULTI_LIMITS) == 1
