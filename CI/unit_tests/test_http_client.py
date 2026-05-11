from __future__ import annotations


import pytest

import software.network.http.async_client as async_http_client
import software.network.http.client as http_client


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, text: str = "ok", content: bytes = b"ok", chunks=None) -> None:
        self.status_code = status_code
        self.headers = {"x-test": "1"}
        self.text = text
        self.content = content
        self._chunks = list(chunks or [b"a", b"", b"b"])
        self.raise_called = 0

    def json(self):
        return {"ok": True}

    def raise_for_status(self) -> None:
        self.raise_called += 1

    def iter_bytes(self, chunk_size: int):
        del chunk_size
        yield from self._chunks


class _FakeStreamCtx:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.exit_calls = 0

    def __enter__(self):
        return self.response

    def __exit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb
        self.exit_calls += 1


class _FakeClient:
    def __init__(self, *, stream_ctx=None, request_response=None) -> None:
        self.stream_ctx = stream_ctx
        self.request_response = request_response or _FakeResponse()
        self.close_calls = 0
        self.request_calls: list[dict[str, object]] = []
        self.stream_calls: list[dict[str, object]] = []

    def request(self, **kwargs):
        self.request_calls.append(kwargs)
        return self.request_response

    def stream(self, **kwargs):
        self.stream_calls.append(kwargs)
        return self.stream_ctx

    def close(self) -> None:
        self.close_calls += 1


class _FakeAsyncResponse:
    def __init__(self, *, status_code: int = 200, text: str = "ok", content: bytes = b"ok", chunks=None) -> None:
        self.status_code = status_code
        self.headers = {"x-test": "1"}
        self.text = text
        self.content = content
        self._chunks = list(chunks or [b"a", b"", b"b"])
        self.raise_called = 0
        self.closed = False

    def json(self):
        return {"ok": True}

    def raise_for_status(self) -> None:
        self.raise_called += 1

    async def aiter_bytes(self, chunk_size: int):
        del chunk_size
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class _FakeAsyncStreamCtx:
    def __init__(self, response: _FakeAsyncResponse, enter_error: Exception | None = None) -> None:
        self.response = response
        self.enter_error = enter_error
        self.enter_calls = 0
        self.exit_calls = 0

    async def __aenter__(self):
        self.enter_calls += 1
        if self.enter_error is not None:
            raise self.enter_error
        return self.response

    async def __aexit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb
        self.exit_calls += 1


class _FakeAsyncClient:
    def __init__(self, *, request_response=None, stream_ctx=None, stream_error: Exception | None = None, **kwargs) -> None:
        del kwargs
        self.request_response = request_response or _FakeAsyncResponse()
        self.stream_ctx = stream_ctx or _FakeAsyncStreamCtx(_FakeAsyncResponse(), enter_error=stream_error)
        self.request_calls: list[dict[str, object]] = []
        self.stream_calls: list[dict[str, object]] = []
        self.close_calls = 0

    async def request(self, method: str, url: str, **kwargs):
        self.request_calls.append({"method": method, "url": url, **kwargs})
        return self.request_response

    def stream(self, method: str, url: str, **kwargs):
        self.stream_calls.append({"method": method, "url": url, **kwargs})
        return self.stream_ctx

    async def aclose(self) -> None:
        self.close_calls += 1


