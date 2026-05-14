from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from software.core.task import ProxyLease
from software.network.proxy.api import provider
from software.network.proxy.policy import source as proxy_source


class _Response:
    def __init__(self, text: str = "", payload: object | None = None, status_code: int = 200) -> None:
        self.text = text
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            error = RuntimeError(f"HTTP {self.status_code}")
            setattr(error, "response", self)
            raise error


class ProxyApiProviderTests:
    def test_status_payload_formats_online_offline_and_unknown_states(self) -> None:
        assert provider.format_status_payload({"online": True}) == ("在线：系统正常运行中", "#228B22")
        assert provider.format_status_payload({"online": False, "message": "维护中"}) == ("离线：维护中", "#cc0000")
        assert provider.format_status_payload([]) == ("未知：返回数据格式异常", "#666666")

    def test_parse_proxy_payload_deduplicates_nested_proxy_addresses(self) -> None:
        text = """
        {
          "items": [
            {"ip": "1.1.1.1", "port": "8000", "account": "u", "password": "p"},
            "http://2.2.2.2:9000",
            {"nested": {"proxy": "u:p@1.1.1.1:8000"}}
          ]
        }
        """

        assert provider._parse_proxy_payload(text) == ["u:p@1.1.1.1:8000", "2.2.2.2:9000"]

    def test_parse_proxy_payload_reports_bad_json_and_empty_result(self) -> None:
        with pytest.raises(ValueError, match="JSON解析失败"):
            provider._parse_proxy_payload("{")
        with pytest.raises(ValueError, match="无有效代理地址"):
            provider._parse_proxy_payload('{"items": []}')

    def test_custom_api_validation_handles_scheme_network_errors_and_fatal_payloads(self, patch_attrs) -> None:
        assert provider.test_custom_proxy_api("") == (False, "API地址不能为空", [])
        assert provider.test_custom_proxy_api("ftp://bad") == (False, "API地址必须以 http:// 或 https:// 开头", [])

        patch_attrs(
            (
                provider.http_client,
                "get",
                lambda *_args, **_kwargs: _Response('{"code": 1, "message": "套餐余量不足"}'),
            )
        )
        assert provider.test_custom_proxy_api("https://proxy.example/api") == (False, "套餐余量不足，请充值", [])

    def test_custom_api_validation_returns_warning_and_proxies(self, patch_attrs) -> None:
        patch_attrs(
            (provider, "get_proxy_occupy_minute", lambda: 5),
            (
                provider.http_client,
                "get",
                lambda *_args, **_kwargs: _Response('{"data": ["3.3.3.3:7000"]}'),
            ),
        )

        ok, warning, proxies = provider.test_custom_proxy_api("https://proxy.example/api?minute=1")

        assert ok is True
        assert "小于当前建议值" in warning
        assert proxies == ["3.3.3.3:7000"]

    def test_custom_api_validation_does_not_require_minute_parameter(self, patch_attrs) -> None:
        patch_attrs(
            (provider, "get_proxy_occupy_minute", lambda: 5),
            (
                provider.http_client,
                "get",
                lambda *_args, **_kwargs: _Response('{"data": ["3.3.3.3:7000"]}'),
            ),
        )

        ok, warning, proxies = provider.test_custom_proxy_api("https://proxy.example/api")

        assert ok is True
        assert warning == ""
        assert proxies == ["3.3.3.3:7000"]

    def test_fetch_custom_proxy_batch_uses_candidate_urls_and_normalizes_leases(self, patch_attrs) -> None:
        original_source = proxy_source.get_proxy_source()
        original_override = proxy_source.get_custom_proxy_api_override()
        try:
            proxy_source.set_proxy_source(proxy_source.PROXY_SOURCE_CUSTOM)
            proxy_source.set_proxy_api_override("https://proxy.example/api")
            calls: list[str] = []

            async def fake_get(url: str, **_kwargs):
                calls.append(url)
                if url.endswith("num=2"):
                    raise RuntimeError("first candidate failed")
                return _Response('{"items": ["4.4.4.4:8000", "5.5.5.5:8000", "4.4.4.4:8000"]}')

            patch_attrs((provider.http_client, "aget", fake_get))

            leases = asyncio.run(provider.fetch_proxy_batch_async(expected_count=2))

            assert calls == ["https://proxy.example/api?num=2", "https://proxy.example/api"]
            assert [lease.address for lease in leases] == ["http://4.4.4.4:8000", "http://5.5.5.5:8000"]
            assert all(isinstance(lease, ProxyLease) for lease in leases)
        finally:
            proxy_source.set_proxy_source(original_source)
            proxy_source.set_proxy_api_override(original_override)

    def test_fetch_custom_proxy_batch_sets_stop_signal_on_fatal_error(self, patch_attrs) -> None:
        original_source = proxy_source.get_proxy_source()
        original_override = proxy_source.get_custom_proxy_api_override()
        try:
            proxy_source.set_proxy_source(proxy_source.PROXY_SOURCE_CUSTOM)
            proxy_source.set_proxy_api_override("https://proxy.example/api")
            stop_signal = threading.Event()
            popups: list[tuple[str, str]] = []
            async def fake_get(*_args, **_kwargs):
                return _Response('{"code": 2, "message": "白名单错误"}')
            patch_attrs(
                (provider.http_client, "aget", fake_get),
                (provider, "log_popup_error", lambda title, message: popups.append((title, message))),
            )

            with pytest.raises(provider.ProxyApiFatalError, match="白名单"):
                asyncio.run(provider.fetch_proxy_batch_async(expected_count=1, stop_signal=stop_signal))

            assert stop_signal.is_set()
            assert popups == [("代理API错误", "请先添加当前IP到代理商白名单")]
        finally:
            proxy_source.set_proxy_source(original_source)
            proxy_source.set_proxy_api_override(original_override)

    def test_official_batch_fetch_builds_leases_from_backend_payload(self, patch_attrs) -> None:
        async def fake_extract_proxy(**_kwargs):
            return {
                "provider": "default",
                "items": [
                    {
                        "host": "6.6.6.6",
                        "port": 9000,
                        "account": "u",
                        "password": "p",
                        "expire_at": "2099-01-01T00:00:00+00:00",
                    },
                    {
                        "host": "7.7.7.7",
                        "port": 9001,
                        "expire_at": "2099-01-01T00:00:00+00:00",
                    },
                ],
            }
        patch_attrs(
            (provider, "get_proxy_source", lambda: provider.PROXY_SOURCE_DEFAULT),
            (provider, "is_custom_proxy_source", lambda _source: False),
            (provider, "is_official_proxy_source", lambda _source: True),
            (provider, "get_proxy_area_code", lambda: "110100"),
            (provider, "get_proxy_occupy_minute", lambda: 3),
            (provider, "get_proxy_upstream", lambda _source: provider.PROXY_UPSTREAM_DEFAULT),
            (provider, "_resolve_default_pool_by_area", lambda _area: "quality"),
            (provider, "_resolve_official_area_request_value", lambda _source, _area: "110100"),
            (provider, "extract_proxy_async", fake_extract_proxy),
        )

        leases = asyncio.run(provider.fetch_proxy_batch_async(expected_count=2))

        assert [lease.address for lease in leases] == [
            "http://u:p@6.6.6.6:9000",
            "http://7.7.7.7:9001",
        ]

    def test_area_quality_retry_payload_notifies_and_stops(self, patch_attrs) -> None:
        stop_signal = threading.Event()
        calls: list[tuple[str, str]] = []
        patch_attrs((provider, "log_popup_error", lambda title, message: calls.append((title, message))))

        provider._handle_area_quality_failure(stop_signal)

        assert stop_signal.is_set()
        assert calls == [("地区代理不可用", "当前地区IP质量差，建议切换其他地区")]
        assert provider._is_area_quality_retry_payload({"code": "-1", "status": "200", "message": "请重试", "data": None})
        assert not provider._is_area_quality_retry_payload(SimpleNamespace())
