from __future__ import annotations

import pytest

from software.core.task import ExecutionConfig
from surveycore.providers.contracts import SurveyQuestionMeta
from surveycore.providers.errors import (
    SubmissionVerificationRequiredError,
    SurveyProviderUnavailableAtRuntimeError,
)
from software.providers.contracts import ProviderSubmissionRejectedError
from wjx.provider import http_runtime as wjx_http

from .http_runtime_fakes import _FakeResponse


def test_wjx_submit_rejected_message_includes_question_title_and_display_num() -> None:
    config = ExecutionConfig(url="https://www.wjx.cn/vm/demo.aspx", survey_provider="wjx")
    config.questions_metadata = {
        10: SurveyQuestionMeta(num=10, display_num=8, title="年龄", type_code="1"),
    }

    with pytest.raises(ProviderSubmissionRejectedError, match=r"第8题（年龄）.*答案不符合要求") as rejected:
        wjx_http._raise_submit_rejected(config, "9〒10〒您提交的答案不符合要求，请检查并修改后重新提交！")
    assert isinstance(rejected.value, RuntimeError)


def test_wjx_submit_rejected_message_uses_delimiter_split_without_regex() -> None:
    config = ExecutionConfig(url="https://www.wjx.cn/vm/demo.aspx", survey_provider="wjx")
    config.questions_metadata = {
        10: SurveyQuestionMeta(num=10, display_num=8, title="年龄", type_code="1"),
    }

    with pytest.raises(ProviderSubmissionRejectedError, match=r"第8题（年龄）.*格式错误"):
        wjx_http._raise_submit_rejected(config, " 9 〒 10 〒 格式错误 ")


def test_wjx_submit_rejected_detects_submission_verification() -> None:
    config = ExecutionConfig(url="https://www.wjx.cn/vm/demo.aspx", survey_provider="wjx")

    assert wjx_http.is_wjx_submission_verification_response("7〒需要安全校验，请重新提交！")
    assert wjx_http.is_wjx_submission_verification_response("22〒请输入验证码")
    assert not wjx_http.is_wjx_submission_verification_response("请先完成智能验证")
    assert not wjx_http.is_wjx_submission_verification_response("请先完成验证码校验后重新提交")

    with pytest.raises(SubmissionVerificationRequiredError, match="启用随机 IP"):
        wjx_http._raise_submit_rejected(config, "7〒需要安全校验，请重新提交！")
    with pytest.raises(SubmissionVerificationRequiredError, match="启用随机 IP"):
        wjx_http._raise_submit_rejected(config, "22〒请输入验证码")

    with pytest.raises(SubmissionVerificationRequiredError, match="更换随机 IP"):
        wjx_http._raise_submit_rejected(
            config,
            "7〒需要安全校验，请重新提交！",
            proxy_address="http://1.1.1.1:80",
        )


def test_wjx_submit_response_classifier_keeps_verification_strict() -> None:
    assert wjx_http.classify_wjx_submit_response("10〒/joinnew/complete.aspx") == wjx_http.WjxSubmitResult.SUCCESS
    assert wjx_http.classify_wjx_submit_response("success") == wjx_http.WjxSubmitResult.SUCCESS
    assert wjx_http.classify_wjx_submit_response("7〒需要安全校验，请重新提交！") == wjx_http.WjxSubmitResult.VERIFICATION
    assert wjx_http.classify_wjx_submit_response("22〒请输入验证码") == wjx_http.WjxSubmitResult.VERIFICATION
    assert wjx_http.classify_wjx_submit_response("请先完成智能验证") == wjx_http.WjxSubmitResult.REJECTED
    assert wjx_http.classify_wjx_submit_response("9〒10〒您提交的答案不符合要求，请检查并修改后重新提交！") == wjx_http.WjxSubmitResult.REJECTED


@pytest.mark.asyncio
async def test_wjx_http_runtime_converts_status_page_to_runtime_stop(monkeypatch) -> None:
    async def fake_get(*_args, **_kwargs):
        return _FakeResponse(text="<html><body>此问卷（123）已暂停，不能填写</body></html>")

    monkeypatch.setattr(wjx_http.http_client, "aget", fake_get)

    with pytest.raises(SurveyProviderUnavailableAtRuntimeError, match="问卷已暂停"):
        await wjx_http._load_wjx_page(
            "https://www.wjx.cn/vm/demo.aspx",
            headers={},
            proxies={},
        )
