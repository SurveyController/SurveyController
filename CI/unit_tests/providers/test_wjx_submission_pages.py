from __future__ import annotations

import pytest

from wjx.provider import submission_pages


class _FakeDriver:
    def __init__(self, *, script_result=None, script_error: Exception | None = None, current_url: str = "") -> None:
        self.script_result = script_result
        self.script_error = script_error
        self._current_url = current_url
        self.scripts: list[str] = []

    async def execute_script(self, script: str):
        self.scripts.append(script)
        if self.script_error is not None:
            raise self.script_error
        return self.script_result

    async def current_url(self) -> str:
        return self._current_url


class WjxSubmissionPagesTests:
    def test_resolve_completion_url_supports_absolute_root_and_relative_values(self) -> None:
        submit_url = "https://www.wjx.cn/joinnew/processjq.ashx"
        assert submission_pages._resolve_completion_url(submit_url, "https://www.wjx.cn/complete.aspx") == "https://www.wjx.cn/complete.aspx"
        assert submission_pages._resolve_completion_url(submit_url, "/complete.aspx") == "https://www.wjx.cn/complete.aspx"
        assert submission_pages._resolve_completion_url(submit_url, "complete.aspx") == "https://www.wjx.cn/complete.aspx"

    def test_normalize_url_for_compare_strips_fragment_and_whitespace(self) -> None:
        assert (
            submission_pages._normalize_url_for_compare(" https://www.wjx.cn/vm/demo.aspx#hash ")
            == "https://www.wjx.cn/vm/demo.aspx"
        )
        assert submission_pages._normalize_url_for_compare(None) == ""

    def test_is_wjx_domain_accepts_subdomain_and_rejects_other_host(self) -> None:
        assert submission_pages._is_wjx_domain("https://sub.wjx.cn/vm/demo.aspx")
        assert not submission_pages._is_wjx_domain("https://example.com/vm/demo.aspx")

    def test_looks_like_wjx_survey_url_rejects_completion_page_and_non_aspx(self) -> None:
        assert submission_pages._looks_like_wjx_survey_url("https://www.wjx.cn/vm/demo.aspx")
        assert not submission_pages._looks_like_wjx_survey_url("https://www.wjx.cn/complete.aspx")
        assert not submission_pages._looks_like_wjx_survey_url("https://www.wjx.cn/api/demo")

    @pytest.mark.asyncio
    async def test_page_looks_like_wjx_questionnaire_returns_false_when_script_fails(self) -> None:
        driver = _FakeDriver(script_error=RuntimeError("js boom"))
        assert not await submission_pages._page_looks_like_wjx_questionnaire(driver)

    @pytest.mark.asyncio
    async def test_page_looks_like_wjx_questionnaire_returns_script_result(self) -> None:
        driver = _FakeDriver(script_result=True)
        assert await submission_pages._page_looks_like_wjx_questionnaire(driver)

    @pytest.mark.asyncio
    async def test_is_device_quota_limit_page_returns_false_when_script_fails(self) -> None:
        driver = _FakeDriver(script_error=RuntimeError("js boom"))
        assert not await submission_pages._is_device_quota_limit_page(driver)

    @pytest.mark.asyncio
    async def test_is_device_quota_limit_page_returns_script_result(self) -> None:
        driver = _FakeDriver(script_result=True)
        assert await submission_pages._is_device_quota_limit_page(driver)

    @pytest.mark.asyncio
    async def test_is_completion_page_short_circuits_complete_url(self) -> None:
        driver = _FakeDriver(current_url="https://www.wjx.cn/complete.aspx")
        assert await submission_pages.is_completion_page(driver)
