"""异步运行时的停止信号等待工具。"""

from __future__ import annotations

import asyncio
from typing import Any, Optional


def is_stop_requested(stop_signal: Any) -> bool:
    if stop_signal is None:
        return False
    checker = getattr(stop_signal, "is_set", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    return False


def _resolve_async_event(stop_signal: Any) -> Optional[asyncio.Event]:
    if isinstance(stop_signal, asyncio.Event):
        return stop_signal
    event = getattr(stop_signal, "_event", None)
    if isinstance(event, asyncio.Event):
        return event
    return None


async def sleep_or_stop(stop_signal: Any, seconds: float) -> bool:
    delay = max(0.0, float(seconds or 0.0))
    if delay <= 0:
        return is_stop_requested(stop_signal)

    async_event = _resolve_async_event(stop_signal)
    if async_event is not None:
        if async_event.is_set():
            return True
        try:
            await asyncio.wait_for(async_event.wait(), timeout=delay)
            return True
        except asyncio.TimeoutError:
            return bool(async_event.is_set())

    if stop_signal is None:
        await asyncio.sleep(delay)
        return False

    waiter = getattr(stop_signal, "wait", None)
    if callable(waiter):
        try:
            return bool(await asyncio.to_thread(waiter, delay))
        except Exception:
            pass

    await asyncio.sleep(delay)
    return is_stop_requested(stop_signal)


__all__ = ["is_stop_requested", "sleep_or_stop"]
