from __future__ import annotations

import pytest

from software.app.config import SUBMISSION_REPORT_TELEMETRY_SETTING_KEY, app_settings
from software.network import submission_report


class _Response:
    def raise_for_status(self) -> None:
        return None


class SubmissionReportTests:
    def test_build_payload_normalizes_provider_and_result(self, monkeypatch) -> None:
        monkeypatch.setattr(submission_report, "get_device_id", lambda: "device-1")

        payload = submission_report.build_submission_report_payload(
            survey_url="https://wjx.cn/vm/demo.aspx",
            result="bad",
            proxy_provider="benefit",
            user_id=12,
        )

        assert payload["user_id"] == 12
        assert payload["device_id"] == "device-1"
        assert payload["result"] == "failed"
        assert payload["proxy_provider"] == "idiot"
        assert payload["survey_url"] == "https://wjx.cn/vm/demo.aspx"
        assert payload["app_version"]

    @pytest.mark.asyncio
    async def test_report_skips_when_telemetry_disabled(self, monkeypatch) -> None:
        app_settings().setValue(SUBMISSION_REPORT_TELEMETRY_SETTING_KEY, False)
        calls: list[object] = []

        async def fake_post(*args, **kwargs):
            calls.append((args, kwargs))
            return _Response()

        monkeypatch.setattr(submission_report.http_client, "apost", fake_post)

        sent = await submission_report.report_submission_result_async(
            survey_url="https://wjx.cn/vm/demo.aspx",
            result="success",
            proxy_provider="default",
            user_id=12,
        )

        assert sent is False
        assert calls == []

    @pytest.mark.asyncio
    async def test_report_posts_payload_and_json_header_when_enabled(self, monkeypatch) -> None:
        app_settings().setValue(SUBMISSION_REPORT_TELEMETRY_SETTING_KEY, True)
        calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        monkeypatch.setattr(submission_report, "get_device_id", lambda: "device-1")

        async def fake_post(*args, **kwargs):
            calls.append((args, kwargs))
            return _Response()

        monkeypatch.setattr(submission_report.http_client, "apost", fake_post)

        sent = await submission_report.report_submission_result_async(
            survey_url="https://wjx.cn/vm/demo.aspx",
            result="success",
            proxy_provider="default",
            user_id=12,
        )

        assert sent is True
        assert len(calls) == 1
        _, kwargs = calls[0]
        assert kwargs["json"]["user_id"] == 12
        assert kwargs["json"]["device_id"] == "device-1"
        assert kwargs["json"]["result"] == "success"
        assert kwargs["json"]["proxy_provider"] == "default"
        assert kwargs["headers"]["Content-Type"] == "application/json"

