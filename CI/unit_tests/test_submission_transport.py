from __future__ import annotations

import asyncio
from functools import partial

import httpx
import pytest

from software.network import http as http_client
from software.network.http import submission
from software.network.http.async_client import async_client_scope


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scheme", "proxy_reply", "method", "error_type", "connection_failure"),
    [
        ("https", b"", b"CONNECT", httpx.ReadTimeout, True),
        (
            "https",
            b"HTTP/1.1 631 Internal Server Error\r\nContent-Length: 0\r\n\r\n",
            b"CONNECT",
            httpx.ProxyError,
            True,
        ),
        ("http", b"", b"POST", httpx.ReadTimeout, False),
    ],
)
async def test_submission_transport_classifies_at_post_boundary(
    monkeypatch, scheme, proxy_reply, method, error_type, connection_failure
) -> None:
    monkeypatch.setattr(
        submission, "_SUBMISSION_TIMEOUT", httpx.Timeout(connect=2, read=0.25, write=2, pool=2)
    )
    requests = []
    drained = asyncio.Event()

    async def handle(reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            requests.append(headers.split(b" ", 1)[0])
            if proxy_reply:
                writer.write(proxy_reply)
                await writer.drain()
            await reader.read()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            finally:
                drained.set()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    post = partial(
        http_client.apost,
        proxies=f"http://127.0.0.1:{port}",
        allow_redirects=False,
    )
    expected = submission.SubmissionConnectionError if connection_failure else error_type
    async with server, async_client_scope():
        with pytest.raises(expected) as error:
            await submission.post_submission(post, f"{scheme}://survey.example.test/submit")
        assert requests == [method]
        if connection_failure:
            assert isinstance(error.value.__cause__, error_type)
        await asyncio.wait_for(drained.wait(), timeout=2)
