from __future__ import annotations

from types import SimpleNamespace

from wjx.provider.questions import reorder as reorder_module


class _FakeBadge:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.style = SimpleNamespace(display="")


class _FakeReorderInput:
    def __init__(self, *, input_type: str, selected: bool = False, send_keys_exception: Exception | None = None) -> None:
        self.input_type = input_type
        self.selected = selected
        self.send_keys_exception = send_keys_exception
        self.cleared = 0
        self.sent_values: list[str] = []
        self.value = ""

    def get_attribute(self, name: str):
        if name == "type":
            return self.input_type
        return None

    def is_selected(self) -> bool:
        return self.selected

    def clear(self) -> None:
        self.cleared += 1

    def send_keys(self, value: str) -> None:
        self.sent_values.append(value)
        if self.send_keys_exception is not None:
            raise self.send_keys_exception
        self.value = value


class _FakeReorderItem:
    def __init__(
        self,
        text: str,
        *,
        input_type: str = "checkbox",
        selected: bool = False,
        badge_text: str = "",
        uid: str = "",
        send_keys_exception: Exception | None = None,
    ) -> None:
        self.text = text
        self.uid = uid
        self.selected = selected
        self.class_name = "selected" if selected else ""
        self.data_checked = "true" if selected else ""
        self.aria_checked = "true" if selected else ""
        self.badges = [_FakeBadge(badge_text)] if badge_text else []
        self.inputs = [
            _FakeReorderInput(
                input_type=input_type,
                selected=selected,
                send_keys_exception=send_keys_exception,
            )
        ]

    def find_elements(self, _by, selector: str):
        if selector == "input":
            return list(self.inputs)
        if selector == "input[type='checkbox'], input[type='radio']":
            return [ipt for ipt in self.inputs if ipt.input_type in ("checkbox", "radio")]
        if selector == ".ui-icon-number, .order-number, .order-index, .num, .sortnum, .sortnum-sel":
            return list(self.badges)
        return []

    def find_element(self, _by, selector: str):
        if selector == ".sortnum, .sortnum-sel, .order-number, .order-index" and self.badges:
            return self.badges[0]
        raise RuntimeError(selector)

    def get_attribute(self, name: str):
        if name == "class":
            return self.class_name
        if name == "data-checked":
            return self.data_checked
        if name == "aria-checked":
            return self.aria_checked
        return None

    def mark_selected(self, rank: int | None = None) -> None:
        self.selected = True
        self.class_name = "selected"
        self.data_checked = "true"
        self.aria_checked = "true"
        for ipt in self.inputs:
            if ipt.input_type in ("checkbox", "radio"):
                ipt.selected = True
        if rank is not None:
            if not self.badges:
                self.badges.append(_FakeBadge())
            self.badges[0].text = str(rank)


class _FakeContainer:
    def __init__(self, items: list[_FakeReorderItem], *, explicit_texts: dict[str, str] | None = None, rank_mode: bool = False) -> None:
        self.items = items
        self.explicit_texts = dict(explicit_texts or {})
        self.rank_mode = rank_mode

    @property
    def text(self) -> str:
        parts = [value for value in self.explicit_texts.values() if value]
        parts.extend(item.text for item in self.items)
        return "\n".join(parts)

    def find_element(self, _by, selector: str):
        if selector in self.explicit_texts:
            return SimpleNamespace(text=self.explicit_texts[selector])
        raise RuntimeError(selector)

    def find_elements(self, _by, selector: str):
        if selector == ".sortnum, .sortnum-sel, .order-number, .order-index, .ui-sortable, .ui-sortable-handle, [class*='sort'], [class*='rank']":
            return [SimpleNamespace()] if self.rank_mode else []
        if selector == ".sortnum, .sortnum-sel":
            badges = []
            for item in self.items:
                badges.extend([badge for badge in item.badges if badge.text])
            return badges
        if selector == "li[aria-checked='true'], li[data-checked='true']":
            return [item for item in self.items if item.selected]
        if selector.startswith("input[type='checkbox']:checked"):
            return [item for item in self.items if item.selected]
        if selector.startswith(".sortnum, .sortnum-sel, .order-number"):
            return [SimpleNamespace()] if self.rank_mode else []
        return []


