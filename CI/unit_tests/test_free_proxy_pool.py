from __future__ import annotations

import math
import re
from unittest.mock import patch

from software.network.proxy.pool.pool import _proxy_connect_probe
from software.network.proxy.pool.free_pool import (
    FREE_POOL_DEFAULT_FETCH_WORKERS,
    FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS,
    FREE_POOL_MAX_CANDIDATE_COUNT,
    FREE_POOL_MAX_VALIDATE_WORKERS,
    FREE_POOL_INITIAL_VALIDATE_ROUNDS,
    PROXY_SOURCE_FREE_POOL,
    fetch_free_proxy_batch,
    validate_proxy_leases_concurrently,
)
from software.core.task import ProxyLease
from software.network.proxy.pool.iplist_pool import fetch_iplist_proxy_batch
from software.network.proxy.pool.parsing import parse_proxy_payload


class FreeProxyPoolTests:
    def test_parse_proxy_payload_accepts_plain_text_and_json(self) -> None:
        text_payload = """
        http://127.0.0.1:8080
        127.0.0.2:8081
        socks5://127.0.0.3:1080
        """
        assert parse_proxy_payload(text_payload, allowed_schemes=("http", "https")) == [
            "http://127.0.0.1:8080",
            "http://127.0.0.2:8081",
        ]
        assert parse_proxy_payload("127.0.0.3:1080", allowed_schemes=("socks5",), default_scheme="socks5") == [
            "socks5://127.0.0.3:1080",
        ]

        json_payload = {
            "items": [
                {"ip": "127.0.0.4", "port": 8082, "protocol": "https"},
                {"proxy": "http://127.0.0.5:8083"},
            ]
        }
        assert parse_proxy_payload(__import__("json").dumps(json_payload)) == [
            "https://127.0.0.4:8082",
            "http://127.0.0.5:8083",
        ]
        ndjson_payload = '{"host":"127.0.0.6","port":1080,"type":"socks5"}\n{"ip":"127.0.0.7","port":8000}'
        assert parse_proxy_payload(ndjson_payload, allowed_schemes=("http", "socks5")) == [
            "socks5://127.0.0.6:1080",
            "http://127.0.0.7:8000",
        ]

    @patch("software.network.proxy.pool.free_pool._fetch_public_source_addresses")
    @patch("software.network.proxy.pool.free_pool.is_http_proxy_connect_responsive", return_value=True)
    def test_fetch_free_proxy_batch_returns_validated_leases(self, mock_responsive, mock_public_sources) -> None:
        mock_public_sources.return_value = ["http://127.0.0.1:8080", "http://127.0.0.2:8081"]

        leases = fetch_free_proxy_batch(
            expected_count=2,
            force_refresh=True,
            candidate_count=1200,
            fetch_workers=64,
        )

        assert len(leases) == 2
        assert {lease.address for lease in leases} == {
            "http://127.0.0.1:8080",
            "http://127.0.0.2:8081",
        }
        assert {lease.source for lease in leases} == {PROXY_SOURCE_FREE_POOL}
        assert mock_public_sources.call_args.kwargs["candidate_count"] == 1200
        assert mock_public_sources.call_args.kwargs["fetch_workers"] == 64
        assert len(mock_responsive.call_args_list) == 2 * FREE_POOL_INITIAL_VALIDATE_ROUNDS
        assert all(call.kwargs["timeout"] == FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS / 1000 for call in mock_responsive.call_args_list)
        assert all(call.kwargs["target_url"] == "" for call in mock_responsive.call_args_list)

    @patch("software.network.proxy.pool.free_pool._fetch_public_source_addresses")
    @patch("software.network.proxy.pool.free_pool.is_http_proxy_connect_responsive", return_value=True)
    def test_fetch_free_proxy_batch_scans_all_candidates_and_uses_custom_probe_timeout(self, mock_responsive, mock_public_sources) -> None:
        mock_public_sources.return_value = [
            "http://43.217.141.124:1001",
            "http://43.217.141.124:1002",
            "http://43.217.141.124:1003",
            "http://8.8.8.8:8080",
        ]

        leases = fetch_free_proxy_batch(
            expected_count=3,
            force_refresh=True,
            probe_timeout_ms=1500,
            target_url="https://v.wjx.cn/vm/demo.aspx",
        )

        assert len(leases) == 4
        assert {lease.address for lease in leases} == {
            "http://43.217.141.124:1001",
            "http://43.217.141.124:1002",
            "http://43.217.141.124:1003",
            "http://8.8.8.8:8080",
        }
        assert len(mock_responsive.call_args_list) == 4 * FREE_POOL_INITIAL_VALIDATE_ROUNDS
        assert all(call.kwargs["target_url"] == "https://v.wjx.cn/vm/demo.aspx" for call in mock_responsive.call_args_list)
        assert all(call.kwargs["timeout"] == 1.5 for call in mock_responsive.call_args_list)

    @patch("software.network.proxy.pool.iplist_pool.random.shuffle", side_effect=lambda _items: None)
    @patch("software.network.proxy.pool.iplist_pool.validate_proxy_leases_concurrently")
    @patch("software.network.proxy.pool.iplist_pool.http_client.get")
    def test_fetch_iplist_proxy_batch_uses_user_endpoint_only(self, mock_get, mock_validate, _mock_shuffle, make_http_response) -> None:
        response = make_http_response()
        response.text = "http://127.0.0.9:9000\nhttp://127.0.0.10:9001\n"
        mock_get.return_value = response
        mock_validate.side_effect = lambda leases, **_kwargs: list(leases)[:1]

        leases = fetch_iplist_proxy_batch(
            expected_count=1,
            proxy_url="https://proxy.example/get_all",
        )

        assert len(leases) == 1
        assert leases[0].address == "http://127.0.0.9:9000"
        assert leases[0].source == "iplist"
        assert [call.args[0] for call in mock_get.call_args_list] == ["https://proxy.example/get_all"]

    @patch("software.network.proxy.pool.free_pool._fetch_public_source_addresses")
    @patch("software.network.proxy.pool.free_pool.is_http_proxy_connect_responsive")
    def test_fetch_free_proxy_batch_scans_all_candidates_each_round(self, mock_responsive, mock_public_sources) -> None:
        mock_public_sources.return_value = [f"http://10.0.0.{idx}:80" for idx in range(1, 121)]
        mock_responsive.side_effect = lambda address, **_kwargs: address == "http://10.0.0.3:80"

        leases = fetch_free_proxy_batch(
            expected_count=1,
            force_refresh=True,
            max_workers=4,
        )

        assert len(leases) == 1
        assert leases[0].address == "http://10.0.0.3:80"
        assert mock_responsive.call_count == 120 * FREE_POOL_INITIAL_VALIDATE_ROUNDS

    @patch("software.network.proxy.pool.free_pool._load_local_seed_addresses", return_value=[])
    @patch("software.network.proxy.pool.free_pool._fetch_text_source_addresses")
    @patch("software.network.proxy.pool.free_pool._fetch_scdn_page_payload")
    def test_fetch_public_source_addresses_merges_scdn_and_extra_sources(
        self,
        mock_scdn_payload,
        mock_text_fetch,
        _mock_local_seed,
    ) -> None:
        from software.network.proxy.pool.free_pool import _fetch_public_source_addresses

        mock_scdn_payload.return_value = {
            "table_html": "<tr><td>1.1.1.1</td><td>80</td><td><span>HTTP</span></td></tr>"
        }
        mock_text_fetch.side_effect = lambda name, url, default_scheme="http": {
            "ProxyScrape HTTP": ["http://2.2.2.2:8080", "http://1.1.1.1:80"],
            "ProxyScrape": ["http://3.3.3.3:8080"],
        }.get(name, [])

        addresses = _fetch_public_source_addresses(candidate_count=10, rounds=1, fetch_workers=8)

        assert "http://1.1.1.1:80" in addresses
        assert "http://2.2.2.2:8080" in addresses
        assert "http://3.3.3.3:8080" in addresses
        assert len(addresses) == len(set(addresses))
        assert mock_text_fetch.call_count >= 10

    @patch("software.network.proxy.pool.free_pool._fetch_text_source_addresses")
    @patch("software.network.proxy.pool.free_pool._fetch_scdn_page_payload")
    def test_fetch_public_source_addresses_prefers_local_seed(
        self,
        mock_scdn_payload,
        mock_text_fetch,
        monkeypatch,
    ) -> None:
        from software.network.proxy.pool.free_pool import _fetch_public_source_addresses

        monkeypatch.setattr(
            "software.network.proxy.pool.free_pool._load_local_seed_addresses",
            lambda: ["socks5://127.9.0.1:1080", "http://127.9.0.2:8080"],
        )

        addresses = _fetch_public_source_addresses(candidate_count=1, rounds=1, fetch_workers=3)

        assert addresses == ["socks5://127.9.0.1:1080"]
        assert mock_scdn_payload.call_count == 0
        assert mock_text_fetch.call_count == 0

    @patch("software.network.proxy.pool.free_pool._fetch_public_source_addresses")
    @patch("software.network.proxy.pool.free_pool.is_http_proxy_connect_responsive", return_value=True)
    def test_fetch_free_proxy_batch_uses_public_source_aggregator(self, _mock_responsive, mock_public_sources) -> None:
        mock_public_sources.return_value = ["http://127.0.0.1:8080"]

        leases = fetch_free_proxy_batch(expected_count=1, force_refresh=True)

        assert leases[0].address == "http://127.0.0.1:8080"
        assert mock_public_sources.call_count == 1

    def test_parse_scdn_table_payload_reads_http_and_https_rows(self) -> None:
        from software.network.proxy.pool.free_pool import _parse_scdn_table_payload

        payload = {
            "table_html": (
                "<tr><td>1.1.1.1</td><td>80</td><td>"
                "<span>HTTP</span></td><td>香港</td></tr>"
                "<tr><td>2.2.2.2</td><td>443</td><td>"
                "<span>HTTP</span> / <span>HTTPS</span></td><td>香港</td></tr>"
                "<tr><td>3.3.3.3</td><td>1080</td><td>"
                "<span>SOCKS5</span></td><td>香港</td></tr>"
            )
        }

        assert _parse_scdn_table_payload(payload, "HTTP") == [
            "http://1.1.1.1:80",
            "http://2.2.2.2:443",
        ]
        assert _parse_scdn_table_payload(payload, "HTTPS") == [
            "http://2.2.2.2:443",
        ]

    @patch("software.network.proxy.pool.free_pool.http_client.get")
    def test_fetch_scdn_page_addresses_expands_candidate_count_to_page_requests(
        self,
        mock_get,
        make_http_response,
        monkeypatch,
    ) -> None:
        from software.network.proxy.pool.free_pool import _fetch_scdn_page_addresses

        monkeypatch.setattr("software.network.proxy.pool.free_pool._SCDN_PAGE_PROTOCOLS", ("HTTP", "HTTPS"))

        def fake_get(url, **_kwargs):
            response = make_http_response()
            protocol = "HTTPS" if "protocol=HTTPS" in url else "HTTP"
            page_match = re.search(r"page=(\d+)", url)
            page = int(page_match.group(1)) if page_match else 1
            host_octet = len(mock_get.call_args_list) + 1
            response.json.return_value = {
                "table_html": (
                    f"<tr><td>127.0.{page}.{host_octet}</td><td>80</td>"
                    f"<td><span>{protocol}</span></td></tr>"
                )
            }
            return response

        mock_get.side_effect = fake_get

        addresses = _fetch_scdn_page_addresses(candidate_count=500, fetch_workers=99)

        assert len(addresses) == math.ceil(500 / 200) * 2
        assert mock_get.call_count == math.ceil(500 / 200) * 2
        assert all("api/get_proxy.php" not in call.args[0] for call in mock_get.call_args_list)
        assert any("get_proxies.php?protocol=HTTP&per_page=100&page=1" in call.args[0] for call in mock_get.call_args_list)
        assert any(address.startswith(("http://", "https://")) for address in addresses)

    @patch("software.network.proxy.pool.free_pool.http_client.get")
    def test_fetch_scdn_page_addresses_raises_when_pages_fail(
        self,
        mock_get,
        make_http_response,
        monkeypatch,
    ) -> None:
        from software.network.proxy.pool.free_pool import _fetch_scdn_page_addresses

        monkeypatch.setattr("software.network.proxy.pool.free_pool._SCDN_PAGE_PROTOCOLS", ("HTTP", "HTTPS"))

        def fake_get(url, **_kwargs):
            response = make_http_response()
            response.raise_for_status.side_effect = RuntimeError("boom")
            return response

        mock_get.side_effect = fake_get

        try:
            _fetch_scdn_page_addresses(candidate_count=400, fetch_workers=99)
        except RuntimeError as exc:
            assert "SCDN 页面代理列表读取失败" in str(exc)
        else:
            raise AssertionError("expected SCDN page-list error")

        assert mock_get.call_count == math.ceil(400 / 200) * 2

    def test_free_pool_default_fetch_workers_is_scdn_friendly(self) -> None:
        assert FREE_POOL_DEFAULT_FETCH_WORKERS == 3
        assert FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS == 5000
        assert FREE_POOL_INITIAL_VALIDATE_ROUNDS == 3

    @patch("software.network.proxy.pool.free_pool.is_http_proxy_connect_responsive")
    def test_proxy_validation_refills_continuously_and_stops_when_ready(self, mock_responsive) -> None:
        leases = [
            ProxyLease(address=f"http://10.1.0.{idx}:80", source=PROXY_SOURCE_FREE_POOL)
            for idx in range(1, 50)
        ]
        mock_responsive.side_effect = lambda address, **_kwargs: address == "http://10.1.0.1:80"

        healthy = validate_proxy_leases_concurrently(
            leases,
            expected_count=1,
            timeout_seconds=0.1,
            max_workers=2,
            source_label="Free",
        )

        assert [lease.address for lease in healthy] == ["http://10.1.0.1:80"]
        assert mock_responsive.call_count <= 2

    @patch("software.network.proxy.pool.free_pool.is_http_proxy_connect_responsive")
    def test_proxy_validation_passes_target_url_to_probe(self, mock_responsive) -> None:
        leases = [ProxyLease(address="http://10.2.0.1:80", source=PROXY_SOURCE_FREE_POOL)]
        mock_responsive.return_value = True

        healthy = validate_proxy_leases_concurrently(
            leases,
            expected_count=1,
            timeout_seconds=0.1,
            max_workers=1,
            source_label="Free",
            target_url="https://v.wjx.cn/vm/demo.aspx",
        )

        assert len(healthy) == 1
        assert mock_responsive.call_args.kwargs["target_url"] == "https://v.wjx.cn/vm/demo.aspx"

    def test_free_pool_validate_worker_limit_allows_large_ui_values(self) -> None:
        assert FREE_POOL_MAX_VALIDATE_WORKERS == 1000

    def test_free_pool_candidate_limit_allows_large_scans(self) -> None:
        assert FREE_POOL_MAX_CANDIDATE_COUNT >= 100000

    def test_free_pool_target_limit_allows_large_user_input(self) -> None:
        from software.network.proxy.pool.free_pool import FREE_POOL_MAX_TARGET_COUNT

        assert FREE_POOL_MAX_TARGET_COUNT >= 100000


