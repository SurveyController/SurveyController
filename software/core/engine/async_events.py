"""Async runtime events and context objects."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

from software.core.task import ExecutionState


class AsyncRunContext:
    """Per-run async state shared by scheduler slots."""

    def __init__(
        self,
        *,
        state: ExecutionState,
        stop_event: asyncio.Event,
        pause_event: asyncio.Event,
        status_sink: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        self.state = state
        self.stop_event = stop_event
        self.pause_event = pause_event
        self.status_sink = status_sink

    def stop_requested(self) -> bool:
        return bool(self.stop_event.is_set())

    async def wait_if_paused(self) -> None:
        while self.pause_event.is_set() and not self.stop_event.is_set():
            await asyncio.sleep(0.1)

    def emit(self, event: dict[str, Any]) -> None:
        sink = self.status_sink
        if callable(sink):
            sink(dict(event or {}))


class ThreadEventProxy:
    """Small threading.Event-shaped proxy backed by an asyncio.Event."""

    def __init__(self, event: asyncio.Event, *, loop: asyncio.AbstractEventLoop) -> None:
        self._event = event
        self._loop = loop

    def is_set(self) -> bool:
        return bool(self._event.is_set())

    def set(self) -> None:
        if self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._event.set)

    def clear(self) -> None:
        if self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._event.clear)

    def wait(self, timeout: Optional[float] = None) -> bool:
        if self.is_set():
            return True
        waiter = threading.Event()

        async def _wait() -> bool:
            try:
                if timeout is None:
                    await self._event.wait()
                    return True
                await asyncio.wait_for(self._event.wait(), timeout=max(0.0, float(timeout)))
                return True
            except asyncio.TimeoutError:
                return bool(self._event.is_set())

        future = asyncio.run_coroutine_threadsafe(_wait(), self._loop)
        try:
            return bool(future.result())
        finally:
            waiter.set()


@dataclass(frozen=True)
class AsyncSlotResult:
    slot_id: int
    completed: bool
    error: Optional[BaseException] = None


__all__ = ["AsyncRunContext", "AsyncSlotResult", "ThreadEventProxy"]
