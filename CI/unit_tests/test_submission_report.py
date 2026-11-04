from __future__ import annotations

import pytest

import software.network.submission_report as submission_report


class _Response:
    def raise_for_status(self) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("client_version", [None, "4.0.1"])
async def test_report_submission_result_posts_expected_payload(monkeypatch, client_version) -> None:
    calls: list[dict[str, object]] = []
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
        enabled=True,
        client_version=client_version,
    )

    kwargs = calls[0]["kwargs"]
    assert kwargs["json"] == {
        "user_id": 73952,
        "survey_url": "https://www.wjx.cn/vm/demo.aspx",
        "result": "success",
        "proxy_provider": "idiot",
        "client_version": client_version or "",
    }
    assert kwargs["headers"]["X-Device-ID"] == "device-1"


@pytest.mark.asyncio
async def test_report_submission_result_skips_when_setting_disabled(monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        submission_report.http_client,
        "apost",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert not await submission_report.report_submission_result_async(
        user_id=73952,
        survey_url="https://www.wjx.cn/vm/demo.aspx",
        result="failed",
        proxy_provider="default",
        enabled=False,
    )
    assert calls == []