class _FakeLocator:
    def __init__(self, page: "_FakePage", selector: str | None = None, has_text: str | None = None) -> None:
        self.page = page
        self.selector = selector
        self.has_text = has_text
        self.first = self

    def count(self) -> int:
        return 1 if self.page.resolve_item(self.selector, self.has_text) is not None else 0

    def click(self, timeout: int = 1200) -> None:
        del timeout
        self.page.click(self.selector, self.has_text)


class _FakePage:
    def __init__(self, items: list[_FakeReorderItem], *, rank_mode: bool = False) -> None:
        self.items = items
        self.rank_mode = rank_mode
        self.rank_counter = 0

    def locator(self, selector: str, has_text: str | None = None):
        return _FakeLocator(self, selector, has_text)

    def resolve_item(self, selector: str | None, has_text: str | None):
        if has_text:
            for item in self.items:
                if has_text in item.text:
                    return item
        if selector is None:
            return None
        if "data-wjx-rank-uid='" in selector:
            uid = selector.split("data-wjx-rank-uid='", 1)[1].split("'", 1)[0]
            for item in self.items:
                if item.uid == uid:
                    return item
        if "nth-child(" in selector:
            index = int(selector.split("nth-child(", 1)[1].split(")", 1)[0]) - 1
            if 0 <= index < len(self.items):
                return self.items[index]
        return None

    def click(self, selector: str | None, has_text: str | None) -> None:
        item = self.resolve_item(selector, has_text)
        if item is None:
            raise RuntimeError("locator not found")
        rank = None
        if self.rank_mode:
            self.rank_counter += 1
            rank = self.rank_counter
        item.mark_selected(rank)


class _FakeReorderDriver:
    def __init__(self, container: _FakeContainer, *, page=None) -> None:
        self.container = container
        self.page = page
        self.executed_scripts: list[tuple[str, tuple[object, ...]]] = []

    def find_element(self, _by, selector: str):
        if selector.startswith("#div"):
            return self.container
        if "data-wjx-rank-uid='" in selector:
            uid = selector.split("data-wjx-rank-uid='", 1)[1].split("'", 1)[0]
            for item in self.container.items:
                if item.uid == uid:
                    return item
        if "nth-child(" in selector:
            index = int(selector.split("nth-child(", 1)[1].split(")", 1)[0]) - 1
            return self.container.items[index]
        raise RuntimeError(selector)

    def find_elements(self, _by, selector: str):
        if selector.startswith("//*[@id='div"):
            return list(self.container.items)
        return []

    def execute_script(self, script: str, *args):
        self.executed_scripts.append((script, args))
        if "setAttribute('data-wjx-rank-uid'" in script:
            item, uid = args
            item.uid = uid
            return None
        if "arguments[0].scrollIntoView" in script:
            return None
        if "el.value = String(val)" in script:
            target_input, value = args
            target_input.value = str(value)
            return None
        return None


