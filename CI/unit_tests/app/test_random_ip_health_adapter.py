from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

import software.app.random_ip_health_adapter as health_adapter

_STATUS_URL = "https://status.hungrym0.com/api/status-page/heartbeat/surveycontroller"
_NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


@pytest.fixture
def status_page(monkeypatch):
    requests = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return _NOW

    monkeypatch.setattr(health_adapter, "datetime", Clock, raising=False)

    async def forbidden_probe(*_args, **_kwargs):
        pytest.fail("状态查询不得调用代理提取接口")

    monkeypatch.setattr(health_adapter.http_client, "apost", forbidden_probe)

    def check(payload, status_code=200):
        async def get(url, **kwargs):
            requests.append((url, kwargs))
            return httpx.Response(status_code, json=payload, request=httpx.Request("GET", url))

        monkeypatch.setattr(health_adapter.http_client, "aget", get)
        return asyncio.run(health_adapter.PythonRandomIpHealthAdapter().check())

    return check, requests


@pytest.mark.parametrize(
    ("status", "level", "text"),
    [
        (0, "error", "服务异常"),
        (1, "success", "服务正常"),
        (2, "warning", "检测中"),
        (3, "warning", "维护中"),
    ],
)
def test_status_page_maps_random_ip_monitor_state(status_page, status, level, text):
    check, requests = status_page
    payload = {
        "heartbeatList": {
            "1": [{"status": 1, "time": "2026-11-13 12:00:00"}],
            "12": [
                {"status": 1, "time": "2026-11-13 11:59:30", "ping": 15},
                {"status": status, "time": "2026-11-13 12:00:00", "ping": 42},
            ],
        }
    }

    result = check(payload)

    assert result["level"] == level
    assert result["text"].startswith(text)
    assert "2026-11-13 12:00:00 UTC" in result["tooltip"]
    assert requests[0][0] == _STATUS_URL
    assert requests[0][1]["timeout"] == 5
    assert "Authorization" not in requests[0][1]["headers"]
    assert "X-Health-Token" not in requests[0][1]["headers"]
    assert "json" not in requests[0][1]


@pytest.mark.parametrize("heartbeats", [{}, {"12": []}])
def test_missing_random_ip_heartbeat_is_unknown(status_page, heartbeats):
    check, _requests = status_page

    result = check({"heartbeatList": heartbeats})

    assert result["level"] == "warning"
    assert result["text"] == "状态未知"


def test_stale_heartbeat_cannot_report_service_normal(status_page):
    check, _requests = status_page
    heartbeat = {"status": 1, "time": (_NOW - timedelta(minutes=6)).isoformat()}

    result = check({"heartbeatList": {"12": [heartbeat]}})

    assert result["level"] == "warning"
    assert result["text"] == "状态未知"
    assert "未更新" in result["tooltip"]


@pytest.mark.parametrize(
    "payload", [[], {}, {"heartbeatList": []}, {"heartbeatList": {"12": "bad"}}]
)
def test_malformed_status_page_response_is_rejected(status_page, payload):
    check, _requests = status_page

    with pytest.raises(ValueError):
        check(payload)


def test_status_page_http_failure_is_not_reported_as_success(status_page):
    check, _requests = status_page

    with pytest.raises(httpx.HTTPStatusError):
        check({"detail": "unavailable"}, status_code=503)
