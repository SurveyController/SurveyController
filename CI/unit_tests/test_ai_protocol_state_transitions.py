from __future__ import annotations

import asyncio

import httpx
import pytest

from software.integrations.ai import protocols


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "protocol", [protocols.acall_chat_completions, protocols.acall_responses_api]
)
@pytest.mark.parametrize("status", [429, 502, 503, 504])
@pytest.mark.parametrize("recover", [True, False])
async def test_ai_http_status_retries_are_bounded(monkeypatch, protocol, status, recover):
    calls, delays = [], []

    async def post(url, **kwargs):
        calls.append((url, kwargs))
        response_status = 200 if recover and len(calls) == 2 else status
        return httpx.Response(
            response_status,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": "答案"}}], "output_text": "答案"},
        )

    async def backoff(delay):
        delays.append(delay)

    monkeypatch.setattr(protocols.http_client, "apost", post)
    monkeypatch.setattr(protocols.asyncio, "sleep", backoff)
    if recover:
        assert (
            await protocol("https://ai.example.test/generate", "key", "model", "Q", "S") == "答案"
        )
    else:
        with pytest.raises(RuntimeError, match="API 调用失败") as error:
            await protocol("https://ai.example.test/generate", "key", "model", "Q", "S")
        assert isinstance(error.value.__cause__, httpx.HTTPStatusError)
        assert error.value.__cause__.response.status_code == status

    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert delays == [1.0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "protocol", [protocols.acall_chat_completions, protocols.acall_responses_api]
)
@pytest.mark.parametrize("status", [400, 401])
async def test_ai_permanent_http_status_fails_without_retry(monkeypatch, protocol, status):
    calls = []

    async def post(url, **kwargs):
        calls.append(url)
        return httpx.Response(status, request=httpx.Request("POST", url))

    async def unexpected_backoff(delay):
        pytest.fail(f"不应等待重试: {delay}")

    monkeypatch.setattr(protocols.http_client, "apost", post)
    monkeypatch.setattr(protocols.asyncio, "sleep", unexpected_backoff)

    with pytest.raises(RuntimeError, match="API 调用失败") as error:
        await protocol("https://ai.example.test/generate", "key", "model", "Q", "S")

    assert isinstance(error.value.__cause__, httpx.HTTPStatusError)
    assert error.value.__cause__.response.status_code == status
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "protocol", [protocols.acall_chat_completions, protocols.acall_responses_api]
)
@pytest.mark.parametrize("cancel_during", ["request", "backoff"])
async def test_ai_cancellation_stops_before_another_attempt(monkeypatch, protocol, cancel_during):
    reached = asyncio.Event()
    blocked = asyncio.Event()
    calls = []

    async def post(url, **kwargs):
        calls.append(url)
        if cancel_during == "request":
            reached.set()
            await blocked.wait()
        return httpx.Response(503, request=httpx.Request("POST", url))

    async def backoff(delay):
        reached.set()
        await blocked.wait()

    monkeypatch.setattr(protocols.http_client, "apost", post)
    monkeypatch.setattr(protocols.asyncio, "sleep", backoff)
    task = asyncio.create_task(
        protocol("https://ai.example.test/generate", "key", "model", "Q", "S")
    )
    try:
        await asyncio.wait_for(reached.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(calls) == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
