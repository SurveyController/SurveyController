from __future__ import annotations

import pytest

from tencent.provider import runtime_flow


class _FakePage:
    def __init__(self, message: str) -> None:
        self.message = message
        self.calls: list[list[str]] = []

    async def evaluate(self, _script: str, markers):
        self.calls.append(list(markers))
        return self.message


class _FakeDriver:
    def __init__(self, page: _FakePage) -> None:
        self._page = page

    async def page(self):
        return self._page


class TencentRuntimeFlowTests:
    @pytest.mark.asyncio
    async def test_submission_validation_message_prefers_verification_markers(self, monkeypatch) -> None:
        page = _FakePage("请先完成验证 | 滑动验证")
        driver = _FakeDriver(page)

        async def _page_factory(_driver):
            return page

        monkeypatch.setattr(runtime_flow, "_page", _page_factory)

        message = await runtime_flow.qq_submission_validation_message(driver)

        assert message == "请先完成验证 | 滑动验证"
        assert page.calls == [list(runtime_flow.QQ_VERIFICATION_MARKERS)]
