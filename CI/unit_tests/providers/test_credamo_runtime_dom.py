from __future__ import annotations

import threading

import pytest

from credamo.provider import runtime_dom


class _FakeRoot:
    def __init__(self, attrs: dict[str, object] | None = None, *, selectors: dict[str, list[object]] | None = None) -> None:
        self.attrs = dict(attrs or {})
        self.selectors = dict(selectors or {})

    async def get_attribute(self, name: str):
        return self.attrs.get(name)

    async def query_selector_all(self, selector: str):
        value = self.selectors.get(selector)
        if isinstance(value, Exception):
            raise value
        return list(value or [])

    async def query_selector(self, selector: str):
        items = await self.query_selector_all(selector)
        return items[0] if items else None


class _FakeTextNode:
    def __init__(self, *, inner_text: str = "", text_content: str = "", value: str = "") -> None:
        self._inner_text = inner_text
        self._text_content = text_content
        self._value = value

    async def inner_text(self, timeout: int = 0) -> str:
        del timeout
        if isinstance(self._inner_text, Exception):
            raise self._inner_text
        return self._inner_text

    async def text_content(self, timeout: int = 0) -> str:
        del timeout
        if isinstance(self._text_content, Exception):
            raise self._text_content
        return self._text_content

    async def get_attribute(self, name: str):
        if name == "value":
            return self._value
        return None


class _FakeElement:
    def __init__(
        self,
        *,
        click_error: Exception | None = None,
        js_click_result: bool = True,
        scroll_error: Exception | None = None,
        value: str = "",
        checked: bool = False,
    ) -> None:
        self.click_error = click_error
        self.js_click_result = js_click_result
        self.scroll_error = scroll_error
        self.value = value
        self.checked = checked
        self.clicked = 0
        self.scrolled = 0

    async def scroll_into_view_if_needed(self, timeout: int = 0) -> None:
        del timeout
        self.scrolled += 1
        if self.scroll_error is not None:
            raise self.scroll_error

    async def click(self, timeout: int = 0) -> None:
        del timeout
        self.clicked += 1
        if self.click_error is not None:
            raise self.click_error


class _FakeBodyLocator:
    def __init__(self, text: str = "", error: Exception | None = None) -> None:
        self.text = text
        self.error = error

    async def inner_text(self, timeout: int = 0) -> str:
        del timeout
        if self.error is not None:
            raise self.error
        return self.text


class _FakeLocatorItem:
    def __init__(
        self,
        *,
        text: str = "",
        visible: bool = True,
        value: str = "",
        click_error: Exception | None = None,
        handle: object | None = None,
        handle_error: Exception | None = None,
        count: int | None = None,
        scroll_error: Exception | None = None,
    ) -> None:
        self.text = text
        self.visible = visible
        self.value = value
        self.click_error = click_error
        self.handle = handle
        self.handle_error = handle_error
        self.count_value = 1 if count is None else count
        self.scroll_error = scroll_error
        self.clicked = 0
        self.scrolled = 0

    async def count(self) -> int:
        return self.count_value

    async def is_visible(self, timeout: int = 0) -> bool:
        del timeout
        return self.visible

    async def text_content(self, timeout: int = 0) -> str:
        del timeout
        return self.text

    async def get_attribute(self, name: str):
        if name == "value":
            return self.value
        return None

    async def click(self, timeout: int = 0) -> None:
        del timeout
        self.clicked += 1
        if self.click_error is not None:
            raise self.click_error

    async def scroll_into_view_if_needed(self, timeout: int = 0) -> None:
        del timeout
        self.scrolled += 1
        if self.scroll_error is not None:
            raise self.scroll_error

    async def element_handle(self, timeout: int = 0):
        del timeout
        if self.handle_error is not None:
            raise self.handle_error
        return self.handle


class _FakeLocator:
    def __init__(self, items: list[_FakeLocatorItem]) -> None:
        self.items = items
        self.first = items[0] if items else _FakeLocatorItem(count=0, visible=False)

    async def count(self) -> int:
        return len(self.items)

    def nth(self, index: int) -> _FakeLocatorItem:
        return self.items[index]