class ReorderQuestionTests:
    def test_extract_reorder_required_from_text_supports_all_select_and_numeric_patterns(self) -> None:
        assert reorder_module._extract_reorder_required_from_text("请将全部选项排序", 4) == 4
        assert reorder_module._extract_reorder_required_from_text("请选择3项并排序") == 3
        assert reorder_module._extract_reorder_required_from_text("至少 2 项", 5) == 2
        assert reorder_module._extract_reorder_required_from_text("数字1-4填入括号", 4) == 4
        assert reorder_module._extract_reorder_required_from_text("没有要求") is None

    def test_detect_reorder_required_count_prefers_explicit_text_over_detected_limit(self, monkeypatch) -> None:
        items = [_FakeReorderItem("A"), _FakeReorderItem("B"), _FakeReorderItem("C")]
        container = _FakeContainer(items, explicit_texts={".qtypetip": "请选择2项并排序"})
        driver = _FakeReorderDriver(container)
        monkeypatch.setattr(reorder_module, "detect_multiple_choice_limit", lambda *_args, **_kwargs: 5)

        result = reorder_module.detect_reorder_required_count(driver, 6, total_options=3)

        assert result == 2

    def test_reorder_returns_quietly_when_no_items_found(self) -> None:
        driver = _FakeReorderDriver(_FakeContainer([]))

        reorder_module.reorder(driver, 3)

        assert driver.executed_scripts == []

    def test_reorder_force_select_all_in_plain_mode_clicks_every_item(self, monkeypatch) -> None:
        items = [_FakeReorderItem("A"), _FakeReorderItem("B"), _FakeReorderItem("C")]
        container = _FakeContainer(items)
        page = _FakePage(items)
        driver = _FakeReorderDriver(container, page=page)
        monkeypatch.setattr(reorder_module.random, "shuffle", lambda _values: None)
        monkeypatch.setattr(reorder_module.time, "sleep", lambda _value: None)
        monkeypatch.setattr(reorder_module, "extract_text_from_element", lambda elem: elem.text)
        monkeypatch.setattr(reorder_module, "detect_multiple_choice_limit_range", lambda *_args, **_kwargs: (None, None))
        monkeypatch.setattr(reorder_module, "detect_reorder_required_count", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(reorder_module, "_extract_multi_limit_range_from_text", lambda *_args, **_kwargs: (None, None))

        reorder_module.reorder(driver, 8)

        assert all(item.selected for item in items)

    def test_reorder_plain_mode_respects_explicit_required_count(self, monkeypatch) -> None:
        items = [_FakeReorderItem("A"), _FakeReorderItem("B"), _FakeReorderItem("C")]
        container = _FakeContainer(items, explicit_texts={".qtypetip": "请选择2项并排序"})
        page = _FakePage(items)
        driver = _FakeReorderDriver(container, page=page)
        monkeypatch.setattr(reorder_module.random, "shuffle", lambda _values: None)
        monkeypatch.setattr(reorder_module.time, "sleep", lambda _value: None)
        monkeypatch.setattr(reorder_module, "extract_text_from_element", lambda elem: elem.text)
        monkeypatch.setattr(reorder_module, "detect_multiple_choice_limit_range", lambda *_args, **_kwargs: (None, None))
        monkeypatch.setattr(reorder_module, "detect_reorder_required_count", lambda *_args, **_kwargs: 2)
        monkeypatch.setattr(reorder_module, "_extract_multi_limit_range_from_text", lambda text: (2, 2) if text else (None, None))

        reorder_module.reorder(driver, 9)

        assert sum(1 for item in items if item.selected) == 2

    def test_reorder_numeric_rank_mode_fills_text_inputs(self, monkeypatch) -> None:
        items = [
            _FakeReorderItem("A", input_type="text"),
            _FakeReorderItem("B", input_type="text"),
            _FakeReorderItem("C", input_type="text"),
        ]
        container = _FakeContainer(items, explicit_texts={".qtypetip": "请选择2项并排序"})
        driver = _FakeReorderDriver(container)
        monkeypatch.setattr(reorder_module.random, "shuffle", lambda _values: None)
        monkeypatch.setattr(reorder_module, "extract_text_from_element", lambda elem: elem.text)
        monkeypatch.setattr(reorder_module, "detect_multiple_choice_limit_range", lambda *_args, **_kwargs: (None, None))
        monkeypatch.setattr(reorder_module, "detect_reorder_required_count", lambda *_args, **_kwargs: 2)
        monkeypatch.setattr(reorder_module, "_extract_multi_limit_range_from_text", lambda text: (2, 2) if text else (None, None))

        reorder_module.reorder(driver, 10)

        assert items[0].inputs[0].sent_values == ["1"]
        assert items[1].inputs[0].sent_values == ["2"]
        assert items[2].inputs[0].sent_values == [""]

    def test_reorder_numeric_rank_mode_falls_back_to_execute_script_when_send_keys_fails(self, monkeypatch) -> None:
        items = [
            _FakeReorderItem("A", input_type="text", send_keys_exception=RuntimeError("fail")),
            _FakeReorderItem("B", input_type="text", send_keys_exception=RuntimeError("fail")),
            _FakeReorderItem("C", input_type="text", send_keys_exception=RuntimeError("fail")),
        ]
        container = _FakeContainer(items, explicit_texts={".qtypetip": "请选择2项并排序"})
        driver = _FakeReorderDriver(container)
        monkeypatch.setattr(reorder_module.random, "shuffle", lambda _values: None)
        monkeypatch.setattr(reorder_module, "extract_text_from_element", lambda elem: elem.text)
        monkeypatch.setattr(reorder_module, "detect_multiple_choice_limit_range", lambda *_args, **_kwargs: (None, None))
        monkeypatch.setattr(reorder_module, "detect_reorder_required_count", lambda *_args, **_kwargs: 2)
        monkeypatch.setattr(reorder_module, "_extract_multi_limit_range_from_text", lambda text: (2, 2) if text else (None, None))

        reorder_module.reorder(driver, 11)

        assert items[0].inputs[0].value == "1"
        assert items[1].inputs[0].value == "2"
        assert items[2].inputs[0].value == ""

    def test_reorder_rank_mode_assigns_uids_and_clicks_planned_items(self, monkeypatch) -> None:
        items = [_FakeReorderItem("A"), _FakeReorderItem("B"), _FakeReorderItem("C")]
        container = _FakeContainer(items, explicit_texts={".qtypetip": "请选择2项并排序"}, rank_mode=True)
        page = _FakePage(items, rank_mode=True)
        driver = _FakeReorderDriver(container, page=page)
        tick = {"value": 1000.0}

        def fake_time() -> float:
            tick["value"] += 0.2
            return tick["value"]

        monkeypatch.setattr(reorder_module.random, "shuffle", lambda _values: None)
        monkeypatch.setattr(reorder_module.random, "randint", lambda _start, _end: 1234)
        monkeypatch.setattr(reorder_module.time, "sleep", lambda _value: None)
        monkeypatch.setattr(reorder_module.time, "time", fake_time)
        monkeypatch.setattr(reorder_module, "extract_text_from_element", lambda elem: elem.text)
        monkeypatch.setattr(reorder_module, "detect_multiple_choice_limit_range", lambda *_args, **_kwargs: (None, None))
        monkeypatch.setattr(reorder_module, "detect_reorder_required_count", lambda *_args, **_kwargs: 2)
        monkeypatch.setattr(reorder_module, "_extract_multi_limit_range_from_text", lambda text: (2, 2) if text else (None, None))

        reorder_module.reorder(driver, 12)

        assert sum(1 for item in items if item.selected) == 2
        assert all(item.uid.startswith("q12_") for item in items)

    def test_reorder_rank_mode_force_select_all_remedies_missing_items(self, monkeypatch) -> None:
        items = [_FakeReorderItem("A"), _FakeReorderItem("B"), _FakeReorderItem("C")]
        container = _FakeContainer(items, rank_mode=True)
        page = _FakePage(items, rank_mode=True)
        driver = _FakeReorderDriver(container, page=page)
        tick = {"value": 2000.0}

        def fake_time() -> float:
            tick["value"] += 0.25
            return tick["value"]

        monkeypatch.setattr(reorder_module.random, "shuffle", lambda _values: None)
        monkeypatch.setattr(reorder_module.random, "randint", lambda _start, _end: 5678)
        monkeypatch.setattr(reorder_module.time, "sleep", lambda _value: None)
        monkeypatch.setattr(reorder_module.time, "time", fake_time)
        monkeypatch.setattr(reorder_module, "extract_text_from_element", lambda elem: elem.text)
        monkeypatch.setattr(reorder_module, "detect_multiple_choice_limit_range", lambda *_args, **_kwargs: (None, None))
        monkeypatch.setattr(reorder_module, "detect_reorder_required_count", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(reorder_module, "_extract_multi_limit_range_from_text", lambda *_args, **_kwargs: (None, None))

        reorder_module.reorder(driver, 13)

        assert all(item.selected for item in items)
