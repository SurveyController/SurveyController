from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from software.network.http.async_client import _AsyncClientManager


@pytest.mark.asyncio
async def test_cancelled_stream_open_releases_client_reference(monkeypatch):
    manager = _AsyncClientManager()
    opening = asyncio.Event()

    class Stream:
        async def __aenter__(self):
            opening.set()
            await asyncio.Event().wait()

    client = SimpleNamespace(
        stream=lambda *args, **kwargs: Stream(), aclose=lambda: asyncio.sleep(0)
    )
    monkeypatch.setattr(manager, "_create_client", lambda **kwargs: client)
    request = asyncio.create_task(
        manager.request("GET", "https://example.com/local.png", stream=True, proxies={})
    )
    try:
        await asyncio.wait_for(opening.wait(), timeout=1)
        assert sum(entry.active_requests for entry in manager._clients.values()) == 1
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert sum(entry.active_requests for entry in manager._clients.values()) == 0
        with manager._lock:
            assert manager._evict_oldest_idle_client_locked() is client
    finally:
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)
        await manager.close_for_loop(asyncio.get_running_loop())
