from __future__ import annotations

import pytest

from wjx.provider import navigation


class _FakeTarget:
    def __init__(self, *, text: str = "", visible: bool = True, click_ok: bool = True) -> None:
        self._text = text
        self._visible = visible
        self._click_ok = click_ok
        self.clicked = 0

    async def is_visible(self) -> bool:
        return self._visible

    async def inner_text(self) -> str:
        return self._text

    async def scroll_into_view_if_needed(self, timeout: int = 0) -> None:
        del timeout

    async def click(self, timeout: int = 0, force: bool = False) -> None:
        del timeout, force
        if not self._click_ok:
            raise RuntimeError("click failed")
        self.clicked += 1


class _FakeLocator:
    def __init__(self, targets: list[_FakeTarget]) -> None:
        self._targets = list(targets)

    @property
    def first(self) -> "_FakeLocator":
        if not self._targets:
            return _FakeLocator([])
        return _FakeLocator([self._targets[0]])

    async def count(self) -> int:
        return len(self._targets)

    def nth(self, index: int) -> _FakeTarget:
        return self._targets[index]


class _FakePage:
    def __init__(self, mapping: dict[str, list[_FakeTarget]]) -> None:
        self._mapping = {key: list(value) for key, value in mapping.items()}

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self._mapping.get(selector, []))


class _FakeDriver:
    def __init__(self, page: _FakePage, *, body_text: str = "", script_results: dict[str, object] | None = None) -> None:
        self._page_obj = page
        self._body_text = body_text
        self._script_results = dict(script_results or {})

    async def page(self) -> _FakePage:
        return self._page_obj

    async def execute_script(self, script: str, *args):
        del args
        if "document.body?.innerText" in script:
            return self._body_text
        for marker, result in self._script_results.items():
            if marker in script:
                return result
        return False


class WjxNavigationTests:
    @pytest.mark.asyncio
    async def test_dismiss_resume_dialog_ignores_empty_text_buttons_without_dialog_marker(self, monkeypatch) -> None:
        empty_button = _FakeTarget(text="")
        page = _FakePage({"button": [empty_button]})
        driver = _FakeDriver(page, body_text="普通题目页面")

        async def _sleep(*_args, **_kwargs):
            return False

        monkeypatch.setattr(navigation, "sleep_or_stop", _sleep)

        closed = await navigation.dismiss_resume_dialog_if_present(driver, timeout=0.1, stop_signal=None)

        assert closed is False
        assert empty_button.clicked == 0

    @pytest.mark.asyncio
    async def test_dismiss_resume_dialog_clicks_named_action_when_dialog_marker_exists(self, monkeypatch) -> None:
        cancel_button = _FakeTarget(text="取消")
        page = _FakePage({"button": [cancel_button]})
        driver = _FakeDriver(page, body_text="继续上次作答")

        async def _sleep(*_args, **_kwargs):
            return False

        monkeypatch.setattr(navigation, "sleep_or_stop", _sleep)

        closed = await navigation.dismiss_resume_dialog_if_present(driver, timeout=0.1, stop_signal=None)

        assert closed is True
        assert cancel_button.clicked == 1

    @pytest.mark.asyncio
    async def test_dismiss_resume_dialog_clicks_english_restart_survey_action(self, monkeypatch) -> None:
        restart_button = _FakeTarget(text="Restart survey")
        page = _FakePage({"button": [restart_button]})
        driver = _FakeDriver(page, body_text="Continue previous answers")

        async def _sleep(*_args, **_kwargs):
            return False

        monkeypatch.setattr(navigation, "sleep_or_stop", _sleep)

        closed = await navigation.dismiss_resume_dialog_if_present(driver, timeout=0.1, stop_signal=None)

        assert closed is True
        assert restart_button.clicked == 1

    @pytest.mark.asyncio
    async def test_try_click_start_answer_button_falls_back_to_text_button(self, monkeypatch) -> None:
        start_button = _FakeTarget(text="开始作答")
        page = _FakePage({"button": [start_button]})
        driver = _FakeDriver(page, body_text="开始作答")

        async def _sleep(*_args, **_kwargs):
            return False

        monkeypatch.setattr(navigation, "sleep_or_stop", _sleep)

        clicked = await navigation.try_click_start_answer_button(driver, timeout=0.1, stop_signal=None)

        assert clicked is True
        assert start_button.clicked == 1

    @pytest.mark.asyncio
    async def test_click_next_page_button_ignores_empty_text_button(self, monkeypatch) -> None:
        empty_button = _FakeTarget(text="")
        page = _FakePage({"button": [empty_button]})
        driver = _FakeDriver(page, body_text="普通题目页面")

        async def _page_number(_driver):
            return 1

        async def _wait_page_change(_driver, previous_page_number: int, *, timeout_ms: int = 5000):
            del previous_page_number, timeout_ms
            return False

        monkeypatch.setattr(navigation, "_resolve_current_page_number", _page_number)
        monkeypatch.setattr(navigation, "_wait_for_page_number_change", _wait_page_change)

        clicked = await navigation._click_next_page_button(driver)

        assert clicked is False
        assert empty_button.clicked == 0

    @pytest.mark.asyncio
    async def test_click_next_page_button_accepts_named_button_fallback(self, monkeypatch) -> None:
        next_button = _FakeTarget(text="下一页")
        page = _FakePage({"button": [next_button]})
        driver = _FakeDriver(page, body_text="下一页")

        async def _page_number(_driver):
            return 1

        async def _wait_page_change(_driver, previous_page_number: int, *, timeout_ms: int = 5000):
            del previous_page_number, timeout_ms
            return True

        monkeypatch.setattr(navigation, "_resolve_current_page_number", _page_number)
        monkeypatch.setattr(navigation, "_wait_for_page_number_change", _wait_page_change)

        clicked = await navigation._click_next_page_button(driver)

        assert clicked is True
        assert next_button.clicked == 1
