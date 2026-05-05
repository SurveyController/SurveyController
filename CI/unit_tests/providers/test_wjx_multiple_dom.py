from __future__ import annotations

from types import SimpleNamespace

from wjx.provider.questions import multiple_dom


class _FakeDomElement:
    def __init__(
        self,
        *,
        element_id: str = "",
        displayed: bool = True,
        click_exception: Exception | None = None,
        attributes: dict[str, str] | None = None,
        selector_map: dict[str, list[object]] | None = None,
    ) -> None:
        self.id = element_id
        self.displayed = displayed
        self.click_exception = click_exception
        self.attributes = dict(attributes or {})
        self.selector_map = dict(selector_map or {})
        self.click_calls = 0

    def is_displayed(self) -> bool:
        return self.displayed

    def get_attribute(self, name: str):
        return self.attributes.get(name)

    def find_elements(self, _by, selector: str):
        result = self.selector_map.get(selector, [])
        if isinstance(result, Exception):
            raise result
        return list(result)

    def click(self) -> None:
        self.click_calls += 1
        if self.click_exception is not None:
            raise self.click_exception


class _FakeContainer:
    def __init__(self, selector_map: dict[str, list[object]] | None = None) -> None:
        self.selector_map = dict(selector_map or {})

    def find_elements(self, _by, selector: str):
        result = self.selector_map.get(selector, [])
        if isinstance(result, Exception):
            raise result
        return list(result)


class _FakeMultipleDomDriver:
    def __init__(self, *, container=None, execute_results: list[object] | None = None) -> None:
        self.container = container
        self.execute_results = list(execute_results or [])
        self.executed_scripts: list[tuple[str, tuple[object, ...]]] = []

    def find_element(self, _by, selector: str):
        if self.container is None:
            raise RuntimeError(selector)
        return self.container

    def execute_script(self, script: str, *args):
        self.executed_scripts.append((script, args))
        if self.execute_results:
            result = self.execute_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return False


class MultipleDomTests:
    def test_looks_like_multiple_option_accepts_class_type_and_nested_checkbox(self) -> None:
        by_class = _FakeDomElement(attributes={"class": "ui-checkbox option"})
        by_type = _FakeDomElement(attributes={"type": "checkbox"})
        by_nested = _FakeDomElement(selector_map={"input[type='checkbox'], .jqcheck, .ui-checkbox": [object()]})
        invalid = _FakeDomElement()

        assert multiple_dom._looks_like_multiple_option(by_class)
        assert multiple_dom._looks_like_multiple_option(by_type)
        assert multiple_dom._looks_like_multiple_option(by_nested)
        assert not multiple_dom._looks_like_multiple_option(invalid)

    def test_collect_multiple_option_elements_returns_first_visible_matching_selector(self) -> None:
        hidden = _FakeDomElement(element_id="hidden", displayed=False, attributes={"class": "ui-checkbox"})
        first = _FakeDomElement(element_id="first", attributes={"class": "ui-checkbox"})
        duplicate = first
        second = _FakeDomElement(element_id="second", attributes={"type": "checkbox"})
        container = _FakeContainer(
            {
                ".ui-controlgroup > div": [hidden, first, duplicate, second],
            }
        )
        driver = _FakeMultipleDomDriver(container=container)

        options, source = multiple_dom._collect_multiple_option_elements(driver, 3)

        assert [opt.id for opt in options] == ["first", "second"]
        assert source == "css:#div .ui-controlgroup > div"

    def test_collect_multiple_option_elements_falls_back_to_checkbox_inputs(self) -> None:
        checkbox = _FakeDomElement(element_id="cb", attributes={"type": "checkbox"})
        container = _FakeContainer(
            {
                ".ui-controlgroup > div": [],
                ".ui-controlgroup li": [],
                "ul > li": [],
                "ol > li": [],
                ".option": [],
                ".ui-checkbox": [],
                ".jqcheck": [],
                "input[type='checkbox']": [checkbox],
            }
        )
        driver = _FakeMultipleDomDriver(container=container)

        options, source = multiple_dom._collect_multiple_option_elements(driver, 7)

        assert options == [checkbox]
        assert source == "css:#div input[type=checkbox]"

    def test_is_multiple_option_selected_returns_false_on_script_error(self) -> None:
        driver = _FakeMultipleDomDriver(container=object(), execute_results=[RuntimeError("boom")])

        assert not multiple_dom._is_multiple_option_selected(driver, object())

    def test_click_multiple_option_uses_direct_click_then_accepts_selected_state(self, monkeypatch) -> None:
        option = _FakeDomElement(element_id="root")
        child = _FakeDomElement(element_id="child")
        option.selector_map[
            ".label, label, .jqcheck, .ui-checkbox, input[type='checkbox'], a, span, div"
        ] = [child]
        driver = _FakeMultipleDomDriver(container=object())
        states = iter([False, True])
        monkeypatch.setattr(multiple_dom, "_is_multiple_option_selected", lambda *_args, **_kwargs: next(states))

        result = multiple_dom._click_multiple_option(driver, option)

        assert result is True
        assert option.click_calls == 1
        assert child.click_calls == 0

    def test_click_multiple_option_falls_back_to_script_click_and_force_select(self, monkeypatch) -> None:
        option = _FakeDomElement(element_id="root", click_exception=RuntimeError("direct failed"))
        child = _FakeDomElement(element_id="child", click_exception=RuntimeError("child failed"))
        option.selector_map[
            ".label, label, .jqcheck, .ui-checkbox, input[type='checkbox'], a, span, div"
        ] = [child]
        driver = _FakeMultipleDomDriver(container=object(), execute_results=[RuntimeError("js click"), False, True])
        state_checks = {"count": 0}

        def fake_selected(*_args, **_kwargs) -> bool:
            state_checks["count"] += 1
            return state_checks["count"] >= 3

        monkeypatch.setattr(multiple_dom, "_is_multiple_option_selected", fake_selected)

        result = multiple_dom._click_multiple_option(driver, option)

        assert result is True
        assert len(driver.executed_scripts) == 3
