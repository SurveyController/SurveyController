from __future__ import annotations

import ssl
from threading import Event

import httpx
import pytest
from surveycore.providers.answering import AnswerAction
from surveycore.providers.contracts import SurveyQuestionMeta
from surveycore.providers.errors import SurveyProviderUnavailableAtRuntimeError

from software.core.task import ExecutionConfig, ExecutionState
from wjx.provider import http_runtime

_HTTPS_SUBMIT_URL = "https://v.wjx.cn/joinnew/processjq.ashx"
_HTTP_SUBMIT_URL = "http://v.wjx.cn/joinnew/processjq.ashx"
_PROXY = "http://proxy.example.test:8080"


@pytest.fixture
def submit_wjx(monkeypatch):
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx?private=value",
        survey_provider="wjx",
        random_proxy_ip_enabled=True,
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(num=1, title="Q1", type_code="3", options=2, option_texts=["A", "B"]),
    }
    state = ExecutionState(config=config)

    async def load_page(*_args, **_kwargs):
        return "<html></html>"

    async def build_answer(*_args, **_kwargs):
        return AnswerAction(
            question_num=1, kind="choice", selected_indices=(0,), record_type="single"
        )

    monkeypatch.setattr(http_runtime, "_load_wjx_page", load_page)
    monkeypatch.setattr(http_runtime, "build_answer_action", build_answer)

    async def submit(**kwargs):
        return await http_runtime.brush_wjx_http(config, state, proxy_address=_PROXY, **kwargs)

    return submit


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [httpx.ProxyError, httpx.ConnectTimeout, httpx.ConnectError])
async def test_falls_back_after_connection_failure_without_probe(
    monkeypatch, submit_wjx, error_type
) -> None:
    calls = []

    async def post(url, **kwargs):
        calls.append(("POST", url, kwargs))
        if url == _HTTPS_SUBMIT_URL:
            raise error_type("connection failed")
        return httpx.Response(200, text="success", request=httpx.Request("POST", url))

    async def unexpected_request(*_args, **_kwargs):
        pytest.fail("回落前不应发送探测请求")

    monkeypatch.setattr(http_runtime.http_client, "apost", post)
    monkeypatch.setattr(http_runtime.http_client, "arequest", unexpected_request)

    assert await submit_wjx()
    assert [(method, url) for method, url, _ in calls] == [
        ("POST", _HTTPS_SUBMIT_URL),
        ("POST", _HTTP_SUBMIT_URL),
    ]
    https, fallback = [kwargs for _, _, kwargs in calls]
    assert all(kwargs["proxies"] == _PROXY for _, _, kwargs in calls)
    assert https["allow_redirects"] is False
    assert fallback["allow_redirects"] is False
    assert fallback["data"] == https["data"] == {"submitdata": "1$1", "sceneId": "q0hcfsca"}
    assert fallback["params"] == https["params"]
    assert fallback["headers"]["Origin"] == "http://v.wjx.cn"
    assert fallback["headers"]["Referer"] == "http://www.wjx.cn/vm/demo.aspx?private=value"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 426])
async def test_http_rejection_is_reported_without_another_post(
    monkeypatch, submit_wjx, status
) -> None:
    sent_urls = []

    async def post(url, **_kwargs):
        sent_urls.append(url)
        if url == _HTTPS_SUBMIT_URL:
            raise httpx.ProxyError("631 Internal Server Error")
        return httpx.Response(status, request=httpx.Request("POST", url))

    monkeypatch.setattr(http_runtime.http_client, "apost", post)

    with pytest.raises(httpx.HTTPStatusError) as error:
        await submit_wjx()
    assert error.value.response.status_code == status
    assert sent_urls == [_HTTPS_SUBMIT_URL, _HTTP_SUBMIT_URL]


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.RemoteProtocolError])
async def test_submission_uncertainty_does_not_fall_back(
    monkeypatch, submit_wjx, error_type
) -> None:
    async def post(url, **_kwargs):
        assert url == _HTTPS_SUBMIT_URL
        raise error_type("response interrupted")

    monkeypatch.setattr(http_runtime.http_client, "apost", post)

    with pytest.raises(error_type):
        await submit_wjx()


@pytest.mark.asyncio
async def test_bad_certificate_does_not_fall_back(monkeypatch, submit_wjx) -> None:
    cert_error = ssl.SSLCertVerificationError("certificate verification failed")
    calls = []

    async def post(url, **kwargs):
        calls.append((url, kwargs))
        if url == _HTTPS_SUBMIT_URL:
            raise httpx.ConnectError("TLS failed") from cert_error
        return httpx.Response(200, text="success", request=httpx.Request("POST", url))

    monkeypatch.setattr(http_runtime.http_client, "apost", post)

    with pytest.raises(http_runtime.SubmissionConnectionError) as error:
        await submit_wjx()
    assert isinstance(error.value.__cause__, httpx.ConnectError)
    assert [call[0] for call in calls] == [_HTTPS_SUBMIT_URL]


@pytest.mark.asyncio
async def test_stop_during_https_connection_prevents_http_post(monkeypatch, submit_wjx) -> None:
    signal = Event()
    sent_urls = []

    async def post(url, **_kwargs):
        sent_urls.append(url)
        signal.set()
        raise httpx.ProxyError("631 Internal Server Error")

    monkeypatch.setattr(http_runtime.http_client, "apost", post)

    assert not await submit_wjx(stop_signal=signal)
    assert signal.is_set()
    assert sent_urls == [_HTTPS_SUBMIT_URL]


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", [False, True])
async def test_submit_redirect_stops_without_following_it(
    monkeypatch, submit_wjx, fallback
) -> None:
    sent_urls = []

    async def post(url, **kwargs):
        assert kwargs["allow_redirects"] is False
        sent_urls.append(url)
        if fallback and url == _HTTPS_SUBMIT_URL:
            raise httpx.ProxyError("631 Internal Server Error")
        return httpx.Response(
            307,
            headers={"Location": _HTTPS_SUBMIT_URL},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(http_runtime.http_client, "apost", post)

    with pytest.raises(SurveyProviderUnavailableAtRuntimeError):
        await submit_wjx()
    assert sent_urls == ([_HTTPS_SUBMIT_URL, _HTTP_SUBMIT_URL] if fallback else [_HTTPS_SUBMIT_URL])
