from __future__ import annotations

import pytest

from software.network.browser.element import PlaywrightElement
from software.network.browser.exceptions import NoSuchElementException


class _FakeHandle:
    def __init__(self) -> None:
        self.actions: list[tuple[str, object]] = []
        self.inner_text_value = "text"
        self.attribute_value = "value"
        self.bounding_box_value = {"width": 10, "height": 20}
        self.evaluate_value = "div"
        self.query_selector_result = None
        self.query_selector_all_result = []
        self.click_error_sequence: list[Exception] = []
        self.fill_error: Exception | None = None
        self.type_error: Exception | None = None
        self.evaluate_error: Exception | None = None

    def inner_text(self) -> str:
        return self.inner_text_value

    def get_attribute(self, name: str):
        self.actions.append(("get_attribute", name))
        return self.attribute_value

    def bounding_box(self):
        return self.bounding_box_value

    def evaluate(self, script: str, *args):
        self.actions.append(("evaluate", script if not args else (script, args)))
        if self.evaluate_error is not None:
            raise self.evaluate_error
        return self.evaluate_value

    def click(self, **kwargs) -> None:
        self.actions.append(("click", kwargs or None))
        if self.click_error_sequence:
            raise self.click_error_sequence.pop(0)

    def scroll_into_view_if_needed(self) -> None:
        self.actions.append(("scroll", None))

    def fill(self, value: str) -> None:
        self.actions.append(("fill", value))
        if self.fill_error is not None:
            raise self.fill_error

    def type(self, value: str) -> None:
        self.actions.append(("type", value))
        if self.type_error is not None:
            raise self.type_error

    def query_selector(self, selector: str):
        self.actions.append(("query_selector", selector))
        return self.query_selector_result

    def query_selector_all(self, selector: str):
        self.actions.append(("query_selector_all", selector))
        return self.query_selector_all_result


class PlaywrightElementTests:
    def test_text_and_attribute_and_size_happy_path(self) -> None:
        handle = _FakeHandle()
        element = PlaywrightElement(handle, page=object())

        assert element.text == "text"
        assert element.get_attribute("data-id") == "value"
        assert element.is_displayed() is True
        assert element.size == {"width": 10, "height": 20}
        assert element.tag_name == "div"

    def test_safe_accessors_fall_back_when_handle_raises(self) -> None:
        handle = _FakeHandle()
        handle.inner_text = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        handle.get_attribute = lambda _name: (_ for _ in ()).throw(RuntimeError("boom"))
        handle.bounding_box = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        handle.evaluate_error = RuntimeError("boom")
        element = PlaywrightElement(handle, page=object())

        assert element.text == ""
        assert element.get_attribute("data-id") is None
        assert element.is_displayed() is False
        assert element.size == {"width": 0, "height": 0}
        assert element.tag_name == ""

    def test_click_timeout_uses_fast_js_fallback(self) -> None:
        handle = _FakeHandle()
        handle.click_error_sequence = [RuntimeError("divS intercepts pointer events")]
        element = PlaywrightElement(handle, page=object())

        element.click()

        assert handle.actions[:2] == [
            ("click", {"timeout": 1200}),
            ("evaluate", "el => { el.click(); return true; }"),
        ]

    def test_hidden_clear_and_send_keys_use_js_without_fill_wait(self) -> None:
        handle = _FakeHandle()
        handle.bounding_box_value = None
        element = PlaywrightElement(handle, page=object())

        element.clear()
        element.send_keys("隐藏值")

        assert not any(action == ("fill", "") for action in handle.actions)
        assert not any(action == ("fill", "隐藏值") for action in handle.actions)
        assert [action[0] for action in handle.actions].count("evaluate") >= 2

    def test_click_uses_scroll_fallback_before_js_click_for_non_timeout_errors(self) -> None:
        handle = _FakeHandle()
        handle.click_error_sequence = [ValueError("first"), RuntimeError("second")]
        element = PlaywrightElement(handle, page=object())

        element.click()

        assert handle.actions[:4] == [
            ("click", {"timeout": 1200}),
            ("scroll", None),
            ("click", {"timeout": 1200}),
            ("evaluate", "el => { el.click(); return true; }"),
        ]

    def test_clear_and_send_keys_use_fallbacks(self) -> None:
        handle = _FakeHandle()
        handle.fill_error = RuntimeError("fill failed")
        handle.type_error = RuntimeError("type failed")
        element = PlaywrightElement(handle, page=object())

        element.clear()
        element.send_keys("hello")

        assert ("evaluate", "el => { el.value = ''; el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }") in handle.actions
        assert ("type", "hello") in handle.actions

    def test_find_element_and_find_elements_wrap_handles(self) -> None:
        child = _FakeHandle()
        handle = _FakeHandle()
        handle.query_selector_result = child
        handle.query_selector_all_result = [child]
        page = object()
        element = PlaywrightElement(handle, page=page)

        found = element.find_element("id", "demo")
        found_list = element.find_elements("css", ".x")

        assert isinstance(found, PlaywrightElement)
        assert len(found_list) == 1
        assert isinstance(found_list[0], PlaywrightElement)

    def test_find_element_raises_when_selector_missing(self) -> None:
        element = PlaywrightElement(_FakeHandle(), page=object())

        with pytest.raises(NoSuchElementException, match="Element not found"):
            element.find_element("id", "missing")