class _FakePage:
    def __init__(
        self,
        *,
        eval_on_selector_all_result=None,
        query_selector_all_results: dict[str, object] | None = None,
        evaluate_result=None,
        title_text: str = "",
        body_text: str = "",
        body_error: Exception | None = None,
        locators: dict[str, _FakeLocator] | None = None,
        evaluate_map: dict[str, list[object]] | None = None,
    ) -> None:
        self.eval_on_selector_all_result = eval_on_selector_all_result
        self.query_selector_all_results = dict(query_selector_all_results or {})
        self.evaluate_result = evaluate_result
        self.title_text = title_text
        self.body_text = body_text
        self.body_error = body_error
        self.locators = dict(locators or {})
        self.evaluate_map = {key: list(value) for key, value in (evaluate_map or {}).items()}

    async def eval_on_selector_all(self, _selector: str, _script: str):
        if isinstance(self.eval_on_selector_all_result, Exception):
            raise self.eval_on_selector_all_result
        return self.eval_on_selector_all_result

    async def query_selector_all(self, selector: str):
        value = self.query_selector_all_results.get(selector, [])
        if isinstance(value, Exception):
            raise value
        return list(value)

    async def evaluate(self, script: str, *args):
        for marker, results in self.evaluate_map.items():
            if marker in script:
                if not results:
                    return None
                result = results.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result
        if isinstance(self.evaluate_result, Exception):
            raise self.evaluate_result
        if "el => !!el.checked" in script:
            return bool(getattr(args[0], "checked", False))
        if "String(el.value || '')" in script:
            return getattr(args[0], "value", "")
        if "el => { el.click(); return true; }" in script:
            element = args[0]
            return bool(getattr(element, "js_click_result", True))
        return self.evaluate_result

    async def title(self) -> str:
        return self.title_text

    def locator(self, selector: str):
        if selector == "body":
            return _FakeBodyLocator(self.body_text, self.body_error)
        return self.locators.get(selector, _FakeLocator([]))


class _FakeDriver:
    def __init__(self, page) -> None:
        self._page = page

    async def page(self):
        return self._page


