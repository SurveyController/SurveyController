from __future__ import annotations

import asyncio
from types import SimpleNamespace

import software.app.random_ip_health_adapter as health_adapter
from software.network.http.defaults import DEFAULT_HTTP_HEADERS


def test_health_adapter_preserves_endpoint_headers_payload_and_timeout(monkeypatch) -> None:
    requests: list[tuple[str, dict[str, object]]] = []

    async def post(url: str, **kwargs: object) -> SimpleNamespace:
        requests.append((url, kwargs))
        return SimpleNamespace(status_code=204)

    monkeypatch.setattr(health_adapter.http_client, "apost", post)

    result = asyncio.run(health_adapter.PythonRandomIpHealthAdapter().check())

    assert len(requests) == 1
    url, kwargs = requests[0]
    assert url == health_adapter.IP_EXTRACT_ENDPOINT
    assert kwargs["json"] == {}
    assert kwargs["timeout"] == 5
    assert kwargs["headers"] == {
        **DEFAULT_HTTP_HEADERS,
        "X-Health-Token": "status-rzib9lqpuk3httr4",
        "Content-Type": "application/json",
    }
    assert result["level"] == "success"
    assert result["text"].startswith("服务正常 ")
    assert result["tooltip"].startswith("随机IP提取接口返回 HTTP 204，耗时 ")


def test_health_adapter_classifies_non_success_http_status(monkeypatch) -> None:
    async def post(_url: str, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(status_code=503)

    monkeypatch.setattr(health_adapter.http_client, "apost", post)

    result = asyncio.run(health_adapter.PythonRandomIpHealthAdapter().check())

    assert result["level"] == "error"
    assert result["text"].startswith("异常 503")
    assert result["tooltip"].startswith("随机IP提取接口返回 HTTP 503，耗时 ")
