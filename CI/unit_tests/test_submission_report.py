from __future__ import annotations

from types import SimpleNamespace

import pytest

import software.network.submission_report as submission_report


class _Settings:
    def __init__(self, value) -> None:
        self._value = value

    def value(self, _key: str):
        return self._value


class _Response:
    def raise_for_status(self) -> None:
        return None


@pytest.mark.asyncio
async def test_report_submission_result_posts_expected_payload(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(submission_report, "app_settings", lambda: _Settings(True))
    monkeypatch.setattr(submission_report, "get_device_id", lambda: "device-1")

    async def fake_post(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return _Response()

    monkeypatch.setattr(submission_report.http_client, "apost", fake_post)

    assert await submission_report.report_submission_result_async(
        user_id="73952",
        survey_url="https://www.wjx.cn/vm/demo.aspx",
        result="success",
        proxy_provider="benefit",
        client_version="4.0.1",
    )

    kwargs = calls[0]["kwargs"]
    assert kwargs["json"] == {
        "user_id": 73952,
        "survey_url": "https://www.wjx.cn/vm/demo.aspx",
        "result": "success",
        "proxy_provider": "idiot",
        "client_version": "4.0.1",
    }
    assert kwargs["headers"]["X-Device-ID"] == "device-1"


@pytest.mark.asyncio
async def test_report_submission_result_skips_when_setting_disabled(monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(submission_report, "app_settings", lambda: _Settings(False))
    monkeypatch.setattr(
        submission_report.http_client,
        "apost",
        lambda *args, **kwargs: calls.append(SimpleNamespace(args=args, kwargs=kwargs)),
    )

    assert not await submission_report.report_submission_result_async(
        user_id=73952,
        survey_url="https://www.wjx.cn/vm/demo.aspx",
        result="failed",
        proxy_provider="default",
    )
    assert calls == []
