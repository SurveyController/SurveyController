from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from software.core.task import ProxyLease
from software.network.proxy.sidecar_client import ProxySidecarClient, ProxySidecarError
from software.network.proxy.sidecar_manager import resolve_sidecar_binary_path
import software.network.proxy.sidecar_manager as sidecar_manager


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class ProxySidecarClientTests:
    def test_acquire_release_and_health_check_use_expected_http_contract(self) -> None:
        requests: list[dict[str, object]] = []

        def fake_request(method, url, *, json=None, timeout=None, proxies=None):
            requests.append(
                {
                    "method": method,
                    "url": url,
                    "json": json,
                    "timeout": timeout,
                    "proxies": proxies,
                }
            )
            if url.endswith("/lease/acquire"):
                return _FakeResponse(payload={"lease": {"address": "1.1.1.1:8000", "expire_at": "", "expire_ts": 0, "poolable": True, "source": "custom"}})
            if url.endswith("/lease/release"):
                return _FakeResponse(payload={"lease": {"address": "http://1.1.1.1:8000", "expire_at": "", "expire_ts": 0, "poolable": True, "source": "custom"}})
            if url.endswith("/health/check"):
                return _FakeResponse(payload={"responsive": True})
            return _FakeResponse(payload={"ok": True})

        client = ProxySidecarClient("http://127.0.0.1:19010")
        with patch("software.network.proxy.sidecar_client.http_client.request", side_effect=fake_request):
            acquired = client.acquire_lease(thread_name="Worker-1", wait=True)
            released = client.release_lease(thread_name="Worker-1", requeue=False)
            healthy = client.check_health("1.1.1.1:8000")

        assert acquired == ProxyLease(address="http://1.1.1.1:8000", expire_at="", expire_ts=0.0, poolable=True, source="custom")
        assert released == ProxyLease(address="http://1.1.1.1:8000", expire_at="", expire_ts=0.0, poolable=True, source="custom")
        assert healthy is True
        assert requests[0]["method"] == "POST"
        assert requests[0]["json"] == {"thread_name": "Worker-1", "wait": True}
        assert requests[1]["json"] == {"thread_name": "Worker-1", "requeue": False}
        assert requests[2]["json"] == {"proxy_address": "1.1.1.1:8000", "skip_for_official": True}

    def test_request_raises_proxy_sidecar_error_when_http_fails(self) -> None:
        client = ProxySidecarClient("http://127.0.0.1:19010")
        with patch("software.network.proxy.sidecar_client.http_client.request", side_effect=RuntimeError("boom")):
            with pytest.raises(ProxySidecarError, match="代理服务连接失败"):
                client.status()

    def test_request_raises_proxy_sidecar_error_when_status_code_is_error(self) -> None:
        client = ProxySidecarClient("http://127.0.0.1:19010")
        with patch(
            "software.network.proxy.sidecar_client.http_client.request",
            return_value=_FakeResponse(status_code=502, payload={"error": "bad gateway"}),
        ):
            with pytest.raises(ProxySidecarError, match="bad gateway"):
                client.prefetch(2)


class ProxySidecarManagerTests:
    def test_resolve_sidecar_binary_path_prefers_first_existing_candidate(self) -> None:
        first = Path("D:/Projects/SurveyController/runtime/proxy_service.exe")
        second = Path("D:/Projects/SurveyController/lib/proxy_service.exe")
        with patch.object(sidecar_manager, "_candidate_binary_paths", return_value=[first, second]), patch.object(
            sidecar_manager.Path,
            "is_file",
            side_effect=[True, False],
        ):
            resolved = resolve_sidecar_binary_path()
        assert resolved == first

    def test_resolve_sidecar_binary_path_raises_when_missing(self) -> None:
        with patch.object(sidecar_manager, "_candidate_binary_paths", return_value=[Path("missing.exe")]), patch.object(
            Path,
            "is_file",
            return_value=False,
        ):
            with pytest.raises(ProxySidecarError, match="未找到 proxy_service.exe"):
                resolve_sidecar_binary_path()

    def test_ensure_proxy_sidecar_running_reuses_alive_client(self) -> None:
        fake_client = SimpleNamespace(status=lambda: {"ok": True})
        with patch.object(sidecar_manager, "_LOCK"), patch.object(sidecar_manager, "_CLIENT", fake_client), patch.object(
            sidecar_manager,
            "_PROCESS",
            SimpleNamespace(poll=lambda: None),
        ), patch.object(sidecar_manager, "_apply_runtime_config") as apply_runtime_config:
            client = sidecar_manager.ensure_proxy_sidecar_running(force_restart=False)
        assert client is fake_client
        apply_runtime_config.assert_called_once_with(fake_client)