class HttpClientTests:
    def test_ensure_supported_httpx_rejects_invalid_and_old_versions(self, monkeypatch) -> None:
        monkeypatch.setattr(http_client.httpx, "__version__", "bad-version")
        with pytest.raises(RuntimeError, match="无法识别"):
            http_client._ensure_supported_httpx()

        monkeypatch.setattr(http_client.httpx, "__version__", "0.26.0")
        with pytest.raises(RuntimeError, match="版本过旧"):
            http_client._ensure_supported_httpx()

    def test_resolve_proxy_and_normalize_timeout_cover_requests_shapes(self) -> None:
        assert http_client._resolve_proxy(None, "https://example.com") == (None, True)
        assert http_client._resolve_proxy({}, "https://example.com") == (None, False)
        assert http_client._resolve_proxy("http://1.1.1.1:80", "https://example.com") == ("http://1.1.1.1:80", False)
        assert http_client._resolve_proxy({"http": "http://a", "https": "http://b"}, "https://example.com") == ("http://b", False)
        assert http_client._resolve_proxy({"http": "http://a"}, "http://example.com") == ("http://a", False)

        assert http_client._normalize_timeout(None) is None
        assert http_client._normalize_timeout(3) == 3.0
        pair_timeout = http_client._normalize_timeout((1, 2))
        assert pair_timeout.connect == 1.0
        assert pair_timeout.read == 2.0
        quad_timeout = http_client._normalize_timeout((1, 2, 3, 4))
        assert quad_timeout.pool == 4.0

    def test_stream_response_iter_content_closes_once(self) -> None:
        response = _FakeResponse(chunks=[b"a", b"", b"b"])
        stream_ctx = _FakeStreamCtx(response)
        released: list[str] = []
        wrapper = http_client._StreamResponse(response, stream_ctx, lambda: released.append("released"))

        assert list(wrapper.iter_content(chunk_size=16)) == [b"a", b"b"]
        wrapper.close()

        assert stream_ctx.exit_calls == 1
        assert released == ["released"]

    def test_sync_client_manager_acquire_release_and_close(self, monkeypatch) -> None:
        manager = http_client._SyncClientManager()
        created_clients: list[_FakeClient] = []

        def _fake_create_client(**kwargs):
            del kwargs
            client = _FakeClient()
            created_clients.append(client)
            return client

        monkeypatch.setattr(manager, "_create_client", _fake_create_client)

        key, entry = manager.acquire(proxy=None, verify=True, follow_redirects=True, trust_env=True)
        assert entry.active_requests == 1

        manager.release(key)
        assert entry.active_requests == 0

        manager.close()
        assert created_clients[0].close_calls == 1

    def test_sync_client_manager_request_releases_client_on_success_and_error(self, monkeypatch) -> None:
        manager = http_client._SyncClientManager()
        response = _FakeResponse()
        client = _FakeClient(request_response=response)
        entry = http_client._ClientEntry(client=client, last_used=0.0)
        release_calls: list[object] = []
        monkeypatch.setattr(manager, "acquire", lambda **kwargs: (http_client._ClientKey(None, True, True, True), entry))
        monkeypatch.setattr(manager, "release", lambda key: release_calls.append(key))

        resolved = manager.request("GET", "https://example.com", timeout=(1, 2))
        assert resolved is response
        assert len(release_calls) == 1

        client.request = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            manager.request("GET", "https://example.com")
        assert len(release_calls) == 2

    def test_sync_client_manager_request_stream_wraps_release(self, monkeypatch) -> None:
        manager = http_client._SyncClientManager()
        response = _FakeResponse()
        stream_ctx = _FakeStreamCtx(response)
        client = _FakeClient(stream_ctx=stream_ctx)
        entry = http_client._ClientEntry(client=client, last_used=0.0)
        release_calls: list[object] = []
        monkeypatch.setattr(manager, "acquire", lambda **kwargs: (http_client._ClientKey(None, True, True, True), entry))
        monkeypatch.setattr(manager, "release", lambda key: release_calls.append(key))

        wrapped = manager.request("GET", "https://example.com", stream=True)
        assert isinstance(wrapped, http_client._StreamResponse)
        wrapped.close()
        assert len(release_calls) == 1

    def test_prewarm_marks_prepared_and_closes_temp_client(self, monkeypatch) -> None:
        fake_client = _FakeClient()
        monkeypatch.setattr(http_client, "_PREWARMED", False)
        monkeypatch.setattr(http_client.httpx, "Client", lambda **kwargs: fake_client)

        http_client.prewarm()
        http_client.prewarm()

        assert http_client._PREWARMED is True
        assert fake_client.close_calls == 1

    @pytest.mark.asyncio
    async def test_async_stream_response_aiter_content_closes_once(self) -> None:
        response = _FakeAsyncResponse(chunks=[b"a", b"", b"b"])
        client = _FakeAsyncClient(send_response=response)
        stream_ctx = _FakeAsyncStreamCtx(response)
        wrapper = async_http_client._AsyncStreamResponse(response, stream_ctx, client)

        chunks = [chunk async for chunk in wrapper.aiter_content(chunk_size=16)]
        await wrapper.aclose()

        assert chunks == [b"a", b"b"]
        assert stream_ctx.exit_calls == 1
        assert client.close_calls == 1

    @pytest.mark.asyncio
    async def test_async_request_stream_uses_send_with_stream_and_keeps_client_open_until_close(self, monkeypatch) -> None:
        response = _FakeAsyncResponse()
        stream_ctx = _FakeAsyncStreamCtx(response)
        fake_client = _FakeAsyncClient(stream_ctx=stream_ctx)
        monkeypatch.setattr(async_http_client.httpx, "AsyncClient", lambda **kwargs: fake_client)

        wrapped = await async_http_client.request("GET", "https://example.com", stream=True, timeout=(1, 2))

        assert isinstance(wrapped, async_http_client._AsyncStreamResponse)
        assert fake_client.request_calls == []
        assert len(fake_client.stream_calls) == 1
        assert fake_client.stream_calls[0]["method"] == "GET"
        timeout = fake_client.stream_calls[0]["timeout"]
        assert timeout.connect == 1.0
        assert timeout.read == 2.0
        assert timeout.write == 2.0
        assert timeout.pool == 1.0
        assert fake_client.close_calls == 0
        assert stream_ctx.enter_calls == 1

        await wrapped.aclose()
        assert fake_client.close_calls == 1
        assert stream_ctx.exit_calls == 1

    @pytest.mark.asyncio
    async def test_async_request_stream_closes_client_when_send_fails(self, monkeypatch) -> None:
        fake_client = _FakeAsyncClient(stream_error=RuntimeError("boom"))
        monkeypatch.setattr(async_http_client.httpx, "AsyncClient", lambda **kwargs: fake_client)

        with pytest.raises(RuntimeError, match="boom"):
            await async_http_client.request("GET", "https://example.com", stream=True)

        assert fake_client.close_calls == 1
