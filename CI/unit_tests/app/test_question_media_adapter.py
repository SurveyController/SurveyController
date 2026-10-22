from __future__ import annotations

import asyncio
import socket

from software.app import question_media_adapter


def test_public_url_validation_rejects_non_http_and_private_hosts(monkeypatch) -> None:
    assert question_media_adapter._is_public_http_url("file:///image.png") is False
    assert question_media_adapter._is_public_http_url("http://127.0.0.1/image.png") is False

    monkeypatch.setattr(
        question_media_adapter.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0)),
        ],
    )
    assert question_media_adapter._is_public_http_url("https://example.com/image.png") is False


def test_fetch_question_media_disables_redirects_and_closes_stream(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class _Response:
        headers = {"content-length": "4"}
        closed = False

        def raise_for_status(self) -> None:
            return None

        async def aiter_content(self, chunk_size: int):
            assert chunk_size == 65536
            yield b"ab"
            yield b"cd"

        async def aclose(self) -> None:
            self.closed = True

    response = _Response()

    async def fake_get(url: str, **kwargs: object) -> _Response:
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr(question_media_adapter, "_is_public_http_url", lambda _url: True)
    monkeypatch.setattr(question_media_adapter.http_client, "aget", fake_get)

    payload = asyncio.run(question_media_adapter.fetch_question_media("https://example.com/a.png"))

    assert payload == b"abcd"
    assert calls == [
        (
            "https://example.com/a.png",
            {"timeout": 8, "proxies": {}, "allow_redirects": False, "stream": True},
        )
    ]
    assert response.closed is True


def test_fetch_question_media_rejects_declared_size_over_five_mib(monkeypatch) -> None:
    class _Response:
        headers = {"content-length": str(5 * 1024 * 1024 + 1)}
        closed = False

        def raise_for_status(self) -> None:
            return None

        def aiter_content(self, _chunk_size: int):
            raise AssertionError("oversized response must not be read")

        async def aclose(self) -> None:
            self.closed = True

    response = _Response()

    async def fake_get(_url: str, **_kwargs: object) -> _Response:
        return response

    monkeypatch.setattr(question_media_adapter, "_is_public_http_url", lambda _url: True)
    monkeypatch.setattr(question_media_adapter.http_client, "aget", fake_get)

    payload = asyncio.run(
        question_media_adapter.fetch_question_media("https://example.com/a.png")
    )

    assert payload == b""
    assert response.closed is True