class ProxyConnectProbeTests:
    def test_connect_probe_requires_target_http_response_after_connect(self, monkeypatch) -> None:
        events: list[str] = []

        class FakeSocket:
            def __init__(self) -> None:
                self.recv_count = 0

            def settimeout(self, _timeout) -> None:
                pass

            def sendall(self, data: bytes) -> None:
                events.append(data.decode("ascii", errors="ignore").splitlines()[0])

            def recv(self, _size: int) -> bytes:
                self.recv_count += 1
                if self.recv_count == 1:
                    return b"HTTP/1.1 200 Connection Established\r\n\r\n"
                return b"HTTP/1.1 403 Forbidden\r\n\r\n"

            def close(self) -> None:
                events.append("close")

        fake_socket = FakeSocket()
        monkeypatch.setattr("software.network.proxy.pool.pool.socket.create_connection", lambda *_args, **_kwargs: fake_socket)

        assert _proxy_connect_probe(
            "http://127.0.0.1:8080",
            target_url="http://v.wjx.cn/vm/demo.aspx",
            timeout=0.1,
            log_failures=False,
            log_success=False,
        )
        assert events[0] == "CONNECT v.wjx.cn:80 HTTP/1.1"
        assert events[1] == "HEAD /vm/demo.aspx HTTP/1.1"

    def test_connect_probe_rejects_connect_only_without_origin_response(self, monkeypatch) -> None:
        class FakeSocket:
            def __init__(self) -> None:
                self.recv_count = 0

            def settimeout(self, _timeout) -> None:
                pass

            def sendall(self, _data: bytes) -> None:
                pass

            def recv(self, _size: int) -> bytes:
                self.recv_count += 1
                if self.recv_count == 1:
                    return b"HTTP/1.1 200 Connection Established\r\n\r\n"
                return b""

            def close(self) -> None:
                pass

        monkeypatch.setattr("software.network.proxy.pool.pool.socket.create_connection", lambda *_args, **_kwargs: FakeSocket())

        assert not _proxy_connect_probe(
            "http://127.0.0.1:8080",
            target_url="http://v.wjx.cn/vm/demo.aspx",
            timeout=0.1,
            log_failures=False,
            log_success=False,
        )

    def test_socks5_probe_connects_to_target_and_checks_origin_response(self, monkeypatch) -> None:
        sent: list[bytes] = []

        class FakeSocksSocket:
            def __init__(self) -> None:
                self.recv_chunks = [
                    b"\x05\x00",
                    b"\x05\x00\x00\x01",
                    b"\x00\x00\x00\x00",
                    b"\x00\x00",
                    b"HTTP/1.1 204 No Content\r\n\r\n",
                ]

            def settimeout(self, _timeout) -> None:
                pass

            def sendall(self, data: bytes) -> None:
                sent.append(data)

            def recv(self, size: int) -> bytes:
                if not self.recv_chunks:
                    return b""
                chunk = self.recv_chunks.pop(0)
                if len(chunk) > size:
                    self.recv_chunks.insert(0, chunk[size:])
                    return chunk[:size]
                return chunk

            def close(self) -> None:
                pass

        monkeypatch.setattr("software.network.proxy.pool.pool.socket.create_connection", lambda *_args, **_kwargs: FakeSocksSocket())

        assert _proxy_connect_probe(
            "socks5://127.0.0.1:1080",
            target_url="http://v.wjx.cn/vm/demo.aspx",
            timeout=0.1,
            log_failures=False,
            log_success=False,
        )
        assert sent[0] == b"\x05\x01\x00"
        assert sent[1].startswith(b"\x05\x01\x00\x03\x08v.wjx.cn\x00P")
        assert sent[2].startswith(b"HEAD /vm/demo.aspx HTTP/1.1")