class CredamoRuntimeDomTests:
    @pytest.mark.asyncio
    async def test_page_and_abort_requested_cover_basic_paths(self) -> None:
        page = object()
        driver = _FakeDriver(page)
        assert await runtime_dom._page(driver) is page
        assert not runtime_dom._abort_requested(None)

        stop_signal = threading.Event()
        assert not runtime_dom._abort_requested(stop_signal)
        stop_signal.set()
        assert runtime_dom._abort_requested(stop_signal)

        class _BrokenStop:
            def is_set(self):
                raise RuntimeError("boom")

        assert not runtime_dom._abort_requested(_BrokenStop())

    @pytest.mark.asyncio
    async def test_question_roots_uses_visible_indexes_and_fallbacks(self) -> None:
        roots = [object(), object(), object()]
        page = _FakePage(
            eval_on_selector_all_result=["1", "x", 2],
            query_selector_all_results={".answer-page .question": roots},
        )
        result = await runtime_dom._question_roots(page)
        assert result == [roots[1], roots[2]]

        fallback_page = _FakePage(
            eval_on_selector_all_result=RuntimeError("eval failed"),
            query_selector_all_results={".answer-page .question": [roots[0]]},
        )
        assert await runtime_dom._question_roots(fallback_page) == [roots[0]]

        broken_page = _FakePage(
            eval_on_selector_all_result=[],
            query_selector_all_results={".answer-page .question": RuntimeError("query failed")},
        )
        assert await runtime_dom._question_roots(broken_page) == []

    @pytest.mark.asyncio
    async def test_collect_question_root_snapshot_and_loading_snapshot_handle_errors(self) -> None:
        page = _FakePage(
            evaluate_result=[
                {
                    "index": "2",
                    "id": "question-2",
                    "visible": True,
                    "title": " 标题 ",
                    "rawNumber": " Q2 ",
                    "text": " 题面 ",
                },
                "bad",
            ],
            title_text="答卷",
            body_text="  载入中...  ",
        )
        snapshot = await runtime_dom._collect_question_root_snapshot(page)
        assert snapshot == [
            {
                "index": 2,
                "id": "question-2",
                "visible": True,
                "title": "标题",
                "raw_number": "Q2",
                "text": "题面",
            }
        ]

        title, body = await runtime_dom._page_loading_snapshot(page)
        assert title == "答卷"
        assert body == "载入中..."

        broken = _FakePage(
            evaluate_result=RuntimeError("boom"),
            body_error=RuntimeError("body failed"),
        )
        assert await runtime_dom._collect_question_root_snapshot(broken) == []
        assert await runtime_dom._page_loading_snapshot(broken) == ("", "")

    def test_looks_like_loading_shell_covers_short_and_normal_pages(self) -> None:
        assert runtime_dom._looks_like_loading_shell("", "")
        assert runtime_dom._looks_like_loading_shell("答卷", "载 入 中 . . .")
        assert runtime_dom._looks_like_loading_shell("答卷", "很短")
        assert not runtime_dom._looks_like_loading_shell("正式问卷", "这里已经有大量题目内容")

    @pytest.mark.asyncio
    async def test_question_number_kind_signature_and_answerable_helpers(self, monkeypatch) -> None:
        page = _FakePage(
            evaluate_map={
                ".question-title .qstNo": ["Q12", RuntimeError("bad number"), "matrix"],
                "return selectors.reduce": [3, 0],
            }
        )
        root = _FakeRoot({"id": "q-12"})
        assert await runtime_dom._question_number_from_root(page, root, 5) == 12
        assert await runtime_dom._question_number_from_root(page, root, 5) == 5

        kind_page = _FakePage(evaluate_result=" matrix ")
        assert await runtime_dom._question_kind_from_root(kind_page, root) == "matrix"

        monkeypatch.setattr(runtime_dom, "_question_kind_from_root", lambda *_args, **_kwargs: _async_return("single")())
        assert await runtime_dom._is_answerable_root(object(), root)

        monkeypatch.setattr(runtime_dom, "_question_kind_from_root", lambda *_args, **_kwargs: _async_return("")())
        monkeypatch.setattr(runtime_dom, "_text_inputs", lambda *_args, **_kwargs: _async_return([object()])())
        assert await runtime_dom._is_answerable_root(page, root)

        monkeypatch.setattr(runtime_dom, "_text_inputs", lambda *_args, **_kwargs: _async_return([])())
        assert not await runtime_dom._is_answerable_root(_FakePage(evaluate_map={"return selectors.reduce": [0]}), root)

        sig_root1 = _FakeRoot({"id": "a"})
        sig_root2 = _FakeRoot({"data-id": "b"})
        monkeypatch.setattr(runtime_dom, "_question_roots", lambda *_args, **_kwargs: _async_return([sig_root1, sig_root2])())
        monkeypatch.setattr(
            runtime_dom,
            "_root_text",
            lambda _page, item: _async_return("A" if item is sig_root1 else "B")(),
        )
        assert await runtime_dom._question_signature(object()) == (("a", "A"), ("b", "B"))

    @pytest.mark.asyncio
    async def test_question_answer_state_and_runtime_question_key_cover_states(self, monkeypatch) -> None:
        answered_page = _FakePage(evaluate_result=" answered ")
        unanswered_page = _FakePage(evaluate_result="unanswered")
        unknown_page = _FakePage(evaluate_result="unknown")
        broken_page = _FakePage(evaluate_result=RuntimeError("bad state"))
        root = _FakeRoot({"data-id": "question-5"})

        assert await runtime_dom._question_answer_state(answered_page, root, kind="single") is True
        assert await runtime_dom._question_answer_state(unanswered_page, root, kind="single") is False
        assert await runtime_dom._question_answer_state(unknown_page, root, kind="order") is None
        assert await runtime_dom._question_answer_state(broken_page, root, kind="single") is None

        assert await runtime_dom._runtime_question_key(object(), root, 5) == "id:question-5"

        no_id_root = _FakeRoot({})
        monkeypatch.setattr(runtime_dom, "_root_text", lambda *_args, **_kwargs: _async_return("长题面")())
        assert await runtime_dom._runtime_question_key(object(), no_id_root, 7) == "num:7|text:长题面"

    @pytest.mark.asyncio
    async def test_unanswered_question_roots_and_dynamic_wait_cover_skip_rules(self, monkeypatch) -> None:
        root1 = _FakeRoot({"id": "a"})
        root2 = _FakeRoot({"id": "b"})
        root3 = _FakeRoot({"id": "c"})

        async def _is_answerable(_page, root):
            return root is not root1

        async def _kind(_page, root):
            return "single" if root is root2 else "text"

        async def _num(_page, root, fallback):
            return 9 if root is root2 else fallback

        async def _key(_page, root, _question_num):
            return "k2" if root is root2 else "k3"

        states = {id(root2): True, id(root3): False}

        async def _state(_page, root, *, kind: str = ""):
            del kind
            return states[id(root)]

        monkeypatch.setattr(runtime_dom, "_is_answerable_root", _is_answerable)
        monkeypatch.setattr(runtime_dom, "_question_kind_from_root", _kind)
        monkeypatch.setattr(runtime_dom, "_question_number_from_root", _num)
        monkeypatch.setattr(runtime_dom, "_runtime_question_key", _key)
        monkeypatch.setattr(runtime_dom, "_question_answer_state", _state)

        pending = await runtime_dom._unanswered_question_roots(object(), [root1, root2, root3], {"k3"}, fallback_start=5)
        assert pending == [(root3, 8, "k3")]

        monkeypatch.setattr(
            runtime_dom,
            "_question_roots",
            lambda *_args, **_kwargs: _async_return([root2])(),
        )
        monkeypatch.setattr(
            runtime_dom,
            "_unanswered_question_roots",
            lambda *_args, **_kwargs: _async_return([(root2, 9, "k2")])(),
        )
        roots = await runtime_dom._wait_for_dynamic_question_roots(object(), set(), None, timeout_ms=1)
        assert roots == [root2]

        stop_signal = threading.Event()
        stop_signal.set()
        assert await runtime_dom._wait_for_dynamic_question_roots(object(), set(), stop_signal, timeout_ms=1) == []

    @pytest.mark.asyncio
    async def test_click_input_text_and_option_helpers_cover_fallbacks(self) -> None:
        element = _FakeElement(click_error=RuntimeError("click failed"), js_click_result=True, scroll_error=RuntimeError("scroll failed"))
        page = _FakePage()
        assert await runtime_dom._click_element(page, element)
        assert element.clicked == 1
        assert element.scrolled == 1

        js_fail = _FakeElement(click_error=RuntimeError("click failed"), js_click_result=False)
        assert not await runtime_dom._click_element(page, js_fail)

        checked = _FakeElement(checked=True, value="abc")
        assert await runtime_dom._is_checked(page, checked)
        assert await runtime_dom._input_value(page, checked) == "abc"

        broken_page = _FakePage(evaluate_result=RuntimeError("bad eval"))
        assert not await runtime_dom._is_checked(broken_page, checked)
        assert await runtime_dom._input_value(broken_page, checked) == ""

        root = _FakeRoot(
            selectors={
                "input[type='radio'], [role='radio']": [1, 2],
                ".single-choice .choice-row, .single-choice .choice, .choice-row, .choice": ["a"],
                "textarea, input:not([readonly])[type='text'], input:not([readonly])[type='search'], input:not([readonly])[type='number'], input:not([readonly])[type='tel'], input:not([readonly])[type='email'], input:not([readonly]):not([type])": ["t"],
            }
        )
        assert await runtime_dom._option_inputs(root, "radio") == [1, 2]
        assert await runtime_dom._option_click_targets(root, "radio") == ["a"]
        assert await runtime_dom._option_click_targets(root, "unknown") == []
        assert await runtime_dom._text_inputs(root) == ["t"]

    @pytest.mark.asyncio
    async def test_text_and_navigation_helpers_cover_primary_and_fallback_paths(self) -> None:
        page = _FakePage()
        element = _FakeTextNode(inner_text="", text_content="", value="  值  ")
        assert await runtime_dom._element_text(page, element) == "值"
        assert runtime_dom._normalize_runtime_text("  a \n b  ") == "a b"

        title_node = _FakeTextNode(inner_text=" 标题 ")
        root = _FakeRoot(selectors={".question-title": [title_node]})
        assert await runtime_dom._question_title_text(page, root) == "标题"

        root_fallback = _FakeRoot()
        page_for_root = _FakePage()
        page_for_root.evaluate_result = "题面"
        assert await runtime_dom._question_title_text(page_for_root, root_fallback) == "题面"

        submit_item = _FakeLocatorItem(text="提交")
        next_item = _FakeLocatorItem(text="下一页")
        nav_page = _FakePage(
            locators={
                "button, a, [role='button'], input[type='button'], input[type='submit']": _FakeLocator([submit_item, next_item]),
            }
        )
        assert await runtime_dom._navigation_action(nav_page) == "submit"

        next_page = _FakePage(
            locators={
                "button, a, [role='button'], input[type='button'], input[type='submit']": _FakeLocator([_FakeLocatorItem(text="下一页")]),
            }
        )
        assert await runtime_dom._navigation_action(next_page) == "next"

        empty_page = _FakePage(
            locators={
                "button, a, [role='button'], input[type='button'], input[type='submit']": _FakeLocator([_FakeLocatorItem(text="帮助")]),
            }
        )
        assert await runtime_dom._navigation_action(empty_page) is None

    @pytest.mark.asyncio
    async def test_click_navigation_wait_for_page_change_and_click_submit_cover_fallbacks(self, monkeypatch) -> None:
        primary = _FakeLocatorItem(text="提交", click_error=RuntimeError("fail"), handle=object())
        fallback = _FakeLocatorItem(text="下一页", click_error=RuntimeError("fail"), handle=object())
        page = _FakePage(
            locators={
                "#credamo-submit-btn": _FakeLocator([primary]),
                "button, a, [role='button'], input[type='button'], input[type='submit']": _FakeLocator([fallback]),
            },
            evaluate_map={"el => { el.click(); return true; }": [True, True]},
        )
        assert await runtime_dom._click_navigation(page, "submit")

        page_next = _FakePage(
            locators={
                "#credamo-submit-btn": _FakeLocator([_FakeLocatorItem(text="继续", click_error=RuntimeError("fail"), handle=object())]),
                "button, a, [role='button'], input[type='button'], input[type='submit']": _FakeLocator([fallback]),
            },
            evaluate_map={"el => { el.click(); return true; }": [True]},
        )
        assert await runtime_dom._click_navigation(page_next, "next")

        failed_page = _FakePage(
            locators={
                "#credamo-submit-btn": _FakeLocator([]),
                "button, a, [role='button'], input[type='button'], input[type='submit']": _FakeLocator([_FakeLocatorItem(text="帮助", visible=True)]),
            }
        )
        assert not await runtime_dom._click_navigation(failed_page, "submit")

        signatures = iter([(("same", "x"),), (("changed", "y"),)])
        monkeypatch.setattr(runtime_dom, "_question_signature", lambda *_args, **_kwargs: _async_return(next(signatures))())
        assert await runtime_dom._wait_for_page_change(object(), (("same", "x"),), None, timeout_ms=20)

        same_signatures = iter([(("same", "x"),), (("same", "x"),)])
        monkeypatch.setattr(runtime_dom, "_question_signature", lambda *_args, **_kwargs: _async_return(next(same_signatures))())
        assert not await runtime_dom._wait_for_page_change(object(), (("same", "x"),), None, timeout_ms=1)

        click_results = iter([False, True])
        monkeypatch.setattr(runtime_dom, "_click_submit_once", lambda *_args, **_kwargs: _async_return(next(click_results))())
        assert await runtime_dom._click_submit(object(), timeout_ms=20)

        stop_signal = threading.Event()
        stop_signal.set()
        monkeypatch.setattr(runtime_dom, "_click_submit_once", lambda *_args, **_kwargs: _async_return(False)())
        assert not await runtime_dom._click_submit(object(), stop_signal, timeout_ms=1)


def _async_return(value=None):
    async def _runner(*_args, **_kwargs):
        return value

    return _runner
